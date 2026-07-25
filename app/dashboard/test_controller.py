"""Tests for `app.dashboard.controller` -- offline, no real GPU/network/ingest. Every
start/resume uses a FAKE `spawn` that launches a harmless `sleep` subprocess (never
`python -m app.ingest`), so these tests exercise the real signaling/process-group/identity-
verification machinery against a real (but harmless) OS process without ever touching the GPU.
"""

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import filelock
import pytest

import app.dashboard.controller as controller_mod
from app.dashboard.controller import DoubleRunError, InvalidOverrideError, NoRunError


def _fake_spawn(data_dir, target, parse_workers, events_path, log_path):
    """Launches `sleep 100` as its own process-group leader -- same `start_new_session=True`
    shape as the real `_spawn`, so `os.killpg` and `/proc`-based identity verification behave
    exactly as they would against a real `app.ingest` process."""
    proc = subprocess.Popen(["sleep", "100"], start_new_session=True)
    return proc.pid


def _spawn_recorder(calls):
    def spawn(data_dir, target, parse_workers, events_path, log_path):
        calls.append((target, parse_workers, events_path, log_path))
        return _fake_spawn(data_dir, target, parse_workers, events_path, log_path)
    return spawn


def _cleanup(manifest):
    """Best-effort: kill any leftover `sleep` process a test spawned but never confirmed dead."""
    pid = manifest.get("pid") if manifest else None
    if pid:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


# --- start: the double-run guard -----------------------------------------------------------


def test_start_writes_manifest_with_real_launch_shape(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, parse_workers=3, spawn=_fake_spawn)
    try:
        assert manifest["status"] == "running"
        assert manifest["target"] == 100
        assert manifest["parse_workers"] == 3
        assert manifest["pid"] > 0
        assert manifest["pid_starttime"] is not None
        assert manifest["pid_cmdline"] is not None
        on_disk = json.loads((tmp_path / "run_manifest.json").read_text())
        assert on_disk == manifest
    finally:
        _cleanup(manifest)


def test_start_refuses_when_a_run_is_already_running(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        with pytest.raises(DoubleRunError):
            controller_mod.start(tmp_path, target=200, spawn=_fake_spawn)
    finally:
        _cleanup(manifest)


def test_start_allowed_again_once_prior_run_confirmed_dead(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    os.killpg(manifest["pid"], signal.SIGKILL)
    # Wait for the OS to actually reap it so reconcile()'s identity check sees it as dead.
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)
    second = controller_mod.start(tmp_path, target=200, spawn=_fake_spawn)
    try:
        assert second["target"] == 200
        assert second["status"] == "running"
    finally:
        _cleanup(second)


# --- T-DOC78: mode="download" -- a bare-downloader run sharing the same manifest/lock ----------


def test_start_default_mode_is_full_and_recorded_in_manifest(tmp_path):
    """Every existing caller/test omits `mode` -- must resolve to `"full"`, today's exact
    behavior, not silently become download-only."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        assert manifest["mode"] == "full"
    finally:
        _cleanup(manifest)


def test_start_with_mode_download_records_mode_in_manifest(tmp_path):
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        assert manifest["mode"] == "download"
        assert manifest["status"] == "running"
    finally:
        _cleanup(manifest)


def test_start_download_refused_while_a_full_run_is_live(tmp_path):
    """Mutual exclusion is the EXISTING double-run guard, mode-agnostic -- no new locking code."""
    full = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        with pytest.raises(DoubleRunError):
            controller_mod.start(
                tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
            )
    finally:
        _cleanup(full)


def test_start_full_refused_while_a_download_only_run_is_live(tmp_path):
    download = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        with pytest.raises(DoubleRunError):
            controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    finally:
        _cleanup(download)


def test_start_download_writes_prefetch_log_at_run_cwd_not_ingest_log(tmp_path):
    """`app/dashboard/status.py::read_downloader` hardcodes the log filename `prefetch.log` -- a
    download-only run's manifest must point at that exact name, not the usual
    `ingest_<run_id>.log`, or the dashboard's downloader-pace display goes blank."""
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        assert manifest["log_path"] == str(tmp_path / "prefetch.log")
    finally:
        _cleanup(manifest)


def test_start_full_still_writes_ingest_log_unchanged(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        assert manifest["log_path"] == str(tmp_path / f"ingest_{manifest['run_id']}.log")
    finally:
        _cleanup(manifest)


def test_start_download_reuses_keywords_override_same_as_a_full_run(tmp_path):
    """T-DOC78: "download now" must use the same keywords staged in the Apply panel --
    `_maybe_build_override` is mode-agnostic; this proves `mode="download"` reaches it too, via
    the same override path `test_start_with_keywords_augments_not_replaces_and_writes_override_config`
    already proves for a full run."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download",
        keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert override_dir != tmp_path  # launched in a scratch dir, not the real data_dir
        assert manifest["run_cwd"] == str(override_dir)
        written_cfg = controller_mod.load_config(Path(override_dir) / "config.yaml")
        assert written_cfg.focus_area_queries == base_cfg.focus_area_queries + ["zzz-test-keyword"]
        assert manifest["mode"] == "download"
    finally:
        _cleanup(manifest)


def test_real_spawn_download_launches_prefetch_pdfs_not_build_corpus(tmp_path, monkeypatch):
    """T-DOC78: `mode="download"`'s real launch command must be `python -m app.prefetch_pdfs` --
    no --target/--parse-workers/--events-path flags (it has none), no GPU, no pass1/pass2. Also
    writes `<data_dir>/prefetch.pid` -- the SAME filename `app/build_corpus.py::_spawn_prefetch`
    already writes, so `app/dashboard/status.py::read_downloader` and
    `app/build_corpus.py::ensure_prefetch_running` need zero changes to find it."""
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            self.pid = 999997

    monkeypatch.setattr(controller_mod.subprocess, "Popen", _FakePopen)
    log_path = tmp_path / "prefetch.log"

    pid = controller_mod._spawn_download(tmp_path, 30000, 1, tmp_path / "events.jsonl", log_path)

    assert pid == 999997
    cmd = captured["cmd"]
    assert "app.prefetch_pdfs" in cmd
    assert "app.build_corpus" not in cmd
    assert "--target" not in cmd
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["start_new_session"] is True
    assert (tmp_path / "prefetch.pid").read_text() == "999997"


# --- pause / stop: process-group signaling + transitional states --------------------------


def test_pause_sends_sigterm_and_confirms_death(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        paused = controller_mod.pause(tmp_path)
        assert paused["status"] == "paused"
        assert not controller_mod._pid_running(manifest["pid"])
        on_disk = json.loads((tmp_path / "run_manifest.json").read_text())
        assert on_disk["status"] == "paused"
    finally:
        _cleanup(manifest)


def test_pause_signals_the_whole_process_group_not_just_the_leader_pid(tmp_path, monkeypatch):
    """`start_new_session=True` at spawn makes the leader its own process-group leader (pgid ==
    pid) -- Pass-1 parse-worker children (`app.parse_phase`, launched by `app.ingest` with no
    session of their own) inherit that same group. Verifies `pause`/`stop` signal the GROUP
    (`os.killpg`), which reaches those children, not just `os.kill`'d the leader alone."""
    calls = []
    real_killpg = os.killpg

    def recording_killpg(pid, sig):
        calls.append((pid, sig))
        real_killpg(pid, sig)  # still actually kill it -- proves the call AND the effect

    monkeypatch.setattr(controller_mod.os, "killpg", recording_killpg)
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        controller_mod.pause(tmp_path)
        assert calls == [(manifest["pid"], signal.SIGTERM)]
    finally:
        _cleanup(manifest)


def test_stop_marks_done_not_paused(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        stopped = controller_mod.stop(tmp_path)
        assert stopped["status"] == "done"
    finally:
        _cleanup(manifest)


def test_pause_with_no_running_run_raises(tmp_path):
    with pytest.raises(NoRunError):
        controller_mod.pause(tmp_path)


def test_stop_with_no_running_run_raises(tmp_path):
    with pytest.raises(NoRunError):
        controller_mod.stop(tmp_path)


# --- resume: relaunches with the SAME params, refuses while still live ---------------------


def test_resume_relaunches_with_same_params(tmp_path):
    calls = []
    manifest = controller_mod.start(tmp_path, target=321, parse_workers=2, spawn=_spawn_recorder(calls))
    try:
        controller_mod.pause(tmp_path)
        resumed = controller_mod.resume(tmp_path, spawn=_spawn_recorder(calls))
        assert resumed["status"] == "running"
        assert resumed["target"] == 321
        assert resumed["parse_workers"] == 2
        assert resumed["pid"] != manifest["pid"]
        # both calls (start + resume) launched with the identical target/parse_workers/paths --
        # this is the controller-level half of "resume never duplicates work": the SAME
        # events_path/log_path/target keep it the same logical run against the same checkpoints.
        assert calls[0][:2] == calls[1][:2] == (321, 2)
        assert calls[0][2] == calls[1][2]  # same events_path
    finally:
        _cleanup(resumed)


def test_resume_relaunches_download_only_run_as_download_not_full(tmp_path, monkeypatch):
    """A paused download-only run's resume() must pick `_spawn_download` (resolved from the
    manifest's own stored mode) when the caller doesn't inject a test fake -- production's real
    call shape (`server.py` never passes `spawn=`) -- not silently fall back to launching a full
    `app.build_corpus` run."""
    calls = []

    def spy_download(data_dir, target, parse_workers, events_path, log_path):
        calls.append("download")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    def spy_full(data_dir, target, parse_workers, events_path, log_path):
        calls.append("full")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        controller_mod.pause(tmp_path)
        monkeypatch.setattr(controller_mod, "_spawn_download", spy_download)
        monkeypatch.setattr(controller_mod, "_spawn", spy_full)
        resumed = controller_mod.resume(tmp_path)  # no spawn injected -- production default path
        assert resumed["mode"] == "download"
        assert calls == ["download"]
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


def test_resume_relaunches_full_run_as_full_when_no_spawn_injected(tmp_path, monkeypatch):
    """The mode="full" (default) mirror of the test above -- resume()'s own default must still
    pick the real `_spawn` (app.build_corpus), today's exact behavior, for a manifest with no
    stored mode or `mode="full"`."""
    calls = []

    def spy_download(data_dir, target, parse_workers, events_path, log_path):
        calls.append("download")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    def spy_full(data_dir, target, parse_workers, events_path, log_path):
        calls.append("full")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        controller_mod.pause(tmp_path)
        monkeypatch.setattr(controller_mod, "_spawn_download", spy_download)
        monkeypatch.setattr(controller_mod, "_spawn", spy_full)
        resumed = controller_mod.resume(tmp_path)
        assert resumed["mode"] == "full"
        assert calls == ["full"]
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


def test_resume_refuses_while_run_is_still_running(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        with pytest.raises(DoubleRunError):
            controller_mod.resume(tmp_path, spawn=_fake_spawn)
    finally:
        _cleanup(manifest)


def test_resume_with_no_manifest_raises(tmp_path):
    with pytest.raises(NoRunError):
        controller_mod.resume(tmp_path, spawn=_fake_spawn)


def test_resume_refuses_while_pausing_has_not_yet_confirmed_dead(tmp_path, monkeypatch):
    """Simulates a slow-to-die process: signaled (status "pausing") but genuinely still alive
    (SIGTERM is a request, not a guarantee) -- resume must refuse rather than assume it worked.
    The process is left running (never actually signaled) so `reconcile()`'s own identity check
    -- unmocked -- correctly sees it as still alive and does NOT self-heal "pausing" away."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        manifest["status"] = "pausing"
        (tmp_path / "run_manifest.json").write_text(json.dumps(manifest))
        monkeypatch.setattr(controller_mod, "_wait_for_death", lambda pid, timeout_s=None: False)
        with pytest.raises(DoubleRunError):
            controller_mod.resume(tmp_path, spawn=_fake_spawn)
    finally:
        _cleanup(manifest)


# --- PID-reuse safety: the identity check refuses to signal a recycled PID ------------------


def test_guard_sees_through_a_stale_running_status_once_pid_is_dead(tmp_path):
    """The real failure mode this whole mechanism defends against: a manifest says `running`
    with a PID that has actually exited (matches the live 3K-run manifest observed in
    production) -- reconcile()/the guard must not treat that as still running.

    OG-47#2: this exact scenario (pid gone, no papers.db at all -> 0 done < target=100) is a
    CRASH, not a clean finish -- the terminal state must be `failed`, not `done` (which used to
    collapse the two indistinguishably). See `test_reconcile_marks_clean_finish_as_done_when_
    target_reached` below for the "actually reached target" contrast case."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    os.killpg(manifest["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)
    live = controller_mod.liveness(tmp_path)
    assert live["status"] == "failed"


def test_reconcile_marks_clean_finish_as_done_when_target_reached(tmp_path):
    """Contrast case for the fix above: when `ingest_state` shows done_count >= target, a dead pid
    reads as a clean finish (`done`), not a crash."""
    import sqlite3

    manifest = controller_mod.start(tmp_path, target=2, spawn=_fake_spawn)
    db_path = Path(manifest["db_path"])
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE ingest_state (paper_id TEXT PRIMARY KEY, stage TEXT)")
    conn.execute("INSERT INTO ingest_state VALUES ('a', 'done')")
    conn.execute("INSERT INTO ingest_state VALUES ('b', 'done')")
    conn.commit()
    conn.close()

    os.killpg(manifest["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)

    live = controller_mod.liveness(tmp_path)
    assert live["status"] == "done"


def test_reconcile_marks_clean_download_finish_as_done_even_though_done_count_never_moved(tmp_path):
    """T-DOC78: a `mode="download"` run's `target` is a PDF-cache count (e.g. prefetch_target),
    not a done-count -- `app.prefetch_pdfs` never writes `ingest_state` at all, so `done_count`
    stays 0 (nowhere near `target`) even on a totally clean exit. Before the `_crashed_before_
    target` mode guard, this made every clean download-mode finish misreport as "failed"."""
    manifest = controller_mod.start(tmp_path, target=30000, mode="download", spawn=_fake_spawn)
    os.killpg(manifest["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)

    live = controller_mod.liveness(tmp_path)
    assert live["status"] == "done"


def test_pause_refuses_to_signal_a_pid_reused_by_an_unrelated_process(tmp_path, monkeypatch):
    """Simulates PID reuse: after the real spawned process exits, some other live process now
    happens to occupy the same PID number. `_verified_pid` must reject it (different identity),
    so `pause()` must treat the run as already gone rather than SIGTERM an innocent process."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    real_pid = manifest["pid"]
    os.killpg(real_pid, signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(real_pid):
            break
        time.sleep(0.05)

    # Stand in for "the OS recycled `real_pid` onto an unrelated process": force
    # `_process_identity` to report a DIFFERENT identity for this exact pid, as if some other
    # process now lives there.
    monkeypatch.setattr(
        controller_mod, "_process_identity",
        lambda pid: (999999.0, "some-unrelated-process\x00") if pid == real_pid else None,
    )
    with pytest.raises(NoRunError):
        controller_mod.pause(tmp_path)  # reconcile() already downgraded status away from "running"


def test_verified_pid_rejects_manifest_with_no_stored_identity(tmp_path):
    """A manifest written before identity-tracking existed (no pid_starttime/pid_cmdline) must
    be treated as unconfirmed, not blindly trusted as alive."""
    manifest = {"pid": os.getpid(), "status": "running"}  # no pid_starttime/pid_cmdline
    assert controller_mod._verified_pid(manifest) is None


# --- `_capture_identity` must not permanently record a transitional (mid-execve) cmdline --------
#
# Real incident: `_spawn` launches via `env PYTHONPATH=<repo> python -m app.build_corpus ...` --
# `env` execve()s itself away into the real program WITHIN THE SAME PID almost immediately, but
# not instantly. `_capture_identity` won that race once, permanently storing `env`'s own argv as
# the run's "identity"; `/proc/<pid>/cmdline` never showed that again once the exec completed, so
# every later `_verified_pid` check mismatched forever -- a healthy, actively-progressing run got
# downgraded to "failed" (queuing its scratch config dir for deletion) out from under it.
#
# Second incident, found chasing a `pytest app/dashboard -q` flake that failed a DIFFERENT test
# each run (always the same family: a live `sleep 100`/`bash` test process downgraded to
# "failed"/"paused"/"done" mid-test): `/proc/<pid>/cmdline` also reads back EMPTY for a brief
# window around every `execve()` -- not just `_spawn`'s `env` wrapper's -- so even a plain
# `sleep 100` with no wrapper at all could be caught here under enough host load.
# `_is_transitional_cmdline` covers both shapes now; the tests below cover the empty-string one
# specifically (the `env`-wrapper tests above already cover the other).


def test_capture_identity_retries_past_the_env_wrappers_transitional_cmdline(monkeypatch):
    calls = {"n": 0}

    def fake_process_identity(pid):
        calls["n"] += 1
        if calls["n"] == 1:
            return (100.0, "env\x00PYTHONPATH=/repo\x00python\x00-m\x00app.build_corpus\x00")
        return (100.0, "python\x00-m\x00app.build_corpus\x00")

    monkeypatch.setattr(controller_mod, "_process_identity", fake_process_identity)
    monkeypatch.setattr(controller_mod.time, "sleep", lambda s: None)

    starttime, cmdline = controller_mod._capture_identity(12345)
    assert cmdline == "python\x00-m\x00app.build_corpus\x00"
    assert calls["n"] == 2  # the 1st (env-wrapper) read must not have been accepted as final


def test_capture_identity_still_retries_through_proc_not_ready_yet(monkeypatch):
    """Existing behavior preserved: `/proc` not yet populated (`_process_identity` -> None)
    still retries, same as before this fix -- only the "must not be the env wrapper" condition
    is new."""
    calls = {"n": 0}

    def fake_process_identity(pid):
        calls["n"] += 1
        if calls["n"] < 3:
            return None
        return (100.0, "python\x00-m\x00app.build_corpus\x00")

    monkeypatch.setattr(controller_mod, "_process_identity", fake_process_identity)
    monkeypatch.setattr(controller_mod.time, "sleep", lambda s: None)

    starttime, cmdline = controller_mod._capture_identity(12345)
    assert cmdline == "python\x00-m\x00app.build_corpus\x00"
    assert calls["n"] == 3


def test_capture_identity_falls_back_to_env_cmdline_if_it_never_resolves(monkeypatch):
    """Best-effort fallback matching this function's existing contract: if every retry still
    shows the transitional `env` wrapper (should never happen in practice -- `env` execve()s
    near-instantly), return the last-observed identity rather than `(None, None)`."""
    monkeypatch.setattr(
        controller_mod, "_process_identity",
        lambda pid: (100.0, "env\x00PYTHONPATH=/repo\x00python\x00"),
    )
    monkeypatch.setattr(controller_mod.time, "sleep", lambda s: None)

    starttime, cmdline = controller_mod._capture_identity(12345)
    assert starttime == 100.0
    assert cmdline == "env\x00PYTHONPATH=/repo\x00python\x00"


def test_capture_identity_accepts_a_cmdline_that_never_went_through_env(monkeypatch):
    """The common/simple case (no wrapper at all, e.g. a test's own fake spawn) must still work
    unchanged -- first successful read wins immediately."""
    calls = {"n": 0}

    def fake_process_identity(pid):
        calls["n"] += 1
        return (100.0, "sleep\x00100\x00")

    monkeypatch.setattr(controller_mod, "_process_identity", fake_process_identity)

    starttime, cmdline = controller_mod._capture_identity(12345)
    assert cmdline == "sleep\x00100\x00"
    assert calls["n"] == 1


def test_capture_identity_retries_past_a_transient_empty_cmdline_read(monkeypatch):
    """The flake's actual mechanism: the FIRST `/proc/<pid>/cmdline` read lands in the kernel's
    brief "old argv cleared, new one not yet installed" window around `execve()` and comes back
    `""` -- not `None` (no exception, `_process_identity` succeeds) and not the `env`-wrapper
    prefix, so the pre-fix code accepted it as final on the first try and stored it permanently.
    Must retry past an empty cmdline exactly like the env-wrapper one."""
    calls = {"n": 0}

    def fake_process_identity(pid):
        calls["n"] += 1
        if calls["n"] == 1:
            return (100.0, "")
        return (100.0, "sleep\x00100\x00")

    monkeypatch.setattr(controller_mod, "_process_identity", fake_process_identity)
    monkeypatch.setattr(controller_mod.time, "sleep", lambda s: None)

    starttime, cmdline = controller_mod._capture_identity(12345)
    assert cmdline == "sleep\x00100\x00"
    assert calls["n"] == 2  # the 1st (empty, transitional) read must not have been accepted


def test_capture_identity_falls_back_to_empty_cmdline_if_it_never_resolves(monkeypatch):
    """Best-effort fallback matching this function's existing contract: if every retry still
    reads empty (should be rare -- `execve()` settles near-instantly), return the last-observed
    identity rather than `(None, None)`."""
    monkeypatch.setattr(controller_mod, "_process_identity", lambda pid: (100.0, ""))
    monkeypatch.setattr(controller_mod.time, "sleep", lambda s: None)

    starttime, cmdline = controller_mod._capture_identity(12345)
    assert starttime == 100.0
    assert cmdline == ""


def test_reconcile_does_not_downgrade_a_live_run_whose_capture_raced_an_empty_cmdline(tmp_path):
    """End-to-end regression for the actual observed flake: even if `_capture_identity`'s retry
    loop is defeated entirely (every read transient), a run that's still genuinely alive must not
    be silently, permanently downgraded the moment `reconcile()` next runs. This exercises the
    real `start()` -> `_verified_pid()` path against a real, live process -- unlike the two tests
    above (which test `_capture_identity` in isolation), this confirms the fix actually closes the
    reconcile()-time symptom (`NoRunError` from `pause`/`stop`/`resume` immediately after start)."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        # capture_identity already retried past any real transitional read by the time start()
        # returns (the fix under test) -- confirm the stored cmdline is the real, settled one, not
        # empty, so every later reconcile() call verifies this live process correctly.
        assert manifest["pid_cmdline"], "must not have captured an empty/transitional cmdline"
        live = controller_mod.liveness(tmp_path)
        assert live["status"] == "running"
    finally:
        _cleanup(manifest)


# --- atomic writes ---------------------------------------------------------------------------


def test_manifest_write_is_atomic_no_tmp_file_left_behind(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        assert not (tmp_path / "run_manifest.json.tmp").exists()
        assert (tmp_path / "run_manifest.json").exists()
    finally:
        _cleanup(manifest)


# --- retarget: stop-then-start ---------------------------------------------------------------


def test_retarget_stops_current_run_then_starts_new_target(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    old_pid = manifest["pid"]
    try:
        retargeted = controller_mod.retarget(tmp_path, target=500, spawn=_fake_spawn)
        assert retargeted["target"] == 500
        assert retargeted["status"] == "running"
        assert not controller_mod._pid_running(old_pid)
    finally:
        _cleanup(retargeted)


def test_retarget_with_nothing_running_just_starts(tmp_path):
    started = controller_mod.retarget(tmp_path, target=500, spawn=_fake_spawn)
    try:
        assert started["target"] == 500
    finally:
        _cleanup(started)


# --- OG-41: the real _spawn launches app.build_corpus, not app.ingest ----------------------------


def test_real_spawn_launches_build_corpus_not_ingest(tmp_path, monkeypatch):
    """OG-41: the dashboard's real launch command must be `python -m app.build_corpus --target N
    --parse-workers K --events-path <path>` -- not the old direct `app.ingest --limit`/
    `--paper-ids-file` invocation. build_corpus is the group leader that in turn keeps
    app.prefetch_pdfs running and repeatedly launches app.ingest batches itself."""
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            self.pid = 999999

    monkeypatch.setattr(controller_mod.subprocess, "Popen", _FakePopen)
    events_path = tmp_path / "events.jsonl"
    log_path = tmp_path / "run.log"

    pid = controller_mod._spawn(tmp_path, 500, 4, events_path, log_path)

    assert pid == 999999
    cmd = captured["cmd"]
    assert "app.build_corpus" in cmd
    assert "app.ingest" not in cmd
    assert "--target" in cmd and cmd[cmd.index("--target") + 1] == "500"
    assert "--parse-workers" in cmd and cmd[cmd.index("--parse-workers") + 1] == "4"
    assert "--events-path" in cmd and cmd[cmd.index("--events-path") + 1] == str(events_path)
    assert "--limit" not in cmd
    assert "--paper-ids-file" not in cmd
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["start_new_session"] is True


def test_real_spawn_ignores_paper_ids_file_kwarg_without_erroring(tmp_path, monkeypatch):
    """`paper_ids_file` is still accepted (so `_call_spawn`'s uniform calling convention and the
    manifest's own OG-40 threading don't need special-casing) but build_corpus has no matching
    flag -- it must not appear on the command line."""
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.pid = 999998

    monkeypatch.setattr(controller_mod.subprocess, "Popen", _FakePopen)
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("2601.00001\n")

    controller_mod._spawn(
        tmp_path, 500, 4, tmp_path / "events.jsonl", tmp_path / "run.log",
        paper_ids_file=ids_file,
    )

    assert "--paper-ids-file" not in captured["cmd"]
    assert str(ids_file) not in captured["cmd"]


# --- OG-40: cache-first paper_ids_file threading -------------------------------------------------


def test_paper_ids_file_recorded_in_manifest_and_repassed_on_resume(tmp_path):
    """OG-40: a cache-first run stores `paper_ids_file` in the manifest, hands it to `spawn`, and
    `resume` re-passes the SAME file -- a paused cache-first run must not silently revert to the
    query-driven (809-ceiling) harvest."""
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("2403.19606\n2404.00207\n")
    seen = []

    def spawn(data_dir, target, parse_workers, events_path, log_path, *, paper_ids_file=None):
        seen.append(paper_ids_file)
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    manifest = controller_mod.start(tmp_path, target=2, paper_ids_file=ids_file, spawn=spawn)
    try:
        assert manifest["paper_ids_file"] == str(ids_file)
        assert seen[-1] == ids_file  # start handed the file to spawn (not None, not dropped)

        controller_mod.pause(tmp_path)
        resumed = controller_mod.resume(tmp_path, spawn=spawn)
        assert seen[-1] == ids_file  # resume re-passed it, still cache-first
        assert resumed["paper_ids_file"] == str(ids_file)
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


def test_default_run_has_null_paper_ids_file_and_no_kwarg_to_fake_spawn(tmp_path):
    """A normal (query-driven) run passes NO paper_ids_file kwarg -- so the 5-positional test fake
    keeps working -- and records `paper_ids_file: null`."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        assert manifest["paper_ids_file"] is None
    finally:
        _cleanup(manifest)


# --- OG-43: pass-through CLI params (telemetry_poll_interval, batch_size) -----------------------


def _kwargs_spawn(calls):
    """A spawn fake that accepts arbitrary kwargs (unlike the plain 5-positional `_fake_spawn`) and
    records both the cwd it was launched with and every kwarg it received."""
    def spawn(data_dir, target, parse_workers, events_path, log_path, **kwargs):
        calls.append({"cwd": data_dir, "kwargs": kwargs})
        proc = subprocess.Popen(["sleep", "100"], start_new_session=True)
        return proc.pid
    return spawn


def test_start_forwards_telemetry_poll_interval_and_batch_size_as_plain_flags(tmp_path):
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, telemetry_poll_interval=2.5, batch_size=50,
        spawn=_kwargs_spawn(calls),
    )
    try:
        assert calls[0]["kwargs"] == {"telemetry_poll_interval": 2.5, "batch_size": 50}
        # no config-derived edit requested -- cwd stays the real data_dir, no override dir
        assert calls[0]["cwd"] == tmp_path
        assert manifest["run_cwd"] == str(tmp_path)
        assert manifest["params"]["telemetry_poll_interval"] == 2.5
        assert manifest["params"]["batch_size"] == 50
    finally:
        _cleanup(manifest)


def test_real_spawn_appends_telemetry_and_batch_size_flags_when_set(tmp_path, monkeypatch):
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.pid = 999997

    monkeypatch.setattr(controller_mod.subprocess, "Popen", _FakePopen)
    controller_mod._spawn(
        tmp_path, 500, 4, tmp_path / "events.jsonl", tmp_path / "run.log",
        telemetry_poll_interval=2.5, batch_size=50,
    )
    cmd = captured["cmd"]
    assert "--telemetry-poll-interval" in cmd
    assert cmd[cmd.index("--telemetry-poll-interval") + 1] == "2.5"
    assert "--batch-size" in cmd
    assert cmd[cmd.index("--batch-size") + 1] == "50"


def test_real_spawn_omits_telemetry_and_batch_size_flags_when_unset(tmp_path, monkeypatch):
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.pid = 999996

    monkeypatch.setattr(controller_mod.subprocess, "Popen", _FakePopen)
    controller_mod._spawn(tmp_path, 500, 4, tmp_path / "events.jsonl", tmp_path / "run.log")
    cmd = captured["cmd"]
    assert "--telemetry-poll-interval" not in cmd
    assert "--batch-size" not in cmd


# --- OG-43: config-derived overrides (keywords augment, parse_batch_size) -----------------------


def test_start_with_no_edits_launches_in_the_real_data_dir_no_override(tmp_path):
    """A run that edits nothing must launch exactly the old way -- no override scratch dir, no
    extra config.yaml written anywhere."""
    calls = []
    manifest = controller_mod.start(tmp_path, target=100, spawn=_kwargs_spawn(calls))
    try:
        assert calls[0]["cwd"] == tmp_path
        assert manifest["run_cwd"] == str(tmp_path)
    finally:
        _cleanup(manifest)


def test_start_with_keywords_augments_not_replaces_and_writes_override_config(tmp_path):
    """OG-43 owner decision: editing keywords AUGMENTS focus_area_queries (adds topics), never
    replaces the library. The override config.yaml must carry the merged list, and the run must
    launch with cwd=<the scratch dir that holds it> so app.build_corpus/prefetch/ingest all pick
    it up via their own load_config()."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert override_dir != tmp_path  # launched in a scratch dir, not the real data_dir
        assert manifest["run_cwd"] == str(override_dir)

        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert written_cfg.focus_area_queries == base_cfg.focus_area_queries + ["zzz-test-keyword"]
        assert manifest["focus_queries"] == written_cfg.focus_area_queries
    finally:
        _cleanup(manifest)


def test_start_with_keyword_already_in_base_config_is_a_no_op_override(tmp_path):
    """Re-adding an already-present keyword changes nothing -- no override dir needed."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=[base_cfg.focus_area_queries[0]], spawn=_kwargs_spawn(calls),
    )
    try:
        assert calls[0]["cwd"] == tmp_path  # no override -- nothing actually changed
        assert manifest["run_cwd"] == str(tmp_path)
    finally:
        _cleanup(manifest)


# --- Task 3: keyword REMOVAL (owner-requested; supersedes "augment, never replace" for removal) --


def test_start_with_remove_keywords_removes_a_base_config_query(tmp_path):
    """Removal works on the 33 base config.yaml queries too, not just ones added in this same
    request -- the override writes the resulting list wholesale."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    removed = base_cfg.focus_area_queries[0]
    manifest = controller_mod.start(
        tmp_path, target=100, remove_keywords=[removed], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert override_dir != tmp_path
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert removed not in written_cfg.focus_area_queries
        assert len(written_cfg.focus_area_queries) == len(base_cfg.focus_area_queries) - 1
        assert manifest["focus_queries"] == written_cfg.focus_area_queries
    finally:
        _cleanup(manifest)


def test_start_with_remove_keywords_not_present_is_a_harmless_no_op(tmp_path):
    """Removing a keyword that isn't present must not error -- and since nothing actually changed,
    no override is needed at all."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, remove_keywords=["not-a-real-keyword-at-all"],
        spawn=_kwargs_spawn(calls),
    )
    try:
        assert calls[0]["cwd"] == tmp_path  # no override -- nothing actually changed
        assert manifest["run_cwd"] == str(tmp_path)
    finally:
        _cleanup(manifest)


def test_start_with_keywords_and_remove_keywords_together_applies_remove_after_augment(tmp_path):
    """Semantics: remove_keywords applies AFTER the keywords augment merge -- add+remove in one
    request is well-defined (e.g. adding then immediately removing the same term is a no-op add)."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    to_remove = base_cfg.focus_area_queries[0]
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-added-keyword"], remove_keywords=[to_remove],
        spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert "zzz-added-keyword" in written_cfg.focus_area_queries
        assert to_remove not in written_cfg.focus_area_queries
    finally:
        _cleanup(manifest)


def test_start_with_remove_keywords_matching_the_just_added_keyword_is_a_no_op(tmp_path):
    """Adding a keyword and removing that SAME keyword in one request nets out to the unedited
    base config -- no override needed."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-added-then-removed"],
        remove_keywords=["zzz-added-then-removed"], spawn=_kwargs_spawn(calls),
    )
    try:
        assert calls[0]["cwd"] == tmp_path
        assert manifest["run_cwd"] == str(tmp_path)
    finally:
        _cleanup(manifest)


def test_start_with_remove_keywords_removing_everything_is_refused(tmp_path):
    """Guard: refuse to remove every keyword -- an empty focus_area_queries leaves the downloader
    with nothing to search. contracts/config.py's `focus_area_queries` is a bare `list[str]` with
    no min-length, so this explicit guard is the only thing standing between the request and a
    dead run."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    with pytest.raises(InvalidOverrideError):
        controller_mod.start(
            tmp_path, target=100, remove_keywords=list(base_cfg.focus_area_queries),
            spawn=_kwargs_spawn(calls),
        )
    assert calls == [], "must never reach spawn -- rejected pre-spawn"
    assert not (tmp_path / "run_manifest.json").exists()


def test_retarget_wires_remove_keywords_through(tmp_path):
    calls = []
    controller_mod.start(tmp_path, target=100, spawn=_kwargs_spawn(calls))
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    removed = base_cfg.focus_area_queries[0]
    try:
        retargeted = controller_mod.retarget(
            tmp_path, target=500, remove_keywords=[removed], spawn=_kwargs_spawn(calls),
        )
        assert removed not in retargeted["focus_queries"]
    finally:
        _cleanup(retargeted)


def test_start_with_parse_batch_size_writes_override_config_with_absolute_paths(tmp_path):
    """The override config.yaml's path-valued fields (db_path/blob_dir/pdf_cache_dir/...) must be
    resolved ABSOLUTE -- the subprocess launched into the scratch dir has a different cwd than the
    real data_dir, so an unresolved relative field would silently point somewhere else."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, parse_batch_size=8, spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert manifest["parse_batch_size"] == 8
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert written_cfg.parse_batch_size == 8
        assert Path(written_cfg.db_path).is_absolute()
        assert Path(written_cfg.pdf_cache_dir).is_absolute()
    finally:
        _cleanup(manifest)


def test_start_with_arxiv_categories_writes_override_config(tmp_path):
    """OG-45: unlike keywords, category/date filters REPLACE the base config's value for this
    run (no "augment a filter" semantics)."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, arxiv_categories=["stat.ME", "econ.EM"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert override_dir != tmp_path
        assert manifest["arxiv_categories"] == ["stat.ME", "econ.EM"]
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert written_cfg.arxiv_categories == ["stat.ME", "econ.EM"]
    finally:
        _cleanup(manifest)


def test_start_with_arxiv_date_range_writes_override_config(tmp_path):
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, arxiv_date_from="2018-01-01", arxiv_date_to="2020-01-01",
        spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert manifest["arxiv_date_from"] == "2018-01-01"
        assert manifest["arxiv_date_to"] == "2020-01-01"
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert written_cfg.arxiv_date_from == "2018-01-01"
        assert written_cfg.arxiv_date_to == "2020-01-01"
    finally:
        _cleanup(manifest)


def test_start_with_ordering_relevance_writes_override_config(tmp_path):
    """OG-46: dashboard-launched runs may opt into arXiv-relevance ordering."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, ordering="relevance", spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert manifest["ordering"] == "relevance"
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert written_cfg.ordering == "relevance"
    finally:
        _cleanup(manifest)


def test_start_with_no_edits_reports_the_base_config_ordering_and_filters(tmp_path):
    """An unedited run's manifest still carries the (unedited) ordering/filter values -- the
    dashboard's run-panel indicator has something to read regardless of whether this run edited
    anything."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    manifest = controller_mod.start(tmp_path, target=100, spawn=_kwargs_spawn(calls))
    try:
        assert calls[0]["cwd"] == tmp_path  # no override -- nothing actually changed
        assert manifest["ordering"] == base_cfg.ordering
        assert manifest["arxiv_categories"] == base_cfg.arxiv_categories
    finally:
        _cleanup(manifest)


def test_start_with_ordering_matching_the_base_config_is_a_no_op_override(tmp_path):
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, ordering="freshest_first", spawn=_kwargs_spawn(calls),
    )
    try:
        assert calls[0]["cwd"] == tmp_path  # "freshest_first" already matches the base default
    finally:
        _cleanup(manifest)


def test_resume_reuses_the_same_run_cwd_and_pass_through_params(tmp_path):
    """A paused edited run must come back with the SAME override dir (and pass-through params) --
    not silently revert to config.yaml's unedited defaults."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-test-keyword"],
        telemetry_poll_interval=2.5, spawn=_kwargs_spawn(calls),
    )
    try:
        controller_mod.pause(tmp_path)
        resumed = controller_mod.resume(tmp_path, spawn=_kwargs_spawn(calls))
        assert resumed["run_cwd"] == manifest["run_cwd"]
        assert calls[1]["cwd"] == calls[0]["cwd"]
        assert calls[1]["kwargs"] == {"telemetry_poll_interval": 2.5}
    finally:
        _cleanup(resumed)


# --- OG-49 M10: override scratch dir lifecycle -----------------------------------------------


def test_pause_does_not_remove_the_override_dir(tmp_path):
    """`resume()` reuses `run_cwd` verbatim (see the test above) -- `pause` must leave the
    override scratch dir on disk, not delete the very thing a later resume needs."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    override_dir = Path(manifest["run_cwd"])
    try:
        assert override_dir != tmp_path
        assert override_dir.is_dir()
        controller_mod.pause(tmp_path)
        assert override_dir.is_dir(), "pause must not remove a dir resume() will reuse"
    finally:
        _cleanup(manifest)


def test_stop_removes_an_edited_runs_override_dir(tmp_path):
    """A user-initiated stop is final (module docstring, no later resume) -- its override scratch
    dir is safe to remove once death is confirmed."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    override_dir = Path(manifest["run_cwd"])
    assert override_dir.is_dir()
    stopped = controller_mod.stop(tmp_path)
    assert stopped["status"] == "done"
    assert not override_dir.exists()


def test_stop_with_no_override_never_touches_the_real_data_dir(tmp_path):
    """An unedited run's `run_cwd` IS the real data dir -- `stop`'s cleanup must never rmtree it,
    even though it's the same "terminal, no resume expected" case as the override-dir test above."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    assert manifest["run_cwd"] == str(tmp_path)
    controller_mod.stop(tmp_path)
    assert tmp_path.is_dir()
    assert (tmp_path / "run_manifest.json").exists()


def test_reconcile_removes_override_dir_once_a_crashed_run_self_heals_to_done(tmp_path):
    """A run whose process dies WITHOUT going through pause/stop, but had actually REACHED its
    target (a clean finish reconcile() just never got to record) is caught by reconcile()'s own
    identity check and downgraded to `done` -- that transition must clean up the override dir too,
    the same as an explicit `stop()` does."""
    import sqlite3

    calls = []
    manifest = controller_mod.start(
        tmp_path, target=2, keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    override_dir = Path(manifest["run_cwd"])
    assert override_dir.is_dir()
    conn = sqlite3.connect(manifest["db_path"])
    conn.execute("CREATE TABLE ingest_state (paper_id TEXT PRIMARY KEY, stage TEXT)")
    conn.execute("INSERT INTO ingest_state VALUES ('a', 'done')")
    conn.execute("INSERT INTO ingest_state VALUES ('b', 'done')")
    conn.commit()
    conn.close()
    os.killpg(manifest["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)

    reconciled = controller_mod.liveness(tmp_path)

    assert reconciled["status"] == "done"
    assert not override_dir.exists()


def test_reconcile_preserves_override_dir_for_a_genuine_crash_so_resume_can_use_it(tmp_path):
    """OG-49 M10 vs. resume-from-failed: a run whose process dies mid-way (target NOT reached) is
    downgraded to `failed`, not `done` -- and `reconcile()` must leave its override dir alone, the
    exact opposite of the `done` case above. A crashed run is precisely the one the user will
    resume; deleting run_cwd here is what made every edited run's resume-from-failed
    unconditionally raise `FileNotFoundError` (the bug this fix closes)."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    override_dir = Path(manifest["run_cwd"])
    assert override_dir.is_dir()
    os.killpg(manifest["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)

    reconciled = controller_mod.liveness(tmp_path)

    assert reconciled["status"] == "failed"
    assert override_dir.is_dir(), "a crashed run's run_cwd must survive for a later resume()"


# --- resume is broken for any run that used a config override (the durable-override-dir fix) ----
#
# Confirmed repro: reconcile() marks a crashed run "failed" -> the OLD reconcile() deleted that
# run's run_cwd -> a later resume() calls _call_spawn(..., run_cwd) -> subprocess.Popen(cwd=<
# deleted dir>) -> FileNotFoundError, uncaught by server.py's _dispatch. Resume worked fine for an
# UNEDITED run (run_cwd == data_dir, never deleted) -- broken for every run that edited keywords/
# filters/ordering/parse_batch_size. Four parts: (1) durable dir under data_dir, not /tmp; (2)
# reconcile() no longer deletes on "failed" (see the test above); (3) resume rebuilds a missing
# run_cwd from the manifest; (4) start() cleans up an abandoned prior run's run_cwd so it doesn't
# leak forever when the user never resumes it.


def test_override_dir_lives_under_data_dir_not_tmp(tmp_path):
    """Part 1: the scratch config.yaml dir must be durable (survive a reboot) -- under
    data_dir/.run_overrides/<run_id>, never /tmp (the old `tempfile.mkdtemp` location, which does
    NOT survive a reboot and leaked 328 dirs over time)."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = Path(manifest["run_cwd"])
        assert override_dir.is_relative_to(tmp_path)
        assert override_dir == tmp_path / ".run_overrides" / manifest["run_id"]
        assert "/tmp" not in str(override_dir) or str(override_dir).startswith(str(tmp_path))
    finally:
        _cleanup(manifest)


def test_resume_rebuilds_a_missing_run_cwd_from_the_manifests_own_recorded_params(tmp_path):
    """Part 3, the actual repro from the owner's stuck manifest: a "failed" run's run_cwd is gone
    (simulating a reboot that wiped it, or any other loss) -- resume() must rebuild the override
    config.yaml from the manifest's OWN persisted effective params, not raise FileNotFoundError
    and not silently fall back to the unedited base config (which would resurrect the run with the
    WRONG settings)."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-rebuild-keyword"], parse_batch_size=7,
        ordering="relevance", arxiv_categories=["stat.ME"], arxiv_date_from="2019-01-01",
        spawn=_kwargs_spawn(calls),
    )
    override_dir = Path(manifest["run_cwd"])
    assert override_dir.is_dir()
    os.killpg(manifest["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(manifest["pid"]):
            break
        time.sleep(0.05)
    assert controller_mod.liveness(tmp_path)["status"] == "failed"

    # Simulate the loss: the dir is gone, but the manifest (and its recorded effective params)
    # survives -- exactly the owner's real stuck-manifest scenario.
    shutil.rmtree(override_dir)
    assert not override_dir.exists()

    resumed = controller_mod.resume(tmp_path, spawn=_kwargs_spawn(calls))
    try:
        assert resumed["status"] == "running"
        assert override_dir.is_dir(), "resume must rebuild the missing run_cwd, not skip it"
        rebuilt_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert "zzz-rebuild-keyword" in rebuilt_cfg.focus_area_queries
        assert rebuilt_cfg.parse_batch_size == 7
        assert rebuilt_cfg.ordering == "relevance"
        assert rebuilt_cfg.arxiv_categories == ["stat.ME"]
        assert rebuilt_cfg.arxiv_date_from == "2019-01-01"
        # rebuilt paths must still resolve absolute under data_dir, same as a fresh override write.
        assert Path(rebuilt_cfg.db_path).is_absolute()
        assert calls[-1]["cwd"] == override_dir
    finally:
        _cleanup(resumed)


def test_resume_with_intact_run_cwd_never_rebuilds(tmp_path):
    """The rebuild path must be a fallback ONLY -- an intact run_cwd (the common case) is reused
    verbatim, never rewritten (which could needlessly touch or race a config.yaml the paused
    process's own downloader/ingest children might still reference)."""
    calls = []
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-keep-keyword"], spawn=_kwargs_spawn(calls),
    )
    override_dir = Path(manifest["run_cwd"])
    controller_mod.pause(tmp_path)
    before = (override_dir / "config.yaml").read_text()

    resumed = controller_mod.resume(tmp_path, spawn=_kwargs_spawn(calls))
    try:
        assert (override_dir / "config.yaml").read_text() == before
    finally:
        _cleanup(resumed)


def test_start_cleans_up_a_paused_runs_override_dir_when_abandoning_it(tmp_path):
    """Part 4 (the abandon leak an audit found): pausing an edited run and then hitting Apply for
    a FRESH run (never resuming the paused one) must not leak the old scratch dir forever --
    `reconcile()` never cleans up "paused" (a later resume() might still want it), so this is its
    only remaining chance."""
    calls = []
    first = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-abandoned-keyword"], spawn=_kwargs_spawn(calls),
    )
    old_override_dir = Path(first["run_cwd"])
    controller_mod.pause(tmp_path)
    assert old_override_dir.is_dir()

    second = controller_mod.start(tmp_path, target=200, spawn=_kwargs_spawn(calls))
    try:
        assert not old_override_dir.exists(), "abandoned paused run's scratch dir must be cleaned up"
        assert second["target"] == 200
    finally:
        _cleanup(second)


def test_start_cleans_up_a_failed_runs_override_dir_when_abandoning_it(tmp_path):
    """Same leak, the "failed" side: now that reconcile() no longer auto-cleans a "failed" run's
    run_cwd (it might be resumed), abandoning it for a fresh start instead is the only other place
    left that can reclaim the scratch dir."""
    calls = []
    first = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-abandoned-failed-keyword"], spawn=_kwargs_spawn(calls),
    )
    old_override_dir = Path(first["run_cwd"])
    os.killpg(first["pid"], signal.SIGKILL)
    for _ in range(50):
        if not controller_mod._pid_running(first["pid"]):
            break
        time.sleep(0.05)
    assert controller_mod.liveness(tmp_path)["status"] == "failed"
    assert old_override_dir.is_dir()

    second = controller_mod.start(tmp_path, target=200, spawn=_kwargs_spawn(calls))
    try:
        assert not old_override_dir.exists()
        assert second["target"] == 200
    finally:
        _cleanup(second)


def test_retarget_wires_og43_params_through(tmp_path):
    """`retarget` (stop-then-start) is the "Apply new settings while live" path -- edits must
    reach the fresh run exactly as they would via a plain `start`."""
    calls = []
    controller_mod.start(tmp_path, target=100, spawn=_kwargs_spawn(calls))
    try:
        retargeted = controller_mod.retarget(
            tmp_path, target=500, parse_batch_size=8, batch_size=25, spawn=_kwargs_spawn(calls),
        )
        assert retargeted["parse_batch_size"] == 8
        assert retargeted["params"]["batch_size"] == 25
        assert calls[-1]["kwargs"]["batch_size"] == 25
    finally:
        _cleanup(retargeted)


def test_retarget_wires_og45_og46_params_through(tmp_path):
    calls = []
    controller_mod.start(tmp_path, target=100, spawn=_kwargs_spawn(calls))
    try:
        retargeted = controller_mod.retarget(
            tmp_path, target=500,
            arxiv_categories=["cs.LG"], arxiv_date_from="2019-01-01", ordering="relevance",
            spawn=_kwargs_spawn(calls),
        )
        assert retargeted["arxiv_categories"] == ["cs.LG"]
        assert retargeted["arxiv_date_from"] == "2019-01-01"
        assert retargeted["ordering"] == "relevance"
    finally:
        _cleanup(retargeted)


# --- OG-49#1: base config loads from data_dir, not the dashboard process's own cwd ---------------


def test_override_run_resolves_db_path_under_data_dir_not_repo_root(tmp_path):
    """OG-49#1: an overridden run must load its BASE config from data_dir/config.yaml (falling
    back to the repo-root config only when data_dir has none of its own) and resolve every
    relative path field absolute against data_dir -- never against the dashboard SERVER process's
    own cwd (which could be the repo root, the exact live-dangerous bug)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.yaml").write_text(
        "focus_area_queries: ['test query']\n"
        "db_path: papers.db\n"
        "blob_dir: blobs\n"
        "pdf_cache_dir: pdf_cache\n"
    )
    calls = []
    manifest = controller_mod.start(
        data_dir, target=100, keywords=["zzz-extra-keyword"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert override_dir != data_dir  # an edit -- real override scratch dir
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert Path(written_cfg.db_path).is_absolute()
        assert Path(written_cfg.db_path).is_relative_to(data_dir), (
            f"db_path {written_cfg.db_path!r} must resolve under data_dir={data_dir}, not "
            "wherever the dashboard process's own cwd happens to be"
        )
        assert Path(written_cfg.blob_dir).is_relative_to(data_dir)
        assert Path(written_cfg.pdf_cache_dir).is_relative_to(data_dir)
        assert written_cfg.db_path == str(data_dir / "papers.db")
    finally:
        _cleanup(manifest)


def test_start_falls_back_to_repo_root_config_when_data_dir_has_none(tmp_path):
    """No data_dir/config.yaml (e.g. a fresh/test data dir) -- must fall back to the repo-root
    config, same as every other existing test in this file relies on implicitly."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    manifest = controller_mod.start(
        tmp_path, target=100, keywords=["zzz-fallback-test"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        written_cfg = controller_mod.load_config(override_dir / "config.yaml")
        assert written_cfg.focus_area_queries == base_cfg.focus_area_queries + ["zzz-fallback-test"]
    finally:
        _cleanup(manifest)


# --- OG-49#6/M8: model_copy(update=) bypasses validation -- re-validated pre-spawn ---------------


def test_start_rejects_an_invalid_override_before_spawning(tmp_path):
    """A bad override value (parse_batch_size must be > 0, contracts/config.py) must be rejected
    by `Config.model_validate` BEFORE any subprocess is spawned -- not accepted by `model_copy`
    and left to crash the subprocess later, after the manifest already says 'running'."""
    calls = []
    with pytest.raises(InvalidOverrideError):
        controller_mod.start(
            tmp_path, target=100, parse_batch_size=-1, spawn=_kwargs_spawn(calls),
        )
    assert calls == [], "must never reach spawn -- rejected pre-spawn"
    assert not (tmp_path / "run_manifest.json").exists()


# --- OG-49#5: pause/stop escalate past a single SIGTERM ------------------------------------------


def test_pause_escalates_to_sigkill_when_process_ignores_sigterm(tmp_path, monkeypatch):
    """A process wedged in a blocking call that swallows SIGTERM (e.g. mid-syscall in a parse/
    generation/rerank request to one of its backing services) must still get killed -- resend
    SIGTERM, then SIGKILL the process group, before giving up. Shrink the escalation timeouts so
    this test doesn't take ~14s wall-clock."""
    monkeypatch.setattr(controller_mod, "_DEATH_TIMEOUT_S", 0.3)
    monkeypatch.setattr(controller_mod, "_ESCALATION_RESEND_TIMEOUT_S", 0.3)
    monkeypatch.setattr(controller_mod, "_ESCALATION_KILL_TIMEOUT_S", 0.3)

    def spawn(data_dir, target, parse_workers, events_path, log_path):
        # The leader (bash) ignores SIGTERM forever; individual `sleep 0.1`s inside the loop each
        # die to the group SIGTERM independently but the loop just spawns another -- the leader
        # pid itself only ever dies to SIGKILL.
        proc = subprocess.Popen(
            ["bash", "-c", "trap '' TERM; while true; do sleep 0.1; done"],
            start_new_session=True,
        )
        return proc.pid

    manifest = controller_mod.start(tmp_path, target=100, spawn=spawn)
    try:
        paused = controller_mod.pause(tmp_path)
        assert paused["status"] == "paused"
        assert not controller_mod._pid_running(manifest["pid"])
    finally:
        _cleanup(manifest)


def test_stop_escalates_to_sigkill_when_process_ignores_sigterm(tmp_path, monkeypatch):
    monkeypatch.setattr(controller_mod, "_DEATH_TIMEOUT_S", 0.3)
    monkeypatch.setattr(controller_mod, "_ESCALATION_RESEND_TIMEOUT_S", 0.3)
    monkeypatch.setattr(controller_mod, "_ESCALATION_KILL_TIMEOUT_S", 0.3)

    def spawn(data_dir, target, parse_workers, events_path, log_path):
        proc = subprocess.Popen(
            ["bash", "-c", "trap '' TERM; while true; do sleep 0.1; done"],
            start_new_session=True,
        )
        return proc.pid

    manifest = controller_mod.start(tmp_path, target=100, spawn=spawn)
    try:
        stopped = controller_mod.stop(tmp_path)
        assert stopped["status"] == "done"
        assert not controller_mod._pid_running(manifest["pid"])
    finally:
        _cleanup(manifest)


# --- OG-47#1: ALL control ops serialized under one data_dir/.control.lock ------------------------


def test_control_lock_is_mutually_exclusive(tmp_path):
    lock_a = controller_mod._control_lock(tmp_path)
    with lock_a:
        lock_b = controller_mod._control_lock(tmp_path)
        with pytest.raises(controller_mod.filelock.Timeout):
            with lock_b.acquire(timeout=0.1):
                pass


def test_concurrent_starts_are_serialized_exactly_one_run(tmp_path):
    """OG-47#1: two concurrent POST /api/control starts must not both pass the double-run guard.
    A slow fake spawn widens the race window the OLD (unlocked) code would fall into -- without
    the control lock, both threads' `reconcile()` would see no manifest yet (the first is still
    mid-spawn) and both would proceed to spawn + write, giving 2 successes/0 errors. With the
    lock, exactly one succeeds and the other deterministically sees the first's manifest."""
    results = []
    errors = []

    def slow_spawn(data_dir, target, parse_workers, events_path, log_path):
        time.sleep(0.3)
        return _fake_spawn(data_dir, target, parse_workers, events_path, log_path)

    def worker(target, delay):
        time.sleep(delay)
        try:
            results.append(controller_mod.start(tmp_path, target=target, spawn=slow_spawn))
        except DoubleRunError as e:
            errors.append(e)

    t1 = threading.Thread(target=worker, args=(100, 0.0))
    t2 = threading.Thread(target=worker, args=(200, 0.05))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    try:
        assert len(results) == 1, f"expected exactly one successful start, got {len(results)}"
        assert len(errors) == 1, f"expected exactly one DoubleRunError, got {len(errors)}"
        manifest = controller_mod._read_manifest(tmp_path)
        assert manifest["status"] == "running"
        assert manifest["pid"] == results[0]["pid"]
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


# --- T-DOC78: free_gpu() / load_for_mcp() -- explicit, on-demand TEI eviction/reload -----------


def test_free_gpu_refused_while_a_full_run_is_running(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        calls = []
        with pytest.raises(DoubleRunError):
            controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == [], "must refuse BEFORE calling stop_tei, not race it"
    finally:
        _cleanup(manifest)


def test_free_gpu_refused_while_a_full_run_is_pausing_not_yet_confirmed_dead(tmp_path, monkeypatch):
    """SIGTERM sent (status: "pausing") but the process hasn't confirmed dead yet -- still
    potentially mid-Pass-2 embed/rerank, same risk as "running"."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        manifest["status"] = "pausing"
        (tmp_path / "run_manifest.json").write_text(json.dumps(manifest))
        monkeypatch.setattr(controller_mod, "_wait_for_death", lambda pid, timeout_s=None: False)
        calls = []
        with pytest.raises(DoubleRunError):
            controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == []
    finally:
        _cleanup(manifest)


def test_free_gpu_allowed_while_a_full_run_is_paused(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        controller_mod.pause(tmp_path)
        calls = []
        result = controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == ["stopped"]
        assert result == {"tei_stopped": True}
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


def test_free_gpu_allowed_while_a_download_only_run_is_running(tmp_path):
    """Download-only mode never touches TEI -- freeing the GPU while it's live is always safe."""
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        calls = []
        result = controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
        assert calls == ["stopped"]
        assert result == {"tei_stopped": True}
    finally:
        _cleanup(manifest)


def test_free_gpu_allowed_with_no_run_at_all(tmp_path):
    calls = []
    result = controller_mod.free_gpu(tmp_path, stop_tei=lambda: calls.append("stopped"))
    assert calls == ["stopped"]
    assert result == {"tei_stopped": True}


def test_load_for_mcp_always_allowed_even_while_a_full_run_is_running(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        calls = []
        result = controller_mod.load_for_mcp(tmp_path, start_tei=lambda: calls.append("started"))
        assert calls == ["started"]
        assert result == {"tei_started": True}
    finally:
        _cleanup(manifest)


def test_load_for_mcp_with_no_run_at_all(tmp_path):
    calls = []
    result = controller_mod.load_for_mcp(tmp_path, start_tei=lambda: calls.append("started"))
    assert calls == ["started"]
    assert result == {"tei_started": True}


def test_load_for_mcp_refused_while_pass1_is_actively_running(tmp_path):
    """T-DOC78 (fix round 3): load_for_mcp had NO guard at all against the same OOM risk free_gpu
    already guards against, via a different entry point -- clicking "Load for MCP" during Pass 1
    (e.g. because the dashboard's own "TEI embed: down" indicator, which is exactly what an
    operator sees during Pass 1, invites the click) must not reload TEI's ~9.4GB against the parse
    phase's ~1GB safety margin."""
    lock_path = controller_mod.tei_lifecycle.pass1_lock_path(str(tmp_path / "papers.db"))
    holder = filelock.FileLock(str(lock_path))
    holder.acquire()
    try:
        calls = []
        with pytest.raises(DoubleRunError):
            controller_mod.load_for_mcp(tmp_path, start_tei=lambda: calls.append("started"))
        assert calls == [], "must refuse BEFORE calling start_tei, not race it"
    finally:
        holder.release()


def test_load_for_mcp_allowed_when_pass1_is_not_active(tmp_path):
    """Sanity check: the guard is specific to an ACTIVELY held Pass-1 lock, not to a lock file
    merely existing at that path -- with no Pass 1 in flight (the common case), load_for_mcp
    behaves exactly as it did before this guard existed."""
    calls = []
    result = controller_mod.load_for_mcp(tmp_path, start_tei=lambda: calls.append("started"))
    assert calls == ["started"]
    assert result == {"tei_started": True}
