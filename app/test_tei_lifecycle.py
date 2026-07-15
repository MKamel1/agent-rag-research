"""Tests for `app.tei_lifecycle` (T-DOC19) -- offline, no real Docker/GPU/network calls.

Mirrors `rag/test_summarizer.py`'s pattern for `OllamaSummarizer.unload()`: fake/monkeypatched
`subprocess.run` for the lifecycle command, an `httpx.MockTransport`-backed client for the health
poll, and monkeypatched poll interval/timeout constants (real `time.sleep`, just shrunk) so the
timeout tests run fast without a fake clock.
"""

import logging
import subprocess

import httpx
import pytest

from app.tei_lifecycle import (
    _TEI_CONTAINERS,
    start_tei_containers,
    stop_tei_containers,
)
import app.tei_lifecycle as _mod


# ---------------------------------------------------------------------------
# stop_tei_containers()
# ---------------------------------------------------------------------------


def test_stop_tei_containers_runs_docker_stop_with_both_container_names(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )

    stop_tei_containers()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["docker", "stop", "rag-tei-embed", "rag-tei-reranker"]
    assert args == ["docker", "stop", *_TEI_CONTAINERS]
    assert kwargs.get("check") is True


@pytest.mark.parametrize(
    "error", [subprocess.CalledProcessError(1, "docker"), FileNotFoundError("no docker")]
)
def test_stop_tei_containers_is_best_effort_and_swallows_failures(monkeypatch, caplog, error):
    def raise_error(args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", raise_error)

    with caplog.at_level(logging.WARNING, logger="app.tei_lifecycle"):
        stop_tei_containers()  # must not raise

    assert any("rag-tei-embed" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# start_tei_containers()
# ---------------------------------------------------------------------------


def _healthy_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))


def test_start_tei_containers_runs_docker_start_with_both_container_names(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )

    start_tei_containers(client=_healthy_client())

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["docker", "start", *_TEI_CONTAINERS]
    assert kwargs.get("check") is True


@pytest.mark.parametrize(
    "error", [subprocess.CalledProcessError(1, "docker"), FileNotFoundError("no docker")]
)
def test_start_tei_containers_swallows_docker_start_failure_and_still_polls_health(
    monkeypatch, caplog, error
):
    def raise_error(args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", raise_error)

    with caplog.at_level(logging.WARNING, logger="app.tei_lifecycle"):
        start_tei_containers(client=_healthy_client())  # must not raise

    assert any("rag-tei-embed" in record.message for record in caplog.records)


def test_start_tei_containers_polls_until_both_endpoints_are_healthy(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: None)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_TIMEOUT_SECONDS", 5.0)

    polls = {"http://localhost:8080/health": 0, "http://localhost:8082/health": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        polls[url] += 1
        # Embedder ready on its 2nd poll, reranker ready on its 3rd -- proves both are actually
        # checked each iteration, not just the first one found ready.
        ready = polls[url] >= (2 if "8080" in url else 3)
        return httpx.Response(200 if ready else 503)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    start_tei_containers(client=client)

    # Each loop iteration re-checks the embedder first, then (short-circuiting `all()`) only
    # checks the reranker once the embedder itself is already healthy -- so by the time both
    # report ready, the embedder has been polled once more than the reranker (4 vs 3). What
    # matters: neither is checked just once, and the loop stops as soon as both are ready.
    assert polls["http://localhost:8080/health"] == 4
    assert polls["http://localhost:8082/health"] == 3, (
        "must poll repeatedly until healthy, not trust a single check"
    )


def test_start_tei_containers_times_out_and_logs_a_warning_if_never_healthy(monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: None)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_TIMEOUT_SECONDS", 0.05)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)  # never healthy

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with caplog.at_level(logging.WARNING, logger="app.tei_lifecycle"):
        start_tei_containers(client=client)  # must not raise or hang

    assert any("rag-tei-embed" in record.message for record in caplog.records), (
        "must log a warning naming the containers when health can't be confirmed before the "
        "timeout"
    )


def test_start_tei_containers_swallows_a_connection_error_as_unhealthy(monkeypatch):
    """httpx.ConnectError (e.g. the container isn't listening yet) must count as "not ready",
    not propagate -- the poll loop should keep retrying rather than crash."""
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: None)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(_mod, "_TEI_START_POLL_TIMEOUT_SECONDS", 5.0)

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    start_tei_containers(client=client)  # must not raise

    assert attempts["n"] >= 4
