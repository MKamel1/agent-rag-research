"""`python -m app.ingest` — the real IngestionOrchestrator composition root.

Runs Pass 1 (parse, MinerU/GPU-bound) as a subprocess (`app/parse_phase.py`) so its exit fully
releases MinerU's VRAM (ARCHITECTURE.md §3), then runs Pass 2 (finish: summarize+embed+store,
also GPU-bound) in this process. The two GPU-bound phases never share a process, so they never
have to share VRAM at the same instant.
"""

import os
import subprocess
import sys

from app import tei_lifecycle
from app.assembly import build_ingestion_orchestrator
from contracts.config import Config
from rag.config import load_config


def _run_finish_phase(cfg: Config) -> None:
    """Pass 2 setup + run -- pulled out of `__main__` so a test can drive it without spawning the
    real Pass 1 subprocess.

    Restarts TEI HERE, before `orchestrator.finish_phase()` is ever called (T-DOC19 bug fix):
    `finish_phase()` embeds its once-per-run `topic_query_vec` BEFORE its own `before_finish_phase`
    hook fires (`rag/orchestrator.py`, frozen -- see that module's `finish_phase` docstring), so a
    composition-root hook wired to `tei_lifecycle.start_tei_containers` restarts TEI too late: this
    process's own `docker stop` (from Pass 1's `before_parse_phase`, still in effect across the
    Pass-1-subprocess boundary) is still in effect when that embed call fires, and it fails.
    Calling `start_tei_containers()` explicitly out here, before `finish_phase()` is invoked at
    all, closes that gap -- see `app/assembly.py` (no longer wires `before_finish_phase` for this).
    """
    orchestrator = build_ingestion_orchestrator(
        cfg,
        db_path=os.environ.get("RAG_DB_PATH"),
        blob_dir=os.environ.get("RAG_BLOB_DIR"),
        collection=os.environ.get("RAG_COLLECTION", "papers"),
    )
    # RAG_INGEST_PAPER_IDS: see app/parse_phase.py's identical branch -- kept in sync so both
    # phases of one run agree on the same explicit paper set instead of Pass 2 falling back to a
    # fresh query-driven harvest() that Pass 1 never used.
    ids_env = os.environ.get("RAG_INGEST_PAPER_IDS")
    if ids_env:
        from rag.harvester import ArxivSource

        refs = ArxivSource().fetch_by_ids([i.strip() for i in ids_env.split(",") if i.strip()])
    else:
        refs = orchestrator.harvest(cfg.focus_area_queries, cfg.corpus_cap)
    tei_lifecycle.start_tei_containers()
    orchestrator.finish_phase(refs)


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

    _run_finish_phase(cfg)
