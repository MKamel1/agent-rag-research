"""M9 IngestionOrchestrator (ARCHITECTURE.md "M9 · IngestionOrchestrator", owner A).

`IngestionOrchestrator.ingest(focus_area, cap)` wires harvest -> parse -> {chunk, summarize} ->
embed -> compute relevance_score -> store (put) -> index (upsert), one paper at a time, resuming
from the injected `state` checkpoint store wherever a prior run left off (CONVENTIONS.md §5's
idempotency pattern: read the row before doing a stage's work, upsert it after).

Pipelining (ARCHITECTURE.md "Operational invariants" §3 / CONVENTIONS.md §6): CPU-bound work
(parse/chunk) for paper N+1 runs on a one-deep background prefetch while GPU-bound work
(summarize/embed) for paper N is in flight on the main thread, so the GPU-bound-call queue
doesn't sit idle waiting on CPU stages. This orchestrator acquires the injected `GpuLock` around
no work of its own -- the stage adapters (Summarizer/Embedder) acquire it themselves around their
own inference calls; the Orchestrator only wires the same `GpuLock` instance through (accepted as
a constructor argument, stored, never `.acquire()`d here).

Cross-thread `state` access (decision proposal `.phase0-data/orchestrator-checkpoint-proposal.md`
§5): `_prepare` (the prefetch-pool thread) and `_finish` (the main thread) both call
`state.get`/`state.checkpoint` concurrently for adjacent papers. The injected `state` MUST be safe
to call from two threads at once -- this is a precondition on every `state` adapter, not something
this orchestrator serializes itself. A real sqlite3-backed adapter needs its own locking or a
connection-per-call (sqlite3 connections default to `check_same_thread=True`); see
`rag/ingest_state_sqlite.py` for one such adapter.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.errors import ContractError, PermanentError
from contracts.harvester import PaperRef
from contracts.ingest_state import CheckpointArtifacts
from contracts.parser import ParsedDoc

# The `ingest_state.stage` vocabulary, in progress order (DATA-CONTRACTS.md, migrations/0001).
# `failed` is deliberately NOT a member: a parse/summarize `PermanentError` moves a paper straight
# to `quarantine`, whose row removes any `ingest_state`/`ingest_checkpoint` row for that paper (see
# `FakeIngestState.quarantine`) -- so `state.get()` never legitimately returns that value.
# ARCHITECTURE.md "Operational invariants" §1 previously listed "+ failed" here too; that wording
# was the stale half of this inconsistency and has been corrected to match this list.
_STAGES = ("harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done")


def _at_least(stage: str | None, target: str) -> bool:
    """Has a checkpoint's `stage` already reached (or passed) `target`?

    Raises `ContractError` (not a raw `ValueError`) naming the offending value if `stage` is ever
    outside `_STAGES` -- a violation of the frozen `ingest_state.stage` vocabulary is a bug
    (CONVENTIONS.md §4: crash loud and legible, not an opaque index-lookup error).
    """
    if stage is None:
        return False
    try:
        return _STAGES.index(stage) >= _STAGES.index(target)
    except ValueError as error:
        raise ContractError(
            f"ingest_state stage {stage!r} is not one of the frozen vocabulary {_STAGES}"
        ) from error


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass
class _Prepared:
    """The CPU-bound prep output for one paper -- what the background prefetch hands to the
    main-thread GPU-bound finish step. `parsed`/`chunks` are `None` only when nothing needed
    re-deriving (paper already checkpointed past `chunked`); `_finish` never reads them in that
    case (it re-derives what it needs from `document_store`/`state` artifacts instead).
    """

    ref: PaperRef
    parsed: ParsedDoc | None
    chunks: list[Chunk] | None


class IngestionOrchestrator:
    """Preconditions: every injected collaborator satisfies its documented interface
    (ARCHITECTURE.md M1-M6); `state` persists `ingest_state`/`ingest_checkpoint`-shaped
    checkpoints keyed by `paper_id` (`get`/`checkpoint`/`quarantine`, see
    `rag/fakes/fake_ingest_state.py`'s `FakeIngestState` for the exact shape this suite commits,
    and `contracts/ingest_state.py` for the typed `CheckpointArtifacts` payload), and MUST be safe
    to call from two threads concurrently (see module docstring, "Cross-thread `state` access").
    Postconditions: `ingest()` is idempotent (a fully-`done` corpus re-run touches no stage) and
    resumable at every stage boundary; a `PermanentError` from `parser.parse`/
    `summarizer.summarize` quarantines that one paper and the run continues; any other exception
    propagates out of `ingest()` and stops the run (CONVENTIONS.md §4 -- only `PermanentError` is
    "this paper is bad", everything else is a bug or an infrastructure failure worth crashing loud
    on).
    """

    def __init__(
        self,
        harvester,
        parser,
        chunker,
        summarizer,
        embedder,
        document_store,
        vector_index,
        state,
        gpu_lock,
        config: Config,
    ):
        self._harvester = harvester
        self._parser = parser
        self._chunker = chunker
        self._summarizer = summarizer
        self._embedder = embedder
        self._document_store = document_store
        self._vector_index = vector_index
        self._state = state
        self._gpu_lock = gpu_lock  # wired through to the composition root; never acquired here.
        self._config = config

    def ingest(self, focus_area: list[str], cap: int) -> None:
        # Hoisted exactly once per run, before the per-paper loop -- ARCHITECTURE.md §M9. The
        # query string never changes across papers in a run, so embedding it inside the loop
        # below would call embed() on a constant value once per paper for no reason.
        topic_query_vec = self._embedder.embed([" ".join(self._config.focus_area_queries)])[0]

        refs = list(self._harvester.harvest(focus_area, cap, self._config.ordering))
        if not refs:
            return

        # One-deep prefetch: while the main thread runs GPU-bound `_finish` for paper i, the pool
        # thread runs CPU-bound `_prepare` for paper i+1, so paper i+1's GPU stage never has to
        # wait on its own parse/chunk once we reach it (ARCHITECTURE "Operational invariants" §3).
        with ThreadPoolExecutor(max_workers=1) as pool:
            prep_future = pool.submit(self._prepare, refs[0])
            for i, ref in enumerate(refs):
                this_future = prep_future
                prep_future = (
                    pool.submit(self._prepare, refs[i + 1]) if i + 1 < len(refs) else None
                )
                prepared = this_future.result()
                if prepared is None:
                    continue  # quarantined during prep, or already `done` -- nothing to finish
                self._finish(prepared, topic_query_vec)

    # -- CPU-bound: harvest (already done)/parse/chunk -----------------------------------------

    def _prepare(self, ref: PaperRef) -> _Prepared | None:
        paper_id = ref.paper_id
        checkpoint = self._state.get(paper_id)
        stage = checkpoint.stage if checkpoint else None
        artifacts = checkpoint.artifacts if checkpoint else CheckpointArtifacts()

        if stage == "done":
            return None
        if _at_least(stage, "chunked"):
            # Already parsed+chunked (or further along) in a prior run -- `_finish` re-derives
            # whatever it needs from `state`/`document_store`; no need to hand it real artifacts.
            return _Prepared(ref=ref, parsed=None, chunks=None)

        if _at_least(stage, "parsed"):
            parsed = artifacts.parsed
        else:
            try:
                parsed = self._parser.parse(ref)
            except PermanentError as error:
                self._state.quarantine(paper_id, "parsed", error)
                return None
            self._state.checkpoint(
                paper_id, "parsed", artifacts=CheckpointArtifacts(parsed=parsed)
            )

        chunks = self._chunker.chunk(parsed)
        self._state.checkpoint(
            paper_id, "chunked", artifacts=CheckpointArtifacts(parsed=parsed, chunks=chunks)
        )
        return _Prepared(ref=ref, parsed=parsed, chunks=chunks)

    # -- GPU-bound: summarize/embed, then store (put) and index (upsert) -----------------------

    def _finish(self, prepared: _Prepared, topic_query_vec: list[float]) -> None:
        ref = prepared.ref
        paper_id = ref.paper_id
        checkpoint = self._state.get(paper_id)
        stage = checkpoint.stage if checkpoint else None
        artifacts = checkpoint.artifacts if checkpoint else CheckpointArtifacts()

        if _at_least(stage, "stored"):
            # Resume across the stored->done gap (ARCHITECTURE "Operational invariants" §1):
            # source of truth already written; only the derived index is missing. Re-embedding is
            # a documented, accepted V0 cost of this rare resume path -- Embedder is deterministic
            # per (text, model, version) (ARCHITECTURE M4), so it reproduces the same vectors.
            record = self._document_store.get(paper_id)
            summary_vec, *chunk_vecs = self._embedder.embed(
                [record.summary_text] + [c.text for c in record.chunks]
            )
            self._upsert_record(record, summary_vec, chunk_vecs)
            self._state.checkpoint(paper_id, "done")
            return

        parsed = prepared.parsed if prepared.parsed is not None else artifacts.parsed
        chunks = prepared.chunks if prepared.chunks is not None else artifacts.chunks

        if _at_least(stage, "summarized"):
            summary_text = artifacts.summary_text
        else:
            try:
                summary_text = self._summarizer.summarize(parsed)
            except PermanentError as error:
                self._state.quarantine(paper_id, "summarized", error)
                return
            self._state.checkpoint(
                paper_id,
                "summarized",
                artifacts=CheckpointArtifacts(
                    parsed=parsed, chunks=chunks, summary_text=summary_text
                ),
            )

        # One batched embed() call per paper (summary + every chunk together) -- not two separate
        # calls -- so the per-paper embed cost stays at exactly one call (the `topic_query_vec`
        # hoist above is the only other embed() call in a run, giving the N+1 total ARCHITECTURE
        # requires, never 2N).
        summary_vec, *chunk_vecs = self._embedder.embed(
            [summary_text] + [c.text for c in chunks]
        )
        relevance_score = _cosine(summary_vec, topic_query_vec)
        self._state.checkpoint(
            paper_id,
            "embedded",
            artifacts=CheckpointArtifacts(
                parsed=parsed,
                chunks=chunks,
                summary_text=summary_text,
                relevance_score=relevance_score,
            ),
        )

        record = PaperRecord(
            ref=ref,
            parsed=parsed,
            chunks=chunks,
            summary_text=summary_text,
            summary_id=f"{paper_id}:summary",
            relevance_score=relevance_score,
        )
        self._document_store.put(record)  # source of truth, written before the derived index
        self._state.checkpoint(paper_id, "stored")

        self._upsert_record(record, summary_vec, chunk_vecs)
        self._state.checkpoint(paper_id, "done")

    def _upsert_record(
        self, record: PaperRecord, summary_vec: list[float], chunk_vecs: Iterable[list[float]]
    ) -> None:
        payload_common = {
            "paper_id": record.ref.paper_id,
            "categories": record.ref.categories,
            "published": record.ref.published.isoformat(),
            "embedding_version": self._embedder.info.version,
        }
        self._vector_index.upsert(
            record.summary_id,
            summary_vec,
            {**payload_common, "kind": "summary", "section_path": ""},
        )
        for chunk, vector in zip(record.chunks, chunk_vecs, strict=True):
            self._vector_index.upsert(
                chunk.chunk_id,
                vector,
                {**payload_common, "kind": "chunk", "section_path": chunk.section_path},
            )
