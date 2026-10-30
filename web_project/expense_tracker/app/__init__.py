"""Application factory: builds and configures the Flask app."""
from flask import Flask, jsonify, render_template

from . import db
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

    from .api import bp
    app.register_blueprint(bp)

    @app.cli.command("init-db")
    def init_db_command():
        """Initialize the database tables and indexes safely."""
        with app.app_context():
            db.init_schema()
            mode = app.config.get("DATABASE_MODE", "sqlite")
            print(f"Database schema initialized successfully for mode: {mode}.")

    @app.get("/")
    @app.get("/api/index")
    @app.get("/api/index.py")
    def index():
        return render_template("index.html", base_currency=app.config["BASE_CURRENCY"])

    @app.errorhandler(ValidationError)
    def handle_validation_error(err):
        return jsonify(error=str(err)), 400

    @app.errorhandler(RuntimeError)
    def handle_database_error(err):
        msg = str(err)
        # Redact any auth token if accidentally in error string
        token = app.config.get("TURSO_AUTH_TOKEN", "")
        if token and token in msg:
            msg = msg.replace(token, "[REDACTED]")
        if "turso" in msg.lower() or "database" in msg.lower() or "connect" in msg.lower():
            return jsonify(error="Database service is currently unavailable. Please check your configuration."), 503
        return jsonify(error=msg), 500

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'"
        )
        return response

    return app
