"""Tests for `app.dashboard.controller` -- offline, no real GPU/network/ingest. Every
start/resume uses a FAKE `spawn` that launches a harmless `sleep` subprocess (never
`python -m app.ingest`), so these tests exercise the real signaling/process-group/identity-
verification machinery against a real (but harmless) OS process without ever touching the GPU.
"""

import json
import os
import signal
import subprocess
import time

import pytest

import app.dashboard.controller as controller_mod
from app.dashboard.controller import DoubleRunError, NoRunError


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
    production) -- reconcile()/the guard must not treat that as still running."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
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
