"""Tests for `app.doctor` (T-DOC43/T-DOC52) -- offline, no real Docker/GPU/network calls.

Every health check is driven through `monkeypatch.setattr(doctor_mod, "_is_healthy", ...)` (a
plain function, controllable per-URL) rather than a real socket -- this module deliberately uses
stdlib `urllib` instead of `httpx` (see its module docstring: `httpx`/`grobid`/`qdrant`/`ollama`
are vendor-restricted tokens under `ci/checks/vendor_isolation.py`'s `VENDOR_RULES`, allowed only
in their own adapter file, and extending that allowlist is a foundation-protected `ci/` change
outside this ticket's file territory), so there's no `httpx.MockTransport` seam to reuse the way
`app/test_tei_lifecycle.py` does.
"""

import shutil
import subprocess
from pathlib import Path

import filelock

from contracts.config import Config

import app.doctor as doctor_mod
from app.doctor import (
    PreflightIssue,
    check_disk_headroom,
    check_gpu_headroom,
    check_gpu_lock_free,
    check_services,
    format_issues,
    run_preflight,
)


# ---------------------------------------------------------------------------
# check_disk_headroom
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, free_bytes: int):
        self.free = free_bytes


def test_check_disk_headroom_passes_when_plenty_free(monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _FakeUsage(100 * 1024**3))
    assert check_disk_headroom(".", min_free_gib=5.0) is None


def test_check_disk_headroom_fails_with_named_reason_when_low(monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _FakeUsage(int(1.5 * 1024**3)))
    issue = check_disk_headroom(".", min_free_gib=5.0)
    assert isinstance(issue, PreflightIssue)
    assert issue.check == "disk"
    assert "1.5" in issue.detail


# ---------------------------------------------------------------------------
# check_gpu_headroom (reuses app/gpu_headroom.py -- T-DOC43 "reuse if it fits")
# ---------------------------------------------------------------------------


def test_check_gpu_headroom_passes_when_plenty_free(monkeypatch):
    monkeypatch.setattr(doctor_mod.gpu_headroom, "free_vram_mib", lambda: 20_000)
    assert check_gpu_headroom(min_free_mib=2000) is None


def test_check_gpu_headroom_fails_with_named_reason_when_low(monkeypatch):
    monkeypatch.setattr(doctor_mod.gpu_headroom, "free_vram_mib", lambda: 500)
    issue = check_gpu_headroom(min_free_mib=2000)
    assert issue is not None
    assert issue.check == "gpu"
    assert "500" in issue.detail


def test_check_gpu_headroom_fails_when_probe_cannot_read_vram(monkeypatch):
    """`app/gpu_headroom.py`'s own contract: `None` on any failure -- doctor must treat that as
    an issue, not silently pass."""
    monkeypatch.setattr(doctor_mod.gpu_headroom, "free_vram_mib", lambda: None)
    issue = check_gpu_headroom(min_free_mib=2000)
    assert issue is not None
    assert issue.check == "gpu"


# ---------------------------------------------------------------------------
# check_gpu_lock_free
# ---------------------------------------------------------------------------


def test_check_gpu_lock_free_passes_when_unheld(tmp_path):
    lock_path = str(tmp_path / ".gpu.lock")
    assert check_gpu_lock_free(lock_path) is None


def test_check_gpu_lock_free_fails_with_named_reason_when_held(tmp_path):
    lock_path = str(tmp_path / ".gpu.lock")
    holder = filelock.FileLock(lock_path)
    holder.acquire(timeout=0)
    try:
        issue = check_gpu_lock_free(lock_path)
        assert issue is not None
        assert issue.check == "gpu_lock"
        assert lock_path in issue.detail
    finally:
        holder.release()


def test_check_gpu_lock_free_never_holds_the_lock_past_returning(tmp_path):
    """The probe must release its own zero-timeout acquire immediately -- a real orchestrator
    acquiring the lock right after preflight must not find it still held by this check."""
    lock_path = str(tmp_path / ".gpu.lock")
    assert check_gpu_lock_free(lock_path) is None

    real_lock = filelock.FileLock(lock_path)
    real_lock.acquire(timeout=0)  # must not raise -- doctor's probe released it
    real_lock.release()


# ---------------------------------------------------------------------------
# check_services / run_preflight -- healthy, unhealthy, and T-DOC52 auto-start
# ---------------------------------------------------------------------------


def _all_healthy(monkeypatch):
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: True)


def test_check_services_passes_when_everything_healthy(monkeypatch):
    _all_healthy(monkeypatch)
    assert check_services() == []


def test_check_services_fails_with_named_reason_when_a_service_is_down(monkeypatch):
    """T-DOC43: a down service must be named, not just "something failed"."""
    down_url = doctor_mod._HEALTH_ONLY_SERVICES[0].health_url

    def fake_is_healthy(url: str) -> bool:
        return url != down_url

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)

    issues = check_services()

    assert len(issues) == 1
    assert issues[0].check == doctor_mod._HEALTH_ONLY_SERVICES[0].name
    assert down_url in issues[0].detail


def test_check_services_reports_multiple_down_services_in_one_pass(monkeypatch):
    down_urls = {
        doctor_mod._TEI_EMBED_HEALTH_URL,
        doctor_mod._HEALTH_ONLY_SERVICES[1].health_url,
    }

    def fake_is_healthy(url: str) -> bool:
        return url not in down_urls

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)

    issues = check_services()

    checks = {issue.check for issue in issues}
    assert "TEI embedder" in checks
    assert doctor_mod._HEALTH_ONLY_SERVICES[1].name in checks
    assert len(issues) == 2


def test_check_services_auto_starts_a_down_tei_container_via_tei_lifecycle(monkeypatch):
    """T-DOC52: a down TEI endpoint gets one recovery attempt through the already-tested
    `app.tei_lifecycle.start_tei_containers()` before being reported -- reused, not
    reimplemented. If the (mocked) restart "fixes" the endpoint, no issue is reported."""
    healthy = {"embed": False}
    calls = []

    def fake_is_healthy(url: str) -> bool:
        if url == doctor_mod._TEI_EMBED_HEALTH_URL:
            return healthy["embed"]
        return True

    def fake_start_tei_containers() -> None:
        calls.append("start_tei_containers")
        healthy["embed"] = True  # simulate the container coming up healthy after restart

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", fake_start_tei_containers)

    issues = check_services(auto_start=True)

    assert calls == ["start_tei_containers"]
    assert issues == []


def test_check_services_reports_tei_as_down_if_auto_start_does_not_fix_it(monkeypatch):
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: False)
    calls = []
    monkeypatch.setattr(
        doctor_mod.tei_lifecycle, "start_tei_containers", lambda: calls.append("start")
    )

    issues = check_services(auto_start=True)

    assert calls == ["start"], "must still attempt recovery exactly once"
    checks = {issue.check for issue in issues}
    assert "TEI embedder" in checks
    assert "TEI reranker" in checks


def test_check_services_no_auto_start_never_attempts_a_restart(monkeypatch):
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: False)
    calls = []
    monkeypatch.setattr(
        doctor_mod.tei_lifecycle, "start_tei_containers", lambda: calls.append("start")
    )

    check_services(auto_start=False)

    assert calls == [], "auto_start=False must never attempt a TEI restart"


# ---------------------------------------------------------------------------
# run_preflight -- the full T-DOC43 gate
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path) -> Config:
    return Config(focus_area_queries=["x"], gpu_lock_path=str(tmp_path / ".gpu.lock"))


def test_run_preflight_passes_when_everything_healthy(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _FakeUsage(100 * 1024**3))
    monkeypatch.setattr(doctor_mod.gpu_headroom, "free_vram_mib", lambda: 20_000)
    _all_healthy(monkeypatch)

    assert run_preflight(_cfg(tmp_path)) == []


def test_run_preflight_fails_with_named_reason_when_a_service_is_down(monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _FakeUsage(100 * 1024**3))
    monkeypatch.setattr(doctor_mod.gpu_headroom, "free_vram_mib", lambda: 20_000)

    down_url = doctor_mod._HEALTH_ONLY_SERVICES[1].health_url

    def fake_is_healthy(url: str) -> bool:
        return url != down_url

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)

    issues = run_preflight(_cfg(tmp_path))

    assert len(issues) == 1
    assert issues[0].check == doctor_mod._HEALTH_ONLY_SERVICES[1].name


def test_run_preflight_reports_every_kind_of_issue_at_once(monkeypatch, tmp_path):
    """T-DOC43: "one clear message naming what's missing" -- multiple simultaneous problems
    (disk, GPU, a down service) must all surface together, not just the first one hit."""
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _FakeUsage(int(0.1 * 1024**3)))
    monkeypatch.setattr(doctor_mod.gpu_headroom, "free_vram_mib", lambda: None)
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: False)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)

    issues = run_preflight(_cfg(tmp_path), auto_start=False)

    checks = {issue.check for issue in issues}
    assert "disk" in checks
    assert "gpu" in checks
    assert "TEI embedder" in checks
    message = format_issues(issues)
    assert str(len(issues)) in message
    for issue in issues:
        assert str(issue) in message


# ---------------------------------------------------------------------------
# T-DOC52: docker-start pattern reused for TEI, but NOT reimplemented for the two other
# containerized services (see module docstring for why -- vendor-restricted container names)
# ---------------------------------------------------------------------------


def test_health_only_services_never_shell_out_to_docker(monkeypatch):
    """The two containerized health-only services must never trigger a `docker start` -- doctor
    has no container name for them at all (by design, see module docstring)."""
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: False)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)

    check_services(auto_start=True)

    assert calls == [], "doctor must never shell out to docker directly for the health-only services"
