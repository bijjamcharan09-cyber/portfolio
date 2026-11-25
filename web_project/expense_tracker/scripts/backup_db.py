#!/usr/bin/env python3
"""Automated database backup and recovery utility.

Supports both SQLite (using .backup() API for WAL-safe copies) and Turso (libSQL export).
Features:
- Configurable backup destination and retention
- Integrity verification (checksum + test restore)
- Timestamped backup files
- Safe credential handling
- Clear failure logging

Usage:
    python scripts/backup_db.py                    # Run backup with defaults
    python scripts/backup_db.py --destination /backups --retention 7
    python scripts/backup_db.py --restore backup_file.db --target /tmp/restore_test.db
    python scripts/backup_db.py --verify backup_file.db

Environment Variables:
    BACKUP_DIR              Backup destination directory (default: ./backups)
    BACKUP_RETENTION_DAYS   Retention period in days (default: 7)
    DATABASE_MODE           'sqlite' or 'turso'
    DATABASE_PATH           SQLite database path (when mode=sqlite)
    TURSO_DATABASE_URL      Turso database URL (when mode=turso)
    TURSO_AUTH_TOKEN        Turso auth token (when mode=turso)
"""
import argparse
import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def _sanitize_message(message: str, token: str = "") -> str:
    """Ensure authentication tokens are never exposed in logs."""
    if not message:
        return ""
    if token and token in message:
        message = message.replace(token, "[REDACTED]")
    return message


def _calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _verify_sqlite_integrity(db_path: Path) -> bool:
    """Verify SQLite database integrity using PRAGMA integrity_check."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        result = conn.execute("PRAGMA integrity_check;").fetchone()
        conn.close()
        return result[0] == "ok"
    except Exception as exc:
        logger.error("Integrity check failed for %s: %s", db_path, exc)
        return False


def _backup_sqlite(source_path: Path, backup_dir: Path) -> Path:
    """Create a WAL-safe backup of SQLite database using .backup() API."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"expense_tracker_{timestamp}.db"
    backup_path = backup_dir / backup_name

    # Open source in read-only mode to guarantee no modifications
    source_uri = f"file:{source_path.resolve().as_posix()}?mode=ro"
    source_conn = sqlite3.connect(source_uri, uri=True)
    source_conn.row_factory = sqlite3.Row

    # Create backup connection
    backup_conn = sqlite3.connect(str(backup_path))

    try:
        # Use SQLite's backup API (handles WAL mode correctly)
        source_conn.backup(backup_conn)
        backup_conn.close()
        source_conn.close()

        # Verify backup integrity
        if not _verify_sqlite_integrity(backup_path):
            backup_path.unlink(missing_ok=True)
            raise RuntimeError("Backup integrity check failed")

        checksum = _calculate_checksum(backup_path)
        logger.info("SQLite backup created: %s (checksum: %s)", backup_path.name, checksum[:16])
        return backup_path

    except Exception as exc:
        backup_conn.close()
        source_conn.close()
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"SQLite backup failed: {exc}") from None


def _backup_turso(url: str, token: str, backup_dir: Path) -> Path:
    """Create a backup of Turso database using libsql export."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"expense_tracker_turso_{timestamp}.db"
    backup_path = backup_dir / backup_name

    # Use libsql to export
    try:
        import libsql
    except ImportError:
        raise RuntimeError("libsql driver not installed. Install with: pip install libsql")

    # Connect to Turso and export to local SQLite file
    conn = libsql.connect(database=url, auth_token=token or None)
    local_conn = sqlite3.connect(str(backup_path))

    try:
        # Export schema and data
        conn.execute("PRAGMA foreign_keys = ON;")
        local_conn.execute("PRAGMA foreign_keys = ON;")

        # Get schema from Turso
        schema_rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type IN ('table', 'index', 'trigger', 'view') AND sql IS NOT NULL"
        ).fetchall()

        # Apply schema to local
        for row in schema_rows:
            sql = row[0] if isinstance(row, (tuple, list)) else row["sql"]
            if sql and not sql.startswith("CREATE VIRTUAL TABLE"):  # Skip virtual tables
                try:
                    local_conn.execute(sql)
                except Exception:
                    pass  # Some schema may not apply to local SQLite

        # Export data for each table
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        for row in table_rows:
            table_name = row[0] if isinstance(row, (tuple, list)) else row["name"]
            if table_name in ("sqlite_sequence",):
                continue

            # Get column info
            col_info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            columns = [c[1] if isinstance(c, (tuple, list)) else c["name"] for c in col_info]

            if not columns:
                continue

            # Fetch all data
            data_rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
            if not data_rows:
                continue

            placeholders = ", ".join(["?"] * len(columns))
            cols_str = ", ".join(columns)
            insert_sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"

            for data_row in data_rows:
                values = [data_row[c] if hasattr(data_row, "keys") else data_row[i]
                          for i, c in enumerate(columns)]
                try:
                    local_conn.execute(insert_sql, values)
                except Exception as exc:
                    logger.warning("Failed to insert row into %s: %s", table_name, exc)

        local_conn.commit()
        local_conn.close()
        conn.close()

        # Verify backup integrity
        if not _verify_sqlite_integrity(backup_path):
            backup_path.unlink(missing_ok=True)
            raise RuntimeError("Turso backup integrity check failed")

        checksum = _calculate_checksum(backup_path)
        logger.info("Turso backup created: %s (checksum: %s)", backup_path.name, checksum[:16])
        return backup_path

    except Exception as exc:
        local_conn.close()
        try:
            conn.close()
        except Exception:
            pass
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"Turso backup failed: {exc}") from None


def _cleanup_old_backups(backup_dir: Path, retention_days: int) -> int:
    """Remove backup files older than retention period."""
    if retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0

    for backup_file in backup_dir.glob("expense_tracker_*.db"):
        try:
            # Extract timestamp from filename
            timestamp_str = backup_file.stem.split("_")[-1]
            file_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            if file_time < cutoff:
                backup_file.unlink()
                removed += 1
                logger.info("Removed expired backup: %s", backup_file.name)
        except Exception:
            # Skip files with unparsable names
            pass

    return removed


def run_backup(
    database_mode: str = None,
    database_path: str = None,
    turso_url: str = None,
    turso_token: str = None,
    backup_dir: str = None,
    retention_days: int = 7
) -> dict:
    """Run a database backup with verification.

    Returns:
        dict with keys: success, backup_path, checksum, error
    """
    database_mode = database_mode or os.getenv("DATABASE_MODE", "sqlite")
    backup_dir = Path(backup_dir or os.getenv("BACKUP_DIR", BASE_DIR / "backups"))
    retention_days = retention_days or int(os.getenv("BACKUP_RETENTION_DAYS", "7"))

    # Create backup directory
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Validate configuration
    if database_mode == "sqlite":
        database_path = database_path or os.getenv("DATABASE_PATH") or os.getenv("SQLITE_DATABASE_PATH") or "data/tracker.db"
        source_path = Path(database_path)
        if not source_path.is_absolute():
            source_path = BASE_DIR / source_path
        if not source_path.exists():
            return {"success": False, "error": f"Source database not found: {source_path}"}

        logger.info("Starting SQLite backup from %s", source_path)
        try:
            backup_path = _backup_sqlite(source_path, backup_dir)
            checksum = _calculate_checksum(backup_path)
            removed = _cleanup_old_backups(backup_dir, retention_days)
            logger.info("Cleaned up %d expired backups", removed)
            return {"success": True, "backup_path": str(backup_path), "checksum": checksum, "expired_removed": removed}
        except Exception as exc:
            logger.error("Backup failed: %s", exc)
            return {"success": False, "error": str(exc)}

    elif database_mode == "turso":
        turso_url = turso_url or os.getenv("TURSO_DATABASE_URL", "").strip()
        turso_token = turso_token or os.getenv("TURSO_AUTH_TOKEN", "").strip()

        if not turso_url:
            return {"success": False, "error": "TURSO_DATABASE_URL not configured"}

        logger.info("Starting Turso backup")
        try:
            backup_path = _backup_turso(turso_url, turso_token, backup_dir)
            checksum = _calculate_checksum(backup_path)
            removed = _cleanup_old_backups(backup_dir, retention_days)
            logger.info("Cleaned up %d expired backups", removed)
            return {"success": True, "backup_path": str(backup_path), "checksum": checksum, "expired_removed": removed}
        except Exception as exc:
            logger.error("Backup failed: %s", exc)
            return {"success": False, "error": str(exc)}

    else:
        return {"success": False, "error": f"Unsupported DATABASE_MODE: {database_mode}"}


def verify_backup(backup_path: str) -> dict:
    """Verify a backup file integrity."""
    path = Path(backup_path)
    if not path.exists():
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    try:
        checksum = _calculate_checksum(path)
        integrity_ok = _verify_sqlite_integrity(path)
        return {
            "success": integrity_ok,
            "checksum": checksum,
            "integrity_ok": integrity_ok,
            "size_bytes": path.stat().st_size
        }
    except Exception as exc:
        return {"success": False, "error": f"Verification failed: {exc}"}


def restore_backup(backup_path: str, target_path: str) -> dict:
    """Restore a backup to a target location (for testing/verification)."""
    source = Path(backup_path)
    target = Path(target_path)

    if not source.exists():
        return {"success": False, "error": f"Backup file not found: {backup_path}"}

    # Verify before restore
    verify_result = verify_backup(backup_path)
    if not verify_result["success"]:
        return {"success": False, "error": f"Backup verification failed: {verify_result.get('error')}"}

    try:
        # Ensure target directory exists
        target.parent.mkdir(parents=True, exist_ok=True)

        # Copy backup to target
        shutil.copy2(source, target)

        # Verify restored copy
        restored_verify = verify_backup(str(target))
        if not restored_verify["success"]:
            target.unlink(missing_ok=True)
            return {"success": False, "error": "Restored copy failed integrity check"}

        logger.info("Backup restored to %s (checksum: %s)", target, restored_verify["checksum"][:16])
        return {"success": True, "target_path": str(target), "checksum": restored_verify["checksum"]}
    except Exception as exc:
        target.unlink(missing_ok=True)
        return {"success": False, "error": f"Restore failed: {exc}"}


def main():
    parser = argparse.ArgumentParser(description="Expense Tracker Database Backup & Recovery")
    parser.add_argument("--destination", "-d", help="Backup destination directory")
    parser.add_argument("--retention", "-r", type=int, help="Retention period in days")
    parser.add_argument("--mode", choices=["sqlite", "turso"], help="Database mode")
    parser.add_argument("--db-path", help="SQLite database path")
    parser.add_argument("--turso-url", help="Turso database URL")
    parser.add_argument("--turso-token", help="Turso auth token")
    parser.add_argument("--restore", help="Restore backup file to target")
    parser.add_argument("--target", help="Target path for restore")
    parser.add_argument("--verify", help="Verify backup file integrity")

    args = parser.parse_args()

    if args.verify:
        result = verify_backup(args.verify)
        if result["success"]:
            print(f"[OK] Backup verified: {args.verify}")
            print(f"  Checksum: {result['checksum']}")
            print(f"  Size: {result['size_bytes']} bytes")
            sys.exit(0)
        else:
            print(f"[ERROR] Backup verification failed: {result['error']}")
            sys.exit(1)

    if args.restore:
        if not args.target:
            print("Error: --target required for restore")
            sys.exit(1)
        result = restore_backup(args.restore, args.target)
        if result["success"]:
            print(f"[OK] Restored to {result['target_path']}")
            print(f"  Checksum: {result['checksum']}")
            sys.exit(0)
        else:
            print(f"[ERROR] Restore failed: {result['error']}")
            sys.exit(1)

    # Run backup
    result = run_backup(
        database_mode=args.mode,
        database_path=args.db_path,
        turso_url=args.turso_url,
        turso_token=args.turso_token,
        backup_dir=args.destination,
        retention_days=args.retention
    )

    if result["success"]:
        print(f"[OK] Backup completed: {result['backup_path']}")
        print(f"  Checksum: {result['checksum']}")
        if result.get("expired_removed"):
            print(f"  Expired backups removed: {result['expired_removed']}")
        sys.exit(0)
    else:
        print(f"[ERROR] Backup failed: {result['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()