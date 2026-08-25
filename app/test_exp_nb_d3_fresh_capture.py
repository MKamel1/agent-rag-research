"""`app/exp_nb_d3_fresh_capture.py` test suite. Zero-GPU, zero-network, zero-corpus
(TEST-STRATEGY.md golden rule): the live wiring in main() is deliberately not exercised here --
only `capture_fixture`'s own logic is, against a fake retriever and a tmp-path fixture.

What the module adds over plain retrieval_eval.run() is exactly three behaviours, so those are
what these tests pin: full score vectors (not just rank-1) per question, the absent flag derived
from the empty-gold partition, and error-isolated records that keep the fixture's denominators
intact when one question's retrieval blows up.
"""

import json
import types

import pytest

from app.exp_nb_d3_fresh_capture import capture_fixture


def _hit(score: float, paper_id: str):
    return types.SimpleNamespace(score=score, paper_id=paper_id)


class _FakeRetriever:
    def __init__(self, hits_by_text=None, explode_for=None):
        self.hits_by_text = hits_by_text or {}
        self.explode_for = explode_for
        self.calls = []

    def retrieve(self, text, filters, k):
        self.calls.append(text)
        if self.explode_for is not None and text == self.explode_for:
            raise RuntimeError("vector store exploded")
        return self.hits_by_text[text][:k], []


class _FakeServer:
    def __init__(self, retriever):
        self.retriever = retriever


@pytest.fixture
def fixture_path(tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({
        "ground_truth": [
            {"question_id": "Q-ANS-1", "question_text": "answerable ask",
             "source_paper_id": "1234.5678"},
            {"question_id": "Q-DUP", "question_text": "duplicate rewording",
             "source_paper_id": "1234.5678", "duplicate_of": "Q-ANS-1"},
            {"question_id": "Q-ABS-1", "question_text": "known-absent ask"},
        ]
    }))
    return path


def _hits(text):
    return [_hit(0.02 - i * 0.001, f"p{i}") for i in range(12)]


def test_full_score_vectors_and_absent_partition(fixture_path):
    retriever = _FakeRetriever(hits_by_text={
        "answerable ask": _hits("answerable ask"),
        "known-absent ask": _hits("known-absent ask"),
    })
    result = capture_fixture("test", fixture_path, _FakeServer(retriever), k=10)

    # duplicate excluded by load_questions' default -- same denominators as the baseline runner
    assert result["n_questions"] == 2
    assert result["n_errors"] == 0
    by_id = {r["question_id"]: r for r in result["questions"]}
    assert by_id["Q-ABS-1"]["absent"] is True
    assert by_id["Q-ANS-1"]["absent"] is False
    row = by_id["Q-ANS-1"]
    assert len(row["scores"]) == 10  # truncated to k even though the fake returned 12
    assert row["scores"][0] > row["scores"][1]
    assert row["paper_ids"] == [f"p{i}" for i in range(10)]


def test_k_truncation_respected(fixture_path):
    retriever = _FakeRetriever(hits_by_text={
        "answerable ask": [_hit(0.5, "only")],
        "known-absent ask": [],
    })
    result = capture_fixture("test", fixture_path, _FakeServer(retriever), k=10)
    by_id = {r["question_id"]: r for r in result["questions"]}
    assert by_id["Q-ANS-1"]["scores"] == [0.5]
    assert by_id["Q-ABS-1"]["scores"] == []  # zero results recorded, not silently dropped


def test_error_isolated_per_question(fixture_path):
    retriever = _FakeRetriever(
        hits_by_text={"known-absent ask": _hits("known-absent ask")},
        explode_for="answerable ask",
    )
    result = capture_fixture("test", fixture_path, _FakeServer(retriever), k=10)

    assert result["n_questions"] == 2
    assert result["n_errors"] == 1
    by_id = {r["question_id"]: r for r in result["questions"]}
    errored = by_id["Q-ANS-1"]
    assert errored["scores"] == [] and errored["paper_ids"] == []
    assert "vector store exploded" in errored["error"]
    assert by_id["Q-ABS-1"]["scores"]  # sibling question still scored
