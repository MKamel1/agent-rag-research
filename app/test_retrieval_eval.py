"""Unit tests for `app/retrieval_eval.py` (T-DOC41). Zero-GPU, zero-network: every test uses a
local `FakeRetriever` double (never the real `app.assembly.build_mcp_server` wiring) and
hand-built `GroundedResult`s -- no `rag/fakes/` collaborators needed since nothing here exercises
the embed/hybrid/RRF/rerank pipeline itself, only the scoring math sitting on top of whatever a
`Retriever.retrieve()`-shaped call returns.
"""

import json

import pytest

from app.retrieval_eval import (
    Question,
    build_report,
    load_questions,
    run,
    score_question,
)
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult

_CITATION = Citation(
    paper_id="P1", title="A Paper", authors=["A. Author"],
    arxiv_url="https://arxiv.org/abs/P1", section_path="3 Method",
)


def _hit(paper_id: str, block_id: str) -> GroundedResult:
    return GroundedResult(
        passage_text="some chunk text",
        anchor=Anchor(
            paper_id=paper_id, block_id=block_id, page=0, bbox=(0.0, 0.0, 1.0, 1.0),
            snippet="snippet", section_path="3 Method",
        ),
        paper_id=paper_id,
        score=1.0,
        citation=_CITATION,
    )


class FakeRetriever:
    """`.retrieve(query, filters, k) -> (list[GroundedResult], None)`, the same shape
    `Retriever.retrieve()` returns (the coverage element is unused by the runner, so a fake needn't
    build a real `RetrievalCoverage`). Canned per-query results, keyed by exact query text; a query
    with no entry raises (simulates a real retrieval error) unless `default=[]` is set.
    """

    def __init__(self, responses: dict[str, list[GroundedResult]], *, default=None):
        self._responses = responses
        self._default = default
        self.calls: list[str] = []

    def retrieve(self, query: str, filters, k: int):
        self.calls.append(query)
        if query not in self._responses:
            if self._default is not None:
                return self._default, None
            raise RuntimeError(f"FakeRetriever: no canned response for query {query!r}")
        return self._responses[query][:k], None


# --- load_questions ---------------------------------------------------------------------------


def test_load_questions_self_contained_record(tmp_path):
    gt_path = tmp_path / "eval_equation_slice.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-EQ-001",
                "question_text": "What is the loss function?",
                "source_paper_id": "P1",
                "question_type": "Equation-Retrieval",
                "gold_block_id": "P1:b5",
            },
        ],
    }))

    questions = load_questions(gt_path)

    assert questions == [
        Question(
            question_id="Q-EQ-001",
            question_text="What is the loss function?",
            question_type="Equation-Retrieval",
            gold_paper_ids=frozenset({"P1"}),
            gold_block_id="P1:b5",
        )
    ]


def test_load_questions_joins_sibling_blind_file(tmp_path):
    (tmp_path / "eval_questions_blind.json").write_text(json.dumps({
        "questions": [
            {"question_id": "Q-001", "question_text": "What did they find?",
             "question_type": "Result-Comprehension"},
        ],
    }))
    gt_path = tmp_path / "eval_ground_truth.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-001",
                "answer_text": "...",
                "source_paper_id": "P1",
                "question_type": "Result-Comprehension",
            },
        ],
    }))

    questions = load_questions(gt_path)

    assert len(questions) == 1
    assert questions[0].question_text == "What did they find?"
    assert questions[0].gold_block_id is None  # 210-set records carry no gold_block_id


def test_load_questions_multi_gold_paper_ids(tmp_path):
    gt_path = tmp_path / "eval_ground_truth.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-101",
                "question_text": "embedded text",
                "source_paper_id": "P1",
                "question_type": "Multi-Paper-Synthesis",
                "additional_gold_paper_ids": ["P2"],
            },
        ],
    }))

    questions = load_questions(gt_path)

    assert questions[0].gold_paper_ids == frozenset({"P1", "P2"})


def test_load_questions_missing_text_raises(tmp_path):
    # blind sibling exists but doesn't cover this question_id -- exercises the "still missing
    # after checking the blind file" guard, distinct from a bare missing-file crash.
    (tmp_path / "eval_questions_blind.json").write_text(json.dumps({
        "questions": [
            {"question_id": "Q-OTHER", "question_text": "unrelated", "question_type": "X"},
        ],
    }))
    gt_path = tmp_path / "eval_ground_truth.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {"question_id": "Q-001", "source_paper_id": "P1", "question_type": "X"},
        ],
    }))
    with pytest.raises(ValueError, match="Q-001"):
        load_questions(gt_path)


# --- score_question ----------------------------------------------------------------------------


def test_score_question_paper_and_passage_hit_at_rank_1():
    q = Question("Q1", "text", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5")
    results = [_hit("P1", "P1:b5"), _hit("P2", "P2:b1")]

    r = score_question(q, results, k=10)

    assert r.paper_rank == 1
    assert r.passage_rank == 1
    assert r.passage_scored is True


def test_score_question_right_paper_wrong_block_is_paper_hit_passage_miss():
    """The case the ticket explicitly calls out: the correct PAPER is present in the results, but
    not the specific gold BLOCK -- must count as a paper-level hit and a passage-level miss, not
    the same outcome at both granularities. This is exactly what the paper-level-only 210-set
    scoring can't distinguish and the equation slice exists to catch.
    """
    q = Question("Q1", "text", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5")
    # P1 appears, but anchored at a different block than the gold equation's chunk.
    results = [_hit("P1", "P1:b99"), _hit("P2", "P2:b1")]

    r = score_question(q, results, k=10)

    assert r.paper_rank == 1
    assert r.passage_rank is None


def test_score_question_no_hit_at_all():
    q = Question("Q1", "text", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5")
    results = [_hit("P2", "P2:b1"), _hit("P3", "P3:b1")]

    r = score_question(q, results, k=10)

    assert r.paper_rank is None
    assert r.passage_rank is None


def test_score_question_rank_reflects_position_not_just_presence():
    q = Question("Q1", "text", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5")
    results = [_hit("P9", "P9:b1"), _hit("P8", "P8:b1"), _hit("P1", "P1:b5")]

    r = score_question(q, results, k=10)

    assert r.paper_rank == 3
    assert r.passage_rank == 3


def test_score_question_no_gold_block_id_is_not_passage_scored():
    """210-set questions carry no gold_block_id -- passage-level must be skipped (not scored as a
    miss), so it doesn't silently drag passage-level Recall@10 toward zero for a file that was
    never meant to support that granularity.
    """
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [_hit("P1", "P1:b5")]

    r = score_question(q, results, k=10)

    assert r.paper_rank == 1
    assert r.passage_scored is False
    assert r.passage_rank is None


def test_score_question_multi_gold_paper_match():
    q = Question("Q101", "text", "Multi-Paper-Synthesis", frozenset({"P1", "P2"}), gold_block_id=None)
    results = [_hit("P9", "P9:b1"), _hit("P2", "P2:b1")]  # co-source paper P2, not primary P1

    r = score_question(q, results, k=10)

    assert r.paper_rank == 2


def test_score_question_respects_k_truncation():
    q = Question("Q1", "text", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5")
    # gold hit is present but past k=1
    results = [_hit("P9", "P9:b1"), _hit("P1", "P1:b5")]

    r = score_question(q, results, k=1)

    assert r.paper_rank is None
    assert r.passage_rank is None


# --- run ------------------------------------------------------------------------------------


def test_run_scores_each_question_via_the_retriever():
    questions = [
        Question("Q1", "query one", "Equation-Retrieval", frozenset({"P1"}), "P1:b5"),
        Question("Q2", "query two", "Equation-Retrieval", frozenset({"P2"}), "P2:b1"),
    ]
    retriever = FakeRetriever({
        "query one": [_hit("P1", "P1:b5")],
        "query two": [_hit("P9", "P9:b1")],
    })

    results = run(questions, retriever, k=10)

    assert retriever.calls == ["query one", "query two"]
    assert results[0].paper_rank == 1 and results[0].passage_rank == 1
    assert results[1].paper_rank is None and results[1].passage_rank is None


def test_run_records_retrieval_error_without_aborting_the_whole_run():
    questions = [
        Question("Q1", "boom", "Equation-Retrieval", frozenset({"P1"}), "P1:b5"),
        Question("Q2", "query two", "Equation-Retrieval", frozenset({"P2"}), "P2:b1"),
    ]
    retriever = FakeRetriever({"query two": [_hit("P2", "P2:b1")]})  # "boom" has no canned entry

    results = run(questions, retriever, k=10)

    assert results[0].error is not None
    assert results[0].paper_rank is None
    # the second question still gets scored -- one bad question doesn't blank the whole run
    assert results[1].paper_rank == 1
    assert results[1].error is None


# --- build_report -----------------------------------------------------------------------------


def test_build_report_paper_vs_passage_granularity_and_by_type():
    from app.retrieval_eval import QuestionResult

    results = [
        QuestionResult("Q1", "Equation-Retrieval", paper_rank=1, passage_rank=1, passage_scored=True),
        QuestionResult("Q2", "Equation-Retrieval", paper_rank=1, passage_rank=None, passage_scored=True),
        QuestionResult("Q3", "Result-Comprehension", paper_rank=2, passage_rank=None, passage_scored=False),
    ]

    report = build_report(results, k=10)

    assert report["n_questions"] == 3
    # paper-level: all 3 questions scored, 3/3 hits
    assert report["paper_level"]["overall"]["n"] == 3
    assert report["paper_level"]["overall"]["recall_at_k"] == 1.0
    # passage-level: only the 2 passage_scored questions count, 1/2 hits
    assert report["passage_level"]["n_scored"] == 2
    assert report["passage_level"]["overall"]["recall_at_k"] == 0.5
    assert report["passage_level"]["overall"]["mrr"] == 0.5
    # Result-Comprehension never appears in the passage-level breakout (no scored questions of
    # that type) -- confirms per-type reporting doesn't fabricate an empty-but-present split.
    assert "Result-Comprehension" not in report["passage_level"]["by_question_type"]
    assert report["paper_level"]["by_question_type"]["Result-Comprehension"]["n"] == 1


def test_build_report_handles_no_passage_scorable_questions():
    from app.retrieval_eval import QuestionResult

    results = [
        QuestionResult("Q1", "Result-Comprehension", paper_rank=1, passage_rank=None, passage_scored=False),
    ]

    report = build_report(results, k=10)

    assert report["passage_level"]["n_scored"] == 0
    assert report["passage_level"]["overall"] == {"recall_at_k": None, "mrr": None, "n": 0}
