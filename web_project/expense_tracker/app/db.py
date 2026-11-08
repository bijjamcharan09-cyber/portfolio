"""Database abstraction supporting local SQLite and remote Turso (hosted libSQL).
Money is stored as integer cents to avoid floating-point rounding errors.
All queries use parameterized (?) placeholders to prevent SQL injection.
"""
import logging
import sqlite3
import time
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
    """Open a local SQLite database connection."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
        # then fallback to SQLITE_DATABASE_PATH or default.
        if is_testing and current_app.config.get("DATABASE"):
            db_path = current_app.config.get("DATABASE")
        else:
            db_path = (
                current_app.config.get("SQLITE_DATABASE_PATH")
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

        # Safely create composite index on user_id and date
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, date)")
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


def list_transactions(start, end, user_id=None):
    """List up to 500 transactions within the specified date range, isolating by user_id."""
    s, e = start.isoformat(), end.isoformat()
    if user_id is not None:
        return get_db().execute(
            "SELECT * FROM transactions WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date DESC, id DESC LIMIT 500",
            (user_id, s, e),
        ).fetchall()
    return get_db().execute(
        "SELECT * FROM transactions WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC LIMIT 500",
        (s, e),
    ).fetchall()


def update_transaction(tx_id, t, user_id=None) -> bool:
    """Update an existing transaction if owned by the user (IDOR prevention)."""
    conn = get_db()
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
