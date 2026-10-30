import sqlite3
import pytest
from scripts.migrate_sqlite_to_turso import migrate_data


def test_migrate_data_transfers_and_is_idempotent(tmp_path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"

    # Setup source database with known test transactions
    conn = sqlite3.connect(str(source_db))
    conn.execute("""
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        category TEXT NOT NULL,
        note TEXT NOT NULL,
        date TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)
    records = [
        (1, "income", 100000, "Salary", "monthly paycheck", "2026-09-01", "2026-09-01 10:00:00"),
        (2, "expense", 2500, "Food", "groceries", "2026-09-02", "2026-09-02 12:30:00"),
        (5, "expense", 7500, "Transport", "bus pass", "2026-09-05", "2026-09-05 08:15:00"),
    ]
    conn.executemany(
        "INSERT INTO transactions (id, type, amount_cents, category, note, date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        records,
    )
    conn.commit()
    conn.close()

    # Record source file size and modification time
    source_bytes = source_db.read_bytes()

    # First migration run
    res1 = migrate_data(
        source_path=str(source_db),
        target_sqlite_path=str(target_db),
    )
    assert res1["status"] == "success"
    assert res1["source_count"] == 3
    assert res1["migrated_count"] == 3
    assert res1["skipped_count"] == 0
    assert res1["target_total"] == 3

    # Verify target records match source exactly
    target_conn = sqlite3.connect(str(target_db))
    target_conn.row_factory = sqlite3.Row
    rows = target_conn.execute("SELECT * FROM transactions ORDER BY id ASC").fetchall()
    assert len(rows) == 3
    assert rows[0]["id"] == 1
    assert rows[0]["amount_cents"] == 100000
    assert rows[1]["id"] == 2
    assert rows[2]["id"] == 5
    assert rows[2]["category"] == "Transport"
    assert rows[2]["created_at"] == "2026-09-05 08:15:00"
    target_conn.close()

    # Second migration run (idempotency check)
    res2 = migrate_data(
        source_path=str(source_db),
        target_sqlite_path=str(target_db),
    )
    assert res2["status"] == "success"
    assert res2["source_count"] == 3
    assert res2["migrated_count"] == 0
    assert res2["skipped_count"] == 3
    assert res2["target_total"] == 3

    # Source database must not have been modified at all
    assert source_db.read_bytes() == source_bytes


def test_migrate_fails_when_source_missing(tmp_path):
    missing_file = str(tmp_path / "non_existent.db")
    with pytest.raises(FileNotFoundError):
        migrate_data(source_path=missing_file, target_sqlite_path=str(tmp_path / "target.db"))
