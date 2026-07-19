"""Tests for `app.build_corpus` -- offline, no real GPU/network/ingest/prefetch subprocess.

`build_to_target`'s own tests drive it against fakes for every injected seam (`ensure_prefetch`,
`run_ingest`, `cached_not_done`, `done_count`, `sleep`) -- same style as
`app/test_prefetch_pdfs.py`'s `prefetch_loop` tests. `cached_not_done`/`done_count` get their own
tests against a real (temp) sqlite db (`migrations.migrate`), same pattern as
`app/test_prefetch_pdfs.py`'s dedup tests. `ensure_prefetch_running` gets its own tests against a
real (but harmless) OS process, same pattern as `app/dashboard/test_controller.py`.
"""

import json
import logging
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from app.build_corpus import (
    _DEFAULT_MAX_IDLE,
    _is_live_prefetch,
    _normalize_date,
    _order_by_relevance,
    _parse_args,
    _prefetch_pid_path,
    _spawn_prefetch,
    _validate_cli_args,
    build_to_target,
    cached_not_done,
    done_count,
    ensure_prefetch_running,
)
from migrations.migrate import migrate
from rag.ingest_state_sqlite import SqliteIngestState


def _insert_paper(
    conn: sqlite3.Connection, paper_id: str, published: str, categories: list[str] | None = None,
) -> None:
    """Minimal `papers` row -- same pattern as `app/test_corpus_integrity.py::_insert_paper`,
    trimmed to just the columns this file's date/category-filter tests need. `categories`
    defaults to `[]`, matching every pre-existing call site that doesn't care about it."""
    conn.execute(
        """
        INSERT INTO papers
            (paper_id, version, title, abstract, authors_json, categories_json,
             published, updated, pdf_path, markdown_path, relevance_score)
        VALUES (?, 'v1', 't', 'a', '[]', ?, ?, ?, 'p', 'm.md', 0.5)
        """,
        (paper_id, json.dumps(categories or []), published, published),
    )
    conn.commit()

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


# --- date-range scoping: `target` means "done papers IN the date filter", not "done total" -------


def test_normalize_date_passes_through_iso():
    assert _normalize_date("2026-01-15") == "2026-01-15"


def test_normalize_date_converts_compact_yyyymmdd():
    assert _normalize_date("20260115") == "2026-01-15"


def test_done_count_date_filter_counts_only_papers_published_in_range(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-15")
    _insert_paper(conn, "2601.00002", "2026-03-01")
    _insert_paper(conn, "2601.00003", "2025-12-31")
    conn.close()
    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00001", "done")
    state.checkpoint("2601.00002", "done")
    state.checkpoint("2601.00003", "done")

    assert done_count(db_path, date_from="2026-01-01", date_to="2026-01-31") == 1
    assert done_count(db_path, date_from="2026-01-01") == 2
    assert done_count(db_path, date_to="2026-01-31") == 2
    assert done_count(db_path) == 3  # no filter -- unscoped, byte-for-byte the old behavior


def test_done_count_date_filter_accepts_compact_yyyymmdd(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-15")
    conn.close()
    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00001", "done")

    assert done_count(db_path, date_from="20260101", date_to="20260131") == 1
    assert done_count(db_path, date_from="20260201") == 0


def test_done_count_date_filter_excludes_not_yet_done_papers(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-15")
    conn.close()
    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00001", "parsed")

    assert done_count(db_path, date_from="2026-01-01") == 0


def test_done_count_date_filter_of_missing_db_is_zero(tmp_path):
    assert done_count(str(tmp_path / "no_such.db"), date_from="2026-01-01") == 0


# --- category scoping: T-DOC71's identically-shaped date gap, extended to arxiv_categories -------


def test_done_count_category_filter_is_an_or_match_like_the_harvester(tmp_path):
    """Same semantics as `rag/harvester.py::ArxivSource`'s own `cat:` OR-clause: a paper counts
    if ANY of its categories is in the requested list, not all of them."""
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-01", categories=["stat.ME"])
    _insert_paper(conn, "2601.00002", "2026-01-01", categories=["cs.LG", "stat.ML"])
    _insert_paper(conn, "2601.00003", "2026-01-01", categories=["econ.EM"])
    conn.close()
    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00001", "done")
    state.checkpoint("2601.00002", "done")
    state.checkpoint("2601.00003", "done")

    assert done_count(db_path, categories=["stat.ME"]) == 1
    assert done_count(db_path, categories=["stat.ML"]) == 1  # matches via the 2nd category entry
    assert done_count(db_path, categories=["stat.ME", "econ.EM"]) == 2
    assert done_count(db_path, categories=["cs.CL"]) == 0  # no paper has this category
    assert done_count(db_path) == 3  # no filter -- unscoped, byte-for-byte the old behavior


def test_done_count_category_filter_excludes_not_yet_done_papers(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-01", categories=["stat.ME"])
    conn.close()
    state = SqliteIngestState(db_path)
    state.checkpoint("2601.00001", "parsed")

    assert done_count(db_path, categories=["stat.ME"]) == 0


def test_done_count_combined_date_and_category_filter_requires_both(tmp_path):
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-15", categories=["stat.ME"])  # matches both
    _insert_paper(conn, "2601.00002", "2025-12-01", categories=["stat.ME"])  # wrong date
    _insert_paper(conn, "2601.00003", "2026-01-15", categories=["cs.LG"])  # wrong category
    conn.close()
    state = SqliteIngestState(db_path)
    for paper_id in ("2601.00001", "2601.00002", "2601.00003"):
        state.checkpoint(paper_id, "done")

    assert done_count(db_path, date_from="2026-01-01", categories=["stat.ME"]) == 1


def test_done_count_empty_categories_list_is_treated_as_no_filter(tmp_path):
    """Matches `rag/harvester.py::ArxivSource`'s own truthy `if self._categories:` check --
    `Config.arxiv_categories=[]` means "every category," same as `None`, not "match nothing"."""
    db_path = str(tmp_path / "papers.db")
    migrate(db_path)
    conn = sqlite3.connect(db_path)
    _insert_paper(conn, "2601.00001", "2026-01-01", categories=["stat.ME"])
    conn.close()
    SqliteIngestState(db_path).checkpoint("2601.00001", "done")

    assert done_count(db_path, categories=[]) == 1


def test_done_count_category_filter_of_missing_db_is_zero(tmp_path):
    assert done_count(str(tmp_path / "no_such.db"), categories=["stat.ME"]) == 0


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


# --- _spawn_prefetch: the real launch (not the fakes used elsewhere in this file) --------------


def test_spawn_prefetch_redirects_stdout_and_stderr_to_a_dedicated_log(tmp_path):
    """T-DOC<n>: `app/dashboard/status.py::read_downloader` used to tail the SHARED build_corpus
    run log for prefetch's own "downloaded X / target Y" pace line -- far more verbose
    parse-progress logging sharing that same file could push the real pace line tens of MB
    further back than the tail window ever reached, permanently blanking the dashboard's
    downloader fields even while prefetch was alive and working. `_spawn_prefetch` now redirects
    to its OWN dedicated `<data_dir>/prefetch.log` -- this test drives the REAL function (not a
    fake spawn) against a `tmp_path` with no `config.yaml`, so the real `app.prefetch_pdfs`
    fails fast on startup; that's fine, this only cares that whatever it prints on the way out
    lands in the dedicated log file rather than vanishing into this test process's own stdout."""
    pid = _spawn_prefetch(tmp_path)
    try:
        for _ in range(100):
            if not _alive_ignoring_cmdline(pid):
                break
            time.sleep(0.05)
        log_path = tmp_path / "prefetch.log"
        assert log_path.exists()
        assert log_path.read_text().strip() != ""
    finally:
        _cleanup_pid(pid)


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


# --- OG-49#3/#4: a batch that runs but makes ZERO net done_count progress is a stall too ---------


def test_build_to_target_zero_net_progress_batch_counts_as_a_stall(caplog, tmp_path):
    """The exact parse_workers=0 shape: cached_not_done keeps returning the SAME non-empty batch
    every iteration (nothing ever gets marked done) -- must trip the idle guard and stop, with a
    real sleep between attempts, not spin forever with zero sleep leaking batch-ids files."""
    written_batches = []

    def fake_cached_not_done(cache_dir, db_path):
        return ["2601.00001", "2601.00002"]  # never shrinks -- nothing ever completes

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        written_batches.append(batch_file)
        # "succeeds" (app.ingest --parse-workers 0 exits 0 having parsed nothing) -- done_count
        # never advances.

    sleeps = []
    with caplog.at_level(logging.INFO):
        build_to_target(
            tmp_path, "db", Path("cache"), target=100, parse_workers=1, events_path=Path("events"),
            ensure_prefetch=_fake_ensure_prefetch(alive=True),
            run_ingest=fake_run_ingest,
            cached_not_done=fake_cached_not_done,
            done_count=lambda db_path: 0,
            sleep=sleeps.append,
            max_idle=3,
        )

    assert len(written_batches) == 3  # one ingest attempt per idle pass, not an infinite tight loop
    # 2 sleeps: between attempts 1->2 and 2->3 -- the 3rd (max_idle-th) stops immediately, no sleep.
    assert len(sleeps) == 2
    assert "stalled" in caplog.text
    assert "zero net progress" in caplog.text


def test_build_to_target_progress_resets_the_idle_counter(tmp_path):
    """A batch that DOES make progress must reset idle_passes -- a single earlier zero-progress
    batch must not accumulate toward the stall threshold once real progress resumes."""
    done: set[str] = set()
    all_ids = ["2601.00001", "2601.00002"]
    call_count = {"n": 0}

    def fake_cached_not_done(cache_dir, db_path):
        return sorted(set(all_ids) - done)

    def fake_done_count(db_path):
        return len(done)

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return  # first batch: zero progress (simulates a transient hiccup)
        done.update(all_ids)  # second batch: real progress -- reaches target

    build_to_target(
        tmp_path, "db", Path("cache"), target=2, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=fake_done_count,
        sleep=lambda s: None,
        max_idle=2,
    )

    assert call_count["n"] == 2  # reached target on the 2nd batch -- never hit the idle guard


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


# ================================================================================================
# date-range scoping (fix for the dashboard "retarget with a new date range silently no-ops"
# gap): build_to_target(date_from=..., date_to=...) must check the SCOPED done count against
# `target`, not the corpus-wide total -- and must not break old callers/fakes that don't filter.
# ================================================================================================


def test_build_to_target_date_filter_keeps_going_past_a_stale_global_done_count(tmp_path):
    """Reproduces the exact gap: `done_count`'s fake tracks only papers done WITHIN the active
    date filter (as the real SQL-joined version now does) and deliberately ignores a much larger
    "global total" -- the loop must keep fetching/ingesting until the SCOPED count reaches
    target, not stop instantly the way it would if it read the unscoped total instead."""
    scoped_done: set[str] = set()
    all_ids = ["2601.00001", "2601.00002"]
    seen_filters = []

    def fake_cached_not_done(cache_dir, db_path):
        return sorted(set(all_ids) - scoped_done)

    def fake_done_count(db_path, *, date_from=None, date_to=None, categories=None):
        seen_filters.append((date_from, date_to))
        return len(scoped_done)  # NOT the corpus-wide total, which a real corpus already exceeds

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        ids = [line for line in batch_file.read_text().splitlines() if line]
        scoped_done.update(ids)

    build_to_target(
        tmp_path, "db", Path("cache"), target=2, parse_workers=1, events_path=Path("events"),
        date_from="2026-01-01", date_to="2026-01-31",
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=fake_done_count,
        sleep=lambda s: None,
    )

    assert len(scoped_done) == 2
    assert seen_filters and all(f == ("2026-01-01", "2026-01-31") for f in seen_filters)


def test_build_to_target_without_date_filter_calls_done_count_with_plain_signature(tmp_path):
    """Default (no date filter, matching every other test in this file) must call
    `done_count(db_path)` with no kwargs -- so an old test fake that takes only `db_path` (no
    **kwargs) keeps working unmodified, and a real unscoped run's SQL is unchanged."""
    seen = []

    def fake_done_count(db_path):
        seen.append("called")
        return 1

    build_to_target(
        tmp_path, "db", Path("cache"), target=1, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ingest expected")),
        cached_not_done=lambda cache_dir, db_path: [],
        done_count=fake_done_count,
        sleep=lambda s: None,
    )
    assert seen == ["called"]


# ================================================================================================
# category scoping -- T-DOC71's identically-shaped date gap, extended to arxiv_categories:
# build_to_target(categories=...) must check the SCOPED done count against `target` too.
# ================================================================================================


def test_build_to_target_category_filter_keeps_going_past_a_stale_global_done_count(tmp_path):
    """Same reproduction as the date-filter version above, but for `categories`: a corpus that
    already exceeds `target` overall, with zero papers done in the requested subject(s), must not
    "reach target" without ingesting anything matching that subject."""
    scoped_done: set[str] = set()
    all_ids = ["2601.00001", "2601.00002"]
    seen_filters = []

    def fake_cached_not_done(cache_dir, db_path):
        return sorted(set(all_ids) - scoped_done)

    def fake_done_count(db_path, *, date_from=None, date_to=None, categories=None):
        seen_filters.append(categories)
        return len(scoped_done)  # NOT the corpus-wide total, which a real corpus already exceeds

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        ids = [line for line in batch_file.read_text().splitlines() if line]
        scoped_done.update(ids)

    build_to_target(
        tmp_path, "db", Path("cache"), target=2, parse_workers=1, events_path=Path("events"),
        categories=["stat.ME", "econ.EM"],
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=fake_done_count,
        sleep=lambda s: None,
    )

    assert len(scoped_done) == 2
    assert seen_filters and all(f == ["stat.ME", "econ.EM"] for f in seen_filters)


def test_build_to_target_without_category_filter_calls_done_count_with_plain_signature(tmp_path):
    """Default (no filters at all) must still call `done_count(db_path)` with no kwargs -- an old
    test fake with no **kwargs keeps working unmodified, and a real unfiltered run's SQL is
    unchanged."""
    seen = []

    def fake_done_count(db_path):
        seen.append("called")
        return 1

    build_to_target(
        tmp_path, "db", Path("cache"), target=1, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ingest expected")),
        cached_not_done=lambda cache_dir, db_path: [],
        done_count=fake_done_count,
        sleep=lambda s: None,
    )
    assert seen == ["called"]


# ================================================================================================
# OG-46: relevance-priority processing queue -- _order_by_relevance + build_to_target(ordering=...)
# ================================================================================================


def test_order_by_relevance_puts_ranked_ids_first_in_rank_order():
    ranked = ["b", "a", "c"]  # arXiv relevance order for the current focus
    ids = ["a", "b", "z", "y"]  # cached-not-done batch: "b" and "a" are ranked, "z"/"y" are not
    assert _order_by_relevance(ids, ranked) == ["b", "a", "y", "z"]


def test_order_by_relevance_is_a_reordering_not_a_filter():
    """Every id in the input batch is still present exactly once -- OG-46: an ORDER, not a filter."""
    ids = ["x1", "x2", "x3"]
    result = _order_by_relevance(ids, ranked_ids=["x3"])
    assert sorted(result) == sorted(ids)
    assert result[0] == "x3"


def test_order_by_relevance_ignores_ranked_ids_not_in_the_batch():
    # "q" is ranked but isn't in `ids` (already done, or not cached yet) -- must not appear.
    assert _order_by_relevance(["a", "b"], ranked_ids=["q", "b", "a"]) == ["b", "a"]


def test_order_by_relevance_with_no_ranked_ids_falls_back_to_sorted():
    assert _order_by_relevance(["c", "a", "b"], ranked_ids=[]) == ["a", "b", "c"]


def test_build_to_target_default_ordering_never_calls_relevance_rank(tmp_path):
    """Default (freshest_first) must not touch `relevance_rank` at all -- zero behavior change for
    every existing (unordered) caller."""
    def fail_rank(focus_area_queries):
        raise AssertionError("relevance_rank must not be called under freshest_first ordering")

    build_to_target(
        tmp_path, "db", Path("cache"), target=1, parse_workers=1, events_path=Path("events"),
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=lambda batch_file, parse_workers, events_path, data_dir: None,
        cached_not_done=lambda cache_dir, db_path: ["a"],
        done_count=lambda db_path: 1,
        relevance_rank=fail_rank,
        sleep=lambda s: None,
    )


def test_build_to_target_relevance_ordering_reorders_each_batch(tmp_path):
    """cached_not_done keeps returning the same 4 ids across 2 iterations (2 processed per batch)
    -- the ranked ones must always come first, in rank order, even once the earlier-ranked ids
    are already done and gone from the pool."""
    all_ids = {"p1", "p2", "p3", "p4"}
    done: set[str] = set()
    batches_run = []

    def fake_cached_not_done(cache_dir, db_path):
        return sorted(all_ids - done)  # unordered-by-relevance input, same as the real function

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        ids = [line for line in batch_file.read_text().splitlines() if line]
        batches_run.append(ids)
        done.update(ids)

    build_to_target(
        tmp_path, "db", Path("cache"), target=4, parse_workers=1, events_path=Path("events"),
        batch_size=2,
        ordering="relevance",
        focus_area_queries=["causal inference"],
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=lambda db_path: len(done),
        relevance_rank=lambda focus: ["p3", "p1", "p4", "p2"],
        sleep=lambda s: None,
    )
    assert batches_run == [["p3", "p1"], ["p4", "p2"]]


def test_build_to_target_relevance_rank_is_computed_once_and_memoized(tmp_path):
    """The ranking harvest is a real (rate-limited) arXiv round trip -- must happen at most once
    per `build_to_target` call, not once per loop iteration."""
    all_ids = {"p1", "p2"}
    done: set[str] = set()
    rank_calls = []

    def fake_cached_not_done(cache_dir, db_path):
        return sorted(all_ids - done)

    def fake_run_ingest(batch_file, parse_workers, events_path, data_dir):
        ids = [line for line in batch_file.read_text().splitlines() if line]
        done.update(ids)

    def relevance_rank(focus):
        rank_calls.append(focus)
        return ["p2", "p1"]

    build_to_target(
        tmp_path, "db", Path("cache"), target=2, parse_workers=1, events_path=Path("events"),
        batch_size=1,
        ordering="relevance",
        focus_area_queries=["causal inference"],
        ensure_prefetch=_fake_ensure_prefetch(alive=True),
        run_ingest=fake_run_ingest,
        cached_not_done=fake_cached_not_done,
        done_count=lambda db_path: len(done),
        relevance_rank=relevance_rank,
        sleep=lambda s: None,
    )
    assert rank_calls == [["causal inference"]]  # exactly one harvest for the whole run


def test_build_to_target_relevance_ordering_with_empty_cache_never_ranks(tmp_path):
    """No cached-not-done ids yet (cold start) -- nothing to reorder, so the ranking harvest
    (a real network round trip in production) must not fire needlessly."""
    def fail_rank(focus_area_queries):
        raise AssertionError("must not rank when there is nothing cached yet")

    build_to_target(
        tmp_path, "db", Path("cache"), target=100, parse_workers=1, events_path=Path("events"),
        ordering="relevance",
        focus_area_queries=["causal inference"],
        ensure_prefetch=_fake_ensure_prefetch(alive=False),
        run_ingest=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ingest expected")),
        cached_not_done=lambda cache_dir, db_path: [],
        done_count=lambda db_path: 0,
        relevance_rank=fail_rank,
        sleep=lambda s: None,
    )


# --- OG-49#3: CLI-boundary validation (defense-in-depth for a manual/non-dashboard invocation) ---


def test_validate_cli_args_rejects_parse_workers_zero(capsys):
    args = _parse_args(["--target", "10", "--parse-workers", "0"])
    with pytest.raises(SystemExit) as exc_info:
        _validate_cli_args(args)
    assert exc_info.value.code == 1
    assert "--parse-workers must be >= 1" in capsys.readouterr().err


def test_validate_cli_args_rejects_negative_batch_size(capsys):
    args = _parse_args(["--target", "10", "--batch-size", "-5"])
    with pytest.raises(SystemExit):
        _validate_cli_args(args)
    assert "--batch-size must be >= 1" in capsys.readouterr().err


def test_validate_cli_args_accepts_defaults():
    args = _parse_args(["--target", "10"])
    _validate_cli_args(args)  # must not raise/exit


def test_validate_cli_args_accepts_unset_batch_size():
    args = _parse_args(["--target", "10", "--parse-workers", "3"])
    _validate_cli_args(args)  # must not raise/exit
