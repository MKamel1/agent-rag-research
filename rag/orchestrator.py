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

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.errors import ContractError, PermanentError
from contracts.harvester import PaperRef
from contracts.ingest_state import CheckpointArtifacts
from contracts.parser import ParsedDoc

logger = logging.getLogger(__name__)

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
    `summarizer.summarize` quarantines that one paper and the run continues. Any OTHER exception
    for one paper (a bug, or an infrastructure failure CONVENTIONS.md §4 would otherwise say
    should crash the run loud) is also quarantined and the run continues -- `parse_phase`/
    `finish_phase`'s `_guard_per_paper` safety net (see its own comment block, above
    `_guard_per_paper`'s definition, for the full reasoning) -- UNLESS `_MAX_CONSECUTIVE_
    UNEXPECTED_FAILURES` such failures happen back-to-back within one phase, which re-raises and
    does stop the run: real per-paper flakiness and a real systemic fault (disk full, GPU driver
    crashed) look identical from inside one paper's try/except, and only a run of consecutive
    failures tells them apart.
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

        Wrapped in the per-paper safety net (`_guard_per_paper`, class docstring "Unexpected-
        exception safety net") -- an unanticipated bug in `_prepare` for one paper must not stop
        every other paper still queued behind it.
        """
        self._before_parse_phase()
        consecutive_unexpected_failures = 0
        for ref in refs:
            consecutive_unexpected_failures = self._guard_per_paper(
                ref.paper_id, "parse_phase", consecutive_unexpected_failures,
                lambda ref=ref: self._prepare(ref),
            )

    def finish_phase(self, refs: list[PaperRef]) -> None:
        """Pass 2: drive every ref from wherever it sits to `done` using the GPU-bound `_finish`.
        Resumes purely from durable `state`/`CheckpointArtifacts` -- nothing from Pass 1 is held
        in memory across the phase boundary (matters at 15k-paper scale).

        Wrapped in the per-paper safety net (`_guard_per_paper`, class docstring "Unexpected-
        exception safety net") -- same reasoning as `parse_phase`.
        """
        # Hoisted exactly once per run, before the per-paper loop -- ARCHITECTURE.md §M9. The
        # query string never changes across papers in a run, so embedding it inside the loop
        # below would call embed() on a constant value once per paper for no reason.
        # Deliberately NOT inside the safety net below: a failure here isn't about one paper, it's
        # either a broken Config or a dead Embedder -- both make every subsequent paper in this
        # phase pointless to attempt, so this crashes loud rather than burning through the whole
        # run one quarantine at a time.
        topic_query_vec = self._embedder.embed([" ".join(self._config.focus_area_queries)])[0]
        self._before_finish_phase()
        consecutive_unexpected_failures = 0
        for ref in refs:
            consecutive_unexpected_failures = self._guard_per_paper(
                ref.paper_id, "finish_phase", consecutive_unexpected_failures,
                lambda ref=ref: self._finish_checkpoint(ref, topic_query_vec),
            )

    # -- Unexpected-exception safety net (last line of defense, both phases) -------------------
    #
    # CONVENTIONS.md §4 is explicit that only TransientError/PermanentError get caught here; any
    # other exception is a bug or an infrastructure failure and "should" crash loud so it gets
    # fixed, not limped past. In principle that's still correct. In practice, three separate real
    # multi-day production runs this session each crashed the ENTIRE batch on a different single
    # unanticipated exception type -- a GROBID 500 that wasn't TransientError-wrapped yet, a
    # finish_phase exception with no boundary at all, and (T-DOC14, this same PR)
    # `quarantine()`'s own bookkeeping raising sqlite3.IntegrityError on a re-attempted paper. Each
    # one cost real wall-clock/GPU-idle time to notice and fix, for a fault that ultimately
    # affected exactly one paper. `_guard_per_paper` is the deliberate, narrowly-scoped exception
    # to "never catch Exception broadly": it sits OUTSIDE `_prepare`/`_finish`'s own
    # TransientError/PermanentError handling (never instead of it) as a backstop for whatever that
    # handling doesn't anticipate -- including a bug in the handling itself.
    #
    # `ContractError` is deliberately EXCLUDED (re-raised before the broad `except Exception`
    # below ever sees it) -- CONVENTIONS.md §4 draws a hard line between "an infrastructure
    # failure or a bug nobody anticipated" (this safety net's whole point: quarantine and keep
    # going) and "a broken invariant" (must ALWAYS crash, unconditionally, never quarantined,
    # never counted toward the circuit breaker -- limping past a corrupted `ingest_state.stage`
    # value with a wrong result is worse than a stack trace naming it). Swallowing every exception
    # indiscriminately would have quietly defeated that distinction for the one class this project
    # most needs loud.
    #
    # It is not an unconditional "never stop" mechanism. `_MAX_CONSECUTIVE_UNEXPECTED_FAILURES`
    # consecutive unexpected failures (reset by any paper that completes without hitting this
    # path) still stops the run. Rationale for both pieces:
    #
    #   - Recording is defensive at two layers, not one bare `except: pass`: the caught exception
    #     is logged with its full traceback (so it's actually diagnosable later, not silently
    #     eaten) and recorded to `quarantine` with a reason prefixed `UNEXPECTED:` (so the
    #     quarantine table itself distinguishes "an already-understood failure mode" from "this
    #     was a surprise, go look at it" without needing to grep logs). The `quarantine()` call
    #     is ITSELF wrapped in its own try/except -- if even that fails, this falls back to a
    #     `logger.critical` and still continues to the next paper. The loop must be structurally
    #     unable to crash from this path.
    #   - The threshold is 5 CONSECUTIVE unexpected failures (not a fraction of a sliding window):
    #     a real per-paper bug (bad unicode, a corrupt individual PDF, a one-off data-shape
    #     gremlin) is independent across papers, so 5 of them in a row by chance is vanishingly
    #     unlikely if failures are genuinely per-paper. A SYSTEMIC fault (disk full, GPU driver
    #     crashed, network down) instead fails EVERY subsequent paper, so it trips this in at most
    #     5 papers -- fast enough to stop wasting GPU time, not so eager that two unrelated bad
    #     papers back-to-back (which does happen at 15k-paper scale) falsely kills a healthy run.
    #     "Consecutive" (not "N of the last M") also means one success anywhere resets it, so a
    #     genuinely spiky-but-recovering run is never punished for failures that aren't systemic.
    #     Revisit this number against real run data if it ever proves too eager or too slow to
    #     react -- it is a judgment call, not a derived constant.

    _MAX_CONSECUTIVE_UNEXPECTED_FAILURES = 5

    def _guard_per_paper(self, paper_id: str, stage: str, consecutive_failures: int, fn) -> int:
        """Runs `fn()` (one paper's `_prepare`/`_finish_checkpoint` call). On success, returns 0
        (resets the caller's consecutive-failure counter). On any exception other than
        `TransientError`/`PermanentError` (both already handled, and so never seen here, by
        `fn` itself), quarantines `paper_id` and returns `consecutive_failures + 1` -- unless that
        crosses the circuit-breaker threshold, in which case it re-raises instead."""
        try:
            fn()
        except ContractError:
            # CONVENTIONS.md §4: a ContractError is a broken invariant -- a bug, not "this paper is
            # bad" -- and must ALWAYS crash the run loud, unconditionally, never be quarantined or
            # counted toward the circuit breaker. Re-raised before the generic `except Exception`
            # below would otherwise catch it too (ContractError is an Exception subclass).
            raise
        except Exception as error:
            consecutive_failures += 1
            logger.error(
                "%s: unexpected exception during %s (not a TransientError/PermanentError this "
                "stage already knows how to handle) -- quarantining and continuing",
                paper_id,
                stage,
                exc_info=error,
            )
            try:
                self._state.quarantine(paper_id, stage, RuntimeError(f"UNEXPECTED: {error!r}"))
            except Exception:
                logger.critical(
                    "%s: quarantine() itself raised while recording an unexpected %s failure -- "
                    "this paper is UNRECORDED in the quarantine table, continuing anyway",
                    paper_id,
                    stage,
                    exc_info=True,
                )
            if consecutive_failures >= self._MAX_CONSECUTIVE_UNEXPECTED_FAILURES:
                raise RuntimeError(
                    f"{consecutive_failures} consecutive unexpected per-paper failures during "
                    f"{stage} -- stopping the run. This looks like a systemic failure (disk "
                    "full / GPU driver crashed / network down), not per-paper flakiness -- see "
                    f"the logged traceback for each. Last paper_id={paper_id!r}, error={error!r}"
                ) from error
            return consecutive_failures
        return 0

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
