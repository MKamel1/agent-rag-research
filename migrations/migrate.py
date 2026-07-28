"""migrate.py — apply the SQLite schema (migrations/000N_*.sql) to a database file.

Usage:
    python migrations/migrate.py <path/to/db.sqlite>

Precondition: none — safe to run against a path that does not exist yet (sqlite3 creates the file)
AND against an already-migrated, populated database (see T-DOC81 note in `migrate()` below).
Postcondition: the database at `path` has WAL journal mode active and contains exactly the tables
defined across every `000N_*.sql` file in this directory (0001_init.sql's V0 tables — papers,
blocks, chunks, summaries, ingest_state, quarantine — plus 0002_ingest_checkpoint.sql's
`ingest_checkpoint`) — no V1+ tables (DATA-CONTRACTS.md "SQLite schema": V1 tables are named in a
comment only, never created here) — plus the `schema_version` tracking table this file itself owns.

This script is intentionally a thin, literal executor of the numbered `.sql` files in this
directory — it does not contain any DDL of its own, other than `schema_version` (see below). If a
schema needs to change, edit the relevant `000N_*.sql` file (and DATA-CONTRACTS.md first, since
that doc is the source of truth), not this file. A new table is always a new, additive `000N_*.sql`
file (0001_init.sql's own header comment) — never an edit to an already-applied one.

`schema_version (filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL)` records exactly which
numbered files have been applied to this database and when. `migrate()` is idempotent: it applies
only the files not yet recorded, in filename order, recording each immediately after it succeeds.
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""
# The one legitimate `IF NOT EXISTS` in this codebase (T-DOC81): schema_version is the tracking
# mechanism itself, which by definition cannot be tracked by itself.

# T-DOC81 adoption probes — HISTORICAL AND FIXED, do not extend this dict for a new migration.
# These four entries exist only to classify databases that predate `schema_version` (production,
# on the day T-DOC81 landed: 0001-0004 already applied — 0004 by hand — nothing recorded). Every
# migration from 0005 onward is recorded the moment `migrate()`'s own loop below applies it, so it
# needs no probe, ever. If you're adding a migration and reaching for this dict: stop, you don't
# need to touch it.
_ADOPTION_PROBES = {
    "0001_init.sql": lambda conn: _table_exists(conn, "papers"),
    "0002_ingest_checkpoint.sql": lambda conn: _table_exists(conn, "ingest_checkpoint"),
    "0003_quarantine_diagnostics.sql": lambda conn: _table_exists(conn, "quarantine_diagnostics"),
    "0004_doc_type_and_chapter_titles.sql": lambda conn: _column_exists(
        conn, "papers", "doc_type"
    ),
}


def _schema_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _has_any_application_table(conn: sqlite3.Connection) -> bool:
    """True if the database has any table besides `schema_version` itself — the signal that this
    is a pre-existing database (adopt what's present) rather than a brand-new one (nothing to
    adopt; every file below applies normally)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name != 'schema_version' LIMIT 1"
    ).fetchone()
    return row is not None


def _record_applied(conn: sqlite3.Connection, filename: str) -> None:
    conn.execute(
        "INSERT INTO schema_version (filename, applied_at) VALUES (?, ?)",
        (filename, datetime.now(timezone.utc).isoformat()),
    )


def _adopt(conn: sqlite3.Connection) -> None:
    """Classify a pre-existing, unrecorded database by running each historical probe in
    `_ADOPTION_PROBES` and recording every migration whose artifact is found present."""
    for filename, probe in _ADOPTION_PROBES.items():
        if probe(conn):
            _record_applied(conn, filename)


def migrate(db_path: str) -> None:
    """Bring the SQLite database at `db_path` up to date with every numbered schema file in this
    directory, creating the file if needed. Idempotent (T-DOC81): applies only the files not yet
    recorded in `schema_version`, in filename order, recording each immediately after it succeeds.
    Calling this twice in a row is a no-op the second time.

    A database that predates `schema_version` but already has application tables (production, the
    day T-DOC81 landed) is adopted first — see `_adopt` — so it is classified as already having
    whatever migrations its schema shows evidence of, instead of `migrate()` trying to re-apply
    them and failing. A brand-new database has nothing to adopt, so every file applies normally.
    One code path for both.

    Sets WAL journal mode (ADR-05) and foreign_keys=ON before any DDL.

    T-DOC81 note — read this before changing the contract again: this function used to apply every
    file unconditionally on every call, with no tracking, and re-running it against an
    already-migrated database was expected to fail loudly ("re-running is a bug", pinned by
    `test_migrate_on_already_migrated_db_fails_loudly_not_silently`). That assumption is exactly
    what made the gap structural: with no idempotent path, an additive migration (0004) had no
    supported way to reach a database that already had rows, so it never ran against production —
    it was applied by hand instead (WORK-BREAKDOWN.md T-DOC81). Re-running is now the supported,
    expected path. The old intent (never silently skip work that was actually needed) survives in
    a better form: `schema_version` records exactly what was applied and when, so "did this
    migration run?" is answerable by querying it, not by inferring from whether `migrate()` raised.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        # T-DOC40: this connection only ever runs DDL (CREATE TABLE/ALTER TABLE), so the pragma has
        # no observable effect here -- set anyway for consistency with every other seam that opens
        # a sqlite3 connection against this schema (DocumentStore, rag/document_store.py), so no
        # future caller of this module can assume FK enforcement is off just because migrate() ran.
        conn.execute("PRAGMA foreign_keys=ON;")

        conn.execute(_SCHEMA_VERSION_DDL)
        conn.commit()

        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_version")}
        if not applied and _has_any_application_table(conn):
            _adopt(conn)
            conn.commit()
            applied = {row[0] for row in conn.execute("SELECT filename FROM schema_version")}

        for schema_file in _schema_files():
            if schema_file.name in applied:
                continue
            conn.executescript(schema_file.read_text())
            _record_applied(conn, schema_file.name)
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
