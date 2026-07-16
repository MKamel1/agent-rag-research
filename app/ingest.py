"""`python -m app.ingest` — the real IngestionOrchestrator composition root.

Runs Pass 1 (parse, MinerU/GPU-bound) as a subprocess (`app/parse_phase.py`) so its exit fully
releases MinerU's VRAM (ARCHITECTURE.md §3), then runs Pass 2 (finish: summarize+embed+store,
also GPU-bound) in this process. The two GPU-bound phases never share a process, so they never
have to share VRAM at the same instant.

T-DOC51: `--parse-workers N` (default 1, i.e. today's exact behavior) runs Pass 1 as N concurrent
`app.parse_phase` subprocesses instead of one, each parsing a disjoint shard of the same harvested
corpus -- measured +63% parse throughput (3 workers, `.phase0-data/pass1-gpu-underutilization.md`)
because the parser renders each doc with exactly 1 CPU process while the GPU idles, and a
second/third worker's GPU work fills that gap. Every worker still fully exits before Pass 2 starts
(two-phase VRAM isolation, unchanged).
"""

import argparse
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


def _run_parse_phase_subprocesses(parse_workers: int) -> None:
    """Pass 1 -- pulled out of `__main__` (same pattern as `_run_finish_phase`) so a test can
    drive it with a mocked `subprocess.Popen`/`subprocess.run` instead of spawning real
    GPU-bound parse subprocesses.

    `parse_workers == 1` (default) is byte-for-byte the original single
    `subprocess.run(..., check=True)` call -- unchanged.

    `parse_workers > 1` spawns that many `app.parse_phase` subprocesses, each given a disjoint
    `--shard-index`/`--shard-count` slice of the same harvested corpus (`app/parse_phase.py`'s
    `_shard`). All N are waited on -- not just until the first failure -- before this function
    returns or raises, preserving two-phase VRAM isolation: `__main__` below only calls
    `_run_finish_phase` (Pass 2) after every Pass-1 worker has fully exited. Any non-zero exit
    fails the WHOLE run (`RuntimeError`), never just the workers that happened to fail: a dead
    shard must not silently ship a partial corpus -- exactly the failure mode that made one
    benchmark config look like a win when a worker had actually OOM'd
    (`.phase0-data/pass1-gpu-underutilization.md`).
    """
    if parse_workers == 1:
        subprocess.run([sys.executable, "-m", "app.parse_phase"], check=True)
        return

    procs = [
        subprocess.Popen(
            [
                sys.executable, "-m", "app.parse_phase",
                "--shard-index", str(i), "--shard-count", str(parse_workers),
            ]
        )
        for i in range(parse_workers)
    ]
    failures = [(i, rc) for i, p in enumerate(procs) if (rc := p.wait()) != 0]
    if failures:
        raise RuntimeError(
            f"app.parse_phase: {len(failures)}/{parse_workers} shard worker(s) failed "
            f"(shard_index, returncode): {failures}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parse-workers", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    cfg = load_config()
    args = _parse_args()

    # ponytail: no retry/backoff if a Pass-1 subprocess fails (e.g. external GPU pressure beyond
    # what eviction can clear) -- letting it raise stops the run; a re-run resumes from
    # ingest_state checkpoints. Add a poll-and-backoff `_ensure_vram` here if this ever proves to
    # be a real problem in practice (ARCHITECTURE.md §3).
    # No explicit env/cwd handoff needed (T-DOC29): every subprocess inherits this process's cwd
    # by default and calls the same `load_config()` (see app/parse_phase.py's `__main__`), so all
    # of them read the identical config.yaml -- every phase/shard agrees on
    # db_path/blob_dir/collection/etc. by construction, not by propagating env vars across process
    # boundaries.
    _run_parse_phase_subprocesses(args.parse_workers)

    _run_finish_phase(cfg)
