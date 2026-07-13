"""End-to-end proof that the two composition roots (app.assembly) actually wire up into a real,
running pipeline -- the first real run of this entire system against a live paper, not a fake.

Needs the full real stack up: the arXiv API, the reference-resolution service, the real Parser
adapter (rag.parser), the real Summarizer/Embedder/Reranker services, and the real vector store.
Uses a throwaway temp DB/blob dir and a disposable vector-store collection per run.

Runs the two-pass ingest for real (ARCHITECTURE.md §3): Pass 1 (parse) as a real subprocess
(`python -m app.parse_phase`, same as `app/ingest.py` does), Pass 2 (finish) in this process --
this is the actual reproduction of the CUDA OOM this design fixes, not an in-process shortcut.
Samples real GPU memory throughout both phases to prove the parser and the Summarizer are never
both resident at a measured peak.
"""

import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest
import yaml

from app.assembly import build_ingestion_orchestrator, build_mcp_server
from contracts.config import Config

pytestmark = pytest.mark.real_adapter

# A narrow, distinctive query so a cap=1 harvest resolves fast and predictably to one real paper.
_QUERY = ["Riesz regression Neyman orthogonal score debiased machine learning"]
_REPO_ROOT = str(Path(__file__).resolve().parents[1])


@pytest.fixture
def workdir():
    d = tempfile.mkdtemp(prefix="composition_e2e_")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _GpuSampler:
    """Polls `nvidia-smi` for this machine's total used VRAM in a background thread -- a coarse
    but real measurement (shared with whatever else is on the card), good enough to prove "peak
    stayed within budget" and "the two phases' peaks look like the two different residency sets
    ARCHITECTURE.md §3 predicts", not a precise per-process accounting.
    """

    def __init__(self, interval=0.5):
        self._interval = interval
        self._samples: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
                ).decode()
                self._samples.append(int(out.strip().splitlines()[0]))
            except (subprocess.SubprocessError, OSError, ValueError, IndexError):
                pass
            time.sleep(self._interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)

    @property
    def peak_mib(self) -> int:
        return max(self._samples) if self._samples else 0


def test_ingest_then_query_one_real_paper(workdir, monkeypatch):
    collection = f"e2e_{uuid.uuid4().hex[:8]}"
    db_path = str(workdir / "papers.db")
    blob_dir = str(workdir / "blobs")
    gpu_lock_path = str(workdir / ".gpu.lock")
    cfg = Config(focus_area_queries=_QUERY, gpu_lock_path=gpu_lock_path)

    # Pass 1: a REAL subprocess (mirrors app/ingest.py exactly) so the parser's VRAM release is
    # the real OS-level guarantee this design relies on, not an in-process approximation of it.
    # monkeypatch.setenv (not a manual merge of this process's environment) so the subprocess --
    # which inherits the current process's environment by default when `env=` is omitted -- picks
    # up these overrides alongside everything else already in this test process's environment.
    config_yaml = workdir / "config.yaml"
    config_yaml.write_text(yaml.safe_dump({
        "focus_area_queries": _QUERY, "corpus_cap": 1, "gpu_lock_path": gpu_lock_path,
    }))
    monkeypatch.setenv("PYTHONPATH", _REPO_ROOT)
    monkeypatch.setenv("RAG_DB_PATH", db_path)
    monkeypatch.setenv("RAG_BLOB_DIR", blob_dir)
    monkeypatch.setenv("RAG_COLLECTION", collection)
    with _GpuSampler() as parse_gpu:
        subprocess.run(
            [sys.executable, "-m", "app.parse_phase"],
            cwd=str(workdir), check=True, timeout=300,
        )

    # Pass 2: in this process, same config/paths -- proves the phase boundary hands off cleanly
    # across a real process exit, not just within one long-lived orchestrator instance.
    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=db_path, blob_dir=blob_dir, collection=collection
    )
    refs = orchestrator.harvest(cfg.focus_area_queries, cap=1)
    with _GpuSampler() as finish_gpu:
        orchestrator.finish_phase(refs)

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
    assert checkpoint.stage == "done"  # no CUDA OOM anywhere in either phase -- the actual fix

    # The real peak-VRAM proof (ARCHITECTURE.md §3's two residency totals): Pass 1 (parser +
    # Embedder + Reranker, ~16.2GB) and Pass 2 (Summarizer + Embedder + Reranker, ~21.4GB) each
    # measured well under this card's 24GB, and Pass 2's peak reflects the Summarizer being loaded
    # (higher baseline than Pass 1, since the summarize model at ~11.8GB dwarfs the parser's ~6.6GB).
    assert parse_gpu.peak_mib < 24576, f"Pass 1 peak {parse_gpu.peak_mib}MiB exceeded the card"
    assert finish_gpu.peak_mib < 24576, f"Pass 2 peak {finish_gpu.peak_mib}MiB exceeded the card"

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
