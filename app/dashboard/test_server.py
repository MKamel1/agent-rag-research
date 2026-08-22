"""Smoke tests for `app.dashboard.server`'s HTTP routes -- a real `ThreadingHTTPServer` bound to
127.0.0.1:0 (an ephemeral port) driven with real `urllib` requests, but `status_module`/
`controller_module` are FAKES (no real DB, manifest, or subprocess) -- proves the routes exist,
parse bodies correctly, and return the exact API-contract shape, without touching anything real.
"""

import json
import os
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date
from functools import partial

import pytest

import app.dashboard.controller as controller_mod
import app.dashboard.server as server_mod
import app.dashboard.status as status_mod
from app.dashboard.controller import DoubleRunError, DropInPendingError, NoRunError
from app.dashboard.test_status import _write_fake_proc_entry
from app.dashboard.server import _LazyMcpServer, _status_dict, build_server
from contracts.errors import TransientError
from contracts.mcp_server import Coverage, SearchResponse
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult
from contracts.vector_index import SearchFilters
from migrations.migrate import migrate

# These tests bind a real loopback (127.0.0.1) socket -- no external network, no vendor -- so they
# opt out of the suite's default `--disable-socket` (pytest.ini) the same way
# `rag/test_vector_index.py` does for its own real-transport tests, but WITHOUT `real_adapter`
# (that marker is for tests needing real external vendor infra; a loopback HTTP round-trip against
# fakes belongs in the default suite `pytest app/dashboard/ -q` runs).
pytestmark = pytest.mark.enable_socket

_TOKEN = "secret-token"


class _FakeStatus:
    """Fixed, known snapshot pieces -- `_status_dict` in server.py composes these into the full
    `/api/status` shape."""

    def read_corpus(self, data_dir):
        return {
            "funnel": {
                "harvested": 10, "parsed": 9, "chunked": 8, "summarized": 7,
                "embedded": 6, "stored": 5, "done": 5, "quarantined": 1,
            },
            "by_doc_type": {
                "book": {
                    "harvested": 2, "parsed": 2, "chunked": 1, "summarized": 1,
                    "embedded": 1, "stored": 1, "done": 1, "quarantined": 0,
                },
                "paper": {
                    "harvested": 8, "parsed": 7, "chunked": 7, "summarized": 6,
                    "embedded": 5, "stored": 4, "done": 4, "quarantined": 1,
                },
            },
            "quarantine_reasons": [{"reason": "TransientError @ parsed", "count": 1}],
        }

    def read_telemetry(self, events_path, total_done, *, data_dir=None, started_at=None, target=None):
        return {
            "stage": "finish", "papers_per_hour": 12.5, "wall_clock_s": 300.0, "eta_s": 900.0,
            "gpu_util_pct": 80.0, "vram_mib": 9000, "power_w": 200.0,
        }

    def read_downloads(self, data_dir, prefetch_target, run_cwd=None):
        return {
            "staged_pdfs": 20, "sidecars": 15, "prefetch_target": prefetch_target,
            "stalled": False, "new_last_pass": None,
        }

    def read_consistency(self, done_count, collection):
        return {"sqlite_done": done_count, "vector_points": 500, "consistent": True}

    def read_downloader(self, run_cwd, manifest_pid=None, *, live_pids=None, data_dir=None):
        return {
            "prefetch_alive": True, "downloaded": 120, "prefetch_target": 30000,
            "live_pids": [], "orphan": False, "tracked_pid": None, "tags_pending": None,
        }

    @staticmethod
    def _live_prefetch_pids(data_dir=None):
        # RI-19: the route composes this with the dashboard's own data_dir bound, so the stub
        # must accept it (a zero-arg signature hid the real function's data_dir=None default).
        return []

    def read_disk(self, data_dir):
        return {"free_gb": 500.0, "total_gb": 1000.0, "used_pct": 50.0}

    def read_tei_status(self):
        return {"embed_healthy": True, "rerank_healthy": True}

    def read_drop_in(self, drop_dir, db_path):
        return {
            "pending_papers": 2, "pending_books": 1, "staged": 1, "failed": 0, "excluded": 0,
            "failure_reasons": [], "failure_reasons_truncated": False, "manifest_ids": 0,
            "latest_manifest": None, "processed": None, "processed_papers": None,
            "processed_books": None,
        }


class _FakeController:
    def __init__(self):
        self.calls = []

    def liveness(self, data_dir):
        return {
            "run_id": "run-fake", "status": "running", "target": 100, "parse_workers": 3,
            "focus_queries": ["causal inference"], "started_at": "2026-01-01T00:00:00",
            "events_path": "events.jsonl", "collection": "papers",
            "params": {"parse_workers": 3, "limit": 100, "telemetry_poll_interval": None},
            "paper_ids_file": None, "run_cwd": "data_dir", "log_path": "run.log",
            "parse_batch_size": None,
        }

    def start(self, data_dir, target, parse_workers=3, **kwargs):
        self.calls.append(("start", target, parse_workers, kwargs))

    def retarget(self, data_dir, target, parse_workers=3, **kwargs):
        self.calls.append(("retarget", target, parse_workers, kwargs))

    def pause(self, data_dir):
        self.calls.append(("pause",))

    def resume(self, data_dir):
        self.calls.append(("resume",))

    def stop(self, data_dir):
        raise NoRunError("no running run to stop")

    def restart_downloader(self, data_dir, **kwargs):
        self.calls.append(("restart_downloader",))

    def free_gpu(self, data_dir):
        self.calls.append(("free_gpu",))

    def load_for_mcp(self, data_dir):
        self.calls.append(("load_for_mcp",))

    def resolve_drop_dir(self, cfg):
        return "/fake/drop_in"

    def outcome_for_run(self, data_dir, run_id):
        return None

    def promote_pending_drop_in(self, data_dir, spawn=None):
        return None

    def start_drop_in(self, data_dir, **kwargs):
        self.calls.append(("start_drop_in",))

    DoubleRunError = DoubleRunError
    NoRunError = NoRunError
    DropInPendingError = DropInPendingError


@pytest.fixture
def running_server(tmp_path):
    fake_status = _FakeStatus()
    fake_controller = _FakeController()
    httpd = build_server(
        tmp_path, _TOKEN, port=0, host="127.0.0.1",
        status_module=fake_status, controller_module=fake_controller,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}", fake_controller
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)


def _get(url, path, token=_TOKEN):
    # OG-48#1/OG-49#4: GET /api/status and /api/search are now token-gated, same header
    # `POST /api/control` already required -- every test that expects a successful GET must send
    # it. `token=None` omits the header entirely (the 401-without-token tests use this).
    headers = {} if token is None else {"X-Dashboard-Token": token}
    req = urllib.request.Request(url + path, headers=headers)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return resp.status, json.loads(resp.read())


def _get_raw(url, path):
    with urllib.request.urlopen(url + path, timeout=5.0) as resp:
        return resp.status, resp.read()


def _post(url, path, body, token=_TOKEN):
    req = urllib.request.Request(
        url + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Dashboard-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# --- GET / -------------------------------------------------------------------------------------


def test_root_serves_html(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b"Corpus Dashboard" in body


def test_root_is_reachable_without_a_token(running_server):
    # "/" stays open (OG-48#1/OG-49#4) -- only the static frontend shell, no corpus content.
    url, _ = running_server
    status, _body = _get_raw(url, "/")
    assert status == 200


def test_root_html_persists_token_and_distinguishes_auth_errors_from_staleness(running_server):
    """Regression guard for the "dashboard shows stale/reconnecting on every page load" bug: the
    #token field had no persistence (every reload started empty -> first poll() 401'd -> the old
    poll() crashed rendering the {ok:false} body -> generic 'stale / reconnecting'). The fix
    persists the token via localStorage and makes poll() check `resp.ok` before calling render(),
    so a reachable-but-unauthorized response shows the real message instead."""
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b"localStorage" in body
    assert b"resp.ok" in body


def test_root_html_has_download_now_button_wired_to_the_download_action(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="btnDownloadOnly"' in body
    assert b'"download"' in body


def test_root_html_has_free_gpu_and_load_for_mcp_buttons(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="btnFreeGpu"' in body
    assert b'"free_gpu"' in body
    assert b'id="btnLoadForMcp"' in body
    assert b'"load_for_mcp"' in body


def test_root_html_has_the_supply_exhausted_outcome_line(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="outcomeLine"' in body
    assert b"arXiv exhausted" in body
    assert b"supply_exhausted" in body


def test_root_html_has_restart_downloader_button(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="btnRestartDownloader"' in body
    assert b'"restart_downloader"' in body


def test_root_html_mode_indicator_branches_on_download_mode(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b"download-only" in body


def test_root_html_has_drop_in_panel_wired_to_the_start_drop_in_action(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="btnStartDropIn"' in body
    assert b'"start_drop_in"' in body


def test_root_html_has_usage_panel(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b"renderUsage" in body
    # available: false must render "no usage recorded yet", not a wall of zeros.
    assert b"no usage recorded yet" in body


# --- OG-48#1/OG-49#4: GET /api/status and GET /api/search are now token-gated ------------------


def test_status_route_without_token_is_401(running_server):
    url, _ = running_server
    status, body = _get_allow_error(url, "/api/status", token=None)
    assert status == 401
    assert body["ok"] is False


def test_status_route_with_wrong_token_is_401(running_server):
    url, _ = running_server
    status, body = _get_allow_error(url, "/api/status", token="wrong-token")
    assert status == 401
    assert body["ok"] is False


def test_status_route_with_valid_token_is_200(running_server):
    url, _ = running_server
    status, _body = _get(url, "/api/status", token=_TOKEN)
    assert status == 200


# --- GET /api/status: exact API-contract shape --------------------------------------------------


def test_status_route_shape_matches_api_contract(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert set(body.keys()) == {
        "funnel", "by_doc_type", "run", "telemetry", "downloads", "downloader", "disk",
        "consistency", "quarantine_reasons", "search", "tei", "drop_in", "usage", "tags",
    }
    assert set(body["funnel"].keys()) == {
        "harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done", "quarantined",
    }
    assert set(body["run"].keys()) == {
        "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
        "paper_ids_file", "parse_batch_size", "arxiv_categories", "arxiv_date_from",
        "arxiv_date_to", "ordering", "stranded_policy", "mode", "outcome",
    }
    assert set(body["telemetry"].keys()) == {
        "stage", "papers_per_hour", "gpu_util_pct", "vram_mib", "power_w", "wall_clock_s", "eta_s",
    }
    assert set(body["downloads"].keys()) == {
        "staged_pdfs", "sidecars", "prefetch_target", "stalled", "new_last_pass",
    }
    assert set(body["downloader"].keys()) == {
        "prefetch_alive", "downloaded", "prefetch_target", "live_pids", "orphan", "tracked_pid",
        "tags_pending",
    }
    assert set(body["disk"].keys()) == {"free_gb", "total_gb", "used_pct"}
    assert set(body["consistency"].keys()) == {"sqlite_done", "vector_points", "consistent"}
    assert set(body["search"].keys()) == {
        "top_k_default", "rerank_pool_size", "hybrid_dense_weight",
    }
    assert body["run"]["run_id"] == "run-fake"
    assert body["run"]["params"]["telemetry_poll_interval"] is None
    assert body["run"]["parse_batch_size"] == 4  # config.yaml's real default -- not hard-coded null
    assert body["funnel"]["done"] == 5
    assert body["quarantine_reasons"] == [{"reason": "TransientError @ parsed", "count": 1}]


# --- O-1: run.outcome ("supply_exhausted" or None) -----------------------------------------------


def test_status_route_run_outcome_is_none_by_default(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert body["run"]["outcome"] is None


def test_status_dict_threads_outcome_for_run_into_the_run_block(tmp_path):
    """`_status_dict` must call `controller_module.outcome_for_run(data_dir, run_id)` and surface
    whatever it returns as `run.outcome` -- proven with a controller fake that actually returns a
    value, not just the always-None default `_FakeController` uses everywhere else."""
    calls = []

    class _OutcomeController(_FakeController):
        def outcome_for_run(self, data_dir, run_id):
            calls.append((data_dir, run_id))
            return "supply_exhausted"

    body = _status_dict(tmp_path, _FakeStatus(), _OutcomeController())
    assert body["run"]["outcome"] == "supply_exhausted"
    assert calls == [(tmp_path, "run-fake")]  # "run-fake" is _FakeController.liveness's run_id


# --- D-6 Task 4: downloader block carries orphan/tags_pending, restart control action ----------


def test_status_route_downloader_block_exposes_orphan_and_tags_pending(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    for key in ("live_pids", "orphan", "tags_pending", "tracked_pid"):
        assert key in body["downloader"], f"missing {key}"


def test_control_restart_downloader_calls_controller(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "restart_downloader"})
    assert status == 200
    assert body["ok"] is True
    assert fake_controller.calls == [("restart_downloader",)]


def test_control_restart_downloader_hands_over_a_corpus_scoped_live_pid_scan(
    tmp_path, monkeypatch,
):
    """RI-19: the route must hand `restart_downloader` a scan BOUND to this dashboard's own
    data_dir. RI-8 qualified the COUNTING path (`read_downloader`), but this destructive path
    passed the bare function -- whose `data_dir=None` default degrades to a machine-wide,
    argv-only scan -- so with two corpora live, corpus A's "Restart downloader" SIGTERMed and
    then SIGKILLed corpus B's downloader. A zero-arg stub could never catch that (the real
    function's default was never exercised through this route), so this test keeps every read
    fake EXCEPT the handed-over scan: the real `_live_prefetch_pids`, with only its `proc_root`
    test seam pointed at a synthetic `/proc` tree (same helper `test_status.py` uses), invoked
    through the actual route."""
    own = tmp_path / "corpus-a"
    other = tmp_path / "corpus-b"
    own.mkdir()
    other.mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    monkeypatch.setattr(status_mod.os, "kill", lambda pid, sig: None)
    _write_fake_proc_entry(proc_root, 555601, ["python", "-m", "app.prefetch_pdfs"], cwd=own)
    _write_fake_proc_entry(proc_root, 555602, ["python", "-m", "app.prefetch_pdfs"], cwd=other)

    captured = {}

    class CapturingController(_FakeController):
        def restart_downloader(self, data_dir, **kwargs):
            captured["data_dir"] = data_dir
            captured["live_pids"] = kwargs["live_pids"]

    fake_status = _FakeStatus()
    fake_status._live_prefetch_pids = partial(
        status_mod._live_prefetch_pids, proc_root=proc_root,
    )
    httpd = build_server(
        own, _TOKEN, port=0, host="127.0.0.1",
        status_module=fake_status, controller_module=CapturingController(),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}"
        status, body = _post(url, "/api/control", {"action": "restart_downloader"})
        assert status == 200
        assert body["ok"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)

    assert captured["data_dir"] == own
    # THE assertion: the composed callable excludes corpus B's downloader. With the bare-function
    # bug it runs data_dir=None (argv-only) over the same tree and returns BOTH pids.
    assert captured["live_pids"]() == [555601]


def test_status_route_includes_by_doc_type_block(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert "by_doc_type" in body
    # The combined funnel must survive untouched -- it is what ETA/rate math reads.
    assert "funnel" in body
    assert "done" in body["funnel"]
    assert body["by_doc_type"]["book"]["done"] == 1
    assert body["by_doc_type"]["paper"]["done"] == 4


# --- POST /api/control: token gate + dispatch + shapes -------------------------------------


# --- _status_dict: threads started_at/target into read_telemetry (OG-44) -----------------------


def test_status_dict_threads_started_at_and_target_into_read_telemetry(tmp_path):
    """`_status_dict` must pass `data_dir`, the manifest's `started_at`, and `target` through to
    `status.read_telemetry` -- without these, the per-run rate/ETA fix (status.py) has nothing to
    anchor on."""
    calls = []

    class SpyStatus(_FakeStatus):
        def read_telemetry(self, events_path, total_done, *, data_dir=None, started_at=None, target=None):
            calls.append(
                {
                    "events_path": events_path, "total_done": total_done,
                    "data_dir": data_dir, "started_at": started_at, "target": target,
                }
            )
            return super().read_telemetry(events_path, total_done)

    _status_dict(tmp_path, SpyStatus(), _FakeController())

    assert len(calls) == 1
    call = calls[0]
    assert call["events_path"] == "events.jsonl"
    assert call["total_done"] == 5  # corpus["funnel"]["done"]
    assert call["data_dir"] == tmp_path
    assert call["started_at"] == "2026-01-01T00:00:00"
    assert call["target"] == 100


# T-1 (docs/TEST-AUDIT-2026-07-31.md): the only test above joining `_status_dict` with
# `status.read_corpus` uses `_FakeStatus`, which hardcodes `funnel["done"] = 5` -- it never
# exercises the real `_funnel_from_stage_counts`. If that function's "done" key were ever renamed,
# nested, or dropped, `_status_dict`'s `corpus["funnel"].get("done")` would silently become `None`
# and no test would fail. This drives a REAL `status.read_corpus` against a real migrated sqlite
# db, and spies on the real `status.read_telemetry` to capture the `total_done` it actually
# receives -- closing that gap.
def test_status_dict_threads_real_read_corpus_done_into_read_telemetry(tmp_path):
    migrate(str(tmp_path / "papers.db"))
    conn = sqlite3.connect(str(tmp_path / "papers.db"))
    for i, stage in enumerate(["done", "done", "done", "parsed"]):
        conn.execute(
            "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, ?)",
            (f"p{i}", stage, "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()

    calls = []
    real_read_telemetry = status_mod.read_telemetry

    class RealStatusSpy:
        """Every read is the REAL `status` module function -- only `read_telemetry` is wrapped, to
        record the `total_done` it's called with, matching this file's existing spy-around-a-real-
        implementation pattern (`super().read_telemetry(...)` above) rather than a from-scratch
        fake."""

        read_corpus = staticmethod(status_mod.read_corpus)
        read_downloads = staticmethod(status_mod.read_downloads)
        read_consistency = staticmethod(status_mod.read_consistency)
        read_downloader = staticmethod(status_mod.read_downloader)
        read_disk = staticmethod(status_mod.read_disk)
        read_tei_status = staticmethod(status_mod.read_tei_status)
        read_drop_in = staticmethod(status_mod.read_drop_in)

        def read_telemetry(self, events_path, total_done, **kwargs):
            calls.append(total_done)
            return real_read_telemetry(events_path, total_done, **kwargs)

    _status_dict(tmp_path, RealStatusSpy(), _FakeController())

    assert calls == [3]  # real _funnel_from_stage_counts: 3 "done" + 1 "parsed" behind it


def test_status_dict_passes_prefetch_target_not_the_run_target(tmp_path):
    """Regression: server.py used to pass live.get('target') -- the run's PROCESSING target -- as
    the denominator for DOWNLOADED pdfs, while the downloader aims at cfg.prefetch_target. The fake
    controller's manifest target is 100; config.example.yaml's prefetch_target is 30000 -- if the
    wrong one leaks through, this test catches it."""
    seen = {}

    class SpyStatus(_FakeStatus):
        def read_downloads(self, data_dir, prefetch_target, run_cwd=None):
            seen["prefetch_target"] = prefetch_target
            return super().read_downloads(data_dir, prefetch_target, run_cwd=run_cwd)

    _status_dict(tmp_path, SpyStatus(), _FakeController())

    assert seen["prefetch_target"] == server_mod._static_config(tmp_path).prefetch_target
    assert seen["prefetch_target"] != 100  # the manifest's (unrelated) run target


def test_status_dict_threads_the_manifests_run_cwd_into_read_downloads(tmp_path):
    """RI-30: `downloads.stalled` and `downloader.downloaded` describe the SAME downloader's
    log -- the manifest `run_cwd` the downloader block below already receives must reach
    `read_downloads` too, or an edited run's two downloader fields disagree (the data dir keeps
    the last unedited run's stale log; the live one sits in the override dir)."""
    seen = {}
    override_dir = tmp_path / ".run_overrides" / "run-fake"

    class SpyStatus(_FakeStatus):
        def read_downloads(self, data_dir, prefetch_target, run_cwd=None):
            seen["run_cwd"] = run_cwd
            return super().read_downloads(data_dir, prefetch_target)

    class OverrideCwdController(_FakeController):
        def liveness(self, data_dir):
            manifest = super().liveness(data_dir)
            manifest["run_cwd"] = str(override_dir)
            return manifest

    _status_dict(tmp_path, SpyStatus(), OverrideCwdController())

    assert seen["run_cwd"] == str(override_dir)


def test_control_without_token_is_rejected(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "pause"}, token="wrong")
    assert status == 401
    assert body["ok"] is False
    assert fake_controller.calls == []


def test_control_pause_dispatches_and_returns_ok(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "pause"})
    assert status == 200
    assert body == {"ok": True, "message": "pause ok"}
    assert fake_controller.calls == [("pause",)]


def test_control_free_gpu_dispatches(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "free_gpu"})
    assert status == 200
    assert body["ok"] is True
    assert fake_controller.calls[-1] == ("free_gpu",)


def test_control_load_for_mcp_dispatches(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "load_for_mcp"})
    assert status == 200
    assert fake_controller.calls[-1] == ("load_for_mcp",)


def test_control_free_gpu_refused_while_running_returns_409(running_server):
    url, fake_controller = running_server

    def raise_double_run(data_dir):
        raise DoubleRunError("a full run is actively running")

    fake_controller.free_gpu = raise_double_run
    status, body = _post(url, "/api/control", {"action": "free_gpu"})
    assert status == 409
    assert body["ok"] is False


def test_status_route_includes_tei_block(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert body["tei"] == {"embed_healthy": True, "rerank_healthy": True}


# --- Task 4: drop-in tray block + start_drop_in control action ----------------------------------


def test_status_route_includes_drop_in_block(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    block = body["drop_in"]
    for key in ("pending_papers", "pending_books", "staged", "processed",
                "failed", "excluded", "latest_manifest", "pending_drop_in"):
        assert key in block, f"missing {key}"


def test_status_route_includes_usage_block(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert "usage" in body
    assert "available" in body["usage"]
    # No mcp_usage.db has been written in this tmp_path -- available: false, not a wall of zeros.
    assert body["usage"]["available"] is False


# --- T-DOC41/D-5 Part 2: tag pool block + add/hold/restore_tags control actions ------------------


def test_status_route_includes_tags_block(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert set(body["tags"]) >= {"active", "held", "active_count", "held_count"}
    # First touch seeds from config.example.yaml's own focus_area_queries (RAG_CONFIG, this
    # suite's conftest) -- 33 queries, none held yet.
    assert body["tags"]["active_count"] == len(body["tags"]["active"])
    assert body["tags"]["held_count"] == 0


def test_control_hold_tags_moves_a_tag_to_held(running_server):
    url, _ = running_server
    _, first_status = _get(url, "/api/status")
    a_tag = first_status["tags"]["active"][0]

    resp_status, resp = _post(url, "/api/control", {"action": "hold_tags", "tags": [a_tag]})
    assert resp_status == 200
    assert resp["ok"] is True

    status, body = _get(url, "/api/status")
    assert status == 200
    assert a_tag not in body["tags"]["active"]
    assert a_tag in [h["query"] for h in body["tags"]["held"]]


def test_control_restore_tags_brings_a_held_tag_back(running_server):
    url, _ = running_server
    _, first_status = _get(url, "/api/status")
    a_tag = first_status["tags"]["active"][0]
    _post(url, "/api/control", {"action": "hold_tags", "tags": [a_tag]})

    resp_status, resp = _post(url, "/api/control", {"action": "restore_tags", "tags": [a_tag]})
    assert resp_status == 200
    assert resp["ok"] is True

    status, body = _get(url, "/api/status")
    assert a_tag in body["tags"]["active"]
    assert a_tag not in [h["query"] for h in body["tags"]["held"]]


def test_control_purge_tags_reaches_tag_pool_purge(running_server):
    url, _ = running_server
    _, first_status = _get(url, "/api/status")
    a_tag = first_status["tags"]["active"][0]
    _post(url, "/api/control", {"action": "hold_tags", "tags": [a_tag]})

    resp_status, resp = _post(url, "/api/control", {"action": "purge_tags", "tags": [a_tag]})
    assert resp_status == 200
    assert resp["ok"] is True

    status, body = _get(url, "/api/status")
    assert a_tag not in body["tags"]["active"]
    assert a_tag not in [h["query"] for h in body["tags"]["held"]]


def test_control_purge_tags_on_an_active_tag_returns_400(running_server):
    url, _ = running_server
    _, first_status = _get(url, "/api/status")
    a_tag = first_status["tags"]["active"][0]

    status, resp = _post(url, "/api/control", {"action": "purge_tags", "tags": [a_tag]})
    assert status == 400
    assert resp["ok"] is False

    _, body = _get(url, "/api/status")
    assert a_tag in body["tags"]["active"]  # refused -- pool untouched


def test_control_add_tags_adds_a_new_query(running_server):
    url, _ = running_server
    status, resp = _post(url, "/api/control", {"action": "add_tags", "tags": ["a new topic"]})
    assert status == 200
    assert resp["ok"] is True

    _, body = _get(url, "/api/status")
    assert "a new topic" in body["tags"]["active"]


def test_control_add_tags_rejects_a_quote_injection_tag(running_server):
    url, _ = running_server
    status, resp = _post(url, "/api/control", {"action": "add_tags", "tags": ['bad"tag']})
    assert status == 400
    assert resp["ok"] is False


def test_control_hold_tags_refuses_to_empty_the_pool(running_server):
    url, _ = running_server
    _, first_status = _get(url, "/api/status")
    everything = first_status["tags"]["active"]

    status, resp = _post(url, "/api/control", {"action": "hold_tags", "tags": everything})
    assert status == 400
    assert resp["ok"] is False


def test_control_without_token_is_rejected_for_hold_tags(running_server):
    url, _ = running_server
    req = urllib.request.Request(
        url + "/api/control", data=json.dumps({"action": "hold_tags", "tags": ["x"]}).encode(),
        method="POST", headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5.0)
        raise AssertionError("expected HTTPError")
    except urllib.error.HTTPError as e:
        assert e.code == 401


def test_control_start_drop_in_dispatches_and_returns_ok(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "start_drop_in"})
    assert status == 200
    assert body == {"ok": True, "message": "start_drop_in ok"}
    assert fake_controller.calls == [("start_drop_in",)]


def test_control_start_drop_in_refused_while_a_drop_in_is_already_pending_returns_409(
    running_server,
):
    """Same 409 mapping DoubleRunError/NoRunError already get -- DropInPendingError is a live-run
    contention error too, not a validation error."""
    url, fake_controller = running_server

    def raise_pending(data_dir, **kwargs):
        raise DropInPendingError("a drop-in run is queued and must run first")

    fake_controller.start_drop_in = raise_pending
    status, body = _post(url, "/api/control", {"action": "start_drop_in"})
    assert status == 409
    assert body["ok"] is False


def test_control_start_forwards_target_and_parse_workers(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "start", "target": 500, "parse_workers": 2})
    assert status == 200
    assert fake_controller.calls == [("start", 500, 2, {})]


def test_control_start_forwards_og43_editable_params(running_server):
    """OG-43: telemetry_poll_interval/batch_size/parse_batch_size/keywords in the POST body reach
    `controller.start` as kwargs -- an absent field must NOT show up as an explicit None/[]."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "telemetry_poll_interval": 2.5, "batch_size": 50, "parse_batch_size": 8,
        "keywords": ["double machine learning", "synthetic control"],
    })
    assert status == 200
    assert fake_controller.calls == [(
        "start", 500, 2,
        {
            "telemetry_poll_interval": 2.5, "batch_size": 50, "parse_batch_size": 8,
            "keywords": ["double machine learning", "synthetic control"],
        },
    )]


# --- OG-49#3/#6: boundary validation -- rejected with 400, never reaching controller.start -----


def test_control_start_rejects_parse_workers_zero(running_server):
    url, fake_controller = running_server
    status, body = _post(
        url, "/api/control", {"action": "start", "target": 500, "parse_workers": 0}
    )
    assert status == 400
    assert body["ok"] is False
    assert fake_controller.calls == []


def test_control_start_rejects_negative_parse_workers(running_server):
    url, fake_controller = running_server
    status, body = _post(
        url, "/api/control", {"action": "start", "target": 500, "parse_workers": -1}
    )
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_rejects_batch_size_zero(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2, "batch_size": 0,
    })
    assert status == 400
    assert fake_controller.calls == []


def test_control_retarget_also_rejects_parse_workers_zero(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "retarget", "target": 500, "parse_workers": 0,
    })
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_rejects_a_quote_injection_keyword(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "keywords": ['causal inference" OR cat:econ.EM'],
    })
    assert status == 400
    assert body["ok"] is False
    assert fake_controller.calls == []


def test_control_start_rejects_an_invalid_arxiv_category(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "arxiv_categories": ["stat.ME OR cs.LG"],
    })
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_rejects_a_malformed_arxiv_date(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "arxiv_date_from": "not-a-date",
    })
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_accepts_valid_parse_workers_and_batch_size(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 3, "batch_size": 25,
    })
    assert status == 200
    assert fake_controller.calls == [("start", 500, 3, {"batch_size": 25})]


def test_control_start_omits_unset_og43_params(running_server):
    url, fake_controller = running_server
    _post(url, "/api/control", {"action": "start", "target": 500, "parse_workers": 2, "keywords": []})
    assert fake_controller.calls == [("start", 500, 2, {})]


def test_control_start_forwards_og45_og46_editable_params(running_server):
    """OG-45/OG-46: arxiv_categories/arxiv_date_from/arxiv_date_to/ordering in the POST body reach
    `controller.start` as kwargs -- an absent field must not show up as an explicit None/[]."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "arxiv_categories": ["stat.ME", "econ.EM"], "arxiv_date_from": "2018-01-01",
        "arxiv_date_to": "2020-01-01", "ordering": "relevance",
    })
    assert status == 200
    assert fake_controller.calls == [(
        "start", 500, 2,
        {
            "arxiv_categories": ["stat.ME", "econ.EM"], "arxiv_date_from": "2018-01-01",
            "arxiv_date_to": "2020-01-01", "ordering": "relevance",
        },
    )]


# --- T-DOC78: POST /api/control {"action": "download"} -----------------------------------------


def test_control_download_dispatches_start_with_mode_and_prefetch_target(running_server, tmp_path):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "download"})
    assert status == 200
    assert body["ok"] is True
    call = fake_controller.calls[-1]
    assert call[0] == "start"
    _, target, parse_workers, kwargs = call
    assert target == server_mod._static_config(tmp_path).prefetch_target
    assert parse_workers == 1
    assert kwargs["mode"] == "download"


def test_control_download_forwards_keywords_and_arxiv_filters(running_server):
    url, fake_controller = running_server
    body = {
        "action": "download",
        "keywords": ["double machine learning"],
        "arxiv_categories": ["stat.ME"],
        "arxiv_date_from": "2024-01-01",
    }
    status, _ = _post(url, "/api/control", body)
    assert status == 200
    _, _, _, kwargs = fake_controller.calls[-1]
    assert kwargs["keywords"] == ["double machine learning"]
    assert kwargs["arxiv_categories"] == ["stat.ME"]
    assert kwargs["arxiv_date_from"] == "2024-01-01"
    # Full-run-only fields must never reach a download-only start, even if present in the body.
    assert "ordering" not in kwargs
    assert "stranded_policy" not in kwargs
    assert "parse_batch_size" not in kwargs
    assert "batch_size" not in kwargs
    assert "telemetry_poll_interval" not in kwargs


def test_control_download_rejects_a_quote_injection_keyword(running_server):
    url, _ = running_server
    status, body = _post(url, "/api/control", {"action": "download", "keywords": ['bad"keyword']})
    assert status == 400
    assert body["ok"] is False


def test_control_download_rejects_an_invalid_arxiv_category(running_server):
    url, _ = running_server
    status, body = _post(
        url, "/api/control", {"action": "download", "arxiv_categories": ["not a category!"]}
    )
    assert status == 400


def test_control_download_rejects_a_malformed_arxiv_date(running_server):
    url, _ = running_server
    status, body = _post(
        url, "/api/control", {"action": "download", "arxiv_date_from": "not-a-date"}
    )
    assert status == 400


def test_status_route_shape_includes_run_mode(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert "mode" in body["run"]


def test_status_route_reads_config_from_data_dir_not_cwd(tmp_path, monkeypatch):
    """T-DOC90 regression: `_static_config` used a bare `load_config()`, so after T-DOC89 changed
    discovery to RAG_CONFIG -> cwd -> walk-up, a dashboard started by `scripts/dashboard.sh` (which
    cd's to the repo root, where no deployed config.yaml exists) raised ContractError on EVERY
    `GET /api/status`. Serving from a cwd with no config.yaml is the exact shape that broke."""
    import shutil
    from pathlib import Path

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(Path(__file__).resolve().parents[2] / "config.example.yaml",
                data_dir / "config.yaml")

    empty_cwd = tmp_path / "no_config_here"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    monkeypatch.delenv("RAG_CONFIG", raising=False)

    server = server_mod.build_server(data_dir, "tok", 0, host="127.0.0.1")
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/status",
            headers={"X-Dashboard-Token": "tok"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
    finally:
        server.shutdown()
        server.server_close()

    # Proves the config came from data_dir, not from a default or a stray discovery hit.
    expected = controller_mod.load_config(data_dir / "config.yaml")
    assert body["search"]["top_k_default"] == expected.top_k
    assert body["search"]["hybrid_dense_weight"] == expected.hybrid_dense_weight


def test_search_display_rerank_pool_size_is_not_clamped(tmp_path):
    """RI-16 regression: `build_mcp_server` threads `config.rerank_depth` into `Retriever`
    unclamped (the reranker packs an oversized pool into several vendor-batch-sized chunks and
    merges their scores instead of truncating), so this display must report that same uncapped
    value. Pinned at 64 -- a `rerank_depth` still at or below the old 32-item batch limit would
    pass even with a stale `min(rerank_depth, 32)` clamp reintroduced, so it wouldn't catch this."""
    from pathlib import Path

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = Path(__file__).resolve().parents[2] / "config.example.yaml"
    config_text = config_path.read_text().replace("rerank_depth: 32", "rerank_depth: 64")
    (data_dir / "config.yaml").write_text(config_text)

    result = server_mod._search_display(data_dir)
    assert result["rerank_pool_size"] == 64


def test_control_start_omits_unset_og45_og46_params(running_server):
    url, fake_controller = running_server
    _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2, "arxiv_categories": [],
    })
    assert fake_controller.calls == [("start", 500, 2, {})]


# --- keyword REMOVAL: `remove_keywords` on start/retarget --------------------------------------


def test_control_start_forwards_remove_keywords(running_server):
    """The API contract: POST /api/control body field "remove_keywords": [...], valid for
    "start"/"retarget", reaches controller.start/retarget as a kwarg."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "remove_keywords": ["obsolete topic"],
    })
    assert status == 200
    assert fake_controller.calls == [("start", 500, 2, {"remove_keywords": ["obsolete topic"]})]


def test_control_retarget_forwards_keywords_and_remove_keywords_together(running_server):
    """Add+remove in one request is well-defined -- both reach controller.retarget alongside each
    other, unmangled."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "retarget", "target": 500, "parse_workers": 2,
        "keywords": ["new topic"], "remove_keywords": ["old topic"],
    })
    assert status == 200
    assert fake_controller.calls == [(
        "retarget", 500, 2, {"keywords": ["new topic"], "remove_keywords": ["old topic"]},
    )]


def test_control_start_omits_unset_remove_keywords(running_server):
    """Omitted entirely when nothing is being removed -- same "absent, not []" convention every
    other OG-43/45/46 editable param already follows, so retarget never clobbers a stored value."""
    url, fake_controller = running_server
    _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2, "remove_keywords": [],
    })
    assert fake_controller.calls == [("start", 500, 2, {})]


def test_control_start_rejects_a_quote_injection_remove_keyword(running_server):
    """Same `_UNSAFE_KEYWORD_CHARS_RE` boundary check `keywords` already gets -- a bad
    remove_keywords entry must 400 before ever reaching controller.start too."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2,
        "remove_keywords": ['causal inference" OR cat:econ.EM'],
    })
    assert status == 400
    assert fake_controller.calls == []


# --- boundary hardening: target / telemetry_poll_interval, and no more dropped connections ------


def test_control_start_rejects_target_zero(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "start", "target": 0, "parse_workers": 2})
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_rejects_a_negative_target(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "start", "target": -5, "parse_workers": 2})
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_rejects_a_negative_telemetry_poll_interval(running_server):
    """`<input min="0.1">` is decorative -- a browser doesn't block an out-of-range TYPED value,
    and telemetry_poll_interval had no server-side check at all before this fix."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2, "telemetry_poll_interval": -5,
    })
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_rejects_a_zero_telemetry_poll_interval(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2, "telemetry_poll_interval": 0,
    })
    assert status == 400
    assert fake_controller.calls == []


def test_control_start_with_non_numeric_target_is_a_clean_error_not_a_dropped_connection(running_server):
    """`int(body["target"])` on `{"target": "not-a-number"}` used to raise a bare `ValueError`,
    which do_POST's except tuple did not catch -- an uncaught exception, dropped connection, no
    response body. Must now be a clean status+message like any other rejected request."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "start", "target": "not-a-number"})
    assert status == 409
    assert body["ok"] is False
    assert fake_controller.calls == []


class _SpawnFailureController(_FakeController):
    """Simulates Task 2's resume-from-a-crashed-run failure mode: `subprocess.Popen(cwd=<deleted
    dir>)` raises `FileNotFoundError` (an `OSError`), which do_POST's except tuple did not catch
    either -- same uncaught-exception, dropped-connection, no-response-body failure mode as the
    non-numeric target above."""

    def start(self, data_dir, target, parse_workers=3, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "/some/deleted/run_cwd")


def test_control_start_spawn_failure_is_a_clean_error_not_a_dropped_connection(tmp_path):
    httpd = build_server(
        tmp_path, _TOKEN, port=0, host="127.0.0.1",
        status_module=_FakeStatus(), controller_module=_SpawnFailureController(),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}"
        status, body = _post(url, "/api/control", {"action": "start", "target": 500})
        assert status == 409
        assert body["ok"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)


_BROKEN_CONFIG_CASES = [
    pytest.param("focus_area_queries: [unclosed\n", id="malformed-yaml-syntax"),
    pytest.param("", id="empty-file-parses-to-no-mapping"),
    pytest.param("bogus_key: 1\n", id="well-formed-mapping-with-an-unknown-key"),
]


@pytest.mark.parametrize("yaml_text", _BROKEN_CONFIG_CASES)
def test_status_route_with_broken_config_yaml_is_a_clean_error_not_a_dropped_connection(
    tmp_path, yaml_text,
):
    """RI-27 fix 2: do_GET had no error handling around the /api/status build, so a broken
    config.yaml raised straight through the socket layer -- the client got a connection reset
    with NO HTTP response at all, on every poll (startup never touches config, so the server
    came up healthy, and lru_cache does not cache exceptions, so every poll re-raised). The
    parametrized cases cover the config-error types rag.config.load_config's own docstring
    enumerates (YAMLError / ContractError / pydantic ValidationError); each must come back as
    the same JSON error shape do_POST already returns."""
    (tmp_path / "config.yaml").write_text(yaml_text)
    httpd = build_server(
        tmp_path, _TOKEN, port=0, host="127.0.0.1",
        status_module=_FakeStatus(), controller_module=_FakeController(),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        url = f"http://127.0.0.1:{port}"
        req = urllib.request.Request(url + "/api/status", headers={"X-Dashboard-Token": _TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                status_code, body = resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            status_code, body = e.code, json.loads(e.read())
        assert status_code == 500
        assert body["ok"] is False
        assert body["message"], "the operator broke their own config -- name the actual problem"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)


def test_control_retarget_dispatches_with_params(running_server):
    """OG-43: "Apply new settings" while a run is live goes through `retarget` (stop-then-start),
    not plain `start` (which would just hit the double-run guard)."""
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {
        "action": "retarget", "target": 500, "parse_workers": 2, "parse_batch_size": 6,
    })
    assert status == 200
    assert fake_controller.calls == [("retarget", 500, 2, {"parse_batch_size": 6})]


def test_control_unknown_action_is_a_client_error(running_server):
    url, _ = running_server
    status, body = _post(url, "/api/control", {"action": "bogus"})
    assert status == 409
    assert body["ok"] is False


def test_control_stop_with_no_run_reports_conflict_not_crash(running_server):
    url, _ = running_server
    status, body = _post(url, "/api/control", {"action": "stop"})
    assert status == 409
    assert body["ok"] is False
    assert "no running run" in body["message"]


def test_control_invalid_json_body_is_a_client_error(running_server):
    url, _ = running_server
    req = urllib.request.Request(
        url + "/api/control", data=b"not json", method="POST",
        headers={"Content-Type": "application/json", "X-Dashboard-Token": _TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            status, body = resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        status, body = e.code, json.loads(e.read())
    assert status == 400
    assert body["ok"] is False


def test_unknown_route_is_404(running_server):
    url, _ = running_server
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(url + "/nope", timeout=5.0)
    assert exc_info.value.code == 404


# --- GET /api/search: the "Try a search" panel's backend --------------------------------------
#
# HARD GUARDRAIL: every test below injects a FAKE `mcp_server_factory` -- never the real default
# (`_LazyMcpServer`, which would build a real `GpuLock`/vector-store connection/TEI clients on
# first use). That keeps this suite offline and clear of the shared GPU lock, same as every other
# fake in this file.

_BBOX = (0.0, 0.0, 100.0, 200.0)


def _grounded_result(
    paper_id="2506.01234", title="A Causal Method", section_path="3. Method",
    text="The estimator is defined as the sample analogue.", score=0.9,
):
    citation = Citation(paper_id=paper_id, title=title, authors=["A. Author"],
                        arxiv_url=f"https://arxiv.org/abs/{paper_id}", section_path=section_path)
    anchor = Anchor(paper_id=paper_id, block_id=f"{paper_id}:b0", page=0, bbox=_BBOX,
                    snippet=text[:16], section_path=section_path)
    return GroundedResult(passage_text=text, anchor=anchor, paper_id=paper_id, score=score,
                          citation=citation)


class _FakeMcpServer:
    """Stands in for `_LazyMcpServer` (or the real `McpServer`) -- records every
    `semantic_search` call and returns a canned `SearchResponse`, or raises a canned error."""

    def __init__(self, results=(), coverage=None, error=None):
        self.calls: list[tuple] = []
        self._results = list(results)
        self._coverage = coverage or Coverage(
            returned=len(self._results), candidates=len(self._results)
        )
        self._error = error

    def semantic_search(self, query, filters, k):
        self.calls.append((query, filters, k))
        if self._error is not None:
            raise self._error
        return SearchResponse(results=self._results, coverage=self._coverage)


def _get_allow_error(url, path, token=_TOKEN):
    """Same as `_get`, but doesn't let a non-2xx response raise -- `/api/search` returns 400/502
    on a client/backend error (same convention `_post` already uses for `/api/control`)."""
    headers = {} if token is None else {"X-Dashboard-Token": token}
    req = urllib.request.Request(url + path, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@contextmanager
def _search_server(tmp_path, fake_mcp):
    httpd = build_server(
        tmp_path, _TOKEN, port=0, host="127.0.0.1",
        status_module=_FakeStatus(), controller_module=_FakeController(),
        mcp_server_factory=fake_mcp,
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)


# --- OG-48#7: _LazyMcpServer's first build is guarded, never duplicated under concurrency -------


def test_lazy_mcp_server_builds_only_once_under_concurrent_first_calls(tmp_path, monkeypatch):
    build_calls = []
    build_started = threading.Event()
    release_build = threading.Event()

    class _StubServer:
        def semantic_search(self, query, filters, k):
            return SearchResponse(results=[], coverage=Coverage(returned=0, candidates=0))

    def slow_build(*args, **kwargs):
        # Simulates the real build's real cost (GpuLock/vector-store/TEI client construction)
        # taking long enough for a second concurrent first-request to arrive mid-build.
        build_calls.append(1)
        build_started.set()
        assert release_build.wait(timeout=5.0), "test setup: build was never released"
        return _StubServer()

    monkeypatch.setattr(server_mod, "build_mcp_server", slow_build)
    lazy = _LazyMcpServer(tmp_path)
    results = []

    def call():
        results.append(lazy.semantic_search("q", None, None))

    t1 = threading.Thread(target=call)
    t2 = threading.Thread(target=call)
    t1.start()
    assert build_started.wait(timeout=5.0), "first build never started"
    t2.start()  # arrives while the first build is still in flight, sees self._server is None too
    release_build.set()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert len(build_calls) == 1, "both concurrent first-searches must share ONE build"
    assert len(results) == 2


def test_search_route_without_token_is_401_and_never_calls_the_backend(tmp_path):
    fake_mcp = _FakeMcpServer(results=[])
    with _search_server(tmp_path, fake_mcp) as url:
        status, body = _get_allow_error(url, "/api/search?q=estimator", token=None)
    assert status == 401
    assert body["ok"] is False
    assert fake_mcp.calls == []


def test_search_route_with_valid_token_is_200(tmp_path):
    fake_mcp = _FakeMcpServer(results=[])
    with _search_server(tmp_path, fake_mcp) as url:
        status, _body = _get(url, "/api/search?q=estimator", token=_TOKEN)
    assert status == 200


def test_search_route_returns_results_and_coverage_shape(tmp_path):
    result = _grounded_result()
    fake_mcp = _FakeMcpServer(results=[result], coverage=Coverage(returned=1, candidates=5))

    with _search_server(tmp_path, fake_mcp) as url:
        status, body = _get(url, "/api/search?q=estimator")

    assert status == 200
    assert body["ok"] is True
    assert body["coverage"] == {"returned": 1, "candidates": 5}
    assert body["results"] == [{
        "paper_id": "2506.01234", "title": "A Causal Method", "section_path": "3. Method",
        "snippet": result.passage_text, "score": 0.9,
    }]
    # No k/filters given -> both flow through as None, letting McpServer's own default_k
    # (Config.top_k) and "no restriction" apply -- this route never invents a default of its own.
    assert fake_mcp.calls == [("estimator", None, None)]


def test_search_route_clamps_k_to_bounds(tmp_path):
    # OG-48#5: k=-1, 0, and a huge k must all be clamped before reaching the backend -- never
    # passed through raw (results[:-1] silently drops the last element; a huge k fans out to
    # thousands of per-hit SQLite queries from one unauth GET).
    from app.dashboard.server import _SEARCH_MAX_K, _SEARCH_MIN_K

    fake_mcp = _FakeMcpServer(results=[])
    with _search_server(tmp_path, fake_mcp) as url:
        _get(url, "/api/search?q=estimator&k=-1")
        _get(url, "/api/search?q=estimator&k=0")
        _get(url, "/api/search?q=estimator&k=99999")

    assert [k for (_q, _f, k) in fake_mcp.calls] == [_SEARCH_MIN_K, _SEARCH_MIN_K, _SEARCH_MAX_K]


def test_search_route_parses_k_and_subject_date_filters(tmp_path):
    fake_mcp = _FakeMcpServer(results=[])
    qs = urllib.parse.urlencode({
        "q": "estimator", "k": "5", "categories": "stat.ME, econ.EM",
        "published_after": "2020-01-01", "published_before": "2021-01-01",
    })

    with _search_server(tmp_path, fake_mcp) as url:
        status, _body = _get(url, f"/api/search?{qs}")

    assert status == 200
    [(query, filters, k)] = fake_mcp.calls
    assert query == "estimator"
    assert k == 5
    assert filters == SearchFilters(
        categories=["stat.ME", "econ.EM"],
        published_after=date(2020, 1, 1),
        published_before=date(2021, 1, 1),
    )


def test_search_route_missing_query_is_a_client_error_and_never_calls_the_backend(tmp_path):
    fake_mcp = _FakeMcpServer()

    with _search_server(tmp_path, fake_mcp) as url:
        status, body = _get_allow_error(url, "/api/search")

    assert status == 400
    assert body["ok"] is False
    assert fake_mcp.calls == []


def test_search_route_backend_failure_degrades_to_502_not_a_crash(tmp_path):
    fake_mcp = _FakeMcpServer(error=TransientError("TEI reranker unreachable"))

    with _search_server(tmp_path, fake_mcp) as url:
        status, body = _get_allow_error(url, "/api/search?q=estimator")

    assert status == 502
    assert body["ok"] is False
    # OG-48#8: the client (any authenticated tailnet host, not necessarily a trusted operator)
    # must never see the raw backend exception text -- it can carry lock paths/vendor strings.
    assert "TEI reranker unreachable" not in body["message"]
    assert "TEI" not in body["message"]


def test_search_route_records_dashboard_usage_on_success(tmp_path):
    """Task 3: `/api/search` must record with source="dashboard" so the usage picture (Task 1's
    `mcp_usage.db`) has no hole in it alongside the MCP tools' own @record_usage rows."""
    fake_mcp = _FakeMcpServer(results=[], coverage=Coverage(returned=0, candidates=3))

    with _search_server(tmp_path, fake_mcp) as url:
        status, _body = _get(url, "/api/search?q=estimator")

    assert status == 200
    conn = sqlite3.connect(tmp_path / "mcp_usage.db")
    row = conn.execute(
        "SELECT source, tool, query, result_count, candidates, error FROM requests"
    ).fetchone()
    conn.close()
    assert row == ("dashboard", "semantic_search", "estimator", 0, 3, None)


def test_search_route_records_dashboard_usage_on_backend_failure(tmp_path):
    """Recording happens on the failure path too -- without changing the existing 502 response."""
    fake_mcp = _FakeMcpServer(error=TransientError("TEI reranker unreachable"))

    with _search_server(tmp_path, fake_mcp) as url:
        status, body = _get_allow_error(url, "/api/search?q=estimator")

    assert status == 502  # existing error-response behavior is unchanged
    assert body["ok"] is False
    conn = sqlite3.connect(tmp_path / "mcp_usage.db")
    row = conn.execute(
        "SELECT source, tool, query, result_count, candidates, error FROM requests"
    ).fetchone()
    conn.close()
    assert row == ("dashboard", "semantic_search", "estimator", None, None, "TransientError")


def test_search_route_backend_failure_logs_full_detail_server_side(tmp_path, caplog):
    fake_mcp = _FakeMcpServer(error=TransientError("TEI reranker unreachable at /tmp/.gpu.lock"))

    with caplog.at_level("WARNING", logger="app.dashboard.server"):
        with _search_server(tmp_path, fake_mcp) as url:
            _get_allow_error(url, "/api/search?q=estimator")

    assert "TEI reranker unreachable at /tmp/.gpu.lock" in caplog.text


# --- OG-48#9: reversed published_after/published_before range is a clear 400 -------------------


def test_search_route_reversed_date_range_is_a_clean_400_not_silent_zero_results(tmp_path):
    fake_mcp = _FakeMcpServer(results=[])
    qs = urllib.parse.urlencode({
        "q": "estimator", "published_after": "2021-01-01", "published_before": "2020-01-01",
    })

    with _search_server(tmp_path, fake_mcp) as url:
        status, body = _get_allow_error(url, f"/api/search?{qs}")

    assert status == 400
    assert body["ok"] is False
    assert "published_after" in body["message"]
    assert fake_mcp.calls == []  # rejected before ever reaching the backend


def test_search_route_equal_date_range_is_allowed(tmp_path):
    # A single-day range (after == before) is valid, not "reversed" -- must not be rejected.
    fake_mcp = _FakeMcpServer(results=[])
    qs = urllib.parse.urlencode({
        "q": "estimator", "published_after": "2020-01-01", "published_before": "2020-01-01",
    })

    with _search_server(tmp_path, fake_mcp) as url:
        status, _body = _get(url, f"/api/search?{qs}")

    assert status == 200
    assert len(fake_mcp.calls) == 1


# --- T-DOC78: _load_or_create_token -- the dashboard manages its own token file -----------------


def test_load_or_create_token_generates_and_persists_a_new_token_at_mode_0600(tmp_path):
    token = server_mod._load_or_create_token(tmp_path)

    token_path = tmp_path / ".dashboard_token"
    assert token_path.exists()
    assert token_path.read_text().strip() == token
    assert len(token) == 32, "secrets.token_hex(16) -- 16 bytes as hex"
    assert oct(token_path.stat().st_mode)[-3:] == "600"


def test_write_private_file_never_touches_another_writers_temp_file(tmp_path):
    """RI-21: `_write_private_file` delegates to the shared pid-qualified helper
    (`rag.atomic_write`) -- same mechanism, plus the mode=0600 opt-in asserted above. Another
    writer's staged temp (different pid, same target) must survive our write byte-for-byte and
    the token must land complete."""
    target = tmp_path / ".dashboard_token"
    foreign_tmp = tmp_path / f".dashboard_token.{os.getpid() + 1}.tmp"
    foreign_tmp.write_text("another generator's partial write")

    server_mod._write_private_file(target, "token-value")

    assert foreign_tmp.read_text() == "another generator's partial write"
    assert target.read_text() == "token-value"


def test_load_or_create_token_reads_an_existing_token_without_regenerating_it(tmp_path):
    token_path = tmp_path / ".dashboard_token"
    token_path.write_text("existing-operator-token")
    token_path.chmod(0o600)

    token = server_mod._load_or_create_token(tmp_path)

    assert token == "existing-operator-token"


def test_load_or_create_token_never_chmods_an_existing_file(tmp_path):
    """An operator's existing token file might carry different permissions (this codebase's own
    convention is 0600, but this function must not be the one enforcing that on a file it didn't
    create) -- only a freshly-created file gets chmod'd."""
    token_path = tmp_path / ".dashboard_token"
    token_path.write_text("existing-operator-token")
    token_path.chmod(0o644)  # deliberately NOT 0600, to prove this function leaves it alone

    server_mod._load_or_create_token(tmp_path)

    assert oct(token_path.stat().st_mode)[-3:] == "644"


def test_load_or_create_token_never_prints_the_token_value(tmp_path, capsys):
    token = server_mod._load_or_create_token(tmp_path)

    captured = capsys.readouterr()
    assert token not in captured.out
    assert str(tmp_path / ".dashboard_token") in captured.out


def test_parse_args_token_defaults_to_none_so_main_falls_back_to_the_token_file(monkeypatch):
    """An explicit `--token` still wins (main() only calls `_load_or_create_token` when
    `args.token is None`) -- this just proves the CLI default itself is None, not a required
    string, now that T-DOC78 makes `--token` optional."""
    monkeypatch.setattr(
        "sys.argv", ["dashboard", "--data-dir", "/tmp/whatever"]
    )
    args = server_mod._parse_args()
    assert args.token is None


# --- RI-2: an empty effective token fails closed at startup -------------------------------------


@contextmanager
def _server_with_token(data_dir, token):
    """A real server on 127.0.0.1:0 built with an explicitly-resolved `token`, for tests that
    drive a startup path (flag / generated file / operator file) end to end."""
    httpd = build_server(
        data_dir, token, port=0, host="127.0.0.1",
        status_module=_FakeStatus(), controller_module=_FakeController(),
    )
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)


def test_main_refuses_to_start_when_the_token_flag_is_empty(tmp_path, monkeypatch, capsys):
    """`--token ""` used to win over the generated token (`args.token is not None`), and a
    configured "" token makes `hmac.compare_digest(<missing header's default "">, "")` succeed --
    every request carrying NO header at all authenticated (review-verified live: no header -> 200).
    The guard lives at the effective-token resolution point in main(), NOT inside
    `_load_or_create_token`: the file path can't hand back an empty token, only the flag can, and
    a guard where the value is resolved also covers any future third source. Refuse-to-start over
    silently regenerating: an operator who typed `--token ""` has a broken invocation and needs to
    be told, not quietly overridden."""
    monkeypatch.setattr(
        "sys.argv", ["dashboard", "--data-dir", str(tmp_path), "--token", ""],
    )

    def _must_not_be_reached(*args, **kwargs):
        raise AssertionError("build_server must never run with an empty effective token")

    monkeypatch.setattr(server_mod, "build_server", _must_not_be_reached)

    with pytest.raises(SystemExit) as excinfo:
        server_mod.main()

    assert excinfo.value.code != 0
    assert "--token" in capsys.readouterr().err


@pytest.mark.parametrize("startup", ["explicit_flag", "generated_file", "preexisting_file",
                                     "empty_file_regenerated"])
def test_no_header_request_is_rejected_under_every_startup_path(tmp_path, startup):
    """RI-2's done-when, end to end over a real socket: however the server's token was resolved,
    a request with NO X-Dashboard-Token header must 401 -- it must never compare equal to the
    configured token."""
    if startup == "explicit_flag":
        token = "explicit-cli-token"
    elif startup == "generated_file":
        token = server_mod._load_or_create_token(tmp_path)
    else:
        (tmp_path / ".dashboard_token").write_text("" if startup == "empty_file_regenerated"
                                                   else "operator-token")
        token = server_mod._load_or_create_token(tmp_path)
    assert token, "every startup path that can start a server must resolve a non-empty token"

    with _server_with_token(tmp_path, token) as url:
        status, body = _get_allow_error(url, "/api/status", token=None)

    assert status == 401
    assert body["ok"] is False


# --- RI-6: token-file crash window, writer sidecar, corrupt tolerance ---------------------------


@pytest.mark.parametrize("content", ["", "  \n\t\n"])
def test_empty_token_file_is_regenerated_never_handed_back(tmp_path, content):
    """An empty `.dashboard_token` (an operator's `touch`, an editor saved empty, or the old
    touch->chmod->write_text crash window) used to be read verbatim as "" -- feeding RI-2's auth
    hole from the file side. Reading it back must regenerate instead; an empty value can never
    again reach `_token_ok`'s comparison."""
    (tmp_path / ".dashboard_token").write_text(content)

    token = server_mod._load_or_create_token(tmp_path)

    assert token and len(token) == 32
    assert (tmp_path / ".dashboard_token").read_text() == token


def test_generated_token_writes_a_sidecar_recording_the_writing_process(tmp_path):
    """The sidecar records WHICH process generated the current token file (pid + /proc starttime
    + cmdline, the run manifest's PID-reuse-safe identity triple) -- without it, a stale sidecar
    from a dead run is indistinguishable from a live one."""
    token = server_mod._load_or_create_token(tmp_path)

    record = json.loads((tmp_path / ".dashboard_token.sidecar").read_text())
    assert record["pid"] == os.getpid()
    assert isinstance(record["pid_starttime"], float)
    assert record["pid_cmdline"]
    assert token not in json.dumps(record), "the sidecar carries provenance, not the secret"


def test_generation_overwrites_a_malformed_sidecar(tmp_path):
    """A truncated/corrupt sidecar must be tolerated as absent -- and the next generation simply
    replaces it with a valid record rather than propagating the parse error."""
    (tmp_path / ".dashboard_token.sidecar").write_text('{"pid": 12')  # torn JSON write

    token = server_mod._load_or_create_token(tmp_path)

    record = json.loads((tmp_path / ".dashboard_token.sidecar").read_text())
    assert record["pid"] == os.getpid()
    assert token and len(token) == 32


def test_malformed_sidecar_does_not_block_reading_an_operator_token(tmp_path):
    (tmp_path / ".dashboard_token").write_text("operator-token")
    (tmp_path / ".dashboard_token.sidecar").write_text("not json at all")

    assert server_mod._load_or_create_token(tmp_path) == "operator-token"


def test_live_sidecar_writer_refuses_to_generate_a_token(tmp_path):
    """A sidecar whose recorded writer is STILL the live process at that pid means another
    dashboard instance generated the current token and is running on this data dir right now.
    Handing out that persisted token would be safe -- both processes read the same value, so
    nothing diverges -- but GENERATING a replacement would overwrite the file out from under
    the live writer, last-writer-wins again. The refusal therefore fires exactly at the
    generation path, not on the read-an-existing-token path."""
    server_mod._load_or_create_token(tmp_path)  # records THIS process as the writer
    (tmp_path / ".dashboard_token").unlink()  # force the generation path

    with pytest.raises(server_mod._LiveTokenWriterError) as excinfo:
        server_mod._load_or_create_token(tmp_path)

    assert str(os.getpid()) in str(excinfo.value)


def test_live_writer_with_a_usable_token_file_hands_out_that_same_token(tmp_path):
    """The ambiguity the sidecar resolves is DIVERGENCE -- two processes each generating a
    different token, silently resolved by last-writer-wins. With a valid non-empty token file
    on disk there is nothing to diverge: a second start under a still-live writer reads the
    same value and must succeed with it, not be refused -- e.g. a second dashboard on another
    port against the same corpus, the shape scripts/dashboard.sh's independent
    DASHBOARD_PORT/DASHBOARD_DATA_DIR env vars allow."""
    first = server_mod._load_or_create_token(tmp_path)  # records THIS process as the writer

    second = server_mod._load_or_create_token(tmp_path)

    assert second == first
    assert second == (tmp_path / ".dashboard_token").read_text()


def test_main_refuses_to_start_when_the_sidecar_writer_is_alive(tmp_path, monkeypatch, capsys):
    """End to end: a live rival writer blocks only the GENERATION path, so this drives main()
    with no usable token file -- the sidecar alone would not refuse a start that finds one
    (that start joins with the same token, see the join test above)."""
    identity = controller_mod._process_identity(os.getpid())
    (tmp_path / ".dashboard_token.sidecar").write_text(json.dumps({
        "pid": os.getpid(), "pid_starttime": identity[0], "pid_cmdline": identity[1],
    }))
    monkeypatch.setattr("sys.argv", ["dashboard", "--data-dir", str(tmp_path)])

    def _must_not_be_reached(*args, **kwargs):
        raise AssertionError("build_server must never run under a live rival writer")

    monkeypatch.setattr(server_mod, "build_server", _must_not_be_reached)

    with pytest.raises(SystemExit) as excinfo:
        server_mod.main()

    assert excinfo.value.code != 0
    err = capsys.readouterr().err
    assert "sidecar" in err
    assert str(os.getpid()) in err


def test_dead_writer_sidecar_is_honored(tmp_path):
    """The normal restart case: the previous dashboard (the sidecar's writer) is gone -- its pid
    verified dead via a really-reaped child, not an invented number -- so the persisted token is
    honored unchanged. Token persistence across restarts is the whole point of T-DOC78."""
    proc = subprocess.Popen(["true"])
    proc.wait()  # reaped: this pid is definitively dead
    (tmp_path / ".dashboard_token").write_text("operator-token")
    (tmp_path / ".dashboard_token.sidecar").write_text(json.dumps({
        "pid": proc.pid, "pid_starttime": 12345.0, "pid_cmdline": "whatever\x00the\x00child\x00ran",
    }))

    assert server_mod._load_or_create_token(tmp_path) == "operator-token"


def test_recycled_pid_with_mismatched_identity_is_honored_not_refused(tmp_path):
    """PID-reuse safety, same lesson as the run manifest's `_verified_pid`: bare pid-liveness is
    not enough. Here the recorded pid IS alive (it is this very test process) but its starttime/
    cmdline don't match the record -- i.e. the OS recycled the pid onto something else. That must
    read as 'writer gone', not as a live rival: a check that only tested liveness would refuse
    every restart after a reboot-and-pid-wraparound."""
    (tmp_path / ".dashboard_token").write_text("operator-token")
    (tmp_path / ".dashboard_token.sidecar").write_text(json.dumps({
        "pid": os.getpid(), "pid_starttime": 1.0, "pid_cmdline": "\x00not\x00this\x00process",
    }))

    assert server_mod._load_or_create_token(tmp_path) == "operator-token"


def test_generation_leaves_no_tmp_residue_and_both_files_are_private(tmp_path):
    """The crash-window fix writes through a pid-qualified temp file (OG-49 M12's two-writer
    convention) and renames: on success nothing temporary remains, and both files are owner-only
    from creation, before any content lands in them."""
    server_mod._load_or_create_token(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".dashboard_token", ".dashboard_token.sidecar",
    ]
    assert oct((tmp_path / ".dashboard_token").stat().st_mode)[-3:] == "600"
    assert oct((tmp_path / ".dashboard_token.sidecar").stat().st_mode)[-3:] == "600"


def test_status_dict_falls_back_to_the_data_dirs_own_collection_not_papers(tmp_path):
    """Regression (found 2026-08-07 running the Waymo corpus's dashboard): `_status_dict` passed
    `live.get("collection")` straight to `status.read_consistency`, but `collection` is only ever
    written into the run manifest when a run STARTS (`controller.py`'s `"collection":
    effective_cfg.collection`). With no run in the manifest -- an idle dashboard, or one brought up
    before the first run -- that get returns None, and `read_consistency`'s own
    `collection or "papers"` fallback then counted points in the DEFAULT corpus's collection.

    On any data dir whose config names a non-default collection, the consistency panel therefore
    reported a completely unrelated corpus's `vector_points` and derived `consistent` from it.
    Observed live: the Waymo dashboard (`collection: waymo_av_safety`, 405 points) reported
    412,167 -- the main `papers` corpus -- alongside its own `sqlite_done: 17`, and called that
    `consistent: True`. A false pass on exactly the OG-16/T-DOC35 "done rows, zero vectors" check
    `read_consistency` exists to make, since it was checking the wrong collection entirely.

    `app/dashboard/verify_numbers.py` does not cross-check `consistency` at all, so nothing caught
    this -- hence a direct test here.
    """
    import shutil
    from pathlib import Path

    import re

    shutil.copy(Path(__file__).resolve().parents[2] / "config.example.yaml",
                tmp_path / "config.yaml")
    config_text = (tmp_path / "config.yaml").read_text()
    config_text, n = re.subn(
        r"^collection:.*$", "collection: some_other_corpus", config_text, flags=re.M
    )
    assert n == 1, f"expected exactly one collection: line in config.example.yaml, found {n}"
    (tmp_path / "config.yaml").write_text(config_text)

    seen = {}

    class SpyStatus(_FakeStatus):
        def read_consistency(self, done_count, collection):
            seen["collection"] = collection
            return super().read_consistency(done_count, collection)

    class _IdleController(_FakeController):
        def liveness(self, data_dir):
            live = super().liveness(data_dir)
            live.pop("collection")  # no run has started -> manifest carries no collection
            return live

    _status_dict(tmp_path, SpyStatus(), _IdleController())

    assert seen["collection"] == "some_other_corpus", (
        "read_consistency must fall back to the data dir's OWN configured collection, never to "
        f"the hardcoded default; got {seen['collection']!r}"
    )


def test_status_dict_still_prefers_the_running_runs_collection_over_config(tmp_path):
    """Companion to the test above: when a run IS live, its manifest collection still wins. A run
    can be started against a run-scoped override config (`controller`'s `.run_overrides/<run_id>`),
    so the manifest -- not the data dir's base config.yaml -- is the authority while it runs."""
    import shutil
    from pathlib import Path

    import re

    shutil.copy(Path(__file__).resolve().parents[2] / "config.example.yaml",
                tmp_path / "config.yaml")
    config_text = (tmp_path / "config.yaml").read_text()
    config_text, n = re.subn(
        r"^collection:.*$", "collection: base_config_collection", config_text, flags=re.M
    )
    assert n == 1
    (tmp_path / "config.yaml").write_text(config_text)

    seen = {}

    class SpyStatus(_FakeStatus):
        def read_consistency(self, done_count, collection):
            seen["collection"] = collection
            return super().read_consistency(done_count, collection)

    class _RunningController(_FakeController):
        def liveness(self, data_dir):
            live = super().liveness(data_dir)
            live["collection"] = "run_scoped_collection"
            return live

    _status_dict(tmp_path, SpyStatus(), _RunningController())

    assert seen["collection"] == "run_scoped_collection"
