"""SQLite access. Every query uses ? placeholders (prevents SQL injection).
Money is stored as integer cents to avoid floating-point rounding errors."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    date         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(app):
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.executescript(SCHEMA)
    app.teardown_appcontext(close_db)


def row_to_dict(row):
    return {
        "id": row["id"],
        "type": row["type"],
        "amount": row["amount_cents"] / 100,
        "category": row["category"],
        "note": row["note"],
        "date": row["date"],
    }


def add_transaction(t):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO transactions (type, amount_cents, category, note, date) VALUES (?, ?, ?, ?, ?)",
        (t["type"], t["amount_cents"], t["category"], t["note"], t["date"]),
    )
    conn.commit()
    return cur.lastrowid


def get_transaction(tx_id):
    return get_db().execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()


def list_transactions(start, end):
    return get_db().execute(
        "SELECT * FROM transactions WHERE date BETWEEN ? AND ? ORDER BY date DESC, id DESC LIMIT 500",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def delete_transaction(tx_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    conn.commit()
    return cur.rowcount > 0
