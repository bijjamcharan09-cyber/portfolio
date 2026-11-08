"""Authentication and Role-Based Access Control (RBAC) helpers.
Provides login/role decorators, password hashing, and session management.
"""
from functools import wraps
import secrets

from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


def hash_password(password: str) -> str:
    """Hash password using Werkzeug security utilities (scrypt/pbkdf2)."""
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against stored hash."""
    return check_password_hash(password_hash, password)


def login_user(user: dict):
    """Establish a secure session for the given user, preventing session fixation."""
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["user_name"] = user["full_name"]
    session["user_email"] = user["email"]
    session["user_role"] = user["role"]
    g.current_user = user


def logout_user():
    """Clear the session completely upon logout."""
    session.clear()
    g.current_user = None


def get_current_user():
    """Retrieve the current logged-in user record from the database."""
    if hasattr(g, "current_user") and g.current_user is not None:
        return g.current_user

    user_id = session.get("user_id")
    if not user_id:
        g.current_user = None
        return None

    user = db.get_user_by_id(user_id)
    if not user or not user["is_active"]:
        logout_user()
        g.current_user = None
        return None

    g.current_user = user
    return user


def login_required(f):
    """Ensure the user is authenticated and active before accessing the route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify(error="Authentication required. Please log in."), 401
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)

    return decorated_function


def role_required(*allowed_roles):
    """Enforce role-based authorization for the specified roles."""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user or user["role"] not in allowed_roles:
                if request.path.startswith("/api/"):
                    return jsonify(error="Access denied. Insufficient permissions."), 403
                return jsonify(error="Access forbidden: You do not have permission to view this resource."), 403
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_required(f):
    """Convenience decorator ensuring only active administrators can access."""
    return role_required("admin")(f)


# ============================================================================
# CSRF Protection Helpers
# ============================================================================

def generate_csrf_token() -> str:
    """Generate or retrieve a per-session CSRF token."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def validate_csrf():
    """Validate CSRF token for mutating requests."""
    # Skip CSRF check in testing mode or for GET/HEAD/OPTIONS
    if current_app.config.get("TESTING", False):
        return True
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True

    expected = session.get("_csrf_token")
    if not expected:
        return False

    received = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
        or (request.is_json and request.get_json(silent=True) and request.get_json(silent=True).get("csrf_token"))
    )

    return bool(received and secrets.compare_digest(str(received), str(expected)))
