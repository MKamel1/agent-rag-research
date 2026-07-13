"""`python -m app.ingest` — the real IngestionOrchestrator composition root."""

from app.assembly import build_ingestion_orchestrator
from rag.config import load_config

if __name__ == "__main__":
    cfg = load_config()
    build_ingestion_orchestrator(cfg).ingest(cfg.focus_area_queries, cfg.corpus_cap)
