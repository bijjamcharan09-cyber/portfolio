"""REST API endpoints. Routes stay thin: validate -> call a helper -> return JSON.
Enforces authentication, user-level data isolation, and RBAC on every protected route.
"""
from datetime import date, datetime, timezone
import io
import time

from flask import Blueprint, Response, current_app, jsonify, request, send_file, session

from . import db
from .auth import (
    admin_required,
    get_current_guest_id,
    get_current_user,
    guest_required,
    hash_password,
    login_required,
    login_user,
    logout_user,
    verify_password,
)
from .services.excel import (
    export_expenses_to_excel,
    generate_template_excel,
    import_expenses_from_excel,
)
from .services.exchange import ExchangeError, get_rate
from .services.reports import date_range, render_chart, summarize, summarize_guest
from .validators import CATEGORIES, ValidationError, parse_date, validate_login, validate_registration, validate_transaction

bp = Blueprint("api", __name__, url_prefix="/api")


def _range():
    """Read ?period=day|month|year|days&date=YYYY-MM-DD&days=N from the URL."""
    period = request.args.get("period", "month")
    anchor = parse_date(request.args["date"]) if "date" in request.args else date.today()
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        raise ValidationError("days must be a whole number")
    if not 1 <= days <= 3650:
        raise ValidationError("days must be between 1 and 3650")
    try:
        return date_range(period, anchor, days)
    except ValueError as err:
        raise ValidationError(str(err))


# ============================================================================
# Authentication API Endpoints
# ============================================================================

@bp.post("/auth/register")
def register_api():
    """Register a new user account."""
    payload = request.get_json(silent=True) or request.form.to_dict()
    data = validate_registration(payload)

    # Prevent duplicate email registrations
    existing = db.get_user_by_email(data["email"])
    if existing:
        return jsonify(error="An account with this email address already exists."), 400

    # Role assignment: first user or designated ADMIN_EMAIL is admin
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
    return jsonify(user=db.user_to_dict(new_user)), 201


@bp.post("/auth/login")
def login_api():
    """Log in using email and password."""
    payload = request.get_json(silent=True) or request.form.to_dict()
    data = validate_login(payload)

    user = db.get_user_by_email(data["email"])
    if not user or not verify_password(data["password"], user["password_hash"]):
        return jsonify(error="Invalid email or password."), 401

    if not user["is_active"]:
        return jsonify(error="Account is deactivated. Please contact an administrator."), 403

    login_user(user)
    return jsonify(user=db.user_to_dict(user)), 200


@bp.post("/auth/logout")
def logout_api():
    """Log out current user and invalidate session."""
    logout_user()
    return jsonify(message="Logged out successfully."), 200


@bp.get("/auth/me")
@login_required
def current_user_api():
    """Return currently authenticated user profile."""
    user = get_current_user()
    return jsonify(user=db.user_to_dict(user))


# ============================================================================
# Admin Management API Endpoints (Admin Role Only)
# ============================================================================

@bp.get("/admin/users")
@admin_required
def admin_list_users():
    """View all registered users and their transaction statistics."""
    return jsonify(users=db.list_users())


@bp.post("/admin/users/<int:user_id>/toggle-status")
@admin_required
def admin_toggle_user_status(user_id):
    """Activate or deactivate a user account with safety checks."""
    if user_id == session.get("user_id"):
        return jsonify(error="You cannot deactivate your own administrative account."), 400

    target = db.get_user_by_id(user_id)
    if not target:
        return jsonify(error="User not found."), 404

    # Prevent deactivating the only active admin
    if target["role"] == "admin" and target["is_active"]:
        active_admins = [u for u in db.list_users() if u["role"] == "admin" and u["is_active"]]
        if len(active_admins) <= 1:
            return jsonify(error="Cannot deactivate the only active administrator."), 400

    new_status = 0 if target["is_active"] else 1
    db.update_user(user_id, is_active=new_status)
    updated = db.get_user_by_id(user_id)
    return jsonify(user=db.user_to_dict(updated))


@bp.delete("/admin/users/<int:user_id>")
@admin_required
def admin_delete_user(user_id):
    """Delete a user account with safety checks (cannot delete self or sole admin)."""
    if user_id == session.get("user_id"):
        return jsonify(error="You cannot delete your own administrative account."), 400

    target = db.get_user_by_id(user_id)
    if not target:
        return jsonify(error="User not found."), 404

    if target["role"] == "admin":
        admins = [u for u in db.list_users() if u["role"] == "admin"]
        if len(admins) <= 1:
            return jsonify(error="Cannot delete the only administrator account."), 400

    db.delete_user(user_id)
    return jsonify(message="User deleted successfully."), 200


@bp.get("/admin/stats")
@admin_required
def admin_platform_stats():
    """View application-wide statistics."""
    return jsonify(db.get_platform_stats())


# ============================================================================
# Personal Transaction Endpoints (User-Isolated & IDOR-Protected)
# ============================================================================

@bp.get("/categories")
def categories():
    """Return available transaction categories."""
    return jsonify(CATEGORIES)


@bp.get("/transactions")
@login_required
def list_transactions():
    """List transactions for the authenticated user only."""
    start, end = _range()
    user_id = session.get("user_id")
    return jsonify([db.row_to_dict(r) for r in db.list_transactions(start, end, user_id=user_id)])


@bp.post("/transactions")
@login_required
def create_transaction():
    """Create a new transaction for the authenticated user."""
    data = validate_transaction(request.get_json(silent=True))
    user_id = session.get("user_id")
    new_id = db.add_transaction(data, user_id=user_id)
    return jsonify(db.row_to_dict(db.get_transaction(new_id, user_id=user_id))), 201


@bp.get("/transactions/<int:tx_id>")
@login_required
def get_single_transaction(tx_id):
    """Retrieve a single transaction ensuring user ownership (prevents IDOR)."""
    user_id = session.get("user_id")
    tx = db.get_transaction(tx_id, user_id=user_id)
    if not tx:
        return jsonify(error="transaction not found"), 404
    return jsonify(db.row_to_dict(tx))


@bp.put("/transactions/<int:tx_id>")
@login_required
def update_transaction(tx_id):
    """Edit an existing transaction ensuring user ownership (prevents IDOR)."""
    user_id = session.get("user_id")
    existing = db.get_transaction(tx_id, user_id=user_id)
    if not existing:
        return jsonify(error="transaction not found"), 404

    data = validate_transaction(request.get_json(silent=True))
    db.update_transaction(tx_id, data, user_id=user_id)
    updated = db.get_transaction(tx_id, user_id=user_id)
    return jsonify(db.row_to_dict(updated)), 200


@bp.delete("/transactions/<int:tx_id>")
@login_required
def delete_transaction(tx_id):
    """Delete a transaction ensuring user ownership (prevents IDOR)."""
    user_id = session.get("user_id")
    if not db.delete_transaction(tx_id, user_id=user_id):
        return jsonify(error="transaction not found"), 404
    return "", 204


@bp.get("/reports/summary")
@login_required
def report_summary():
    """Generate summary report for the authenticated user only."""
    start, end = _range()
    user_id = session.get("user_id")
    return jsonify(summarize(start, end, user_id=user_id))


@bp.get("/reports/chart.png")
@login_required
def report_chart():
    """Render financial chart for the authenticated user only."""
    start, end = _range()
    user_id = session.get("user_id")
    return Response(render_chart(summarize(start, end, user_id=user_id)), mimetype="image/png")


@bp.get("/convert")
@login_required
def convert_balance():
    """Convert authenticated user's period balance into target currency."""
    target = request.args.get("to", "").upper()
    if len(target) != 3 or not target.isalpha():
        raise ValidationError("'to' must be a 3-letter currency code, e.g. EUR")
    start, end = _range()
    user_id = session.get("user_id")
    base = current_app.config["BASE_CURRENCY"]
    balance = summarize(start, end, user_id=user_id)["balance"]
    try:
        rate = get_rate(base, target)
    except ExchangeError as err:
        return jsonify(error=str(err)), 502
    return jsonify(base=base, to=target, rate=rate, balance=balance, converted=round(balance * rate, 2))


# ============================================================================
# Excel Import & Export Endpoints (Registered Users)
# ============================================================================

@bp.get("/excel/template")
def download_excel_template():
    """Download blank standardized Excel template with formatting and sample data."""
    buf = generate_template_excel()
    return send_file(
        buf,
        as_attachment=True,
        download_name="expense_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/excel/export")
@login_required
def export_user_excel():
    """Export authenticated user's transactions to an Excel spreadsheet."""
    user = get_current_user()
    user_id = user["id"]

    if "period" in request.args:
        start, end = _range()
        raw_rows = db.list_transactions(start, end, user_id=user_id)
    else:
        conn = db.get_db()
        raw_rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC, id DESC",
            (user_id,),
        ).fetchall()

    txs = [db.row_to_dict(r) for r in raw_rows]
    buf = export_expenses_to_excel(
        txs,
        title=f"{user['full_name']} Expense Report",
        base_currency=current_app.config["BASE_CURRENCY"],
    )
    today_str = date.today().strftime("%Y_%m_%d")
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"expense_report_{today_str}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.post("/excel/import")
@login_required
def import_user_excel():
    """Import expenses from an uploaded Excel spreadsheet for the authenticated user."""
    if "file" not in request.files:
        return jsonify(error="No file uploaded. Please select an .xlsx file."), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify(error="No file selected."), 400

    if not uploaded_file.filename.lower().endswith(".xlsx"):
        return jsonify(error="Only .xlsx Excel files are supported."), 400

    user = get_current_user()
    user_id = user["id"]

    try:
        parsed = import_expenses_from_excel(uploaded_file.stream)
    except ValidationError as err:
        return jsonify(error=str(err)), 400
    except Exception as exc:
        return jsonify(error=f"Could not parse Excel file: {exc}"), 400

    valid_records = parsed["valid_records"]
    inserted_count = 0
    for rec in valid_records:
        db.add_transaction(rec, user_id=user_id)
        inserted_count += 1

    return jsonify({
        "success": True,
        "message": f"Successfully imported {inserted_count} transactions.",
        "success_count": inserted_count,
        "rejected_count": parsed["rejected_count"],
        "errors": parsed["errors"],
    }), 200


# ============================================================================
# Guest Mode Isolated API Endpoints
# ============================================================================

@bp.get("/guest/categories")
def guest_categories():
    """Return available categories for guest demo."""
    return jsonify(CATEGORIES)


@bp.get("/guest/transactions")
@guest_required
def guest_list_transactions():
    """List transactions for the active guest session."""
    start, end = _range()
    guest_id = get_current_guest_id()
    rows = db.list_guest_transactions(guest_id, start, end)
    return jsonify([db.row_to_dict(r) for r in rows])


@bp.post("/guest/transactions")
@guest_required
def guest_create_transaction():
    """Create a transaction in temporary guest storage."""
    data = validate_transaction(request.get_json(silent=True))
    guest_id = get_current_guest_id()
    timeout = current_app.config.get("GUEST_SESSION_TIMEOUT", 1800)
    expires_at = datetime.fromtimestamp(time.time() + timeout, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_id = db.add_guest_transaction(guest_id, data, expires_at)
    row = db.get_guest_transaction(guest_id, new_id)
    return jsonify(db.row_to_dict(row)), 201


@bp.get("/guest/transactions/<int:tx_id>")
@guest_required
def guest_get_single_transaction(tx_id):
    """Retrieve single guest transaction."""
    guest_id = get_current_guest_id()
    row = db.get_guest_transaction(guest_id, tx_id)
    if not row:
        return jsonify(error="transaction not found"), 404
    return jsonify(db.row_to_dict(row))


@bp.put("/guest/transactions/<int:tx_id>")
@guest_required
def guest_update_transaction(tx_id):
    """Update a guest transaction."""
    guest_id = get_current_guest_id()
    existing = db.get_guest_transaction(guest_id, tx_id)
    if not existing:
        return jsonify(error="transaction not found"), 404

    data = validate_transaction(request.get_json(silent=True))
    db.update_guest_transaction(guest_id, tx_id, data)
    updated = db.get_guest_transaction(guest_id, tx_id)
    return jsonify(db.row_to_dict(updated)), 200


@bp.delete("/guest/transactions/<int:tx_id>")
@guest_required
def guest_delete_transaction(tx_id):
    """Delete a guest transaction."""
    guest_id = get_current_guest_id()
    if not db.delete_guest_transaction(guest_id, tx_id):
        return jsonify(error="transaction not found"), 404
    return "", 204


@bp.get("/guest/reports/summary")
@guest_required
def guest_report_summary():
    """Generate summary for the active guest session."""
    start, end = _range()
    guest_id = get_current_guest_id()
    return jsonify(summarize_guest(start, end, guest_id=guest_id))


@bp.get("/guest/reports/chart.png")
@guest_required
def guest_report_chart():
    """Render chart for the active guest session."""
    start, end = _range()
    guest_id = get_current_guest_id()
    return Response(render_chart(summarize_guest(start, end, guest_id=guest_id)), mimetype="image/png")


@bp.get("/guest/convert")
@guest_required
def guest_convert_balance():
    """Convert guest period balance into target currency."""
    target = request.args.get("to", "").upper()
    if len(target) != 3 or not target.isalpha():
        raise ValidationError("'to' must be a 3-letter currency code, e.g. EUR")
    start, end = _range()
    guest_id = get_current_guest_id()
    base = current_app.config["BASE_CURRENCY"]
    balance = summarize_guest(start, end, guest_id=guest_id)["balance"]
    try:
        rate = get_rate(base, target)
    except ExchangeError as err:
        return jsonify(error=str(err)), 502
    return jsonify(base=base, to=target, rate=rate, balance=balance, converted=round(balance * rate, 2))


@bp.get("/guest/excel/template")
def guest_excel_template():
    """Download blank Excel template for guest demo."""
    buf = generate_template_excel()
    return send_file(
        buf,
        as_attachment=True,
        download_name="expense_template.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.get("/guest/excel/export")
@guest_required
def guest_export_excel():
    """Export guest demo transactions to Excel."""
    guest_id = get_current_guest_id()
    if "period" in request.args:
        start, end = _range()
        raw_rows = db.list_guest_transactions(guest_id, start, end)
    else:
        raw_rows = db.list_guest_transactions(guest_id)

    txs = [db.row_to_dict(r) for r in raw_rows]
    buf = export_expenses_to_excel(
        txs,
        title="Guest Demo Expense Report",
        base_currency=current_app.config["BASE_CURRENCY"],
    )
    today_str = date.today().strftime("%Y_%m_%d")
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"guest_demo_expenses_{today_str}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.post("/guest/excel/import")
@guest_required
def guest_import_excel():
    """Import expenses from an Excel spreadsheet into temporary guest data."""
    if "file" not in request.files:
        return jsonify(error="No file uploaded. Please select an .xlsx file."), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify(error="No file selected."), 400

    if not uploaded_file.filename.lower().endswith(".xlsx"):
        return jsonify(error="Only .xlsx Excel files are supported."), 400

    guest_id = get_current_guest_id()
    try:
        parsed = import_expenses_from_excel(uploaded_file.stream)
    except ValidationError as err:
        return jsonify(error=str(err)), 400
    except Exception as exc:
        return jsonify(error=f"Could not parse Excel file: {exc}"), 400

    timeout = current_app.config.get("GUEST_SESSION_TIMEOUT", 1800)
    expires_at = datetime.fromtimestamp(time.time() + timeout, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    valid_records = parsed["valid_records"]
    inserted_count = 0
    for rec in valid_records:
        db.add_guest_transaction(guest_id, rec, expires_at)
        inserted_count += 1

    return jsonify({
        "success": True,
        "message": f"Successfully imported {inserted_count} demo transactions.",
        "success_count": inserted_count,
        "rejected_count": parsed["rejected_count"],
        "errors": parsed["errors"],
    }), 200

