"""Utility script to safely initialize or verify the schema on a Turso database.

Usage:
    python scripts/init_turso_db.py
    python scripts/init_turso_db.py --url <url> --token <token>
"""
import argparse
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

from app.db import SCHEMA_STATEMENTS, _connect_turso, _sanitize_message


def init_turso_database(url: str, auth_token: str) -> bool:
    """Execute non-destructive schema initialization against Turso."""
    if not url:
        print("Error: TURSO_DATABASE_URL is not set.", file=sys.stderr)
        return False

    print("Connecting to Turso database (URL configured)...")
    try:
        conn = _connect_turso(url, auth_token)
    except Exception as err:
        safe_msg = _sanitize_message(str(err), auth_token)
        print(f"Error connecting to Turso: {safe_msg}", file=sys.stderr)
        return False

    try:
        print("Applying schema (idempotent CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS)...")
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.commit()

        # Verify table exists
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
        row = cur.fetchone()
        if not row:
            print("Error: transactions table was not created.", file=sys.stderr)
            return False

        print("Success: Database schema is initialized and verified on Turso.")
        return True
    except Exception as err:
        safe_msg = _sanitize_message(str(err), auth_token)
        print(f"Error initializing schema: {safe_msg}", file=sys.stderr)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Initialize Turso database schema.")
    parser.add_argument("--url", default=os.getenv("TURSO_DATABASE_URL", ""), help="Turso database URL")
    parser.add_argument("--token", default=os.getenv("TURSO_AUTH_TOKEN", ""), help="Turso authentication token")
    args = parser.parse_args()

    success = init_turso_database(args.url.strip(), args.token.strip())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
