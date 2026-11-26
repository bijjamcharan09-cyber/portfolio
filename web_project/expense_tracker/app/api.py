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
from .validators import (
    CATEGORIES,
    ValidationError,
    parse_date,
    validate_login,
    validate_profile_update,
    validate_registration,
    validate_transaction,
    validate_budget,
    validate_recurring_transaction,
    validate_financial_goal,
    validate_goal_contribution,
    validate_subscription,
)

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

    # Strict RBAC: Public registration ALWAYS creates standard user accounts.
    # Automatic admin promotion (first user, admin email, or name) is strictly prevented.
    # Admin accounts can only be created via CLI or by an authenticated admin.
    role = "user"

    password_hash = hash_password(data["password"])
    user_id = db.create_user(
        full_name=data["full_name"],
        email=data["email"],
        password_hash=password_hash,
        role=role,
        is_active=1,
    )

    # Audit log: user registration
    db.audit_log(
        action="user_register",
        entity_type="user",
        entity_id=str(user_id),
        user_id=user_id,
        metadata={"email": data["email"], "role": role}
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
        # Audit log: failed login
        if user:
            db.audit_log(
                action="login_failed",
                entity_type="user",
                entity_id=str(user["id"]),
                user_id=user["id"],
                metadata={"reason": "invalid_password"}
            )
        else:
            db.audit_log(
                action="login_failed",
                entity_type="user",
                metadata={"email": data["email"], "reason": "user_not_found"}
            )
        return jsonify(error="Invalid email or password."), 401

    if not user["is_active"]:
        # Audit log: failed login - deactivated account
        db.audit_log(
            action="login_failed",
            entity_type="user",
            entity_id=str(user["id"]),
            user_id=user["id"],
            metadata={"reason": "account_deactivated"}
        )
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


@bp.put("/auth/me")
@login_required
def update_current_user_api():
    """Update authenticated user profile (strictly prevents privilege/role escalation)."""
    payload = request.get_json(silent=True) or request.form.to_dict()
    updates = validate_profile_update(payload)
    user = get_current_user()

    if "full_name" in updates and updates["full_name"] != user["full_name"]:
        old_name = user["full_name"]
        db.update_user(user["id"], full_name=updates["full_name"])
        session["user_name"] = updates["full_name"]
        # Audit log: profile update
        db.audit_log(
            action="profile_update",
            entity_type="user",
            entity_id=str(user["id"]),
            user_id=user["id"],
            metadata={"field": "full_name", "old_value": old_name, "new_value": updates["full_name"]}
        )

    if "new_password" in updates:
        if not verify_password(updates["current_password"], user["password_hash"]):
            return jsonify(error="Current password does not match."), 400
        db.update_user(user["id"], password_hash=hash_password(updates["new_password"]))
        # Audit log: password change
        db.audit_log(
            action="password_change",
            entity_type="user",
            entity_id=str(user["id"]),
            user_id=user["id"]
        )

    updated = db.get_user_by_id(user["id"])
    return jsonify(user=db.user_to_dict(updated)), 200


# ============================================================================
# Admin Management API Endpoints (Admin Role Only)
# ============================================================================

@bp.get("/admin/users")
@admin_required
def admin_list_users():
    """View all registered users and their transaction statistics."""
    return jsonify(users=db.list_users())


@bp.post("/admin/users")
@admin_required
def admin_create_user():
    """Create a new user or administrator account (Authorized Admins only)."""
    payload = request.get_json(silent=True) or request.form.to_dict()
    data = validate_registration(payload)

    existing = db.get_user_by_email(data["email"])
    if existing:
        return jsonify(error="An account with this email address already exists."), 400

    # Authorized admin can specify role, defaults to 'user'
    requested_role = (payload.get("role") or "user").strip().lower()
    role = "admin" if requested_role == "admin" else "user"

    password_hash = hash_password(data["password"])
    admin_user_id = session.get("user_id")
    user_id = db.create_user(
        full_name=data["full_name"],
        email=data["email"],
        password_hash=password_hash,
        role=role,
        is_active=1,
    )
    # Audit log: admin user create
    db.audit_log(
        action="admin_user_create",
        entity_type="user",
        entity_id=str(user_id),
        user_id=admin_user_id,
        metadata={"target_email": data["email"], "target_role": role}
    )
    new_user = db.get_user_by_id(user_id)
    return jsonify(user=db.user_to_dict(new_user)), 201


@bp.post("/admin/users/<int:user_id>/toggle-status")
@admin_required
def admin_toggle_user_status(user_id):
    """Activate or deactivate a user account with safety checks."""
    admin_user_id = session.get("user_id")
    if user_id == admin_user_id:
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
    # Audit log: admin user toggle
    db.audit_log(
        action="admin_user_toggle",
        entity_type="user",
        entity_id=str(user_id),
        user_id=admin_user_id,
        metadata={"target_email": target["email"], "new_status": "active" if new_status else "inactive"}
    )
    updated = db.get_user_by_id(user_id)
    return jsonify(user=db.user_to_dict(updated))


@bp.delete("/admin/users/<int:user_id>")
@admin_required
def admin_delete_user(user_id):
    """Delete a user account with safety checks (cannot delete self or sole admin)."""
    admin_user_id = session.get("user_id")
    if user_id == admin_user_id:
        return jsonify(error="You cannot delete your own administrative account."), 400

    target = db.get_user_by_id(user_id)
    if not target:
        return jsonify(error="User not found."), 404

    if target["role"] == "admin":
        admins = [u for u in db.list_users() if u["role"] == "admin"]
        if len(admins) <= 1:
            return jsonify(error="Cannot delete the only administrator account."), 400

    target_email = target["email"]
    target_role = target["role"]
    db.delete_user(user_id)

    # Audit log: admin user delete
    db.audit_log(
        action="admin_user_delete",
        entity_type="user",
        entity_id=str(user_id),
        user_id=admin_user_id,
        metadata={"target_email": target_email, "target_role": target_role}
    )
    return jsonify(message="User deleted successfully."), 200


@bp.get("/admin/stats")
@admin_required
def admin_platform_stats():
    """View application-wide statistics."""
    return jsonify(db.get_platform_stats())


# ============================================================================
# Audit Log Endpoints (Admin Only)
# ============================================================================

@bp.get("/admin/audit-logs")
@admin_required
def admin_audit_logs():
    """View audit logs with filtering and pagination (admin only)."""
    user_id = request.args.get("user_id", type=int)
    action = request.args.get("action", type=str)
    entity_type = request.args.get("entity_type", type=str)
    page = request.args.get("page", 1, type=int)
    per_page = min(max(request.args.get("per_page", 50, type=int), 1), 200)

    offset = (page - 1) * per_page

    logs = db.get_audit_logs(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        limit=per_page,
        offset=offset
    )
    total = db.count_audit_logs(
        user_id=user_id,
        action=action,
        entity_type=entity_type
    )

    return jsonify(
        audit_logs=[dict(r) for r in logs],
        pagination={
            "current_page": page,
            "per_page": per_page,
            "total_records": total,
            "total_pages": (total + per_page - 1) // per_page,
            "has_next": page * per_page < total,
            "has_previous": page > 1,
        }
    )


@bp.get("/admin/audit-logs/actions")
@admin_required
def admin_audit_log_actions():
    """Get distinct action types for audit log filtering."""
    conn = db.get_db()
    rows = conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action").fetchall()
    return jsonify(actions=[r["action"] for r in rows])


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
    """List transactions for the authenticated user only with pagination."""
    start, end = _range()
    user_id = session.get("user_id")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", type=int)

    result = db.list_transactions(start, end, user_id=user_id, page=page, per_page=per_page)
    return jsonify(
        transactions=[db.row_to_dict(r) for r in result["transactions"]],
        pagination=result["pagination"],
    )


@bp.post("/transactions")
@login_required
def create_transaction():
    """Create a new transaction for the authenticated user."""
    data = validate_transaction(request.get_json(silent=True))
    user_id = session.get("user_id")
    new_id = db.add_transaction(data, user_id=user_id)
    created = db.get_transaction(new_id, user_id=user_id)
    # Audit log: transaction create
    db.audit_log(
        action="transaction_create",
        entity_type="transaction",
        entity_id=str(new_id),
        user_id=user_id,
        metadata={"type": data["type"], "amount_cents": data["amount_cents"], "category": data["category"], "date": data["date"]}
    )
    return jsonify(db.row_to_dict(created)), 201


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
    # Capture old values for audit log
    old_data = {
        "type": existing["type"],
        "amount_cents": existing["amount_cents"],
        "category": existing["category"],
        "note": existing["note"],
        "date": existing["date"],
    }
    db.update_transaction(tx_id, data, user_id=user_id)
    updated = db.get_transaction(tx_id, user_id=user_id)
    # Audit log: transaction update
    db.audit_log(
        action="transaction_update",
        entity_type="transaction",
        entity_id=str(tx_id),
        user_id=user_id,
        metadata={"old": old_data, "new": {"type": data["type"], "amount_cents": data["amount_cents"], "category": data["category"], "note": data["note"], "date": data["date"]}}
    )
    return jsonify(db.row_to_dict(updated)), 200


@bp.delete("/transactions/<int:tx_id>")
@login_required
def delete_transaction(tx_id):
    """Delete a transaction ensuring user ownership (prevents IDOR)."""
    user_id = session.get("user_id")
    existing = db.get_transaction(tx_id, user_id=user_id)
    if not existing:
        return jsonify(error="transaction not found"), 404

    # Capture data for audit log before deletion
    deleted_data = {
        "type": existing["type"],
        "amount_cents": existing["amount_cents"],
        "category": existing["category"],
        "note": existing["note"],
        "date": existing["date"],
    }

    if not db.delete_transaction(tx_id, user_id=user_id):
        return jsonify(error="transaction not found"), 404

    # Audit log: transaction delete
    db.audit_log(
        action="transaction_delete",
        entity_type="transaction",
        entity_id=str(tx_id),
        user_id=user_id,
        metadata=deleted_data
    )
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
        result = db.list_transactions(start, end, user_id=user_id)
    else:
        conn = db.get_db()
        raw_rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC, id DESC",
            (user_id,),
        ).fetchall()
        result = {"transactions": raw_rows, "pagination": {}}

    txs = [db.row_to_dict(r) for r in result["transactions"]]
    buf = export_expenses_to_excel(
        txs,
        title=f"{user['full_name']} Expense Report",
        base_currency=current_app.config["BASE_CURRENCY"],
    )
    today_str = date.today().strftime("%Y_%m_%d")

    # Audit log: excel export
    db.audit_log(
        action="excel_export",
        entity_type="excel",
        entity_id=f"expense_report_{today_str}",
        user_id=user_id,
        metadata={"record_count": len(txs), "period": request.args.get("period", "all")}
    )

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

    # Audit log: excel import
    db.audit_log(
        action="excel_import",
        entity_type="excel",
        entity_id=uploaded_file.filename,
        user_id=user_id,
        metadata={"inserted_count": inserted_count, "rejected_count": parsed["rejected_count"], "filename": uploaded_file.filename}
    )

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
    """List transactions for the active guest session with pagination."""
    start, end = _range()
    guest_id = get_current_guest_id()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", type=int)

    result = db.list_guest_transactions(guest_id, start, end, page=page, per_page=per_page)
    return jsonify(
        transactions=[db.row_to_dict(r) for r in result["transactions"]],
        pagination=result["pagination"],
    )


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
    # Audit log: guest transaction create
    db.audit_log(
        action="guest_transaction_create",
        entity_type="guest_transaction",
        entity_id=str(new_id),
        user_id=None,
        metadata={"type": data["type"], "amount_cents": data["amount_cents"], "category": data["category"], "date": data["date"]}
    )
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
    # Capture old values for audit log
    old_data = {
        "type": existing["type"],
        "amount_cents": existing["amount_cents"],
        "category": existing["category"],
        "note": existing["note"],
        "date": existing["date"],
    }
    db.update_guest_transaction(guest_id, tx_id, data)
    updated = db.get_guest_transaction(guest_id, tx_id)
    # Audit log: guest transaction update
    db.audit_log(
        action="guest_transaction_update",
        entity_type="guest_transaction",
        entity_id=str(tx_id),
        user_id=None,
        metadata={"old": old_data, "new": {"type": data["type"], "amount_cents": data["amount_cents"], "category": data["category"], "note": data["note"], "date": data["date"]}}
    )
    return jsonify(db.row_to_dict(updated)), 200


@bp.delete("/guest/transactions/<int:tx_id>")
@guest_required
def guest_delete_transaction(tx_id):
    """Delete a guest transaction."""
    guest_id = get_current_guest_id()
    existing = db.get_guest_transaction(guest_id, tx_id)
    if not existing:
        return jsonify(error="transaction not found"), 404

    # Capture data for audit log before deletion
    deleted_data = {
        "type": existing["type"],
        "amount_cents": existing["amount_cents"],
        "category": existing["category"],
        "note": existing["note"],
        "date": existing["date"],
    }

    if not db.delete_guest_transaction(guest_id, tx_id):
        return jsonify(error="transaction not found"), 404

    # Audit log: guest transaction delete
    db.audit_log(
        action="guest_transaction_delete",
        entity_type="guest_transaction",
        entity_id=str(tx_id),
        user_id=None,
        metadata=deleted_data
    )
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
        result = db.list_guest_transactions(guest_id, start, end)
    else:
        result = db.list_guest_transactions(guest_id)

    txs = [db.row_to_dict(r) for r in result["transactions"]]
    buf = export_expenses_to_excel(
        txs,
        title="Guest Demo Expense Report",
        base_currency=current_app.config["BASE_CURRENCY"],
    )
    today_str = date.today().strftime("%Y_%m_%d")

    # Audit log: guest excel export
    db.audit_log(
        action="guest_excel_export",
        entity_type="excel",
        entity_id=f"guest_demo_expenses_{today_str}",
        user_id=None,
        metadata={"record_count": len(txs), "period": request.args.get("period", "all")}
    )

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

    # Audit log: guest excel import
    db.audit_log(
        action="guest_excel_import",
        entity_type="excel",
        entity_id=uploaded_file.filename,
        user_id=None,
        metadata={"inserted_count": inserted_count, "rejected_count": parsed["rejected_count"], "filename": uploaded_file.filename}
    )

    return jsonify({
        "success": True,
        "message": f"Successfully imported {inserted_count} demo transactions.",
        "success_count": inserted_count,
        "rejected_count": parsed["rejected_count"],
        "errors": parsed["errors"],
    }), 200


# ============================================================================
# Budget Endpoints (User-Isolated)
# ============================================================================

@bp.get("/budgets")
@login_required
def list_budgets():
    """List all budgets for the authenticated user."""
    user_id = session.get("user_id")
    is_active = request.args.get("is_active", type=int)
    period = request.args.get("period", type=str)

    budgets = db.list_budgets(user_id, is_active=is_active, period=period)
    return jsonify(budgets=[dict(b) for b in budgets])


@bp.post("/budgets")
@login_required
def create_budget():
    """Create a new budget for the authenticated user."""
    data = validate_budget(request.get_json(silent=True))
    user_id = session.get("user_id")
    new_id = db.add_budget(user_id, data)
    budget = db.get_budget(new_id, user_id)
    # Audit log: budget create
    db.audit_log(
        action="budget_create",
        entity_type="budget",
        entity_id=str(new_id),
        user_id=user_id,
        metadata={"name": data["name"], "period": data["period"], "amount_cents": data["amount_cents"]}
    )
    return jsonify(dict(budget)), 201


@bp.get("/budgets/<int:budget_id>")
@login_required
def get_budget(budget_id):
    """Retrieve a single budget ensuring user ownership."""
    user_id = session.get("user_id")
    budget = db.get_budget(budget_id, user_id)
    if not budget:
        return jsonify(error="budget not found"), 404
    return jsonify(dict(budget))


@bp.put("/budgets/<int:budget_id>")
@login_required
def update_budget(budget_id):
    """Update an existing budget ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_budget(budget_id, user_id)
    if not existing:
        return jsonify(error="budget not found"), 404

    data = validate_budget(request.get_json(silent=True))
    # Capture old values for audit log
    old_data = dict(existing)
    db.update_budget(budget_id, user_id, data)
    updated = db.get_budget(budget_id, user_id)
    # Audit log: budget update
    db.audit_log(
        action="budget_update",
        entity_type="budget",
        entity_id=str(budget_id),
        user_id=user_id,
        metadata={"old": old_data, "new": dict(updated)}
    )
    return jsonify(dict(updated)), 200


@bp.delete("/budgets/<int:budget_id>")
@login_required
def delete_budget(budget_id):
    """Delete a budget ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_budget(budget_id, user_id)
    if not existing:
        return jsonify(error="budget not found"), 404

    # Capture data for audit log before deletion
    deleted_data = dict(existing)

    if not db.delete_budget(budget_id, user_id):
        return jsonify(error="budget not found"), 404

    # Audit log: budget delete
    db.audit_log(
        action="budget_delete",
        entity_type="budget",
        entity_id=str(budget_id),
        user_id=user_id,
        metadata=deleted_data
    )
    return "", 204


@bp.get("/budgets/utilization")
@login_required
def get_budget_utilization():
    """Get budget utilization for all active budgets in the current period."""
    user_id = session.get("user_id")
    start, end = _range()
    auto_period = "period" not in request.args

    utilizations = db.get_all_budget_utilizations(user_id, start, end, auto_period=auto_period)
    return jsonify(budgets=utilizations)


# ============================================================================
# Recurring Transaction Endpoints (User-Isolated)
# ============================================================================

@bp.get("/recurring")
@login_required
def list_recurring_transactions():
    """List all recurring transactions for the authenticated user (auto-processes due items)."""
    user_id = session.get("user_id")
    # Idempotently process any due recurring transactions for this user
    db.process_due_recurring_for_user(user_id)
    is_active = request.args.get("is_active", type=int)
    is_paused = request.args.get("is_paused", type=int)

    recurring = db.list_recurring_transactions(user_id, is_active=is_active, is_paused=is_paused)
    return jsonify(recurring=[dict(r) for r in recurring])


@bp.post("/recurring")
@login_required
def create_recurring_transaction():
    """Create a new recurring transaction for the authenticated user."""
    data = validate_recurring_transaction(request.get_json(silent=True))
    user_id = session.get("user_id")
    new_id = db.add_recurring_transaction(user_id, data)
    rt = db.get_recurring_transaction(new_id, user_id)
    # Audit log: recurring transaction create
    db.audit_log(
        action="recurring_create",
        entity_type="recurring_transaction",
        entity_id=str(new_id),
        user_id=user_id,
        metadata={"frequency": data["frequency"], "amount_cents": data["amount_cents"], "category": data["category"]}
    )
    return jsonify(dict(rt)), 201


@bp.get("/recurring/<int:rt_id>")
@login_required
def get_recurring_transaction(rt_id):
    """Retrieve a single recurring transaction ensuring user ownership."""
    user_id = session.get("user_id")
    rt = db.get_recurring_transaction(rt_id, user_id)
    if not rt:
        return jsonify(error="recurring transaction not found"), 404
    return jsonify(dict(rt))


@bp.put("/recurring/<int:rt_id>")
@login_required
def update_recurring_transaction(rt_id):
    """Update an existing recurring transaction ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_recurring_transaction(rt_id, user_id)
    if not existing:
        return jsonify(error="recurring transaction not found"), 404

    data = validate_recurring_transaction(request.get_json(silent=True))
    # Capture old values for audit log
    old_data = dict(existing)
    db.update_recurring_transaction(rt_id, user_id, data)
    updated = db.get_recurring_transaction(rt_id, user_id)
    # Audit log: recurring transaction update
    db.audit_log(
        action="recurring_update",
        entity_type="recurring_transaction",
        entity_id=str(rt_id),
        user_id=user_id,
        metadata={"old": old_data, "new": dict(updated)}
    )
    return jsonify(dict(updated)), 200


@bp.delete("/recurring/<int:rt_id>")
@login_required
def delete_recurring_transaction(rt_id):
    """Delete a recurring transaction ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_recurring_transaction(rt_id, user_id)
    if not existing:
        return jsonify(error="recurring transaction not found"), 404

    # Capture data for audit log before deletion
    deleted_data = dict(existing)

    if not db.delete_recurring_transaction(rt_id, user_id):
        return jsonify(error="recurring transaction not found"), 404

    # Audit log: recurring transaction delete
    db.audit_log(
        action="recurring_delete",
        entity_type="recurring_transaction",
        entity_id=str(rt_id),
        user_id=user_id,
        metadata=deleted_data
    )
    return "", 204


@bp.post("/recurring/<int:rt_id>/pause")
@login_required
def pause_recurring_transaction(rt_id):
    """Pause a recurring transaction."""
    user_id = session.get("user_id")
    existing = db.get_recurring_transaction(rt_id, user_id)
    if not existing:
        return jsonify(error="recurring transaction not found"), 404

    db.update_recurring_transaction(rt_id, user_id, {"is_paused": 1})
    # Audit log: recurring transaction pause
    db.audit_log(
        action="recurring_pause",
        entity_type="recurring_transaction",
        entity_id=str(rt_id),
        user_id=user_id
    )
    updated = db.get_recurring_transaction(rt_id, user_id)
    return jsonify(dict(updated)), 200


@bp.post("/recurring/<int:rt_id>/resume")
@login_required
def resume_recurring_transaction(rt_id):
    """Resume a paused recurring transaction."""
    user_id = session.get("user_id")
    existing = db.get_recurring_transaction(rt_id, user_id)
    if not existing:
        return jsonify(error="recurring transaction not found"), 404

    db.update_recurring_transaction(rt_id, user_id, {"is_paused": 0})
    # Audit log: recurring transaction resume
    db.audit_log(
        action="recurring_resume",
        entity_type="recurring_transaction",
        entity_id=str(rt_id),
        user_id=user_id
    )
    updated = db.get_recurring_transaction(rt_id, user_id)
    return jsonify(dict(updated)), 200


@bp.post("/recurring/process")
@login_required
def process_recurring_transactions():
    """Process due recurring transactions and generate actual transactions."""
    user_id = session.get("user_id")
    generated = db.process_due_recurring_for_user(user_id, date.today())

    for item in generated:
        db.audit_log(
            action="recurring_generated",
            entity_type="transaction",
            entity_id=str(item["transaction_id"]),
            user_id=user_id,
            metadata={"recurring_id": item["recurring_id"], "frequency": item["frequency"]}
        )

    return jsonify(generated=generated, count=len(generated)), 200


# ============================================================================
# Financial Goals Endpoints (User-Isolated)
# ============================================================================

@bp.get("/goals")
@login_required
def list_financial_goals():
    """List all financial goals for the authenticated user."""
    user_id = session.get("user_id")
    is_completed = request.args.get("is_completed", type=int)

    goals = db.list_financial_goals(user_id, is_completed=is_completed)
    return jsonify(goals=[dict(g) for g in goals])


@bp.post("/goals")
@login_required
def create_financial_goal():
    """Create a new financial goal for the authenticated user."""
    data = validate_financial_goal(request.get_json(silent=True))
    user_id = session.get("user_id")
    new_id = db.add_financial_goal(user_id, data)
    goal = db.get_financial_goal(new_id, user_id)
    # Audit log: goal create
    db.audit_log(
        action="goal_create",
        entity_type="goal",
        entity_id=str(new_id),
        user_id=user_id,
        metadata={"name": data["name"], "target_amount_cents": data["target_amount_cents"]}
    )
    return jsonify(dict(goal)), 201


@bp.get("/goals/<int:goal_id>")
@login_required
def get_financial_goal(goal_id):
    """Retrieve a single financial goal ensuring user ownership."""
    user_id = session.get("user_id")
    goal = db.get_financial_goal(goal_id, user_id)
    if not goal:
        return jsonify(error="goal not found"), 404

    # Include progress info
    progress = db.get_goal_progress(goal_id, user_id)
    result = dict(goal)
    result.update(progress)
    return jsonify(result)


@bp.put("/goals/<int:goal_id>")
@login_required
def update_financial_goal(goal_id):
    """Update an existing financial goal ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_financial_goal(goal_id, user_id)
    if not existing:
        return jsonify(error="goal not found"), 404

    data = validate_financial_goal(request.get_json(silent=True))
    # Capture old values for audit log
    old_data = dict(existing)
    db.update_financial_goal(goal_id, user_id, data)
    updated = db.get_financial_goal(goal_id, user_id)
    # Audit log: goal update
    db.audit_log(
        action="goal_update",
        entity_type="goal",
        entity_id=str(goal_id),
        user_id=user_id,
        metadata={"old": old_data, "new": dict(updated)}
    )
    return jsonify(dict(updated)), 200


@bp.delete("/goals/<int:goal_id>")
@login_required
def delete_financial_goal(goal_id):
    """Delete a financial goal ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_financial_goal(goal_id, user_id)
    if not existing:
        return jsonify(error="goal not found"), 404

    # Capture data for audit log before deletion
    deleted_data = dict(existing)

    if not db.delete_financial_goal(goal_id, user_id):
        return jsonify(error="goal not found"), 404

    # Audit log: goal delete
    db.audit_log(
        action="goal_delete",
        entity_type="goal",
        entity_id=str(goal_id),
        user_id=user_id,
        metadata=deleted_data
    )
    return "", 204


@bp.post("/goals/<int:goal_id>/contributions")
@login_required
def add_goal_contribution(goal_id):
    """Add a contribution to a financial goal."""
    user_id = session.get("user_id")
    existing = db.get_financial_goal(goal_id, user_id)
    if not existing:
        return jsonify(error="goal not found"), 404

    data = validate_goal_contribution(request.get_json(silent=True))
    contribution_id = db.add_goal_contribution(goal_id, user_id, data)

    # Get updated goal progress
    progress = db.get_goal_progress(goal_id, user_id)
    # Audit log: goal contribution
    db.audit_log(
        action="goal_contribution",
        entity_type="goal",
        entity_id=str(goal_id),
        user_id=user_id,
        metadata={"amount_cents": data["amount_cents"], "progress_pct": progress["progress_pct"]}
    )

    # Check for goal completion notification
    if progress["is_completed"] and not existing["is_completed"]:
        db.audit_log(
            action="goal_completed",
            entity_type="goal",
            entity_id=str(goal_id),
            user_id=user_id,
            metadata={"target_amount": progress["target_amount"], "final_amount": progress["current_amount"]}
        )

    return jsonify(contribution_id=contribution_id, progress=progress), 201


@bp.get("/goals/<int:goal_id>/contributions")
@login_required
def list_goal_contributions(goal_id):
    """List all contributions for a financial goal."""
    user_id = session.get("user_id")
    existing = db.get_financial_goal(goal_id, user_id)
    if not existing:
        return jsonify(error="goal not found"), 404

    contributions = db.get_goal_contributions(goal_id, user_id)
    return jsonify(contributions=[dict(c) for c in contributions])


# ============================================================================
# Subscription Endpoints (User-Isolated)
# ============================================================================

@bp.get("/subscriptions")
@login_required
def list_subscriptions():
    """List all subscriptions for the authenticated user."""
    user_id = session.get("user_id")
    status = request.args.get("status", type=str)

    subs = db.list_subscriptions(user_id, status=status)
    return jsonify(subscriptions=[dict(s) for s in subs])


@bp.post("/subscriptions")
@login_required
def create_subscription():
    """Create a new subscription for the authenticated user."""
    data = validate_subscription(request.get_json(silent=True))
    user_id = session.get("user_id")
    new_id = db.add_subscription(user_id, data)
    sub = db.get_subscription(new_id, user_id)
    # Audit log: subscription create
    db.audit_log(
        action="subscription_create",
        entity_type="subscription",
        entity_id=str(new_id),
        user_id=user_id,
        metadata={"name": data["name"], "amount_cents": data["amount_cents"], "billing_cycle": data["billing_cycle"]}
    )
    return jsonify(dict(sub)), 201


@bp.get("/subscriptions/<int:sub_id>")
@login_required
def get_subscription(sub_id):
    """Retrieve a single subscription ensuring user ownership."""
    user_id = session.get("user_id")
    sub = db.get_subscription(sub_id, user_id)
    if not sub:
        return jsonify(error="subscription not found"), 404
    return jsonify(dict(sub))


@bp.put("/subscriptions/<int:sub_id>")
@login_required
def update_subscription(sub_id):
    """Update an existing subscription ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_subscription(sub_id, user_id)
    if not existing:
        return jsonify(error="subscription not found"), 404

    data = validate_subscription(request.get_json(silent=True))
    # Capture old values for audit log
    old_data = dict(existing)
    db.update_subscription(sub_id, user_id, data)
    updated = db.get_subscription(sub_id, user_id)
    # Audit log: subscription update
    db.audit_log(
        action="subscription_update",
        entity_type="subscription",
        entity_id=str(sub_id),
        user_id=user_id,
        metadata={"old": old_data, "new": dict(updated)}
    )
    return jsonify(dict(updated)), 200


@bp.delete("/subscriptions/<int:sub_id>")
@login_required
def delete_subscription(sub_id):
    """Delete a subscription ensuring user ownership."""
    user_id = session.get("user_id")
    existing = db.get_subscription(sub_id, user_id)
    if not existing:
        return jsonify(error="subscription not found"), 404

    # Capture data for audit log before deletion
    deleted_data = dict(existing)

    if not db.delete_subscription(sub_id, user_id):
        return jsonify(error="subscription not found"), 404

    # Audit log: subscription delete
    db.audit_log(
        action="subscription_delete",
        entity_type="subscription",
        entity_id=str(sub_id),
        user_id=user_id,
        metadata=deleted_data
    )
    return "", 204


@bp.get("/subscriptions/upcoming")
@login_required
def get_upcoming_subscriptions():
    """Get subscriptions with upcoming renewals."""
    user_id = session.get("user_id")
    days_ahead = request.args.get("days", type=int)
    if days_ahead is None:
        days_ahead = request.args.get("days_ahead", 30, type=int)

    upcoming = db.get_upcoming_renewals(user_id, days_ahead)
    return jsonify(subscriptions=[dict(s) for s in upcoming])


@bp.get("/subscriptions/totals")
@login_required
def get_subscription_totals():
    """Get monthly and annual subscription totals."""
    user_id = session.get("user_id")
    totals = db.get_subscription_totals(user_id)
    totals["currency"] = current_app.config.get("BASE_CURRENCY", "INR")
    return jsonify(totals)


# ============================================================================
# Notification Endpoints (User-Isolated)
# ============================================================================

@bp.get("/notifications")
@login_required
def list_notifications():
    """List notifications for the authenticated user with pagination."""
    user_id = session.get("user_id")
    is_read = request.args.get("is_read", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = min(max(request.args.get("per_page", 20, type=int), 1), 100)
    offset = (page - 1) * per_page

    notifications = db.list_notifications(user_id, is_read=is_read, limit=per_page, offset=offset)
    total = db.count_notifications(user_id, is_read=is_read)

    return jsonify(
        notifications=[dict(n) for n in notifications],
        pagination={
            "current_page": page,
            "per_page": per_page,
            "total_records": total,
            "total_pages": (total + per_page - 1) // per_page,
            "has_next": page * per_page < total,
            "has_previous": page > 1,
        }
    )


@bp.get("/notifications/unread-count")
@login_required
def get_unread_notification_count():
    """Get count of unread notifications."""
    user_id = session.get("user_id")
    count = db.count_notifications(user_id, is_read=0)
    return jsonify(unread_count=count)


@bp.get("/notifications/<int:notif_id>")
@login_required
def get_notification(notif_id):
    """Retrieve a single notification ensuring user ownership."""
    user_id = session.get("user_id")
    notif = db.get_notification(notif_id, user_id)
    if not notif:
        return jsonify(error="notification not found"), 404
    return jsonify(dict(notif))


@bp.post("/notifications/<int:notif_id>/read")
@login_required
def mark_notification_read(notif_id):
    """Mark a notification as read."""
    user_id = session.get("user_id")
    if not db.mark_notification_read(notif_id, user_id):
        return jsonify(error="notification not found"), 404
    return jsonify(success=True), 200


@bp.post("/notifications/read-all")
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read."""
    user_id = session.get("user_id")
    count = db.mark_all_notifications_read(user_id)
    return jsonify(marked=count), 200


@bp.delete("/notifications/<int:notif_id>")
@login_required
def delete_notification(notif_id):
    """Delete a notification."""
    user_id = session.get("user_id")
    if not db.delete_notification(notif_id, user_id):
        return jsonify(error="notification not found"), 404
    return "", 204


@bp.post("/notifications/check")
@login_required
def run_notification_checks():
    """Manually trigger notification checks for the user."""
    user_id = session.get("user_id")
    results = db.run_all_notification_checks(user_id)
    return jsonify(results)


# ============================================================================
# Financial Forecasting Endpoints (User-Isolated)
# ============================================================================

@bp.get("/forecast")
@login_required
def get_financial_forecast():
    """Generate financial forecast based on historical transaction data."""
    from datetime import datetime
    user_id = session.get("user_id")

    # Get months of history to analyze
    months = request.args.get("months", 6, type=int)
    if not 1 <= months <= 36:
        raise ValidationError("months must be between 1 and 36")

    # Get historical transactions
    conn = db.get_db()
    today = date.today()

    # Calculate date range safely across multiple years
    total_months = today.year * 12 + (today.month - 1) - (months - 1)
    start_year, start_month_zero = divmod(total_months, 12)
    start_month = start_month_zero + 1

    start_date = f"{start_year}-{start_month:02d}-01"
    end_date = today.isoformat()

    # Get monthly totals by category
    rows = conn.execute(
        """SELECT date, type, amount_cents, category
           FROM transactions
           WHERE user_id = ? AND date BETWEEN ? AND ?
           ORDER BY date ASC""",
        (user_id, start_date, end_date)
    ).fetchall()

    if len(rows) < 2:
        return jsonify(
            forecast=None,
            message="Insufficient historical data for forecasting. Need at least 2 months of transactions."
        )

    # Process by month
    monthly_data = {}
    for row in rows:
        dt = datetime.fromisoformat(row["date"])
        month_key = f"{dt.year}-{dt.month:02d}"
        if month_key not in monthly_data:
            monthly_data[month_key] = {"income": 0, "expense": 0, "categories": {}}

        amount = row["amount_cents"] / 100
        if row["type"] == "income":
            monthly_data[month_key]["income"] += amount
        else:
            monthly_data[month_key]["expense"] += amount
            cat = row["category"]
            monthly_data[month_key]["categories"][cat] = monthly_data[month_key]["categories"].get(cat, 0) + amount

    # Sort months
    sorted_months = sorted(monthly_data.keys())
    if len(sorted_months) < 2:
        return jsonify(
            forecast=None,
            message="Insufficient monthly data points for forecasting."
        )

    # Simple moving average forecast (last 3 months)
    recent_months = sorted_months[-3:] if len(sorted_months) >= 3 else sorted_months
    income_values = [monthly_data[m]["income"] for m in recent_months]
    expense_values = [monthly_data[m]["expense"] for m in recent_months]

    avg_income = sum(income_values) / len(income_values)
    avg_expense = sum(expense_values) / len(expense_values)

    # Category-wise forecast where data exists
    category_forecasts = {}
    all_categories = set()
    for m in recent_months:
        all_categories.update(monthly_data[m]["categories"].keys())

    for cat in all_categories:
        cat_values = [monthly_data[m]["categories"].get(cat, 0) for m in recent_months]
        if cat_values and sum(cat_values) > 0:
            category_forecasts[cat] = round(sum(cat_values) / len(cat_values), 2)

    # Linear regression for trend (simple implementation)
    def linear_trend(values):
        n = len(values)
        if n < 2:
            return 0
        x = list(range(n))
        y = values
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(x[i] * x[i] for i in range(n))

        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            return 0

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope

    income_trend = linear_trend(income_values)
    expense_trend = linear_trend(expense_values)

    # Next month forecast
    next_month_income = round(avg_income + income_trend, 2)
    next_month_expense = round(avg_expense + expense_trend, 2)
    next_month_savings = round(next_month_income - next_month_expense, 2)

    # Confidence indicator based on data volume and consistency
    cv_income = 0
    cv_expense = 0
    if len(income_values) > 1:
        import statistics
        try:
            cv_income = statistics.stdev(income_values) / statistics.mean(income_values) if statistics.mean(income_values) > 0 else 0
            cv_expense = statistics.stdev(expense_values) / statistics.mean(expense_values) if statistics.mean(expense_values) > 0 else 0
        except:
            pass

    confidence = "high"
    if cv_income > 0.5 or cv_expense > 0.5:
        confidence = "low"
    elif cv_income > 0.3 or cv_expense > 0.3:
        confidence = "medium"

    history = [
        {
            "month": m,
            "income": round(monthly_data[m]["income"], 2),
            "expense": round(monthly_data[m]["expense"], 2),
        }
        for m in sorted_months
    ]

    return jsonify(
        forecast={
            "period": "next_month",
            "predicted_income": next_month_income,
            "predicted_expense": next_month_expense,
            "predicted_savings": next_month_savings,
            "income_trend": round(income_trend, 2),
            "expense_trend": round(expense_trend, 2),
            "category_forecasts": category_forecasts,
            "history": history,
            "confidence": confidence,
            "based_on_months": len(sorted_months),
            "data_quality": {
                "income_cv": round(cv_income, 3),
                "expense_cv": round(cv_expense, 3),
            },
            "disclaimer": "Forecasts are estimates based on historical data and simple statistical methods. They are not guaranteed financial outcomes."
        }
    )

