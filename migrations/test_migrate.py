"""Runnable check for migrations/migrate.py — collected by default (`pyproject.toml` testpaths,
T-DOC81 review fix: `migrations/` previously had no `__init__.py`, so pytest's default import mode
couldn't resolve `from migrations.migrate import migrate` without `PYTHONPATH` set by hand, and
this suite silently never ran in CI). Can still be invoked directly with
`pytest migrations/test_migrate.py`.

Verifies T-F3's acceptance criteria (WORK-BREAKDOWN.md "M0"): the schema creates cleanly, WAL mode
is active, and the table set `migrate()` produces is exactly what DATA-CONTRACTS.md's "SQLite
schema" section specifies — no V1+ tables (claims/claim_relations/citation_edges), which that
section names as "DO NOT CREATE IN V0".

T-A2 checkpoint-durability fix (`.phase0-data/orchestrator-checkpoint-proposal.md`, Option A) added
0002_ingest_checkpoint.sql, additive to 0001_init.sql's V0 set — `migrate()` now applies both, so
`ALL_TABLES` (not `V0_TABLES`) is what a freshly migrated database actually contains.

T-DOC17 parse-failure-diagnostics fix added 0003_quarantine_diagnostics.sql, additive to
`quarantine` — `ALL_TABLES` now also includes `quarantine_diagnostics`.
"""

import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from migrations import migrate as migrate_module
from migrations.migrate import migrate

V0_TABLES = {"papers", "blocks", "chunks", "summaries", "ingest_state", "quarantine"}
ALL_TABLES = V0_TABLES | {"ingest_checkpoint", "quarantine_diagnostics"}
# Table set after every migration through 0006 (figures/tables, RI-18) has applied -- distinct
# from ALL_TABLES above, which the 0004/0005 parity tests below still use to mean "the table set
# as of THAT migration," not the whole-schema final set.
ALL_TABLES_THROUGH_0006 = ALL_TABLES | {"figures", "tables"}
# T-DOC81: schema_version is created unconditionally by migrate() itself (the one legitimate
# `CREATE TABLE IF NOT EXISTS` in this codebase) -- it exists in every database migrate() has
# touched, fresh or adopted. Only tests that call migrate() should expect it; the DDL-parity tests
# below build a schema by executing the raw `.sql` files directly and never see it, so they keep
# comparing against plain ALL_TABLES (or ALL_TABLES_THROUGH_0006, for the 0006-scoped ones).
MIGRATED_TABLES = ALL_TABLES_THROUGH_0006 | {"schema_version"}
# Pre-existing bug, unrelated to T-DOC81: 0001+0002 alone don't create quarantine_diagnostics
# (that's 0003) or doc_type (that's 0004) -- the 0002-scoped parity test below must compare
# against what 0001+0002 actually create, not the whole-schema ALL_TABLES.
CHECKPOINT_TABLES = V0_TABLES | {"ingest_checkpoint"}
V1_TABLES_NOT_CREATED = {"claims", "claim_relations", "citation_edges"}
ALL_MIGRATION_FILENAMES = {
    "0001_init.sql",
    "0002_ingest_checkpoint.sql",
    "0003_quarantine_diagnostics.sql",
    "0004_doc_type_and_chapter_titles.sql",
    "0005_author_orgs.sql",
    "0006_figures_tables.sql",
}

REPO_ROOT = Path(__file__).parent.parent
DATA_CONTRACTS = REPO_ROOT / "DATA-CONTRACTS.md"
SCHEMA_FILE = Path(__file__).parent / "0001_init.sql"
CHECKPOINT_SCHEMA_FILE = Path(__file__).parent / "0002_ingest_checkpoint.sql"
QUARANTINE_DIAGNOSTICS_SCHEMA_FILE = Path(__file__).parent / "0003_quarantine_diagnostics.sql"
DOC_TYPE_AND_TITLES_SCHEMA_FILE = Path(__file__).parent / "0004_doc_type_and_chapter_titles.sql"
AUTHOR_ORGS_SCHEMA_FILE = Path(__file__).parent / "0005_author_orgs.sql"
FIGURES_TABLES_SCHEMA_FILE = Path(__file__).parent / "0006_figures_tables.sql"


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    return {r[0] for r in rows}


def _applied_migrations(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT filename FROM schema_version;").fetchall()
    return {r[0] for r in rows}


def _raw_apply(conn: sqlite3.Connection, *schema_files: Path) -> None:
    """Apply schema files directly with `executescript`, bypassing `migrate()` entirely -- this is
    how every T-DOC81 test builds a database that predates (or partially has) the `schema_version`
    table, i.e. the exact shape production was in before this ticket."""
    for schema_file in schema_files:
        conn.executescript(schema_file.read_text())
    conn.commit()


def _insert_minimal_paper(conn: sqlite3.Connection, paper_id: str, doc_type_column: bool) -> None:
    """Insert one row into `papers` with just enough columns for the NOT NULL constraints 0001_init
    declares, optionally including the 0004 `doc_type` column when the caller has already applied
    that migration."""
    columns = [
        "paper_id", "version", "title", "abstract", "authors_json", "categories_json",
        "published", "updated", "pdf_path", "markdown_path",
    ]
    values = [paper_id, "v1", "T", "A", "[]", "[]", "2020-01-01", "2020-01-01", "pdf", "md"]
    if doc_type_column:
        columns.append("doc_type")
        values.append("paper")
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO papers ({', '.join(columns)}) VALUES ({placeholders})", values
    )
    conn.commit()


def _insert_minimal_chunk(conn: sqlite3.Connection, chunk_id: str, paper_id: str) -> None:
    conn.execute(
        "INSERT INTO chunks (chunk_id, paper_id, text, anchor_json, section_path) "
        "VALUES (?, ?, ?, ?, ?)",
        (chunk_id, paper_id, "chunk text", "{}", "sec"),
    )
    conn.commit()


def test_migrate_creates_exactly_the_v0_and_checkpoint_tables(tmp_path):
    db_path = str(tmp_path / "test.sqlite")

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        tables = _table_names(conn)
        assert tables == MIGRATED_TABLES
        assert tables.isdisjoint(V1_TABLES_NOT_CREATED)
        # T-DOC81 required test #4 (fresh DB): every migration file applies and is recorded --
        # pins that the new schema_version machinery didn't break the original from-scratch path.
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
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


def test_migrate_on_already_migrated_db_is_idempotent_not_a_failure(tmp_path):
    """T-DOC81 REVERSES this test's former contract -- it used to be named
    `..._fails_loudly_not_silently` and asserted `migrate()` raises `sqlite3.OperationalError` on
    a second call. That was deliberate at the time ("re-running is a bug"), but it is exactly the
    assumption that made the gap structural: with no idempotent path, an additive migration (0004)
    had no supported way to reach a database that already had rows, so it never ran against
    production and was applied by hand instead (WORK-BREAKDOWN.md T-DOC81). Re-running is now the
    supported, expected path -- `schema_version` answers "did this migration run?" directly,
    instead of that question being inferred from whether `migrate()` raised."""
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        recorded_before = {
            row for row in conn.execute("SELECT filename, applied_at FROM schema_version")
        }
    finally:
        conn.close()

    migrate(db_path)  # must NOT raise

    conn = sqlite3.connect(db_path)
    try:
        recorded_after = {
            row for row in conn.execute("SELECT filename, applied_at FROM schema_version")
        }
        # Same rows, same applied_at timestamps: the second call did not re-apply anything.
        assert recorded_after == recorded_before
    finally:
        conn.close()


def test_migrate_twice_in_a_row_is_a_noop_the_second_time(tmp_path):
    """T-DOC81 required test #3 (idempotency): calling `migrate()` twice consecutively must not
    raise and must not change what's recorded or applied."""
    db_path = str(tmp_path / "test.sqlite")

    migrate(db_path)
    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        assert _table_names(conn) == MIGRATED_TABLES
    finally:
        conn.close()


N_RACING_CALLERS = 4


def test_concurrent_migrate_calls_on_one_fresh_db_all_succeed(tmp_path):
    """RI-24: every composition root migrates at construction (`DocumentStore.__init__`,
    `SqliteIngestState.__init__`, `python -m migrations.migrate`), and two of them starting
    against the SAME brand-new db_path (dashboard coming up while an ingest bootstraps a new
    corpus, RI-5) both see an empty `schema_version` and both run the apply loop. Before this
    fix the loser died with `duplicate column name`/`table already exists` inside whichever
    file the winner had just applied -- out of `__init__`, killing startup.

    Drives the actual race the way the reviewer reproduced it: several threads, one fresh
    path, all released together at a barrier. Every caller must return normally, and the
    finished database must be exactly the standard migrated set with each file recorded
    exactly once (the T-DOC81 BEGIN/COMMIT wrapper already keeps losers rolled back and
    unrecorded; what was missing was tolerating "a peer just applied this")."""
    db_path = str(tmp_path / "test.sqlite")
    barrier = threading.Barrier(N_RACING_CALLERS)

    def _attempt() -> None:
        barrier.wait(timeout=30)
        migrate(db_path)

    with ThreadPoolExecutor(max_workers=N_RACING_CALLERS) as pool:
        futures = [pool.submit(_attempt) for _ in range(N_RACING_CALLERS)]
        outcomes = [future.exception(timeout=60) for future in futures]

    assert outcomes == [None] * N_RACING_CALLERS

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        for filename in sorted(ALL_MIGRATION_FILENAMES):
            count = conn.execute(
                "SELECT COUNT(*) FROM schema_version WHERE filename = ?", (filename,)
            ).fetchone()[0]
            assert count == 1, f"{filename} recorded {count} times"
        assert _table_names(conn) == MIGRATED_TABLES
    finally:
        conn.close()


def test_migrate_applies_additive_migration_to_populated_db_and_preserves_data(tmp_path):
    """T-DOC81 required test #1 -- the test that would have caught the actual incident: a database
    at an older schema version, with real rows, must pick up a later additive migration (0004)
    without losing anything already in it. Every pre-T-DOC81 test starts from an empty `tmp_path`,
    where 0001-0004 apply cleanly in order and this path is never exercised."""
    db_path = str(tmp_path / "test.sqlite")
    conn = sqlite3.connect(db_path)
    try:
        _raw_apply(
            conn, SCHEMA_FILE, CHECKPOINT_SCHEMA_FILE, QUARANTINE_DIAGNOSTICS_SCHEMA_FILE
        )
        _insert_minimal_paper(conn, "p1", doc_type_column=False)
        _insert_minimal_chunk(conn, "c1", "p1")
    finally:
        conn.close()

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
        assert "doc_type" in cols
        paper = conn.execute(
            "SELECT paper_id, title, doc_type FROM papers WHERE paper_id = 'p1'"
        ).fetchone()
        assert paper == ("p1", "T", "paper")  # pre-existing row survived and got the new default
        chunk = conn.execute(
            "SELECT chunk_id FROM chunks WHERE paper_id = 'p1'"
        ).fetchone()
        assert chunk == ("c1",)
    finally:
        conn.close()


def test_migrate_applies_0005_author_orgs_to_populated_db_and_preserves_data(tmp_path):
    """T-ORG1's own version of the T-DOC81 required test #1: 0005 is additive on top of 0001-0004
    -- a database with real rows and no `raw_affiliations`/`author_orgs` columns yet must pick
    them up (as NULL, since nothing has run the tagger against pre-existing rows) without losing
    anything already there."""
    db_path = str(tmp_path / "test.sqlite")
    conn = sqlite3.connect(db_path)
    try:
        _raw_apply(
            conn,
            SCHEMA_FILE,
            CHECKPOINT_SCHEMA_FILE,
            QUARANTINE_DIAGNOSTICS_SCHEMA_FILE,
            DOC_TYPE_AND_TITLES_SCHEMA_FILE,
        )
        _insert_minimal_paper(conn, "p1", doc_type_column=True)
        _insert_minimal_chunk(conn, "c1", "p1")
    finally:
        conn.close()

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
        assert {"raw_affiliations", "author_orgs"} <= cols
        paper = conn.execute(
            "SELECT paper_id, title, raw_affiliations, author_orgs FROM papers WHERE paper_id = 'p1'"
        ).fetchone()
        assert paper == ("p1", "T", None, None)  # pre-existing row survived; new columns NULL
        chunk = conn.execute("SELECT chunk_id FROM chunks WHERE paper_id = 'p1'").fetchone()
        assert chunk == ("c1",)
    finally:
        conn.close()


def test_migrate_twice_in_a_row_is_a_noop_the_second_time_including_0005(tmp_path):
    """Idempotency for 0005 specifically (mirrors `test_migrate_twice_in_a_row_is_a_noop_the_second_time`
    for 0001-0004): calling `migrate()` twice consecutively must not raise and must leave exactly
    one recorded application of 0005."""
    db_path = str(tmp_path / "test.sqlite")

    migrate(db_path)
    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        rows = conn.execute(
            "SELECT COUNT(*) FROM schema_version WHERE filename = '0005_author_orgs.sql'"
        ).fetchone()
        assert rows[0] == 1
        cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
        assert {"raw_affiliations", "author_orgs"} <= cols
    finally:
        conn.close()


def test_migrate_applies_0006_figures_tables_to_populated_db_and_preserves_data(tmp_path):
    """RI-18's own version of the T-DOC81 required test #1: 0006 (figures/tables, new child
    tables rather than an ALTER) is additive on top of 0001-0005 -- a database with real rows and
    no `figures`/`tables` tables yet must pick them up without losing anything already there.

    Stops the raw-apply at 0004, like `test_migrate_applies_0005_author_orgs_...` above: 0005 has
    no `_ADOPTION_PROBES` entry (only 0001-0004 do, by design -- see `migrations/migrate.py`), so
    raw-applying 0005 here too would make `migrate()`'s own loop try to re-apply it and fail on
    `raw_affiliations` already existing -- letting `migrate()` apply 0005 (and then 0006) itself
    through its normal loop is the realistic "never touched by hand" scenario anyway."""
    db_path = str(tmp_path / "test.sqlite")
    conn = sqlite3.connect(db_path)
    try:
        _raw_apply(
            conn,
            SCHEMA_FILE,
            CHECKPOINT_SCHEMA_FILE,
            QUARANTINE_DIAGNOSTICS_SCHEMA_FILE,
            DOC_TYPE_AND_TITLES_SCHEMA_FILE,
        )
        _insert_minimal_paper(conn, "p1", doc_type_column=True)
        _insert_minimal_chunk(conn, "c1", "p1")
    finally:
        conn.close()

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        assert {"figures", "tables"} <= _table_names(conn)
        paper = conn.execute(
            "SELECT paper_id, title FROM papers WHERE paper_id = 'p1'"
        ).fetchone()
        assert paper == ("p1", "T")  # pre-existing row survived
        chunk = conn.execute("SELECT chunk_id FROM chunks WHERE paper_id = 'p1'").fetchone()
        assert chunk == ("c1",)
    finally:
        conn.close()


def test_migrate_twice_in_a_row_is_a_noop_the_second_time_including_0006(tmp_path):
    """Idempotency for 0006 specifically (mirrors the 0005 version above): calling `migrate()`
    twice consecutively must not raise and must leave exactly one recorded application of 0006."""
    db_path = str(tmp_path / "test.sqlite")

    migrate(db_path)
    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        rows = conn.execute(
            "SELECT COUNT(*) FROM schema_version WHERE filename = '0006_figures_tables.sql'"
        ).fetchone()
        assert rows[0] == 1
        assert {"figures", "tables"} <= _table_names(conn)
    finally:
        conn.close()


def test_migrate_adopts_a_database_matching_productions_exact_shape(tmp_path):
    """T-DOC81 required test #2 -- production's exact shape the day this ticket was opened: 0001
    through 0004 already applied (0004 by hand, per WORK-BREAKDOWN.md), no `schema_version` table
    at all. `migrate()` must adopt all four as already-applied, re-apply none of them, and leave
    the existing data untouched."""
    db_path = str(tmp_path / "test.sqlite")
    conn = sqlite3.connect(db_path)
    try:
        _raw_apply(
            conn,
            SCHEMA_FILE,
            CHECKPOINT_SCHEMA_FILE,
            QUARANTINE_DIAGNOSTICS_SCHEMA_FILE,
            DOC_TYPE_AND_TITLES_SCHEMA_FILE,
        )
        _insert_minimal_paper(conn, "p1", doc_type_column=True)
        _insert_minimal_chunk(conn, "c1", "p1")
    finally:
        conn.close()

    migrate(db_path)  # must NOT raise -- this is the exact re-run-against-existing-data path

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        assert _table_names(conn) == MIGRATED_TABLES
        paper = conn.execute(
            "SELECT paper_id FROM papers WHERE paper_id = 'p1'"
        ).fetchone()
        assert paper == ("p1",)
        chunk = conn.execute("SELECT chunk_id FROM chunks WHERE paper_id = 'p1'").fetchone()
        assert chunk == ("c1",)
    finally:
        conn.close()


def test_migrate_partially_adopts_and_applies_the_rest(tmp_path):
    """T-DOC81 required test #5: a database with only 0001-0002 applied by hand (no
    `quarantine_diagnostics` table, no `doc_type` column) -- `migrate()` must adopt the two present
    and apply the two missing, ending up fully up to date."""
    db_path = str(tmp_path / "test.sqlite")
    conn = sqlite3.connect(db_path)
    try:
        _raw_apply(conn, SCHEMA_FILE, CHECKPOINT_SCHEMA_FILE)
        _insert_minimal_paper(conn, "p1", doc_type_column=False)
    finally:
        conn.close()

    migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert _applied_migrations(conn) == ALL_MIGRATION_FILENAMES
        assert _table_names(conn) == MIGRATED_TABLES
        cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
        assert "doc_type" in cols
        paper = conn.execute(
            "SELECT paper_id FROM papers WHERE paper_id = 'p1'"
        ).fetchone()
        assert paper == ("p1",)
    finally:
        conn.close()


def test_migrate_rolls_back_a_failed_migration_file_and_does_not_compound_on_retry(
    tmp_path, monkeypatch
):
    """T-DOC81 review fix: `executescript()` runs in autocommit, not one transaction per file -- a
    mid-file failure used to leave the file's earlier statements permanently committed while the
    file itself went unrecorded, so every later `migrate()` call died on the already-applied
    prefix forever (reproduced end to end against 0004's two ALTERs in review). `migrate()` now
    wraps each file's script in BEGIN/COMMIT so a failure rolls back the whole file, leaving it
    cleanly unapplied and unrecorded, and a retry fails the same clean way instead of compounding.

    Uses a throwaway migrations directory under `tmp_path` (monkeypatching `MIGRATIONS_DIR`) --
    never touches the real `migrations/` directory."""
    fake_dir = tmp_path / "fake_migrations"
    fake_dir.mkdir()
    (fake_dir / "0001_init.sql").write_text("CREATE TABLE papers (paper_id TEXT PRIMARY KEY);")
    # Second statement fails (references a table that doesn't exist) -- AFTER the first succeeds.
    (fake_dir / "0002_broken.sql").write_text(
        "CREATE TABLE ingest_checkpoint (paper_id TEXT PRIMARY KEY);\n"
        "ALTER TABLE nonexistent_table ADD COLUMN x TEXT;"
    )
    monkeypatch.setattr(migrate_module, "MIGRATIONS_DIR", fake_dir)

    db_path = str(tmp_path / "test.sqlite")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        # The whole 0002 file rolled back -- ingest_checkpoint must NOT exist, half-applied.
        assert "ingest_checkpoint" not in _table_names(conn)
        assert _applied_migrations(conn) == {"0001_init.sql"}
    finally:
        conn.close()

    # Retry must fail the same clean way (0001 recorded and skipped, 0002 fails on its own broken
    # ALTER again) -- NOT a compounded "table ingest_checkpoint already exists" from a half-applied
    # prior attempt, which is what the un-wrapped executescript() used to produce.
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        migrate(db_path)

    conn = sqlite3.connect(db_path)
    try:
        assert "ingest_checkpoint" not in _table_names(conn)
        assert _applied_migrations(conn) == {"0001_init.sql"}
    finally:
        conn.close()


def _extract_schema_sql_block(markdown_text: str, heading: str) -> str:
    """Pull the first ```sql ... ``` block under the given markdown heading."""
    match = re.search(re.escape(heading) + r".*?```sql\n(.*?)\n```", markdown_text, re.DOTALL)
    assert match, f"Could not find a sql code block under {heading!r} in DATA-CONTRACTS.md"
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
    contracts_sql = _extract_schema_sql_block(DATA_CONTRACTS.read_text(), "## SQLite schema")
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


def test_0002_ingest_checkpoint_matches_data_contracts_schema():
    """Same DDL parity check as `test_0001_init_matches_data_contracts_schema`, for the additive
    `ingest_checkpoint` table (T-A2 checkpoint-durability fix). `ingest_checkpoint` REFERENCES
    `ingest_state`, so both schema files must be applied together for the FK-bearing DDL to
    parse."""
    contracts_sql = _extract_schema_sql_block(
        DATA_CONTRACTS.read_text(), "### ingest_checkpoint"
    )
    checkpoint_sql = CHECKPOINT_SCHEMA_FILE.read_text()

    contracts_conn = sqlite3.connect(":memory:")
    init_conn = sqlite3.connect(":memory:")
    try:
        contracts_conn.executescript(SCHEMA_FILE.read_text())
        contracts_conn.executescript(contracts_sql)
        init_conn.executescript(SCHEMA_FILE.read_text())
        init_conn.executescript(checkpoint_sql)

        assert _table_names(contracts_conn) == _table_names(init_conn) == CHECKPOINT_TABLES
        assert _schema_snapshot(contracts_conn) == _schema_snapshot(init_conn)
    finally:
        contracts_conn.close()
        init_conn.close()


def test_0004_doc_type_and_chapter_titles_matches_data_contracts_schema():
    """Same DDL parity check, for the additive `papers.doc_type` / `summaries.title` columns
    (T-DOC80 drop-in-folder + book ingestion). Unlike 0002/0003, 0004 adds no new table — just two
    `ALTER TABLE ADD COLUMN`s on tables 0001_init.sql already created — so both must be applied
    first for the ALTERs to have a table to target."""
    contracts_sql = _extract_schema_sql_block(
        DATA_CONTRACTS.read_text(), "### doc_type + chapter titles"
    )
    doc_type_sql = DOC_TYPE_AND_TITLES_SCHEMA_FILE.read_text()

    contracts_conn = sqlite3.connect(":memory:")
    init_conn = sqlite3.connect(":memory:")
    try:
        contracts_conn.executescript(SCHEMA_FILE.read_text())
        contracts_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        contracts_conn.executescript(QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text())
        contracts_conn.executescript(contracts_sql)
        init_conn.executescript(SCHEMA_FILE.read_text())
        init_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        init_conn.executescript(QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text())
        init_conn.executescript(doc_type_sql)

        assert _table_names(contracts_conn) == _table_names(init_conn) == ALL_TABLES
        assert _schema_snapshot(contracts_conn) == _schema_snapshot(init_conn)
    finally:
        contracts_conn.close()
        init_conn.close()


def test_0005_author_orgs_matches_data_contracts_schema():
    """Same DDL parity check, for the additive `papers.raw_affiliations` / `papers.author_orgs`
    columns (T-ORG1). Like 0004, adds no new table -- just two `ALTER TABLE ADD COLUMN`s on
    `papers`, which 0001-0004 must already have created."""
    contracts_sql = _extract_schema_sql_block(DATA_CONTRACTS.read_text(), "### author orgs")
    author_orgs_sql = AUTHOR_ORGS_SCHEMA_FILE.read_text()

    contracts_conn = sqlite3.connect(":memory:")
    init_conn = sqlite3.connect(":memory:")
    try:
        contracts_conn.executescript(SCHEMA_FILE.read_text())
        contracts_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        contracts_conn.executescript(QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text())
        contracts_conn.executescript(DOC_TYPE_AND_TITLES_SCHEMA_FILE.read_text())
        contracts_conn.executescript(contracts_sql)
        init_conn.executescript(SCHEMA_FILE.read_text())
        init_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        init_conn.executescript(QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text())
        init_conn.executescript(DOC_TYPE_AND_TITLES_SCHEMA_FILE.read_text())
        init_conn.executescript(author_orgs_sql)

        assert _table_names(contracts_conn) == _table_names(init_conn) == ALL_TABLES
        assert _schema_snapshot(contracts_conn) == _schema_snapshot(init_conn)
    finally:
        contracts_conn.close()
        init_conn.close()


def test_0003_quarantine_diagnostics_matches_data_contracts_schema():
    """Same DDL parity check, for the additive `quarantine_diagnostics` table (T-DOC17
    parse-failure-diagnostics fix). `quarantine_diagnostics` REFERENCES `quarantine`, so
    0001_init.sql must be applied first for the FK-bearing DDL to parse."""
    contracts_sql = _extract_schema_sql_block(
        DATA_CONTRACTS.read_text(), "### quarantine_diagnostics"
    )
    diagnostics_sql = QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text()

    contracts_conn = sqlite3.connect(":memory:")
    init_conn = sqlite3.connect(":memory:")
    try:
        contracts_conn.executescript(SCHEMA_FILE.read_text())
        contracts_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        contracts_conn.executescript(contracts_sql)
        init_conn.executescript(SCHEMA_FILE.read_text())
        init_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        init_conn.executescript(diagnostics_sql)

        assert _table_names(contracts_conn) == _table_names(init_conn) == ALL_TABLES
        assert _schema_snapshot(contracts_conn) == _schema_snapshot(init_conn)
    finally:
        contracts_conn.close()
        init_conn.close()


def test_0006_figures_tables_matches_data_contracts_schema():
    """Same DDL parity check, for the additive `figures`/`tables` tables (RI-18). Like 0002/0003,
    adds new tables (not columns) that REFERENCE `papers`, so 0001_init.sql must be applied first
    for the FK-bearing DDL to parse."""
    contracts_sql = _extract_schema_sql_block(DATA_CONTRACTS.read_text(), "### figures + tables")
    figures_tables_sql = FIGURES_TABLES_SCHEMA_FILE.read_text()

    contracts_conn = sqlite3.connect(":memory:")
    init_conn = sqlite3.connect(":memory:")
    try:
        contracts_conn.executescript(SCHEMA_FILE.read_text())
        contracts_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        contracts_conn.executescript(QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text())
        contracts_conn.executescript(DOC_TYPE_AND_TITLES_SCHEMA_FILE.read_text())
        contracts_conn.executescript(AUTHOR_ORGS_SCHEMA_FILE.read_text())
        contracts_conn.executescript(contracts_sql)
        init_conn.executescript(SCHEMA_FILE.read_text())
        init_conn.executescript(CHECKPOINT_SCHEMA_FILE.read_text())
        init_conn.executescript(QUARANTINE_DIAGNOSTICS_SCHEMA_FILE.read_text())
        init_conn.executescript(DOC_TYPE_AND_TITLES_SCHEMA_FILE.read_text())
        init_conn.executescript(AUTHOR_ORGS_SCHEMA_FILE.read_text())
        init_conn.executescript(figures_tables_sql)

        assert _table_names(contracts_conn) == _table_names(init_conn) == ALL_TABLES_THROUGH_0006
        assert _schema_snapshot(contracts_conn) == _schema_snapshot(init_conn)
    finally:
        contracts_conn.close()
        init_conn.close()
