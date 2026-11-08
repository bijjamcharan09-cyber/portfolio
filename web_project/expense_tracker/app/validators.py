"""Input checks. Never trust data coming from the browser."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

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


def validate_registration(data):
    """Validate user registration inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid registration payload.")

    full_name = str(data.get("full_name") or "").strip()
    if not full_name:
        raise ValidationError("Full name is required.")
    if len(full_name) > 100:
        raise ValidationError("Full name must be 100 characters or fewer.")

    email = str(data.get("email") or "").strip().lower()
    if not email:
        raise ValidationError("Email address is required.")
    if len(email) > 255 or not EMAIL_REGEX.match(email):
        raise ValidationError("Please provide a valid email address.")

    password = str(data.get("password") or "")
    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if len(password) > 128:
        raise ValidationError("Password must be 128 characters or fewer.")

    confirm_password = str(data.get("confirm_password") or "")
    if password != confirm_password:
        raise ValidationError("Passwords do not match.")

    return {
        "full_name": full_name,
        "email": email,
        "password": password,
    }


def validate_login(data):
    """Validate user login credentials."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid login payload.")

    email = str(data.get("email") or "").strip().lower()
    if not email:
        raise ValidationError("Email address is required.")

    password = str(data.get("password") or "")
    if not password:
        raise ValidationError("Password is required.")

    return {
        "email": email,
        "password": password,
    }


def validate_profile_update(data):
    """Validate profile update inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid profile update payload.")

    result = {}
    if "full_name" in data:
        full_name = str(data.get("full_name") or "").strip()
        if not full_name:
            raise ValidationError("Full name cannot be empty.")
        if len(full_name) > 100:
            raise ValidationError("Full name must be 100 characters or fewer.")
        result["full_name"] = full_name

    new_password = str(data.get("new_password") or "")
    if new_password:
        current_password = str(data.get("current_password") or "")
        if not current_password:
            raise ValidationError("Current password is required to set a new password.")
        if len(new_password) < 8:
            raise ValidationError("New password must be at least 8 characters long.")
        if len(new_password) > 128:
            raise ValidationError("New password must be 128 characters or fewer.")
        confirm_new = str(data.get("confirm_new_password") or "")
        if new_password != confirm_new:
            raise ValidationError("New passwords do not match.")
        result["current_password"] = current_password
        result["new_password"] = new_password

    return result


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
