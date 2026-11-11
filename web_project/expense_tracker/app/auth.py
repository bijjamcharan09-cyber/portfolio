"""Authentication and Role-Based Access Control (RBAC) helpers.
Provides login/role decorators, password hashing, and session management.
"""
from functools import wraps
import secrets
import time
from datetime import datetime, timezone

from flask import current_app, g, jsonify, redirect, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
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
            return redirect(url_for("views.login", next=request.path))
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


# ============================================================================
# Guest Mode Trial & Lifecycle Helpers
# ============================================================================

GUEST_TRIAL_COOKIE_NAME = "guest_trial_record"


def get_guest_trial_serializer() -> URLSafeTimedSerializer:
    """Return timed serializer for signing tamper-proof guest trial tracking cookies."""
    secret = current_app.config.get("SECRET_KEY", "fallback-secret")
    return URLSafeTimedSerializer(secret, salt="guest-trial-auth-v1")


def is_guest_trial_used(req=None) -> bool:
    """Verify if the one-time guest trial cookie has already been recorded on this browser.

    Limitation Note: While this signed cookie prevents normal browser reuse and resists tampering,
    clearing browser cookies/storage or switching browsers/devices will naturally allow a fresh trial.
    Invasive device fingerprinting is explicitly avoided per security guidelines.
    """
    r = req or request
    token = r.cookies.get(GUEST_TRIAL_COOKIE_NAME)
    if not token:
        return False

    serializer = get_guest_trial_serializer()
    try:
        data = serializer.loads(token)
        return bool(data.get("trial_used"))
    except (BadSignature, SignatureExpired, Exception):
        return False


def mark_guest_trial_used(response, guest_id: str):
    """Set a signed, persistent cookie recording that this browser has consumed its guest trial."""
    serializer = get_guest_trial_serializer()
    token = serializer.dumps({
        "trial_used": True,
        "guest_id": guest_id,
        "issued_at": time.time(),
    })
    is_secure = bool(current_app.config.get("SESSION_COOKIE_SECURE", False))
    response.set_cookie(
        GUEST_TRIAL_COOKIE_NAME,
        token,
        max_age=365 * 24 * 3600,  # 1 year
        httponly=True,
        samesite="Lax",
        secure=is_secure,
    )


def start_guest_session(guest_id: str):
    """Initialize an isolated guest session in the Flask session cookie."""
    session.clear()
    session.permanent = True
    session["is_guest"] = True
    session["guest_id"] = guest_id
    session["guest_role"] = "guest"
    session["guest_created_at"] = datetime.now(timezone.utc).isoformat()
    session["guest_last_active"] = time.time()


def logout_guest():
    """Terminate active guest session and purge temporary data."""
    guest_id = session.get("guest_id")
    if guest_id:
        try:
            db.delete_guest_data(guest_id)
        except Exception:
            pass
    session.clear()


def is_active_guest() -> bool:
    """Check if the current request belongs to an active, non-expired guest session."""
    if not session.get("is_guest") or not session.get("guest_id"):
        return False

    timeout = current_app.config.get("GUEST_SESSION_TIMEOUT", 1800)
    last_active = session.get("guest_last_active", 0)
    now = time.time()

    # Expire after 30 minutes of inactivity
    if (now - last_active) > timeout:
        logout_guest()
        return False

    session["guest_last_active"] = now
    return True


def get_current_guest_id() -> str | None:
    """Return the active guest ID or None if not an active guest."""
    if is_active_guest():
        return session.get("guest_id")
    return None


def guest_required(f):
    """Ensure the request is made by an active, non-expired guest session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_active_guest():
            if request.path.startswith("/api/"):
                return jsonify(error="Guest session expired or invalid. Please log in or register."), 401
            return redirect(url_for("views.login", trial_expired=1))
        return f(*args, **kwargs)

    return decorated_function

