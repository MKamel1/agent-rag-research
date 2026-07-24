"""Tests for `app.doctor` (T-DOC43/T-DOC52/T-DOC78) -- offline, no real Docker/GPU/network calls.

Every health check is driven through `monkeypatch.setattr(doctor_mod, "_is_healthy", ...)` (a
plain function, controllable per-URL) rather than a real socket -- `app.doctor` deliberately uses
a stdlib HTTP call instead of a third-party client (see that module's own docstring for why), so
there's no mock-transport seam to reuse the way `app/test_tei_lifecycle.py` does. The two
health-only services' recovery paths (T-DOC78) are stubbed via `monkeypatch.setattr` on
`doctor_mod._parser_adapter`/`doctor_mod._vector_index_adapter` -- never a real `docker`/network
call, same reasoning `app/test_tei_lifecycle.py` gives for faking `subprocess.run`.
"""

import shutil
from pathlib import Path

import filelock

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
from contracts.config import Config

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


def _stub_health_only_starts(monkeypatch):
    """The two containerized health-only services (parser reference-resolution, vector store)
    now carry a real recovery path (T-DOC78) -- any test that leaves them down with
    `auto_start=True` (the default) must stub both adapters' start functions, or `check_services`
    will try to actually shell out to `docker`."""
    monkeypatch.setattr(
        doctor_mod._parser_adapter, "start_reference_resolution_container", lambda: None
    )
    monkeypatch.setattr(doctor_mod._vector_index_adapter, "start_container", lambda: None)


def test_check_services_fails_with_named_reason_when_a_service_is_down(monkeypatch):
    """T-DOC43: a down service must be named, not just "something failed"."""
    down_url = doctor_mod._HEALTH_ONLY_SERVICES[0].health_url

    def fake_is_healthy(url: str) -> bool:
        return url != down_url

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)
    _stub_health_only_starts(monkeypatch)

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
    _stub_health_only_starts(monkeypatch)

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
    _stub_health_only_starts(monkeypatch)

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
    _stub_health_only_starts(monkeypatch)

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
# T-DOC78: the parser reference-resolution service and vector store now get the same one-shot
# recovery attempt as TEI, routed through their own adapter's `start_...` helper (never through a
# vendor name/container this module names itself -- see module docstring for why).
# ---------------------------------------------------------------------------


def test_check_services_auto_starts_a_down_reference_resolution_service(monkeypatch):
    """A down parser reference-resolution endpoint gets one recovery attempt through
    `rag.parser.start_reference_resolution_container` before being reported -- if the (mocked)
    restart "fixes" the endpoint, no issue is reported."""
    down_url = doctor_mod._HEALTH_ONLY_SERVICES[0].health_url
    healthy = {"down": False}
    calls = []

    def fake_is_healthy(url: str) -> bool:
        if url == down_url:
            return healthy["down"]
        return True

    def fake_start() -> None:
        calls.append("start_reference_resolution_container")
        healthy["down"] = True

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)
    monkeypatch.setattr(
        doctor_mod._parser_adapter, "start_reference_resolution_container", fake_start
    )
    monkeypatch.setattr(doctor_mod._vector_index_adapter, "start_container", lambda: None)

    issues = check_services(auto_start=True)

    assert calls == ["start_reference_resolution_container"]
    assert issues == []


def test_check_services_auto_starts_a_down_vector_store(monkeypatch):
    """Same recovery path, for the vector store, through `rag.vector_index.start_container`."""
    down_url = doctor_mod._HEALTH_ONLY_SERVICES[1].health_url
    healthy = {"down": False}
    calls = []

    def fake_is_healthy(url: str) -> bool:
        if url == down_url:
            return healthy["down"]
        return True

    def fake_start() -> None:
        calls.append("start_container")
        healthy["down"] = True

    monkeypatch.setattr(doctor_mod, "_is_healthy", fake_is_healthy)
    monkeypatch.setattr(
        doctor_mod._parser_adapter, "start_reference_resolution_container", lambda: None
    )
    monkeypatch.setattr(doctor_mod._vector_index_adapter, "start_container", fake_start)

    issues = check_services(auto_start=True)

    assert calls == ["start_container"]
    assert issues == []


def test_check_services_reports_health_only_service_still_down_if_start_does_not_fix_it(
    monkeypatch,
):
    """If the (mocked) restart doesn't bring the endpoint up, it's still reported as an issue --
    same "attempt once, then report if still broken" contract as TEI."""
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: False)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)
    calls = []
    monkeypatch.setattr(
        doctor_mod._parser_adapter,
        "start_reference_resolution_container",
        lambda: calls.append("parser"),
    )
    monkeypatch.setattr(
        doctor_mod._vector_index_adapter, "start_container", lambda: calls.append("vector_index")
    )

    issues = check_services(auto_start=True)

    assert calls == ["parser", "vector_index"], "must still attempt recovery exactly once each"
    checks = {issue.check for issue in issues}
    assert doctor_mod._HEALTH_ONLY_SERVICES[0].name in checks
    assert doctor_mod._HEALTH_ONLY_SERVICES[1].name in checks


def test_check_services_never_auto_starts_the_summarizer_host_service(monkeypatch):
    """The summarizer's model-serving endpoint has no recovery path (`start=None`) -- it's a host
    service, not a container, T-DOC43's original scope note, unaffected by T-DOC78."""
    assert doctor_mod._HEALTH_ONLY_SERVICES[2].start is None


def test_check_services_no_auto_start_never_attempts_health_only_recovery(monkeypatch):
    """`auto_start=False` must skip the parser/vector-store recovery attempt too, not just TEI's."""
    monkeypatch.setattr(doctor_mod, "_is_healthy", lambda url: False)
    monkeypatch.setattr(doctor_mod.tei_lifecycle, "start_tei_containers", lambda: None)
    calls = []
    monkeypatch.setattr(
        doctor_mod._parser_adapter,
        "start_reference_resolution_container",
        lambda: calls.append("parser"),
    )
    monkeypatch.setattr(
        doctor_mod._vector_index_adapter, "start_container", lambda: calls.append("vector_index")
    )

    check_services(auto_start=False)

    assert calls == [], "auto_start=False must never attempt a health-only-service restart"
