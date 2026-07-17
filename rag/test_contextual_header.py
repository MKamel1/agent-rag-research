"""T-DOC41 (Contextual Retrieval spike) — `rag/contextual_header.ContextualHeaderGenerator` test
suite. Zero-GPU, zero-network (TEST-STRATEGY.md golden rule): a `FakeGpuLock` plus an
`httpx.Client` wired to `httpx.MockTransport` (same offline-fixture style
`rag/test_summarizer.py`/`rag/test_reranker.py` already use) -- no real generation-LLM server, no
GPU, ever, in this file.
"""

import json

import httpx
import pytest

from contracts.errors import PermanentError, TransientError
from rag.contextual_header import DEFAULT_HEADER_PROMPT, ContextualHeaderGenerator
from rag.fakes.fake_gpu_lock import FakeGpuLock

_SUMMARY = "This paper proposes a doubly-robust estimator for treatment effects."
_CHUNK = "L(theta) = E[(Y - m(X))^2] + lambda * ||theta||_1"


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://generation-llm.local", transport=httpx.MockTransport(handler)
    )


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"response": "This is the loss term for the estimator."})


# ---------------------------------------------------------------------------
# Precondition: empty summary or chunk short-circuits, never touches the LLM or the lock
# ---------------------------------------------------------------------------


def test_empty_summary_returns_empty_string_without_calling_llm_or_lock():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_handler(request)

    lock = FakeGpuLock()
    adapter = ContextualHeaderGenerator(_client(handler), lock, "test-model")

    assert adapter.generate("", _CHUNK) == ""
    assert adapter.generate("   ", _CHUNK) == ""
    assert calls == []
    assert lock.acquired == []


def test_empty_chunk_returns_empty_string_without_calling_llm_or_lock():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok_handler(request)

    lock = FakeGpuLock()
    adapter = ContextualHeaderGenerator(_client(handler), lock, "test-model")

    assert adapter.generate(_SUMMARY, "") == ""
    assert adapter.generate(_SUMMARY, "  \n ") == ""
    assert calls == []
    assert lock.acquired == []


# ---------------------------------------------------------------------------
# Prompt formatting: both summary and chunk actually land in the request
# ---------------------------------------------------------------------------


def test_generate_formats_prompt_with_summary_and_chunk():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_handler(request)

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    adapter.generate(_SUMMARY, _CHUNK)

    prompt = captured["body"]["prompt"]
    assert _SUMMARY in prompt
    assert _CHUNK in prompt
    assert prompt == DEFAULT_HEADER_PROMPT.format(summary=_SUMMARY, chunk=_CHUNK)
    assert captured["body"]["model"] == "test-model"


def test_generate_accepts_a_custom_prompt_template():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_handler(request)

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    custom = "SUMMARY={summary} CHUNK={chunk}"
    adapter.generate(_SUMMARY, _CHUNK, prompt=custom)

    assert captured["body"]["prompt"] == custom.format(summary=_SUMMARY, chunk=_CHUNK)


# ---------------------------------------------------------------------------
# GPU lock: acquires "header" (never "summarize"/"embed"/"rerank")
# ---------------------------------------------------------------------------


def test_generate_acquires_the_gpu_lock_with_the_header_stage_label():
    lock = FakeGpuLock()
    adapter = ContextualHeaderGenerator(_client(_ok_handler), lock, "test-model")
    adapter.generate(_SUMMARY, _CHUNK)
    assert lock.acquired == ["header"]


# ---------------------------------------------------------------------------
# Happy path + clamping
# ---------------------------------------------------------------------------


def test_generate_returns_the_llm_response_text():
    adapter = ContextualHeaderGenerator(_client(_ok_handler), FakeGpuLock(), "test-model")
    assert adapter.generate(_SUMMARY, _CHUNK) == "This is the loss term for the estimator."


def test_generate_clamps_an_overlong_response_to_the_max_word_ceiling():
    long_header = " ".join(f"word{i}" for i in range(500))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": long_header})

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    result = adapter.generate(_SUMMARY, _CHUNK)
    assert len(result.split()) <= 130
    assert result == " ".join(long_header.split()[:130])


# ---------------------------------------------------------------------------
# Vendor/HTTP failure mapping (CONVENTIONS §4): never a bare httpx/KeyError exception
# ---------------------------------------------------------------------------


def test_5xx_response_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "model is loading"})

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    with pytest.raises(TransientError):
        adapter.generate(_SUMMARY, _CHUNK)


def test_4xx_response_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    with pytest.raises(PermanentError):
        adapter.generate(_SUMMARY, _CHUNK)


def test_connection_failure_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    with pytest.raises(TransientError):
        adapter.generate(_SUMMARY, _CHUNK)


def test_response_missing_response_field_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    with pytest.raises(PermanentError):
        adapter.generate(_SUMMARY, _CHUNK)


def test_empty_llm_response_raises_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "   "})

    adapter = ContextualHeaderGenerator(_client(handler), FakeGpuLock(), "test-model")
    with pytest.raises(PermanentError):
        adapter.generate(_SUMMARY, _CHUNK)
