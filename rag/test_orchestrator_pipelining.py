"""T-A2 IngestionOrchestrator -- GPU-stage pipelining (WORK-BREAKDOWN.md T-A2 "Also accept",
ARCHITECTURE.md "Operational invariants" §3 / CONVENTIONS.md §6): CPU-bound work (parse/chunk)
for paper N+1 must proceed while GPU-bound work (summarize/embed) for paper N is in flight, so
the GPU-bound-call queue never sits idle waiting on CPU stages.

Not part of the frozen M1a suite (`rag/test_orchestrator.py`, which asserts correctness/resume,
not timing) -- this is a separate, timing-based test proving the *speed* property T-A2's
acceptance criteria adds on top of that suite. Self-contained (its own tiny fakes) rather than
importing `rag/test_orchestrator.py`'s helpers, so it stays independent of that frozen file.
"""

import time
from datetime import date

from contracts.chunker import Chunk
from contracts.config import Config
from contracts.document_store import PaperRecord
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from rag.fakes.fake_embedder import FakeEmbedder
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_summarizer import FakeSummarizer
from rag.fakes.fake_vector_store import FakeVectorStore
from rag.orchestrator import IngestionOrchestrator

CPU_DELAY = 0.06  # simulated parse+chunk cost
GPU_DELAY = 0.06  # simulated embed cost
N_PAPERS = 4


def _make_ref(i: int) -> PaperRef:
    return PaperRef(
        paper_id=f"25{i:02d}.00001",
        version="v1",
        title=f"Paper {i}",
        abstract=f"Abstract {i}",
        authors=["A. Author"],
        categories=["cs.LG"],
        published=date(2026, 1, 1 + i),
        updated=date(2026, 1, 1 + i),
        pdf_url=f"https://arxiv.org/pdf/25{i:02d}.00001v1",
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
        parser_id="slow-fake-parser",
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


class StubHarvester:
    def __init__(self, refs):
        self._refs = list(refs)

    def harvest(self, focus_area, cap, ordering):
        return iter(self._refs[:cap])


class SlowParser:
    """Simulated CPU-bound cost (real parsing: the Phase-0-chosen parser adapter, M2)."""

    def parse(self, ref: PaperRef) -> ParsedDoc:
        time.sleep(CPU_DELAY)
        return _make_parsed(ref)


class SlowChunker:
    def chunk(self, parsed: ParsedDoc) -> list[Chunk]:
        return [_make_chunk(parsed)]


class FakeSlowEmbedder:
    """Simulated GPU-bound cost (real embedding inference) -- `Fake`-prefixed (like every other
    fake in this repo) so it's exempt from the real-GPU-adapter `gpu_lock` check (CONVENTIONS.md
    §6/§12(f)): it holds no GPU, `time.sleep` stands in for inference latency only.
    """

    def __init__(self):
        self._inner = FakeEmbedder()

    @property
    def info(self):
        return self._inner.info

    def embed(self, texts: list[str]):
        time.sleep(GPU_DELAY)
        return self._inner.embed(texts)


class DocStoreDouble:
    def __init__(self):
        self.records: dict[str, PaperRecord] = {}

    def put(self, record: PaperRecord) -> None:
        self.records[record.ref.paper_id] = record

    def get(self, paper_id: str):
        return self.records.get(paper_id)


class RecordingVectorIndex:
    def __init__(self, store: FakeVectorStore):
        self._store = store

    def upsert(self, id: str, vector, payload) -> None:
        self._store.upsert(id, vector, payload)


class _Checkpoint:
    def __init__(self):
        self.stage: str | None = None
        self.artifacts: dict = {}


class FakeIngestState:
    def __init__(self):
        self._rows: dict[str, _Checkpoint] = {}

    def get(self, paper_id):
        return self._rows.get(paper_id)

    def checkpoint(self, paper_id, stage, **artifacts):
        row = self._rows.setdefault(paper_id, _Checkpoint())
        row.stage = stage
        row.artifacts.update(artifacts)

    def quarantine(self, paper_id, stage, error):
        self._rows.pop(paper_id, None)


def _build_orchestrator(refs, document_store):
    return IngestionOrchestrator(
        harvester=StubHarvester(refs),
        parser=SlowParser(),
        chunker=SlowChunker(),
        summarizer=FakeSummarizer(),
        embedder=FakeSlowEmbedder(),
        document_store=document_store,
        vector_index=RecordingVectorIndex(FakeVectorStore()),
        state=FakeIngestState(),
        gpu_lock=FakeGpuLock(),
        config=Config(focus_area_queries=["causal inference"]),
    )


def test_cpu_prep_for_next_paper_overlaps_gpu_work_for_current_paper():
    refs = [_make_ref(i) for i in range(N_PAPERS)]
    orch = _build_orchestrator(refs, DocStoreDouble())

    start = time.perf_counter()
    orch.ingest(["causal inference"], cap=len(refs))
    elapsed = time.perf_counter() - start

    # Fully sequential (no pipelining) would pay every paper's CPU delay *and* GPU delay, plus one
    # more GPU delay for the topic_query_vec hoist: (N+1)*GPU_DELAY + N*CPU_DELAY.
    fully_sequential = (N_PAPERS + 1) * GPU_DELAY + N_PAPERS * CPU_DELAY
    # Perfect pipelining hides all but the first paper's CPU work behind GPU work; require at
    # least half of the theoretically-hideable CPU time to actually be hidden, generous enough to
    # absorb scheduling jitter while still failing if CPU/GPU work ran fully sequentially.
    hideable = (N_PAPERS - 1) * CPU_DELAY
    assert elapsed < fully_sequential - hideable * 0.5, (
        f"elapsed={elapsed:.3f}s not faster than the non-pipelined estimate "
        f"({fully_sequential:.3f}s) by a margin consistent with CPU/GPU overlap -- "
        "CPU-bound prep for paper N+1 should run concurrently with GPU-bound work for paper N"
    )


def test_pipelined_run_still_produces_correct_output():
    # The timing property above is worthless if it comes at the cost of correctness -- confirm
    # every paper still lands in the store with the expected count.
    refs = [_make_ref(i) for i in range(N_PAPERS)]
    document_store = DocStoreDouble()
    orch = _build_orchestrator(refs, document_store)
    orch.ingest(["causal inference"], cap=len(refs))
    assert len(document_store.records) == N_PAPERS
