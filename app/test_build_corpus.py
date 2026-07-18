"""Tests for `app.build_corpus` -- offline, no real GPU/network/ingest/prefetch subprocess.

`build_to_target`'s own tests drive it against fakes for every injected seam (`ensure_prefetch`,
`run_ingest`, `cached_not_done`, `done_count`, `sleep`) -- same style as
`app/test_prefetch_pdfs.py`'s `prefetch_loop` tests. `cached_not_done`/`done_count` get their own
tests against a real (temp) sqlite db (`migrations.migrate`), same pattern as
`app/test_prefetch_pdfs.py`'s dedup tests. `ensure_prefetch_running` gets its own tests against a
real (but harmless) OS process, same pattern as `app/dashboard/test_controller.py`.
"""

import logging
import os
import signal
import subprocess
from pathlib import Path

from app.build_corpus import (
    _DEFAULT_MAX_IDLE,
    _is_live_prefetch,
    _prefetch_pid_path,
    build_to_target,
    cached_not_done,
    done_count,
    ensure_prefetch_running,
)
from migrations.migrate import migrate
from rag.ingest_state_sqlite import SqliteIngestState

# ================================================================================================
# cached_not_done / done_count -- cache-first to-do list = pdf_cache/*.pdf minus stage='done'.
# ================================================================================================


def test_cached_not_done_is_cached_pdfs_minus_done(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    for paper_id in ("2601.00001", "2601.00002", "2601.00003"):
        (cache_dir / f"{paper_id}.pdf").write_bytes(b"%PDF-fake")

    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00002", "done")
    state.checkpoint("2601.00003", "parsed")  # cached, in progress, NOT done -- still on the list

    assert cached_not_done(cache_dir, db_path) == ["2601.00001", "2601.00003"]


def test_cached_not_done_is_sorted_and_stable(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    for paper_id in ("2601.00099", "2601.00001", "2601.00050"):
        (cache_dir / f"{paper_id}.pdf").write_bytes(b"%PDF-fake")

    assert cached_not_done(cache_dir, db_path) == ["2601.00001", "2601.00050", "2601.00099"]


def test_cached_not_done_empty_cache_returns_empty_list(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    assert cached_not_done(cache_dir, db_path) == []


def test_cached_not_done_tolerates_a_db_that_does_not_exist_yet(tmp_path):
    """A build's very first pass can run before `papers.db` exists -- must degrade to "nothing
    done yet", not raise."""
    cache_dir = tmp_path / "pdf_cache"
    cache_dir.mkdir()
    (cache_dir / "2601.00001.pdf").write_bytes(b"%PDF-fake")
    assert cached_not_done(cache_dir, str(tmp_path / "no_such.db")) == ["2601.00001"]


def test_done_count_counts_only_done_stage(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00001", "done")
    state.checkpoint("2601.00002", "done")
    state.checkpoint("2601.00003", "parsed")
    assert done_count(db_path) == 2


def test_done_count_of_missing_db_is_zero(tmp_path):
    assert done_count(str(tmp_path / "no_such.db")) == 0


# ================================================================================================
# ensure_prefetch_running -- reuse a live downloader, never launch a duplicate.
# ================================================================================================


def _cleanup_pid(pid):
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _alive_ignoring_cmdline(pid: int) -> bool:
    """Stands in for `_is_live_prefetch` in tests that spawn a harmless `sleep` process instead of
    a real `app.prefetch_pdfs` (whose cmdline the real check would correctly reject) -- these tests
    care about the reuse/launch DECISION, not the cmdline-matching mechanics (covered separately by
    `test_is_live_prefetch_*` below)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_ensure_prefetch_running_launches_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.build_corpus._is_live_prefetch", _alive_ignoring_cmdline)
    spawned = []

    def fake_spawn(data_dir):
        proc = subprocess.Popen(["sleep", "100"])
        spawned.append(proc.pid)
        return proc.pid

    try:
        alive = ensure_prefetch_running(tmp_path, spawn=fake_spawn)
        assert len(spawned) == 1
        assert _prefetch_pid_path(tmp_path).read_text().strip() == str(spawned[0])
        assert alive() is True
    finally:
        for pid in spawned:
            _cleanup_pid(pid)


def test_ensure_prefetch_running_reuses_an_existing_live_downloader(tmp_path, monkeypatch):
    """A live process whose cmdline names app.prefetch_pdfs must be reused, not duplicated."""
    proc = subprocess.Popen(["sleep", "100"])
    try:
        monkeypatch.setattr(
            "app.build_corpus._is_live_prefetch",
            lambda pid: pid == proc.pid,
        )
        _prefetch_pid_path(tmp_path).write_text(str(proc.pid))

        def fail_spawn(data_dir):
            raise AssertionError("must not launch a second downloader when one is already live")

        alive = ensure_prefetch_running(tmp_path, spawn=fail_spawn)
        assert alive() is True
    finally:
        _cleanup_pid(proc.pid)


def test_ensure_prefetch_running_replaces_a_dead_pid_file(tmp_path, monkeypatch):
    """A stale prefetch.pid (process no longer alive, or alive but not actually prefetch_pdfs)
    must not be trusted -- a fresh downloader is launched instead."""
    monkeypatch.setattr("app.build_corpus._is_live_prefetch", _alive_ignoring_cmdline)
    _prefetch_pid_path(tmp_path).write_text("999999999")  # not a real pid
    spawned = []

    def fake_spawn(data_dir):
        proc = subprocess.Popen(["sleep", "100"])
        spawned.append(proc.pid)
        return proc.pid

    try:
        alive = ensure_prefetch_running(tmp_path, spawn=fake_spawn)
        assert len(spawned) == 1
        assert alive() is True
    finally:
        for pid in spawned:
            _cleanup_pid(pid)


def test_is_live_prefetch_false_for_a_process_whose_cmdline_does_not_name_prefetch(tmp_path):
    """Guards against a recycled PID that happens to be some unrelated live process -- alive alone
    is not enough, the cmdline must actually name app.prefetch_pdfs."""
    proc = subprocess.Popen(["sleep", "100"])
    try:
        assert _is_live_prefetch(proc.pid) is False  # cmdline is "sleep 100", not prefetch_pdfs
    finally:
        _cleanup_pid(proc.pid)


def test_is_live_prefetch_false_for_a_dead_pid():
    assert _is_live_prefetch(999999999) is False


# ================================================================================================
# build_to_target -- the loop itself, fully faked (no real subprocess/GPU/network/sleep).
# ================================================================================================


def _fake_ensure_prefetch(alive=True):
    def ensure_prefetch(data_dir):
        return lambda: alive
    return ensure_prefetch


def test_build_to_target_reaches_target_over_several_iterations(tmp_path, caplog):
    """Each fake ingest run "processes" its whole batch (moves those ids from cached-not-done to
    done) -- the loop must keep going, batch after batch, until done_count reaches target."""
    all_ids = [f"2601.{i:05d}" for i in range(9)]
    done: set[str] = set()
    batches_run = []

    def fake_cached_not_done(cache_dir, db_path):
        return sorted(set(all_ids) - done)

    def fake_done_count(db_path):
        return len(done)

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        ids = [line for line in batch_file.read_text().splitlines() if line]
        batches_run.append(ids)
        done.update(ids[:3])  # only 3 "complete" per batch -- forces multiple iterations

    with caplog.at_level(logging.INFO):
        build_to_target(
            tmp_path, "db", Path("cache"), target=9, parse_workers=2, events_path=Path("events"),
            ensure_prefetch=_fake_ensure_prefetch(alive=True),
            run_ingest=fake_run_ingest,
            cached_not_done=fake_cached_not_done,
            done_count=fake_done_count,
            sleep=lambda s: None,
        )

    assert len(done) == 9
    assert len(batches_run) == 3  # 9 ids, 3 completed per batch -> 3 iterations
    assert "reached target -- 9/9 done" in caplog.text


def test_build_to_target_writes_batch_ids_file_and_passes_it_to_run_ingest(tmp_path):
    seen_batch_files = []
    state = {"ingested": False}

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        seen_batch_files.append(batch_file)
        assert batch_file.parent == data_dir
        assert batch_file.read_text().splitlines() == ["2601.00001", "2601.00002"]
        state["ingested"] = True

    def fake_cached_not_done(cache_dir, db_path):
        return [] if state["ingested"] else ["2601.00001", "2601.00002"]

    def fake_done_count(db_path):
        return 2 if state["ingested"] else 0

    build_to_target(
        tmp_path, "db", Path("cache"), target=2, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=fake_done_count,
        sleep=lambda s: None,
    )
    assert len(seen_batch_files) == 1
    assert seen_batch_files[0].exists()


def test_build_to_target_stops_when_cache_exhausted_and_prefetch_dead(tmp_path, caplog):
    def fake_run_ingest(*a, **k):
        raise AssertionError("must not ingest anything -- cache is empty")

    with caplog.at_level(logging.INFO):
        build_to_target(
            tmp_path, "db", Path("cache"), target=100, parse_workers=1, events_path=Path("events"),
            ensure_prefetch=_fake_ensure_prefetch(alive=False),
            run_ingest=fake_run_ingest,
            cached_not_done=lambda cache_dir, db_path: [],
            done_count=lambda db_path: 5,
            sleep=lambda s: None,
        )

    assert (
        "cache exhausted and the downloader has stopped -- stopping short at 5/100" in caplog.text
    )


def test_build_to_target_waits_when_caught_up_but_prefetch_still_alive(caplog, tmp_path):
    """Cache momentarily empty but the downloader is still working -- sleep and re-check, don't
    give up, and don't treat it as the terminal "exhausted" condition."""
    empty_calls = {"n": 0}
    state = {"ingested": False}
    sleeps = []

    def fake_cached_not_done(cache_dir, db_path):
        if state["ingested"]:
            return []
        empty_calls["n"] += 1
        return ["2601.00001"] if empty_calls["n"] > 2 else []  # found on the 3rd check

    def fake_done_count(db_path):
        return 1 if state["ingested"] else 0

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        state["ingested"] = True  # simulate success; done_count() now reports target reached

    with caplog.at_level(logging.INFO):
        build_to_target(
            tmp_path, "db", Path("cache"), target=1, parse_workers=1, events_path=Path("events"),
            ensure_prefetch=_fake_ensure_prefetch(alive=True),
            run_ingest=fake_run_ingest,
            cached_not_done=fake_cached_not_done,
            done_count=fake_done_count,
            sleep=sleeps.append,
            poll_interval_s=42.0,
        )

    assert sleeps == [42.0, 42.0]  # exactly the 2 caught-up passes before the batch showed up
    assert "caught up with the cache" in caplog.text


def test_build_to_target_idle_guard_trips_after_max_idle_consecutive_waits(caplog, tmp_path):
    def fake_run_ingest(*a, **k):
        raise AssertionError("must never ingest -- cache never produces anything")

    sleeps = []
    with caplog.at_level(logging.INFO):
        build_to_target(
            tmp_path, "db", Path("cache"), target=100, parse_workers=1, events_path=Path("events"),
            ensure_prefetch=_fake_ensure_prefetch(alive=True),
            run_ingest=fake_run_ingest,
            cached_not_done=lambda cache_dir, db_path: [],
            done_count=lambda db_path: 0,
            sleep=sleeps.append,
            max_idle=3,
        )

    assert len(sleeps) == 2  # the max_idle-th idle pass stops immediately, no pointless sleep
    assert "stalled -- 0/100 done, no new cached papers after 3 consecutive idle" in caplog.text


def test_build_to_target_default_max_idle_matches_module_constant():
    assert _DEFAULT_MAX_IDLE > 0  # sanity: the default guard is actually bounded, not unbounded


def test_build_to_target_batch_size_caps_ids_per_iteration(tmp_path):
    seen = []
    state = {"ingested": False}

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        seen.append(batch_file.read_text().splitlines())
        state["ingested"] = True

    def fake_cached_not_done(cache_dir, db_path):
        return [] if state["ingested"] else ["a", "b", "c", "d", "e"]

    def fake_done_count(db_path):
        return 100 if state["ingested"] else 0  # done after the one batch this test cares about

    build_to_target(
        tmp_path, "db", Path("cache"), target=100, parse_workers=1, events_path=Path("events"),
        batch_size=2,
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=fake_done_count,
        sleep=lambda s: None,
    )
    assert seen == [["a", "b"]]


def test_build_to_target_calls_ensure_prefetch_exactly_once(tmp_path):
    """`ensure_prefetch` launches/adopts the downloader once up front -- not re-checked/re-launched
    every loop iteration."""
    calls = {"n": 0}

    def ensure_prefetch(data_dir):
        calls["n"] += 1
        return lambda: True

    build_to_target(
        tmp_path, "db", Path("cache"), target=100, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=ensure_prefetch,
        run_ingest=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ingest expected")),
        cached_not_done=lambda cache_dir, db_path: [],
        done_count=lambda db_path: 0,
        sleep=lambda s: None,
        max_idle=2,
    )
    assert calls["n"] == 1


# ================================================================================================
# OG-43: telemetry_poll_interval pass-through -- app.build_corpus --telemetry-poll-interval must
# reach every app.ingest batch invocation it runs (`_run_ingest`'s --telemetry-poll-interval flag).
# ================================================================================================


def test_build_to_target_omits_telemetry_poll_interval_kwarg_when_unset(tmp_path):
    """Default (unset) must call `run_ingest` with the plain 4-positional signature -- so an old
    test fake with no **kwargs (like every other test in this file) keeps working unmodified."""
    seen = []

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        seen.append("called")

    build_to_target(
        tmp_path, "db", Path("cache"), target=1, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=lambda cache_dir, db_path: (["a"] if not seen else []),
        done_count=lambda db_path: (1 if seen else 0),
        sleep=lambda s: None,
    )
    assert seen == ["called"]


def test_build_to_target_forwards_telemetry_poll_interval_when_set(tmp_path):
    seen = []

    def fake_run_ingest(
        batch_file, parse_workers, events_path, data_dir, *, telemetry_poll_interval=None,
    ):
        seen.append(telemetry_poll_interval)

    build_to_target(
        tmp_path, "db", Path("cache"), target=1, parse_workers=1, events_path=Path("events"),
        telemetry_poll_interval=2.5,
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=lambda cache_dir, db_path: (["a"] if not seen else []),
        done_count=lambda db_path: (1 if seen else 0),
        sleep=lambda s: None,
    )
    assert seen == [2.5]


def test_run_ingest_appends_telemetry_poll_interval_flag_only_when_set(tmp_path, monkeypatch):
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)

    monkeypatch.setattr("app.build_corpus.subprocess.run", fake_run)
    batch_file = tmp_path / "batch.ids"
    batch_file.write_text("2601.00001\n")

    from app.build_corpus import _run_ingest

    _run_ingest(batch_file, 1, Path("events.jsonl"), tmp_path)
    _run_ingest(batch_file, 1, Path("events.jsonl"), tmp_path, telemetry_poll_interval=3.0)

    assert "--telemetry-poll-interval" not in captured[0]
    assert "--telemetry-poll-interval" in captured[1]
    assert captured[1][captured[1].index("--telemetry-poll-interval") + 1] == "3.0"
