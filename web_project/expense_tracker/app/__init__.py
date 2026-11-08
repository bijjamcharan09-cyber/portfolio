"""Application factory: builds and configures the Flask app."""
import click
from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import db
from .auth import generate_csrf_token, get_current_user, hash_password
from .config import Config
from .validators import ValidationError


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

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

    # Global template context processor
    @app.context_processor
    def inject_template_globals():
        return {
            "current_user": get_current_user(),
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
