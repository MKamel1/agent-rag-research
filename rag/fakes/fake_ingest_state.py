"""FakeIngestState — the in-memory `state` (`ingest_state` + `ingest_checkpoint` + `quarantine`)
adapter for every zero-GPU test of `IngestionOrchestrator` (T-F4-style committed fake).

Promoted here from the test-local class `rag/test_orchestrator.py` used to define inline (T-A2
checkpoint-durability fix, `.phase0-data/orchestrator-checkpoint-proposal.md` Option A) so every
suite shares one adapter instead of re-declaring it, and so it can be typed against the real
`CheckpointArtifacts` contract instead of an untyped `**artifacts` dict.

Real interface (assumed by `rag/orchestrator.py`; not yet frozen in `contracts/` -- see
`rag/test_orchestrator.py`'s module docstring):

    get(paper_id) -> Checkpoint | None
    checkpoint(paper_id, stage, artifacts=None) -> None   # upsert stage, merge artifacts
    quarantine(paper_id, stage, error) -> None             # dead-letter; row removed

Backed by one plain dict, not sqlite -- this fake stands in for BOTH the `ingest_state` table
(`stage`) and the additive `ingest_checkpoint` table (`artifacts`) at once, keyed by `paper_id`.
`rag/ingest_state_sqlite.py`'s `SqliteIngestState` is the real, schema-backed counterpart that
persists those as two actual tables.
"""

from contracts.ingest_state import Checkpoint, CheckpointArtifacts


class FakeIngestState:
    """`checkpoint`'s merge semantics: a stage transition that doesn't repeat every earlier field
    (e.g. bumping straight from `chunked` to `done` with no `artifacts`) never un-sets what an
    earlier call already recorded — except reaching `done` itself, which clears the row's
    artifacts (ARCHITECTURE.md "Operational invariants" §1 / DATA-CONTRACTS.md
    "ingest_checkpoint": nothing is left to resume once a paper is fully stored and indexed).
    """

    def __init__(self):
        self._rows: dict[str, Checkpoint] = {}
        self.quarantined: dict[str, tuple[str, Exception]] = {}

    def get(self, paper_id: str) -> Checkpoint | None:
        return self._rows.get(paper_id)

    def checkpoint(
        self, paper_id: str, stage: str, artifacts: CheckpointArtifacts | None = None
    ) -> None:
        artifacts = artifacts if artifacts is not None else CheckpointArtifacts()
        if stage == "done":
            self._rows[paper_id] = Checkpoint(stage=stage, artifacts=CheckpointArtifacts())
            return
        existing = self._rows.get(paper_id)
        merged = existing.artifacts.merge(artifacts) if existing else artifacts
        self._rows[paper_id] = Checkpoint(stage=stage, artifacts=merged)

    def quarantine(self, paper_id: str, stage: str, error: Exception) -> None:
        self.quarantined[paper_id] = (stage, error)
        self._rows.pop(paper_id, None)

    def stage_of(self, paper_id: str) -> str | None:
        row = self._rows.get(paper_id)
        return row.stage if row else None
