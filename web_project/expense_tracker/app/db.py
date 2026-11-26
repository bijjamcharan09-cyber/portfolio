"""Database abstraction supporting local SQLite and remote Turso (hosted libSQL).
Money is stored as integer cents to avoid floating-point rounding errors.
All queries use parameterized (?) placeholders to prevent SQL injection.
"""
import logging
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path

from flask import current_app, g

logger = logging.getLogger(__name__)

# Import Turso / libSQL drivers safely
try:
    import turso_serverless
except ImportError:
    turso_serverless = None

try:
    import libsql
except ImportError:
    libsql = None

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)",
    """CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    type         TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    date         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_user_date_type ON transactions(user_id, date, type)",
    """CREATE TABLE IF NOT EXISTS guest_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guest_id       TEXT    NOT NULL,
    type           TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    category       TEXT    NOT NULL,
    note           TEXT    NOT NULL DEFAULT '',
    payment_method TEXT    NOT NULL DEFAULT '',
    date           TEXT    NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at     TEXT    NOT NULL
)""",
    "CREATE INDEX IF NOT EXISTS idx_guest_tx_guest ON guest_transactions(guest_id)",
    "CREATE INDEX IF NOT EXISTS idx_guest_tx_expires ON guest_transactions(expires_at)",
    """CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    action        TEXT    NOT NULL,
    entity_type   TEXT,
    entity_id     TEXT,
    timestamp     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    request_id    TEXT,
    metadata_json TEXT
)""",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id)",
    # Release 2 tables (idempotent, matches 003_release2_tables.sql)
    """CREATE TABLE IF NOT EXISTS budgets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name              TEXT    NOT NULL,
    period            TEXT    NOT NULL CHECK (period IN ('weekly', 'monthly')),
    category          TEXT,
    amount_cents      INTEGER NOT NULL CHECK (amount_cents > 0),
    warning_threshold INTEGER NOT NULL DEFAULT 80 CHECK (warning_threshold BETWEEN 1 AND 100),
    start_date        TEXT    NOT NULL,
    end_date          TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_budgets_user_id ON budgets(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_budgets_active ON budgets(user_id, is_active)",
    """CREATE TABLE IF NOT EXISTS recurring_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type           TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    category       TEXT    NOT NULL,
    note           TEXT    NOT NULL DEFAULT '',
    payment_method TEXT    NOT NULL DEFAULT '',
    frequency      TEXT    NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
    start_date     TEXT    NOT NULL,
    end_date       TEXT,
    last_generated TEXT,
    next_due_date  TEXT    NOT NULL,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_paused      INTEGER NOT NULL DEFAULT 0 CHECK (is_paused IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_recurring_user_id ON recurring_transactions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_recurring_next_due ON recurring_transactions(next_due_date)",
    "CREATE INDEX IF NOT EXISTS idx_recurring_active ON recurring_transactions(user_id, is_active, is_paused)",
    """CREATE TABLE IF NOT EXISTS financial_goals (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                 TEXT    NOT NULL,
    target_amount_cents  INTEGER NOT NULL CHECK (target_amount_cents > 0),
    current_amount_cents INTEGER NOT NULL DEFAULT 0 CHECK (current_amount_cents >= 0),
    target_date          TEXT,
    description          TEXT    NOT NULL DEFAULT '',
    is_completed         INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    completed_at         TEXT,
    created_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_goals_user_id ON financial_goals(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_goals_completed ON financial_goals(user_id, is_completed)",
    """CREATE TABLE IF NOT EXISTS goal_contributions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id      INTEGER NOT NULL REFERENCES financial_goals(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    note         TEXT    NOT NULL DEFAULT '',
    date         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_contributions_goal_id ON goal_contributions(goal_id)",
    "CREATE INDEX IF NOT EXISTS idx_contributions_user_id ON goal_contributions(user_id)",
    """CREATE TABLE IF NOT EXISTS subscriptions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name              TEXT    NOT NULL,
    amount_cents      INTEGER NOT NULL CHECK (amount_cents > 0),
    currency          TEXT    NOT NULL DEFAULT 'INR',
    billing_cycle     TEXT    NOT NULL CHECK (billing_cycle IN ('monthly', 'quarterly', 'yearly', 'custom')),
    custom_cycle_days INTEGER,
    renewal_date      TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled', 'expired')),
    category          TEXT    NOT NULL DEFAULT 'Subscription',
    payment_method    TEXT    NOT NULL DEFAULT '',
    notes             TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(user_id, status)",
    """CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    message       TEXT    NOT NULL,
    entity_type   TEXT,
    entity_id     TEXT,
    is_read       INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    read_at       TEXT,
    metadata_json TEXT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
)""",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(user_id, is_read)",
]

# Backwards compatible full SCHEMA string
SCHEMA = ";\n".join(SCHEMA_STATEMENTS) + ";\n"


def _sanitize_message(message: str, token: str = "") -> str:
    """Ensure authentication tokens are never exposed in logs or exceptions."""
    if not message:
        return ""
    if token and token in message:
        message = message.replace(token, "[REDACTED]")
    return message


def _connect_turso(url: str, auth_token: str):
    """Open a connection to Turso using the best available driver with transient error retry."""
    if not url:
        raise ValueError("TURSO_DATABASE_URL is required for Turso connection.")

    max_attempts = 2
    last_err = None

    for attempt in range(1, max_attempts + 1):
        try:
            if turso_serverless is not None:
                conn = turso_serverless.connect(url, auth_token=auth_token or None)
                conn.row_factory = turso_serverless.Row
                return conn
            elif libsql is not None:
                conn = libsql.connect(database=url, auth_token=auth_token or None)
                return conn
            else:
                raise RuntimeError(
                    "No Turso client is installed. Please install 'turso_serverless' or 'libsql'."
                )
        except Exception as exc:
            last_err = exc
            safe_msg = _sanitize_message(str(exc), auth_token)
            if attempt < max_attempts:
                logger.warning(
                    "Transient connection failure to Turso (attempt %d/%d): %s. Retrying...",
                    attempt,
                    max_attempts,
                    safe_msg,
                )
                time.sleep(0.2)
            else:
                logger.error("Failed to connect to Turso after %d attempts: %s", max_attempts, safe_msg)

    sanitized_err_msg = _sanitize_message(str(last_err), auth_token)
    raise RuntimeError(f"Could not connect to Turso database: {sanitized_err_msg}") from None


def _connect_sqlite(db_path: str):
    """Open a local SQLite database connection with concurrency and durability pragmas."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row

    # Configure SQLite PRAGMAs for performance, concurrency, and integrity
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 10000;")  # 10s wait for locked tables
        if db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
    except Exception as exc:
        logger.warning("Could not set SQLite PRAGMA configuration: %s", exc)

    return conn


def get_db():
    """Retrieve or create the database connection for the current Flask request context."""
    if "db" in g:
        return g.db

    # Determine database mode from Flask configuration
    mode = current_app.config.get("DATABASE_MODE", "sqlite")
    is_testing = current_app.config.get("TESTING", False)

    # In testing mode or when explicitly set to sqlite, use SQLite
    if is_testing or mode == "sqlite":
        # Check 'DATABASE' first for test fixtures (e.g. tmp_path / "test.db")
        # then prioritize DATABASE_PATH (e.g. /data/expenses.db on Railway)
        if is_testing and current_app.config.get("DATABASE"):
            db_path = current_app.config.get("DATABASE")
        else:
            db_path = (
                current_app.config.get("DATABASE_PATH")
                or current_app.config.get("SQLITE_DATABASE_PATH")
                or current_app.config.get("DATABASE")
                or "data/tracker.db"
            )
        g.db = _connect_sqlite(db_path)
        return g.db

    if mode == "turso":
        url = current_app.config.get("TURSO_DATABASE_URL", "").strip()
        token = current_app.config.get("TURSO_AUTH_TOKEN", "").strip()

        if not url:
            raise RuntimeError(
                "DATABASE_MODE is 'turso' but TURSO_DATABASE_URL is not configured."
            )
        if (url.startswith("libsql://") or "turso.io" in url) and not token:
            raise RuntimeError(
                "TURSO_AUTH_TOKEN is required for remote Turso connection."
            )

        g.db = _connect_turso(url, token)
        return g.db

    raise ValueError(f"Unsupported DATABASE_MODE: '{mode}'. Must be 'sqlite' or 'turso'.")


def close_db(_error=None):
    """Close the database connection at the end of the Flask request lifecycle."""
    conn = g.pop("db", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def init_schema(conn=None):
    """Safely and repeatably initialize the database schema (non-destructive)."""
    close_when_done = False
    if conn is None:
        conn = get_db()

    try:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)

        # Ensure user_id column exists on transactions table (for pre-existing tables)
        try:
            cur = conn.execute("PRAGMA table_info(transactions)")
            columns = []
            for r in cur.fetchall():
                if isinstance(r, (tuple, list)):
                    columns.append(r[1])
                elif hasattr(r, "keys") and "name" in r.keys():
                    columns.append(r["name"])
            if "user_id" not in columns and len(columns) > 0:
                conn.execute(
                    "ALTER TABLE transactions ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
                )
        except Exception:
            pass

        
        # Ensure payment_method column exists on transactions table
        try:
            cur = conn.execute("PRAGMA table_info(transactions)")
            columns = []
            for r in cur.fetchall():
                if isinstance(r, (tuple, list)):
                    columns.append(r[1])
                elif hasattr(r, "keys") and "name" in r.keys():
                    columns.append(r["name"])
            if "payment_method" not in columns and len(columns) > 0:
                conn.execute("ALTER TABLE transactions ADD COLUMN payment_method TEXT DEFAULT ''")
        except Exception:
            pass

        conn.commit()
    finally:
        if close_when_done:
            conn.close()


def init_db(app):
    """Initialize database handling for the Flask app.
    Registers teardown handler and safely ensures schema is initialized.
    """
    app.teardown_appcontext(close_db)

    # Automatically ensure schema exists on both SQLite and Turso
    try:
        with app.app_context():
            init_schema()
    except Exception as exc:
        logger.warning("Could not auto-initialize database schema on startup: %s", exc)


def row_to_dict(row):
    """Convert a database row (sqlite3.Row or turso_serverless.Row) to an API dictionary."""
    if row is None:
        return None
    data = {
        "id": row["id"],
        "type": row["type"],
        "amount": row["amount_cents"] / 100,
        "category": row["category"],
        "note": row["note"],
        "date": row["date"],
    }
    # Include user_id if present in row
    try:
        if "user_id" in row.keys() and row["user_id"] is not None:
            data["user_id"] = row["user_id"]
    except Exception:
        pass
    # Include payment_method if present in row
    try:
        if "payment_method" in row.keys() and row["payment_method"]:
            data["payment_method"] = row["payment_method"]
    except Exception:
        pass
    return data


def user_to_dict(row):
    """Convert a user row to a safe public dictionary (never exposes password_hash)."""
    if row is None:
        return None
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


# ============================================================================
# User Database Operations (Multi-User & RBAC)
# ============================================================================

def create_user(full_name: str, email: str, password_hash: str, role: str = "user", is_active: int = 1) -> int:
    """Create a new user account and return the new user ID."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO users (full_name, email, password_hash, role, is_active) VALUES (?, ?, ?, ?, ?)",
        (full_name.strip(), email.strip().lower(), password_hash, role, 1 if is_active else 0),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_id(user_id: int):
    """Fetch a user record by ID (includes password_hash for internal auth checks)."""
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(email: str):
    """Fetch a user record by email (case-insensitive, includes password_hash)."""
    return get_db().execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip().lower(),)).fetchone()


def update_user(user_id: int, **fields) -> bool:
    """Update user fields (e.g. full_name, password_hash, is_active, role)."""
    allowed_fields = {"full_name", "password_hash", "is_active", "role"}
    updates = {k: v for k, v in fields.items() if k in allowed_fields}
    if not updates:
        return False

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [user_id]

    conn = get_db()
    cur = conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    """Delete a user account and cascade delete their transactions."""
    conn = get_db()
    # Explicitly delete user's transactions for SQLite drivers without foreign key cascades enabled
    conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def list_users() -> list:
    """List all registered users with their transaction counts (admin view)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.full_name, u.email, u.role, u.is_active, u.created_at,
               COUNT(t.id) as transaction_count
        FROM users u
        LEFT JOIN transactions t ON t.user_id = u.id
        GROUP BY u.id
        ORDER BY u.created_at DESC, u.id DESC
    """).fetchall()
    return [
        {
            "id": r["id"],
            "full_name": r["full_name"],
            "email": r["email"],
            "role": r["role"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "transaction_count": r["transaction_count"],
        }
        for r in rows
    ]


def count_users() -> int:
    """Count total registered users."""
    row = get_db().execute("SELECT COUNT(*) FROM users").fetchone()
    return row[0] if row else 0


def get_platform_stats() -> dict:
    """Calculate platform-wide statistics for the admin dashboard."""
    conn = get_db()
    total_users_row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    total_users = total_users_row[0] if total_users_row else 0

    active_users_row = conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()
    active_users = active_users_row[0] if active_users_row else 0

    tx_count_row = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
    total_tx = tx_count_row[0] if tx_count_row else 0

    volume_row = conn.execute("SELECT SUM(amount_cents) FROM transactions").fetchone()
    total_volume_cents = (volume_row[0] or 0) if volume_row else 0

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_transactions": total_tx,
        "total_volume": round(total_volume_cents / 100, 2),
    }


# ============================================================================
# Transaction Database Operations (User-Isolated)
# ============================================================================

def add_transaction(t, user_id=None):
    """Insert a new transaction and return its ID, isolating by user_id."""
    conn = get_db()
    uid = user_id or t.get("user_id")
    pm = str(t.get("payment_method") or "")

    try:
        if uid is not None:
            cur = conn.execute(
                "INSERT INTO transactions (user_id, type, amount_cents, category, note, payment_method, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, t["type"], t["amount_cents"], t["category"], t["note"], pm, t["date"]),
            )
        else:
            cur = conn.execute(
                "INSERT INTO transactions (type, amount_cents, category, note, payment_method, date) VALUES (?, ?, ?, ?, ?, ?)",
                (t["type"], t["amount_cents"], t["category"], t["note"], pm, t["date"]),
            )
    except Exception:
        if uid is not None:
            cur = conn.execute(
                "INSERT INTO transactions (user_id, type, amount_cents, category, note, date) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, t["type"], t["amount_cents"], t["category"], t["note"], t["date"]),
            )
        else:
            cur = conn.execute(
                "INSERT INTO transactions (type, amount_cents, category, note, date) VALUES (?, ?, ?, ?, ?)",
                (t["type"], t["amount_cents"], t["category"], t["note"], t["date"]),
            )
    conn.commit()
    return cur.lastrowid


def get_transaction(tx_id, user_id=None):
    """Fetch a single transaction by ID, optionally verifying ownership."""
    if user_id is not None:
        return get_db().execute(
            "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
            (tx_id, user_id),
        ).fetchone()
    return get_db().execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def list_transactions(start, end, user_id=None, page=1, per_page=None):
    """List transactions within the specified date range, isolating by user_id, with pagination."""
    if per_page is None:
        per_page = DEFAULT_PAGE_SIZE
    per_page = min(max(1, per_page), MAX_PAGE_SIZE)
    page = max(1, page)
    offset = (page - 1) * per_page

    s, e = start.isoformat(), end.isoformat()
    conn = get_db()

    if user_id is not None:
        # Count total records for pagination metadata
        count_row = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id = ? AND date BETWEEN ? AND ?",
            (user_id, s, e),
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, s, e, per_page, offset),
        ).fetchall()
    else:
        count_row = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE date BETWEEN ? AND ?", (s, e)
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            "SELECT * FROM transactions WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (s, e, per_page, offset),
        ).fetchall()

    return {
        "transactions": rows,
        "pagination": {
            "current_page": page,
            "per_page": per_page,
            "total_records": total,
            "total_pages": (total + per_page - 1) // per_page,
            "has_next": page * per_page < total,
            "has_previous": page > 1,
        },
    }


def update_transaction(tx_id, t, user_id=None) -> bool:
    """Update an existing transaction if owned by the user (IDOR prevention)."""
    conn = get_db()
    pm = str(t.get("payment_method") or "")
    try:
        if user_id is not None:
            cur = conn.execute(
                "UPDATE transactions SET type = ?, amount_cents = ?, category = ?, note = ?, payment_method = ?, date = ? WHERE id = ? AND user_id = ?",
                (t["type"], t["amount_cents"], t["category"], t["note"], pm, t["date"], tx_id, user_id),
            )
        else:
            cur = conn.execute(
                "UPDATE transactions SET type = ?, amount_cents = ?, category = ?, note = ?, payment_method = ?, date = ? WHERE id = ?",
                (t["type"], t["amount_cents"], t["category"], t["note"], pm, t["date"], tx_id),
            )
    except Exception:
        if user_id is not None:
            cur = conn.execute(
                "UPDATE transactions SET type = ?, amount_cents = ?, category = ?, note = ?, date = ? WHERE id = ? AND user_id = ?",
                (t["type"], t["amount_cents"], t["category"], t["note"], t["date"], tx_id, user_id),
            )
        else:
            cur = conn.execute(
                "UPDATE transactions SET type = ?, amount_cents = ?, category = ?, note = ?, date = ? WHERE id = ?",
                (t["type"], t["amount_cents"], t["category"], t["note"], t["date"], tx_id),
            )
    conn.commit()
    return cur.rowcount > 0


def delete_transaction(tx_id, user_id=None):
    """Delete a transaction by ID, optionally verifying ownership. Returns True if deleted."""
    conn = get_db()
    if user_id is not None:
        cur = conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
    else:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()
    return cur.rowcount > 0


# ============================================================================
# Guest Mode Isolated Database Operations
# ============================================================================

def add_guest_transaction(guest_id: str, t: dict, expires_at: str) -> int:
    """Insert a transaction into isolated temporary guest storage."""
    conn = get_db()
    pm = str(t.get("payment_method") or "")
    cur = conn.execute(
        "INSERT INTO guest_transactions (guest_id, type, amount_cents, category, note, payment_method, date, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (guest_id, t["type"], t["amount_cents"], t["category"], t["note"], pm, t["date"], expires_at),
    )
    conn.commit()
    return cur.lastrowid


def get_guest_transaction(guest_id: str, tx_id: int):
    """Retrieve a single guest transaction strictly scoped to guest_id."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return get_db().execute(
        "SELECT * FROM guest_transactions WHERE id = ? AND guest_id = ? AND expires_at > ?",
        (tx_id, guest_id, now_iso),
    ).fetchone()


def list_guest_transactions(guest_id: str, start=None, end=None, page=1, per_page=None):
    """List transactions for a guest session within optional date bounds, with pagination."""
    if per_page is None:
        per_page = DEFAULT_PAGE_SIZE
    per_page = min(max(1, per_page), MAX_PAGE_SIZE)
    page = max(1, page)
    offset = (page - 1) * per_page

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = get_db()

    if start and end:
        s, e = start.isoformat(), end.isoformat()
        count_row = conn.execute(
            "SELECT COUNT(*) FROM guest_transactions WHERE guest_id = ? AND expires_at > ? AND date BETWEEN ? AND ?",
            (guest_id, now_iso, s, e),
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            "SELECT * FROM guest_transactions WHERE guest_id = ? AND expires_at > ? AND date BETWEEN ? AND ? "
            "ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (guest_id, now_iso, s, e, per_page, offset),
        ).fetchall()
    else:
        count_row = conn.execute(
            "SELECT COUNT(*) FROM guest_transactions WHERE guest_id = ? AND expires_at > ?",
            (guest_id, now_iso),
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            "SELECT * FROM guest_transactions WHERE guest_id = ? AND expires_at > ? "
            "ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (guest_id, now_iso, per_page, offset),
        ).fetchall()

    return {
        "transactions": rows,
        "pagination": {
            "current_page": page,
            "per_page": per_page,
            "total_records": total,
            "total_pages": (total + per_page - 1) // per_page,
            "has_next": page * per_page < total,
            "has_previous": page > 1,
        },
    }


def update_guest_transaction(guest_id: str, tx_id: int, t: dict) -> bool:
    """Update a guest transaction strictly scoped to the active guest."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pm = str(t.get("payment_method") or "")
    conn = get_db()
    cur = conn.execute(
        "UPDATE guest_transactions SET type = ?, amount_cents = ?, category = ?, note = ?, payment_method = ?, date = ? "
        "WHERE id = ? AND guest_id = ? AND expires_at > ?",
        (t["type"], t["amount_cents"], t["category"], t["note"], pm, t["date"], tx_id, guest_id, now_iso),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_guest_transaction(guest_id: str, tx_id: int) -> bool:
    """Delete a guest transaction strictly scoped to the active guest."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM guest_transactions WHERE id = ? AND guest_id = ? AND expires_at > ?",
        (tx_id, guest_id, now_iso),
    )
    conn.commit()
    return cur.rowcount > 0


def delete_guest_data(guest_id: str) -> int:
    """Clean up all transactions for a specific guest upon exit or expiration."""
    conn = get_db()
    cur = conn.execute("DELETE FROM guest_transactions WHERE guest_id = ?", (guest_id,))
    conn.commit()
    return cur.rowcount


def cleanup_expired_guests() -> int:
    """Opportunistically purge expired guest transactions across the database."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn = get_db()
    cur = conn.execute("DELETE FROM guest_transactions WHERE expires_at <= ?", (now_iso,))
    conn.commit()
    return cur.rowcount


def seed_guest_sample_data(guest_id: str, expires_at: str):
    """Seed realistic financial records into isolated guest storage."""
    from datetime import date
    today = date.today()
    y, m = today.year, today.month

    # Generate dates safely within the current month
    d1 = date(y, m, 1).isoformat()
    d2 = date(y, m, min(3, today.day)).isoformat()
    d3 = date(y, m, min(5, today.day)).isoformat()
    d4 = date(y, m, min(7, today.day)).isoformat()
    d5 = date(y, m, min(9, today.day)).isoformat()
    d6 = date(y, m, min(10, today.day)).isoformat()
    d7 = date(y, m, min(11, today.day)).isoformat()

    sample_records = [
        {"type": "income", "amount_cents": 7500000, "category": "Salary", "note": "Monthly Tech Salary", "payment_method": "Direct Deposit", "date": d1},
        {"type": "expense", "amount_cents": 2200000, "category": "Rent", "note": "Apartment Monthly Rent", "payment_method": "Bank Transfer", "date": d2},
        {"type": "expense", "amount_cents": 345000, "category": "Bills", "note": "Fiber Broadband & Utilities", "payment_method": "UPI", "date": d3},
        {"type": "expense", "amount_cents": 482000, "category": "Food", "note": "Organic Supermarket Groceries", "payment_method": "Credit Card", "date": d4},
        {"type": "expense", "amount_cents": 210000, "category": "Transport", "note": "Metro Smartcard & Fuel", "payment_method": "Debit Card", "date": d5},
        {"type": "income", "amount_cents": 1850000, "category": "Freelance", "note": "UI/UX Design Consulting", "payment_method": "Direct Deposit", "date": d6},
        {"type": "expense", "amount_cents": 260000, "category": "Entertainment", "note": "Weekend Dining & Cinema", "payment_method": "Credit Card", "date": d7},
        {"type": "expense", "amount_cents": 145000, "category": "Health", "note": "Pharmacy & Health Vitamins", "payment_method": "Cash", "date": d7},
    ]

    for rec in sample_records:
        add_guest_transaction(guest_id, rec, expires_at)


# ============================================================================
# Audit Logging
# ============================================================================

def audit_log(action: str, entity_type: str = None, entity_id: str = None, user_id: int = None, request_id: str = None, metadata: dict = None) -> bool:
    """Record an audit log entry.

    Args:
        action: Action performed (e.g., 'login', 'logout', 'transaction_create', 'transaction_update', 'transaction_delete', 'excel_import', 'excel_export', 'admin_user_create', 'admin_user_delete', 'admin_user_toggle', 'password_change', 'profile_update')
        entity_type: Type of entity affected ('user', 'transaction', 'guest_transaction', 'excel')
        entity_id: ID of the entity affected
        user_id: ID of the user performing the action (None for guest/anonymous)
        request_id: Request ID for tracing
        metadata: Additional non-sensitive metadata (JSON-serializable dict)

    Returns:
        True if logged successfully
    """
    import json
    conn = get_db()
    try:
        meta_json = json.dumps(metadata) if metadata else None
        conn.execute(
            "INSERT INTO audit_log (user_id, action, entity_type, entity_id, request_id, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, action, entity_type, str(entity_id) if entity_id else None, request_id, meta_json),
        )
        conn.commit()
        return True
    except Exception as exc:
        # Never let audit failures break the main operation
        logger.warning("Audit log write failed: %s", exc)
        return False


def get_audit_logs(user_id: int = None, action: str = None, entity_type: str = None, limit: int = 100, offset: int = 0):
    """Retrieve audit logs with optional filters. Admin only."""
    conn = get_db()
    conditions = []
    params = []

    if user_id is not None:
        conditions.append("user_id = ?")
        params.append(user_id)
    if action:
        conditions.append("action = ?")
        params.append(action)
    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    params.extend([limit, offset])
    return conn.execute(
        f"SELECT * FROM audit_log {where_clause} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()


def count_audit_logs(user_id: int = None, action: str = None, entity_type: str = None) -> int:
    """Count audit logs with optional filters."""
    conn = get_db()
    conditions = []
    params = []

    if user_id is not None:
        conditions.append("user_id = ?")
        params.append(user_id)
    if action:
        conditions.append("action = ?")
        params.append(action)
    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    row = conn.execute(
        f"SELECT COUNT(*) FROM audit_log {where_clause}",
        params,
    ).fetchone()
    return row[0] if row else 0


# ============================================================================
# Budget Database Operations
# ============================================================================

def add_budget(user_id: int, budget: dict) -> int:
    """Create a new budget and return its ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO budgets (user_id, name, period, category, amount_cents, warning_threshold,
           start_date, end_date, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, budget["name"], budget["period"], budget.get("category"),
         budget["amount_cents"], budget.get("warning_threshold", 80),
         budget["start_date"], budget.get("end_date"), budget.get("is_active", 1))
    )
    conn.commit()
    return cur.lastrowid


def get_budget(budget_id: int, user_id: int):
    """Fetch a single budget by ID, verifying ownership."""
    return get_db().execute(
        "SELECT * FROM budgets WHERE id = ? AND user_id = ?", (budget_id, user_id)
    ).fetchone()


def list_budgets(user_id: int, is_active: int = None, period: str = None):
    """List budgets for a user with optional filters."""
    conn = get_db()
    conditions = ["user_id = ?"]
    params = [user_id]

    if is_active is not None:
        conditions.append("is_active = ?")
        params.append(is_active)
    if period:
        conditions.append("period = ?")
        params.append(period)

    where_clause = "WHERE " + " AND ".join(conditions)
    return conn.execute(
        f"SELECT * FROM budgets {where_clause} ORDER BY created_at DESC",
        params
    ).fetchall()


def update_budget(budget_id: int, user_id: int, budget: dict) -> bool:
    """Update an existing budget if owned by the user."""
    allowed_fields = {"name", "period", "category", "amount_cents", "warning_threshold",
                      "start_date", "end_date", "is_active"}
    updates = {k: v for k, v in budget.items() if k in allowed_fields}
    if not updates:
        return False

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [budget_id, user_id]

    conn = get_db()
    cur = conn.execute(f"UPDATE budgets SET {set_clause} WHERE id = ? AND user_id = ?", values)
    conn.commit()
    return cur.rowcount > 0


def delete_budget(budget_id: int, user_id: int) -> bool:
    """Delete a budget by ID, verifying ownership."""
    conn = get_db()
    cur = conn.execute("DELETE FROM budgets WHERE id = ? AND user_id = ?", (budget_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def get_budget_utilization(user_id: int, budget_id: int, start: date, end: date) -> dict:
    """Calculate budget utilization for a given period."""
    conn = get_db()
    budget = conn.execute(
        "SELECT * FROM budgets WHERE id = ? AND user_id = ?", (budget_id, user_id)
    ).fetchone()

    if not budget:
        return None

    # Get transactions in the budget period
    category = budget["category"]
    s, e = start.isoformat(), end.isoformat()

    if category:
        # Category-specific budget
        rows = conn.execute(
            """SELECT SUM(amount_cents) as total FROM transactions
               WHERE user_id = ? AND date BETWEEN ? AND ? AND category = ? AND type = 'expense'""",
            (user_id, s, e, category)
        ).fetchone()
    else:
        # Overall budget across all categories
        rows = conn.execute(
            """SELECT SUM(amount_cents) as total FROM transactions
               WHERE user_id = ? AND date BETWEEN ? AND ? AND type = 'expense'""",
            (user_id, s, e)
        ).fetchone()

    spent = rows["total"] if rows and rows["total"] else 0
    budget_amount = budget["amount_cents"]
    utilization_pct = (spent / budget_amount * 100) if budget_amount > 0 else 0

    return {
        "budget_id": budget_id,
        "budget_name": budget["name"],
        "period": budget["period"],
        "category": budget["category"],
        "budget_amount": budget_amount / 100,
        "spent": spent / 100,
        "remaining": (budget_amount - spent) / 100,
        "budget_amount_cents": budget_amount,
        "spent_cents": spent,
        "remaining_cents": budget_amount - spent,
        "utilization_pct": round(utilization_pct, 2),
        "warning_threshold": budget["warning_threshold"],
        "is_warning": utilization_pct >= budget["warning_threshold"],
        "is_exceeded": utilization_pct >= 100,
    }


def get_all_budget_utilizations(user_id: int, start: date, end: date, auto_period: bool = False) -> list:
    """Get utilization for all active budgets in a period."""
    from datetime import timedelta
    budgets = list_budgets(user_id, is_active=1)
    results = []
    today = date.today()
    for b in budgets:
        b_start, b_end = start, end
        if auto_period and b["period"] == "weekly":
            b_start = today - timedelta(days=today.weekday())
            b_end = b_start + timedelta(days=6)
        util = get_budget_utilization(user_id, b["id"], b_start, b_end)
        if util:
            results.append(util)
    return results


# ============================================================================
# Recurring Transaction Database Operations
# ============================================================================

def add_recurring_transaction(user_id: int, rt: dict) -> int:
    """Create a new recurring transaction and return its ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO recurring_transactions (user_id, type, amount_cents, category, note,
           payment_method, frequency, start_date, end_date, next_due_date, is_active, is_paused)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, rt["type"], rt["amount_cents"], rt["category"], rt.get("note", ""),
         rt.get("payment_method", ""), rt["frequency"], rt["start_date"],
         rt.get("end_date"), rt["next_due_date"], rt.get("is_active", 1), rt.get("is_paused", 0))
    )
    conn.commit()
    return cur.lastrowid


def get_recurring_transaction(rt_id: int, user_id: int):
    """Fetch a single recurring transaction by ID, verifying ownership."""
    return get_db().execute(
        "SELECT * FROM recurring_transactions WHERE id = ? AND user_id = ?", (rt_id, user_id)
    ).fetchone()


def list_recurring_transactions(user_id: int, is_active: int = None, is_paused: int = None):
    """List recurring transactions for a user with optional filters."""
    conn = get_db()
    conditions = ["user_id = ?"]
    params = [user_id]

    if is_active is not None:
        conditions.append("is_active = ?")
        params.append(is_active)
    if is_paused is not None:
        conditions.append("is_paused = ?")
        params.append(is_paused)

    where_clause = "WHERE " + " AND ".join(conditions)
    return conn.execute(
        f"SELECT * FROM recurring_transactions {where_clause} ORDER BY next_due_date ASC",
        params
    ).fetchall()


def update_recurring_transaction(rt_id: int, user_id: int, rt: dict) -> bool:
    """Update an existing recurring transaction if owned by the user."""
    allowed_fields = {"type", "amount_cents", "category", "note", "payment_method",
                      "frequency", "start_date", "end_date", "next_due_date",
                      "last_generated", "is_active", "is_paused"}
    updates = {k: v for k, v in rt.items() if k in allowed_fields}
    if not updates:
        return False

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [rt_id, user_id]

    conn = get_db()
    cur = conn.execute(
        f"UPDATE recurring_transactions SET {set_clause} WHERE id = ? AND user_id = ?",
        values
    )
    conn.commit()
    return cur.rowcount > 0


def delete_recurring_transaction(rt_id: int, user_id: int) -> bool:
    """Delete a recurring transaction by ID, verifying ownership."""
    conn = get_db()
    cur = conn.execute("DELETE FROM recurring_transactions WHERE id = ? AND user_id = ?", (rt_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def get_due_recurring_transactions(user_id: int, as_of: date = None) -> list:
    """Get recurring transactions that are due to generate a transaction on or before as_of date."""
    if as_of is None:
        as_of = date.today()

    conn = get_db()
    return conn.execute(
        """SELECT * FROM recurring_transactions
           WHERE user_id = ? AND is_active = 1 AND is_paused = 0
           AND next_due_date <= ?
           AND (end_date IS NULL OR end_date >= ?)""",
        (user_id, as_of.isoformat(), as_of.isoformat())
    ).fetchall()


def generate_recurring_transaction(user_id: int, rt: dict, tx_date: str) -> int:
    """Generate a single transaction from a recurring transaction template."""
    conn = get_db()
    # Handle both dict and sqlite3.Row objects
    def get_val(key, default=""):
        try:
            return rt[key]
        except (KeyError, TypeError):
            return default

    cur = conn.execute(
        """INSERT INTO transactions (user_id, type, amount_cents, category, note, payment_method, date)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, rt["type"], rt["amount_cents"], rt["category"],
         get_val("note", ""), get_val("payment_method", ""), tx_date)
    )
    conn.commit()
    return cur.lastrowid


def advance_recurring_transaction(rt_id: int, user_id: int, new_next_due: str, last_generated: str) -> bool:
    """Advance the recurring transaction to its next due date."""
    conn = get_db()
    cur = conn.execute(
        """UPDATE recurring_transactions
           SET next_due_date = ?, last_generated = ?, updated_at = ?
           WHERE id = ? AND user_id = ?""",
        (new_next_due, last_generated, datetime.now(timezone.utc).isoformat(), rt_id, user_id)
    )
    conn.commit()
    return cur.rowcount > 0


def process_due_recurring_for_user(user_id: int, process_date: date = None) -> list:
    """Atomically process all due recurring transactions for a user without duplicates."""
    from datetime import timedelta
    if process_date is None:
        process_date = date.today()

    process_iso = process_date.isoformat()
    due = get_due_recurring_transactions(user_id, process_date)
    generated = []

    for rt in due:
        # Guard against duplicate generation on the same date
        if rt["last_generated"] == process_iso:
            continue

        # Calculate next due date based on frequency
        next_due = date.fromisoformat(rt["next_due_date"])
        if rt["frequency"] == "daily":
            next_due = next_due + timedelta(days=1)
        elif rt["frequency"] == "weekly":
            next_due = next_due + timedelta(weeks=1)
        elif rt["frequency"] == "monthly":
            if next_due.month == 12:
                next_due = next_due.replace(year=next_due.year + 1, month=1)
            else:
                next_due = next_due.replace(month=next_due.month + 1)
        elif rt["frequency"] == "yearly":
            next_due = next_due.replace(year=next_due.year + 1)

        # Ensure next_due advances past process_date if it was multiple periods behind
        while next_due <= process_date:
            if rt["frequency"] == "daily":
                next_due = next_due + timedelta(days=1)
            elif rt["frequency"] == "weekly":
                next_due = next_due + timedelta(weeks=1)
            elif rt["frequency"] == "monthly":
                if next_due.month == 12:
                    next_due = next_due.replace(year=next_due.year + 1, month=1)
                else:
                    next_due = next_due.replace(month=next_due.month + 1)
            elif rt["frequency"] == "yearly":
                next_due = next_due.replace(year=next_due.year + 1)

        is_still_active = 0 if (rt["end_date"] and next_due > date.fromisoformat(rt["end_date"])) else 1
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Re-verify inside lock that another worker didn't already advance this recurring item
            current_rt = conn.execute(
                "SELECT next_due_date, last_generated, is_active, is_paused FROM recurring_transactions WHERE id = ? AND user_id = ?",
                (rt["id"], user_id)
            ).fetchone()
            if not current_rt or not current_rt["is_active"] or current_rt["is_paused"]:
                conn.rollback()
                continue
            if current_rt["next_due_date"] > process_iso or current_rt["last_generated"] == process_iso:
                conn.rollback()
                continue

            cur = conn.execute(
                """INSERT INTO transactions (user_id, type, amount_cents, category, note, payment_method, date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, rt["type"], rt["amount_cents"], rt["category"],
                 rt["note"] or "", rt["payment_method"] or "", process_iso)
            )
            tx_id = cur.lastrowid

            conn.execute(
                """UPDATE recurring_transactions
                   SET next_due_date = ?, last_generated = ?, is_active = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (next_due.isoformat(), process_iso, is_still_active, datetime.now(timezone.utc).isoformat(), rt["id"], user_id)
            )
            conn.commit()
            generated.append({
                "recurring_id": rt["id"],
                "transaction_id": tx_id,
                "next_due_date": next_due.isoformat(),
                "frequency": rt["frequency"],
            })
        except Exception:
            conn.rollback()
            raise

    return generated


# ============================================================================
# Financial Goals Database Operations
# ============================================================================

def add_financial_goal(user_id: int, goal: dict) -> int:
    """Create a new financial goal and return its ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO financial_goals (user_id, name, target_amount_cents, current_amount_cents,
           target_date, description, is_completed)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, goal["name"], goal["target_amount_cents"], goal.get("current_amount_cents", 0),
         goal.get("target_date"), goal.get("description", ""), goal.get("is_completed", 0))
    )
    conn.commit()
    return cur.lastrowid


def get_financial_goal(goal_id: int, user_id: int):
    """Fetch a single financial goal by ID, verifying ownership."""
    return get_db().execute(
        "SELECT * FROM financial_goals WHERE id = ? AND user_id = ?", (goal_id, user_id)
    ).fetchone()


def list_financial_goals(user_id: int, is_completed: int = None):
    """List financial goals for a user with optional filter."""
    conn = get_db()
    conditions = ["user_id = ?"]
    params = [user_id]

    if is_completed is not None:
        conditions.append("is_completed = ?")
        params.append(is_completed)

    where_clause = "WHERE " + " AND ".join(conditions)
    return conn.execute(
        f"SELECT * FROM financial_goals {where_clause} ORDER BY created_at DESC",
        params
    ).fetchall()


def update_financial_goal(goal_id: int, user_id: int, goal: dict) -> bool:
    """Update an existing financial goal if owned by the user."""
    allowed_fields = {"name", "target_amount_cents", "current_amount_cents",
                      "target_date", "description", "is_completed", "completed_at"}
    updates = {k: v for k, v in goal.items() if k in allowed_fields}
    if not updates:
        return False

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [goal_id, user_id]

    conn = get_db()
    cur = conn.execute(
        f"UPDATE financial_goals SET {set_clause} WHERE id = ? AND user_id = ?",
        values
    )
    conn.commit()
    return cur.rowcount > 0


def delete_financial_goal(goal_id: int, user_id: int) -> bool:
    """Delete a financial goal by ID, verifying ownership."""
    conn = get_db()
    cur = conn.execute("DELETE FROM financial_goals WHERE id = ? AND user_id = ?", (goal_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def add_goal_contribution(goal_id: int, user_id: int, contribution: dict) -> int:
    """Add a contribution to a financial goal and update goal progress atomically."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        # Insert contribution
        cur = conn.execute(
            """INSERT INTO goal_contributions (goal_id, user_id, amount_cents, note, date)
               VALUES (?, ?, ?, ?, ?)""",
            (goal_id, user_id, contribution["amount_cents"],
             contribution.get("note", ""), contribution["date"])
        )
        contribution_id = cur.lastrowid

        # Update goal current amount
        conn.execute(
            """UPDATE financial_goals
               SET current_amount_cents = current_amount_cents + ?, updated_at = ?
               WHERE id = ? AND user_id = ?""",
            (contribution["amount_cents"], datetime.now(timezone.utc).isoformat(), goal_id, user_id)
        )

        # Check if goal is now completed
        goal = conn.execute(
            "SELECT target_amount_cents, current_amount_cents FROM financial_goals WHERE id = ?",
            (goal_id,)
        ).fetchone()

        if goal and goal["current_amount_cents"] >= goal["target_amount_cents"]:
            conn.execute(
                """UPDATE financial_goals
                   SET is_completed = 1, completed_at = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat(), goal_id, user_id)
            )

        conn.commit()
        return contribution_id
    except Exception as exc:
        conn.rollback()
        raise exc


def get_goal_contributions(goal_id: int, user_id: int):
    """Get all contributions for a goal, verifying ownership."""
    conn = get_db()
    return conn.execute(
        """SELECT gc.* FROM goal_contributions gc
           JOIN financial_goals fg ON gc.goal_id = fg.id
           WHERE gc.goal_id = ? AND fg.user_id = ?
           ORDER BY gc.date DESC, gc.id DESC""",
        (goal_id, user_id)
    ).fetchall()


def get_goal_progress(goal_id: int, user_id: int) -> dict:
    """Calculate goal progress including estimated completion."""
    conn = get_db()
    goal = conn.execute(
        "SELECT * FROM financial_goals WHERE id = ? AND user_id = ?", (goal_id, user_id)
    ).fetchone()

    if not goal:
        return None

    target = goal["target_amount_cents"]
    current = goal["current_amount_cents"]
    pct = (current / target * 100) if target > 0 else 0

    # Get contributions for velocity calculation
    contributions = conn.execute(
        """SELECT amount_cents, date FROM goal_contributions
           WHERE goal_id = ? ORDER BY date ASC""",
        (goal_id,)
    ).fetchall()

    estimated_completion = None
    if len(contributions) >= 2:
        # Simple linear regression based on contribution dates and amounts
        try:
            from datetime import datetime
            dates = [datetime.fromisoformat(c["date"]).timestamp() for c in contributions]
            amounts = [c["amount_cents"] for c in contributions]

            # Calculate average daily contribution rate
            if dates[-1] > dates[0]:
                days_span = (dates[-1] - dates[0]) / 86400
                total_contributed = sum(amounts)
                daily_rate = total_contributed / days_span if days_span > 0 else 0

                if daily_rate > 0:
                    remaining = target - current
                    days_to_complete = remaining / daily_rate
                    estimated_completion = datetime.fromtimestamp(
                        datetime.now().timestamp() + days_to_complete * 86400
                    ).date().isoformat()
        except Exception:
            pass

    return {
        "goal_id": goal_id,
        "name": goal["name"],
        "target_amount": target / 100,
        "current_amount": current / 100,
        "remaining_amount": max(0, (target - current) / 100),
        "progress_pct": round(pct, 2),
        "is_completed": bool(goal["is_completed"]),
        "target_date": goal["target_date"],
        "estimated_completion": estimated_completion,
        "description": goal["description"],
    }


# ============================================================================
# Subscriptions Database Operations
# ============================================================================

def add_subscription(user_id: int, sub: dict) -> int:
    """Create a new subscription and return its ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO subscriptions (user_id, name, amount_cents, currency, billing_cycle,
           custom_cycle_days, renewal_date, status, category, payment_method, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, sub["name"], sub["amount_cents"], sub.get("currency", "INR"),
         sub["billing_cycle"], sub.get("custom_cycle_days"), sub["renewal_date"],
         sub.get("status", "active"), sub.get("category", "Subscription"),
         sub.get("payment_method", ""), sub.get("notes", ""))
    )
    conn.commit()
    return cur.lastrowid


def get_subscription(sub_id: int, user_id: int):
    """Fetch a single subscription by ID, verifying ownership."""
    return get_db().execute(
        "SELECT * FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id)
    ).fetchone()


def list_subscriptions(user_id: int, status: str = None):
    """List subscriptions for a user with optional status filter."""
    conn = get_db()
    conditions = ["user_id = ?"]
    params = [user_id]

    if status:
        conditions.append("status = ?")
        params.append(status)

    where_clause = "WHERE " + " AND ".join(conditions)
    return conn.execute(
        f"SELECT * FROM subscriptions {where_clause} ORDER BY renewal_date ASC",
        params
    ).fetchall()


def update_subscription(sub_id: int, user_id: int, sub: dict) -> bool:
    """Update an existing subscription if owned by the user."""
    allowed_fields = {"name", "amount_cents", "currency", "billing_cycle",
                      "custom_cycle_days", "renewal_date", "status", "category",
                      "payment_method", "notes"}
    updates = {k: v for k, v in sub.items() if k in allowed_fields}
    if not updates:
        return False

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [sub_id, user_id]

    conn = get_db()
    cur = conn.execute(
        f"UPDATE subscriptions SET {set_clause} WHERE id = ? AND user_id = ?",
        values
    )
    conn.commit()
    return cur.rowcount > 0


def delete_subscription(sub_id: int, user_id: int) -> bool:
    """Delete a subscription by ID, verifying ownership."""
    conn = get_db()
    cur = conn.execute("DELETE FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def get_upcoming_renewals(user_id: int, days_ahead: int = 30) -> list:
    """Get subscriptions renewing within the specified days."""
    conn = get_db()
    from datetime import date, timedelta
    today = date.today()
    future = today + timedelta(days=days_ahead)

    return conn.execute(
        """SELECT * FROM subscriptions
           WHERE user_id = ? AND status = 'active'
           AND renewal_date BETWEEN ? AND ?
           ORDER BY renewal_date ASC""",
        (user_id, today.isoformat(), future.isoformat())
    ).fetchall()


def get_subscription_totals(user_id: int) -> dict:
    """Calculate monthly and annual subscription costs."""
    conn = get_db()
    subs = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = ? AND status = 'active'", (user_id,)
    ).fetchall()

    monthly = 0
    yearly = 0

    for sub in subs:
        amount = sub["amount_cents"]
        cycle = sub["billing_cycle"]

        if cycle == "monthly":
            monthly += amount
            yearly += amount * 12
        elif cycle == "quarterly":
            monthly += amount / 3
            yearly += amount * 4
        elif cycle == "yearly":
            monthly += amount / 12
            yearly += amount
        elif cycle == "custom" and sub["custom_cycle_days"]:
            # Convert custom cycle to monthly/yearly equivalent
            monthly += amount * 30 / sub["custom_cycle_days"]
            yearly += amount * 365 / sub["custom_cycle_days"]

    return {
        "monthly_total": round(monthly / 100, 2),
        "yearly_total": round(yearly / 100, 2),
        "subscription_count": len(subs)
    }


# ============================================================================
# Notifications Database Operations
# ============================================================================

def add_notification(user_id: int, notification: dict) -> int:
    """Create a new notification and return its ID."""
    import json
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO notifications (user_id, type, title, message, entity_type, entity_id, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, notification["type"], notification["title"], notification["message"],
         notification.get("entity_type"), notification.get("entity_id"),
         json.dumps(notification.get("metadata")) if notification.get("metadata") else None)
    )
    conn.commit()
    return cur.lastrowid


def get_notification(notif_id: int, user_id: int):
    """Fetch a single notification by ID, verifying ownership."""
    return get_db().execute(
        "SELECT * FROM notifications WHERE id = ? AND user_id = ?", (notif_id, user_id)
    ).fetchone()


def list_notifications(user_id: int, is_read: int = None, limit: int = 50, offset: int = 0):
    """List notifications for a user with optional read filter and pagination."""
    conn = get_db()
    conditions = ["user_id = ?"]
    params = [user_id]

    if is_read is not None:
        conditions.append("is_read = ?")
        params.append(is_read)

    where_clause = "WHERE " + " AND ".join(conditions)
    params.extend([limit, offset])

    return conn.execute(
        f"SELECT * FROM notifications {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params
    ).fetchall()


def count_notifications(user_id: int, is_read: int = None) -> int:
    """Count notifications for a user."""
    conn = get_db()
    conditions = ["user_id = ?"]
    params = [user_id]

    if is_read is not None:
        conditions.append("is_read = ?")
        params.append(is_read)

    where_clause = "WHERE " + " AND ".join(conditions)
    row = conn.execute(
        f"SELECT COUNT(*) FROM notifications {where_clause}", params
    ).fetchone()
    return row[0] if row else 0


def mark_notification_read(notif_id: int, user_id: int) -> bool:
    """Mark a notification as read."""
    conn = get_db()
    cur = conn.execute(
        """UPDATE notifications SET is_read = 1, read_at = ? WHERE id = ? AND user_id = ?""",
        (datetime.now(timezone.utc).isoformat(), notif_id, user_id)
    )
    conn.commit()
    return cur.rowcount > 0


def mark_all_notifications_read(user_id: int) -> int:
    """Mark all unread notifications as read for a user."""
    conn = get_db()
    cur = conn.execute(
        """UPDATE notifications SET is_read = 1, read_at = ? WHERE user_id = ? AND is_read = 0""",
        (datetime.now(timezone.utc).isoformat(), user_id)
    )
    conn.commit()
    return cur.rowcount


def delete_notification(notif_id: int, user_id: int) -> bool:
    """Delete a notification by ID, verifying ownership."""
    conn = get_db()
    cur = conn.execute("DELETE FROM notifications WHERE id = ? AND user_id = ?", (notif_id, user_id))
    conn.commit()
    return cur.rowcount > 0


def check_budget_notifications(user_id: int) -> list:
    """Check budgets and create notifications for warnings/exceeded budgets."""
    from datetime import date, timedelta
    import calendar
    today = date.today()

    # Current month range for monthly budgets; auto_period=True handles weekly budgets automatically
    last_day = calendar.monthrange(today.year, today.month)[1]
    start = today.replace(day=1)
    end = today.replace(day=last_day)

    utilizations = get_all_budget_utilizations(user_id, start, end, auto_period=True)
    notifications = []

    for util in utilizations:
        if util["is_exceeded"]:
            # Check if notification already exists
            existing = get_db().execute(
                """SELECT id FROM notifications
                   WHERE user_id = ? AND type = 'budget_exceeded'
                   AND entity_type = 'budget' AND entity_id = ?
                   AND date(created_at) = date(?)""",
                (user_id, str(util["budget_id"]), today.isoformat())
            ).fetchone()

            if not existing:
                notif_id = add_notification(user_id, {
                    "type": "budget_exceeded",
                    "title": f"Budget Exceeded: {util['budget_name']}",
                    "message": f"You've exceeded your {util['period']} budget of {util['budget_amount']:.2f} by spending {util['spent']:.2f}.",
                    "entity_type": "budget",
                    "entity_id": str(util["budget_id"]),
                    "metadata": {"utilization_pct": util["utilization_pct"]}
                })
                notifications.append(notif_id)
        elif util["is_warning"] and not util["is_exceeded"]:
            # Check if warning notification already exists
            existing = get_db().execute(
                """SELECT id FROM notifications
                   WHERE user_id = ? AND type = 'budget_warning'
                   AND entity_type = 'budget' AND entity_id = ?
                   AND date(created_at) = date(?)""",
                (user_id, str(util["budget_id"]), today.isoformat())
            ).fetchone()

            if not existing:
                notif_id = add_notification(user_id, {
                    "type": "budget_warning",
                    "title": f"Budget Warning: {util['budget_name']}",
                    "message": f"You've used {util['utilization_pct']:.1f}% of your {util['period']} budget ({util['budget_amount']:.2f}).",
                    "entity_type": "budget",
                    "entity_id": str(util["budget_id"]),
                    "metadata": {"utilization_pct": util["utilization_pct"]}
                })
                notifications.append(notif_id)

    return notifications


def check_recurring_notifications(user_id: int) -> list:
    """Check for due recurring transactions and create notifications."""
    from datetime import date
    today = date.today()
    due = get_due_recurring_transactions(user_id, today)
    notifications = []

    for rt in due:
        # Check if notification already exists for this recurring transaction today
        existing = get_db().execute(
            """SELECT id FROM notifications
               WHERE user_id = ? AND type = 'recurring_due'
               AND entity_type = 'recurring_transaction' AND entity_id = ?
               AND date(created_at) = date(?)""",
            (user_id, str(rt["id"]), today.isoformat())
        ).fetchone()

        if not existing:
            notif_id = add_notification(user_id, {
                "type": "recurring_due",
                "title": f"Recurring Transaction Due: {rt['category']}",
                "message": f"Your {rt['frequency']} {rt['type']} of {rt['amount_cents']/100:.2f} is due today.",
                "entity_type": "recurring_transaction",
                "entity_id": str(rt["id"]),
                "metadata": {"frequency": rt["frequency"], "amount_cents": rt["amount_cents"]}
            })
            notifications.append(notif_id)

    return notifications


def check_subscription_notifications(user_id: int) -> list:
    """Check for upcoming subscription renewals and create notifications."""
    from datetime import date, timedelta
    today = date.today()
    upcoming = get_upcoming_renewals(user_id, days_ahead=7)
    notifications = []

    for sub in upcoming:
        # Check if notification already exists for this subscription renewal
        existing = get_db().execute(
            """SELECT id FROM notifications
               WHERE user_id = ? AND type = 'subscription_renewal'
               AND entity_type = 'subscription' AND entity_id = ?
               AND date(created_at) = date(?)""",
            (user_id, str(sub["id"]), today.isoformat())
        ).fetchone()

        if not existing:
            renewal = date.fromisoformat(sub["renewal_date"])
            days_until = (renewal - today).days

            notif_id = add_notification(user_id, {
                "type": "subscription_renewal",
                "title": f"Subscription Renewal: {sub['name']}",
                "message": f"Your {sub['name']} subscription ({sub['amount_cents']/100:.2f}) renews in {days_until} day(s) on {renewal.isoformat()}.",
                "entity_type": "subscription",
                "entity_id": str(sub["id"]),
                "metadata": {"amount_cents": sub["amount_cents"], "renewal_date": sub["renewal_date"]}
            })
            notifications.append(notif_id)

    return notifications


def check_goal_notifications(user_id: int) -> list:
    """Check for goal milestones and create notifications."""
    from datetime import date
    # Check both incomplete goals and recently completed goals (within today)
    today = date.today().isoformat()

    # First check incomplete goals for milestones
    goals = list_financial_goals(user_id, is_completed=0)
    notifications = []

    for goal in goals:
        progress = get_goal_progress(goal["id"], user_id)
        if not progress:
            continue

        pct = progress["progress_pct"]

        # Check for 50%, 75%, 90%, 95% milestones
        milestones = [50, 75, 90, 95]
        for milestone in milestones:
            if pct >= milestone:
                existing = get_db().execute(
                    """SELECT id FROM notifications
                       WHERE user_id = ? AND type = 'goal_milestone'
                       AND entity_type = 'goal' AND entity_id = ?
                       AND json_extract(metadata_json, '$.milestone') = ?
                       AND date(created_at) = date(?)""",
                    (user_id, str(goal["id"]), milestone, today)
                ).fetchone()

                if not existing:
                    notif_id = add_notification(user_id, {
                        "type": "goal_milestone",
                        "title": f"Goal Milestone: {goal['name']}",
                        "message": f"Congratulations! You've reached {milestone}% of your goal '{goal['name']}' ({progress['current_amount']:.2f}/{progress['target_amount']:.2f}).",
                        "entity_type": "goal",
                        "entity_id": str(goal["id"]),
                        "metadata": {"milestone": milestone, "progress_pct": pct}
                    })
                    notifications.append(notif_id)

    # Check for goal completion - look at goals completed today
    completed_goals = list_financial_goals(user_id, is_completed=1)
    for goal in completed_goals:
        # Only notify if completed today
        if goal["completed_at"] and goal["completed_at"].startswith(today):
            progress = get_goal_progress(goal["id"], user_id)
            if not progress:
                continue

            existing = get_db().execute(
                """SELECT id FROM notifications
                   WHERE user_id = ? AND type = 'goal_completed'
                   AND entity_type = 'goal' AND entity_id = ?
                   AND date(created_at) = date(?)""",
                (user_id, str(goal["id"]), today)
            ).fetchone()

            if not existing:
                notif_id = add_notification(user_id, {
                    "type": "goal_completed",
                    "title": f"Goal Completed: {goal['name']}",
                    "message": f"Congratulations! You've completed your goal '{goal['name']}' with {progress['current_amount']:.2f} saved!",
                    "entity_type": "goal",
                    "entity_id": str(goal["id"]),
                    "metadata": {"target_amount": progress["target_amount"], "final_amount": progress["current_amount"]}
                })
                notifications.append(notif_id)

    return notifications


def run_all_notification_checks(user_id: int) -> dict:
    """Run all notification checks and return summary."""
    return {
        "budget_notifications": check_budget_notifications(user_id),
        "recurring_notifications": check_recurring_notifications(user_id),
        "subscription_notifications": check_subscription_notifications(user_id),
        "goal_notifications": check_goal_notifications(user_id),
    }

