"""Application factory: builds and configures the Flask app."""
import click
from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import db
from .auth import generate_csrf_token, get_current_user, hash_password, is_active_guest
from .config import Config
from .validators import ValidationError

# Rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # Disable rate limiting in test mode by default
    if app.config.get("TESTING", False):
        app.config["RATE_LIMIT_ENABLED"] = False

    # Validate production configuration if running in production or explicit Turso mode
    # (unless explicitly in testing mode)
    if not app.config.get("TESTING", False):
        if app.config.get("IS_PRODUCTION") or app.config.get("DATABASE_MODE") == "turso":
            Config.validate_production_config(app.config)

    # Initialize database lifecycle and dev/test schema
    db.init_db(app)

    # Register API blueprint
    from .api import bp as api_bp
    app.register_blueprint(api_bp)

    # Register Web Views blueprint
    from .views import views_bp
    app.register_blueprint(views_bp)

    # Initialize rate limiter (after blueprints are registered)
    _init_rate_limiter(app)

    # Global template context processor
    @app.context_processor
    def inject_template_globals():
        return {
            "current_user": get_current_user(),
            "is_guest": is_active_guest(),
            "csrf_token": generate_csrf_token(),
            "base_currency": app.config.get("BASE_CURRENCY", "INR(₹)"),
        }

    # CLI command: init-db
    @app.cli.command("init-db")
    def init_db_command():
        """Initialize the database tables and indexes safely."""
        with app.app_context():
            db.init_schema()
            mode = app.config.get("DATABASE_MODE", "sqlite")
            print(f"Database schema initialized successfully for mode: {mode}.")

    # CLI command: create-admin (without hardcoded passwords)
    @app.cli.command("create-admin")
    @click.option("--name", prompt="Admin Full Name", help="Full name of administrator")
    @click.option("--email", prompt="Admin Email", help="Email of administrator")
    @click.password_option(prompt="Admin Password", confirmation_prompt=True, help="Password for administrator")
    def create_admin_command(name, email, password):
        """Create a new administrator account safely via CLI."""
        with app.app_context():
            clean_email = email.strip().lower()
            existing = db.get_user_by_email(clean_email)
            if existing:
                print(f"Error: An account with email '{clean_email}' already exists.")
                return

            if len(password) < 8:
                print("Error: Password must be at least 8 characters long.")
                return

            p_hash = hash_password(password)
            user_id = db.create_user(
                full_name=name.strip(),
                email=clean_email,
                password_hash=p_hash,
                role="admin",
                is_active=1,
            )
            print(f"Administrator account '{clean_email}' (ID: {user_id}) created successfully.")

    @app.errorhandler(ValidationError)
    def handle_validation_error(err):
        if request.path.startswith("/api/"):
            return jsonify(error=str(err)), 400
        return render_template("login.html", error=str(err)), 400

    @app.errorhandler(403)
    def handle_forbidden(err):
        if request.path.startswith("/api/"):
            return jsonify(error="Access denied. Insufficient permissions."), 403
        return render_template("login.html", error="Access forbidden: You do not have permission to view this resource."), 403

    @app.errorhandler(Exception)
    def handle_unexpected_error(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return err

        msg = str(err)
        token = app.config.get("TURSO_AUTH_TOKEN", "")
        if token and token in msg:
            msg = msg.replace(token, "[REDACTED]")

        if "turso" in msg.lower() or "database" in msg.lower() or "connect" in msg.lower():
            if request.path.startswith("/api/"):
                return jsonify(error="Database service is currently unavailable. Please check your configuration."), 503
            return render_template("login.html", error="Database service is currently unavailable. Please try again later."), 503

        if request.path.startswith("/api/"):
            return jsonify(error="An internal server error occurred."), 500
        return render_template("login.html", error="An internal server error occurred. Please try again."), 500

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
        )
        return response

    return app


def _init_rate_limiter(app):
    """Initialize Flask-Limiter with appropriate storage backend and limits."""
    if not app.config.get("RATE_LIMIT_ENABLED", True):
        return

    storage_url = app.config.get("RATE_LIMIT_STORAGE_URL", "")
    trusted_proxy = app.config.get("RATE_LIMIT_TRUSTED_PROXY", False)

    # Configure key function with proxy support
    def get_client_ip():
        if trusted_proxy:
            # Trust X-Forwarded-For header only when behind known proxy
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return get_remote_address()

    # Configure storage backend
    if storage_url:
        # Redis backend for multi-instance deployments
        limiter = Limiter(
            key_func=get_client_ip,
            app=app,
            storage_uri=storage_url,
            default_limits=["200 per minute", "1000 per hour"],
            strategy="fixed-window",
        )
    else:
        # In-memory backend for development/single instance
        limiter = Limiter(
            key_func=get_client_ip,
            app=app,
            default_limits=["200 per minute", "1000 per hour"],
            strategy="fixed-window",
        )

    # Apply specific limits to sensitive endpoints
    limiter.limit("5 per minute")(app.view_functions.get("api.login_api"))
    limiter.limit("3 per minute")(app.view_functions.get("api.register_api"))
    limiter.limit("10 per minute")(app.view_functions.get("views.login"))
    limiter.limit("5 per minute")(app.view_functions.get("views.register"))
    limiter.limit("10 per minute")(app.view_functions.get("views.start_guest"))
    limiter.limit("60 per minute")(app.view_functions.get("api.list_transactions"))
    limiter.limit("60 per minute")(app.view_functions.get("api.guest_list_transactions"))
    limiter.limit("10 per minute")(app.view_functions.get("api.import_user_excel"))
    limiter.limit("10 per minute")(app.view_functions.get("api.guest_import_excel"))
    limiter.limit("30 per minute")(app.view_functions.get("api.export_user_excel"))
    limiter.limit("30 per minute")(app.view_functions.get("api.guest_export_excel"))
    limiter.limit("30 per minute")(app.view_functions.get("api.download_excel_template"))
    limiter.limit("30 per minute")(app.view_functions.get("api.guest_excel_template"))

    # Custom 429 handler
    @app.errorhandler(429)
    def handle_rate_limit_exceeded(err):
        retry_after = err.description if hasattr(err, 'description') else "60"
        if request.path.startswith("/api/"):
            return jsonify(
                error="Rate limit exceeded. Please slow down your requests.",
                retry_after=retry_after
            ), 429, {"Retry-After": str(retry_after)}
        return render_template(
            "login.html",
            error="Too many requests. Please wait a moment and try again."
        ), 429, {"Retry-After": str(retry_after)}

    return limiter
