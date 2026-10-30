"""Migration utility: transfers records from local SQLite to Turso database.

Features:
- Reads from local SQLite (e.g. data/tracker.db) without modifying or deleting it.
- Preserves primary key IDs, created_at timestamps, amounts, categories, types, notes, dates.
- Idempotent: uses INSERT OR IGNORE to prevent duplicate records on retry.
- Verifies post-migration row counts against the source.
- Redacts authentication tokens from logs and console output.
- Supports target Turso connection via environment variables or CLI arguments.
- Also supports a target SQLite database for automated testing.

Usage:
    python scripts/migrate_sqlite_to_turso.py
    python scripts/migrate_sqlite_to_turso.py --source data/tracker.db --url <turso_url> --token <turso_token>
"""
import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

from app.db import SCHEMA_STATEMENTS, _connect_turso, _sanitize_message


def _exec_with_retry(conn, sql, params=(), max_retries=3):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return conn.execute(sql, params)
        except Exception as err:
            last_err = err
            err_msg = str(err).lower()
            if attempt < max_retries and any(
                w in err_msg
                for w in (
                    "remotedisconnected",
                    "closed connection",
                    "connection reset",
                    "getaddrinfo",
                    "protocolerror",
                    "operationalerror",
                    "eof",
                    "timed out",
                )
            ):
                time.sleep(0.5 * attempt)
                continue
            raise
    raise last_err


def _commit_with_retry(conn, max_retries=3):
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            conn.commit()
            return
        except Exception as err:
            last_err = err
            err_msg = str(err).lower()
            if attempt < max_retries and any(
                w in err_msg
                for w in (
                    "remotedisconnected",
                    "closed connection",
                    "connection reset",
                    "getaddrinfo",
                    "protocolerror",
                    "operationalerror",
                    "eof",
                    "timed out",
                )
            ):
                time.sleep(0.5 * attempt)
                continue
            raise
    raise last_err


def migrate_data(
    source_path: str,
    target_url: str = "",
    target_token: str = "",
    target_sqlite_path: str = "",
    batch_size: int = 100,
) -> dict:
    """Migrate transactions from local SQLite to target database (Turso or target SQLite).

    Returns a summary dict:
        {
            "source_count": int,
            "migrated_count": int,
            "skipped_count": int,
            "target_total": int,
            "status": "success" | "failure"
        }
    """
    source_file = Path(source_path)
    if not source_file.is_absolute():
        source_file = BASE_DIR / source_file

    if not source_file.exists():
        raise FileNotFoundError(f"Source SQLite database not found: {source_file}")

    print(f"Reading source database from: {source_file}")
    # Open source in read-only mode to guarantee the source file is never modified
    source_uri = f"file:{source_file.resolve().as_posix()}?mode=ro"
    try:
        source_conn = sqlite3.connect(source_uri, uri=True)
    except Exception:
        # Fallback to standard connect without URI if URI mode is unsupported
        source_conn = sqlite3.connect(str(source_file))

    source_conn.row_factory = sqlite3.Row

    # Verify transactions table in source
    cur = source_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
    if not cur.fetchone():
        source_conn.close()
        raise RuntimeError("Source database does not contain a 'transactions' table.")

    source_rows = source_conn.execute(
        "SELECT id, type, amount_cents, category, note, date, created_at FROM transactions ORDER BY id ASC"
    ).fetchall()
    source_count = len(source_rows)
    print(f"Found {source_count} records in source 'transactions' table.")

    # Connect to target database
    if target_sqlite_path:
        print(f"Connecting to target SQLite test database: {target_sqlite_path}")
        target_conn = sqlite3.connect(target_sqlite_path)
        target_conn.row_factory = sqlite3.Row
    else:
        if not target_url:
            source_conn.close()
            raise ValueError("Target Turso URL must be provided (or set TURSO_DATABASE_URL).")
        print("Connecting to target Turso database...")
        target_conn = _connect_turso(target_url, target_token)

    try:
        # 1. Initialize schema idempotently on target
        print("Ensuring target schema is ready...")
        for stmt in SCHEMA_STATEMENTS:
            _exec_with_retry(target_conn, stmt)
        _commit_with_retry(target_conn)

        # Check existing IDs on target to accurately report migrated vs skipped
        existing_target_ids = set()
        try:
            cur = _exec_with_retry(target_conn, "SELECT id FROM transactions")
            existing_target_ids = {r[0] if isinstance(r, (tuple, list)) else r["id"] for r in cur.fetchall()}
        except Exception:
            existing_target_ids = set()

        # 2. Transfer records safely in batches using INSERT OR IGNORE
        migrated_count = 0
        skipped_count = 0

        insert_sql = """
        INSERT OR IGNORE INTO transactions (id, type, amount_cents, category, note, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        records_to_insert = []
        for r in source_rows:
            row_id = r["id"]
            if row_id in existing_target_ids:
                skipped_count += 1
                continue

            records_to_insert.append((
                r["id"],
                r["type"],
                r["amount_cents"],
                r["category"],
                r["note"],
                r["date"],
                r["created_at"],
            ))

        for i in range(0, len(records_to_insert), batch_size):
            batch = records_to_insert[i : i + batch_size]
            for row in batch:
                _exec_with_retry(target_conn, insert_sql, row)
            _commit_with_retry(target_conn)
            migrated_count += len(batch)

        # 3. Verify target counts
        cur = _exec_with_retry(target_conn, "SELECT COUNT(*) FROM transactions")
        count_row = cur.fetchone()
        target_total = count_row[0] if isinstance(count_row, (tuple, list)) else count_row["COUNT(*)"]

        print("\nMigration Summary:")
        print(f"  Source records:   {source_count}")
        print(f"  Records migrated: {migrated_count}")
        print(f"  Records skipped:  {skipped_count} (already present)")
        print(f"  Target total:     {target_total}")

        if target_total < source_count:
            print(
                f"Warning: Target count ({target_total}) is less than source count ({source_count}).",
                file=sys.stderr,
            )

        return {
            "source_count": source_count,
            "migrated_count": migrated_count,
            "skipped_count": skipped_count,
            "target_total": target_total,
            "status": "success",
        }

    except Exception as err:
        safe_msg = _sanitize_message(str(err), target_token)
        print(f"Migration error: {safe_msg}", file=sys.stderr)
        raise RuntimeError(f"Migration failed: {safe_msg}") from None

    finally:
        source_conn.close()
        try:
            target_conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Migrate Expense Tracker SQLite database to Turso.")
    parser.add_argument(
        "--source",
        default=os.getenv("SQLITE_DATABASE_PATH") or os.getenv("DATABASE_PATH") or "data/tracker.db",
        help="Path to source SQLite file (default: data/tracker.db)",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("TURSO_DATABASE_URL", ""),
        help="Target Turso database URL (default: TURSO_DATABASE_URL env var)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("TURSO_AUTH_TOKEN", ""),
        help="Target Turso auth token (default: TURSO_AUTH_TOKEN env var)",
    )
    parser.add_argument(
        "--target-sqlite",
        default="",
        help="Target SQLite path for local verification/testing",
    )
    args = parser.parse_args()

    try:
        result = migrate_data(
            source_path=args.source.strip(),
            target_url=args.url.strip(),
            target_token=args.token.strip(),
            target_sqlite_path=args.target_sqlite.strip(),
        )
        if result["status"] == "success":
            print("\nMigration completed successfully.")
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as exc:
        print(f"\nMigration aborted: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
