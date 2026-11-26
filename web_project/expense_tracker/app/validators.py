"""Input checks. Never trust data coming from the browser."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

CATEGORIES = {
    "expense": ["Food", "Transport", "Rent", "Bills", "Shopping", "Health", "Education", "Entertainment", "Other"],
    "income": ["Salary", "Freelance", "Gift", "Investment", "Other"],
}

BUDGET_PERIODS = ["weekly", "monthly"]
RECURRING_FREQUENCIES = ["daily", "weekly", "monthly", "yearly"]
SUBSCRIPTION_CYCLES = ["monthly", "quarterly", "yearly", "custom"]
SUBSCRIPTION_STATUSES = ["active", "paused", "cancelled", "expired"]


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


def validate_budget(data):
    """Validate budget creation/update inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid budget payload.")

    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Budget name is required.")
    if len(name) > 100:
        raise ValidationError("Budget name must be 100 characters or fewer.")

    period = data.get("period")
    if period not in BUDGET_PERIODS:
        raise ValidationError(f"period must be one of: {', '.join(BUDGET_PERIODS)}")

    category = data.get("category")
    if category is not None:
        category = str(category).strip()
        if category and len(category) > 50:
            raise ValidationError("Category must be 50 characters or fewer.")

    try:
        amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("amount must be a number")
    if not 0 < amount <= Decimal("1000000000"):
        raise ValidationError("amount must be greater than 0")

    warning_threshold = data.get("warning_threshold", 80)
    try:
        warning_threshold = int(warning_threshold)
    except (ValueError, TypeError):
        raise ValidationError("warning_threshold must be a number")
    if not 1 <= warning_threshold <= 100:
        raise ValidationError("warning_threshold must be between 1 and 100")

    start_date = data.get("start_date")
    if not start_date:
        raise ValidationError("start_date is required")
    try:
        parse_date(start_date)
    except ValidationError:
        raise ValidationError("start_date must be YYYY-MM-DD")

    end_date = data.get("end_date")
    if end_date:
        try:
            parse_date(end_date)
        except ValidationError:
            raise ValidationError("end_date must be YYYY-MM-DD")

    is_active = data.get("is_active", 1)
    if is_active not in (0, 1):
        raise ValidationError("is_active must be 0 or 1")

    return {
        "name": name,
        "period": period,
        "category": category,
        "amount_cents": int(amount * 100),
        "warning_threshold": warning_threshold,
        "start_date": start_date,
        "end_date": end_date,
        "is_active": is_active,
    }


def validate_recurring_transaction(data):
    """Validate recurring transaction creation/update inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid recurring transaction payload.")

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

    payment_method = str(data.get("payment_method") or "").strip()
    if len(payment_method) > 50:
        raise ValidationError("payment_method must be 50 characters or fewer")

    frequency = data.get("frequency")
    if frequency not in RECURRING_FREQUENCIES:
        raise ValidationError(f"frequency must be one of: {', '.join(RECURRING_FREQUENCIES)}")

    start_date = data.get("start_date")
    if not start_date:
        raise ValidationError("start_date is required")
    try:
        parse_date(start_date)
    except ValidationError:
        raise ValidationError("start_date must be YYYY-MM-DD")

    end_date = data.get("end_date")
    if end_date:
        try:
            parse_date(end_date)
        except ValidationError:
            raise ValidationError("end_date must be YYYY-MM-DD")

    next_due_date = data.get("next_due_date")
    if not next_due_date:
        raise ValidationError("next_due_date is required")
    try:
        parse_date(next_due_date)
    except ValidationError:
        raise ValidationError("next_due_date must be YYYY-MM-DD")

    is_active = data.get("is_active", 1)
    if is_active not in (0, 1):
        raise ValidationError("is_active must be 0 or 1")

    is_paused = data.get("is_paused", 0)
    if is_paused not in (0, 1):
        raise ValidationError("is_paused must be 0 or 1")

    return {
        "type": kind,
        "amount_cents": int(amount * 100),
        "category": category,
        "note": note,
        "payment_method": payment_method,
        "frequency": frequency,
        "start_date": start_date,
        "end_date": end_date,
        "next_due_date": next_due_date,
        "is_active": is_active,
        "is_paused": is_paused,
    }


def validate_financial_goal(data):
    """Validate financial goal creation/update inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid financial goal payload.")

    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Goal name is required.")
    if len(name) > 100:
        raise ValidationError("Goal name must be 100 characters or fewer.")

    try:
        target_amount = Decimal(str(data.get("target_amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("target_amount must be a number")
    if not 0 < target_amount <= Decimal("1000000000"):
        raise ValidationError("target_amount must be greater than 0")

    current_amount = data.get("current_amount", 0)
    try:
        current_amount = Decimal(str(current_amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("current_amount must be a number")
    if current_amount < 0:
        raise ValidationError("current_amount cannot be negative")

    target_date = data.get("target_date")
    if target_date:
        try:
            parse_date(target_date)
        except ValidationError:
            raise ValidationError("target_date must be YYYY-MM-DD")

    description = str(data.get("description") or "").strip()
    if len(description) > 500:
        raise ValidationError("description must be 500 characters or fewer")

    is_completed = data.get("is_completed", 0)
    if is_completed not in (0, 1):
        raise ValidationError("is_completed must be 0 or 1")

    completed_at = data.get("completed_at")
    if completed_at:
        try:
            parse_date(completed_at)
        except ValidationError:
            raise ValidationError("completed_at must be YYYY-MM-DD")

    return {
        "name": name,
        "target_amount_cents": int(target_amount * 100),
        "current_amount_cents": int(current_amount * 100),
        "target_date": target_date,
        "description": description,
        "is_completed": is_completed,
        "completed_at": completed_at,
    }


def validate_goal_contribution(data):
    """Validate goal contribution inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid contribution payload.")

    try:
        amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("amount must be a number")
    if not 0 < amount <= Decimal("1000000000"):
        raise ValidationError("amount must be greater than 0")

    note = str(data.get("note") or "").strip()
    if len(note) > 200:
        raise ValidationError("note must be 200 characters or fewer")

    day = parse_date(data["date"]) if data.get("date") else date.today()

    return {
        "amount_cents": int(amount * 100),
        "note": note,
        "date": day.isoformat(),
    }


def validate_subscription(data):
    """Validate subscription creation/update inputs."""
    if not isinstance(data, dict):
        raise ValidationError("Invalid subscription payload.")

    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Subscription name is required.")
    if len(name) > 100:
        raise ValidationError("Subscription name must be 100 characters or fewer.")

    try:
        amount = Decimal(str(data.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("amount must be a number")
    if not 0 < amount <= Decimal("1000000000"):
        raise ValidationError("amount must be greater than 0")

    currency = str(data.get("currency") or "INR").strip().upper()
    if len(currency) != 3:
        raise ValidationError("currency must be a 3-letter code")

    billing_cycle = data.get("billing_cycle")
    if billing_cycle not in SUBSCRIPTION_CYCLES:
        raise ValidationError(f"billing_cycle must be one of: {', '.join(SUBSCRIPTION_CYCLES)}")

    custom_cycle_days = data.get("custom_cycle_days")
    if billing_cycle == "custom":
        if not custom_cycle_days:
            raise ValidationError("custom_cycle_days is required for custom billing cycle")
        try:
            custom_cycle_days = int(custom_cycle_days)
        except (ValueError, TypeError):
            raise ValidationError("custom_cycle_days must be a number")
        if not 1 <= custom_cycle_days <= 3650:
            raise ValidationError("custom_cycle_days must be between 1 and 3650")
    else:
        custom_cycle_days = None

    renewal_date = data.get("renewal_date")
    if not renewal_date:
        raise ValidationError("renewal_date is required")
    try:
        parse_date(renewal_date)
    except ValidationError:
        raise ValidationError("renewal_date must be YYYY-MM-DD")

    status = data.get("status", "active")
    if status not in SUBSCRIPTION_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(SUBSCRIPTION_STATUSES)}")

    category = str(data.get("category") or "Subscription").strip()
    if len(category) > 50:
        raise ValidationError("category must be 50 characters or fewer")

    payment_method = str(data.get("payment_method") or "").strip()
    if len(payment_method) > 50:
        raise ValidationError("payment_method must be 50 characters or fewer")

    notes = str(data.get("notes") or "").strip()
    if len(notes) > 500:
        raise ValidationError("notes must be 500 characters or fewer")

    return {
        "name": name,
        "amount_cents": int(amount * 100),
        "currency": currency,
        "billing_cycle": billing_cycle,
        "custom_cycle_days": custom_cycle_days,
        "renewal_date": renewal_date,
        "status": status,
        "category": category,
        "payment_method": payment_method,
        "notes": notes,
    }
