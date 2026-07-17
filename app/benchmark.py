"""`python -m app.benchmark` -- T-DOC55: a controlled GPU benchmark/perf harness (OG-20).

Why this exists (`.phase0-data/pass1-gpu-underutilization.md` "RESOLVED"): answering "how do we
raise pages/minute" required hand-building, from scratch, every control needed to trust the
numbers -- evict TEI, verify a clean `nvidia-smi` baseline, exclude model-init via a discarded
warm-up, hold the paper set fixed, poll GPU util, normalize to pages/min, and treat any crashed
worker as invalidating its config, not a fast result. None of that existed in the repo; every
benchmark reinvented it. Two real near-misses this caused: an alternate parser backend's first
test was a false negative (a memory-fraction default left too little KV cache, and the
summarizer's local model may still have been resident) and had to be redone from a clean GPU to
be trusted; and a session nearly dispatched three GPU benchmarks in parallel, which on one GPU
would have contended and produced confidently wrong numbers for all three.

This is a MEASUREMENT harness, not a new ingest path: it orchestrates the existing parse
machinery by shelling out to `python -m app.parse_phase` (same subprocess pattern
`app/ingest.py` uses for Pass 1), never reimplements parsing.

Four controls, in the order a run applies them:

1. **GPU serialization lock** (`acquire_gpu_lock_or_fail`) -- the part with no existing
   analogue. Reuses `rag/gpu_lock.py`'s `FileGpuLock` (same lock file, same `filelock` mechanism
   production ingest already serializes on via `Config.gpu_lock_path`), but fails fast
   (`timeout=0`) instead of `FileGpuLock`'s own blocking wait: production ingest is fine queuing,
   a benchmark run is not -- two concurrent GPU benchmarks contend and both come back wrong.
2. **Clean-GPU verification** (`verify_clean_gpu`) -- refuses to benchmark unless `nvidia-smi`
   shows a true baseline (optionally evicting TEI first via `app.tei_lifecycle`, imported not
   edited).
3. **Warm-up-then-time** (`run_benchmark`) -- a discarded single-paper warm-up subprocess run,
   then a separate timed run over the full fixed corpus, so first-touch model-load/kernel-compile
   cost never contaminates the steady-state number.
4. **Fixed-corpus + normalized output** (`BenchmarkResult`) -- GPU util sampled every
   `_POLL_INTERVAL_SECONDS` throughout the timed run; avg util / %@0% / %>=90% / peak VRAM /
   pages-per-minute (normalized by real page counts via `pypdfium2`, the same library
   `rag/parser.py` already uses for this), and any worker crash marks the whole config `oom=True`
   -- invalidated, never scored as a fast result (the "config-D trap": a dead worker did less
   work, not more).
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import filelock
import pypdfium2 as pdfium
import yaml

from app import tei_lifecycle
from contracts.config import Config
from rag.config import load_config
from rag.gpu_lock import FileGpuLock

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 0.5
# Matches the scratchpad `evict_gpu.sh` threshold this control codifies -- below this, residual
# driver/display overhead, not a real compute resident.
_CLEAN_GPU_MAX_USED_MIB = 600
_HIGH_UTIL_THRESHOLD_PCT = 90
# Real signatures observed/expected from a CUDA OOM surfacing through a parse-worker subprocess
# crash (`.phase0-data/pass1-gpu-underutilization.md`'s decision table: "3 workers + VRAM=32"
# rows).
_OOM_SIGNATURES = (
    "CUDA out of memory",
    "CUDNN_STATUS_ALLOC_FAILED",
    "OutOfMemoryError",
    "RuntimeError: CUDA error: out of memory",
)


class BenchmarkError(RuntimeError):
    """The harness could not produce a trustworthy measurement -- GPU lock held elsewhere, a
    dirty baseline, a failed warm-up, or a worker crash. Deliberately distinct from
    `contracts/errors.py`'s three-class taxonomy: those classify a *pipeline stage's* outcome for
    one paper (retry / quarantine / crash-the-run); this classifies a *benchmark run's* outcome
    for a whole config, which the caller must refuse to score, not retry or quarantine.
    """


# --- normalized output (control #4) ---------------------------------------------------------


@dataclass(frozen=True)
class GpuSample:
    epoch: float
    util_pct: int
    mem_used_mib: int


@dataclass(frozen=True)
class BenchmarkResult:
    """One config's measured result. `oom=True` invalidates every derived metric below (they all
    read as `0.0`/`0` rather than a real-looking number) -- the config-D trap: a worker that
    OOM'd and died partway through leaves a short elapsed time that would otherwise look like a
    *fast* result if scored normally.
    """

    config_name: str
    total_pages: int
    elapsed_s: float
    samples: list[GpuSample] = field(default_factory=list)
    oom: bool = False

    @property
    def avg_util_pct(self) -> float:
        if self.oom or not self.samples:
            return 0.0
        return statistics.fmean(s.util_pct for s in self.samples)

    @property
    def pct_at_zero(self) -> float:
        return self._pct(lambda s: s.util_pct == 0)

    @property
    def pct_at_high_util(self) -> float:
        return self._pct(lambda s: s.util_pct >= _HIGH_UTIL_THRESHOLD_PCT)

    @property
    def peak_vram_mib(self) -> int:
        if self.oom or not self.samples:
            return 0
        return max(s.mem_used_mib for s in self.samples)

    @property
    def pages_per_minute(self) -> float:
        """Pages/minute normalized by real page count -- `0.0` for an invalidated (`oom=True`)
        config so it can never look like a competitive number in a decision table; never divides
        by a zero/negative elapsed time either."""
        if self.oom or self.elapsed_s <= 0:
            return 0.0
        return self.total_pages / (self.elapsed_s / 60.0)

    def _pct(self, predicate: Callable[[GpuSample], bool]) -> float:
        if self.oom or not self.samples:
            return 0.0
        return 100.0 * sum(1 for s in self.samples if predicate(s)) / len(self.samples)

    def to_dict(self) -> dict:
        return {
            "config_name": self.config_name,
            "total_pages": self.total_pages,
            "elapsed_s": round(self.elapsed_s, 2),
            "oom": self.oom,
            "avg_util_pct": round(self.avg_util_pct, 1),
            "pct_at_zero": round(self.pct_at_zero, 1),
            "pct_at_high_util": round(self.pct_at_high_util, 1),
            "peak_vram_mib": self.peak_vram_mib,
            "pages_per_minute": round(self.pages_per_minute, 1),
            "n_samples": len(self.samples),
        }


def detect_oom(returncodes: list[int], combined_output: str) -> bool:
    """A worker crash (any non-zero exit) always invalidates the config; this only distinguishes
    the OOM case for a clearer message -- `run_benchmark` raises `BenchmarkError` either way on a
    crash it can't attribute to OOM, and marks `oom=True` when it can.
    """
    if all(rc == 0 for rc in returncodes):
        return False
    return any(sig in combined_output for sig in _OOM_SIGNATURES)


# --- GPU lock (control #1) -------------------------------------------------------------------


@contextmanager
def acquire_gpu_lock_or_fail(lock_path: Path) -> Iterator[None]:
    """Exclusive lock so two benchmarks can never run concurrently on the one GPU. Reuses
    `rag.gpu_lock.FileGpuLock` unmodified -- same lock file/`filelock` mechanism production
    ingest serializes on -- but calls the underlying `filelock.FileLock.acquire(timeout=0)`
    directly (`FileGpuLock.acquire()` returns that raw `FileLock`, see `rag/gpu_lock.py`) instead
    of entering it Protocol-style: production ingest is fine blocking until the GPU is free; a
    benchmark run must fail fast and say so, not silently queue behind another benchmark and
    report a number contaminated by contention.

    Raises `BenchmarkError` immediately if the lock is already held.
    """
    raw_lock = FileGpuLock(lock_path).acquire("benchmark")
    try:
        with raw_lock.acquire(timeout=0):
            yield
    except filelock.Timeout as e:
        raise BenchmarkError(
            f"GPU lock ({lock_path}) is already held by another process -- refusing to run a "
            "second concurrent benchmark on the one GPU (concurrent GPU benchmarks contend and "
            "produce confidently wrong numbers for both)."
        ) from e


# --- GPU sampling / clean-baseline verification (control #2) ---------------------------------


def _query_gpu() -> GpuSample | None:
    """One `nvidia-smi` sample, or `None` on any failure (never raises -- same best-effort
    contract as `app/gpu_headroom.py::free_vram_mib`)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10.0, check=True,
        )
        util_str, mem_str = result.stdout.strip().splitlines()[0].split(",")
        return GpuSample(epoch=time.time(), util_pct=int(util_str), mem_used_mib=int(mem_str))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError,
            ValueError, IndexError) as e:
        logger.warning("nvidia-smi sample failed, discarding this sample: %s", e)
        return None


def verify_clean_gpu(*, evict_tei: bool = True, query_gpu: Callable[[], GpuSample | None] = _query_gpu) -> None:
    """Refuse to benchmark on a dirty GPU. Optionally evicts TEI first (best-effort, via
    `app.tei_lifecycle`, imported not edited), then requires one real `nvidia-smi` sample under
    `_CLEAN_GPU_MAX_USED_MIB`. Raises `BenchmarkError` if the baseline can't be confirmed clean --
    a dirty baseline makes every timed number downstream untrustworthy.
    """
    if evict_tei:
        tei_lifecycle.stop_tei_containers()

    sample = query_gpu()
    if sample is None:
        raise BenchmarkError(
            "could not read an nvidia-smi baseline -- refusing to benchmark without one"
        )
    if sample.mem_used_mib > _CLEAN_GPU_MAX_USED_MIB:
        raise BenchmarkError(
            f"GPU is not at a clean baseline: {sample.mem_used_mib}MiB used (max allowed "
            f"{_CLEAN_GPU_MAX_USED_MIB}MiB) -- evict other GPU residents (TEI, the summarizer's "
            "local model, or a stray process) before benchmarking."
        )


# --- warm-up-then-time + fixed corpus (controls #3 + #4) -------------------------------------


def _total_pages(pdf_cache_dir: str, paper_ids: list[str]) -> int:
    """Real page counts via `pypdfium2` (same library `rag/parser.py` already uses for this) over
    the cached PDF for each paper id -- `{pdf_cache_dir}/{paper_id}.pdf`, the same naming
    convention `app/assembly.py::_PdfDownloadParser` and `app/prefetch_pdfs.py` already use.
    """
    total = 0
    for paper_id in paper_ids:
        pdf_path = Path(pdf_cache_dir) / f"{paper_id}.pdf"
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            total += len(doc)
        finally:
            doc.close()
    return total


def _write_scratch_config(
    dest_dir: Path, base_config: Config, *, paper_ids: list[str], db_path: str, blob_dir: str,
) -> None:
    """Writes a throwaway `config.yaml` into `dest_dir` so a `python -m app.parse_phase`
    subprocess launched with `cwd=dest_dir` picks it up via its own default `load_config()` call
    (`rag/config.py`'s loader resolves relative to the process cwd -- `app/parse_phase.py`'s own
    module docstring documents exactly this trick for pointing a test subprocess at a throwaway
    location). Every other field carries over unchanged from `base_config` -- only the fixed
    corpus (`ingest_paper_ids`) and the throwaway storage paths (so a benchmark run never touches
    real `papers.db`/blobs) are overridden.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    data = base_config.model_dump()
    data["ingest_paper_ids"] = list(paper_ids)
    data["db_path"] = str(dest_dir / db_path)
    data["blob_dir"] = str(dest_dir / blob_dir)
    (dest_dir / "config.yaml").write_text(yaml.safe_dump(data))


def _run_worker_processes(cwd: Path, n_workers: int) -> tuple[list[int], str]:
    """Launches `n_workers` concurrent `python -m app.parse_phase` subprocesses sharded
    round-robin (same `--shard-index`/`--shard-count` flags `app/ingest.py` drives), each logging
    to its own file under `cwd` (log files, not pipes -- avoids the pipe-buffer deadlock risk of
    reading one worker's output before the others finish, same reason `run_pipeline_multi.py`'s
    scratchpad prototype did this). Waits for every worker, never just the first failure, mirroring
    `app/ingest.py::_run_parse_phase_subprocesses`'s "a dead shard must not silently ship a
    partial corpus" ordering. Returns every worker's returncode and their combined log text (for
    `detect_oom`).
    """
    procs: list[tuple[subprocess.Popen, object, Path]] = []
    for i in range(n_workers):
        log_path = cwd / f"worker{i}.log"
        log_f = open(log_path, "w")
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "app.parse_phase",
                "--shard-index", str(i), "--shard-count", str(n_workers),
            ],
            cwd=cwd, stdout=log_f, stderr=subprocess.STDOUT,
        )
        procs.append((proc, log_f, log_path))

    returncodes = []
    for proc, log_f, _ in procs:
        returncodes.append(proc.wait())
        log_f.close()
    combined = "\n".join(log_path.read_text() for _, _, log_path in procs if log_path.exists())
    return returncodes, combined


WorkerRunner = Callable[[Path, int], tuple[list[int], str]]


def run_benchmark(
    *,
    config_name: str,
    base_config: Config,
    paper_ids: list[str],
    n_workers: int,
    scratch_dir: Path,
    run_worker: WorkerRunner = _run_worker_processes,
    query_gpu: Callable[[], GpuSample | None] = _query_gpu,
    poll_interval_s: float = _POLL_INTERVAL_SECONDS,
) -> BenchmarkResult:
    """Runs one config's full measurement: a discarded single-paper warm-up (control #3), then a
    GPU-sampled timed run over the whole fixed `paper_ids` corpus (control #4). Does NOT acquire
    the GPU lock or verify a clean baseline itself -- the CLI `__main__` below does both exactly
    once per invocation, wrapping a possible sweep of several `run_benchmark` calls (a decision
    table across configs) in one lock hold + one baseline check, not one per config.

    `run_worker`/`query_gpu` are injected (CONVENTIONS.md §2) purely as a test seam -- the real
    default is `_run_worker_processes`/`_query_gpu`.
    """
    total_pages = _total_pages(base_config.pdf_cache_dir, paper_ids)

    warmup_dir = scratch_dir / "warmup"
    _write_scratch_config(
        warmup_dir, base_config, paper_ids=paper_ids[:1], db_path="warmup.db",
        blob_dir="warmup_blobs",
    )
    warmup_rcs, warmup_out = run_worker(warmup_dir, 1)
    if any(rc != 0 for rc in warmup_rcs):
        raise BenchmarkError(
            f"{config_name}: warm-up run failed (returncodes={warmup_rcs}) -- cannot trust a "
            f"timed run after a failed warm-up:\n{warmup_out}"
        )

    timed_dir = scratch_dir / "timed"
    _write_scratch_config(
        timed_dir, base_config, paper_ids=paper_ids, db_path="timed.db", blob_dir="timed_blobs",
    )

    samples: list[GpuSample] = []
    stop_sampling = threading.Event()

    def _sample_loop() -> None:
        while not stop_sampling.is_set():
            sample = query_gpu()
            if sample is not None:
                samples.append(sample)
            stop_sampling.wait(poll_interval_s)

    sampler = threading.Thread(target=_sample_loop, daemon=True)
    sampler.start()
    t0 = time.monotonic()
    try:
        returncodes, combined_out = run_worker(timed_dir, n_workers)
    finally:
        stop_sampling.set()
        sampler.join(timeout=5.0)
    elapsed_s = time.monotonic() - t0

    if any(rc != 0 for rc in returncodes):
        if detect_oom(returncodes, combined_out):
            logger.warning(
                "%s: worker(s) OOM'd (returncodes=%s) -- config INVALIDATED, not scored",
                config_name, returncodes,
            )
            return BenchmarkResult(
                config_name=config_name, total_pages=total_pages, elapsed_s=elapsed_s,
                samples=samples, oom=True,
            )
        raise BenchmarkError(
            f"{config_name}: worker(s) failed (returncodes={returncodes}), no OOM signature "
            f"found -- not a config to retry automatically, see output:\n{combined_out}"
        )

    return BenchmarkResult(
        config_name=config_name, total_pages=total_pages, elapsed_s=elapsed_s, samples=samples,
        oom=False,
    )


# --- composition root -------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml", help="base config.yaml to copy levers from")
    parser.add_argument("--config-name", required=True, help="label for this run in the report")
    parser.add_argument("--paper-ids", required=True, help="comma-separated fixed paper-id corpus")
    parser.add_argument("--parse-workers", type=int, default=1)
    parser.add_argument("--scratch-dir", required=True, help="throwaway dir for scratch config/db/logs")
    parser.add_argument("--no-evict-tei", action="store_true", help="skip stopping TEI before verifying baseline")
    parser.add_argument("--out", default=None, help="write the JSON result here (else stdout only)")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    cfg = load_config(args.config)
    paper_ids = [p.strip() for p in args.paper_ids.split(",") if p.strip()]
    scratch_dir = Path(args.scratch_dir)

    with acquire_gpu_lock_or_fail(Path(cfg.gpu_lock_path)):
        verify_clean_gpu(evict_tei=not args.no_evict_tei)
        result = run_benchmark(
            config_name=args.config_name, base_config=cfg, paper_ids=paper_ids,
            n_workers=args.parse_workers, scratch_dir=scratch_dir,
        )

    print(result.to_dict())
    if args.out:
        Path(args.out).write_text(json.dumps(result.to_dict(), indent=2))
