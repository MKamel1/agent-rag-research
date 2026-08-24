"""JUDGE-1 — `app/judge_llm.LlmJudge` test suite. Zero-GPU, zero-network (TEST-STRATEGY.md golden
rule): a `FakeGpuLock` plus an `httpx.Client` wired to `httpx.MockTransport` (same offline-fixture
style `rag/test_summarizer.py`/`rag/test_contextual_header.py` already use) -- no real generation-LLM
server, no GPU, ever, in this file.
"""

import json

import httpx
import pytest

from app.judge_eval import AuditItem, Claim
from app.judge_llm import LlmJudge
from contracts.errors import PermanentError, TransientError
from rag.fakes.fake_gpu_lock import FakeGpuLock

_RUBRIC = "A claim is supported/unsupported/contradicted per the passages."


def _item() -> AuditItem:
    return AuditItem(
        question_id="Q-1",
        question_text="What did the paper find?",
        passages=("The passage says X causes a 10% reduction in Y.",),
        answer="X causes a 10% reduction in Y.",
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://generation-llm.local", transport=httpx.MockTransport(handler)
    )


def _ok_handler_returning(claims_json: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": json.dumps(claims_json)})

    return handler


_ONE_SUPPORTED_CLAIM = [
    {"claim": "X causes a 10% reduction in Y", "verdict": "supported", "rationale": "passage says so"}
]


# ---------------------------------------------------------------------------
# Happy path: parses the model's JSON array into Claims
# ---------------------------------------------------------------------------


def test_call_returns_claims_parsed_from_the_judge_response():
    judge = LlmJudge(_client(_ok_handler_returning(_ONE_SUPPORTED_CLAIM)), FakeGpuLock(), "m")
    claims = judge(_item(), _RUBRIC)

    assert claims == [
        Claim(text="X causes a 10% reduction in Y", verdict="supported", rationale="passage says so")
    ]


def test_call_handles_all_three_verdicts():
    payload = [
        {"claim": "a", "verdict": "supported", "rationale": "r-a"},
        {"claim": "b", "verdict": "unsupported", "rationale": "r-b"},
        {"claim": "c", "verdict": "contradicted", "rationale": "r-c"},
    ]
    judge = LlmJudge(_client(_ok_handler_returning(payload)), FakeGpuLock(), "m")
    claims = judge(_item(), _RUBRIC)

    assert {c.verdict for c in claims} == {"supported", "unsupported", "contradicted"}


def test_call_handles_an_empty_claim_list():
    judge = LlmJudge(_client(_ok_handler_returning([])), FakeGpuLock(), "m")
    assert judge(_item(), _RUBRIC) == []


def test_call_strips_a_markdown_code_fence_around_the_json():
    def handler(request: httpx.Request) -> httpx.Response:
        fenced = "```json\n" + json.dumps(_ONE_SUPPORTED_CLAIM) + "\n```"
        return httpx.Response(200, json={"response": fenced})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    claims = judge(_item(), _RUBRIC)
    assert claims[0].verdict == "supported"


# ---------------------------------------------------------------------------
# Prompt formatting: rubric, question, numbered passages, and answer all land in the request
# ---------------------------------------------------------------------------


def test_call_formats_prompt_with_rubric_question_passages_and_answer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_handler_returning(_ONE_SUPPORTED_CLAIM)(request)

    judge = LlmJudge(_client(handler), FakeGpuLock(), "test-model")
    item = _item()
    judge(item, _RUBRIC)

    prompt = captured["body"]["prompt"]
    assert _RUBRIC in prompt
    assert item.question_text in prompt
    assert "[1] " + item.passages[0] in prompt
    assert item.answer in prompt
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["think"] is False


def test_call_numbers_multiple_passages():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_handler_returning([])(request)

    item = AuditItem(
        question_id="Q-2", question_text="q", passages=("first excerpt", "second excerpt"), answer="a"
    )
    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    judge(item, _RUBRIC)

    prompt = captured["body"]["prompt"]
    assert "[1] first excerpt" in prompt
    assert "[2] second excerpt" in prompt


# ---------------------------------------------------------------------------
# GPU lock: acquires "judge" (never "summarize"/"embed"/"rerank"/"header")
# ---------------------------------------------------------------------------


def test_call_acquires_the_gpu_lock_with_the_judge_stage_label():
    lock = FakeGpuLock()
    judge = LlmJudge(_client(_ok_handler_returning([])), lock, "m")
    judge(_item(), _RUBRIC)
    assert lock.acquired == ["judge"]


# ---------------------------------------------------------------------------
# Vendor/HTTP failure mapping (CONVENTIONS §4): never a bare httpx/KeyError/ValueError exception
# ---------------------------------------------------------------------------


def test_5xx_response_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "model is loading"})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(TransientError):
        judge(_item(), _RUBRIC)


def test_4xx_response_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(PermanentError):
        judge(_item(), _RUBRIC)


def test_connection_failure_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(TransientError):
        judge(_item(), _RUBRIC)


def test_200_with_undecodable_body_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>gateway garbage</html>")

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(TransientError):
        judge(_item(), _RUBRIC)


# ---------------------------------------------------------------------------
# Malformed judge output: every shape failure is a PermanentError naming the question_id, never a
# raw exception escaping the Judge Protocol's contract
# ---------------------------------------------------------------------------


def test_non_json_response_maps_to_permanent_error_naming_the_question():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "not json at all"})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(PermanentError, match="Q-1"):
        judge(_item(), _RUBRIC)


def test_json_object_instead_of_array_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": json.dumps({"claim": "a"})})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(PermanentError):
        judge(_item(), _RUBRIC)


def test_claim_entry_missing_a_required_key_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        bad = [{"claim": "a", "verdict": "supported"}]  # no "rationale"
        return httpx.Response(200, json={"response": json.dumps(bad)})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(PermanentError):
        judge(_item(), _RUBRIC)


def test_unknown_verdict_literal_maps_to_permanent_error_not_a_raw_value_error():
    def handler(request: httpx.Request) -> httpx.Response:
        bad = [{"claim": "a", "verdict": "maybe", "rationale": "r"}]
        return httpx.Response(200, json={"response": json.dumps(bad)})

    judge = LlmJudge(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(PermanentError, match="unknown verdict"):
        judge(_item(), _RUBRIC)
