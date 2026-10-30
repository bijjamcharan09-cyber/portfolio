"""Input checks. Never trust data coming from the browser."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CATEGORIES = {
    "expense": ["Food", "Transport", "Rent", "Bills", "Shopping", "Health", "Education", "Entertainment", "Other"],
    "income": ["Salary", "Freelance", "Gift", "Investment", "Other"],
}


class ValidationError(ValueError):
    pass


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValidationError("date must look like YYYY-MM-DD")


def validate_transaction(data):
    if not isinstance(data, dict):
        raise ValidationError("send a JSON body")

    kind = data.get("type")
    if kind not in CATEGORIES:
        raise ValidationError("type must be 'income' or 'expense'")

    try:
        amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValidationError("amount must be a number")
    if not 0 < amount <= Decimal("1000000000"):
        raise ValidationError("amount must be greater than 0")

    category = data.get("category")
    if category not in CATEGORIES[kind]:
        raise ValidationError(f"category must be one of: {', '.join(CATEGORIES[kind])}")

    note = str(data.get("note") or "").strip()
    if len(note) > 200:
        raise ValidationError("note must be 200 characters or fewer")

    day = parse_date(data["date"]) if data.get("date") else date.today()

    return {
        "type": kind,
        "amount_cents": int(amount * 100),
        "category": category,
        "note": note,
        "date": day.isoformat(),
    }
