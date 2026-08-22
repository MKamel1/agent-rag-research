"""`python -m app.parse_phase` — runs ONLY `IngestionOrchestrator.parse_phase()` (MinerU/GPU-bound
parse+chunk for the whole corpus), then exits.

Why a separate process at all (ARCHITECTURE.md §3): this project's own real-adapter VRAM
measurements found that clearing the parser's in-process model caches only partially frees GPU
memory (some sub-models don't release via `torch.cuda.empty_cache()`), and that residue would
accumulate paper after paper across a long run. A subprocess's exit is an OS-level guarantee of
full VRAM release regardless of that — `app/ingest.py` runs this file as a subprocess for Pass 1,
then runs Pass 2 (`finish_phase`) in its own process once this one has exited.

T-DOC51: `--shard-index I --shard-count N` (default 0/1, i.e. today's exact single-worker
behavior) lets `app/ingest.py` spawn N of these subprocesses concurrently, each parsing a disjoint
slice of the same harvested corpus -- see `_shard` and `app/ingest.py`'s `--parse-workers` for the
measured +63% throughput fix this enables (`.phase0-data/pass1-gpu-underutilization.md`).
"""

import argparse
import hashlib
import logging

from app.assembly import build_ingestion_orchestrator, harvest_refs
from contracts.config import Config
from contracts.harvester import PaperRef
from rag.config import load_config

logger = logging.getLogger(__name__)


def _shard(refs: list[PaperRef], shard_index: int, shard_count: int) -> list[PaperRef]:
    """Identity-stable partition (RI-22): keep the refs whose paper_id hashes into this shard.

    Shard membership must be a function of the paper_id alone -- NOT of list position. Each of the
    N workers re-harvests independently (`_run_parse_phase` -> `harvest_refs`) against one shared
    corpus, and a query-driven harvest paginates arXiv for many minutes at the shipped
    `corpus_cap`; under `freshest_first`, one submission appearing between worker W0's page-k
    fetch and worker W1's page-k fetch inserts at rank 0 and shifts every later position by one.
    The previous stride slice (`refs[shard_index::shard_count]`) turned that shift into
    cross-worker double-assignment -- concurrent dual-writer access to `ingest_state`
    (`rag/ingest_state_sqlite.py`'s module docstring, "Cross-PROCESS safety") plus up to ~2x the
    GPU work. Hashing the paper_id makes every worker's slices agree paper-by-paper even when
    their lists differ: safety comes from identity-stable partitioning and no longer depends on
    the two harvests agreeing.

    Disjoint-and-complete still holds by construction (each id hashes to exactly one shard;
    pinned by `app/test_parse_phase.py::test_shard_is_disjoint_and_complete`), so each paper_id
    is still touched by exactly one worker. What is given up is the stride slice's exact
    round-robin balance: hash partitioning balances only approximately -- sha256 spreads ids
    roughly uniformly, so shard sizes stay close without depending on input order (17 ids over
    4 shards measured 2/5/4/6).

    The hash must be stable ACROSS PROCESSES, which rules out Python's builtin `hash()`: it is
    randomised per process via PYTHONHASHSEED, so two workers would silently disagree on shard
    assignment -- exactly the cross-process case this partition exists for. hashlib.sha256 is
    deterministic across processes and runs.
    """
    def _in_this_shard(ref: PaperRef) -> bool:
        digest = int(hashlib.sha256(ref.paper_id.encode("utf-8")).hexdigest(), 16)
        return digest % shard_count == shard_index

    return [ref for ref in refs if _in_this_shard(ref)]


def _run_parse_phase(cfg: Config, *, shard_index: int = 0, shard_count: int = 1) -> None:
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
    # T-DOC89 §4: report what was resolved, same pattern as app/delete_docs.py -- `cfg` here is
    # already this subprocess's own final, effective config (its own load_config() call in
    # __main__, or the scratch override config app/ingest.py's --limit/--scratch path spawns it
    # against via cwd -- either way, nothing downstream of this point changes it further).
    logger.info(
        "parse_phase: resolved db_path=%s blob_dir=%s collection=%s",
        cfg.db_path, cfg.blob_dir, cfg.collection,
    )
    orchestrator = build_ingestion_orchestrator(
        cfg, db_path=cfg.db_path, blob_dir=cfg.blob_dir, collection=cfg.collection,
    )
    # harvest_refs (app/assembly.py): shared with app/ingest.py's identical call so both phases of
    # one run agree on the same explicit paper set (cfg.ingest_paper_ids, if set) instead of Pass
    # 2 falling back to a fresh query-driven harvest() that this phase never used.
    refs = harvest_refs(cfg, orchestrator)
    orchestrator.parse_phase(_shard(refs, shard_index, shard_count))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    _run_parse_phase(load_config(), shard_index=args.shard_index, shard_count=args.shard_count)
