#!/usr/bin/env python3
"""Database migration runner for Expense Tracker.

Lightweight versioned SQL migration system compatible with SQLite and Turso.
No ORM required - works with raw SQL migrations.

Features:
- Version-controlled schema migrations in app/migrations/
- Migration tracking table (schema_migrations)
- Idempotent execution with checksums
- Safe for both SQLite and Turso
- Fresh database initialization support
- Rollback notes for failed migrations

Migration files: app/migrations/001_description.sql, 002_description.sql, etc.
Each file should contain one or more SQL statements separated by semicolons.
"""

import argparse
import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)

from app.db import get_db, _connect_sqlite, _connect_turso, _sanitize_message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = BASE_DIR / "app" / "migrations"


def _calculate_checksum(content: str) -> str:
    """Calculate SHA256 checksum of migration content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ensure_migrations_table(conn):
    """Create the schema_migrations tracking table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            checksum    TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            rolled_back INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()


def _get_applied_migrations(conn) -> dict:
    """Get dict of applied migrations: version -> {checksum, applied_at, rolled_back}."""
    try:
        rows = conn.execute("SELECT version, checksum, applied_at, rolled_back FROM schema_migrations").fetchall()
        return {r["version"]: {"checksum": r["checksum"], "applied_at": r["applied_at"], "rolled_back": r["rolled_back"]} for r in rows}
    except Exception:
        return {}


def _discover_migrations() -> list:
    """Discover all migration files in migrations directory."""
    if not MIGRATIONS_DIR.exists():
        return []

    migrations = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        # Parse version from filename (e.g., 001_initial_schema.sql -> version="001")
        stem = path.stem
        parts = stem.split("_", 1)
        if len(parts) != 2:
            logger.warning("Skipping migration with invalid name format: %s", path.name)
            continue

        version = parts[0]
        if not version.isdigit():
            logger.warning("Skipping migration with non-numeric version: %s", path.name)
            continue

        name = parts[1]
        content = path.read_text(encoding="utf-8")
        checksum = _calculate_checksum(content)

        migrations.append({
            "version": version,
            "name": name,
            "path": path,
            "content": content,
            "checksum": checksum
        })

    # Sort by version
    migrations.sort(key=lambda m: int(m["version"]))
    return migrations


def _run_migration(conn, migration: dict) -> bool:
    """Execute a single migration within a transaction."""
    statements = [s.strip() for m in migration["content"].split(";") if (s := m.strip())]

    try:
        for stmt in statements:
            # Handle ALTER TABLE ADD COLUMN for idempotency
            # If column already exists, catch the error and continue
            try:
                conn.execute(stmt)
            except Exception as exc:
                # Check for duplicate column error (SQLite: "duplicate column name")
                # or Turso/libSQL equivalent
                error_msg = str(exc).lower()
                if "duplicate column" in error_msg or "already exists" in error_msg:
                    logger.info("Skipping duplicate column in migration %s: %s", migration["version"], exc)
                    continue
                raise
        conn.commit()
        return True
    except Exception as exc:
        logger.error("Migration %s failed: %s", migration["version"], exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def _record_migration(conn, migration: dict, success: bool = True):
    """Record migration in tracking table."""
    if success:
        conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
            (migration["version"], migration["name"], migration["checksum"], datetime.now(timezone.utc).isoformat())
        )
    else:
        # Record failed attempt for visibility
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, name, checksum, applied_at, rolled_back) VALUES (?, ?, ?, ?, 1)",
            (migration["version"], migration["name"], migration["checksum"], datetime.now(timezone.utc).isoformat())
        )
    conn.commit()


def run_migrations(
    database_mode: str = None,
    database_path: str = None,
    turso_url: str = None,
    turso_token: str = None,
    dry_run: bool = False,
    target_version: str = None
) -> dict:
    """Run pending migrations.

    Args:
        database_mode: 'sqlite' or 'turso'
        database_path: SQLite database path
        turso_url: Turso database URL
        turso_token: Turso auth token
        dry_run: If True, show what would be run without executing
        target_version: Run migrations up to this version (inclusive)

    Returns:
        dict with success status and details
    """
    database_mode = database_mode or os.getenv("DATABASE_MODE", "sqlite")

    # Connect to database
    if database_mode == "sqlite":
        database_path = database_path or os.getenv("DATABASE_PATH") or os.getenv("SQLITE_DATABASE_PATH") or "data/tracker.db"
        source_path = Path(database_path)
        if not source_path.is_absolute():
            source_path = BASE_DIR / source_path
        source_path.parent.mkdir(parents=True, exist_ok=True)

        conn = _connect_sqlite(str(source_path))
    elif database_mode == "turso":
        turso_url = turso_url or os.getenv("TURSO_DATABASE_URL", "").strip()
        turso_token = turso_token or os.getenv("TURSO_AUTH_TOKEN", "").strip()

        if not turso_url:
            return {"success": False, "error": "TURSO_DATABASE_URL not configured"}

        conn = _connect_turso(turso_url, turso_token)
    else:
        return {"success": False, "error": f"Unsupported DATABASE_MODE: {database_mode}"}

    try:
        _ensure_migrations_table(conn)
        applied = _get_applied_migrations(conn)
        migrations = _discover_migrations()

        if not migrations:
            logger.info("No migrations found in %s", MIGRATIONS_DIR)
            return {"success": True, "applied": 0, "message": "No migrations found"}

        # Filter to target version if specified
        if target_version:
            migrations = [m for m in migrations if int(m["version"]) <= int(target_version)]

        pending = []
        for migration in migrations:
            version = migration["version"]
            if version in applied:
                existing = applied[version]
                if existing["rolled_back"]:
                    logger.warning("Migration %s was previously rolled back, will re-apply", version)
                    pending.append(migration)
                elif existing["checksum"] != migration["checksum"]:
                    logger.error("Migration %s checksum mismatch! Expected %s, got %s",
                               version, existing["checksum"], migration["checksum"])
                    return {"success": False, "error": f"Checksum mismatch for migration {version}"}
                else:
                    logger.info("Migration %s already applied, skipping", version)
            else:
                pending.append(migration)

        if not pending:
            logger.info("All migrations up to date")
            return {"success": True, "applied": 0, "message": "All migrations up to date"}

        logger.info("Found %d pending migrations", len(pending))

        if dry_run:
            for m in pending:
                logger.info("Would apply: %s - %s", m["version"], m["name"])
            return {"success": True, "applied": 0, "pending": [m["version"] for m in pending], "message": "Dry run complete"}

        # Apply pending migrations
        applied_count = 0
        for migration in pending:
            logger.info("Applying migration %s: %s", migration["version"], migration["name"])
            if _run_migration(conn, migration):
                _record_migration(conn, migration, success=True)
                applied_count += 1
                logger.info("Migration %s applied successfully", migration["version"])
            else:
                _record_migration(conn, migration, success=False)
                return {"success": False, "error": f"Migration {migration['version']} failed", "applied": applied_count}

        return {"success": True, "applied": applied_count, "message": f"Applied {applied_count} migrations"}

    except Exception as exc:
        logger.error("Migration process failed: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def init_fresh_database(
    database_mode: str = None,
    database_path: str = None,
    turso_url: str = None,
    turso_token: str = None
) -> dict:
    """Initialize a fresh database with all migrations applied.

    This is for new deployments - creates schema from migrations, not from SCHEMA_STATEMENTS.
    """
    database_mode = database_mode or os.getenv("DATABASE_MODE", "sqlite")

    if database_mode == "sqlite":
        database_path = database_path or os.getenv("DATABASE_PATH") or os.getenv("SQLITE_DATABASE_PATH") or "data/tracker.db"
        source_path = Path(database_path)
        if not source_path.is_absolute():
            source_path = BASE_DIR / source_path
        source_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing file if it exists
        if source_path.exists():
            source_path.unlink()

        conn = _connect_sqlite(str(source_path))
    elif database_mode == "turso":
        turso_url = turso_url or os.getenv("TURSO_DATABASE_URL", "").strip()
        turso_token = turso_token or os.getenv("TURSO_AUTH_TOKEN", "").strip()

        if not turso_url:
            return {"success": False, "error": "TURSO_DATABASE_URL not configured"}

        conn = _connect_turso(turso_url, turso_token)
    else:
        return {"success": False, "error": f"Unsupported DATABASE_MODE: {database_mode}"}

    try:
        _ensure_migrations_table(conn)
        migrations = _discover_migrations()

        if not migrations:
            logger.info("No migrations found")
            return {"success": True, "applied": 0}

        for migration in migrations:
            logger.info("Applying migration %s: %s", migration["version"], migration["name"])
            if _run_migration(conn, migration):
                _record_migration(conn, migration, success=True)
            else:
                return {"success": False, "error": f"Migration {migration['version']} failed during init"}

        return {"success": True, "applied": len(migrations)}

    except Exception as exc:
        logger.error("Fresh database initialization failed: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def status(
    database_mode: str = None,
    database_path: str = None,
    turso_url: str = None,
    turso_token: str = None
) -> dict:
    """Show migration status."""
    database_mode = database_mode or os.getenv("DATABASE_MODE", "sqlite")

    if database_mode == "sqlite":
        database_path = database_path or os.getenv("DATABASE_PATH") or os.getenv("SQLITE_DATABASE_PATH") or "data/tracker.db"
        source_path = Path(database_path)
        if not source_path.is_absolute():
            source_path = BASE_DIR / source_path
        if not source_path.exists():
            return {"success": False, "error": "Database file not found"}

        conn = _connect_sqlite(str(source_path))
    elif database_mode == "turso":
        turso_url = turso_url or os.getenv("TURSO_DATABASE_URL", "").strip()
        turso_token = turso_token or os.getenv("TURSO_AUTH_TOKEN", "").strip()

        if not turso_url:
            return {"success": False, "error": "TURSO_DATABASE_URL not configured"}

        conn = _connect_turso(turso_url, turso_token)
    else:
        return {"success": False, "error": f"Unsupported DATABASE_MODE: {database_mode}"}

    try:
        _ensure_migrations_table(conn)
        applied = _get_applied_migrations(conn)
        migrations = _discover_migrations()

        status_list = []
        for migration in migrations:
            version = migration["version"]
            if version in applied:
                existing = applied[version]
                status_list.append({
                    "version": version,
                    "name": migration["name"],
                    "status": "rolled_back" if existing["rolled_back"] else "applied",
                    "checksum_match": existing["checksum"] == migration["checksum"],
                    "applied_at": existing["applied_at"]
                })
            else:
                status_list.append({
                    "version": version,
                    "name": migration["name"],
                    "status": "pending",
                    "checksum_match": None,
                    "applied_at": None
                })

        return {"success": True, "migrations": status_list}
    except Exception as exc:
        logger.error("Status check failed: %s", exc)
        return {"success": False, "error": str(exc)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Expense Tracker Database Migrations")
    parser.add_argument("command", choices=["run", "init", "status"], help="Command to execute")
    parser.add_argument("--mode", choices=["sqlite", "turso"], help="Database mode")
    parser.add_argument("--db-path", help="SQLite database path")
    parser.add_argument("--turso-url", help="Turso database URL")
    parser.add_argument("--turso-token", help="Turso auth token")
    parser.add_argument("--dry-run", action="store_true", help="Show pending migrations without applying")
    parser.add_argument("--target", help="Run migrations up to this version (inclusive)")

    args = parser.parse_args()

    if args.command == "run":
        result = run_migrations(
            database_mode=args.mode,
            database_path=args.db_path,
            turso_url=args.turso_url,
            turso_token=args.turso_token,
            dry_run=args.dry_run,
            target_version=args.target
        )
    elif args.command == "init":
        result = init_fresh_database(
            database_mode=args.mode,
            database_path=args.db_path,
            turso_url=args.turso_url,
            turso_token=args.turso_token
        )
    elif args.command == "status":
        result = status(
            database_mode=args.mode,
            database_path=args.db_path,
            turso_url=args.turso_url,
            turso_token=args.turso_token
        )
    else:
        parser.print_help()
        sys.exit(1)

    if result["success"]:
        if args.command == "status":
            print("Migration Status:")
            for m in result["migrations"]:
                status_icon = "[OK]" if m["status"] == "applied" else "[!]" if m["status"] == "rolled_back" else "[..]"
                print(f"  {status_icon} {m['version']}: {m['name']} ({m['status']})")
        elif args.command == "init":
            print(f"[OK] Fresh database initialized with {result['applied']} migrations")
        elif args.dry_run:
            print(f"[OK] Dry run: {result.get('pending', [])} pending migrations")
        else:
            print(f"[OK] {result.get('message', 'Migrations applied successfully')}")
        sys.exit(0)
    else:
        print(f"[ERROR] {result['error']}")
        if "applied" in result:
            print(f"  Migrations applied before failure: {result['applied']}")
        sys.exit(1)


if __name__ == "__main__":
    main()