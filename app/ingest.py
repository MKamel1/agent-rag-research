"""`python -m app.ingest` — the real IngestionOrchestrator composition root.

Runs Pass 1 (parse, MinerU/GPU-bound) as a subprocess (`app/parse_phase.py`) so its exit fully
releases MinerU's VRAM (ARCHITECTURE.md §3), then runs Pass 2 (finish: summarize+embed+store,
also GPU-bound) in this process. The two GPU-bound phases never share a process, so they never
have to share VRAM at the same instant.
"""

import subprocess
import sys

from app import tei_lifecycle
from app.assembly import build_ingestion_orchestrator, harvest_refs
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
        cfg, db_path=cfg.db_path, blob_dir=cfg.blob_dir, collection=cfg.collection,
    )
    # harvest_refs (app/assembly.py): shared with app/parse_phase.py's identical call so both
    # phases of one run agree on the same explicit paper set (cfg.ingest_paper_ids, if set)
    # instead of Pass 2 falling back to a fresh query-driven harvest() that Pass 1 never used.
    refs = harvest_refs(cfg, orchestrator)
    tei_lifecycle.start_tei_containers()
    orchestrator.finish_phase(refs)


if __name__ == "__main__":
    cfg = load_config()

    # ponytail: no retry/backoff if this subprocess fails (e.g. external GPU pressure beyond what
    # eviction can clear) -- `check=True` lets it raise and stop the run; a re-run resumes from
    # ingest_state checkpoints. Add a poll-and-backoff `_ensure_vram` here if this ever proves to
    # be a real problem in practice (ARCHITECTURE.md §3).
    # No explicit env/cwd handoff needed (T-DOC29): this subprocess inherits this process's cwd by
    # default and calls the same `load_config()` (see app/parse_phase.py's `__main__`), so it reads
    # the identical config.yaml -- both phases agree on db_path/blob_dir/collection/etc. by
    # construction, not by propagating env vars across the process boundary.
    subprocess.run([sys.executable, "-m", "app.parse_phase"], check=True)

    _run_finish_phase(cfg)
