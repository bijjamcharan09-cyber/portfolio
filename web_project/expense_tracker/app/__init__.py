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

    db.init_db(app)

    from .api import bp
    app.register_blueprint(bp)

    @app.get("/")
    def index():
        return render_template("index.html", base_currency=app.config["BASE_CURRENCY"])

    @app.errorhandler(ValidationError)
    def handle_validation_error(err):
        return jsonify(error=str(err)), 400

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'"
        )
        return response

    return app
