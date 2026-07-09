"""Runnable check for migrations/migrate.py — not wired into the default pytest testpaths (that's
T-F5/T-F6's CI-harness territory, out of this ticket's scope); invoke directly with
`pytest migrations/test_migrate.py`.

Verifies T-F3's acceptance criteria (WORK-BREAKDOWN.md "M0"): the schema creates cleanly, WAL mode
is active, and the V0 table set is exactly what DATA-CONTRACTS.md's "SQLite schema" section
specifies — no V1+ tables (claims/claim_relations/citation_edges), which that section names as "DO
NOT CREATE IN V0".
"""

import re
import sqlite3
from pathlib import Path

import pytest

from migrations.migrate import migrate

V0_TABLES = {"papers", "blocks", "chunks", "summaries", "ingest_state", "quarantine"}
V1_TABLES_NOT_CREATED = {"claims", "claim_relations", "citation_edges"}

REPO_ROOT = Path(__file__).parent.parent
DATA_CONTRACTS = REPO_ROOT / "DATA-CONTRACTS.md"
SCHEMA_FILE = Path(__file__).parent / "0001_init.sql"


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


def _extract_schema_sql_block(markdown_text: str) -> str:
    """Pull the ```sql ... ``` block under DATA-CONTRACTS.md's "## SQLite schema" heading."""
    match = re.search(r"## SQLite schema.*?```sql\n(.*?)\n```", markdown_text, re.DOTALL)
    assert match, "Could not find the SQLite schema code block in DATA-CONTRACTS.md"
    return match.group(1)


def _schema_snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Structural snapshot keyed by table name: sorted (name, type, notnull, pk) per column.

    Going through SQLite's own parser (executescript + PRAGMA table_info) means whitespace and
    comment differences between the two DDL copies can't cause a false mismatch — only real
    structural drift (a missing/renamed/retyped column, a dropped NOT NULL or PK) will.
    """
    return {
        table: sorted(
            (c[1], c[2], c[3], c[5]) for c in conn.execute(f"PRAGMA table_info('{table}')")
        )
        for table in _table_names(conn)
    }


def test_0001_init_matches_data_contracts_schema():
    """DDL parity check, mechanizing the invariant 0001_init.sql's own header declares ("if this
    ever needs to diverge from DATA-CONTRACTS.md... fix DATA-CONTRACTS.md first, then this file"):
    the two copies of the schema must stay structurally identical, not just eyeballed-equal."""
    contracts_sql = _extract_schema_sql_block(DATA_CONTRACTS.read_text())
    init_sql = SCHEMA_FILE.read_text()

    contracts_conn = sqlite3.connect(":memory:")
    init_conn = sqlite3.connect(":memory:")
    try:
        contracts_conn.executescript(contracts_sql)
        init_conn.executescript(init_sql)

        assert _table_names(contracts_conn) == _table_names(init_conn) == V0_TABLES
        assert _schema_snapshot(contracts_conn) == _schema_snapshot(init_conn)
    finally:
        contracts_conn.close()
        init_conn.close()
