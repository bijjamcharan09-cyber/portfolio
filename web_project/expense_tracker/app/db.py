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
    """CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
        conn.commit()
    finally:
        if close_when_done:
            conn.close()


def init_db(app):
    """Initialize database handling for the Flask app.
    Registers teardown handler and creates tables for local SQLite / test environments.
    """
    app.teardown_appcontext(close_db)

    # In SQLite dev/testing mode, create the schema if it does not exist yet.
    # In Turso production mode, schema is pre-initialized using migration or init script.
    mode = app.config.get("DATABASE_MODE", "sqlite")
    if mode == "sqlite" or app.config.get("TESTING", False):
        with app.app_context():
            init_schema()


def row_to_dict(row):
    """Convert a database row (sqlite3.Row or turso_serverless.Row) to an API dictionary."""
    if row is None:
        return None
    return {
        "id": row["id"],
        "type": row["type"],
        "amount": row["amount_cents"] / 100,
        "category": row["category"],
        "note": row["note"],
        "date": row["date"],
    }


def add_transaction(t):
    """Insert a new transaction and return its ID."""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO transactions (type, amount_cents, category, note, date) VALUES (?, ?, ?, ?, ?)",
        (t["type"], t["amount_cents"], t["category"], t["note"], t["date"]),
    )
    conn.commit()
    return cur.lastrowid


def get_transaction(tx_id):
    """Fetch a single transaction by ID."""
    return get_db().execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()


def list_transactions(start, end):
    """List up to 500 transactions within the specified date range."""
    return get_db().execute(
        "SELECT * FROM transactions WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC LIMIT 500",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def delete_transaction(tx_id):
    """Delete a transaction by ID. Returns True if deleted, False if not found."""
    conn = get_db()
    cur = conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()
    return cur.rowcount > 0
