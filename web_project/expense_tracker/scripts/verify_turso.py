"""Safe remote Turso connectivity, schema, read/write, and persistence verification.

Never logs or prints authentication tokens. Cleans up its temporary verification row.

Usage:
    python scripts/verify_turso.py
"""
import os
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env", override=True)

from app import create_app
from app.db import _connect_turso, _sanitize_message, verify_database_connection


def main():
    url = os.getenv("TURSO_DATABASE_URL", "").strip()
    token = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    if not url or not token:
        print("ERROR: TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set.", file=sys.stderr)
        sys.exit(1)

    app = create_app(
        {
            "TESTING": False,
            "IS_PRODUCTION": True,
            "DATABASE_MODE": "turso",
            "TURSO_DATABASE_URL": url,
            "TURSO_AUTH_TOKEN": token,
            "SECRET_KEY": "verify-turso-ephemeral-secret-key-not-used-for-http",
        }
    )

    test_guest_id = f"__verify_{uuid.uuid4().hex[:12]}"

    try:
        with app.app_context():
            status = verify_database_connection()
            print(f"[OK] Connected via mode={status['mode']}, tables_ok={status['tables_ok']}")
            if not status["tables_ok"]:
                print(f"[FAIL] Missing tables: {status['missing_tables']}", file=sys.stderr)
                sys.exit(1)

        # Write test row using a fresh app context/connection
        with app.app_context():
            from app.db import get_db

            conn = get_db()
            conn.execute(
                "INSERT INTO guest_transactions (guest_id, type, amount_cents, category, note, date, expires_at) "
                "VALUES (?, 'expense', 100, 'Other', 'turso_verify', '2026-01-01', '2099-01-01T00:00:00Z')",
                (test_guest_id,),
            )
            conn.commit()
            print("[OK] Write + commit succeeded.")

        # Read back from a brand-new connection (proves persistence across restart/reconnect)
        fresh_conn = _connect_turso(url, token)
        try:
            row = fresh_conn.execute(
                "SELECT id, note FROM guest_transactions WHERE guest_id = ?",
                (test_guest_id,),
            ).fetchone()
            if not row:
                print("[FAIL] Written verification record not visible on fresh connection.", file=sys.stderr)
                sys.exit(1)
            print("[OK] Read-back on fresh remote connection succeeded (persistence verified).")

            fresh_conn.execute(
                "DELETE FROM guest_transactions WHERE guest_id = ?",
                (test_guest_id,),
            )
            fresh_conn.commit()
            print("[OK] Temporary verification row cleaned up.")
        finally:
            fresh_conn.close()

        # Verify /health/ready endpoint in Turso mode
        client = app.test_client()
        resp = client.get("/health/ready")
        data = resp.get_json()
        print(f"[OK] /health/ready -> {resp.status_code} {data}")
        assert resp.status_code == 200
        assert data["database_mode"] == "turso"

    except Exception as exc:
        safe_msg = _sanitize_message(str(exc), token)
        print(f"[FAIL] Turso verification error: {safe_msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
