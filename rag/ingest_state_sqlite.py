"""SqliteIngestState — a real, schema-backed `state` adapter over `ingest_state` +
`ingest_checkpoint` (migrations/0001_init.sql, migrations/0002_ingest_checkpoint.sql).

Not yet wired into any composition root -- that is a separate, not-yet-assigned ticket (V0's two
composition roots are IngestionOrchestrator/M9 and McpServer/M8, ARCHITECTURE.md "Operational
invariants" §3). This module exists to prove, end to end, that the `ingest_checkpoint` migration +
`CheckpointArtifacts` contract (T-A2 checkpoint-durability fix,
`.phase0-data/orchestrator-checkpoint-proposal.md` Option A) actually round-trips through real
SQLite -- see `rag/test_ingest_state_sqlite.py`'s crash-and-restart regression test, which is the
scenario this whole fix is about: a real crash resumes from a *fresh* `SqliteIngestState` instance
(a new process, not a shared Python object) without re-invoking Chunker/Summarizer or re-writing
the source-of-truth record.

Interface: the same three methods `rag/orchestrator.py` composes against
(`rag/fakes/fake_ingest_state.py`'s `FakeIngestState` docstring has the full assumed shape) --
`get`/`checkpoint`/`quarantine` -- plus `stage_of` as a test convenience, mirroring the fake.
"""

import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from contracts.ingest_state import Checkpoint, CheckpointArtifacts

_T = TypeVar("_T")


class SqliteIngestState:
    """Precondition: `db_path` has already had `migrations/migrate.py`'s `migrate()` applied (so
    `ingest_state`/`ingest_checkpoint`/`quarantine` exist) -- this adapter contains no DDL of its
    own (CONVENTIONS §1: schema lives in `migrations/`, never re-declared by an adapter).

    Thread-safety: `IngestionOrchestrator` calls `state.get`/`state.checkpoint` from two threads
    concurrently (its own prefetch pool + the main thread -- see `rag/orchestrator.py`'s module
    docstring, "Cross-thread `state` access"). sqlite3 connections default to
    `check_same_thread=True`, so this adapter opens one connection per call and serializes every
    call behind one `threading.Lock`.
    # ponytail: one process-wide lock serializes ALL calls, not just concurrent writers to the
    # same paper_id -- fine at V0's one-orchestrator-process throughput; move to a connection pool
    # + row-level locking (or WAL busy_timeout tuning) if this ever shows up as a bottleneck.

    Cross-PROCESS safety: this lock is per-instance, so it serializes nothing across two separate
    OS processes -- `checkpoint()`/`quarantine()` are non-atomic read-merge-write/delete
    sequences with no protection against a second process's call interleaving on the same
    paper_id. `get()`/`all_known_paper_ids()` are safe to call from a second process (WAL mode
    lets readers never block on a writer), but a second process must NOT call
    `checkpoint()`/`quarantine()` against a `db_path` a live `IngestionOrchestrator` is also
    writing to -- see `app/prefetch_pdfs.py`'s module docstring point 1 for the concrete failure
    mode this was written to avoid.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()

    def _with_connection(self, fn: Callable[[sqlite3.Connection], _T]) -> _T:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                result = fn(conn)
                conn.commit()
                return result
            finally:
                conn.close()

    def get(self, paper_id: str) -> Checkpoint | None:
        def _get(conn: sqlite3.Connection) -> Checkpoint | None:
            row = conn.execute(
                "SELECT stage FROM ingest_state WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                return None
            artifacts_row = conn.execute(
                "SELECT artifacts_json FROM ingest_checkpoint WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            artifacts = (
                CheckpointArtifacts.model_validate_json(artifacts_row[0])
                if artifacts_row is not None
                else CheckpointArtifacts()
            )
            return Checkpoint(stage=row[0], artifacts=artifacts)

        return self._with_connection(_get)

    def checkpoint(
        self, paper_id: str, stage: str, artifacts: CheckpointArtifacts | None = None
    ) -> None:
        artifacts = artifacts if artifacts is not None else CheckpointArtifacts()

        def _checkpoint(conn: sqlite3.Connection) -> None:
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(paper_id) DO UPDATE SET "
                "stage = excluded.stage, updated_at = excluded.updated_at",
                (paper_id, stage, now),
            )
            if stage == "done":
                # Nothing left to resume once a paper is fully stored and indexed (decision
                # proposal Option A) -- drop the checkpoint row; the ingest_state row stays so a
                # re-run still recognizes this paper as `done`.
                conn.execute("DELETE FROM ingest_checkpoint WHERE paper_id = ?", (paper_id,))
                return
            existing_row = conn.execute(
                "SELECT artifacts_json FROM ingest_checkpoint WHERE paper_id = ?", (paper_id,)
            ).fetchone()
            existing = (
                CheckpointArtifacts.model_validate_json(existing_row[0])
                if existing_row is not None
                else CheckpointArtifacts()
            )
            merged = existing.merge(artifacts)
            conn.execute(
                "INSERT INTO ingest_checkpoint (paper_id, artifacts_json) VALUES (?, ?) "
                "ON CONFLICT(paper_id) DO UPDATE SET artifacts_json = excluded.artifacts_json",
                (paper_id, merged.model_dump_json()),
            )

        self._with_connection(_checkpoint)

    def quarantine(self, paper_id: str, stage: str, error: Exception) -> None:
        def _quarantine(conn: sqlite3.Connection) -> None:
            now = datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, ?, ?, ?)",
                (paper_id, stage, str(error), now),
            )
            conn.execute("DELETE FROM ingest_state WHERE paper_id = ?", (paper_id,))
            conn.execute("DELETE FROM ingest_checkpoint WHERE paper_id = ?", (paper_id,))

        self._with_connection(_quarantine)

    def stage_of(self, paper_id: str) -> str | None:
        checkpoint = self.get(paper_id)
        return checkpoint.stage if checkpoint else None

    def all_known_paper_ids(self) -> set[str]:
        """Every paper_id already tracked in `ingest_state` (any stage) or dead-lettered in
        `quarantine` -- the full "someone has already handled this paper" set, in one query.

        Exists for a bulk startup scan across a whole harvested corpus (e.g.
        `app/prefetch_pdfs.py` deciding which papers still need a PDF download) that would
        otherwise need one `get()` call -- and one connection open -- per paper_id. `get()` stays
        the right tool for `IngestionOrchestrator`'s own per-paper checkpoint cadence; this is for
        the different access pattern of "which of these thousands of ids are already spoken for".
        """

        def _all_ids(conn: sqlite3.Connection) -> set[str]:
            rows = conn.execute(
                "SELECT paper_id FROM ingest_state UNION SELECT paper_id FROM quarantine"
            ).fetchall()
            return {r[0] for r in rows}

        return self._with_connection(_all_ids)
