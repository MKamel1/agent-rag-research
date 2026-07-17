"""Tests for `app.telemetry` (T-DOC47/T-DOC54) -- offline, no real GPU/subprocess/network.

Mirrors house patterns: `app/test_benchmark.py`'s monkeypatched-`subprocess.run` style for
`_query_gpu`, `app/test_doctor.py`'s note that stdlib-HTTP probes are tested by monkeypatching the
probe function itself at the call site that uses it (`query_point_count=`/`query_gpu=` injection
seams here), and a direct `urllib.request.urlopen` monkeypatch for `_query_vector_store_point_count`
itself (the one function whose own internals are worth a direct test).
"""

from __future__ import annotations

import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from app import telemetry
from migrations.migrate import migrate as real_migrate


# ---------------------------------------------------------------------------
# _query_gpu -- same shape as app/benchmark.py::_query_gpu, extended with power
# ---------------------------------------------------------------------------


def _fake_completed(stdout: str):
    return SimpleNamespace(stdout=stdout, returncode=0)


def test_query_gpu_parses_util_memory_and_power(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("45, 8192, 210.5\n"))
    reading = telemetry._query_gpu()
    assert reading.util_pct == 45
    assert reading.mem_used_mib == 8192
    assert reading.power_draw_w == pytest.approx(210.5)


def test_query_gpu_handles_unavailable_power_reading(monkeypatch):
    """Some cards report `power.draw` as `[N/A]` (no power sensor) -- that alone must not discard
    the whole sample, just leave power unset."""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("10, 500, [N/A]\n"))
    reading = telemetry._query_gpu()
    assert reading.util_pct == 10
    assert reading.mem_used_mib == 500
    assert reading.power_draw_w is None


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
    assert telemetry._query_gpu() is None


def test_query_gpu_returns_none_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed("garbage\n"))
    assert telemetry._query_gpu() is None


# ---------------------------------------------------------------------------
# GpuSampler -- start/stop background thread, tagged by current stage
# ---------------------------------------------------------------------------


def test_gpu_sampler_collects_samples_tagged_with_the_current_stage():
    sampler = telemetry.GpuSampler(
        poll_interval_s=0.01,
        query_gpu=lambda: telemetry.GpuReading(util_pct=50, mem_used_mib=1000, power_draw_w=100.0),
    )
    sampler.set_stage("parse")
    sampler.start()
    time.sleep(0.05)
    sampler.set_stage("finish")
    time.sleep(0.05)
    samples = sampler.stop()

    assert len(samples) >= 2
    stages_seen = {s.stage for s in samples}
    assert stages_seen <= {"parse", "finish"}
    assert "parse" in stages_seen and "finish" in stages_seen


def test_gpu_sampler_discards_failed_readings():
    sampler = telemetry.GpuSampler(poll_interval_s=0.01, query_gpu=lambda: None)
    sampler.start()
    time.sleep(0.05)
    samples = sampler.stop()
    assert samples == []


def test_gpu_sampler_stop_is_idempotent_and_returns_a_copy():
    sampler = telemetry.GpuSampler(
        poll_interval_s=0.01,
        query_gpu=lambda: telemetry.GpuReading(util_pct=0, mem_used_mib=0, power_draw_w=None),
    )
    sampler.start()
    time.sleep(0.03)
    first = sampler.stop()
    first.append("mutated-by-caller")  # must not affect the sampler's own internal list
    second = sampler.stop()
    assert "mutated-by-caller" not in second


# ---------------------------------------------------------------------------
# StageGpuStats / summarize_by_stage
# ---------------------------------------------------------------------------


def _sample(stage: str, util: int, mem: int, power: float | None = None) -> telemetry.GpuSample:
    return telemetry.GpuSample(epoch=0.0, stage=stage, util_pct=util, mem_used_mib=mem, power_draw_w=power)


def test_stage_gpu_stats_computes_averages_and_peak():
    samples = [_sample("parse", 0, 1000, 100.0), _sample("parse", 100, 2000, 200.0)]
    stats = telemetry.StageGpuStats.from_samples(samples)
    assert stats.avg_util_pct == pytest.approx(50.0)
    assert stats.pct_at_high_util == pytest.approx(50.0)
    assert stats.peak_vram_mib == 2000
    assert stats.avg_power_w == pytest.approx(150.0)
    assert stats.n_samples == 2


def test_stage_gpu_stats_empty_never_raises_zero_division():
    stats = telemetry.StageGpuStats.from_samples([])
    assert stats.avg_util_pct == 0.0
    assert stats.pct_at_high_util == 0.0
    assert stats.peak_vram_mib == 0
    assert stats.avg_power_w is None
    assert stats.n_samples == 0


def test_stage_gpu_stats_avg_power_none_when_no_reading_has_power():
    samples = [_sample("parse", 10, 100, None), _sample("parse", 20, 200, None)]
    stats = telemetry.StageGpuStats.from_samples(samples)
    assert stats.avg_power_w is None


def test_summarize_by_stage_groups_samples_by_stage_tag():
    samples = [_sample("parse", 10, 100), _sample("parse", 20, 200), _sample("finish", 90, 5000)]
    by_stage = telemetry.summarize_by_stage(samples)
    assert set(by_stage) == {"parse", "finish"}
    assert by_stage["parse"].n_samples == 2
    assert by_stage["finish"].n_samples == 1


# ---------------------------------------------------------------------------
# RunEventLog -- append-only JSON lines
# ---------------------------------------------------------------------------


def test_run_event_log_writes_one_json_object_per_line(tmp_path):
    path = tmp_path / "events.jsonl"
    log = telemetry.RunEventLog(path, run_id="abc123")

    log.emit("RUN_START", stage=None, paper_count=100)
    log.emit("STAGE_START", stage="parse")

    lines = path.read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event"] == "RUN_START"
    assert first["run_id"] == "abc123"
    assert first["paper_count"] == 100
    assert "ts" in first
    second = json.loads(lines[1])
    assert second["event"] == "STAGE_START"
    assert second["stage"] == "parse"


def test_run_event_log_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "events.jsonl"
    telemetry.RunEventLog(path, run_id="x")
    assert path.parent.is_dir()


def test_run_event_log_appends_across_multiple_instances(tmp_path):
    path = tmp_path / "events.jsonl"
    telemetry.RunEventLog(path, run_id="run1").emit("RUN_START")
    telemetry.RunEventLog(path, run_id="run1").emit("RUN_END")
    lines = path.read_text().splitlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# _query_vector_store_point_count -- stdlib urllib REST probe, vendor-neutral
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_query_vector_store_point_count_parses_a_healthy_response(monkeypatch):
    body = json.dumps({"result": {"points_count": 4321}, "status": "ok"}).encode()
    monkeypatch.setattr(telemetry.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(body))

    count = telemetry._query_vector_store_point_count("localhost", 6333, "papers")

    assert count == 4321


def test_query_vector_store_point_count_returns_none_on_connection_failure(monkeypatch):
    def raise_error(url, timeout=None):
        raise telemetry.urllib.error.URLError("connection refused")

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", raise_error)

    assert telemetry._query_vector_store_point_count("localhost", 6333, "papers") is None


def test_query_vector_store_point_count_returns_none_on_unexpected_shape(monkeypatch):
    body = json.dumps({"unexpected": "shape"}).encode()
    monkeypatch.setattr(telemetry.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(body))

    assert telemetry._query_vector_store_point_count("localhost", 6333, "papers") is None


def test_query_vector_store_point_count_returns_none_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        telemetry.urllib.request, "urlopen", lambda url, timeout=None: _FakeResponse(b"not json")
    )
    assert telemetry._query_vector_store_point_count("localhost", 6333, "papers") is None


# ---------------------------------------------------------------------------
# summarize_run -- end-of-run report (OG-7) against a real migrated SQLite db
# ---------------------------------------------------------------------------


def _seed_db(db_path: str, *, done_ids=(), quarantined=()):
    import sqlite3

    real_migrate(db_path)
    conn = sqlite3.connect(db_path)
    try:
        for paper_id in done_ids:
            conn.execute(
                "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, 'done', '2026-01-01')",
                (paper_id,),
            )
        for paper_id, error_type in quarantined:
            conn.execute(
                "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, 'parsed', 'boom', '2026-01-01')",
                (paper_id,),
            )
            conn.execute(
                "INSERT INTO quarantine_diagnostics (paper_id, error_type, diagnostics_json) VALUES (?, ?, NULL)",
                (paper_id, error_type),
            )
        conn.commit()
    finally:
        conn.close()


def test_summarize_run_counts_done_and_quarantined_with_reasons(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(
        db_path,
        done_ids=["a", "b", "c"],
        quarantined=[("d", "PermanentError"), ("e", "PermanentError"), ("f", "TransientError")],
    )

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=3600.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: 999,
    )

    assert summary.n_done == 3
    assert summary.n_quarantined == 3
    assert summary.quarantine_reasons == {"PermanentError": 2, "TransientError": 1}
    assert summary.papers_per_hour == pytest.approx(3.0)


def test_summarize_run_zero_wall_clock_never_divides_by_zero(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, done_ids=["a"])

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=0.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: 10,
    )

    assert summary.papers_per_hour == 0.0


def test_summarize_run_consistent_when_vector_store_has_points_for_done_papers(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, done_ids=["a", "b"])

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=10.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: 50,
    )

    assert summary.consistent is True
    assert summary.vector_store_point_count == 50


def test_summarize_run_flags_mismatch_when_done_papers_have_zero_points(tmp_path):
    """The exact OG-16/T-DOC35 failure class: papers marked 'done' with zero vectors stored."""
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, done_ids=["a", "b"])

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=10.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: 0,
    )

    assert summary.consistent is False


def test_summarize_run_unknown_when_vector_store_probe_fails(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, done_ids=["a"])

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=10.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: None,
    )

    assert summary.consistent is None
    assert summary.vector_store_point_count is None


def test_summarize_run_survives_a_missing_database(tmp_path):
    """Runs from a `finally` block in app.ingest, possibly after the run's own real failure --
    an unreadable DB must degrade to a zeroed report, never raise and mask the original error."""
    db_path = str(tmp_path / "does_not_exist" / "papers.db")

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=10.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: None,
    )

    assert summary.n_done == 0
    assert summary.n_quarantined == 0


def test_run_summary_format_includes_key_fields(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, done_ids=["a"], quarantined=[("b", "PermanentError")])

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=3600.0, collection="papers", gpu_samples=[_sample("parse", 80, 9000, 250.0)],
        run_id="run-xyz", query_point_count=lambda host, port, collection: 5,
    )
    text = summary.format()

    assert "run-xyz" in text
    assert "done: 1" in text
    assert "quarantined: 1" in text
    assert "PermanentError=1" in text
    assert "papers/hour: 1.0" in text
    assert "OK" in text
    assert "[parse]" in text


# ---------------------------------------------------------------------------
# RunTelemetry -- full composition: events + sampler + summary, one run id
# ---------------------------------------------------------------------------


def test_run_telemetry_emits_run_start_stage_and_run_end_events(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, done_ids=["a"])
    events_path = tmp_path / "events.jsonl"

    run = telemetry.RunTelemetry.start(
        events_path=str(events_path), poll_interval_s=0.01,
        requested_paper_count=1, query_gpu=lambda: None,
    )
    run.stage_start("parse")
    run.stage_end("parse")
    run.stage_start("finish")
    run.stage_end("finish")
    summary = run.finish(
        db_path=db_path, collection="papers",
        query_point_count=lambda host, port, collection: 10,
    )

    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    event_names = [e["event"] for e in events]
    assert event_names == ["RUN_START", "STAGE_START", "STAGE_END", "STAGE_START", "STAGE_END", "RUN_END"]
    assert all(e["run_id"] == run.run_id for e in events)
    assert events[1]["stage"] == "parse"
    assert events[3]["stage"] == "finish"
    assert events[-1]["n_done"] == 1
    assert summary.n_done == 1


def test_run_telemetry_stops_the_sampler_on_finish(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path)
    events_path = tmp_path / "events.jsonl"

    reading = telemetry.GpuReading(util_pct=77, mem_used_mib=1234, power_draw_w=None)
    run = telemetry.RunTelemetry.start(
        events_path=str(events_path), poll_interval_s=0.01, query_gpu=lambda: reading,
    )
    run.stage_start("parse")
    time.sleep(0.05)
    run.stage_end("parse")
    summary = run.finish(
        db_path=db_path, collection="papers",
        query_point_count=lambda host, port, collection: None,
    )

    assert "parse" in summary.gpu_by_stage
    assert summary.gpu_by_stage["parse"].n_samples >= 1
    assert summary.gpu_by_stage["parse"].avg_util_pct == pytest.approx(77.0)


def test_run_telemetry_set_stage_retags_the_sampler_without_an_event(tmp_path):
    """T-DOC59 (OG-25): `set_stage` re-tags the running GPU sampler for a finer sub-stage boundary
    INSIDE an already-started coarse stage -- this is what `app/ingest.py` wires
    `rag/orchestrator.py`'s per-paper `on_stage` hook to, so "finish" splits into "summarize"/
    "embed"/"store" in the end-of-run per-stage GPU report. Unlike `stage_start`/`stage_end`, it
    must NOT emit a STAGE_START/STAGE_END event pair -- that would flood the event log with one
    pair per paper for no benefit the existing coarse "finish" pair doesn't already give.
    """
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path)
    events_path = tmp_path / "events.jsonl"
    reading = telemetry.GpuReading(util_pct=42, mem_used_mib=2000, power_draw_w=None)

    run = telemetry.RunTelemetry.start(
        events_path=str(events_path), poll_interval_s=0.01, query_gpu=lambda: reading,
    )
    run.stage_start("finish")
    run.set_stage("summarize")
    time.sleep(0.05)
    run.set_stage("embed")
    time.sleep(0.05)
    run.stage_end("finish")
    summary = run.finish(
        db_path=db_path, collection="papers",
        query_point_count=lambda host, port, collection: None,
    )

    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    event_names = [e["event"] for e in events]
    assert event_names == ["RUN_START", "STAGE_START", "STAGE_END", "RUN_END"], (
        "set_stage() must not add STAGE_START/STAGE_END events of its own"
    )
    assert "summarize" in summary.gpu_by_stage
    assert "embed" in summary.gpu_by_stage
    assert "finish" not in summary.gpu_by_stage, (
        "every sample after the first set_stage() call must carry the finer tag, not \"finish\""
    )
