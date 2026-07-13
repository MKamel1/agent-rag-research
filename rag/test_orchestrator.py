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
    state.quarantine(paper_id, stage, error)           # dead-letter; run continues

Stage vocabulary is the frozen `ingest_state.stage` set (migrations/0001_init.sql):
harvested|parsed|chunked|summarized|embedded|stored|done.

`parser.parse(ref)` is passed a `PaperRef` (not raw bytes) so the suite stays zero-network — a
documented choice; if M1b threads a separate byte-fetch step, `SpyParser` moves with it.
--------------------------------------------------------------------------------------------------
"""

from datetime import date

import pytest

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.errors import PermanentError
from contracts.harvester import PaperRef
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

    def new_orchestrator(self, embedder=None, vector_index=None):
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
# GpuLock wiring
# ================================================================================================

def test_orchestrator_wraps_no_gpu_work_of_its_own():
    # T-A2 acceptance: the orchestrator wires the injected GpuLock to the (GPU-bound) stage
    # adapters, which acquire it themselves — the orchestrator acquires it around no work of its
    # own. With fake stages (which don't acquire), nothing should have acquired the lock.
    rig = Rig()
    rig.ingest()
    assert rig.gpu_lock.acquired == []
