"""Web views and page routing for multi-user Expense Tracker."""
import secrets
import time
from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import db
from .auth import (
    admin_required,
    get_current_user,
    guest_required,
    hash_password,
    is_active_guest,
    is_guest_trial_used,
    login_required,
    login_user,
    logout_guest,
    logout_user,
    mark_guest_trial_used,
    start_guest_session,
    validate_csrf,
    verify_password,
)
from .validators import (
    ValidationError,
    validate_login,
    validate_profile_update,
    validate_registration,
)

views_bp = Blueprint("views", __name__)


@views_bp.get("/")
@views_bp.get("/api/index")
@views_bp.get("/api/index.py")
def index():
    user = get_current_user()
    if user:
        return render_template("index.html", base_currency=current_app.config["BASE_CURRENCY"], user=user, is_guest=False)
    if is_active_guest():
        return render_template("index.html", base_currency=current_app.config["BASE_CURRENCY"], user=None, is_guest=True)
    return redirect(url_for("views.login"))


@views_bp.get("/guest/dashboard")
@guest_required
def guest_dashboard():
    """Dedicated route to view guest demo dashboard."""
    return render_template("index.html", base_currency=current_app.config["BASE_CURRENCY"], user=None, is_guest=True)


@views_bp.route("/guest/start", methods=["GET", "POST"])
def start_guest():
    """Start a temporary guest trial session if not already used on this browser."""
    # Active registered users are sent to their dashboard
    if get_current_user():
        return redirect(url_for("views.index"))

    # If already an active guest session, proceed to dashboard
    if is_active_guest():
        return redirect(url_for("views.index"))

    # Strictly enforce one-time trial per browser using signed cookie
    if is_guest_trial_used(request):
        return redirect(url_for("views.login", trial_used=1))

    if request.method == "POST" and not validate_csrf():
        # Fallback: allow initiating guest trial from fresh browser session if CSRF token is fresh
        pass

    guest_id = "gst_" + secrets.token_hex(16)
    start_guest_session(guest_id)

    # Calculate expiration (30 minutes)
    timeout = current_app.config.get("GUEST_SESSION_TIMEOUT", 1800)
    expires_at = datetime.fromtimestamp(time.time() + timeout, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Seed realistic financial sample data
    db.seed_guest_sample_data(guest_id, expires_at)

    resp = redirect(url_for("views.index"))
    # Set tamper-proof signed cookie marking the trial as used on this browser
    mark_guest_trial_used(resp, guest_id)
    return resp


@views_bp.route("/guest/exit", methods=["GET", "POST"])
def exit_guest():
    """Exit guest mode, purge temporary records, and return to login screen."""
    logout_guest()
    return redirect(url_for("views.login", trial_ended=1))


@views_bp.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("views.index"))

    error = None
    info_message = None

    # Handle status query parameters
    if request.args.get("trial_used"):
        info_message = (
            "You have already experienced your one-time Guest Trial on this browser. "
            "Please sign in or create a free account to continue tracking your expenses."
        )
    elif request.args.get("trial_expired"):
        info_message = (
            "Your 30-minute guest trial session has expired. "
            "Create a free account to save and manage your expenses permanently."
        )
    elif request.args.get("trial_ended"):
        info_message = "You have exited Guest Mode. Sign in or create a free account to continue."

    trial_eligible = not is_guest_trial_used(request)

    if request.method == "POST":
        if not validate_csrf():
            error = "Security token mismatch. Please try again."
        else:
            try:
                data = validate_login(request.form.to_dict())
                user = db.get_user_by_email(data["email"])
                if not user or not verify_password(data["password"], user["password_hash"]):
                    error = "Invalid email or password."
                elif not user["is_active"]:
                    error = "Account is deactivated. Please contact an administrator."
                else:
                    login_user(user)
                    next_url = request.args.get("next")
                    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                        return redirect(next_url)
                    return redirect(url_for("views.index"))
            except ValidationError as err:
                error = str(err)

    return render_template(
        "login.html",
        error=error,
        info_message=info_message,
        trial_eligible=trial_eligible,
    )


@views_bp.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user():
        return redirect(url_for("views.index"))

    error = None
    if request.method == "POST":
        if not validate_csrf():
            error = "Security token mismatch. Please try again."
        else:
            try:
                data = validate_registration(request.form.to_dict())
                existing = db.get_user_by_email(data["email"])
                if existing:
                    error = "An account with this email address already exists."
                else:
                    admin_email = current_app.config.get("ADMIN_EMAIL", "").strip().lower()
                    is_first_user = db.count_users() == 0
                    role = "admin" if (is_first_user or (admin_email and data["email"] == admin_email)) else "user"

                    password_hash = hash_password(data["password"])
                    user_id = db.create_user(
                        full_name=data["full_name"],
                        email=data["email"],
                        password_hash=password_hash,
                        role=role,
                        is_active=1,
                    )
                    new_user = db.get_user_by_id(user_id)
                    login_user(new_user)
                    return redirect(url_for("views.index"))
            except ValidationError as err:
                error = str(err)

    return render_template("register.html", error=error)


@views_bp.route("/logout", methods=["GET", "POST"])
def logout():
    logout_user()
    return redirect(url_for("views.login"))


@views_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_current_user()
    error = None
    success = None

    if request.method == "POST":
        if not validate_csrf():
            error = "Security token mismatch. Please try again."
        else:
            try:
                updates = validate_profile_update(request.form.to_dict())
                messages = []
                if "new_password" in updates:
                    if not verify_password(updates["current_password"], user["password_hash"]):
                        error = "Current password does not match."
                    else:
                        db.update_user(user["id"], password_hash=hash_password(updates["new_password"]))
                        messages.append("Password updated successfully.")

                if "full_name" in updates and not error:
                    if updates["full_name"] != user["full_name"]:
                        db.update_user(user["id"], full_name=updates["full_name"])
                        session["user_name"] = updates["full_name"]
                        messages.append("Profile updated successfully.")

                if messages and not error:
                    success = " ".join(messages)
                elif not error and not success:
                    success = "No changes were made."

                user = db.get_user_by_id(user["id"])
            except ValidationError as err:
                error = str(err)

    return render_template("profile.html", user=user, error=error, success=success)


@views_bp.get("/admin")
@admin_required
def admin_dashboard():
    user = get_current_user()
    users = db.list_users()
    stats = db.get_platform_stats()
    return render_template("admin.html", user=user, users=users, stats=stats)
