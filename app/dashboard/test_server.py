"""Smoke tests for `app.dashboard.server`'s HTTP routes -- a real `ThreadingHTTPServer` bound to
127.0.0.1:0 (an ephemeral port) driven with real `urllib` requests, but `status_module`/
`controller_module` are FAKES (no real DB, manifest, or subprocess) -- proves the routes exist,
parse bodies correctly, and return the exact API-contract shape, without touching anything real.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from app.dashboard.controller import DoubleRunError, NoRunError
from app.dashboard.server import _status_dict, build_server

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
            "quarantine_reasons": [{"reason": "TransientError", "count": 1}],
        }

    def read_telemetry(self, events_path, total_done, *, data_dir=None, started_at=None, target=None):
        return {
            "stage": "finish", "papers_per_hour": 12.5, "wall_clock_s": 300.0, "eta_s": 900.0,
            "gpu_util_pct": 80.0, "vram_mib": 9000, "power_w": 200.0,
        }

    def read_downloads(self, data_dir, target):
        return {"cached_pdfs": 20, "sidecars": 15, "target": target}

    def read_consistency(self, done_count, collection):
        return {"sqlite_done": done_count, "vector_points": 500, "consistent": True}

    def read_downloader(self, run_cwd, log_path):
        return {"prefetch_alive": True, "downloaded": 120, "prefetch_target": 30000}

    def read_disk(self, data_dir):
        return {"free_gb": 500.0, "total_gb": 1000.0, "used_pct": 50.0}


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

    DoubleRunError = DoubleRunError
    NoRunError = NoRunError


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


def _get(url, path):
    with urllib.request.urlopen(url + path, timeout=5.0) as resp:
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


# --- GET /api/status: exact API-contract shape --------------------------------------------------


def test_status_route_shape_matches_api_contract(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert set(body.keys()) == {
        "funnel", "run", "telemetry", "downloads", "downloader", "disk", "consistency",
        "quarantine_reasons", "search",
    }
    assert set(body["funnel"].keys()) == {
        "harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done", "quarantined",
    }
    assert set(body["run"].keys()) == {
        "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
        "paper_ids_file", "parse_batch_size",
    }
    assert set(body["telemetry"].keys()) == {
        "stage", "papers_per_hour", "gpu_util_pct", "vram_mib", "power_w", "wall_clock_s", "eta_s",
    }
    assert set(body["downloads"].keys()) == {"cached_pdfs", "sidecars", "target"}
    assert set(body["downloader"].keys()) == {"prefetch_alive", "downloaded", "prefetch_target"}
    assert set(body["disk"].keys()) == {"free_gb", "total_gb", "used_pct"}
    assert set(body["consistency"].keys()) == {"sqlite_done", "vector_points", "consistent"}
    assert set(body["search"].keys()) == {
        "top_k_default", "rerank_pool_size", "hybrid_dense_weight",
    }
    assert body["run"]["run_id"] == "run-fake"
    assert body["run"]["params"]["telemetry_poll_interval"] is None
    assert body["run"]["parse_batch_size"] == 4  # config.yaml's real default -- not hard-coded null
    assert body["funnel"]["done"] == 5
    assert body["quarantine_reasons"] == [{"reason": "TransientError", "count": 1}]


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


def test_control_start_omits_unset_og43_params(running_server):
    url, fake_controller = running_server
    _post(url, "/api/control", {"action": "start", "target": 500, "parse_workers": 2, "keywords": []})
    assert fake_controller.calls == [("start", 500, 2, {})]


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
