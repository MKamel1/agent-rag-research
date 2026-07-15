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
    `summarizer.summarize`/`embedder.embed`/`vector_index.upsert` quarantines that one paper and
    the run continues; a `TransientError` from any of those four calls gets a bounded retry
    (`max_retries`, `retry_sleep` -- same shape as `rag/harvester.py`'s `Harvester`) and then
    quarantines if the retry budget is exhausted (T-DOC12/T-DOC13 -- two real end-to-end run
    crashes, first a `parse_phase()` subprocess crash on an unretried reference-extraction
    `TransientError` out of `parser.parse` (T-DOC12, PR #75), then the identical gap found in
    `_finish`/`finish_phase` before it could crash the same way (T-DOC13, PR #76) --
    CONVENTIONS.md §4's "retry with backoff, then quarantine" was simply never wired up for any of
    these four calls). Any other exception propagates out of `ingest()` and stops the run
    (CONVENTIONS.md §4 -- everything else is a bug or an infrastructure failure worth crashing
    loud on).
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
        batch_size_provider: Callable[[], int] | None = None,
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
        # Bounded retry for a `TransientError` from `parser.parse` (T-DOC12), and from
        # `summarizer.summarize`/`embedder.embed`/`vector_index.upsert` (T-DOC13) -- same
        # (`max_retries`, `retry_sleep`) API shape as `rag/harvester.py`'s `Harvester`, so every
        # bounded-retry call site in this codebase reads the same way. `retry_sleep` defaults to
        # real `time.sleep`; tests inject a no-op/recording stand-in.
        #
        # Ownership differs from the other retry sites, though, and deliberately so: both
        # `Harvester` and `app/assembly.py`'s `_PdfDownloadParser` retry entirely *inside* the
        # adapter touching the flaky I/O, so their caller never sees a retryable error at all.
        # Here the retry lives in the Orchestrator instead, because the Orchestrator already owned
        # the quarantine decision for `PermanentError` from all four calls before this change --
        # this just extends that pre-existing, per-call quarantine ownership to `TransientError`
        # too; it is not "the Orchestrator retries its collaborators" as a house style.
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep
        # Model-lifecycle hooks (ARCHITECTURE.md §3): a composition root wires these to evict the
        # GPU-bound model *this* phase doesn't need, so it never has to co-reside with the model
        # the other phase does need. No-op by default -- every fake/test caller that doesn't pass
        # these gets the prior single-process behavior unchanged.
        self._before_parse_phase = before_parse_phase or (lambda: None)
        self._before_finish_phase = before_finish_phase or (lambda: None)
        self._before_embed = before_embed or (lambda: None)
        # T-DOC21: an optional callable returning the next Pass-1 batch size, called once per
        # batch in `parse_phase()` below. `None` (the default) keeps today's exact fixed-size
        # behavior (`config.parse_batch_size` every time) -- every fake/test caller that doesn't
        # pass this is unaffected.
        self._batch_size_provider = batch_size_provider

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
        if the two calls return slightly different sets).

        Deliberately does NOT exclude `paper_id`s already sitting in `quarantine` -- only
        `_harvester`'s own dedup applies. This is intentional, not a gap: `quarantine()` deletes
        the `ingest_state` row for that paper (module docstring above), so to `_prepare`/`_finish`
        a quarantined paper is indistinguishable from one never harvested, and will be retried in
        full on the next `harvest()` call, whether that's a killed-and-resumed run minutes later or
        a fresh run days later. That's the point: the leading real-world cause of a `PermanentError`
        here is arXiv indexing a paper's metadata before its PDF finishes processing (a real,
        observed 404 -- `.phase0-data/100-paper-run-stats.md` "Key learning") -- a condition that
        resolves on arXiv's side over hours/days, not something permanent about the paper. Giving
        every run a fresh shot at every quarantined paper is the correct default so those papers
        aren't lost forever over what was actually a transient upstream state. The cost is bounded
        and cheap: a paper that's still genuinely bad just re-fails `parser.parse`/`summarizer.
        summarize` and re-quarantines -- safe because `SqliteIngestState.quarantine` is idempotent
        (first reason wins, logged, never raises) precisely to make repeated re-attempts of an
        already-quarantined paper harmless. If quarantine volume or repeated-failure cost ever
        becomes a real problem at 15k-paper scale, the fix is a `quarantine`-aware exclusion in
        `harvest()` (e.g. skip a paper_id quarantined within the last N days) -- not yet needed,
        so not built.
        """
        return list(self._harvester.harvest(focus_area, cap, self._config.ordering))

    def parse_phase(self, refs: list[PaperRef]) -> None:
        """Pass 1: drive every ref to (at least) `chunked` using the CPU/MinerU-bound `_prepare`.
        Sequential, not pipelined against Pass 2 -- see module docstring for why.

        Batches `refs` into groups of `config.parse_batch_size` and tries
        `parser.parse_batch()` once per group (T-DOC16, `.phase0-data/
        pass1-gpu-underutilization.md`) -- one batched parser call for the whole group fills the
        GPU-idle gaps a one-document-at-a-time `parser.parse()` loop leaves between a single
        document's own sequential processing stages; see `rag/parser.py`'s module docstring for
        the vendor-specific mechanism. `parser.parse_batch` is whole-batch-fails, by design (same
        docstring) -- a `TransientError`/`PermanentError` from it falls back to today's
        proven-safe per-paper `_prepare`/`_parse_with_retry` path for that group, unchanged. The
        last group of a harvest may be shorter than `parse_batch_size`; that's handled naturally
        by slicing, not a special case.

        Also slices out the *next* group (`next_batch`, `[]` past the end of `refs`) and hands it
        to `_prepare_batch` alongside the current one (T-DOC18 Layer 2) purely so a parser that
        implements the optional `prefetch_next_batch` hook (`app/assembly.py`'s
        `_PdfDownloadParser`) can start resolving next group's PDF bytes in the background while
        the current group's `parse_batch()` call is blocked on the GPU -- this loop still calls
        `_prepare_batch` once per group, strictly in order; nothing here runs off the main thread.

        Batch size is `config.parse_batch_size` (fixed) unless a `batch_size_provider` was
        injected (T-DOC21, `.claude/plans/giggly-tumbling-globe.md` "Adaptive Pass-1 batch
        sizing") -- when present, it's called once per group instead, letting a composition root
        grow/shrink batches to real, currently-free VRAM instead of one static number. Batch
        boundaries aren't fixed-stride when this is active, so the loop tracks its own running
        index rather than using `range(0, len(refs), batch_size)`. The `next_batch` lookahead
        guess is computed by calling the provider a *second* time -- by construction this may
        differ from what the batch after next actually ends up using once its own turn comes (real
        composition is decided when the `while` loop actually gets there, not at prefetch-guess
        time). Not a bug: `_prepare_batch`'s prefetch match is exact-ref-tuple equality, so a
        size-mismatched guess is simply a wasted prefetch for that one group, falling through to a
        fresh, correctness-safe download -- never broken, just occasionally not sped up.
        """
        self._before_parse_phase()
        i = 0
        while i < len(refs):
            # Called exactly ONCE per real batch, not twice (review finding, T-DOC21): the
            # injected provider (`AdaptiveBatchSizer.next_size`) is a *stateful* bound method --
            # every call both reads a live VRAM probe and mutates its own internal size, so a
            # second "just for the lookahead guess" call silently doubles the real growth/shrink
            # rate per iteration, not a free/idempotent peek. The same `size` value is reused for
            # both this batch's slice and the next-batch lookahead guess -- exactly what the
            # pre-T-DOC21 fixed-stride code already did with one `batch_size` value for both.
            size = self._batch_size_provider() if self._batch_size_provider else self._config.parse_batch_size
            batch = refs[i : i + size]
            next_batch = refs[i + size : i + 2 * size]
            self._prepare_batch(batch, next_batch)
            i += size

    def _prepare_batch(self, batch: list[PaperRef], next_batch: list[PaperRef] | None = None) -> None:
        """One `parse_phase` group. Only refs that haven't reached `parsed` yet (a fresh paper, or
        one that crashed before checkpointing `parsed` on a prior run) need an actual parser call
        -- refs already at `parsed` or further along are left entirely to `_prepare`'s own
        pre-existing resume logic below, same as before this method existed.

        `parser.parse_batch` is duck-typed optional (`getattr(..., None)`, not a hard interface
        requirement): the real composition-root parser (`app/assembly.py`'s `_PdfDownloadParser`)
        implements it, but a collaborator that doesn't (this suite's pre-existing `SpyParser`,
        which predates T-DOC16 and covers unrelated per-paper fault-injection scenarios) falls
        straight through to the unchanged per-ref `_prepare` loop below -- exactly today's
        behavior, not a new failure mode. `parser.prefetch_next_batch` (T-DOC18 Layer 2) is
        optional the same way, for the same reason: called, if present, with `next_batch`'s
        not-yet-parsed refs right before `parse_batch()`, so a parser that supports it can start
        resolving them in the background while this call's `parse_batch()` blocks on the GPU; a
        parser without it (or a `next_batch` that's empty -- e.g. the last group) is simply
        skipped, same behavior as today.

        On a successful `parser.parse_batch()`, each fresh ref's `ParsedDoc` is checkpointed at
        `parsed` right here, then EVERY ref in the group (fresh and already-resumed alike) is
        routed through `_prepare`, which finds `parsed` already satisfied for the ones just
        checkpointed and proceeds straight to chunking -- so the chunk/checkpoint step this method
        does not change (T-DOC16 scope) never duplicates.

        On `TransientError`/`PermanentError` from `parser.parse_batch()`, no ref in the group was
        checkpointed (the batch call raises before ever returning ANY `ParsedDoc` -- `rag/
        parser.py`'s whole-batch-fails contract), so falling back to `_prepare` for every ref in
        the group is safe and correct: each one re-attempts its own parse via the existing,
        unchanged `_parse_with_retry` path.
        """
        needs_parse = [
            ref for ref in batch if not _at_least(self._stage(ref.paper_id), "parsed")
        ]
        parse_batch_fn = getattr(self._parser, "parse_batch", None)
        if needs_parse and parse_batch_fn is not None:
            prefetch_fn = getattr(self._parser, "prefetch_next_batch", None)
            if prefetch_fn is not None and next_batch:
                next_needs_parse = [
                    ref for ref in next_batch if not _at_least(self._stage(ref.paper_id), "parsed")
                ]
                if next_needs_parse:
                    prefetch_fn(next_needs_parse)
            try:
                parsed_docs = parse_batch_fn(needs_parse)
            except (TransientError, PermanentError):
                parsed_docs = None
            if parsed_docs is not None:
                for ref, parsed in zip(needs_parse, parsed_docs, strict=True):
                    self._state.checkpoint(
                        ref.paper_id, "parsed", artifacts=CheckpointArtifacts(parsed=parsed)
                    )
        for ref in batch:
            self._prepare(ref)

    def _stage(self, paper_id: str) -> str | None:
        checkpoint = self._state.get(paper_id)
        return checkpoint.stage if checkpoint else None

    def finish_phase(self, refs: list[PaperRef]) -> None:
        """Pass 2: drive every ref from wherever it sits to `done` using the GPU-bound `_finish`.
        Resumes purely from durable `state`/`CheckpointArtifacts` -- nothing from Pass 1 is held
        in memory across the phase boundary (matters at 15k-paper scale)."""
        # Hoisted exactly once per run, before the per-paper loop -- ARCHITECTURE.md §M9. The
        # query string never changes across papers in a run, so embedding it inside the loop
        # below would call embed() on a constant value once per paper for no reason.
        #
        # Bounded-retried (T-DOC13, review finding) but never quarantined -- unlike every other
        # embed() call in this class, this one isn't about any one paper, so there is no paper_id
        # to quarantine. A `TransientError` gets the same backoff as the per-paper calls; once the
        # budget is exhausted this re-raises and crashes the run loud, same as the pre-existing
        # behavior for this call (CONVENTIONS.md §4 -- this is the correct outcome for an
        # infrastructure failure with no single paper to blame, not a regression from adding the
        # retry).
        topic_query_vec = self._embed_topic_query_vec_with_retry()
        self._before_finish_phase()
        for ref in refs:
            self._finish_checkpoint(ref, topic_query_vec)

    def _embed_topic_query_vec_with_retry(self) -> list[float]:
        text = " ".join(self._config.focus_area_queries)
        attempt = 0
        while True:
            try:
                return self._embedder.embed([text])[0]
            except TransientError:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                self._retry_sleep(self._backoff(attempt))

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
        # Same exponential curve (1s, 2s, 4s, ...) as `rag/harvester.py`'s `Harvester._backoff`,
        # shared by every bounded-retry call site in this class (`_parse_with_retry` T-DOC12,
        # PR #75; `_summarize_with_retry`/`_embed_with_retry`/`_upsert_with_retry` T-DOC13,
        # PR #76) -- not shared code across files (one line; a shared helper would be more
        # machinery than the duplication it removes), just the same documented shape
        # (CONVENTIONS.md §4).
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
            #
            # Quarantining out of THIS branch (T-DOC13, if `_embed_with_retry`/
            # `_upsert_with_retry` exhaust their budget) is still safe even though
            # `document_store.put` already ran for this paper_id in a prior run:
            # `DocumentStore.put` is an upsert (`ON CONFLICT paper_id DO UPDATE`,
            # rag/document_store.py), so a later full re-ingest of a quarantined paper_id
            # safely overwrites this record rather than duplicating or orphaning it.
            record = self._document_store.get(paper_id)
            self._before_embed()
            embedded = self._embed_with_retry(
                paper_id, [record.summary_text] + [c.text for c in record.chunks]
            )
            if embedded is None:
                return  # quarantined inside _embed_with_retry
            summary_vec, *chunk_vecs = embedded
            if not self._upsert_with_retry(paper_id, record, summary_vec, chunk_vecs):
                return  # quarantined inside _upsert_with_retry
            self._state.checkpoint(paper_id, "done")
            return

        parsed = prepared.parsed if prepared.parsed is not None else artifacts.parsed
        chunks = prepared.chunks if prepared.chunks is not None else artifacts.chunks

        if _at_least(stage, "summarized"):
            summary_text = artifacts.summary_text
        else:
            summary_text = self._summarize_with_retry(paper_id, parsed)
            if summary_text is None:
                return  # quarantined inside _summarize_with_retry
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
        embedded = self._embed_with_retry(paper_id, [summary_text] + [c.text for c in chunks])
        if embedded is None:
            return  # quarantined inside _embed_with_retry
        summary_vec, *chunk_vecs = embedded
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

        if not self._upsert_with_retry(paper_id, record, summary_vec, chunk_vecs):
            return  # quarantined inside _upsert_with_retry
        self._state.checkpoint(paper_id, "done")

    def _summarize_with_retry(self, paper_id: str, parsed: ParsedDoc) -> str | None:
        """The per-paper error boundary `summarizer.summarize` needs (T-DOC13 -- the `_finish`
        analog of T-DOC12/PR #75's `_parse_with_retry`): a `TransientError` here has the identical
        crash shape the reference-extraction adapter's `TransientError` had in `parse_phase()` before T-DOC12 -- uncaught,
        it propagates out of `ingest()` and kills the whole `finish_phase()` subprocess, losing
        progress for every paper still queued behind it. `PermanentError` was already quarantined
        correctly here (unchanged); `TransientError` now gets the same `max_retries`-bounded,
        backed-off retry then quarantine. Returns `None` (already quarantined) on either exhausted
        `TransientError` or `PermanentError`, same two-outcome shape as `_parse_with_retry`.
        """
        attempt = 0
        while True:
            try:
                return self._summarizer.summarize(parsed)
            except PermanentError as error:
                self._state.quarantine(paper_id, "summarized", error)
                return None
            except TransientError as error:
                attempt += 1
                if attempt > self._max_retries:
                    self._state.quarantine(paper_id, "summarized", error)
                    return None
                self._retry_sleep(self._backoff(attempt))

    def _embed_with_retry(self, paper_id: str, texts: list[str]) -> list[list[float]] | None:
        """Same shape as `_summarize_with_retry`, for either of `_finish`'s two `embedder.embed`
        call sites (T-DOC13) -- previously unguarded against *both* error types (not even
        `PermanentError`), unlike `summarizer.summarize`/`parser.parse`. Quarantines at stage
        "embedded" regardless of which of the two call sites failed: the resume-path call is
        re-deriving the same "embedded" stage output the main-path call produces, just later.
        """
        attempt = 0
        while True:
            try:
                return self._embedder.embed(texts)
            except PermanentError as error:
                self._state.quarantine(paper_id, "embedded", error)
                return None
            except TransientError as error:
                attempt += 1
                if attempt > self._max_retries:
                    self._state.quarantine(paper_id, "embedded", error)
                    return None
                self._retry_sleep(self._backoff(attempt))

    def _upsert_with_retry(
        self,
        paper_id: str,
        record: PaperRecord,
        summary_vec: list[float],
        chunk_vecs: list[list[float]],
    ) -> bool:
        """Guards `_upsert_record`'s `vector_index.upsert` calls (T-DOC13) -- found while auditing
        `_finish` for the same bug class beyond what the ticket named: `rag/vector_index.py`'s
        adapter classifies every vector-store failure as `TransientError` and never `PermanentError`
        (there is no "this vector is bad" case, only "the vector store is unreachable right now"), so only
        `TransientError` needs handling here -- unlike the other three T-DOC12/T-DOC13 call sites.
        Retries the whole per-paper batch (summary + every chunk), not just the one call that
        raised: `VectorIndex.upsert` is idempotent by id (a real vector-store upsert), so re-upserting a
        point that already landed on an earlier attempt is a no-op in effect, not a duplicate.
        Returns `True` on success, `False` (already quarantined) on an exhausted retry budget.
        `chunk_vecs` is a concrete `list`, not the more permissive `Iterable` `_upsert_record`
        itself accepts (review finding): a retry re-iterates it via `_upsert_record`'s internal
        `zip(..., strict=True)` on every attempt, which a one-shot iterator would silently break
        on the second attempt onward.
        """
        attempt = 0
        while True:
            try:
                self._upsert_record(record, summary_vec, chunk_vecs)
                return True
            except TransientError as error:
                attempt += 1
                if attempt > self._max_retries:
                    self._state.quarantine(paper_id, "done", error)
                    return False
                self._retry_sleep(self._backoff(attempt))

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
