"""Smoke tests for `app.dashboard.server`'s HTTP routes -- a real `ThreadingHTTPServer` bound to
127.0.0.1:0 (an ephemeral port) driven with real `urllib` requests, but `status_module`/
`controller_module` are FAKES (no real DB, manifest, or subprocess) -- proves the routes exist,
parse bodies correctly, and return the exact API-contract shape, without touching anything real.
"""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date

import pytest

import app.dashboard.server as server_mod
from app.dashboard.controller import DoubleRunError, NoRunError
from app.dashboard.server import _LazyMcpServer, _status_dict, build_server
from contracts.errors import TransientError
from contracts.mcp_server import Coverage, SearchResponse
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult
from contracts.vector_index import SearchFilters

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

    def read_downloader(self, run_cwd):
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
        "funnel", "run", "telemetry", "downloads", "downloader", "disk", "consistency",
        "quarantine_reasons", "search",
    }
    assert set(body["funnel"].keys()) == {
        "harvested", "parsed", "chunked", "summarized", "embedded", "stored", "done", "quarantined",
    }
    assert set(body["run"].keys()) == {
        "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
        "paper_ids_file", "parse_batch_size", "arxiv_categories", "arxiv_date_from",
        "arxiv_date_to", "ordering", "stranded_policy",
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


def test_control_start_omits_unset_og45_og46_params(running_server):
    url, fake_controller = running_server
    _post(url, "/api/control", {
        "action": "start", "target": 500, "parse_workers": 2, "arxiv_categories": [],
    })
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
