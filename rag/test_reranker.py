"""Tests for TeiReranker (real `Reranker` adapter, ARCHITECTURE.md §M7's injected collaborator).

Mocked tests (lock, reorder correctness, empty input, error taxonomy) run zero-GPU/zero-network in
default CI, mirroring rag/test_summarizer.py's pattern. The live test is `enable_socket`-gated and
skips cleanly if TEI's reranker isn't reachable, mirroring rag/test_vector_index.py's
`test_real_adapter_satisfies_contract` pattern — per DATA-CONTRACTS.md "Reranker", this is an
isolated real-adapter test, not a fake-vs-real contract/agreement pair (V0 has only one reranker).
"""

import httpx
import pytest

from contracts.errors import PermanentError, TransientError
from contracts.retriever import RerankCandidate
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.reranker import TeiReranker


def _candidates(*pairs: tuple[str, str]) -> list[RerankCandidate]:
    return [RerankCandidate(id=id_, text=text) for id_, text in pairs]


def test_rerank_acquires_the_rerank_gpu_lock():
    def handler(request):
        return httpx.Response(200, json=[{"index": 0, "score": 1.0}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    lock = FakeGpuLock()
    reranker = TeiReranker(client, lock)

    reranker.rerank("q", _candidates(("a", "text a")))

    assert lock.acquired == ["rerank"]


def test_rerank_reorders_by_score_and_fabricates_nothing():
    def handler(request):
        # Candidate at index 1 ("b") scores higher than index 0 ("a").
        return httpx.Response(
            200, json=[{"index": 0, "score": 0.1}, {"index": 1, "score": 0.9}]
        )

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())
    candidates = _candidates(("a", "text a"), ("b", "text b"))

    result = reranker.rerank("q", candidates)

    assert [c.id for c in result] == ["b", "a"]
    assert len(result) == len(candidates)
    assert set(c.id for c in result) == {"a", "b"}  # nothing fabricated


def test_rerank_ties_break_by_original_index_ascending():
    def handler(request):
        return httpx.Response(
            200, json=[{"index": 0, "score": 0.5}, {"index": 1, "score": 0.5}]
        )

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())
    candidates = _candidates(("a", "text a"), ("b", "text b"))

    result = reranker.rerank("q", candidates)

    assert [c.id for c in result] == ["a", "b"]


def test_rerank_truncates_a_batch_over_the_max_before_calling_tei():
    # T-DOC39 (mocked, zero-network): a caller-supplied batch over `_MAX_BATCH_SIZE` (e.g. a
    # retriever pool built from `k > 32`, McpServer exposes `k` unclamped) must never reach TEI at
    # its full size -- that's exactly the T-DOC24/25 422/0%-recall crash. Assert on what actually
    # went over the wire (via the mock transport), not just the return value, so a fix that
    # truncates the *response* instead of the *request* wouldn't slip this test.
    import rag.reranker as reranker_module

    sent_batch_sizes = []

    def handler(request):
        import json

        body = json.loads(request.content)
        sent_batch_sizes.append(len(body["texts"]))
        return httpx.Response(
            200, json=[{"index": i, "score": 1.0} for i in range(len(body["texts"]))]
        )

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())
    oversized = _candidates(
        *[(str(i), f"text {i}") for i in range(reranker_module._MAX_BATCH_SIZE + 5)]
    )

    result = reranker.rerank("q", oversized)

    assert sent_batch_sizes == [reranker_module._MAX_BATCH_SIZE]
    assert len(result) == reranker_module._MAX_BATCH_SIZE
    # The candidates that DID get sent are the caller's first `_MAX_BATCH_SIZE`, not a random
    # slice -- callers order their pool best-first (RRF/hybrid rank), so truncating from the front
    # keeps the candidates most likely to matter.
    assert {c.id for c in result} == {str(i) for i in range(reranker_module._MAX_BATCH_SIZE)}


def test_rerank_empty_candidates_returns_empty_without_http_call():
    def handler(request):
        raise AssertionError("should not make an HTTP call for empty candidates")

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())

    assert reranker.rerank("q", []) == []


# ---------------------------------------------------------------------------
# Error taxonomy — TransientError/PermanentError, never a bare httpx/KeyError exception
# (rag/test_summarizer.py's pattern).
# ---------------------------------------------------------------------------


def test_5xx_response_maps_to_transient_error():
    def handler(request):
        return httpx.Response(503)

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    # No-op retry_sleep: this test now exercises the (exhausted) retry loop below -- assert on the
    # eventual error, not the real wall-clock backoff delay.
    reranker = TeiReranker(client, FakeGpuLock(), retry_sleep=lambda seconds: None)

    with pytest.raises(TransientError):
        reranker.rerank("q", _candidates(("a", "text a")))


def test_4xx_response_maps_to_permanent_error():
    def handler(request):
        return httpx.Response(400)

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())

    with pytest.raises(PermanentError):
        reranker.rerank("q", _candidates(("a", "text a")))


def test_connection_failure_maps_to_transient_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock(), retry_sleep=lambda seconds: None)

    with pytest.raises(TransientError):
        reranker.rerank("q", _candidates(("a", "text a")))


# ---------------------------------------------------------------------------
# Query-path retry-with-backoff (reliability-audit gap): a transient TEI hiccup (429/502/503/504,
# timeout, connection failure) used to fail the whole `rerank()` call on the FIRST failure --
# unlike rag/harvester.py's Harvester / rag/orchestrator.py's IngestionOrchestrator, which already
# retry-with-backoff on the ingest side. Same shape here: bounded `max_retries`, injected
# `retry_sleep` (never really sleeps in tests), `PermanentError` never retried.
# ---------------------------------------------------------------------------


def test_transient_then_success_is_recovered_with_backoff():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"index": 0, "score": 1.0}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    reranker = TeiReranker(client, FakeGpuLock(), retry_sleep=sleeps.append)

    result = reranker.rerank("q", _candidates(("a", "text a")))

    assert attempts["n"] == 2  # first attempt 503, second succeeds -- no third attempt
    assert sleeps == [1.0]  # exactly one backoff, between attempt 1 and 2
    assert [c.id for c in result] == ["a"]


def test_permanent_error_is_never_retried():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(400)

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    reranker = TeiReranker(client, FakeGpuLock(), retry_sleep=sleeps.append)

    with pytest.raises(PermanentError):
        reranker.rerank("q", _candidates(("a", "text a")))

    assert attempts["n"] == 1  # no retry at all
    assert sleeps == []


def test_retries_exhausted_still_raises_transient_error():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(503)  # always transient -- retry budget must exhaust

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    reranker = TeiReranker(client, FakeGpuLock(), max_retries=2, retry_sleep=sleeps.append)

    with pytest.raises(TransientError):
        reranker.rerank("q", _candidates(("a", "text a")))

    assert attempts["n"] == 3  # initial attempt + 2 retries
    assert sleeps == [1.0, 2.0]  # exponential backoff between each of the 2 retries


def test_malformed_response_body_maps_to_permanent_error():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())

    with pytest.raises(PermanentError):
        reranker.rerank("q", _candidates(("a", "text a")))


def test_response_index_out_of_range_maps_to_permanent_error():
    def handler(request):
        return httpx.Response(200, json=[{"index": 5, "score": 1.0}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())

    with pytest.raises(PermanentError):
        reranker.rerank("q", _candidates(("a", "text a")))


# ---------------------------------------------------------------------------
# Live isolated test (DATA-CONTRACTS.md "Reranker": isolated, not a contract/agreement pair —
# V0 has only one reranker choice, so there's no second adapter to prove agreement against).
# ---------------------------------------------------------------------------


@pytest.mark.enable_socket
def test_real_reranker_returns_a_valid_permutation_of_a_real_candidate_set():
    client = httpx.Client(base_url="http://localhost:8082", timeout=30.0)
    reranker = TeiReranker(client, FakeGpuLock())
    candidates = _candidates(
        ("relevant", "we estimate the average treatment effect using double machine learning"),
        ("irrelevant", "a recipe for chocolate chip cookies"),
        ("neutral", "the weather today is partly cloudy with a chance of rain"),
    )
    try:
        result = reranker.rerank("treatment effect estimation methods", candidates)
    except (httpx.HTTPError, TransientError) as e:
        pytest.skip(f"no live reranker reachable at localhost:8082: {e}")

    assert {c.id for c in result} == {"relevant", "irrelevant", "neutral"}
    assert len(result) == 3
    assert result[0].id == "relevant"  # the real cross-encoder should rank the on-topic text first


@pytest.mark.enable_socket
def test_real_reranker_accepts_a_full_max_batch_sized_batch():
    # T-DOC25 regression, now pinned against the constant's real home: T-DOC24 originally set
    # rag.retriever._RERANK_POOL_SIZE=50, but the real deployed TEI reranker enforces a hard
    # server-side max batch size of 32 -- every real rerank() call with the full pool 422'd
    # ("batch size 50 > maximum allowed batch size 32"), breaking every single real retrieve()
    # call in production. No fakes-only test could catch this (FakeReranker has no batch-size
    # ceiling). T-DOC39 moved the ceiling itself into this module (`_MAX_BATCH_SIZE`, this is now
    # the vendor limit's one authoritative home, not a retriever-owned tuning number) -- import the
    # real constant, not a hardcoded number, so this stays in sync with whatever rerank() actually
    # enforces.
    from rag.reranker import _MAX_BATCH_SIZE

    client = httpx.Client(base_url="http://localhost:8082", timeout=30.0)
    reranker = TeiReranker(client, FakeGpuLock())
    candidates = _candidates(
        *[(str(i), f"filler passage number {i} about causal inference") for i in range(_MAX_BATCH_SIZE)]
    )
    try:
        result = reranker.rerank("treatment effect estimation methods", candidates)
    except (httpx.HTTPError, TransientError) as e:
        pytest.skip(f"no live reranker reachable at localhost:8082: {e}")
    except PermanentError as e:
        pytest.fail(
            f"_MAX_BATCH_SIZE={_MAX_BATCH_SIZE} exceeds what the real reranker server accepts: {e}"
        )

    assert len(result) == _MAX_BATCH_SIZE


@pytest.mark.enable_socket
def test_real_tei_endpoint_rejects_one_batch_item_over_the_max():
    # T-DOC39: the test that would have caught T-DOC24 before it merged. Pins BOTH edges of the
    # real boundary rather than trusting `_MAX_BATCH_SIZE` alone: the test above proves the real
    # server accepts exactly `_MAX_BATCH_SIZE`; this one proves it genuinely rejects one more --
    # so the constant isn't stale in either direction (too high risks a silent production 422
    # again; too low leaves real batch headroom unused). Posts straight to TEI's `/rerank`
    # endpoint, deliberately bypassing `TeiReranker.rerank()`'s own clamp (T-DOC39) -- that clamp
    # is what protects production from ever sending an oversized batch, but going through it here
    # would silently truncate the batch back down to `_MAX_BATCH_SIZE` and hide a stale assumption
    # from this test instead of surfacing it.
    from rag.reranker import _MAX_BATCH_SIZE

    client = httpx.Client(base_url="http://localhost:8082", timeout=30.0)
    texts = [
        f"filler passage number {i} about causal inference" for i in range(_MAX_BATCH_SIZE + 1)
    ]
    try:
        response = client.post(
            "/rerank",
            json={"query": "treatment effect estimation methods", "texts": texts},
        )
    except httpx.HTTPError as e:
        pytest.skip(f"no live reranker reachable at localhost:8082: {e}")

    assert response.status_code == 422, (
        f"expected the real TEI server to reject a batch of {_MAX_BATCH_SIZE + 1} (one over "
        f"_MAX_BATCH_SIZE={_MAX_BATCH_SIZE}) with a 422 -- got {response.status_code}. If TEI's "
        f"real deployed limit has changed, update _MAX_BATCH_SIZE (rag/reranker.py) to match; "
        f"don't just relax this test."
    )
