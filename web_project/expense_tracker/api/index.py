"""Vercel Serverless Function entry point for Expense Tracker."""
import sys
from pathlib import Path

# Ensure application root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import create_app


class VercelPathMiddleware:
    """WSGI middleware ensuring Flask receives the original request path on Vercel.

    When Vercel rewrites routes to a serverless function (e.g. /api/index),
    the internal WSGI PATH_INFO may reflect the rewrite destination instead
    of the original client URL. Vercel provides the client's actual path in
    headers such as HTTP_X_MATCHED_PATH and HTTP_X_VERCEL_MATCHED_PATH.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        matched_path = environ.get("HTTP_X_MATCHED_PATH") or environ.get("HTTP_X_VERCEL_MATCHED_PATH")
        if matched_path:
            # Strip query string from matched_path if present (Flask expects path only in PATH_INFO)
            clean_path = matched_path.split("?")[0]
            environ["PATH_INFO"] = clean_path
        elif environ.get("PATH_INFO") in ("/api/index", "/api/index.py"):
            environ["PATH_INFO"] = "/"

        return self.wsgi_app(environ, start_response)


app = create_app()
app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
handler = app
