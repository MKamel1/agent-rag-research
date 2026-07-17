"""Tests for `app.benchmark` (T-DOC55) -- offline, no real GPU/subprocess/network.

Mirrors house patterns: `app/test_gpu_headroom.py`'s monkeypatched-`subprocess.run` style for
`_query_gpu`, `rag/test_gpu_lock.py`'s real-`tmp_path`-`filelock` style for the lock, and
`app/test_parse_phase.py`'s pulled-out-of-`__main__` seam style for `run_benchmark`'s injected
`run_worker`/`query_gpu`.
"""

from __future__ import annotations

import io
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import filelock
import pypdfium2 as pdfium
import pytest
import yaml

from app.benchmark import (
    BenchmarkError,
    BenchmarkResult,
    GpuSample,
    _query_gpu,
    _total_pages,
    _write_scratch_config,
    acquire_gpu_lock_or_fail,
    detect_oom,
    run_benchmark,
    verify_clean_gpu,
)
import app.benchmark as benchmark_mod
from contracts.config import Config


def _make_pdf(path: Path, n_pages: int) -> None:
    doc = pdfium.PdfDocument.new()
    for _ in range(n_pages):
        doc.new_page(200, 300)
    buf = io.BytesIO()
    doc.save(buf)
    path.write_bytes(buf.getvalue())


def _base_config(**overrides) -> Config:
    data = {"focus_area_queries": ["causal inference"]}
    data.update(overrides)
    return Config(**data)


# ---------------------------------------------------------------------------
# acquire_gpu_lock_or_fail -- control #1, the load-bearing test the ticket asks for
# ---------------------------------------------------------------------------


def test_acquire_gpu_lock_enters_and_exits_cleanly(tmp_path):
    lock_path = tmp_path / "gpu.lock"
    with acquire_gpu_lock_or_fail(lock_path):
        pass  # entering/exiting without error is the whole assertion


def test_acquire_gpu_lock_releases_on_exception(tmp_path):
    lock_path = tmp_path / "gpu.lock"
    with pytest.raises(ValueError):
        with acquire_gpu_lock_or_fail(lock_path):
            raise ValueError("boom")
    # a fresh raw FileLock on the same path can acquire immediately -- proves release happened
    fresh = filelock.FileLock(str(lock_path))
    with fresh.acquire(timeout=0):
        pass


def test_second_concurrent_benchmark_fails_fast_when_lock_is_held(tmp_path):
    """The load-bearing property T-DOC55 exists for: two benchmarks must never run concurrently
    on the one GPU. The second attempt must fail immediately (not queue/block)."""
    lock_path = tmp_path / "gpu.lock"
    with acquire_gpu_lock_or_fail(lock_path):
        start = time.monotonic()
        with pytest.raises(BenchmarkError, match="already held"):
            with acquire_gpu_lock_or_fail(lock_path):
                pytest.fail("must never enter -- lock is held by the outer benchmark")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, "must fail fast (timeout=0), not block waiting for the lock"

    # after the first releases, a second acquire succeeds cleanly
    with acquire_gpu_lock_or_fail(lock_path):
        pass


def test_different_lock_paths_do_not_contend(tmp_path):
    a = tmp_path / "a.lock"
    b = tmp_path / "b.lock"
    with acquire_gpu_lock_or_fail(a):
        with acquire_gpu_lock_or_fail(b):  # different file -- must not raise
            pass


# ---------------------------------------------------------------------------
# _query_gpu -- same shape as app/gpu_headroom.py::free_vram_mib
# ---------------------------------------------------------------------------


def _fake_completed(stdout: str):
    return SimpleNamespace(stdout=stdout, returncode=0)


def test_query_gpu_parses_util_and_memory(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("45, 8192\n"))
    sample = _query_gpu()
    assert sample.util_pct == 45
    assert sample.mem_used_mib == 8192


def test_query_gpu_invokes_the_expected_nvidia_smi_command(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _fake_completed("0, 100\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _query_gpu()
    assert calls == [
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"]
    ]


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "nvidia-smi"),
        subprocess.TimeoutExpired("nvidia-smi", 10.0),
        FileNotFoundError("no nvidia-smi"),
    ],
)
def test_query_gpu_returns_none_on_subprocess_failure(monkeypatch, error):
    def raise_error(*a, **k):
        raise error

    monkeypatch.setattr(subprocess, "run", raise_error)
    assert _query_gpu() is None


def test_query_gpu_returns_none_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("garbage\n"))
    assert _query_gpu() is None


# ---------------------------------------------------------------------------
# verify_clean_gpu -- control #2
# ---------------------------------------------------------------------------


def test_verify_clean_gpu_passes_on_a_true_baseline(monkeypatch):
    monkeypatch.setattr(benchmark_mod.tei_lifecycle, "stop_tei_containers", lambda: None)
    verify_clean_gpu(query_gpu=lambda: GpuSample(epoch=0.0, util_pct=0, mem_used_mib=100))


def test_verify_clean_gpu_raises_on_a_dirty_baseline(monkeypatch):
    monkeypatch.setattr(benchmark_mod.tei_lifecycle, "stop_tei_containers", lambda: None)
    with pytest.raises(BenchmarkError, match="is not at a clean baseline"):
        verify_clean_gpu(query_gpu=lambda: GpuSample(epoch=0.0, util_pct=10, mem_used_mib=9000))


def test_verify_clean_gpu_raises_when_no_reading_is_available(monkeypatch):
    monkeypatch.setattr(benchmark_mod.tei_lifecycle, "stop_tei_containers", lambda: None)
    with pytest.raises(BenchmarkError, match="could not read"):
        verify_clean_gpu(query_gpu=lambda: None)


def test_verify_clean_gpu_evicts_tei_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(benchmark_mod.tei_lifecycle, "stop_tei_containers", lambda: calls.append(1))
    verify_clean_gpu(query_gpu=lambda: GpuSample(epoch=0.0, util_pct=0, mem_used_mib=0))
    assert calls == [1]


def test_verify_clean_gpu_skips_eviction_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(benchmark_mod.tei_lifecycle, "stop_tei_containers", lambda: calls.append(1))
    verify_clean_gpu(evict_tei=False, query_gpu=lambda: GpuSample(epoch=0.0, util_pct=0, mem_used_mib=0))
    assert calls == []


# ---------------------------------------------------------------------------
# detect_oom -- the config-D trap
# ---------------------------------------------------------------------------


def test_detect_oom_false_when_every_worker_exits_zero():
    assert detect_oom([0, 0, 0], "all good") is False


def test_detect_oom_true_on_a_recognized_cuda_oom_signature():
    assert detect_oom([0, 1, 0], "worker1: RuntimeError: CUDA out of memory. Tried to allocate...") is True


def test_detect_oom_false_on_a_non_oom_crash():
    assert detect_oom([1, 0, 0], "worker0: FileNotFoundError: missing pdf") is False


# ---------------------------------------------------------------------------
# BenchmarkResult -- normalized output (control #4)
# ---------------------------------------------------------------------------


def _samples(*util_mem_pairs: tuple[int, int]) -> list[GpuSample]:
    return [GpuSample(epoch=float(i), util_pct=u, mem_used_mib=m) for i, (u, m) in enumerate(util_mem_pairs)]


def test_pages_per_minute_computed_correctly():
    result = BenchmarkResult(config_name="c", total_pages=488, elapsed_s=104.4, samples=[])
    assert result.pages_per_minute == pytest.approx(488 / (104.4 / 60.0))


def test_pages_per_minute_simple_round_number():
    result = BenchmarkResult(config_name="c", total_pages=100, elapsed_s=60.0, samples=[])
    assert result.pages_per_minute == pytest.approx(100.0)


def test_pages_per_minute_zero_when_oom():
    result = BenchmarkResult(config_name="c", total_pages=488, elapsed_s=1.0, samples=[], oom=True)
    assert result.pages_per_minute == 0.0


def test_pages_per_minute_zero_when_elapsed_not_positive():
    result = BenchmarkResult(config_name="c", total_pages=100, elapsed_s=0.0, samples=[])
    assert result.pages_per_minute == 0.0


def test_avg_util_and_percentiles():
    samples = _samples((0, 1000), (0, 1000), (50, 2000), (95, 3000))
    result = BenchmarkResult(config_name="c", total_pages=10, elapsed_s=10.0, samples=samples)
    assert result.avg_util_pct == pytest.approx((0 + 0 + 50 + 95) / 4)
    assert result.pct_at_zero == pytest.approx(50.0)
    assert result.pct_at_high_util == pytest.approx(25.0)
    assert result.peak_vram_mib == 3000


def test_oom_result_reports_all_zero_metrics_even_with_samples():
    samples = _samples((90, 20000), (95, 21000))
    result = BenchmarkResult(config_name="c", total_pages=10, elapsed_s=5.0, samples=samples, oom=True)
    assert result.avg_util_pct == 0.0
    assert result.pct_at_zero == 0.0
    assert result.pct_at_high_util == 0.0
    assert result.peak_vram_mib == 0
    assert result.pages_per_minute == 0.0


def test_empty_samples_never_raise_zero_division():
    result = BenchmarkResult(config_name="c", total_pages=10, elapsed_s=5.0, samples=[])
    assert result.avg_util_pct == 0.0
    assert result.pct_at_zero == 0.0
    assert result.pct_at_high_util == 0.0
    assert result.peak_vram_mib == 0


def test_to_dict_shape():
    result = BenchmarkResult(config_name="3-workers", total_pages=488, elapsed_s=104.4, samples=_samples((70, 19800)))
    d = result.to_dict()
    assert d["config_name"] == "3-workers"
    assert d["total_pages"] == 488
    assert d["oom"] is False
    assert set(d) == {
        "config_name", "total_pages", "elapsed_s", "oom", "avg_util_pct", "pct_at_zero",
        "pct_at_high_util", "peak_vram_mib", "pages_per_minute", "n_samples",
    }


# ---------------------------------------------------------------------------
# _total_pages -- fixed-corpus normalization input
# ---------------------------------------------------------------------------


def test_total_pages_sums_real_page_counts(tmp_path):
    _make_pdf(tmp_path / "2601.00001.pdf", 3)
    _make_pdf(tmp_path / "2601.00002.pdf", 5)
    assert _total_pages(str(tmp_path), ["2601.00001", "2601.00002"]) == 8


def test_total_pages_single_paper(tmp_path):
    _make_pdf(tmp_path / "2601.00001.pdf", 1)
    assert _total_pages(str(tmp_path), ["2601.00001"]) == 1


# ---------------------------------------------------------------------------
# _write_scratch_config -- fixed-corpus wiring into a throwaway config.yaml
# ---------------------------------------------------------------------------


def test_write_scratch_config_overrides_ids_and_storage_paths_only(tmp_path):
    base = _base_config(gpu_lock_path=".custom.gpu.lock", corpus_cap=42)
    dest = tmp_path / "scratch"
    _write_scratch_config(dest, base, paper_ids=["a", "b"], db_path="t.db", blob_dir="t_blobs")

    written = yaml.safe_load((dest / "config.yaml").read_text())
    assert written["ingest_paper_ids"] == ["a", "b"]
    assert written["db_path"] == str(dest / "t.db")
    assert written["blob_dir"] == str(dest / "t_blobs")
    # everything else carried over from base_config unchanged
    assert written["gpu_lock_path"] == ".custom.gpu.lock"
    assert written["corpus_cap"] == 42
    assert written["focus_area_queries"] == ["causal inference"]


# ---------------------------------------------------------------------------
# run_benchmark -- warm-up-then-time (control #3) + OOM invalidation (control #4)
# ---------------------------------------------------------------------------


def _pdf_cache_config(tmp_path, paper_ids, n_pages_each=2):
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    for pid in paper_ids:
        _make_pdf(cache_dir / f"{pid}.pdf", n_pages_each)
    return _base_config(pdf_cache_dir=str(cache_dir))


def test_run_benchmark_excludes_warmup_from_reported_elapsed_time(tmp_path):
    """The exact confound OG-20 names: model-init time must never contaminate the steady-state
    number. A slow discarded warm-up must not show up in `elapsed_s`."""
    paper_ids = ["p1", "p2"]
    cfg = _pdf_cache_config(tmp_path, paper_ids)
    calls = []

    def fake_run_worker(cwd, n_workers):
        calls.append((cwd, n_workers))
        if len(calls) == 1:
            time.sleep(0.2)  # warm-up -- slow, must be discarded
        else:
            time.sleep(0.02)  # timed run -- fast, must be what's reported
        return [0] * n_workers, "ok"

    result = run_benchmark(
        config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=1,
        scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
        query_gpu=lambda: None, poll_interval_s=0.01,
    )

    assert len(calls) == 2, "must run exactly one warm-up call then one timed call"
    assert result.elapsed_s < 0.15, (
        f"elapsed_s={result.elapsed_s} must reflect only the fast timed run, not the slow warm-up"
    )


def test_run_benchmark_warmup_uses_only_the_first_paper_id(tmp_path):
    paper_ids = ["p1", "p2", "p3"]
    cfg = _pdf_cache_config(tmp_path, paper_ids)
    seen_dirs = []

    def fake_run_worker(cwd, n_workers):
        seen_dirs.append(Path(cwd))
        return [0] * n_workers, "ok"

    run_benchmark(
        config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=2,
        scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
        query_gpu=lambda: None, poll_interval_s=0.01,
    )

    warmup_dir, timed_dir = seen_dirs
    warmup_cfg = yaml.safe_load((warmup_dir / "config.yaml").read_text())
    timed_cfg = yaml.safe_load((timed_dir / "config.yaml").read_text())
    assert warmup_cfg["ingest_paper_ids"] == ["p1"]
    assert timed_cfg["ingest_paper_ids"] == ["p1", "p2", "p3"]


def test_run_benchmark_marks_oom_and_invalidates_the_result(tmp_path):
    """The config-D trap: a worker that OOM'd must never be scored as a fast result."""
    paper_ids = ["p1"]
    cfg = _pdf_cache_config(tmp_path, paper_ids)

    def fake_run_worker(cwd, n_workers):
        if "warmup" in str(cwd):
            return [0] * n_workers, "ok"
        return [1] + [0] * (n_workers - 1), "worker0: CUDA out of memory. Tried to allocate 2GiB"

    result = run_benchmark(
        config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=3,
        scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
        query_gpu=lambda: GpuSample(epoch=0.0, util_pct=99, mem_used_mib=23000),
        poll_interval_s=0.01,
    )

    assert result.oom is True
    assert result.pages_per_minute == 0.0, "an OOM'd config must never report a scorable number"


def test_run_benchmark_raises_on_a_non_oom_worker_failure(tmp_path):
    paper_ids = ["p1"]
    cfg = _pdf_cache_config(tmp_path, paper_ids)

    def fake_run_worker(cwd, n_workers):
        if "warmup" in str(cwd):
            return [0] * n_workers, "ok"
        return [1], "worker0: FileNotFoundError: no such pdf"

    with pytest.raises(BenchmarkError, match="no OOM signature"):
        run_benchmark(
            config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=1,
            scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
            query_gpu=lambda: None, poll_interval_s=0.01,
        )


def test_run_benchmark_raises_when_warmup_itself_fails_and_never_runs_the_timed_phase(tmp_path):
    paper_ids = ["p1"]
    cfg = _pdf_cache_config(tmp_path, paper_ids)
    calls = []

    def fake_run_worker(cwd, n_workers):
        calls.append(cwd)
        return [1], "boom"

    with pytest.raises(BenchmarkError, match="warm-up run failed"):
        run_benchmark(
            config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=1,
            scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
            query_gpu=lambda: None, poll_interval_s=0.01,
        )

    assert len(calls) == 1, "the timed phase must never run after a failed warm-up"


def test_run_benchmark_computes_total_pages_from_the_fixed_corpus(tmp_path):
    paper_ids = ["p1", "p2", "p3"]
    cfg = _pdf_cache_config(tmp_path, paper_ids, n_pages_each=4)

    def fake_run_worker(cwd, n_workers):
        return [0] * n_workers, "ok"

    result = run_benchmark(
        config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=1,
        scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
        query_gpu=lambda: None, poll_interval_s=0.01,
    )

    assert result.total_pages == 12


def test_run_benchmark_samples_gpu_util_during_the_timed_run(tmp_path):
    paper_ids = ["p1"]
    cfg = _pdf_cache_config(tmp_path, paper_ids)

    def fake_run_worker(cwd, n_workers):
        time.sleep(0.05)
        return [0] * n_workers, "ok"

    result = run_benchmark(
        config_name="c", base_config=cfg, paper_ids=paper_ids, n_workers=1,
        scratch_dir=tmp_path / "scratch", run_worker=fake_run_worker,
        query_gpu=lambda: GpuSample(epoch=0.0, util_pct=80, mem_used_mib=5000),
        poll_interval_s=0.01,
    )

    assert len(result.samples) >= 1
    assert all(s.util_pct == 80 for s in result.samples)
