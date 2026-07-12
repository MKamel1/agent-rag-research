"""M9 IngestionOrchestrator checkpoint contract (DATA-CONTRACTS.md "M9 IngestionOrchestrator —
checkpoint contract"; decision record `.phase0-data/orchestrator-checkpoint-proposal.md`, Option A).

Fixes the T-A2 (PR #38) foundation-level gap: `_prepare`/`_finish` (`rag/orchestrator.py`) need a
resumed run to skip re-invoking Chunker/Summarizer, which means the `parsed`/`chunks`/
`summary_text` stage outputs must be durable across a crash — but `ingest_state`
(`migrations/0001_init.sql`) has only `paper_id`/`stage`/`updated_at`, no artifact storage. Before
this module, the untyped `state.checkpoint(paper_id, stage, **artifacts)` dict was made durable
only by the test-local `FakeIngestState` (`rag/test_orchestrator.py`) — a real crash-and-restart
had nowhere durable to read `artifacts["parsed"]` back from and would raise `KeyError`.

`CheckpointArtifacts` is the typed replacement for that `**artifacts` dict, persisted by the
additive `ingest_checkpoint` table (`migrations/0002_ingest_checkpoint.sql`) as
`artifacts.model_dump_json()` / `CheckpointArtifacts.model_validate_json(...)`.
"""

from contracts._base import FrozenModel
from contracts.chunker import Chunk
from contracts.parser import ParsedDoc


class CheckpointArtifacts(FrozenModel):
    """Per-paper stage output. Every field is `None` until the stage that produces it has run.

    V1's `ClaimExtractor` stage (ARCHITECTURE.md "Extensibility") needs the identical
    checkpoint/resume mechanism -- under this shape that is one more optional field
    (`claims: list[Claim] | None`), no new table, no new migration (decision record §4).
    """

    parsed: ParsedDoc | None = None
    chunks: list[Chunk] | None = None
    summary_text: str | None = None
    relevance_score: float | None = None

    def merge(self, update: "CheckpointArtifacts") -> "CheckpointArtifacts":
        """Overlay `update`'s non-`None` fields onto `self`, keeping every field `update` leaves
        `None` as `self` already had it. This is `state.checkpoint`'s upsert semantics (never a
        blind overwrite -- ARCHITECTURE.md "Operational invariants" §1's "upserts keyed by stable
        id" rule, applied to the artifacts payload instead of just the `stage` column) --
        every `state` adapter (fake and real) shares this one implementation rather than
        reinventing the merge rule.
        """
        changes = {
            name: value
            for name in type(self).model_fields
            if (value := getattr(update, name)) is not None
        }
        return self.model_copy(update=changes) if changes else self


class Checkpoint:
    """The row shape returned by `state.get(paper_id)`: `stage` (the frozen `ingest_state.stage`
    vocabulary the orchestrator's own `_STAGES` enumerates) plus that row's `CheckpointArtifacts`.

    Not a `contracts/` `FrozenModel`: unlike `CheckpointArtifacts` (which crosses the
    fake/real-adapter <-> orchestrator seam as a JSON-serialized payload and so needs
    construction-time validation), `Checkpoint` is only ever built in-process from an already-typed
    `stage: str` and an already-validated `CheckpointArtifacts` -- the same reasoning
    `contracts/document_store.py` gives for not wrapping `DocumentStore`'s own interface in a
    `contracts/` type, just for a `state`-row return value instead of a whole-module interface.
    """

    __slots__ = ("stage", "artifacts")

    def __init__(self, stage: str, artifacts: CheckpointArtifacts):
        self.stage = stage
        self.artifacts = artifacts
