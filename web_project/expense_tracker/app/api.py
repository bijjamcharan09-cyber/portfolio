"""REST API endpoints. Routes stay thin: validate -> call a helper -> return JSON."""
from datetime import date

from flask import Blueprint, Response, current_app, jsonify, request

from . import db
from .services.exchange import ExchangeError, get_rate
from .services.reports import date_range, render_chart, summarize
from .validators import CATEGORIES, ValidationError, parse_date, validate_transaction

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


@bp.get("/categories")
def categories():
    return jsonify(CATEGORIES)


@bp.get("/transactions")
def list_transactions():
    start, end = _range()
    return jsonify([db.row_to_dict(r) for r in db.list_transactions(start, end)])


@bp.post("/transactions")
def create_transaction():
    data = validate_transaction(request.get_json(silent=True))
    new_id = db.add_transaction(data)
    return jsonify(db.row_to_dict(db.get_transaction(new_id))), 201


@bp.delete("/transactions/<int:tx_id>")
def delete_transaction(tx_id):
    if not db.delete_transaction(tx_id):
        return jsonify(error="transaction not found"), 404
    return "", 204


@bp.get("/reports/summary")
def report_summary():
    start, end = _range()
    return jsonify(summarize(start, end))


@bp.get("/reports/chart.png")
def report_chart():
    start, end = _range()
    return Response(render_chart(summarize(start, end)), mimetype="image/png")


@bp.get("/convert")
def convert_balance():
    """Convert the period's balance into another currency using a live rate."""
    target = request.args.get("to", "").upper()
    if len(target) != 3 or not target.isalpha():
        raise ValidationError("'to' must be a 3-letter currency code, e.g. EUR")
    start, end = _range()
    base = current_app.config["BASE_CURRENCY"]
    balance = summarize(start, end)["balance"]
    try:
        rate = get_rate(base, target)
    except ExchangeError as err:
        return jsonify(error=str(err)), 502
    return jsonify(base=base, to=target, rate=rate, balance=balance, converted=round(balance * rate, 2))
