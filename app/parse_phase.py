"""`python -m app.parse_phase` — runs ONLY `IngestionOrchestrator.parse_phase()` (MinerU/GPU-bound
parse+chunk for the whole corpus), then exits.

Why a separate process at all (ARCHITECTURE.md §3): this project's own real-adapter VRAM
measurements found that clearing the parser's in-process model caches only partially frees GPU
memory (some sub-models don't release via `torch.cuda.empty_cache()`), and that residue would
accumulate paper after paper across a long run. A subprocess's exit is an OS-level guarantee of
full VRAM release regardless of that — `app/ingest.py` runs this file as a subprocess for Pass 1,
then runs Pass 2 (`finish_phase`) in its own process once this one has exited.
"""

from app.assembly import build_ingestion_orchestrator, harvest_refs
from contracts.config import Config
from rag.config import load_config


def _run_parse_phase(cfg: Config) -> None:
    """Pass 1 setup + run -- pulled out of `__main__` (same pattern as `app/ingest.py`'s
    `_run_finish_phase`) so a test can drive it without a real `python -m app.parse_phase`
    subprocess invocation.

    `cfg.db_path`/`cfg.blob_dir`/`cfg.collection` (T-DOC29: real Config fields now, not
    process-environment reads) default to `build_ingestion_orchestrator`'s own
    "papers.db"/"blobs"/"papers" unless `config.yaml` overrides them. Both this subprocess and
    `app/ingest.py`'s own process load the same `config.yaml` from the same cwd, so they agree on
    one location without any cross-process handoff. A test can still point this subprocess at a
    throwaway location by writing its own throwaway `config.yaml` and running from that directory
    (see `rag/test_composition_e2e.py`).
    """
    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=cfg.db_path, blob_dir=cfg.blob_dir, collection=cfg.collection,
    )
    # harvest_refs (app/assembly.py): shared with app/ingest.py's identical call so both phases of
    # one run agree on the same explicit paper set (cfg.ingest_paper_ids, if set) instead of Pass
    # 2 falling back to a fresh query-driven harvest() that this phase never used.
    refs = harvest_refs(cfg, orchestrator)
    orchestrator.parse_phase(refs)


if __name__ == "__main__":
    _run_parse_phase(load_config())
