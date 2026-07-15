# M1A-DORMANT (re-enable in M1b): skips until rag/orchestrator.py exists. M1b's Definition of Done
# (CONVENTIONS §11) requires this suite to be active (importorskip resolves) and green.
"""T-A2 IngestionOrchestrator (M9) — tests-first suite (M1a). Drives the frozen `ingest()`
interface end-to-end with all fakes (`FakeEmbedder`, `FakeGpuLock`, `FakeIngestState`,
`FakeSummarizer`, `FakeVectorStore`) plus test-local spies. Zero network, zero GPU.

Covers TEST-STRATEGY.md "Orchestrator" + WORK-BREAKDOWN T-A2:
  - full fake run: every paper reaches `done`;
  - idempotency: re-run produces no duplicates and re-invokes no stage;
  - resume WITHIN one paper (killed after `chunked`/`summarized`, before `embedded`): Chunker and
    Summarizer are NOT re-invoked for that paper on the resumed run, and later-queued papers still
    complete;
  - resume across the `stored`->`done` gap (killed after `DocumentStore.put()`, before
    `VectorIndex.upsert()`): `upsert()` runs for that paper on resume and it reaches `done` with a
    matching `FakeVectorStore` entry (the regression test for ARCHITECTURE "Operational
    invariants" §1);
  - source-of-truth written before the derived index (`put` precedes `upsert` per paper);
  - one poisoned paper is quarantined and the rest complete;
  - every stored paper has a non-null `relevance_score`;
  - `topic_query_vec` hoisted once per run: `FakeEmbedder.embed()` is called exactly `N+1` times
    for `N` papers, never `2N` (the loop-placement regression);
  - the injected `GpuLock` is wired but wraps no work of the orchestrator's own.

--------------------------------------------------------------------------------------------------
ASSUMED IngestionOrchestrator interface (T-A2) — documented, not yet frozen in `contracts/`.
ARCHITECTURE.md M9 freezes only the public method:

    ingest(focus_area, cap)   # harvest -> parse -> {chunk, summarize} -> embed
                              #  -> compute relevance_score -> store (put) -> index (upsert)

It does NOT pin the constructor / injected collaborators, nor the shape of the `ingest_state`
checkpoint store (DATA-CONTRACTS.md gives the `ingest_state`/`quarantine` *SQL* schema but no
module interface). Per principle 3 (accept dependencies, return results) the orchestrator composes
injected interfaces and imports no vendor SDKs / no `sqlite3` (CONVENTIONS §1 restricts sqlite3 to
DocumentStore + migrations). This suite commits the first concrete constructor shape; M1b conforms
to it (CONVENTIONS §0.7) or it is revised in review:

    IngestionOrchestrator(
        harvester,        # .harvest(focus_area, cap, ordering) -> Iterator[PaperRef] (deduped)
        parser,           # .parse(ref: PaperRef) -> ParsedDoc  (the Parser stage hides PDF/LaTeX
                          #   fetch+routing, ARCHITECTURE M2 "Hides") — kept zero-network here.
        chunker,          # .chunk(parsed) -> list[Chunk]
        summarizer,       # .summarize(parsed) -> str  (summary_text)
        embedder,         # Embedder: .embed(list[str]) -> list[Vector], .info
        document_store,   # M5: .put(PaperRecord), .get(paper_id)   (source of truth)
        vector_index,     # M6: .upsert(id, vector, payload)         (derived index)
        state,            # ingest_state checkpoint store — see below
        gpu_lock,         # GpuLock (wired to the stage adapters; the orchestrator wraps no GPU
                          #   work of its own — T-A2 acceptance)
        config,           # Config (focus_area_queries -> topic_query_vec)
    )

`state` (the ingest_state / checkpoint store). "Checkpointed per stage" + "resume without
re-running Chunker/Summarizer" operationally requires the checkpoint to persist BOTH the stage
label AND that stage's output artifacts (the parsed doc / chunks / summary are lost on crash and
are not yet in the atomic-whole-record DocumentStore before `stored`). API, backed by the
`ingest_state`/`ingest_checkpoint`/`quarantine` tables in production (T-A2 checkpoint-durability
fix, `.phase0-data/orchestrator-checkpoint-proposal.md` Option A — `rag/fakes/fake_ingest_state.py`
is the committed fake, `contracts/ingest_state.py` the typed artifacts payload):

    state.get(paper_id) -> Checkpoint | None           # Checkpoint has .stage, .artifacts
    state.checkpoint(paper_id, stage, artifacts=None)  # upsert stage; merge artifacts (idempotent)
    state.quarantine(paper_id, stage, error)           # dead-letter; run continues; idempotent
                                                        # (no-op, first reason wins, if paper_id is
                                                        # already quarantined)

Stage vocabulary is the frozen `ingest_state.stage` set (migrations/0001_init.sql):
harvested|parsed|chunked|summarized|embedded|stored|done.

`parser.parse(ref)` is passed a `PaperRef` (not raw bytes) so the suite stays zero-network — a
documented choice; if M1b threads a separate byte-fetch step, `SpyParser` moves with it.
--------------------------------------------------------------------------------------------------
"""

import pytest

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.errors import PermanentError, TransientError
from contracts.harvester import PaperRef
from contracts.ingest_state import CheckpointArtifacts
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from rag.fakes.fake_embedder import FakeEmbedder
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_ingest_state import FakeIngestState
from rag.fakes.fake_source import FakeSource
from rag.fakes.fake_summarizer import FakeSummarizer
from rag.fakes.fake_vector_store import FakeVectorStore

_mod = pytest.importorskip("rag.orchestrator")  # suite SKIPS until rag/orchestrator.py exists
IngestionOrchestrator = _mod.IngestionOrchestrator

ORDERING = "freshest_first"
DONE = "done"


# ================================================================================================
# Fixture papers — the committed FakeSource fixture, deduped to base ids (what a real Harvester
# hands the orchestrator). Reused so the suite tracks the same corpus as T-A1 / T-F4.
# ================================================================================================

def fixture_refs():
    """Deduped `PaperRef`s (latest version per base id) from fixtures/harvester/paper_refs.json."""
    latest: dict[str, PaperRef] = {}
    for ref in FakeSource().fetch(["x"], cap=100, ordering=ORDERING):
        prev = latest.get(ref.paper_id)
        if prev is None or ref.version > prev.version:
            latest[ref.paper_id] = ref
    return list(latest.values())


REFS = fixture_refs()
PAPER_IDS = [r.paper_id for r in REFS]
N = len(REFS)  # 3 distinct base ids
FIRST_ID = PAPER_IDS[0]


def make_parsed(ref: PaperRef) -> ParsedDoc:
    block = Block(
        block_id=f"{ref.paper_id}:b0",
        paper_id=ref.paper_id,
        text=ref.abstract,
        type="prose",
        page=0,
        bbox=(0.0, 0.0, 1.0, 1.0),
        section_path="1. Introduction",
        index=0,
    )
    return ParsedDoc(
        paper_id=ref.paper_id,
        markdown=f"# {ref.title}\n\n{ref.abstract}",
        blocks=[block],
        figures=[],
        tables=[],
        references=[],
        parser_id="fake-parser",
    )


def make_chunk(parsed: ParsedDoc) -> Chunk:
    block = parsed.blocks[0]
    anchor = Anchor(
        paper_id=parsed.paper_id,
        block_id=block.block_id,
        page=block.page,
        bbox=block.bbox,
        snippet=block.text[:200],
        section_path=block.section_path,
    )
    return Chunk(
        chunk_id=f"{parsed.paper_id}:c0",
        paper_id=parsed.paper_id,
        text=f"{parsed.markdown[:80]} :: {block.text}",
        anchor=anchor,
        section_path=block.section_path,
        parent_id=block.block_id,
        contextual_header=None,
    )


# ================================================================================================
# Test doubles / spies. The stage collaborators (Parser/Chunker/Summarizer) have no committed
# fakes, so they are recorded here; Embedder/Summarizer/VectorStore/GpuLock use the committed
# fakes, wrapped where a call log or a fault injection is needed.
# ================================================================================================

class StubHarvester:
    """Yields the (already deduped) fixture refs on every `harvest()` — the orchestrator's resume
    is driven by `state`/`ingest_state`, not by the harvester withholding refs, so re-yielding all
    of them on a resumed run is correct (an unfinished paper is re-offered; a `done` one is
    skipped by the stage check)."""

    def __init__(self, refs=REFS):
        self._refs = list(refs)

    def harvest(self, focus_area, cap, ordering):
        return iter(self._refs[:cap])


class SpyParser:
    def __init__(self, poison: set[str] | None = None, transient: dict[str, int] | None = None):
        """`poison`: paper_ids that raise `PermanentError` on every call (pre-existing coverage).
        `transient`: paper_id -> how many `TransientError`s to raise before that paper's `parse`
        finally succeeds (T-DOC12 regression coverage, the real reference-extraction-hiccup shape) -- a count
        at or above the orchestrator's retry budget never recovers, exercising the
        exhausted-retry-then-quarantine path instead.
        """
        self.calls: list[str] = []
        self._poison = poison or set()
        self._transient_budget = dict(transient or {})
        self._transient_calls_made: dict[str, int] = {}

    def parse(self, ref: PaperRef) -> ParsedDoc:
        self.calls.append(ref.paper_id)
        if ref.paper_id in self._poison:
            raise PermanentError(f"unparseable: {ref.paper_id}")
        budget = self._transient_budget.get(ref.paper_id, 0)
        made = self._transient_calls_made.get(ref.paper_id, 0)
        if made < budget:
            self._transient_calls_made[ref.paper_id] = made + 1
            raise TransientError(f"reference extraction failed: {ref.paper_id}")
        return make_parsed(ref)


class SpyChunker:
    def __init__(self):
        self.calls: list[str] = []

    def chunk(self, parsed: ParsedDoc) -> list[Chunk]:
        self.calls.append(parsed.paper_id)
        return [make_chunk(parsed)]


class SummarizerSpy:
    """Wraps the committed FakeSummarizer, adding a call log and (T-DOC13) the same
    poison/transient fault injection `SpyParser` got in T-DOC12/PR #75 -- `parsed.paper_id` is
    available directly here, so this keys off it exactly the same way `SpyParser` keys off
    `ref.paper_id`.

    `poison`: paper_ids that raise `PermanentError` on every call. `transient`: paper_id -> how
    many `TransientError`s to raise before that paper's `summarize` finally succeeds; a count at
    or above the orchestrator's retry budget never recovers, exercising exhausted-retry-then-
    quarantine instead.
    """

    def __init__(self, poison: set[str] | None = None, transient: dict[str, int] | None = None):
        self.calls: list[str] = []
        self._inner = FakeSummarizer()
        self._poison = poison or set()
        self._transient_budget = dict(transient or {})
        self._transient_calls_made: dict[str, int] = {}

    def summarize(self, parsed: ParsedDoc) -> str:
        self.calls.append(parsed.paper_id)
        if parsed.paper_id in self._poison:
            raise PermanentError(f"no usable prose to summarize: {parsed.paper_id}")
        budget = self._transient_budget.get(parsed.paper_id, 0)
        made = self._transient_calls_made.get(parsed.paper_id, 0)
        if made < budget:
            self._transient_calls_made[parsed.paper_id] = made + 1
            raise TransientError(f"generation LLM server returned 503: {parsed.paper_id}")
        return self._inner.summarize(parsed)


def _expected_summary_by_paper_id(refs=REFS) -> dict[str, str]:
    """What `FakeSummarizer` produces for each fixture paper, precomputed so `EmbedderSpy` can
    tell which paper a given `embed()` call belongs to from `texts[0]` alone -- production's
    `Embedder.embed(texts) -> list[Vector]` interface carries no `paper_id` (DATA-CONTRACTS.md
    M4), and `_finish` always puts `summary_text` first in the batch (`[summary_text] + [chunk
    texts]`, both the main-path and resume-path call sites)."""
    summarizer = FakeSummarizer()
    return {ref.paper_id: summarizer.summarize(make_parsed(ref)) for ref in refs}


_SUMMARY_TEXT_TO_PAPER_ID = {v: k for k, v in _expected_summary_by_paper_id().items()}


class EmbedderSpy:
    """Wraps the committed FakeEmbedder, counting `embed()` calls (for the N+1 hoist assertion),
    optionally failing on the Nth call (to inject a crash mid-paper), and (T-DOC13) optionally
    raising `PermanentError`/`TransientError` for a chosen paper's `embed()` call -- same
    poison/transient shape as `SpyParser`/`SummarizerSpy`, keyed via `_SUMMARY_TEXT_TO_PAPER_ID`
    since `embed()` itself only ever sees `texts`, never a `paper_id`. `topic_transient` is a
    separate count for the once-per-run, non-per-paper `topic_query_vec` hoist call (always
    `embed()` call #1, texts that never match any paper's summary) -- that call has no paper_id to
    key fault injection off at all.
    """

    def __init__(
        self,
        fail_on_call: int | None = None,
        poison: set[str] | None = None,
        transient: dict[str, int] | None = None,
        topic_transient: int = 0,
    ):
        self._inner = FakeEmbedder()
        self.calls: list[list[str]] = []
        self._fail_on_call = fail_on_call
        self._poison = poison or set()
        self._transient_budget = dict(transient or {})
        self._transient_calls_made: dict[str, int] = {}
        self._topic_transient_budget = topic_transient
        self._topic_transient_made = 0

    @property
    def info(self):
        return self._inner.info

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        if self._fail_on_call is not None and len(self.calls) == self._fail_on_call:
            raise RuntimeError("injected crash: GPU died mid-embed")
        paper_id = _SUMMARY_TEXT_TO_PAPER_ID.get(texts[0]) if texts else None
        if paper_id is None:
            # Not a per-paper batch (texts[0] matches no fixture paper's summary) -- the
            # once-per-run topic_query_vec call. Gated on paper_id, not call index: a retry
            # re-invokes embed() for the *same* logical call, so keying off "call #1" would only
            # match the first attempt and silently stop injecting on the retry.
            if self._topic_transient_made < self._topic_transient_budget:
                self._topic_transient_made += 1
                raise TransientError("embedding server returned 503: topic_query_vec")
            return self._inner.embed(texts)
        if paper_id in self._poison:
            raise PermanentError(f"embedding server returned 400: {paper_id}")
        budget = self._transient_budget.get(paper_id, 0)
        made = self._transient_calls_made.get(paper_id, 0)
        if made < budget:
            self._transient_calls_made[paper_id] = made + 1
            raise TransientError(f"embedding server returned 503: {paper_id}")
        return self._inner.embed(texts)


class DocStoreDouble:
    """Records every `put()` PaperRecord, keyed by paper_id (so a re-put is an idempotent
    upsert, never a duplicate). Logs `("put", paper_id)` to the shared `events` for ordering
    assertions."""

    def __init__(self, events: list):
        self.records: dict[str, PaperRecord] = {}
        self._events = events

    def put(self, record: PaperRecord) -> None:
        self.records[record.ref.paper_id] = record
        self._events.append(("put", record.ref.paper_id))

    def get(self, paper_id: str) -> PaperRecord | None:
        return self.records.get(paper_id)


class RecordingVectorIndex:
    """Wraps a real FakeVectorStore, logging each `upsert` to the shared `events` and optionally
    failing the first upsert for a chosen paper (to inject a crash in the stored->done gap). The
    underlying FakeVectorStore is shared across runs so a resumed run's upsert lands in the same
    store a test then inspects.

    `transient` (T-DOC13): paper_id -> how many `TransientError`s to raise (mirroring
    `rag/vector_index.py`'s real vector-store-failure classification -- that adapter never raises
    `PermanentError`) before that paper's upsert batch finally succeeds. Independent of
    `fail_paper_ids`, which stays a generic uncaught-`RuntimeError` crash for the pre-existing
    stored->done resume test.
    """

    def __init__(
        self,
        store: FakeVectorStore,
        events: list,
        fail_paper_ids: set[str] | None = None,
        transient: dict[str, int] | None = None,
    ):
        self._store = store
        self._events = events
        self._fail = set(fail_paper_ids or set())
        self._transient_budget = dict(transient or {})
        self._transient_calls_made: dict[str, int] = {}
        self.upserts: list[str] = []

    def upsert(self, id: str, vector, payload) -> None:
        paper_id = payload["paper_id"]
        if paper_id in self._fail:
            self._fail.discard(paper_id)  # fail exactly once, then let the resume succeed
            raise RuntimeError(f"injected crash: index died before upserting {paper_id}")
        budget = self._transient_budget.get(paper_id, 0)
        made = self._transient_calls_made.get(paper_id, 0)
        if made < budget:
            self._transient_calls_made[paper_id] = made + 1
            raise TransientError(f"vector store call failed: injected, {paper_id}")
        self._events.append(("upsert", paper_id))
        self.upserts.append(id)
        self._store.upsert(id, vector, payload)


class Rig:
    """One end-to-end fake wiring. `document_store`, `vector_store` (raw FakeVectorStore) and
    `state` persist across `new_orchestrator()` calls so a crash-then-restart shares them; the
    stage spies are shared too so a call-count assertion spans both runs."""

    def __init__(
        self, refs=REFS, poison=None, transient=None,
        summarizer_poison=None, summarizer_transient=None,
    ):
        self.events: list = []
        self.harvester = StubHarvester(refs)
        self.parser = SpyParser(poison=poison, transient=transient)
        self.chunker = SpyChunker()
        self.summarizer = SummarizerSpy(poison=summarizer_poison, transient=summarizer_transient)
        self.document_store = DocStoreDouble(self.events)
        self.vector_store = FakeVectorStore()
        self.state = FakeIngestState()
        self.gpu_lock = FakeGpuLock()
        self.config = Config(focus_area_queries=["causal inference", "treatment effect"])
        # Records every `retry_sleep(seconds)` call instead of really sleeping (T-DOC12/T-DOC13)
        # -- same injected-sleep pattern `rag.harvester.ArxivSource`'s own test suite uses.
        self.retry_sleeps: list[float] = []

    def new_orchestrator(
        self, embedder=None, vector_index=None, before_parse_phase=None, before_finish_phase=None,
        before_embed=None, max_retries=2,
    ):
        return IngestionOrchestrator(
            harvester=self.harvester,
            parser=self.parser,
            chunker=self.chunker,
            summarizer=self.summarizer,
            embedder=embedder or EmbedderSpy(),
            document_store=self.document_store,
            vector_index=vector_index or RecordingVectorIndex(self.vector_store, self.events),
            state=self.state,
            gpu_lock=self.gpu_lock,
            config=self.config,
            before_parse_phase=before_parse_phase,
            before_finish_phase=before_finish_phase,
            before_embed=before_embed,
            max_retries=max_retries,
            retry_sleep=self.retry_sleeps.append,
        )

    def ingest(self, orch=None, embedder=None, vector_index=None):
        orch = orch or self.new_orchestrator(embedder=embedder, vector_index=vector_index)
        orch.ingest(self.config.focus_area_queries, self.config.corpus_cap)
        return orch


def stored_ids(rig: Rig) -> set[str]:
    return set(rig.document_store.records)


def done_ids(rig: Rig) -> set[str]:
    return {pid for pid in PAPER_IDS if rig.state.stage_of(pid) == DONE}


# ================================================================================================
# Full run
# ================================================================================================

def test_full_run_stores_and_finishes_every_paper():
    rig = Rig()
    rig.ingest()
    assert stored_ids(rig) == set(PAPER_IDS)
    assert done_ids(rig) == set(PAPER_IDS)


def test_every_stored_paper_has_a_non_null_relevance_score():
    # Catches the orchestrator silently skipping the relevance_score computation (DATA-CONTRACTS
    # §M5/§M9). Cosine of unit vectors is in [-1, 1].
    rig = Rig()
    rig.ingest()
    for pid in PAPER_IDS:
        record = rig.document_store.get(pid)
        assert record.relevance_score is not None, f"{pid} stored with NULL relevance_score"
        assert -1.0001 <= record.relevance_score <= 1.0001


def test_source_of_truth_is_written_before_the_derived_index():
    # Ordering invariant (ARCHITECTURE §6A / Operational invariants §1): put() before upsert().
    rig = Rig()
    rig.ingest()
    for pid in PAPER_IDS:
        put_at = next(i for i, e in enumerate(rig.events) if e == ("put", pid))
        upsert_at = next(i for i, e in enumerate(rig.events) if e == ("upsert", pid))
        assert put_at < upsert_at, f"{pid}: derived index written before source of truth"


# ================================================================================================
# topic_query_vec hoist — the N+1 (not 2N) embed-count assertion
# ================================================================================================

def test_embed_is_called_n_plus_one_times_not_two_n():
    # One embed for topic_query_vec (hoisted once, before the per-paper loop) + one per paper.
    # A per-paper re-embed of the constant topic query would make this 2N; FakeEmbedder is
    # deterministic, so only this call-count assertion catches that loop-placement bug.
    rig = Rig()
    embedder = EmbedderSpy()
    rig.ingest(embedder=embedder)
    assert embedder.call_count == N + 1, (
        f"expected N+1={N + 1} embed calls (1 topic + {N} papers), got {embedder.call_count}"
    )
    assert embedder.call_count != 2 * N


def test_transient_topic_query_vec_error_recovers_after_bounded_retry():
    # T-DOC13 review finding: the hoisted topic_query_vec embed() call is the single highest-risk
    # uncaught call in finish_phase() (runs once, unconditionally, before any per-paper guard even
    # matters) -- it now gets the same bounded retry as every per-paper call, just no quarantine
    # (there's no single paper to blame for a run-level setup call).
    rig = Rig()
    embedder = EmbedderSpy(topic_transient=1)
    rig.ingest(embedder=embedder)

    assert rig.retry_sleeps == [1.0]
    assert done_ids(rig) == set(PAPER_IDS)


def test_transient_topic_query_vec_error_exhausts_retries_then_crashes_loud():
    # Unlike every per-paper call, exhausting the retry budget here re-raises instead of
    # quarantining -- CONVENTIONS.md §4's "crash loud" outcome for an infrastructure failure with
    # no per-paper target, matching this call's pre-existing (unguarded) crash behavior.
    rig = Rig()
    embedder = EmbedderSpy(topic_transient=99)
    with pytest.raises(TransientError):
        rig.ingest(embedder=embedder)

    assert rig.retry_sleeps == [1.0, 2.0]
    assert rig.state.quarantined == {}  # nothing quarantined -- this call has no paper to blame


# ================================================================================================
# Idempotency
# ================================================================================================

def test_rerun_produces_no_duplicates_and_re_invokes_no_stage():
    rig = Rig()
    embedder1 = EmbedderSpy()
    rig.ingest(embedder=embedder1)
    assert stored_ids(rig) == set(PAPER_IDS)

    chunker_calls_after_run1 = list(rig.chunker.calls)
    summarizer_calls_after_run1 = list(rig.summarizer.calls)

    # Second run over the same state/stores: everything is `done`, so nothing is reprocessed.
    embedder2 = EmbedderSpy()
    rig.ingest(embedder=embedder2)
    assert stored_ids(rig) == set(PAPER_IDS)  # still one record per paper, no dupes
    assert rig.chunker.calls == chunker_calls_after_run1
    assert rig.summarizer.calls == summarizer_calls_after_run1
    # No paper is re-embedded on a fully-done corpus; at most the once-per-run topic_query_vec
    # embed happens (the orchestrator may compute it before discovering there's no work).
    assert embedder2.call_count <= 1, "a fully-done corpus must re-embed no papers on re-run"


# ================================================================================================
# Resume WITHIN one paper: killed after chunked/summarized, before embedded
# ================================================================================================

def test_resume_after_summarized_does_not_reinvoke_chunker_or_summarizer():
    rig = Rig()

    # Run 1 crashes on the first paper's summary embed (call 1 = topic_query_vec, call 2 = first
    # paper's embed). The paper is checkpointed at `summarized`; later papers never start.
    crashing = EmbedderSpy(fail_on_call=2)
    with pytest.raises(RuntimeError):
        rig.ingest(embedder=crashing)
    assert rig.state.stage_of(FIRST_ID) == "summarized"
    assert rig.chunker.calls.count(FIRST_ID) == 1
    assert rig.summarizer.calls.count(FIRST_ID) == 1

    # Run 2 (clean embedder, same shared state/stores/spies) resumes.
    rig.ingest(embedder=EmbedderSpy())

    # The killed paper is NOT re-chunked or re-summarized — those stages were already checkpointed.
    assert rig.chunker.calls.count(FIRST_ID) == 1
    assert rig.summarizer.calls.count(FIRST_ID) == 1
    # It reaches done, and the later-queued papers (never started on run 1) all complete.
    assert done_ids(rig) == set(PAPER_IDS)
    assert stored_ids(rig) == set(PAPER_IDS)


# ================================================================================================
# Resume across the stored -> done gap (the regression test for ARCHITECTURE Op-invariants §1)
# ================================================================================================

def test_resume_after_stored_reruns_upsert_and_reaches_done():
    rig = Rig()

    # Run 1: the first paper's put() succeeds (paper at `stored`) but the index upsert crashes
    # before `done`. A naive orchestrator that marks `done` at put()-time would leave this paper
    # forever unindexed.
    failing_index = RecordingVectorIndex(rig.vector_store, rig.events, fail_paper_ids={FIRST_ID})
    with pytest.raises(RuntimeError):
        rig.ingest(embedder=EmbedderSpy(), vector_index=failing_index)
    assert rig.state.stage_of(FIRST_ID) == "stored"
    assert FIRST_ID in rig.document_store.records  # source of truth was written
    assert f"{FIRST_ID}:summary" not in rig.vector_store._store  # but the index was not

    # Run 2: a healthy index (sharing the same FakeVectorStore) must re-run upsert for the paper.
    healthy_index = RecordingVectorIndex(rig.vector_store, rig.events)
    rig.ingest(embedder=EmbedderSpy(), vector_index=healthy_index)

    assert any(uid.startswith(FIRST_ID) for uid in healthy_index.upserts), \
        "resume must re-run upsert() for a paper stuck at `stored`"
    assert rig.state.stage_of(FIRST_ID) == DONE
    assert f"{FIRST_ID}:summary" in rig.vector_store._store  # matching FakeVectorStore entry
    assert done_ids(rig) == set(PAPER_IDS)


# ================================================================================================
# Quarantine: one poisoned paper must not kill the run
# ================================================================================================

def test_poisoned_paper_is_quarantined_and_the_rest_complete():
    poisoned = PAPER_IDS[1]
    rig = Rig(poison={poisoned})
    rig.ingest()

    assert poisoned in rig.state.quarantined
    assert poisoned not in rig.document_store.records  # never stored
    survivors = set(PAPER_IDS) - {poisoned}
    assert stored_ids(rig) == survivors
    assert done_ids(rig) == survivors


# ================================================================================================
# T-DOC12/T-DOC13 regression: a `TransientError` from `parser.parse`, `summarizer.summarize`,
# `embedder.embed`, or `vector_index.upsert` must not crash the whole batch. A real end-to-end run
# hit this first for `parser.parse` (one paper's reference-extraction call returned a transient
# 500) -- it propagated all the way out of `ingest()`, killing the `python -m app.parse_phase`
# subprocess (and, via app/ingest.py's `subprocess.run(..., check=True)`, the parent `app.ingest`
# process too) with every paper still queued behind the failing one losing its progress for that
# run (T-DOC12, PR #75). Auditing `_finish`/`finish_phase()` for the same bug class (T-DOC13,
# PR #76) found the identical gap: `summarizer.summarize` only guarded `PermanentError`, both
# `embedder.embed()` call sites guarded neither error type, and `_upsert_record`'s
# `vector_index.upsert()` calls were unguarded too.
# ================================================================================================

def test_transient_parse_error_recovers_after_bounded_retry():
    flaky = PAPER_IDS[1]
    rig = Rig(transient={flaky: 1})  # one TransientError, then succeeds on retry
    rig.ingest()

    assert flaky not in rig.state.quarantined
    assert rig.retry_sleeps == [1.0]  # exactly one retry, backoff attempt 1 -> 2**(1-1)
    assert stored_ids(rig) == set(PAPER_IDS)
    assert done_ids(rig) == set(PAPER_IDS)


def test_transient_summarize_error_recovers_after_bounded_retry():
    flaky = PAPER_IDS[1]
    rig = Rig(summarizer_transient={flaky: 1})  # one TransientError, then succeeds on retry
    rig.ingest()

    assert flaky not in rig.state.quarantined
    assert rig.retry_sleeps == [1.0]  # exactly one retry, backoff attempt 1 -> 2**(1-1)
    assert stored_ids(rig) == set(PAPER_IDS)
    assert done_ids(rig) == set(PAPER_IDS)


def test_transient_parse_error_exhausts_retries_then_quarantines_and_the_rest_complete():
    # This is the actual regression for the crash: before T-DOC12, ANY TransientError out of
    # `parser.parse` (not just an exhausted-retry one) propagated out of the per-paper loop and
    # crashed the whole batch -- the poisoned paper's failure must instead land in `quarantine`,
    # and the loop must continue to every other paper (matching the pre-existing PermanentError
    # quarantine behavior in the test above).
    poisoned = PAPER_IDS[1]
    rig = Rig(transient={poisoned: 99})  # always raises -- exhausts the retry budget
    rig.ingest()

    assert poisoned in rig.state.quarantined
    assert poisoned not in rig.document_store.records  # never stored
    assert rig.retry_sleeps == [1.0, 2.0]  # max_retries=2 default -> 2 retries before quarantine
    survivors = set(PAPER_IDS) - {poisoned}
    assert stored_ids(rig) == survivors
    assert done_ids(rig) == survivors


def test_transient_summarize_error_exhausts_retries_then_quarantines_and_the_rest_complete():
    poisoned = PAPER_IDS[1]
    rig = Rig(summarizer_transient={poisoned: 99})  # always raises -- exhausts the retry budget
    rig.ingest()

    assert poisoned in rig.state.quarantined
    assert poisoned not in rig.document_store.records  # never stored
    assert rig.retry_sleeps == [1.0, 2.0]  # max_retries=2 default -> 2 retries before quarantine
    survivors = set(PAPER_IDS) - {poisoned}
    assert stored_ids(rig) == survivors
    assert done_ids(rig) == survivors


def test_transient_embed_error_recovers_after_bounded_retry():
    flaky = PAPER_IDS[1]
    rig = Rig()
    embedder = EmbedderSpy(transient={flaky: 1})
    rig.ingest(embedder=embedder)

    assert flaky not in rig.state.quarantined
    assert rig.retry_sleeps == [1.0]
    assert stored_ids(rig) == set(PAPER_IDS)
    assert done_ids(rig) == set(PAPER_IDS)


def test_transient_embed_error_exhausts_retries_then_quarantines_and_the_rest_complete():
    poisoned = PAPER_IDS[1]
    rig = Rig()
    embedder = EmbedderSpy(transient={poisoned: 99})
    rig.ingest(embedder=embedder)

    assert poisoned in rig.state.quarantined
    assert poisoned not in rig.document_store.records  # never stored (embed fails before put())
    assert rig.retry_sleeps == [1.0, 2.0]
    survivors = set(PAPER_IDS) - {poisoned}
    assert stored_ids(rig) == survivors
    assert done_ids(rig) == survivors


def test_permanent_embed_error_quarantines_immediately_no_retry():
    # Unlike the parser/summarizer/vector_index seams, `embedder.embed()` was previously unguarded
    # against PermanentError too (not just TransientError) -- this is the regression test for that
    # half of the gap.
    poisoned = PAPER_IDS[1]
    rig = Rig()
    embedder = EmbedderSpy(poison={poisoned})
    rig.ingest(embedder=embedder)

    assert poisoned in rig.state.quarantined
    assert poisoned not in rig.document_store.records
    assert rig.retry_sleeps == []  # PermanentError quarantines immediately, no retry/backoff
    survivors = set(PAPER_IDS) - {poisoned}
    assert stored_ids(rig) == survivors
    assert done_ids(rig) == survivors


def test_transient_embed_error_on_the_resume_path_is_also_guarded():
    # The `_finish` branch for a paper already at `stored` (the stored->done resume gap) calls
    # `embedder.embed()` a second, structurally different way -- this proves the retry/quarantine
    # guard applies there too, not just the main per-paper path.
    rig = Rig()

    # Run 1: get FIRST_ID to `stored` via a healthy embedder/index.
    healthy_index = RecordingVectorIndex(rig.vector_store, rig.events)
    rig.ingest(embedder=EmbedderSpy(), vector_index=healthy_index)
    assert rig.state.stage_of(FIRST_ID) == DONE  # sanity: full run completes cleanly first

    # Force FIRST_ID back to `stored` (simulating "crashed after put(), before done" without
    # re-running the whole pipeline) and re-ingest with an embedder that exhausts retries for it.
    rig.state.checkpoint(FIRST_ID, "stored")
    flaky_embedder = EmbedderSpy(transient={FIRST_ID: 99})
    rig.ingest(embedder=flaky_embedder)

    assert FIRST_ID in rig.state.quarantined
    assert FIRST_ID in rig.document_store.records  # DocumentStore.put's upsert already ran
    assert rig.retry_sleeps == [1.0, 2.0]


def test_transient_upsert_error_recovers_after_bounded_retry():
    flaky = PAPER_IDS[1]
    rig = Rig()
    index = RecordingVectorIndex(rig.vector_store, rig.events, transient={flaky: 1})
    rig.ingest(vector_index=index)

    assert flaky not in rig.state.quarantined
    assert rig.retry_sleeps == [1.0]
    assert done_ids(rig) == set(PAPER_IDS)


def test_transient_upsert_error_exhausts_retries_then_quarantines_and_the_rest_complete():
    poisoned = PAPER_IDS[1]
    rig = Rig()
    index = RecordingVectorIndex(rig.vector_store, rig.events, transient={poisoned: 99})
    rig.ingest(vector_index=index)

    assert poisoned in rig.state.quarantined
    # Unlike summarize/embed, the paper IS already stored by the time upsert runs -- quarantining
    # here relies on DocumentStore.put's upsert semantics to make a later full re-run safe (see
    # `_upsert_with_retry`'s docstring), not on nothing having been persisted yet.
    assert poisoned in rig.document_store.records
    assert rig.retry_sleeps == [1.0, 2.0]
    survivors = set(PAPER_IDS) - {poisoned}
    assert done_ids(rig) == survivors


# ================================================================================================
# GpuLock wiring
# ================================================================================================

def test_orchestrator_wraps_no_gpu_work_of_its_own():
    # T-A2 acceptance: the orchestrator wires the injected GpuLock to the (GPU-bound) stage
    # adapters, which acquire it themselves — the orchestrator acquires it around no work of its
    # own. With fake stages (which don't acquire), nothing should have acquired the lock.
    rig = Rig()
    rig.ingest()
    assert rig.gpu_lock.acquired == []


# ================================================================================================
# Phase-boundary model-lifecycle hooks (ARCHITECTURE.md §3: two-pass ingest, not per-paper
# pipelining — `before_parse_phase`/`before_finish_phase` let a composition root evict the model
# the *other* phase doesn't need before it starts. No-op by default (every test above passes
# neither and is unaffected); these two prove the ordering a real hook depends on.)
# ================================================================================================

def test_before_parse_phase_hook_fires_before_any_parsing():
    rig = Rig()
    snapshot = {}
    orch = rig.new_orchestrator(before_parse_phase=lambda: snapshot.setdefault(
        "parses_done_when_hook_fired", len(rig.parser.calls)
    ))
    rig.ingest(orch=orch)
    assert snapshot["parses_done_when_hook_fired"] == 0
    assert len(rig.parser.calls) == len(PAPER_IDS)  # the phase itself still ran to completion


def test_before_finish_phase_hook_fires_after_every_parse_and_before_any_summarize():
    rig = Rig()
    snapshot = {}

    def hook():
        snapshot["parses_done"] = len(rig.parser.calls)
        snapshot["summaries_done"] = len(rig.summarizer.calls)

    rig.ingest(orch=rig.new_orchestrator(before_finish_phase=hook))
    assert snapshot["parses_done"] == len(PAPER_IDS)  # Pass 1 fully finished first
    assert snapshot["summaries_done"] == 0  # Pass 2's own work hadn't started yet
    assert len(rig.summarizer.calls) == len(PAPER_IDS)  # and still completes normally after


def test_before_embed_hook_fires_once_per_paper_right_before_that_papers_embed_call():
    """Finer-grained than the phase-level hooks above (ARCHITECTURE.md §3, 2026-07-13 addition):
    fires per-paper, immediately before that paper's own `embed()` call -- not once per phase --
    since a real end-to-end run found the Summarizer sitting fully GPU-resident throughout the
    Embedder's work otherwise, real per-paper VRAM waste rather than a one-time cost.
    """
    rig = Rig()
    fire_counts_by_call_index = []

    def hook():
        fire_counts_by_call_index.append(len(rig.embedder_spy.calls))

    embedder = EmbedderSpy()
    rig.embedder_spy = embedder
    rig.ingest(orch=rig.new_orchestrator(embedder=embedder, before_embed=hook))

    # topic_query_vec is embed() call #0 (before any paper); the hook must not fire for that one
    # -- nothing needs evicting since no paper has summarized yet. Then one hook fire immediately
    # before each paper's own embed() call, in lockstep with the call count at that moment.
    assert fire_counts_by_call_index == list(range(1, len(PAPER_IDS) + 1))
    assert embedder.call_count == len(PAPER_IDS) + 1  # topic_query_vec hoist + one per paper


# ================================================================================================
# T-DOC16 (.phase0-data/pass1-gpu-underutilization.md): parse_phase() batches papers through
# `parser.parse_batch()` (config.parse_batch_size at a time) instead of calling `parser.parse()`
# once per paper. `parser.parse_batch` is duck-typed optional (`getattr(..., None)` in
# `_prepare_batch`) -- the pre-existing `SpyParser`/`Rig` above don't implement it, so every test
# above this section exercises the unchanged non-batched fallback path unmodified (confirmed by
# the full suite staying green with zero changes to `SpyParser`/`Rig`). These tests use a
# dedicated, minimal parser double instead, and build the `IngestionOrchestrator` directly rather
# than via `Rig` -- `parse_phase()` only ever touches `_parser`/`_chunker`/`_state`/`_config` (see
# its own and `_prepare`'s bodies), so `harvester`/`summarizer`/`embedder`/`document_store`/
# `vector_index`/`gpu_lock` are never touched and can stay `None`.
# ================================================================================================


class SpyBatchParser:
    """`.parse(ref)` (the pre-existing per-paper interface, used by `_parse_with_retry`'s
    fallback) plus `.parse_batch(refs)` (T-DOC16). `batch_fail_if_contains`: if a `parse_batch()`
    call's refs include any of these paper_ids, the WHOLE call raises `batch_fail_error` (default
    `PermanentError`) -- mirrors `rag/parser.py`'s real whole-batch-fails contract, where one bad
    member takes the whole `do_parse` call down with it. `singular_poison`: paper_ids that also
    raise `PermanentError` from the singular `.parse(ref)` path, independent of batch outcome --
    lets a test prove the fallback both recovers the batch's *good* members AND still correctly
    quarantines a *genuinely* bad one, exactly like today's per-paper `_parse_with_retry`.
    """

    def __init__(
        self,
        batch_fail_if_contains: set[str] | None = None,
        batch_fail_error: type[Exception] = PermanentError,
        singular_poison: set[str] | None = None,
    ):
        self.parse_calls: list[str] = []
        self.batch_calls: list[list[str]] = []
        self._batch_fail_if_contains = batch_fail_if_contains or set()
        self._batch_fail_error = batch_fail_error
        self._singular_poison = singular_poison or set()

    def parse(self, ref: PaperRef) -> ParsedDoc:
        self.parse_calls.append(ref.paper_id)
        if ref.paper_id in self._singular_poison:
            raise PermanentError(f"unparseable even singularly: {ref.paper_id}")
        return make_parsed(ref)

    def parse_batch(self, refs: list[PaperRef]) -> list[ParsedDoc]:
        ids = [r.paper_id for r in refs]
        self.batch_calls.append(ids)
        if self._batch_fail_if_contains & set(ids):
            raise self._batch_fail_error(
                f"whole batch failed, contains: {sorted(self._batch_fail_if_contains & set(ids))}"
            )
        return [make_parsed(ref) for ref in refs]


def _parse_phase_orchestrator(
    parser, state, *, parse_batch_size: int, batch_size_provider=None
) -> IngestionOrchestrator:
    return IngestionOrchestrator(
        harvester=None,
        parser=parser,
        chunker=SpyChunker(),
        summarizer=None,
        embedder=None,
        document_store=None,
        vector_index=None,
        state=state,
        gpu_lock=None,
        config=Config(focus_area_queries=["x"], parse_batch_size=parse_batch_size),
        retry_sleep=lambda seconds: None,
        batch_size_provider=batch_size_provider,
    )


def test_parse_phase_batch_success_checkpoints_all_papers_normally():
    # config.parse_batch_size (4) >= N (3) -> the whole harvest fits in one parse_batch() call.
    parser = SpyBatchParser()
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=4)

    orch.parse_phase(REFS)

    assert parser.batch_calls == [PAPER_IDS]
    assert parser.parse_calls == []  # singular .parse() never used on the success path
    for paper_id in PAPER_IDS:
        checkpoint = state.get(paper_id)
        assert checkpoint.stage == "chunked"
        assert checkpoint.artifacts.parsed is not None
        assert checkpoint.artifacts.chunks is not None


def test_parse_phase_handles_a_short_final_batch():
    # parse_batch_size=2, N=3 -> groups of [2, 1]; the last (short) group must still work.
    parser = SpyBatchParser()
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=2)

    orch.parse_phase(REFS)

    assert parser.batch_calls == [PAPER_IDS[:2], PAPER_IDS[2:]]
    assert len(parser.batch_calls[-1]) == 1  # the short final batch
    for paper_id in PAPER_IDS:
        assert state.get(paper_id).stage == "chunked"


@pytest.mark.parametrize("error_cls", [PermanentError, TransientError])
def test_parse_phase_batch_failure_falls_back_to_singular_path_for_every_paper(error_cls):
    # Neither error type from parse_batch() needs new quarantine/retry logic of its own -- both
    # just degrade to today's proven-safe per-paper `_prepare`/`_parse_with_retry` path.
    parser = SpyBatchParser(
        batch_fail_if_contains={PAPER_IDS[1]}, batch_fail_error=error_cls
    )
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=4)

    orch.parse_phase(REFS)

    assert parser.batch_calls == [PAPER_IDS]  # one attempted (failed) batch call
    assert parser.parse_calls == PAPER_IDS  # fallback: every ref in the batch re-attempted singularly
    for paper_id in PAPER_IDS:
        assert state.get(paper_id).stage == "chunked"  # none genuinely bad -- all recover via .parse()


def test_parse_phase_batch_failure_fallback_still_quarantines_a_genuinely_bad_paper():
    # T-DOC16's most important guarantee (the failure mode the design review flagged): a batch
    # failure must not silently lose or wrongly quarantine the OTHER N-1 good papers just because
    # one member is genuinely bad -- the fallback must recover the good ones AND still correctly
    # quarantine the bad one, exactly like `_parse_with_retry` already does outside of batching.
    poisoned = PAPER_IDS[1]
    parser = SpyBatchParser(
        batch_fail_if_contains={poisoned}, singular_poison={poisoned}
    )
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=4)

    orch.parse_phase(REFS)

    assert parser.batch_calls == [PAPER_IDS]
    assert parser.parse_calls == PAPER_IDS  # fallback still attempted every ref, poisoned included

    survivors = [pid for pid in PAPER_IDS if pid != poisoned]
    for pid in survivors:
        assert state.get(pid).stage == "chunked"  # the other N-1 papers: not lost, not quarantined
    assert state.get(poisoned) is None  # quarantine deletes the ingest_state row (module docstring)
    assert poisoned in state.quarantined


def test_parse_phase_skips_batch_call_for_papers_already_parsed_or_further_along():
    # A ref already at (or past) "parsed" from a prior run doesn't need a fresh parser call --
    # `_prepare_batch` excludes it from `parser.parse_batch()` entirely and lets `_prepare`'s own
    # pre-existing resume logic (unchanged by T-DOC16) handle it.
    parser = SpyBatchParser()
    state = FakeIngestState()
    already_done_id = PAPER_IDS[0]
    already_parsed = make_parsed(REFS[0])
    state.checkpoint(already_done_id, "chunked", artifacts=CheckpointArtifacts(
        parsed=already_parsed, chunks=[make_chunk(already_parsed)]
    ))
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=4)

    orch.parse_phase(REFS)

    fresh_ids = [pid for pid in PAPER_IDS if pid != already_done_id]
    assert parser.batch_calls == [fresh_ids]  # already_done_id excluded from the batch call
    for paper_id in PAPER_IDS:
        assert state.get(paper_id).stage == "chunked"


# ================================================================================================
# T-DOC18 Layer 2 — `_prepare_batch` calls the optional `prefetch_next_batch` hook
# ================================================================================================


class SpyBatchParserWithPrefetch(SpyBatchParser):
    """`SpyBatchParser` plus the optional `prefetch_next_batch` hook (T-DOC18 Layer 2, implemented
    for real by `app/assembly.py`'s `_PdfDownloadParser`). Records a single interleaved
    `calls_order` log (not just separate call lists) so a test can assert the prefetch for group
    N+1 is requested *before* `parse_batch()` runs for group N, matching `_prepare_batch`'s real
    call order."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefetch_calls: list[list[str]] = []
        self.calls_order: list[str] = []

    def prefetch_next_batch(self, refs: list[PaperRef]) -> None:
        ids = [r.paper_id for r in refs]
        self.prefetch_calls.append(ids)
        self.calls_order.append(f"prefetch:{ids}")

    def parse_batch(self, refs: list[PaperRef]) -> list[ParsedDoc]:
        self.calls_order.append(f"batch:{[r.paper_id for r in refs]}")
        return super().parse_batch(refs)


def test_parse_phase_prefetches_the_next_batch_before_the_current_batchs_parse_batch_call():
    # parse_batch_size=2, N=3 -> groups [2, 1]. Group 0's next batch is group 1's one ref; group 1
    # is the last group, so it has no next batch and prefetch is never called for it.
    parser = SpyBatchParserWithPrefetch()
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=2)

    orch.parse_phase(REFS)

    assert parser.prefetch_calls == [PAPER_IDS[2:3]]
    assert parser.calls_order == [
        f"prefetch:{PAPER_IDS[2:3]}",
        f"batch:{PAPER_IDS[0:2]}",
        f"batch:{PAPER_IDS[2:3]}",
    ], "the next batch's prefetch must be requested before the current batch's parse_batch() call"
    for paper_id in PAPER_IDS:
        assert state.get(paper_id).stage == "chunked"


def test_parse_phase_prefetch_excludes_refs_already_parsed_or_further_along():
    # The next batch's prefetch must go through the same "needs parsing" filter as the current
    # batch's own parse_batch() call -- a ref already at (or past) "parsed" has no PDF bytes worth
    # prefetching.
    parser = SpyBatchParserWithPrefetch()
    state = FakeIngestState()
    already_done_id = PAPER_IDS[2]  # would otherwise be the sole member of group 1 (the next batch)
    already_parsed = make_parsed(REFS[2])
    state.checkpoint(already_done_id, "chunked", artifacts=CheckpointArtifacts(
        parsed=already_parsed, chunks=[make_chunk(already_parsed)]
    ))
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=2)

    orch.parse_phase(REFS)

    assert parser.prefetch_calls == [], (
        "group 1's only ref is already parsed -- nothing left in the next batch to prefetch"
    )
    assert parser.batch_calls == [PAPER_IDS[0:2]]  # group 1 never needed a parse_batch() call either


# ================================================================================================
# T-DOC21 (.claude/plans/giggly-tumbling-globe.md): an optional `batch_size_provider` lets a
# composition root grow/shrink Pass-1 batch boundaries instead of the fixed
# `config.parse_batch_size` every time. `None` (the default, used by every test above this
# section) preserves today's exact fixed-stride behavior -- confirmed by every fixed-size test
# above staying green with zero changes.
# ================================================================================================


def test_parse_phase_uses_a_fixed_size_by_default_when_no_batch_size_provider_is_injected():
    # Same shape as test_parse_phase_handles_a_short_final_batch, just confirming explicitly that
    # omitting batch_size_provider (the default) reproduces the pre-T-DOC21 fixed-stride grouping.
    parser = SpyBatchParser()
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(parser, state, parse_batch_size=2)

    orch.parse_phase(REFS)

    assert parser.batch_calls == [PAPER_IDS[0:2], PAPER_IDS[2:3]]


def test_parse_phase_uses_the_batch_size_provider_when_injected_not_the_fixed_config_value():
    # The provider is called twice per loop iteration (current batch size, then a next-batch
    # lookahead guess -- rag/orchestrator.py's parse_phase docstring) -- repeat each intended size
    # so both calls in a given iteration agree: real, uneven batch boundaries [1, 2] a fixed
    # parse_batch_size could never produce (config.parse_batch_size is deliberately set to
    # something else, 4, to prove the provider -- not the config value -- actually drove this).
    sizes = iter([1, 1, 2, 2])
    parser = SpyBatchParser()
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(
        parser, state, parse_batch_size=4, batch_size_provider=lambda: next(sizes)
    )

    orch.parse_phase(REFS)

    assert parser.batch_calls == [PAPER_IDS[0:1], PAPER_IDS[1:3]]
    for paper_id in PAPER_IDS:
        assert state.get(paper_id).stage == "chunked"


def test_parse_phase_batch_size_provider_is_called_once_per_batch_not_once_total():
    call_count = {"n": 0}

    def provider():
        call_count["n"] += 1
        return 1  # one paper per batch -> 3 batches for 3 refs

    parser = SpyBatchParser()
    state = FakeIngestState()
    orch = _parse_phase_orchestrator(
        parser, state, parse_batch_size=4, batch_size_provider=provider
    )

    orch.parse_phase(REFS)

    assert parser.batch_calls == [[p] for p in PAPER_IDS]
    # Called twice per batch (current size + next-batch lookahead guess), 3 batches -> 6 calls.
    # The exact count matters less than "more than once, and scales with batch count" -- pin the
    # real number so a future refactor that changes this has to look at this test, not silently
    # drift.
    assert call_count["n"] == 6
