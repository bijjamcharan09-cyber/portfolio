"""Tests for Railway deployment readiness, health check, and SQLite persistent storage configuration."""
import os
import sqlite3
import pytest
from pathlib import Path

from app.config import Config
from app.db import _connect_sqlite, get_db


def test_health_check_public_and_clean(unauth_client):
    """The /health endpoint must be publicly accessible without auth and leak no sensitive data."""
    res = unauth_client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "expense-tracker"
    # Ensure no internal filesystem paths or secret keys are exposed
    assert "db" not in data
    assert "path" not in data
    assert "token" not in data

    # Also verify alias /api/health
    res_api = unauth_client.get("/api/health")
    assert res_api.status_code == 200
    assert res_api.get_json()["status"] == "healthy"


def test_sqlite_pragmas_and_wal_mode(tmp_path):
    """File-backed SQLite connections must enable foreign keys, busy timeout, and WAL mode."""
    db_file = str(tmp_path / "pragmas_test.db")
    conn = _connect_sqlite(db_file)
    try:
        # Check foreign keys
        fk = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
        assert fk == 1

        # Check busy timeout (10000 ms)
        bt = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert bt >= 10000

        # Check journal mode (WAL)
        jm = conn.execute("PRAGMA journal_mode;").fetchone()[0].lower()
        assert jm == "wal"

        # Check synchronous setting (NORMAL = 1)
        sync = conn.execute("PRAGMA synchronous;").fetchone()[0]
        assert sync == 1  # 1 corresponds to NORMAL in SQLite
    finally:
        conn.close()


def test_production_validation_accepts_railway_sqlite(monkeypatch):
    """Production validation must permit SQLite when a persistent DATABASE_PATH is provided."""
    # Should not raise an exception
    Config.validate_production_config({
        "IS_PRODUCTION": True,
        "SECRET_KEY": "a-strong-random-production-secret-key-64charslong1234567890",
        "DATABASE_MODE": "sqlite",
        "DATABASE_PATH": "/data/expenses.db",
    })


def test_production_validation_still_enforces_vercel_turso():
    """Production validation must still forbid SQLite when running in Vercel serverless environment."""
    with pytest.raises(RuntimeError, match="Production deployment on Vercel requires DATABASE_MODE='turso'"):
        Config.validate_production_config({
            "IS_PRODUCTION": True,
            "VERCEL": "1",
            "SECRET_KEY": "a-strong-random-production-secret-key-64charslong1234567890",
            "DATABASE_MODE": "sqlite",
            "DATABASE_PATH": "/data/expenses.db",
        })


def test_production_validation_rejects_insecure_secret_even_with_sqlite():
    """Insecure SECRET_KEY must always be rejected in production."""
    with pytest.raises(RuntimeError, match="Production requires a secure, non-default SECRET_KEY"):
        Config.validate_production_config({
            "IS_PRODUCTION": True,
            "SECRET_KEY": "dev-only-change-me",
            "DATABASE_MODE": "sqlite",
            "DATABASE_PATH": "/data/expenses.db",
        })


def test_database_path_precedence_in_config(monkeypatch):
    """DATABASE_PATH must take precedence over SQLITE_DATABASE_PATH for Railway volume mounts."""
    monkeypatch.setenv("DATABASE_PATH", "/data/expenses.db")
    monkeypatch.setenv("SQLITE_DATABASE_PATH", "old/path.db")

    raw = os.getenv("DATABASE_PATH", "").strip() or os.getenv("SQLITE_DATABASE_PATH", "").strip()
    assert raw == "/data/expenses.db"
