"""migrate.py — apply the SQLite schema (migrations/000N_*.sql) to a database file.

Usage:
    python migrations/migrate.py <path/to/db.sqlite>

Precondition: none — safe to run against a path that does not exist yet (sqlite3 creates the file).
Postcondition: the database at `path` has WAL journal mode active and contains exactly the tables
defined across every `000N_*.sql` file in this directory (0001_init.sql's V0 tables — papers,
blocks, chunks, summaries, ingest_state, quarantine — plus 0002_ingest_checkpoint.sql's
`ingest_checkpoint`) — no V1+ tables (DATA-CONTRACTS.md "SQLite schema": V1 tables are named in a
comment only, never created here).

This script is intentionally a thin, literal executor of the numbered `.sql` files in this
directory — it does not contain any DDL of its own. If a schema needs to change, edit the
relevant `000N_*.sql` file (and DATA-CONTRACTS.md first, since that doc is the source of truth),
not this file. A new table is always a new, additive `000N_*.sql` file (0001_init.sql's own header
comment) — never an edit to an already-applied one.

Note on the `000N_` filenames: despite the numbering, there is no tracked-migration framework here
(no `schema_version` table, no partial-apply resume) — every file in this directory is applied, in
filename order, every time `migrate()` runs. Re-running against an already-migrated database is
expected to fail loudly (see `test_migrate_on_already_migrated_db_fails_loudly_not_silently`), not
silently no-op.
"""

import sqlite3
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent


def _schema_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def migrate(db_path: str) -> None:
    """Apply every numbered schema file to the SQLite database at `db_path`, creating the file if
    needed, in filename order (0001 before 0002, ...).

    Sets WAL journal mode (ADR-05) before creating tables. Table creation uses plain `CREATE TABLE`
    (no `IF NOT EXISTS`) — running this against an already-migrated database is expected to fail
    loudly (ContractError-equivalent for the schema: re-running a migration is a bug, not a no-op to
    paper over) rather than silently doing nothing.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        for schema_file in _schema_files():
            conn.executescript(schema_file.read_text())
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
