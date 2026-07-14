"""SqliteIngestState — the real-schema regression suite for the T-A2 checkpoint-durability fix
(`.phase0-data/orchestrator-checkpoint-proposal.md`, Option A). Not part of the frozen M1a suite
(`rag/test_orchestrator.py`) -- self-contained (its own tiny fakes), same reasoning
`rag/test_orchestrator_pipelining.py` gives for staying independent of that frozen file.

Exercises `rag/ingest_state_sqlite.py`'s `SqliteIngestState` against a database created by
`migrations/migrate.py` (0001_init.sql + 0002_ingest_checkpoint.sql) -- proving the gap the whole
fix is about is actually closed: before this fix, only the in-memory `FakeIngestState` made
checkpoint artifacts durable, so a real crash-and-restart between `chunked` and `summarized` had
nowhere to read `artifacts["parsed"]` back from and would raise `KeyError` on exactly the resume
path the old M1a suite claimed to cover. The last test here drives that exact scenario end to end
through `IngestionOrchestrator`, with a brand-new `SqliteIngestState` instance standing in for a
fresh process on resume (not a shared Python object, unlike every other resume test in this repo).
"""

import sqlite3
from datetime import date

import pytest

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.harvester import PaperRef
from contracts.ingest_state import CheckpointArtifacts
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from migrations.migrate import migrate
from rag.fakes.fake_embedder import FakeEmbedder
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_summarizer import FakeSummarizer
from rag.fakes.fake_vector_store import FakeVectorStore
from rag.ingest_state_sqlite import SqliteIngestState
from rag.orchestrator import IngestionOrchestrator


def _make_ref(i: int) -> PaperRef:
    return PaperRef(
        paper_id=f"26{i:02d}.00001",
        version="v1",
        title=f"Paper {i}",
        abstract=f"Abstract {i}",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 1, 1 + i),
        updated=date(2026, 1, 1 + i),
        pdf_url=f"https://arxiv.org/pdf/26{i:02d}.00001v1",
    )


def _make_parsed(ref: PaperRef) -> ParsedDoc:
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


def _make_chunk(parsed: ParsedDoc) -> Chunk:
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
        text=block.text,
        anchor=anchor,
        section_path=block.section_path,
        parent_id=block.block_id,
        contextual_header=None,
    )


# ================================================================================================
# SqliteIngestState in isolation: round-trip, merge, done-clears-artifacts, quarantine-removes-row
# ================================================================================================


def test_get_returns_none_for_an_unknown_paper(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)
    assert state.get("2601.00001") is None


def test_checkpoint_round_trips_stage_and_artifacts_through_real_sqlite(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)

    ref = _make_ref(0)
    parsed = _make_parsed(ref)
    state.checkpoint(ref.paper_id, "parsed", artifacts=CheckpointArtifacts(parsed=parsed))

    checkpoint = state.get(ref.paper_id)
    assert checkpoint.stage == "parsed"
    assert checkpoint.artifacts.parsed == parsed
    assert checkpoint.artifacts.chunks is None


def test_checkpoint_merges_artifacts_without_unsetting_earlier_fields(tmp_path):
    # The exact durability gap PR #38 was blocked on: a later stage's checkpoint call doesn't
    # repeat every earlier artifact, so the adapter must merge, not overwrite.
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)

    ref = _make_ref(0)
    parsed = _make_parsed(ref)
    chunks = [_make_chunk(parsed)]
    state.checkpoint(ref.paper_id, "parsed", artifacts=CheckpointArtifacts(parsed=parsed))
    state.checkpoint(ref.paper_id, "chunked", artifacts=CheckpointArtifacts(chunks=chunks))

    checkpoint = state.get(ref.paper_id)
    assert checkpoint.stage == "chunked"
    assert checkpoint.artifacts.parsed == parsed  # kept from the earlier call
    assert checkpoint.artifacts.chunks == chunks


def test_checkpoint_at_done_clears_artifacts_but_keeps_the_stage(tmp_path):
    # Decision proposal Option A: "row is deleted once a paper reaches done (nothing left to
    # resume)" -- for this adapter that means the ingest_checkpoint artifacts are cleared while
    # ingest_state's own row (and stage) survives, so a re-run still skips a `done` paper.
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)

    ref = _make_ref(0)
    parsed = _make_parsed(ref)
    state.checkpoint(ref.paper_id, "parsed", artifacts=CheckpointArtifacts(parsed=parsed))
    state.checkpoint(ref.paper_id, "done")

    checkpoint = state.get(ref.paper_id)
    assert checkpoint.stage == "done"
    assert checkpoint.artifacts.parsed is None


def test_quarantine_removes_the_row_entirely(tmp_path):
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)

    ref = _make_ref(0)
    state.checkpoint(ref.paper_id, "parsed", artifacts=CheckpointArtifacts())
    state.quarantine(ref.paper_id, "parsed", RuntimeError("bad paper"))

    assert state.get(ref.paper_id) is None


def test_quarantine_is_idempotent_for_an_already_quarantined_paper(tmp_path):
    # T-DOC14 regression: a real multi-day run, killed and resumed several times, re-harvested and
    # re-attempted a paper already quarantined from an earlier run (harvest() doesn't exclude
    # quarantined paper_ids -- by design, see rag/orchestrator.py's `harvest` docstring). The
    # second `quarantine()` call hit `quarantine.paper_id`'s PRIMARY KEY and raised
    # sqlite3.IntegrityError uncaught, crashing the entire batch -- the bookkeeping for an
    # already-failed paper must never be allowed to crash processing of every OTHER paper still in
    # flight (CONVENTIONS.md §4: quarantine-and-continue).
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)
    state = SqliteIngestState(db_path)

    ref = _make_ref(0)
    state.quarantine(ref.paper_id, "parsed", RuntimeError("404: PDF not found"))

    # Re-quarantining is a safe no-op -- must not raise sqlite3.IntegrityError.
    state.quarantine(ref.paper_id, "parsed", RuntimeError("404: PDF not found (retry)"))

    # First reason wins: the original quarantine row is untouched by the second call.
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT stage, error FROM quarantine WHERE paper_id = ?", (ref.paper_id,)
        ).fetchall()
    assert rows == [("parsed", "404: PDF not found")]

    # A different error on the repeat attempt is still a no-op (first reason wins regardless).
    state.quarantine(ref.paper_id, "summarized", RuntimeError("different failure entirely"))
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT stage, error FROM quarantine WHERE paper_id = ?", (ref.paper_id,)
        ).fetchall()
    assert rows == [("parsed", "404: PDF not found")]

    # state stays absent either way -- matches the "looks never-harvested" contract harvest()
    # relies on to safely retry a quarantined paper.
    assert state.get(ref.paper_id) is None


# ================================================================================================
# End-to-end crash-and-restart, real schema -- the regression test for the T-A2 blocker itself
# ================================================================================================


class StubHarvester:
    def __init__(self, refs):
        self._refs = list(refs)

    def harvest(self, focus_area, cap, ordering):
        return iter(self._refs[:cap])


class SpyParser:
    def __init__(self):
        self.calls: list[str] = []

    def parse(self, ref: PaperRef) -> ParsedDoc:
        self.calls.append(ref.paper_id)
        return _make_parsed(ref)


class SpyChunker:
    def __init__(self):
        self.calls: list[str] = []

    def chunk(self, parsed: ParsedDoc):
        self.calls.append(parsed.paper_id)
        return [_make_chunk(parsed)]


class SummarizerSpy:
    def __init__(self):
        self.calls: list[str] = []
        self._inner = FakeSummarizer()

    def summarize(self, parsed: ParsedDoc) -> str:
        self.calls.append(parsed.paper_id)
        return self._inner.summarize(parsed)


class EmbedderSpy:
    """Mirrors `rag/test_orchestrator.py`'s `EmbedderSpy` -- optionally fails on the Nth `embed()`
    call to inject a crash mid-run."""

    def __init__(self, fail_on_call: int | None = None):
        self._inner = FakeEmbedder()
        self.calls: list[list[str]] = []
        self._fail_on_call = fail_on_call

    @property
    def info(self):
        return self._inner.info

    def embed(self, texts: list[str]):
        self.calls.append(list(texts))
        if self._fail_on_call is not None and len(self.calls) == self._fail_on_call:
            raise RuntimeError("injected crash: GPU died mid-embed")
        return self._inner.embed(texts)


class DocStoreDouble:
    def __init__(self):
        self.records: dict[str, object] = {}

    def put(self, record) -> None:
        self.records[record.ref.paper_id] = record

    def get(self, paper_id: str):
        return self.records.get(paper_id)


class RecordingVectorIndex:
    def __init__(self, store: FakeVectorStore):
        self._store = store
        self.upserts: list[str] = []

    def upsert(self, id: str, vector, payload) -> None:
        self.upserts.append(id)
        self._store.upsert(id, vector, payload)


def test_crash_and_restart_resumes_via_real_sqlite_schema_without_reinvoking_stages(tmp_path):
    """Run 1 crashes mid-paper (after `summarized`, before `embedded`) against a real, migrated
    sqlite db. Run 2 opens a BRAND-NEW `SqliteIngestState` on the same db file -- standing in for
    a fresh process -- and must resume without re-invoking Chunker/Summarizer for that paper, and
    every paper must still reach `done`."""
    db_path = str(tmp_path / "test.sqlite")
    migrate(db_path)

    refs = [_make_ref(0), _make_ref(1)]
    parser = SpyParser()
    chunker = SpyChunker()
    summarizer = SummarizerSpy()
    document_store = DocStoreDouble()
    vector_store = FakeVectorStore()
    config = Config(focus_area_queries=["causal inference"])

    def build_orchestrator(state, embedder, vector_index):
        return IngestionOrchestrator(
            harvester=StubHarvester(refs),
            parser=parser,
            chunker=chunker,
            summarizer=summarizer,
            embedder=embedder,
            document_store=document_store,
            vector_index=vector_index,
            state=state,
            gpu_lock=FakeGpuLock(),
            config=config,
        )

    # Run 1: crash on the first paper's post-summarize embed call (call 1 = the once-per-run
    # topic_query_vec hoist, call 2 = paper 0's summary+chunks embed).
    run1_state = SqliteIngestState(db_path)
    orch1 = build_orchestrator(
        run1_state, EmbedderSpy(fail_on_call=2), RecordingVectorIndex(vector_store)
    )
    with pytest.raises(RuntimeError):
        orch1.ingest(config.focus_area_queries, cap=len(refs))

    assert run1_state.stage_of(refs[0].paper_id) == "summarized"
    assert chunker.calls.count(refs[0].paper_id) == 1
    assert summarizer.calls.count(refs[0].paper_id) == 1

    # Run 2: a brand-new SqliteIngestState pointed at the same db file -- this is the crash the
    # whole fix is about. Before the fix, this read would find `stage="summarized"` but no
    # durable `parsed`/`chunks`/`summary_text` to resume from (KeyError on `artifacts["parsed"]`).
    run2_state = SqliteIngestState(db_path)
    orch2 = build_orchestrator(run2_state, EmbedderSpy(), RecordingVectorIndex(vector_store))
    orch2.ingest(config.focus_area_queries, cap=len(refs))

    # The crashed paper was NOT re-parsed/re-chunked/re-summarized on resume.
    assert chunker.calls.count(refs[0].paper_id) == 1
    assert summarizer.calls.count(refs[0].paper_id) == 1
    # Every paper reaches `done` and is stored -- proving the real schema round-trip works, not
    # just the in-memory FakeIngestState.
    for ref in refs:
        assert run2_state.stage_of(ref.paper_id) == "done"
        assert ref.paper_id in document_store.records
