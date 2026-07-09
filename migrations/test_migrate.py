"""Runnable check for migrations/migrate.py — not wired into the default pytest testpaths (that's
T-F5/T-F6's CI-harness territory, out of this ticket's scope); invoke directly with
`pytest migrations/test_migrate.py`.

Verifies T-F3's acceptance criteria (WORK-BREAKDOWN.md "M0"): the schema creates cleanly, WAL mode
is active, and the V0 table set is exactly what DATA-CONTRACTS.md's "SQLite schema" section
specifies — no V1+ tables (claims/claim_relations/citation_edges), which that section names as "DO
NOT CREATE IN V0".
"""

import sqlite3

import pytest

from migrations.migrate import migrate

V0_TABLES = {"papers", "blocks", "chunks", "summaries", "ingest_state", "quarantine"}
V1_TABLES_NOT_CREATED = {"claims", "claim_relations", "citation_edges"}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    return {r[0] for r in rows}


def test_migrate_creates_exactly_the_v0_tables(tmp_path):
    db_path = str(tmp_path / "test.sqlite")

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        tables = _table_names(conn)
        assert tables == V0_TABLES
        assert tables.isdisjoint(V1_TABLES_NOT_CREATED)
    finally:
        conn.close()


def test_migrate_sets_wal_journal_mode(tmp_path):
    db_path = str(tmp_path / "test.sqlite")

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode == "wal"
    finally:
        conn.close()


def test_migrate_on_already_migrated_db_fails_loudly_not_silently(tmp_path):
    """Re-running the migration against an already-migrated database must raise, not silently
    no-op — a migration that swallows 'table already exists' would mask a real double-apply bug."""
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)

    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        migrate(db_path)
