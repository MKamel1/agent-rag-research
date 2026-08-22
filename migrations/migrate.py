"""migrate.py — apply the SQLite schema (migrations/000N_*.sql) to a database file.

Usage:
    python migrations/migrate.py <path/to/db.sqlite>

Precondition: none — safe to run against a path that does not exist yet (sqlite3 creates the file)
AND against an already-migrated, populated database (see T-DOC81 note in `migrate()` below).
Postcondition: the database at `path` has WAL journal mode active and contains exactly the tables
defined across every `000N_*.sql` file in this directory (0001_init.sql's V0 tables — papers,
blocks, chunks, summaries, ingest_state, quarantine — plus 0002_ingest_checkpoint.sql's
`ingest_checkpoint`, 0003_quarantine_diagnostics.sql's `quarantine_diagnostics`, and
0006_figures_tables.sql's `figures`/`tables`) — no V1+ tables (DATA-CONTRACTS.md "SQLite schema":
V1 tables are named in a comment only, never created here) — plus the `schema_version` tracking
table this file itself owns.

This script is intentionally a thin, literal executor of the numbered `.sql` files in this
directory — it does not contain any DDL of its own, other than `schema_version` (see below). If a
schema needs to change, edit the relevant `000N_*.sql` file (and DATA-CONTRACTS.md first, since
that doc is the source of truth), not this file. A new table is always a new, additive `000N_*.sql`
file (0001_init.sql's own header comment) — never an edit to an already-applied one.

`schema_version (filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL)` records exactly which
numbered files have been applied to this database and when. `migrate()` is idempotent: it applies
only the files not yet recorded, in filename order, recording each in the same transaction that
applies it (RI-24) -- so concurrent callers of `migrate()` against one fresh database tolerate each
other instead of colliding mid-file (see the except block in `migrate()`).
"""

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent

# RI-24: how long `migrate()` tolerates a peer connection holding the exclusive lock that the
# journal-mode conversion below needs. Sized to match sqlite3.connect()'s own default busy
# timeout (the wait every ordinary write on this connection already gets): the conversion itself
# takes milliseconds once granted, so this window bounds pathological contention, not normal work.
_WAL_CONVERSION_WINDOW_S = 5.0
_WAL_RETRY_INTERVAL_S = 0.01

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
    recorded in `schema_version`, in filename order, recording each in the same transaction that
    applies it. Calling this twice in a row is a no-op the second time.

    Concurrent callers against the same database (RI-24: two composition roots constructing on one
    brand-new db_path) do not collide: each file is applied-and-recorded atomically, so a loser
    whose apply hits a peer's just-committed file re-queries `schema_version`, finds the file
    recorded, and moves on. Any failure that leaves the file unrecorded still propagates -- see
    the except block in the loop below for why the recorded-state check, not the error text, is
    the discriminator.

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
        # RI-24: concurrent migrators against one brand-new file all try to flip it to WAL at the
        # same instant. That conversion takes a brief EXCLUSIVE lock, and -- observed while
        # reproducing this race (4 threads, fresh path) -- SQLite raises "database is locked"
        # immediately rather than routing the wait through connect()'s own busy timeout like an
        # ordinary write would. Bounded retry instead: whichever connection wins the flip settles
        # the file into WAL for everyone, after which the pragma is a no-op read for every later
        # caller. This is the ONE spot of the race handled by retrying rather than by the apply
        # loop's catch-and-recheck below: nothing has been applied or recorded yet, so there is no
        # recorded state to re-query -- the only way forward is to attempt the conversion again.
        # The window matches sqlite3.connect()'s default busy timeout; expiry re-raises, loud.
        wal_deadline = time.monotonic() + _WAL_CONVERSION_WINDOW_S
        while True:
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                break
            except sqlite3.OperationalError:
                if time.monotonic() >= wal_deadline:
                    raise
                time.sleep(_WAL_RETRY_INTERVAL_S)
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
            # T-DOC81 review fix: executescript() runs in autocommit -- each statement in the file
            # commits as it goes, with NO transaction wrapping the whole script. A file with more
            # than one statement (0004's two ALTERs) that fails partway through then leaves the
            # earlier statements permanently committed while the file itself is never recorded --
            # every later migrate() call dies on that already-applied prefix, forever (this is what
            # actually happened to 0004 in production). Wrapping the script in an explicit BEGIN
            # makes it one transaction: SQLite DDL is transactional, so a mid-script failure leaves
            # the transaction open and unwound by the rollback below (or, before RI-24, by the
            # `finally: conn.close()`). DO NOT remove this wrapper as redundant-looking noise.
            #
            # RI-24: the recording INSERT deliberately joins that same transaction (the script text
            # carries no COMMIT of its own) -- apply and record become atomically visible together,
            # so no other migrator can ever observe the half-state "artifacts committed but file
            # unrecorded" that a crash between two separate commits used to leave behind.
            try:
                conn.executescript(f"BEGIN;\n{schema_file.read_text()}")
                _record_applied(conn, schema_file.name)
                conn.commit()
            except sqlite3.OperationalError:
                # Same race `rag/vector_index.py`'s `_ensure_collection()` handles for concurrent
                # collection creators: every composition root migrates at construction
                # (DocumentStore.__init__, SqliteIngestState.__init__, this module's own main), so
                # two processes starting against the same brand-new db_path both see an empty
                # applied set and both run this loop; the loser hits whatever the winner just
                # committed ("table ... already exists", "duplicate column name") or the write lock
                # itself ("database is locked"). The discriminator is the OUTCOME, not the error
                # string: recording lives inside the failed transaction, so if a re-query now shows
                # this file recorded, a peer's byte-for-byte identical apply of the same file
                # committed successfully and the database is in exactly the state we were about to
                # produce -- treat it as applied and move on. If it is still unrecorded, nothing
                # verified happened (a genuine syntax error, a real authoring mistake like two
                # files creating the same table, or lock contention nobody won): re-raise rather
                # than swallow. The rollback first unwinds the failed transaction so this
                # connection stays usable for the remaining files.
                conn.rollback()
                applied = {row[0] for row in conn.execute("SELECT filename FROM schema_version")}
                if schema_file.name not in applied:
                    raise
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
