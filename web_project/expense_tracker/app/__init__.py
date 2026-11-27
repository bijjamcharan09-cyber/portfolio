"""Application factory: builds and configures the Flask app."""
import click
import logging
import sys
import uuid
from flask import Flask, jsonify, redirect, render_template, request, url_for, g

from . import db
from .auth import generate_csrf_token, get_current_user, hash_password, is_active_guest
from .config import Config
from .validators import ValidationError

# Rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Sentry (optional)
try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # Initialize structured logging
    _init_logging(app)

    # Initialize Sentry (optional, non-blocking)
    _init_sentry(app)

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

    # Initialize lightweight request & SQL performance instrumentation
    from . import perf
    perf.init_perf(app)

    # Add request ID middleware for tracing
    @app.before_request
    def inject_request_id():
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]

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

    # CLI command: migrate-db
    @app.cli.command("migrate-db")
    @click.option("--dry-run", is_flag=True, help="Show pending migrations without applying")
    @click.option("--target", help="Run migrations up to this version (inclusive)")
    def migrate_db_command(dry_run, target):
        """Run pending database migrations."""
        from scripts.run_migrations import run_migrations
        result = run_migrations(
            database_mode=app.config.get("DATABASE_MODE"),
            database_path=app.config.get("DATABASE_PATH"),
            turso_url=app.config.get("TURSO_DATABASE_URL"),
            turso_token=app.config.get("TURSO_AUTH_TOKEN"),
            dry_run=dry_run,
            target_version=target
        )
        if result["success"]:
            if dry_run:
                print(f"[OK] Dry run: {len(result.get('pending', []))} pending migrations")
            else:
                print(f"[OK] {result.get('message', 'Migrations applied successfully')}")
        else:
            print(f"[ERROR] {result['error']}")
            if "applied" in result:
                print(f"  Migrations applied before failure: {result['applied']}")

    # CLI command: migrate-status
    @app.cli.command("migrate-status")
    def migrate_status_command():
        """Show migration status."""
        from scripts.run_migrations import status
        result = status(
            database_mode=app.config.get("DATABASE_MODE"),
            database_path=app.config.get("DATABASE_PATH"),
            turso_url=app.config.get("TURSO_DATABASE_URL"),
            turso_token=app.config.get("TURSO_AUTH_TOKEN")
        )
        if result["success"]:
            print("Migration Status:")
            for m in result["migrations"]:
                status_icon = "[OK]" if m["status"] == "applied" else "[!]" if m["status"] == "rolled_back" else "[..]"
                print(f"  {status_icon} {m['version']}: {m['name']} ({m['status']})")
        else:
            print(f"[ERROR] {result['error']}")

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

    # CLI command: process-recurring
    @app.cli.command("process-recurring")
    @click.option("--date", default=None, help="Date to process for (YYYY-MM-DD), defaults to today")
    @click.option("--user-id", type=int, default=None, help="Specific user ID to process (default: all users)")
    def process_recurring_command(date, user_id):
        """Process due recurring transactions and generate actual transactions."""
        from datetime import date as dt_date
        with app.app_context():
            if date:
                try:
                    process_date = dt_date.fromisoformat(date)
                except ValueError:
                    print("Error: Invalid date format. Use YYYY-MM-DD.")
                    return
            else:
                process_date = dt_date.today()

            if user_id:
                users_to_process = [db.get_user_by_id(user_id)]
                if not users_to_process[0]:
                    print(f"Error: User with ID {user_id} not found.")
                    return
            else:
                # Get all active users
                conn = db.get_db()
                users_to_process = conn.execute(
                    "SELECT id, email FROM users WHERE is_active = 1"
                ).fetchall()

            total_generated = 0
            for user in users_to_process:
                uid = user["id"]
                generated = db.process_due_recurring_for_user(uid, process_date)
                for item in generated:
                    total_generated += 1
                    print(f"  Generated transaction {item['transaction_id']} for user {uid} (recurring: {item['recurring_id']})")

            print(f"Processed recurring transactions for {process_date}: {total_generated} transactions generated.")

    # CLI command: check-notifications
    @app.cli.command("check-notifications")
    @click.option("--user-id", type=int, default=None, help="Specific user ID to check (default: all users)")
    def check_notifications_command(user_id):
        """Check and create all types of notifications for users."""
        with app.app_context():
            if user_id:
                users_to_check = [db.get_user_by_id(user_id)]
                if not users_to_check[0]:
                    print(f"Error: User with ID {user_id} not found.")
                    return
            else:
                conn = db.get_db()
                users_to_check = conn.execute(
                    "SELECT id, email FROM users WHERE is_active = 1"
                ).fetchall()

            total_notifications = 0
            for user in users_to_check:
                uid = user["id"]
                print(f"Checking notifications for user {uid}...")

                # Check budget notifications
                budget_notifs = db.check_budget_notifications(uid)
                total_notifications += len(budget_notifs)
                if budget_notifs:
                    print(f"  Budget notifications: {len(budget_notifs)}")

                # Check recurring transaction notifications
                recurring_notifs = db.check_recurring_notifications(uid)
                total_notifications += len(recurring_notifs)
                if recurring_notifs:
                    print(f"  Recurring notifications: {len(recurring_notifs)}")

                # Check subscription renewal notifications
                subscription_notifs = db.check_subscription_notifications(uid)
                total_notifications += len(subscription_notifs)
                if subscription_notifs:
                    print(f"  Subscription notifications: {len(subscription_notifs)}")

                # Check goal milestone notifications
                goal_notifs = db.check_goal_notifications(uid)
                total_notifications += len(goal_notifs)
                if goal_notifs:
                    print(f"  Goal notifications: {len(goal_notifs)}")

            print(f"Total notifications created: {total_notifications}")

    # CLI command: process-all (runs both recurring and notifications)
    @app.cli.command("process-all")
    @click.option("--date", default=None, help="Date to process for (YYYY-MM-DD), defaults to today")
    @click.option("--user-id", type=int, default=None, help="Specific user ID to process (default: all users)")
    def process_all_command(date, user_id):
        """Run both recurring transaction processing and notification checks."""
        from datetime import date as dt_date
        with app.app_context():
            if date:
                try:
                    process_date = dt_date.fromisoformat(date)
                except ValueError:
                    print("Error: Invalid date format. Use YYYY-MM-DD.")
                    return
            else:
                process_date = dt_date.today()

            if user_id:
                users_to_process = [db.get_user_by_id(user_id)]
                if not users_to_process[0]:
                    print(f"Error: User with ID {user_id} not found.")
                    return
            else:
                conn = db.get_db()
                users_to_process = conn.execute(
                    "SELECT id, email FROM users WHERE is_active = 1"
                ).fetchall()

            # Process recurring transactions
            print(f"Processing recurring transactions for {process_date}...")
            total_generated = 0
            for user in users_to_process:
                uid = user["id"]
                generated = db.process_due_recurring_for_user(uid, process_date)
                for item in generated:
                    total_generated += 1
                    print(f"  Generated transaction {item['transaction_id']} for user {uid} (recurring: {item['recurring_id']})")

            print(f"  Recurring transactions generated: {total_generated}")

            # Check notifications
            print(f"Checking notifications for {process_date}...")
            total_notifications = 0
            for user in users_to_process:
                uid = user["id"]
                budget_notifs = db.check_budget_notifications(uid)
                total_notifications += len(budget_notifs)
                if budget_notifs:
                    print(f"  Budget notifications for user {uid}: {len(budget_notifs)}")

                recurring_notifs = db.check_recurring_notifications(uid)
                total_notifications += len(recurring_notifs)
                if recurring_notifs:
                    print(f"  Recurring notifications for user {uid}: {len(recurring_notifs)}")

                subscription_notifs = db.check_subscription_notifications(uid)
                total_notifications += len(subscription_notifs)
                if subscription_notifs:
                    print(f"  Subscription notifications for user {uid}: {len(subscription_notifs)}")

                goal_notifs = db.check_goal_notifications(uid)
                total_notifications += len(goal_notifs)
                if goal_notifs:
                    print(f"  Goal notifications for user {uid}: {len(goal_notifs)}")

            print(f"Total notifications created: {total_notifications}")
            print(f"Done! Generated {total_generated} transactions and {total_notifications} notifications.")

    @app.errorhandler(ValidationError)
    def handle_validation_error(err):
        app.logger.warning("Validation error: %s", err, extra={"path": request.path, "method": request.method})
        if request.path.startswith("/api/"):
            return jsonify(error=str(err)), 400
        return render_template("login.html", error=str(err)), 400

    @app.errorhandler(403)
    def handle_forbidden(err):
        app.logger.warning("Forbidden access: %s", err, extra={"path": request.path, "method": request.method, "user_id": getattr(g, "current_user", {}).get("id") if hasattr(g, "current_user") else None})
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

        # Log the full error with context
        user_id = None
        if hasattr(g, "current_user") and g.current_user:
            try:
                user_id = g.current_user["id"]
            except (TypeError, KeyError):
                user_id = None

        app.logger.error(
            "Unhandled exception: %s",
            msg,
            extra={
                "path": request.path,
                "method": request.method,
                "user_id": user_id,
                "request_id": getattr(g, "request_id", None),
            },
            exc_info=True
        )

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
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
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


def _init_logging(app):
    """Configure structured logging with request context."""
    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    log_format = app.config.get("LOG_FORMAT", "json")

    # Clear existing handlers
    logging.getLogger().handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if log_format == "json":
        # JSON formatter for structured logging
        import json
        from datetime import datetime, timezone

        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_obj = {
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                # Add request context if available
                if hasattr(g, "request_id"):
                    log_obj["request_id"] = g.request_id
                if hasattr(g, "current_user") and g.current_user:
                    try:
                        log_obj["user_id"] = g.current_user["id"]
                    except (TypeError, KeyError):
                        log_obj["user_id"] = None
                # Add extra fields from record
                for key, value in record.__dict__.items():
                    if key not in ["name", "msg", "args", "levelname", "levelno", "pathname",
                                   "filename", "module", "lineno", "funcName", "created",
                                   "msecs", "relativeCreated", "thread", "threadName",
                                   "processName", "process", "message", "exc_info", "exc_text",
                                   "stack_info", "request_id", "user_id"]:
                        log_obj[key] = value
                return json.dumps(log_obj, default=str)

        handler.setFormatter(JsonFormatter())
    else:
        # Text formatter for development
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s [request_id=%(request_id)s]"
        )
        handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    # Set specific loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING if app.config.get("IS_PRODUCTION") else logging.INFO)
    logging.getLogger("flask_limiter").setLevel(logging.WARNING)

    # Add request_id filter for non-JSON logs
    class RequestIdFilter(logging.Filter):
        def filter(self, record):
            if not hasattr(record, "request_id"):
                try:
                    record.request_id = getattr(g, "request_id", "-")
                except RuntimeError:
                    # Outside of request context
                    record.request_id = "-"
            return True

    handler.addFilter(RequestIdFilter())

    return handler


def _init_sentry(app):
    """Initialize Sentry SDK if configured (non-blocking)."""
    dsn = app.config.get("SENTRY_DSN", "").strip()
    if not dsn or not SENTRY_AVAILABLE:
        return

    try:
        sentry_logging = LoggingIntegration(
            level=logging.INFO,
            event_level=logging.ERROR
        )
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration(), sentry_logging],
            traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.1),
            profiles_sample_rate=app.config.get("SENTRY_PROFILES_SAMPLE_RATE", 0.1),
            environment=app.config.get("FLASK_ENV", "development"),
            # Scrub sensitive data
            before_send=_sentry_before_send,
        )
        app.logger.info("Sentry initialized successfully")
    except Exception as exc:
        # Never let Sentry init failure break the app
        app.logger.warning("Sentry initialization failed: %s", exc)


def _sentry_before_send(event, hint):
    """Scrub sensitive data from Sentry events."""
    # Remove auth tokens, passwords, session cookies
    if "request" in event:
        headers = event["request"].get("headers", {})
        sensitive_headers = ["authorization", "cookie", "x-csrf-token", "x-forwarded-for"]
        for h in sensitive_headers:
            if h in headers:
                headers[h] = "[REDACTED]"

        # Scrub URL query params that might contain tokens
        url = event["request"].get("url", "")
        if "?" in url:
            base, query = url.split("?", 1)
            scrubbed_params = []
            for param in query.split("&"):
                if "=" in param:
                    key, val = param.split("=", 1)
                    if any(s in key.lower() for s in ["token", "password", "secret", "key", "auth"]):
                        scrubbed_params.append(f"{key}=[REDACTED]")
                    else:
                        scrubbed_params.append(param)
                else:
                    scrubbed_params.append(param)
            event["request"]["url"] = base + "?" + "&".join(scrubbed_params)

    return event
