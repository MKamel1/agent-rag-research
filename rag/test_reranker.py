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
    reranker = TeiReranker(client, FakeGpuLock())

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
    reranker = TeiReranker(client, FakeGpuLock())

    with pytest.raises(TransientError):
        reranker.rerank("q", _candidates(("a", "text a")))


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
def test_real_reranker_accepts_a_full_rerank_pool_sized_batch():
    # T-DOC25 regression: T-DOC24 set rag.retriever._RERANK_POOL_SIZE=50, but the real deployed
    # TEI reranker enforces a hard server-side max batch size of 32 -- every real rerank() call
    # with the full pool 422'd ("batch size 50 > maximum allowed batch size 32"), breaking every
    # single real retrieve() call in production. No fakes-only test could catch this (FakeReranker
    # has no batch-size ceiling). Import the real constant, not a hardcoded number, so this stays
    # in sync with whatever rag/retriever.py actually sends.
    from rag.retriever import _RERANK_POOL_SIZE

    client = httpx.Client(base_url="http://localhost:8082", timeout=30.0)
    reranker = TeiReranker(client, FakeGpuLock())
    candidates = _candidates(
        *[(str(i), f"filler passage number {i} about causal inference") for i in range(_RERANK_POOL_SIZE)]
    )
    try:
        result = reranker.rerank("treatment effect estimation methods", candidates)
    except (httpx.HTTPError, TransientError) as e:
        pytest.skip(f"no live reranker reachable at localhost:8082: {e}")
    except PermanentError as e:
        pytest.fail(
            f"_RERANK_POOL_SIZE={_RERANK_POOL_SIZE} exceeds what the real reranker server "
            f"accepts: {e}"
        )

    assert len(result) == _RERANK_POOL_SIZE
