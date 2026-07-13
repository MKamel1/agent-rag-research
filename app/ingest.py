"""`python -m app.ingest` — the real IngestionOrchestrator composition root.

Runs Pass 1 (parse, MinerU/GPU-bound) as a subprocess (`app/parse_phase.py`) so its exit fully
releases MinerU's VRAM (ARCHITECTURE.md §3), then runs Pass 2 (finish: summarize+embed+store,
also GPU-bound) in this process. The two GPU-bound phases never share a process, so they never
have to share VRAM at the same instant.
"""

import os
import subprocess
import sys

from app.assembly import build_ingestion_orchestrator
from rag.config import load_config

if __name__ == "__main__":
    cfg = load_config()

    # ponytail: no retry/backoff if this subprocess fails (e.g. external GPU pressure beyond what
    # eviction can clear) -- `check=True` lets it raise and stop the run; a re-run resumes from
    # ingest_state checkpoints. Add a poll-and-backoff `_ensure_vram` here if this ever proves to
    # be a real problem in practice (ARCHITECTURE.md §3).
    # Inherits this process's environment by default -- if RAG_DB_PATH/RAG_BLOB_DIR/RAG_COLLECTION
    # are set (see app/parse_phase.py), the subprocess picks up the same overrides this process's
    # own build_ingestion_orchestrator() call below reads, so both phases agree on one location.
    subprocess.run([sys.executable, "-m", "app.parse_phase"], check=True)

    orchestrator = build_ingestion_orchestrator(
        cfg,
        db_path=os.environ.get("RAG_DB_PATH"),
        blob_dir=os.environ.get("RAG_BLOB_DIR"),
        collection=os.environ.get("RAG_COLLECTION", "papers"),
    )
    refs = orchestrator.harvest(cfg.focus_area_queries, cfg.corpus_cap)
    orchestrator.finish_phase(refs)
