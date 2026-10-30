import os
import sqlite3
import pytest

from app import create_app
from app.config import Config
from app.db import (
    SCHEMA_STATEMENTS,
    _connect_sqlite,
    _sanitize_message,
    init_schema,
    row_to_dict,
)


def test_sanitize_message_redacts_token():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret123"
    raw_error = f"HTTP 401 Unauthorized using Bearer {token} on server"
    sanitized = _sanitize_message(raw_error, token)
    assert token not in sanitized
    assert "[REDACTED]" in sanitized


def test_production_rejects_insecure_secret_key():
    with pytest.raises(RuntimeError, match="Production requires a secure, non-default SECRET_KEY"):
        Config.validate_production_config({
            "IS_PRODUCTION": True,
            "SECRET_KEY": "dev-only-change-me",
            "DATABASE_MODE": "turso",
            "TURSO_DATABASE_URL": "libsql://test-db.turso.io",
            "TURSO_AUTH_TOKEN": "valid-token",
        })


def test_production_rejects_sqlite_mode():
    with pytest.raises(RuntimeError, match="Production deployment on Vercel requires DATABASE_MODE='turso'"):
        Config.validate_production_config({
            "IS_PRODUCTION": True,
            "SECRET_KEY": "very-secure-random-production-secret-12345",
            "DATABASE_MODE": "sqlite",
        })


def test_turso_mode_requires_database_url():
    with pytest.raises(RuntimeError, match="TURSO_DATABASE_URL is not set"):
        Config.validate_production_config({
            "IS_PRODUCTION": False,
            "DATABASE_MODE": "turso",
            "TURSO_DATABASE_URL": "",
            "TURSO_AUTH_TOKEN": "",
        })


def test_turso_mode_requires_auth_token_for_remote_url():
    with pytest.raises(RuntimeError, match="TURSO_AUTH_TOKEN is required"):
        Config.validate_production_config({
            "IS_PRODUCTION": False,
            "DATABASE_MODE": "turso",
            "TURSO_DATABASE_URL": "libsql://my-expense-tracker.turso.io",
            "TURSO_AUTH_TOKEN": "",
        })


def test_repeatable_schema_initialization(tmp_path):
    db_file = str(tmp_path / "schema_repeat.db")
    conn = _connect_sqlite(db_file)

    # First initialization
    init_schema(conn)

    # Insert a record
    conn.execute(
        "INSERT INTO transactions (type, amount_cents, category, note, date) VALUES (?, ?, ?, ?, ?)",
        ("income", 5000, "Salary", "Bonus", "2026-10-01"),
    )
    conn.commit()

    # Second initialization must not drop or fail
    init_schema(conn)

    # Verify the record is preserved
    cur = conn.execute("SELECT COUNT(*) FROM transactions")
    assert cur.fetchone()[0] == 1

    # Third initialization
    init_schema(conn)
    cur = conn.execute("SELECT COUNT(*) FROM transactions")
    assert cur.fetchone()[0] == 1
    conn.close()


def test_row_to_dict_none_handling():
    assert row_to_dict(None) is None


def test_database_error_handler_sanitizes_token(tmp_path):
    fake_token = "secret-token-abcdef123456"
    test_app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test_err.db"),
        "TURSO_AUTH_TOKEN": fake_token,
    })

    @test_app.get("/test-db-error")
    def trigger_db_error():
        raise RuntimeError(f"Connection to Turso failed with token {fake_token}")

    client = test_app.test_client()
    resp = client.get("/test-db-error")
    assert resp.status_code == 503
    assert fake_token not in resp.get_data(as_text=True)
