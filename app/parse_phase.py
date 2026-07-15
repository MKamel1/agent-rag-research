"""`python -m app.parse_phase` — runs ONLY `IngestionOrchestrator.parse_phase()` (MinerU/GPU-bound
parse+chunk for the whole corpus), then exits.

Why a separate process at all (ARCHITECTURE.md §3): this project's own real-adapter VRAM
measurements found that clearing the parser's in-process model caches only partially frees GPU
memory (some sub-models don't release via `torch.cuda.empty_cache()`), and that residue would
accumulate paper after paper across a long run. A subprocess's exit is an OS-level guarantee of
full VRAM release regardless of that — `app/ingest.py` runs this file as a subprocess for Pass 1,
then runs Pass 2 (`finish_phase`) in its own process once this one has exited.
"""

import os

from app.assembly import build_ingestion_orchestrator
from rag.config import load_config

if __name__ == "__main__":
    cfg = load_config()
    # RAG_DB_PATH/RAG_BLOB_DIR/RAG_COLLECTION: optional overrides of build_ingestion_orchestrator's
    # own "papers.db"/"blobs"/"papers" defaults -- unset in normal use (both this subprocess and
    # app/ingest.py's own process then agree on the same relative-path defaults). Exists so a test
    # can point this subprocess at a throwaway location instead of the real one (see
    # rag/test_composition_e2e.py).
    orchestrator = build_ingestion_orchestrator(
        cfg,
        db_path=os.environ.get("RAG_DB_PATH"),
        blob_dir=os.environ.get("RAG_BLOB_DIR"),
        collection=os.environ.get("RAG_COLLECTION", "papers"),
    )
    # RAG_INGEST_PAPER_IDS (optional, comma-separated base arXiv ids): fetch exactly these known
    # papers via ArxivSource.fetch_by_ids() instead of the query-driven harvest() below -- used by
    # T-EVAL, whose 210-question eval set names 100 specific source papers that must be in the
    # corpus for the eval to be meaningful (a focus_area search can't guarantee hitting them).
    # Unset in normal use -- default behavior is completely unchanged.
    ids_env = os.environ.get("RAG_INGEST_PAPER_IDS")
    if ids_env:
        from rag.harvester import ArxivSource

        refs = ArxivSource().fetch_by_ids([i.strip() for i in ids_env.split(",") if i.strip()])
    else:
        refs = orchestrator.harvest(cfg.focus_area_queries, cfg.corpus_cap)
    orchestrator.parse_phase(refs)
