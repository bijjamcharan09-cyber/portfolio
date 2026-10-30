"""Vercel Serverless Function entry point for Expense Tracker."""
import sys
import urllib.parse
from pathlib import Path

# Ensure application root directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import create_app


class VercelPathMiddleware:
    """WSGI middleware ensuring Flask receives the original request path on Vercel.

    When Vercel rewrites routes to /api/index, it supplies the intended route
    via the __route__ query parameter or passes /api/index for the root view.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        qs = environ.get("QUERY_STRING", "")
        if "__route__" in qs:
            params = urllib.parse.parse_qs(qs, keep_blank_values=True)
            route = params.pop("__route__", [None])[0]
            if route:
                clean_route = route.split("?")[0]
                environ["PATH_INFO"] = clean_route if clean_route.startswith("/") else f"/{clean_route}"
                environ["QUERY_STRING"] = urllib.parse.urlencode(
                    [(k, v) for k, vs in params.items() for v in vs]
                )
        elif environ.get("PATH_INFO") in ("/api/index", "/api/index.py"):
            environ["PATH_INFO"] = "/"

        return self.wsgi_app(environ, start_response)


app = create_app()
app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
handler = app
