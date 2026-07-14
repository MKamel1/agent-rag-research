"""M9 IngestionOrchestrator (ARCHITECTURE.md "M9 · IngestionOrchestrator", owner A).

`IngestionOrchestrator.ingest(focus_area, cap)` wires harvest -> parse -> {chunk, summarize} ->
embed -> compute relevance_score -> store (put) -> index (upsert), resuming from the injected
`state` checkpoint store wherever a prior run left off (CONVENTIONS.md §5's idempotency pattern:
read the row before doing a stage's work, upsert it after).

Two passes, not per-paper pipelining (ARCHITECTURE.md "Operational invariants" §3 -- corrected):
`parse_phase()` drives every paper to `chunked` (MinerU, GPU-bound); `finish_phase()` then drives
every paper from wherever it sits to `done` (Summarizer+Embedder, also GPU-bound). This project's
own real-adapter VRAM measurements showed MinerU and the Summarizer together don't fit this
project's GPU budget, so the two GPU-bound stages must never run in the same window -- an earlier
per-paper-pipelined design (CPU prep for paper N+1 overlapping GPU finish for paper N) was
correctness-neutral but memory-unsafe once the corpus needed both models loaded during overlap.
The two-pass split is not a performance regression; it is the fix for a real, reproduced CUDA OOM.
`before_parse_phase`/`before_finish_phase` (constructor args, both default no-op) are hooks for a
composition root to evict the model the *other* phase doesn't need -- see `app/assembly.py`. A
third, finer-grained hook, `before_embed` (also default no-op), fires per-paper, right before each
of `_finish`'s two `embedder.embed()` calls -- found necessary 2026-07-13 by a real end-to-end run:
even *within* Pass 2, the Summarizer sits fully GPU-resident (its own real VRAM use, e.g. ~11.5GB
for a long paper) for the entire time the Embedder is working, though nothing needs it loaded
during that window -- on a real long paper this left too little headroom and the Embedder hit a
real CUDA OOM. `app/assembly.py` wires `before_embed=summarizer.unload` (the same `unload()` used
for the Pass-1 boundary) -- real reload cost measured at ~2.5s, negligible against a real per-paper
summarize call (~15-20s). See `.phase0-data/known-issue-pass2-oom.md`'s 2026-07-13 entries for the
full real-measurement trail (why batch size and individual chunk length were ruled out first).

This orchestrator acquires the injected `GpuLock` around no work of its own -- the stage adapters
(Summarizer/Embedder) acquire it themselves around their own inference calls; the Orchestrator
only wires the same `GpuLock` instance through (accepted as a constructor argument, stored, never
`.acquire()`d here).

`state` access: `_prepare`/`_finish` each call `state.get`/`state.checkpoint` for one paper at a
time, sequentially within their own phase (no cross-thread concurrency anymore -- the prior
one-deep prefetch thread is gone along with the per-paper interleaving it existed for).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.errors import ContractError, PermanentError, TransientError
from contracts.harvester import PaperRef
from contracts.ingest_state import CheckpointArtifacts
from contracts.parser import ParsedDoc

RetrySleep = Callable[[float], None]


def _default_retry_sleep(seconds: float) -> None:
    time.sleep(seconds)

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
    `summarizer.summarize` quarantines that one paper and the run continues; a `TransientError`
    from `parser.parse` gets a bounded retry (`max_retries`, `retry_sleep` -- same shape as
    `rag/harvester.py`'s `Harvester`) and then quarantines if the retry budget is exhausted
    (T-DOC12 -- a real end-to-end run crashed the whole `parse_phase()` subprocess on an
    unretried reference-extraction `TransientError` propagating out of `parser.parse`, CONVENTIONS.md §4's
    "retry with backoff, then quarantine" was simply never wired up for this call). Any other
    exception propagates out of `ingest()` and stops the run (CONVENTIONS.md §4 -- everything
    else is a bug or an infrastructure failure worth crashing loud on).
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
        *,
        before_parse_phase=None,
        before_finish_phase=None,
        before_embed=None,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
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
        # Bounded retry for a `TransientError` from `parser.parse` (T-DOC12) -- same
        # (`max_retries`, `retry_sleep`) API shape as `rag/harvester.py`'s `Harvester`, so the
        # bounded-retry call sites in this codebase read the same way. `retry_sleep` defaults to
        # real `time.sleep`; tests inject a no-op/recording stand-in.
        #
        # Ownership differs from the other two retry sites, though, and deliberately so: both
        # `Harvester` and `app/assembly.py`'s `_PdfDownloadParser` retry entirely *inside* the
        # adapter touching the flaky I/O, so their caller never sees a retryable error at all.
        # Here the retry lives in the Orchestrator instead, because the Orchestrator already owned
        # the quarantine decision for `parser`'s `PermanentError` before this change (see
        # `_parse_with_retry` below) -- this just extends that pre-existing, parser-specific
        # ownership to `TransientError` too; it is not "the Orchestrator retries its collaborators"
        # as a house style. A future fix for `_finish`'s identical gap around
        # `summarizer`/`embedder` should re-derive its own seam, not copy this one by default.
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        # Model-lifecycle hooks (ARCHITECTURE.md §3): a composition root wires these to evict the
        # GPU-bound model *this* phase doesn't need, so it never has to co-reside with the model
        # the other phase does need. No-op by default -- every fake/test caller that doesn't pass
        # these gets the prior single-process behavior unchanged.
        self._before_parse_phase = before_parse_phase or (lambda: None)
        self._before_finish_phase = before_finish_phase or (lambda: None)
        self._before_embed = before_embed or (lambda: None)

    def ingest(self, focus_area: list[str], cap: int) -> None:
        refs = self.harvest(focus_area, cap)
        if not refs:
            return
        self.parse_phase(refs)
        self.finish_phase(refs)

    def harvest(self, focus_area: list[str], cap: int) -> list[PaperRef]:
        """Public so a two-process caller (`app/parse_phase.py`/`app/ingest.py`) can harvest once
        per process without reaching into `_harvester` directly -- each process re-harvests its
        own `refs` rather than one process handing a list to the other (cheap relative to a
        multi-day parse phase; `_finish_checkpoint`'s `state` guard makes re-harvesting safe even
        if the two calls return slightly different sets)."""
        return list(self._harvester.harvest(focus_area, cap, self._config.ordering))

    def parse_phase(self, refs: list[PaperRef]) -> None:
        """Pass 1: drive every ref to (at least) `chunked` using the CPU/MinerU-bound `_prepare`.
        Sequential, not pipelined against Pass 2 -- see module docstring for why."""
        self._before_parse_phase()
        for ref in refs:
            self._prepare(ref)

    def finish_phase(self, refs: list[PaperRef]) -> None:
        """Pass 2: drive every ref from wherever it sits to `done` using the GPU-bound `_finish`.
        Resumes purely from durable `state`/`CheckpointArtifacts` -- nothing from Pass 1 is held
        in memory across the phase boundary (matters at 15k-paper scale)."""
        # Hoisted exactly once per run, before the per-paper loop -- ARCHITECTURE.md §M9. The
        # query string never changes across papers in a run, so embedding it inside the loop
        # below would call embed() on a constant value once per paper for no reason.
        topic_query_vec = self._embedder.embed([" ".join(self._config.focus_area_queries)])[0]
        self._before_finish_phase()
        for ref in refs:
            self._finish_checkpoint(ref, topic_query_vec)

    def _finish_checkpoint(self, ref: PaperRef, topic_query_vec: list[float]) -> None:
        """Guard `_finish` needs that the old inline loop got for free from `_prepare`'s return
        value: skip a ref that Pass 1 quarantined (no `state` row at all) or that's already
        `done` (idempotent re-run) -- `_finish` has no `parsed`/`chunks` to work with for either
        and was never meant to be called on them."""
        checkpoint = self._state.get(ref.paper_id)
        if checkpoint is None or checkpoint.stage == "done":
            return
        self._finish(_Prepared(ref=ref, parsed=None, chunks=None), topic_query_vec)

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
            parsed = self._parse_with_retry(ref)
            if parsed is None:
                return None  # quarantined inside _parse_with_retry
            self._state.checkpoint(
                paper_id, "parsed", artifacts=CheckpointArtifacts(parsed=parsed)
            )

        chunks = self._chunker.chunk(parsed)
        self._state.checkpoint(
            paper_id, "chunked", artifacts=CheckpointArtifacts(parsed=parsed, chunks=chunks)
        )
        return _Prepared(ref=ref, parsed=parsed, chunks=chunks)

    def _parse_with_retry(self, ref: PaperRef) -> ParsedDoc | None:
        """The per-paper error boundary `parser.parse` needs (T-DOC12): a real end-to-end run
        crashed the whole `parse_phase()` subprocess when one paper's reference-extraction
        call raised `TransientError` -- correctly classified by `rag/parser.py`, but nothing
        between there and here retried or quarantined it, so it propagated out of `ingest()` and
        killed every paper still queued behind it. `PermanentError` was already quarantined
        correctly (this is the pre-existing behavior, unchanged); `TransientError` gets the
        `max_retries`-bounded, backed-off retry CONVENTIONS.md §4 documents for it, then
        quarantines once the budget is exhausted -- same two-outcome shape as
        `rag/harvester.py`'s `Harvester.harvest()`. Returns `None` (and has already quarantined)
        on either exhausted `TransientError` or `PermanentError`; `_prepare` treats both the same
        way its call site already did before this method existed.
        """
        paper_id = ref.paper_id
        attempt = 0
        while True:
            try:
                return self._parser.parse(ref)
            except PermanentError as error:
                self._state.quarantine(paper_id, "parsed", error)
                return None
            except TransientError as error:
                attempt += 1
                if attempt > self._max_retries:
                    self._state.quarantine(paper_id, "parsed", error)
                    return None
                self._retry_sleep(self._backoff(attempt))

    @staticmethod
    def _backoff(attempt: int) -> float:
        # Same exponential curve (1s, 2s, 4s, ...) as `rag/harvester.py`'s `Harvester._backoff` --
        # not shared code (one line, two call sites; a shared helper would be more machinery than
        # the duplication it removes), just the same documented shape (CONVENTIONS.md §4).
        return float(2 ** (attempt - 1))

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
            self._before_embed()
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
        self._before_embed()
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
            {**payload_common, "kind": "summary", "section_path": "", "text": record.summary_text},
        )
        for chunk, vector in zip(record.chunks, chunk_vecs, strict=True):
            self._vector_index.upsert(
                chunk.chunk_id,
                vector,
                {
                    **payload_common,
                    "kind": "chunk",
                    "section_path": chunk.section_path,
                    "text": chunk.text,
                },
            )
