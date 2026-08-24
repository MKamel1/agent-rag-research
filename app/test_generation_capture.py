"""Unit tests for `app/generation_capture.py` (FAB-1). Zero-GPU, zero-network (TEST-STRATEGY.md
golden rule): `AnswerGenerator` is exercised through `httpx.MockTransport` + `FakeGpuLock` (same
offline-fixture style `app/test_judge_llm.py` already uses); `capture_run` is exercised through a
local `FakeRetriever` + a canned callable generator, never the real `app.assembly` wiring.
"""

import json
from pathlib import Path

import httpx
import pytest

from app.generation_capture import (
    GENERATION_PROMPT,
    AnswerGenerator,
    _fit_passages_for_generation,
    _num_ctx_for,
    capture_run,
    load_questions,
)
from contracts.errors import PermanentError, TransientError
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult
from rag.fakes.fake_gpu_lock import FakeGpuLock


def _hit(paper_id: str, passage_text: str, block_id: str = "b1") -> GroundedResult:
    return GroundedResult(
        passage_text=passage_text,
        anchor=Anchor(
            paper_id=paper_id, block_id=block_id, page=0, bbox=(0.0, 0.0, 1.0, 1.0),
            snippet="snippet", section_path="3 Method",
        ),
        paper_id=paper_id,
        score=1.0,
        citation=Citation(
            paper_id=paper_id, title="A Paper", authors=["A. Author"],
            arxiv_url=f"https://arxiv.org/abs/{paper_id}", section_path="3 Method",
        ),
    )


class FakeRetriever:
    """`.retrieve(query, filters, k) -> (list[GroundedResult], None)` -- same canned-by-query-text
    shape as `app/test_retrieval_eval.py::FakeRetriever`."""

    def __init__(self, responses: dict[str, list[GroundedResult]]):
        self._responses = responses
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, filters, k: int):
        self.calls.append((query, k))
        if query not in self._responses:
            raise RuntimeError(f"FakeRetriever: no canned response for query {query!r}")
        return self._responses[query][:k], None


def _fake_generator(answer: str = "the answer"):
    calls = []

    def generator(question_text: str, passages: tuple[tuple[str, str], ...]) -> str:
        calls.append((question_text, passages))
        return answer

    generator.calls = calls
    return generator


# ---------------------------------------------------------------------------
# load_questions: every record, in order, duplicates included
# ---------------------------------------------------------------------------


def test_load_questions_returns_every_record_including_duplicates(tmp_path: Path):
    gt = {
        "ground_truth": [
            {"question_id": "Q-1", "question_text": "first?"},
            {"question_id": "Q-2", "question_text": "second?", "duplicate_of": "Q-1"},
        ]
    }
    path = tmp_path / "gt.json"
    path.write_text(json.dumps(gt))

    questions = load_questions(path)

    assert questions == [("Q-1", "first?"), ("Q-2", "second?")]


# ---------------------------------------------------------------------------
# _fit_passages_for_generation: rank-order fill, tail dropped whole, never mid-passage --
# except the single-passage-exceeds-budget guard
# ---------------------------------------------------------------------------


def test_fit_keeps_all_passages_when_well_under_budget():
    passages = (("p1", "short passage one"), ("p2", "short passage two"))
    kept, truncated = _fit_passages_for_generation(passages)
    assert kept == passages
    assert truncated is False


def test_fit_drops_tail_passages_whole_when_over_budget():
    # max_words ~= (16384 - 300) / 2.2 ~= 7,311 words
    big = "word " * 5000
    passages = (("p1", big), ("p2", big), ("p3", "small passage"))
    kept, truncated = _fit_passages_for_generation(passages)
    assert truncated is True
    assert [p for p, _ in kept] == ["p1"]  # p2/p3 dropped whole, not cut into
    assert kept[0][1] == big  # p1 itself is intact, not truncated


def test_fit_truncates_the_first_passage_when_it_alone_exceeds_budget():
    huge = "word " * 20000  # alone exceeds the ~7,311-word budget
    passages = (("p1", huge), ("p2", "small"))
    kept, truncated = _fit_passages_for_generation(passages)
    assert truncated is True
    assert len(kept) == 1
    assert kept[0][0] == "p1"
    assert len(kept[0][1].split()) < len(huge.split())  # cut down, never dropped to zero


# ---------------------------------------------------------------------------
# _num_ctx_for: floor/ceiling arithmetic
# ---------------------------------------------------------------------------


def test_num_ctx_for_respects_floor_and_ceiling():
    assert _num_ctx_for((("p1", "one two three"),)) == 4096  # tiny input -> floor
    huge = "word " * 20000
    assert _num_ctx_for((("p1", huge),)) == 16384  # oversized input -> ceiling


# ---------------------------------------------------------------------------
# AnswerGenerator: happy path, prompt shape, GPU lock stage, HTTP failure mapping
# ---------------------------------------------------------------------------


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url="http://generation-llm.local", transport=httpx.MockTransport(handler)
    )


def _ok_handler_returning(text: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": text})

    return handler


def test_call_returns_the_generation_llm_response_text():
    gen = AnswerGenerator(_client(_ok_handler_returning("the answer")), FakeGpuLock(), "m")
    assert gen("a question", (("p1", "a passage"),)) == "the answer"


def test_call_formats_prompt_with_question_and_numbered_passages():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _ok_handler_returning("ok")(request)

    gen = AnswerGenerator(_client(handler), FakeGpuLock(), "test-model")
    gen("what happened?", (("p1", "first excerpt"), ("p2", "second excerpt")))

    prompt = captured["body"]["prompt"]
    assert "what happened?" in prompt
    assert "[1] first excerpt" in prompt
    assert "[2] second excerpt" in prompt
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["think"] is False
    assert "GENERATION_PROMPT" not in prompt  # sanity: the template itself, not its name, is sent
    assert GENERATION_PROMPT.split("\n\n")[0] in prompt  # the instruction line survived formatting


def test_call_acquires_the_gpu_lock_with_the_generate_stage_label():
    lock = FakeGpuLock()
    gen = AnswerGenerator(_client(_ok_handler_returning("ok")), lock, "m")
    gen("q", (("p1", "text"),))
    assert lock.acquired == ["generate"]


def test_5xx_response_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "model is loading"})

    gen = AnswerGenerator(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(TransientError):
        gen("q", (("p1", "text"),))


def test_4xx_response_maps_to_permanent_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    gen = AnswerGenerator(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(PermanentError):
        gen("q", (("p1", "text"),))


def test_connection_failure_maps_to_transient_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    gen = AnswerGenerator(_client(handler), FakeGpuLock(), "m")
    with pytest.raises(TransientError):
        gen("q", (("p1", "text"),))


# ---------------------------------------------------------------------------
# capture_run: retrieval + generation wiring, error tolerance, record shape
# ---------------------------------------------------------------------------


def test_capture_run_builds_judge_eval_shaped_records():
    retriever = FakeRetriever({"q1": [_hit("p1", "passage one"), _hit("p2", "passage two")]})
    generator = _fake_generator("generated answer")

    records = capture_run([("Q-1", "q1")], retriever, generator, k=10)

    assert records == [
        {
            "question_id": "Q-1",
            "question_text": "q1",
            "answer_text": "generated answer",
            "supporting_passages": [
                {"paper_id": "p1", "passage_excerpt": "passage one"},
                {"paper_id": "p2", "passage_excerpt": "passage two"},
            ],
            "n_passages_retrieved": 2,
            "n_passages_used": 2,
            "passages_truncated": False,
        }
    ]


def test_capture_run_passes_the_question_and_fitted_passages_to_the_generator():
    retriever = FakeRetriever({"q1": [_hit("p1", "passage one")]})
    generator = _fake_generator()

    capture_run([("Q-1", "q1")], retriever, generator, k=10)

    question_text, passages = generator.calls[0]
    assert question_text == "q1"
    assert passages == (("p1", "passage one"),)


def test_capture_run_only_feeds_the_generator_up_to_generation_k_passages():
    hits = [_hit(f"p{i}", f"passage {i}") for i in range(1, 8)]  # 7 hits, more than _GENERATION_K
    retriever = FakeRetriever({"q1": hits})
    generator = _fake_generator()

    records = capture_run([("Q-1", "q1")], retriever, generator, k=10)

    assert records[0]["n_passages_retrieved"] == 7
    assert records[0]["n_passages_used"] == 5  # _GENERATION_K


def test_capture_run_records_a_retrieval_error_without_aborting_the_run():
    retriever = FakeRetriever({"q2": [_hit("p1", "passage")]})  # no entry for q1
    generator = _fake_generator()

    records = capture_run([("Q-1", "q1"), ("Q-2", "q2")], retriever, generator, k=10)

    assert "error" in records[0]
    assert "answer_text" not in records[0]
    assert records[1]["answer_text"] == "the answer"


def test_capture_run_records_a_generation_error_without_aborting_the_run():
    retriever = FakeRetriever({"q1": [_hit("p1", "passage")]})

    def failing_generator(question_text, passages):
        raise TransientError("generation LLM server returned 503")

    records = capture_run([("Q-1", "q1")], retriever, failing_generator, k=10)

    assert "error" in records[0]
    assert "answer_text" not in records[0]
