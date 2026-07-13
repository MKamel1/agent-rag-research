"""End-to-end proof that the two composition roots (app.assembly) actually wire up into a real,
running pipeline -- the first real run of this entire system against a live paper, not a fake.

Needs the full real stack up: the arXiv API, the reference-resolution service, the real Parser
adapter (rag.parser), the real Summarizer/Embedder/Reranker services, and the real vector store.
Uses a throwaway temp DB/blob dir and a disposable vector-store collection per run.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from app.assembly import build_ingestion_orchestrator, build_mcp_server
from contracts.config import Config

pytestmark = pytest.mark.real_adapter

# A narrow, distinctive query so a cap=1 harvest resolves fast and predictably to one real paper.
_QUERY = ["Riesz regression Neyman orthogonal score debiased machine learning"]


@pytest.fixture
def workdir():
    d = tempfile.mkdtemp(prefix="composition_e2e_")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_ingest_then_query_one_real_paper(workdir):
    collection = f"e2e_{uuid.uuid4().hex[:8]}"
    db_path = str(workdir / "papers.db")
    blob_dir = str(workdir / "blobs")
    cfg = Config(focus_area_queries=_QUERY, gpu_lock_path=str(workdir / ".gpu.lock"))

    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=db_path, blob_dir=blob_dir, collection=collection
    )
    orchestrator.ingest(cfg.focus_area_queries, cap=1)

    from rag.document_store import DocumentStore
    from rag.ingest_state_sqlite import SqliteIngestState

    store = DocumentStore(db_path, blob_dir)
    records = list(store.iter_papers())
    assert len(records) == 1, f"expected exactly one ingested paper, got {len(records)}"
    record = records[0]
    paper_id = record.ref.paper_id

    state = SqliteIngestState(db_path)
    checkpoint = state.get(paper_id)
    assert checkpoint is not None
    assert checkpoint.stage == "done"

    server = build_mcp_server(cfg, db_path=db_path, blob_dir=blob_dir, collection=collection)

    # A distinctive word from the real title, so the query term is guaranteed to be meaningful
    # for whatever paper arXiv actually returned (not hardcoded to one specific paper).
    title_words = [w.strip(".,()") for w in record.ref.title.split() if len(w.strip(".,()")) > 6]
    query_term = title_words[0] if title_words else record.ref.title

    search_response = server.semantic_search(query_term, k=10)
    assert search_response.results, "expected at least one grounded result"
    top = search_response.results[0]
    assert top.paper_id == paper_id
    assert top.anchor is not None
    assert top.citation is not None
    # exercises get_span (anchor resolution) end to end
    resolved = server.get_span(top.anchor)
    assert resolved.strip()

    summary_view = server.get_paper(paper_id)
    assert summary_view.paper_id == paper_id
    assert summary_view.summary_text.strip()
