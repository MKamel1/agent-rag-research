"""Tests for TeiReranker (real `Reranker` adapter, ARCHITECTURE.md §M7's injected collaborator).

Mocked tests (lock, reorder correctness, empty input, error taxonomy) run zero-GPU/zero-network in
default CI, mirroring rag/test_summarizer.py's pattern. The live test is `enable_socket`-gated and
skips cleanly if TEI's reranker isn't reachable, mirroring rag/test_vector_index.py's
`test_real_adapter_satisfies_contract` pattern — per DATA-CONTRACTS.md "Reranker", this is an
isolated real-adapter test, not a fake-vs-real contract/agreement pair (V0 has only one reranker).
"""

import contextlib

import httpx
import pytest

import rag.reranker as _mod
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


# ---------------------------------------------------------------------------
# ensure_ready hook: an optional, injected readiness check/side effect, fired once per rerank()
# call, before any HTTP work, and skipped entirely on the empty-candidates short-circuit.
# ---------------------------------------------------------------------------


def test_ensure_ready_hook_called_once_before_the_http_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 0, "score": 0.9}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    reranker.rerank("query", _candidates(("a", "text a")))

    assert calls == ["ready"]


def test_ensure_ready_hook_not_called_on_empty_candidates():
    calls = []
    client = httpx.Client(base_url="http://tei.local")
    reranker = TeiReranker(client, FakeGpuLock(), ensure_ready=lambda: calls.append("ready"))

    result = reranker.rerank("query", [])

    assert result == []
    assert calls == [], "an empty candidate list is a zero-cost no-op"


def test_no_ensure_ready_hook_is_the_unchanged_default():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 0, "score": 0.9}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())  # no ensure_ready kwarg at all

    result = reranker.rerank("query", _candidates(("a", "text a")))

    assert len(result) == 1


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


def test_rerank_splits_a_batch_over_the_max_into_chunks_and_keeps_every_candidate():
    # A caller-supplied batch over `_MAX_BATCH_SIZE` (a retriever pool built from `k > 32`;
    # McpServer exposes `k` unclamped) must never reach TEI at its full size -- that is the
    # T-DOC24/25 422/0%-recall crash. It must ALSO not be truncated, which is what this used to do:
    # truncation silently capped recall at 32 candidates no matter how many the caller had, and
    # pinned `_RERANK_POOL_SIZE` to 32 with it. Assert on what actually went over the wire (via the
    # mock transport), not just the return value, so a fix that chunks the *response* instead of
    # the *request* would not slip this test.
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
    total = reranker_module._MAX_BATCH_SIZE + 5
    oversized = _candidates(*[(str(i), f"text {i}") for i in range(total)])

    result = reranker.rerank("q", oversized)

    # Two requests, neither over the vendor limit.
    assert sent_batch_sizes == [reranker_module._MAX_BATCH_SIZE, 5]
    assert max(sent_batch_sizes) <= reranker_module._MAX_BATCH_SIZE
    # Nothing dropped: every candidate the caller supplied comes back.
    assert len(result) == total
    assert {c.id for c in result} == {str(i) for i in range(total)}


def test_rerank_merges_batches_by_score_not_by_batch_order():
    # The point of chunking is a GLOBAL ranking. A high-scoring candidate sitting in the SECOND
    # batch must outrank a low-scoring one from the first -- otherwise chunking would just be
    # truncation with extra steps, preserving the first batch's priority. Cross-encoder scores are
    # absolute per-(query, document) values, not normalised per request, which is what makes
    # comparing them across batches valid.
    import rag.reranker as reranker_module

    def handler(request):
        import json

        body = json.loads(request.content)
        # Score by the candidate's own text so scores are position-independent: "text N" -> N/100.
        scores = [int(text.split()[-1]) / 100.0 for text in body["texts"]]
        return httpx.Response(
            200, json=[{"index": i, "score": s} for i, s in enumerate(scores)]
        )

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, FakeGpuLock())
    total = reranker_module._MAX_BATCH_SIZE + 5
    candidates = _candidates(*[(str(i), f"text {i}") for i in range(total)])

    result = reranker.rerank("q", candidates)

    # Highest-numbered text scores highest and lives in the LAST batch -- it must come first.
    assert result[0].id == str(total - 1)
    assert [c.id for c in result] == [str(i) for i in range(total - 1, -1, -1)]


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


class _SpyGpuLock:
    """Records whether the lock is currently held -- proves a backoff sleep happens with the lock
    ALREADY RELEASED, not while still holding it (OG-48#3, mirrors rag/test_embedder.py's spy)."""

    def __init__(self):
        self.held = False

    def acquire(self, stage: str, *, timeout: float | None = None):
        return self._ctx()

    @contextlib.contextmanager
    def _ctx(self):
        self.held = True
        try:
            yield
        finally:
            self.held = False


def test_backoff_sleep_happens_with_the_gpu_lock_already_released():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"index": 0, "score": 1.0}])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    lock = _SpyGpuLock()
    held_during_sleep = []
    reranker = TeiReranker(client, lock, retry_sleep=lambda s: held_during_sleep.append(lock.held))

    reranker.rerank("q", _candidates(("a", "text a")))

    assert attempts["n"] == 2  # one retry happened, so the sleep actually ran
    assert held_during_sleep == [False]  # lock was free during the ONE backoff sleep


def test_rerank_raises_transient_error_when_gpu_lock_is_wedged(tmp_path):
    # OG-48#4: a bounded gpu_lock_timeout means waiting for a crashed/wedged holder gives up
    # instead of hanging forever. Real FileGpuLock, real temp lock file -- no GPU, no network.
    from rag.gpu_lock import FileGpuLock

    lock_path = tmp_path / "wedged.lock"
    holder = FileGpuLock(lock_path)
    contender = FileGpuLock(lock_path)

    def handler(request):
        raise AssertionError("must never reach the HTTP call -- the lock itself must time out")

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    reranker = TeiReranker(client, contender, gpu_lock_timeout=0.05)

    with holder.acquire("rerank"):
        with pytest.raises(TransientError):
            reranker.rerank("q", _candidates(("a", "text a")))


def test_rerank_default_gpu_lock_timeout_is_generous_not_none():
    reranker = TeiReranker(httpx.Client(base_url="http://tei.local"), FakeGpuLock())
    assert reranker._gpu_lock_timeout == _mod._DEFAULT_GPU_LOCK_TIMEOUT_S
    assert _mod._DEFAULT_GPU_LOCK_TIMEOUT_S is not None


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


# ================================================================================================
# Token-budget packing (2026-08-19). TEI enforces three limits, not one: max_client_batch_size 32,
# max_input_length 8192 per pair, and max_batch_tokens 16384 for the WHOLE request. Batching by item
# count alone respects only the first, so a 32-item batch of ordinary chunks (causal-corpus median
# ~566 est. tokens => ~18,100 for the batch) exceeds the token budget and TEI answers 413. That is
# non-retryable by design -- resending the same oversized batch fails identically -- so it dropped
# an eval question (Q-158) on every single run.
# ================================================================================================


def test_pack_batches_respects_the_token_budget_not_just_the_item_count():
    import rag.reranker as reranker_module

    # 20 items well under the 32-item cap, but far over the token budget.
    big = "word " * 3000                                   # ~5000 est. tokens each
    candidates = _candidates(*[(str(i), big) for i in range(20)])

    batches = reranker_module._pack_batches("q", candidates)

    assert len(batches) > 1, "item count alone would have sent this as ONE oversized batch"
    for batch in batches:
        est = sum(reranker_module._estimate_tokens(c.text) for c in batch) + \
              len(batch) * reranker_module._estimate_tokens("q")
        assert est <= reranker_module._MAX_BATCH_TOKENS or len(batch) == 1
    assert sum(len(b) for b in batches) == 20, "packing must never drop a candidate"


def test_pack_batches_counts_the_query_once_per_candidate():
    """`/rerank` scores (query, document) PAIRS, so an n-item batch tokenises the query n times.
    Ignoring that is how a batch that looks under budget still 413s."""
    import rag.reranker as reranker_module

    long_query = "q " * 2000                               # ~1300 est. tokens
    candidates = _candidates(*[(str(i), "short text") for i in range(32)])

    batches = reranker_module._pack_batches(long_query, candidates)

    assert len(batches) > 1, "32 * a long query alone blows the budget even with tiny documents"


def test_pack_batches_still_honours_the_item_cap_for_small_documents():
    import rag.reranker as reranker_module
    candidates = _candidates(*[(str(i), "tiny") for i in range(70)])

    batches = reranker_module._pack_batches("q", candidates)

    assert all(len(b) <= reranker_module._MAX_BATCH_SIZE for b in batches)
    assert sum(len(b) for b in batches) == 70


def test_oversized_single_document_is_truncated_to_the_models_own_ceiling():
    """TEI truncates at max_input_length server-side anyway, so the excess never affects the score
    -- sending it only risks blowing the batch budget."""
    import rag.reranker as reranker_module

    huge = "x" * (reranker_module._MAX_ITEM_TOKENS * reranker_module._CHARS_PER_TOKEN * 3)
    sent = reranker_module._truncate_to_item_budget(huge)

    assert len(sent) == reranker_module._MAX_ITEM_TOKENS * reranker_module._CHARS_PER_TOKEN
    assert reranker_module._truncate_to_item_budget("short") == "short"


def test_rerank_sends_truncated_text_but_returns_the_original_candidates():
    """The wire payload is capped; the caller's objects are not. A caller must get back exactly what
    it passed in, or `get_span`/citation resolution downstream would be reading a truncated text."""
    import rag.reranker as reranker_module

    def handler(request):
        import json
        body = json.loads(request.content)
        assert all(len(t) <= reranker_module._MAX_ITEM_TOKENS * reranker_module._CHARS_PER_TOKEN
                   for t in body["texts"])
        return httpx.Response(200, json=[{"index": i, "score": 1.0}
                                         for i in range(len(body["texts"]))])

    client = httpx.Client(base_url="http://tei.local", transport=httpx.MockTransport(handler))
    original = "y" * (reranker_module._MAX_ITEM_TOKENS * reranker_module._CHARS_PER_TOKEN * 2)
    result = TeiReranker(client, FakeGpuLock()).rerank("q", _candidates(("a", original)))

    assert result[0].text == original, "the candidate object itself must be untouched"
