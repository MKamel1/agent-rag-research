"""migrate.py — apply the V0 SQLite schema (migrations/0001_init.sql) to a database file.

Usage:
    python migrations/migrate.py <path/to/db.sqlite>

Precondition: none — safe to run against a path that does not exist yet (sqlite3 creates the file).
Postcondition: the database at `path` has WAL journal mode active and contains exactly the V0 tables
(papers, blocks, chunks, summaries, ingest_state, quarantine) — no V1+ tables (DATA-CONTRACTS.md
"SQLite schema": V1 tables are named in a comment only, never created here).

This script is intentionally a thin, literal executor of 0001_init.sql — it does not contain any
DDL of its own. If the schema needs to change, edit 0001_init.sql (and DATA-CONTRACTS.md first,
since that doc is the source of truth), not this file.
"""

import sqlite3
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent
SCHEMA_FILE = MIGRATIONS_DIR / "0001_init.sql"


def migrate(db_path: str) -> None:
    """Apply the V0 schema to the SQLite database at `db_path`, creating the file if needed.

    Sets WAL journal mode (ADR-05) before creating tables. Table creation uses plain `CREATE TABLE`
    (no `IF NOT EXISTS`) — running this against an already-migrated database is expected to fail
    loudly (ContractError-equivalent for the schema: re-running a migration is a bug, not a no-op to
    paper over) rather than silently doing nothing.
    """
    schema_sql = SCHEMA_FILE.read_text()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: python {sys.argv[0]} <path/to/db.sqlite>", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    migrate(db_path)
    print(f"Migrated {db_path}: schema applied, WAL mode active.")


if __name__ == "__main__":
    main()
