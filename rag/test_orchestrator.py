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

import logging
from datetime import date

import pytest

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.errors import ContractError, PermanentError
from contracts.harvester import PaperRef
from contracts.ingest_state import Checkpoint, CheckpointArtifacts
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
    def __init__(self, poison: set[str] | None = None):
        self.calls: list[str] = []
        self._poison = poison or set()

    def parse(self, ref: PaperRef) -> ParsedDoc:
        self.calls.append(ref.paper_id)
        if ref.paper_id in self._poison:
            raise PermanentError(f"unparseable: {ref.paper_id}")
        return make_parsed(ref)


class SpyChunker:
    def __init__(self):
        self.calls: list[str] = []

    def chunk(self, parsed: ParsedDoc) -> list[Chunk]:
        self.calls.append(parsed.paper_id)
        return [make_chunk(parsed)]


class SummarizerSpy:
    """Wraps the committed FakeSummarizer, adding a call log."""

    def __init__(self):
        self.calls: list[str] = []
        self._inner = FakeSummarizer()

    def summarize(self, parsed: ParsedDoc) -> str:
        self.calls.append(parsed.paper_id)
        return self._inner.summarize(parsed)


class EmbedderSpy:
    """Wraps the committed FakeEmbedder, counting `embed()` calls (for the N+1 hoist assertion)
    and optionally failing on the Nth call (to inject a crash mid-paper)."""

    def __init__(self, fail_on_call: int | None = None):
        self._inner = FakeEmbedder()
        self.calls: list[list[str]] = []
        self._fail_on_call = fail_on_call

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
    store a test then inspects."""

    def __init__(self, store: FakeVectorStore, events: list, fail_paper_ids: set[str] | None = None):
        self._store = store
        self._events = events
        self._fail = set(fail_paper_ids or set())
        self.upserts: list[str] = []

    def upsert(self, id: str, vector, payload) -> None:
        paper_id = payload["paper_id"]
        if paper_id in self._fail:
            self._fail.discard(paper_id)  # fail exactly once, then let the resume succeed
            raise RuntimeError(f"injected crash: index died before upserting {paper_id}")
        self._events.append(("upsert", paper_id))
        self.upserts.append(id)
        self._store.upsert(id, vector, payload)


class Rig:
    """One end-to-end fake wiring. `document_store`, `vector_store` (raw FakeVectorStore) and
    `state` persist across `new_orchestrator()` calls so a crash-then-restart shares them; the
    stage spies are shared too so a call-count assertion spans both runs."""

    def __init__(self, refs=REFS, poison=None):
        self.events: list = []
        self.harvester = StubHarvester(refs)
        self.parser = SpyParser(poison=poison)
        self.chunker = SpyChunker()
        self.summarizer = SummarizerSpy()
        self.document_store = DocStoreDouble(self.events)
        self.vector_store = FakeVectorStore()
        self.state = FakeIngestState()
        self.gpu_lock = FakeGpuLock()
        self.config = Config(focus_area_queries=["causal inference", "treatment effect"])

    def new_orchestrator(
        self, embedder=None, vector_index=None, before_parse_phase=None, before_finish_phase=None,
        before_embed=None,
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
    #
    # Drives harvest/parse_phase directly, then calls `_finish_checkpoint` per-ref instead of
    # `finish_phase(refs)` -- bypassing `finish_phase`'s `_guard_per_paper` per-paper safety net
    # (T-DOC14 add-on: an in-process exception for one paper no longer crashes the whole batch by
    # default). This test simulates a genuine process crash ("Run 1 crashes" -> "Run 2 ... shared
    # state ... resumes"), which the safety net can't and shouldn't absorb -- an OS-level kill
    # isn't something any Python try/except could catch.
    crashing = EmbedderSpy(fail_on_call=2)
    orch = rig.new_orchestrator(embedder=crashing)
    harvested = orch.harvest(rig.config.focus_area_queries, rig.config.corpus_cap)
    orch.parse_phase(harvested)
    topic_query_vec = crashing.embed([" ".join(rig.config.focus_area_queries)])[0]
    with pytest.raises(RuntimeError):
        for ref in harvested:
            orch._finish_checkpoint(ref, topic_query_vec)
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
    #
    # Drives harvest/parse_phase directly, then calls `_finish_checkpoint` per-ref instead of
    # `finish_phase(refs)` -- bypassing `finish_phase`'s `_guard_per_paper` per-paper safety net
    # (T-DOC14 add-on), for the same "simulate a genuine process crash" reason given in
    # `test_resume_after_summarized_does_not_reinvoke_chunker_or_summarizer` above.
    failing_index = RecordingVectorIndex(rig.vector_store, rig.events, fail_paper_ids={FIRST_ID})
    embedder = EmbedderSpy()
    orch = rig.new_orchestrator(embedder=embedder, vector_index=failing_index)
    harvested = orch.harvest(rig.config.focus_area_queries, rig.config.corpus_cap)
    orch.parse_phase(harvested)
    topic_query_vec = embedder.embed([" ".join(rig.config.focus_area_queries)])[0]
    with pytest.raises(RuntimeError):
        for ref in harvested:
            orch._finish_checkpoint(ref, topic_query_vec)
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
# Unexpected-exception safety net (T-DOC14 add-on, `_guard_per_paper`): a bug nobody anticipated
# for one paper must not kill the batch either -- same "quarantine and continue" contract as a
# classified PermanentError above, but for the unclassified case, plus a circuit breaker for when
# repeated "unexpected" failures signal a systemic fault instead of per-paper flakiness. Exercised
# through `parse_phase` (CPU-only, no Embedder/GpuLock wiring needed) -- `_guard_per_paper` is one
# function shared verbatim by `finish_phase`, so this is a full test of its behavior, not a
# parse-phase-specific test.
# ================================================================================================

def _synthetic_refs(n: int) -> list[PaperRef]:
    """`n` distinct minimal PaperRefs -- REFS (module-level, above) only has 3 fixture papers,
    not enough to exercise a 5-consecutive-failure circuit breaker."""
    return [
        PaperRef(
            paper_id=f"2601.{i:05d}",
            version="v1",
            title=f"Synthetic paper {i}",
            abstract=f"Abstract {i}",
            authors=["A. Author"],
            categories=["cs.LG"],
            published=date(2026, 1, 1),
            updated=date(2026, 1, 1),
            pdf_url=f"https://arxiv.org/pdf/2601.{i:05d}v1",
        )
        for i in range(n)
    ]


class ParserWithUnexpectedBug:
    """Like SpyParser, but `buggy` paper_ids raise a plain, unclassified exception (simulating an
    unanticipated bug) instead of the `PermanentError` SpyParser's `poison` set raises -- exercises
    the safety-net path, not the pre-existing PermanentError-quarantine path."""

    def __init__(self, buggy: set[str] | None = None):
        self.calls: list[str] = []
        self._buggy = buggy or set()

    def parse(self, ref: PaperRef) -> ParsedDoc:
        self.calls.append(ref.paper_id)
        if ref.paper_id in self._buggy:
            raise ZeroDivisionError(f"unanticipated bug parsing {ref.paper_id}")
        return make_parsed(ref)


class QuarantineAlsoBrokenState(FakeIngestState):
    """A `state` adapter whose `quarantine()` itself always raises -- the "even the recording
    attempt fails" case `_guard_per_paper` must survive without crashing the batch."""

    def quarantine(self, paper_id, stage, error):
        raise RuntimeError("state backend is also broken")


def _prepare_only_rig(refs, parser, state=None):
    """Minimal wiring for a parse_phase-only scenario -- no Embedder/DocumentStore/VectorIndex
    needed since these tests never reach finish_phase."""
    return IngestionOrchestrator(
        harvester=StubHarvester(refs=refs),
        parser=parser,
        chunker=SpyChunker(),
        summarizer=SummarizerSpy(),
        embedder=EmbedderSpy(),
        document_store=DocStoreDouble([]),
        vector_index=RecordingVectorIndex(FakeVectorStore(), []),
        state=state if state is not None else FakeIngestState(),
        gpu_lock=FakeGpuLock(),
        config=Config(focus_area_queries=["causal inference"]),
    )


def test_unexpected_exception_for_one_paper_is_quarantined_distinctly_and_the_rest_complete():
    refs = _synthetic_refs(4)
    buggy_id = refs[1].paper_id
    parser = ParserWithUnexpectedBug(buggy={buggy_id})
    state = FakeIngestState()
    orch = _prepare_only_rig(refs, parser, state=state)

    orch.parse_phase(refs)  # must not raise -- 1 unexpected failure is far below the threshold

    # Recorded, but distinctly from a normal PermanentError quarantine (UNEXPECTED prefix).
    assert buggy_id in state.quarantined
    _, recorded_error = state.quarantined[buggy_id]
    assert str(recorded_error).startswith("UNEXPECTED:")
    # Every other paper reached chunked -- the bug in one paper didn't stop the batch.
    for ref in refs:
        if ref.paper_id != buggy_id:
            assert state.stage_of(ref.paper_id) == "chunked"


def test_a_broken_quarantine_call_during_unexpected_handling_still_does_not_crash_the_batch(caplog):
    refs = _synthetic_refs(3)
    buggy_id = refs[0].paper_id
    parser = ParserWithUnexpectedBug(buggy={buggy_id})
    state = QuarantineAlsoBrokenState()
    orch = _prepare_only_rig(refs, parser, state=state)

    with caplog.at_level(logging.CRITICAL, logger="rag.orchestrator"):
        orch.parse_phase(refs)  # must not raise even though state.quarantine() itself raises

    assert any(
        buggy_id in record.message and "UNRECORDED" in record.message
        for record in caplog.records
    ), "a broken quarantine() call must be logged loudly, not silently swallowed"
    # The batch still continues past the paper whose bookkeeping failed.
    for ref in refs:
        if ref.paper_id != buggy_id:
            assert state.stage_of(ref.paper_id) == "chunked"


def test_circuit_breaker_stops_the_run_after_enough_consecutive_unexpected_failures():
    threshold = IngestionOrchestrator._MAX_CONSECUTIVE_UNEXPECTED_FAILURES
    refs = _synthetic_refs(threshold + 2)  # more refs than the breaker should ever reach
    parser = ParserWithUnexpectedBug(buggy={ref.paper_id for ref in refs})  # every paper is buggy
    orch = _prepare_only_rig(refs, parser)

    with pytest.raises(RuntimeError, match="consecutive unexpected"):
        orch.parse_phase(refs)

    # Stopped exactly at the threshold -- did not burn through every remaining paper first (that
    # would defeat the point: a systemic failure should be noticed fast, not after wasting the
    # whole run).
    assert parser.calls == [ref.paper_id for ref in refs[:threshold]]


def test_contract_error_is_never_swallowed_by_the_safety_net():
    # ContractError is a broken invariant, not "this paper is bad" (CONVENTIONS.md §4) -- it must
    # ALWAYS crash the run loud, even a single occurrence, never quarantined and never counted
    # toward `_guard_per_paper`'s circuit breaker. A corrupted `ingest_state.stage` value (outside
    # the frozen vocabulary) is `_at_least`'s real, reachable trigger for this.
    refs = _synthetic_refs(2)
    state = FakeIngestState()
    state._rows[refs[0].paper_id] = Checkpoint(
        stage="bogus_stage_outside_the_frozen_vocabulary", artifacts=CheckpointArtifacts()
    )
    orch = _prepare_only_rig(refs, SpyParser(), state=state)

    with pytest.raises(ContractError):
        orch.parse_phase(refs)

    # Never quarantined -- a ContractError is a bug, not a per-paper failure to record and move on
    # from.
    assert refs[0].paper_id not in state.quarantined


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
