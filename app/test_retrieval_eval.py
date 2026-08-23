"""Unit tests for `app/retrieval_eval.py` (T-DOC41). Zero-GPU, zero-network: most tests use a
local `FakeRetriever` double (never the real `app.assembly.build_mcp_server` wiring) and
hand-built `GroundedResult`s -- no `rag/fakes/` collaborators needed since nothing there exercises
the embed/hybrid/RRF/rerank pipeline itself, only the scoring math sitting on top of whatever a
`Retriever.retrieve()`-shaped call returns.

The RI-M3 sparse-ablation section near the bottom is the one deliberate exception: the ablation
itself lives one layer BELOW `FakeRetriever` (inside `VectorIndex.hybrid_search`/
`FakeVectorStore.hybrid_search`'s `rrf_fuse` call), so proving it works means wiring a real
`rag.retriever.Retriever` to the committed `FakeVectorStore`, the same way `rag/test_retriever.py`
does.
"""

import json

import pytest

from app.retrieval_eval import (
    SPARSE_MODES,
    Question,
    build_report,
    load_questions,
    run,
    score_question,
    sparse_mode_weight,
)
from contracts.mcp_server import PaperSearchResult, PaperSummaryView
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult


def _hit(
    paper_id: str,
    block_id: str,
    passage_text: str = "some chunk text",
    title: str = "A Paper",
) -> GroundedResult:
    return GroundedResult(
        passage_text=passage_text,
        anchor=Anchor(
            paper_id=paper_id, block_id=block_id, page=0, bbox=(0.0, 0.0, 1.0, 1.0),
            snippet="snippet", section_path="3 Method",
        ),
        paper_id=paper_id,
        score=1.0,
        citation=Citation(
            paper_id=paper_id, title=title, authors=["A. Author"],
            arxiv_url=f"https://arxiv.org/abs/{paper_id}", section_path="3 Method",
        ),
    )


def _chapter_hit(paper_id: str, chapter: str | None) -> PaperSearchResult:
    """A `search_papers`-shaped hit -- what `Retriever.retrieve_papers()` returns for a book
    chapter routing match (`chapter=None` is what a whole-paper/non-chapter hit looks like)."""
    return PaperSearchResult(
        view=PaperSummaryView(
            paper_id=paper_id, title="A Book", authors=["A. Author"], summary_text="summary",
            section_paths=[],
            citation=Citation(
                paper_id=paper_id, title="A Book", authors=["A. Author"],
                arxiv_url=f"https://example/{paper_id}", section_path="", doc_type="book",
            ),
        ),
        score=1.0,
        chapter=chapter,
    )


class FakeRetriever:
    """`.retrieve(query, filters, k) -> (list[GroundedResult], None)`, the same shape
    `Retriever.retrieve()` returns (the coverage element is unused by the runner, so a fake needn't
    build a real `RetrievalCoverage`). Canned per-query results, keyed by exact query text; a query
    with no entry raises (simulates a real retrieval error) unless `default=[]` is set.

    `chapter_responses` is the same shape for `.retrieve_papers()` (what `search_papers` wraps) --
    a separate canned dict since a real chapter-routing question's `retrieve()` and
    `retrieve_papers()` calls return different result TYPES (`GroundedResult` vs.
    `PaperSearchResult`) for the same query text.
    """

    def __init__(
        self, responses: dict[str, list[GroundedResult]], *, default=None,
        chapter_responses: dict[str, list[PaperSearchResult]] | None = None,
    ):
        self._responses = responses
        self._default = default
        self._chapter_responses = chapter_responses or {}
        self.calls: list[str] = []
        self.chapter_calls: list[str] = []

    def retrieve(self, query: str, filters, k: int):
        self.calls.append(query)
        if query not in self._responses:
            if self._default is not None:
                return self._default, None
            raise RuntimeError(f"FakeRetriever: no canned response for query {query!r}")
        return self._responses[query][:k], None

    def retrieve_papers(self, query: str, filters, k: int):
        self.chapter_calls.append(query)
        if query not in self._chapter_responses:
            raise RuntimeError(
                f"FakeRetriever: no canned chapter response for query {query!r}"
            )
        return self._chapter_responses[query][:k], None


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


def test_load_questions_book_fields(tmp_path):
    """A book question carries `doc_type` and `gold_chapter_title` -- a plain paper record (no
    such keys) must still default to `doc_type="paper"`/`gold_chapter_title=None` so every
    existing fixture (210-set, equation slice) parses unchanged."""
    gt_path = tmp_path / "eval_ground_truth.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "QB-001",
                "question_text": "What does Twyman's Law say?",
                "source_paper_id": "local:14b7e283bdcd",
                "question_type": "Book-Chapter-Recall",
                "doc_type": "book",
                "gold_chapter_title": "Hypothesis Testing: Establishing Statistical Significance",
                "gold_block_id": "local:14b7e283bdcd:b359",
            },
            {
                "question_id": "Q-001",
                "question_text": "unrelated",
                "source_paper_id": "P1",
                "question_type": "X",
            },
        ],
    }))

    questions = load_questions(gt_path)
    book_q, paper_q = questions

    assert book_q.doc_type == "book"
    assert book_q.gold_chapter_title == "Hypothesis Testing: Establishing Statistical Significance"
    assert paper_q.doc_type == "paper"
    assert paper_q.gold_chapter_title is None


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


# --- load_questions: the waymo_gt_verified.json shape (BENCH-1) ---------------------------------
# fixtures/eval/waymo_gt_verified.json differs from every fixture above in three ways at once:
# the 4 multi-paper-synthesis items carry NO top-level source_paper_id (only supporting_passages,
# each with its own paper_id), the 8 known-absent items omit source_paper_id entirely (not even
# null), and 40 of the 73 records carry `question_type: null`. All three must parse.


def test_load_questions_multi_paper_item_takes_gold_from_supporting_passages(tmp_path):
    """A record with no top-level source_paper_id but supporting_passages scores paper-level
    against the UNION of the supporting papers -- otherwise it would carry an empty gold set and
    count as a guaranteed miss, silently deflating recall."""
    gt_path = tmp_path / "waymo_gt.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-WAYB-010",
                "question_text": "How does X compare to Y?",
                "question_type": None,
                "tests": "answerable",
                "supporting_passages": [
                    {"paper_id": "P1", "gold_chunk_id": "P1:c14",
                     "gold_block_id": "P1:b68", "passage_excerpt": "..."},
                    {"paper_id": "P2", "gold_chunk_id": "P2:c2",
                     "gold_block_id": "P2:b9", "passage_excerpt": "..."},
                ],
            },
        ],
    }))

    [question] = load_questions(gt_path)

    assert question.gold_paper_ids == frozenset({"P1", "P2"})
    assert question.gold_block_id is None  # no top-level gold block -- paper-level only


def test_load_questions_supporting_sources_also_widen_the_gold_paper_set(tmp_path):
    """Records carrying supporting_sources alongside a primary still score the primary at passage
    level, and the co-source papers count as gold at paper level (same multi-gold methodology as
    additional_gold_paper_ids)."""
    gt_path = tmp_path / "waymo_gt.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-1",
                "question_text": "What was the crash rate?",
                "question_type": "Result-Comprehension",
                "source_paper_id": "P1",
                "gold_block_id": "P1:b89",
                "supporting_sources": [
                    {"paper_id": "P9", "gold_chunk_id": "P9:c16",
                     "gold_block_id": "P9:b90", "passage_excerpt": "..."},
                ],
            },
        ],
    }))

    [question] = load_questions(gt_path)

    assert question.gold_paper_ids == frozenset({"P1", "P9"})
    assert question.gold_block_id == "P1:b89"


def test_load_questions_known_absent_record_omitting_source_paper_id_has_no_gold(tmp_path):
    """The waymo absent items OMIT source_paper_id outright (unlike eval_known_absent.json's
    explicit null) -- same semantics either way: no gold paper, empty frozenset, never a stray
    KeyError or a `{None}` gold set."""
    gt_path = tmp_path / "waymo_gt.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-ABS",
                "question_text": "What does the corpus say about X?",
                "question_type": None,
                "tests": "absent",
                "absence_note": "...",
            },
        ],
    }))

    [question] = load_questions(gt_path)

    assert question.gold_paper_ids == frozenset()


def test_load_questions_null_question_type_is_reported_as_unlabeled_not_crashing(tmp_path):
    """40 of waymo_gt_verified.json's records carry `question_type: null` -- build_report sorts
    the distinct types, so a None landing in that set crashes sorted(). An explicit placeholder
    keeps the by-type breakdown working while saying plainly that no type was assigned."""
    from app.retrieval_eval import QuestionResult

    gt_path = tmp_path / "waymo_gt.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {"question_id": "Q-A", "question_text": "a", "question_type": None,
             "source_paper_id": "P1"},
            {"question_id": "Q-B", "question_text": "b", "question_type": "Result-X",
             "source_paper_id": "P1"},
        ],
    }))

    questions = load_questions(gt_path)
    assert questions[0].question_type == "Unlabeled"
    assert questions[1].question_type == "Result-X"

    # the crash this guards against lives in build_report's sorted() over result types
    results = [
        QuestionResult("Q-A", "Unlabeled", paper_rank=None, passage_rank=None,
                       passage_scored=False),
        QuestionResult("Q-B", "Result-X", paper_rank=None, passage_rank=None,
                       passage_scored=False),
    ]
    report = build_report(results, k=10)
    assert sorted(report["paper_level"]["by_question_type"]) == ["Result-X", "Unlabeled"]


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


def test_score_question_chapter_hit_at_rank_1():
    q = Question(
        "QB1", "text", "Book-Chapter-Recall", frozenset({"B1"}), gold_block_id=None,
        doc_type="book", gold_chapter_title="Chapter Three",
    )
    chapter_results = [_chapter_hit("B1", "Chapter Three"), _chapter_hit("B2", "Other")]

    r = score_question(q, results=[], k=10, chapter_results=chapter_results)

    assert r.chapter_scored is True
    assert r.chapter_rank == 1


def test_score_question_right_paper_wrong_chapter_is_a_chapter_miss():
    """Same paper, wrong chapter -- must not count as a chapter-routing hit (mirrors the
    paper-hit/passage-miss distinction score_question already makes at the passage granularity)."""
    q = Question(
        "QB1", "text", "Book-Chapter-Recall", frozenset({"B1"}), gold_block_id=None,
        doc_type="book", gold_chapter_title="Chapter Three",
    )
    chapter_results = [_chapter_hit("B1", "Chapter One")]

    r = score_question(q, results=[], k=10, chapter_results=chapter_results)

    assert r.chapter_rank is None


def test_score_question_no_gold_chapter_title_is_not_chapter_scored():
    """A plain paper question (no gold_chapter_title) must not be chapter-scored even if a
    chapter_results list happens to be passed -- mirrors passage_scored's gold_block_id gate."""
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)

    r = score_question(q, results=[_hit("P1", "P1:b1")], k=10, chapter_results=[])

    assert r.chapter_scored is False
    assert r.chapter_rank is None


def test_score_question_chapter_scored_but_no_chapter_results_is_a_miss_not_a_crash():
    """`run()` only omits `chapter_results` (leaves it `None`) when `retrieve_papers()` itself
    errored -- `score_question` must degrade to an unscored-but-flagged miss, not raise."""
    q = Question(
        "QB1", "text", "Book-Chapter-Recall", frozenset({"B1"}), gold_block_id=None,
        doc_type="book", gold_chapter_title="Chapter Three",
    )

    r = score_question(q, results=[], k=10, chapter_results=None)

    assert r.chapter_scored is True
    assert r.chapter_rank is None


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


def test_run_calls_retrieve_papers_only_for_chapter_scored_questions():
    """The extra `retrieve_papers()` call must fire for a book question carrying
    `gold_chapter_title` and must NOT fire for a plain paper question -- an unscored question
    costs no extra retrieval call (module docstring)."""
    questions = [
        Question("Q1", "paper query", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None),
        Question(
            "QB1", "book query", "Book-Chapter-Recall", frozenset({"B1"}), gold_block_id=None,
            doc_type="book", gold_chapter_title="Chapter Three",
        ),
    ]
    retriever = FakeRetriever(
        {"paper query": [_hit("P1", "P1:b1")], "book query": []},
        chapter_responses={"book query": [_chapter_hit("B1", "Chapter Three")]},
    )

    results = run(questions, retriever, k=10)

    assert retriever.chapter_calls == ["book query"]  # not called for "paper query"
    assert results[0].chapter_scored is False
    assert results[1].chapter_scored is True
    assert results[1].chapter_rank == 1


def test_run_records_error_when_retrieve_papers_fails():
    """`retrieve()` succeeding but the follow-up `retrieve_papers()` failing must record the
    WHOLE question as errored, not half-score it on paper/passage level alone."""
    questions = [
        Question(
            "QB1", "book query", "Book-Chapter-Recall", frozenset({"B1"}), gold_block_id=None,
            doc_type="book", gold_chapter_title="Chapter Three",
        ),
    ]
    retriever = FakeRetriever({"book query": [_hit("B1", "B1:ch2")]})  # no chapter_responses entry

    results = run(questions, retriever, k=10)

    assert results[0].error is not None
    assert results[0].paper_rank is None
    assert results[0].chapter_rank is None


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


def test_build_report_chapter_level_and_by_doc_type():
    """Chapter-level scoring plus the `by_doc_type` breakdown that lets a mixed paper+book fixture
    report both doc types separately from one run (docs/DESIGN-book-chapters-and-hierarchy.md Part
    3 Step 1: "must be able to evaluate books separately from papers, and report them separately")."""
    from app.retrieval_eval import QuestionResult

    results = [
        QuestionResult(
            "Q1", "Result-Comprehension", paper_rank=1, passage_rank=None, passage_scored=False,
            doc_type="paper",
        ),
        QuestionResult(
            "QB1", "Book-Chapter-Recall", paper_rank=1, passage_rank=1, passage_scored=True,
            doc_type="book", chapter_rank=1, chapter_scored=True,
        ),
        QuestionResult(
            "QB2", "Book-Chapter-Recall", paper_rank=None, passage_rank=None, passage_scored=True,
            doc_type="book", chapter_rank=None, chapter_scored=True,
        ),
    ]

    report = build_report(results, k=10)

    # chapter-level: only the 2 chapter_scored questions count, 1/2 hits
    assert report["chapter_level"]["n_scored"] == 2
    assert report["chapter_level"]["overall"]["recall_at_k"] == 0.5
    assert report["chapter_level"]["by_question_type"]["Book-Chapter-Recall"]["n"] == 2

    # by_doc_type: paper-level split cleanly between the 1 paper and 2 book questions
    assert report["paper_level"]["by_doc_type"]["paper"]["n"] == 1
    assert report["paper_level"]["by_doc_type"]["paper"]["recall_at_k"] == 1.0
    assert report["paper_level"]["by_doc_type"]["book"]["n"] == 2
    assert report["paper_level"]["by_doc_type"]["book"]["recall_at_k"] == 0.5


def test_build_report_no_chapter_scorable_questions_is_empty_not_error():
    """A papers-only fixture (the 210-set/equation-slice today) must report an empty, not
    crashing, chapter_level section."""
    from app.retrieval_eval import QuestionResult

    results = [
        QuestionResult("Q1", "Result-Comprehension", paper_rank=1, passage_rank=None, passage_scored=False),
    ]

    report = build_report(results, k=10)

    assert report["chapter_level"]["n_scored"] == 0
    assert report["chapter_level"]["overall"] == {"recall_at_k": None, "mrr": None, "n": 0}


# --- build_report: per-question breakdown (T-DOC57) -----------------------------------------


def test_build_report_per_question_array_default_on_via_full_pipeline():
    """End-to-end through run()+build_report() (not hand-built QuestionResults) so the array is
    exercised against exactly what a real eval run produces: one entry per question, right
    hit/rank at both granularities, and the paper-hit/passage-miss case the ticket calls out.
    """
    questions = [
        Question("Q1", "query one", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5"),
        Question("Q2", "query two", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5"),
        Question("Q3", "query three", "Result-Comprehension", frozenset({"P3"}), gold_block_id=None),
    ]
    retriever = FakeRetriever({
        "query one": [_hit("P1", "P1:b5")],  # paper hit + passage hit, rank 1
        "query two": [_hit("P1", "P1:b99"), _hit("P9", "P9:b1")],  # right paper, wrong block
        "query three": [_hit("P3", "P3:b1")],  # no gold_block_id -- not passage-scored
    })

    results = run(questions, retriever, k=10)
    report = build_report(results, k=10)

    assert "questions" in report  # default ON, no flag needed
    rows = {row["question_id"]: row for row in report["questions"]}
    assert len(rows) == 3

    assert rows["Q1"]["paper_level"] == {"hit": True, "rank": 1}
    assert rows["Q1"]["passage_level"] == {"scored": True, "hit": True, "rank": 1}
    assert rows["Q1"]["gold_paper_ids"] == ["P1"]
    assert rows["Q1"]["gold_block_id"] == "P1:b5"
    assert rows["Q1"]["error"] is None

    # the ticket's explicit case: paper hit=true, passage hit=false, with correct ranks at each
    assert rows["Q2"]["paper_level"] == {"hit": True, "rank": 1}
    assert rows["Q2"]["passage_level"] == {"scored": True, "hit": False, "rank": None}

    # no gold_block_id -- passage_level.scored is False, not a miss
    assert rows["Q3"]["paper_level"] == {"hit": True, "rank": 1}
    assert rows["Q3"]["passage_level"] == {"scored": False, "hit": False, "rank": None}


def test_build_report_per_question_array_marks_errors():
    questions = [
        Question("Q1", "boom", "Equation-Retrieval", frozenset({"P1"}), gold_block_id="P1:b5"),
    ]
    retriever = FakeRetriever({})  # "boom" has no canned entry -> retrieve() raises

    results = run(questions, retriever, k=10)
    report = build_report(results, k=10)

    row = report["questions"][0]
    assert row["error"] is not None
    assert row["paper_level"] == {"hit": False, "rank": None}
    assert row["passage_level"] == {"scored": True, "hit": False, "rank": None}


def test_build_report_per_question_array_omitted_when_disabled():
    from app.retrieval_eval import QuestionResult

    results = [
        QuestionResult("Q1", "Equation-Retrieval", paper_rank=1, passage_rank=1, passage_scored=True),
    ]

    report = build_report(results, k=10, include_per_question=False)

    assert "questions" not in report
    # aggregates are unaffected by the flag
    assert report["paper_level"]["overall"]["n"] == 1


# --- title_leak diagnostic + scoring_rule stamp (RI-15) ---------------------------------------
# The hit rule (r.paper_id in gold_paper_ids) cannot tell a semantic match from one that succeeded
# only because the gold paper's TITLE appears verbatim in the passage. The predicate below is a
# diagnostic reported ALONGSIDE the metrics -- a leak must leave recall/MRR untouched.


def test_score_question_flags_verbatim_gold_title_in_passage():
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [_hit("P1", "P1:b1", passage_text="We follow A Paper and its baselines.")]

    r = score_question(q, results, k=10)

    assert r.paper_rank == 1  # still a hit -- the leak changes no metric
    assert r.title_leak is True


def test_score_question_clean_hit_is_not_a_leak():
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [_hit("P1", "P1:b1", passage_text="the estimator is consistent under assumption")]

    assert score_question(q, results, k=10).title_leak is False


def test_score_question_leak_match_is_case_and_whitespace_insensitive():
    """Normalization is casefold + collapse-whitespace-runs: a title typeset differently from the
    prose around it still matches."""
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [
        _hit(
            "P1", "P1:b1",
            passage_text="earlier work on DOUBLE-SPACED titles aside, we study\n a   paper.",
            title="A  Paper",
        )
    ]

    assert score_question(q, results, k=10).title_leak is True


def test_score_question_non_gold_results_are_out_of_scope_for_the_predicate():
    """A non-gold paper whose passage embeds its own title is not a leak: the predicate exists to
    qualify paper-level HITS, and P2 is not one here."""
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [
        _hit("P2", "P2:b1", passage_text="B Paper is the canonical reference.", title="B Paper")
    ]

    r = score_question(q, results, k=10)

    assert r.paper_rank is None
    assert r.title_leak is False


def test_score_question_only_the_hits_own_title_counts_as_a_leak():
    """A gold-paper passage quoting some OTHER paper's title verbatim is ordinary scholarly text,
    not evidence this hit rests on title overlap."""
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [_hit("P1", "P1:b1", passage_text="it extends B Paper's estimator.", title="A Paper")]

    assert score_question(q, results, k=10).title_leak is False


def test_score_question_any_gold_result_leaking_flags_the_question():
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [
        _hit("P1", "P1:b1", passage_text="clean semantic match, no title anywhere"),
        _hit("P9", "P9:b1", passage_text="unrelated"),
        _hit("P1", "P1:b7", passage_text="as A Paper showed, ..."),
    ]

    assert score_question(q, results, k=10).title_leak is True


def test_run_records_no_leak_for_an_errored_question():
    questions = [
        Question("Q1", "boom", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    ]
    retriever = FakeRetriever({})  # "boom" has no canned entry -> retrieve() raises

    (result,) = run(questions, retriever, k=10)

    assert result.error is not None
    assert result.title_leak is False


def test_build_report_reports_leaks_alongside_untouched_metrics():
    """The diagnostic's contract: the aggregate counts leaking hits, while Recall/MRR are exactly
    what they would be with the predicate deleted."""
    from app.retrieval_eval import QuestionResult

    results = [
        QuestionResult("Q1", "Result-Comprehension", paper_rank=1, passage_rank=None,
                       passage_scored=False, title_leak=True),
        QuestionResult("Q2", "Result-Comprehension", paper_rank=2, passage_rank=None,
                       passage_scored=False, title_leak=False),
        QuestionResult("Q3", "Result-Comprehension", paper_rank=None, passage_rank=None,
                       passage_scored=False, title_leak=False),  # a miss can't leak
    ]

    report = build_report(results, k=10)

    tl = report["paper_level"]["title_leak"]
    assert tl["n_hits"] == 2
    assert tl["n_leaking"] == 1
    assert tl["fraction_of_hits"] == 0.5
    assert report["paper_level"]["overall"]["recall_at_k"] == 2 / 3  # leak not subtracted
    assert report["paper_level"]["overall"]["mrr"] == (1.0 + 0.5) / 3


def test_build_report_title_leak_fraction_is_none_with_zero_hits():
    from app.retrieval_eval import QuestionResult

    results = [QuestionResult("Q1", "Result-Comprehension", paper_rank=None,
                              passage_rank=None, passage_scored=False)]

    report = build_report(results, k=10)

    assert report["paper_level"]["title_leak"]["n_leaking"] == 0
    assert report["paper_level"]["title_leak"]["fraction_of_hits"] is None


def test_build_report_states_the_floor_limitation_in_the_report_itself():
    """The limitation must live in the emitted artifact, not just a docstring: a verbatim
    predicate leaves paraphrase-level leaks uncounted, so the number is a floor."""
    report = build_report([], k=10)

    note = report["paper_level"]["title_leak"]["note"]
    assert "floor" in note.lower()
    assert "paraphrase" in note.lower()


def test_build_report_stamps_the_scoring_rule_with_k():
    report = build_report([], k=10)
    other_k = build_report([], k=3)

    stamp = report["scoring_rule"]
    assert "10" in stamp
    assert "gold_paper_ids" in stamp  # names the actual hit rule
    assert stamp != other_k["scoring_rule"]  # k is part of the stamp


def test_build_report_per_question_row_carries_title_leak():
    questions = [
        Question("Q1", "leaky query", "Result-Comprehension", frozenset({"P1"}), None),
        Question("Q2", "clean query", "Result-Comprehension", frozenset({"P2"}), None),
    ]
    retriever = FakeRetriever({
        "leaky query": [_hit("P1", "P1:b1", passage_text="per A Paper, the effect ...")],
        "clean query": [_hit("P2", "P2:b1", passage_text="nothing relevant", title="B Paper")],
    })

    results = run(questions, retriever, k=10)
    report = build_report(results, k=10)

    rows = {row["question_id"]: row for row in report["questions"]}
    assert rows["Q1"]["title_leak"] is True
    assert rows["Q2"]["title_leak"] is False


# --- RI-M3: sparse-arm ablation ------------------------------------------------------------------
# `sparse_mode_weight` -- the pure mapping from mode name to the hybrid_dense_weight a vector store
# must be built with.


def test_sparse_mode_weight_dense_only_and_sparse_only_are_the_rrf_extremes():
    assert sparse_mode_weight("dense_only", configured_weight=0.5) == 1.0
    assert sparse_mode_weight("sparse_only", configured_weight=0.5) == 0.0


def test_sparse_mode_weight_fused_passes_the_configured_weight_through_unchanged():
    assert sparse_mode_weight("fused", configured_weight=0.73) == 0.73


def test_sparse_mode_weight_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        sparse_mode_weight("bogus", configured_weight=0.5)


def test_build_report_stamps_the_sparse_mode_and_weight_into_scoring_rule():
    fused = build_report([], k=10)
    dense = build_report([], k=10, mode="dense_only", hybrid_dense_weight=1.0)
    sparse = build_report([], k=10, mode="sparse_only", hybrid_dense_weight=0.0)

    assert "sparse_mode=fused" in fused["scoring_rule"]
    assert "sparse_mode=dense_only" in dense["scoring_rule"]
    assert "hybrid_dense_weight=1.0" in dense["scoring_rule"]
    assert "sparse_mode=sparse_only" in sparse["scoring_rule"]
    assert "hybrid_dense_weight=0.0" in sparse["scoring_rule"]
    # RI-15's whole point (never silently comparable across rules), extended to modes: none of
    # the three stamps may collide.
    assert len({fused["scoring_rule"], dense["scoring_rule"], sparse["scoring_rule"]}) == 3
    # No parallel "sparse_mode" report field -- the ticket's REUSE instruction is that the existing
    # scoring_rule stamp carries this, not a second field alongside it.
    assert "sparse_mode" not in fused
    assert "sparse_mode" not in dense


# --- RI-M3 end-to-end: a real Retriever + the committed FakeVectorStore, not FakeRetriever --------
#
# Everything above scores against FakeRetriever, which never touches hybrid_search/rrf_fuse -- so
# it cannot prove the ablation itself works. This wires an actual `rag.retriever.Retriever` to
# `rag.fakes.FakeVectorStore` (frozen, unmodified) and drives it through this module's own
# `run()`/`build_report()`, proving three things at once: (1) constructing the vector store with
# `sparse_mode_weight`'s extremes genuinely changes which paper ranks first, (2) a paper found only
# by the disabled arm is demoted, not dropped (the module docstring's stated limitation), and (3)
# the SAME run()/build_report() functions RI-M7 also reuses handle all three modes end to end.


class FakeFixedVectorEmbedder:
    """Returns one caller-supplied vector for every query, ignoring the actual text -- places the
    query at an exact, known point relative to the two candidate vectors below, rather than
    depending on FakeEmbedder's hash-derived (uncontrollable) similarity."""

    def __init__(self, vector):
        self._vector = vector

    def embed(self, texts):
        return [self._vector for _ in texts]


class FakeIdentityReranker:
    """A no-op Reranker double. `rag.fakes.FakeReranker` deliberately REVERSES order (M7's own
    anti-cheat measure) -- exactly what would obscure which arm actually won here."""

    def rerank(self, query, candidates):
        return list(candidates)


class _MinimalAblationDocStore:
    """Just enough of the DocumentStore seam for `Retriever.retrieve()` to resolve a chunk hit --
    same minimal-double posture as `rag/test_retriever.py`'s `RecordingDocStore`, trimmed to only
    what this fixture needs (one chunk/one block/one record per paper, no chapters/summaries)."""

    def __init__(self):
        self._chunks: dict = {}
        self._blocks: dict = {}
        self._records: dict = {}

    def get_chunk(self, chunk_id):
        return self._chunks[chunk_id]

    def get_block(self, block_id):
        return self._blocks[block_id]

    def get(self, paper_id):
        return self._records.get(paper_id)


def _seed_ablation_paper(store, docstore, *, paper_id, vector, text):
    from datetime import date

    from contracts.chunker import Chunk
    from contracts.document_store import PaperRecord
    from contracts.harvester import PaperRef
    from contracts.parser import ParsedDoc
    from contracts.provenance import Block

    block_id = f"{paper_id}:b0"
    anchor = Anchor(paper_id=paper_id, block_id=block_id, page=0, bbox=(0.0, 0.0, 1.0, 1.0),
                     snippet=text[:20], section_path="3. Method")
    docstore._blocks[block_id] = Block(
        block_id=block_id, paper_id=paper_id, text=text, type="prose", page=0,
        bbox=(0.0, 0.0, 1.0, 1.0), section_path="3. Method", index=0,
    )
    chunk_id = f"{paper_id}:c0"
    docstore._chunks[chunk_id] = Chunk(
        chunk_id=chunk_id, paper_id=paper_id, text=text, anchor=anchor,
        section_path="3. Method", parent_id=block_id,
    )
    ref = PaperRef(
        paper_id=paper_id, version="v1", title=f"Paper {paper_id}", abstract="We propose...",
        authors=["A. Author"], categories=["cs.LG"], published=date(2026, 6, 1),
        updated=date(2026, 6, 1), pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
    )
    docstore._records[paper_id] = PaperRecord(
        ref=ref,
        parsed=ParsedDoc(paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[],
                         references=[], parser_id="test-parser-1.x"),
        chunks=[docstore._chunks[chunk_id]], summary_text="s", summary_id=f"{paper_id}:summary",
    )
    store.upsert(chunk_id, vector, {
        "paper_id": paper_id, "kind": "chunk", "section_path": "3. Method", "text": text,
        "categories": ["cs.LG"], "published": "2026-06-01", "embedding_version": "v1",
    })


# The query sits exactly at DENSE's stored vector (cosine 1.0) and is orthogonal to SPARSE's
# (cosine 0.0) -- but the query TEXT is copied verbatim into SPARSE's passage and shares no tokens
# with DENSE's, so the two arms are engineered to pick different winners.
_QUERY_VEC = [1.0, 0.0]
_QUERY_TEXT = "doubly robust orthogonal moment estimator"


def _run_ablation(mode: str) -> dict:
    from rag.fakes import FakeVectorStore
    from rag.retriever import Retriever

    weight = sparse_mode_weight(mode, configured_weight=0.5)
    store = FakeVectorStore(hybrid_dense_weight=weight)
    docstore = _MinimalAblationDocStore()
    _seed_ablation_paper(
        store, docstore, paper_id="DENSE", vector=_QUERY_VEC,
        text="an unrelated sentence about something else entirely",
    )
    _seed_ablation_paper(
        store, docstore, paper_id="SPARSE", vector=[0.0, 1.0], text=_QUERY_TEXT,
    )
    retriever = Retriever(
        embedder=FakeFixedVectorEmbedder(_QUERY_VEC), vector_store=store,
        document_store=docstore, reranker=FakeIdentityReranker(),
    )
    question = Question("Q1", _QUERY_TEXT, "Result-Comprehension", frozenset({"DENSE"}), None)
    results = run([question], retriever, k=10)
    return build_report(results, k=10, mode=mode, hybrid_dense_weight=weight)


def test_dense_only_mode_ranks_the_dense_matching_paper_first():
    report = _run_ablation("dense_only")
    row = report["questions"][0]
    assert row["paper_level"] == {"hit": True, "rank": 1}


def test_sparse_only_mode_demotes_the_dense_matching_paper_but_does_not_drop_it():
    """The stated limitation, proven rather than just asserted in prose: zeroing dense's weight
    does not remove DENSE from the fused candidate pool (rrf_fuse's postcondition -- no id is
    dropped for appearing in only one input list), it demotes DENSE to below SPARSE at score 0.0."""
    report = _run_ablation("sparse_only")
    row = report["questions"][0]
    assert row["paper_level"] == {"hit": True, "rank": 2}


def test_fused_mode_still_finds_the_dense_matching_paper():
    report = _run_ablation("fused")
    assert report["questions"][0]["paper_level"]["hit"] is True


@pytest.mark.parametrize("mode", SPARSE_MODES)
def test_every_sparse_mode_stamps_its_own_scoring_rule(mode):
    report = _run_ablation(mode)
    assert f"sparse_mode={mode}" in report["scoring_rule"]


# --- RI-M7: top_score capture + the null-source_paper_id known-absent shape ----------------------


def test_load_questions_null_source_paper_id_is_no_gold_paper(tmp_path):
    """`fixtures/eval/eval_known_absent.json`'s shape: `source_paper_id: null` means "there is no
    gold paper," not "the gold paper is the string 'None'" -- gold_paper_ids must come out empty,
    not `{None}`, so it stays a genuine `frozenset[str]` and can never accidentally equal a real
    hit's `paper_id`."""
    gt_path = tmp_path / "eval_known_absent.json"
    gt_path.write_text(json.dumps({
        "_metadata": {},
        "ground_truth": [
            {
                "question_id": "Q-ABS-001",
                "question_text": "What does the Kestrel-Odom estimator correct for?",
                "source_paper_id": None,
                "question_type": "Known-Absent",
            },
        ],
    }))

    [question] = load_questions(gt_path)

    assert question.gold_paper_ids == frozenset()


def test_score_question_top_score_is_the_rank_1_result_score():
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)
    results = [_hit("P1", "P1:b1"), _hit("P2", "P2:b1")]

    r = score_question(q, results, k=10)

    assert r.top_score == results[0].score


def test_score_question_top_score_is_none_with_zero_results():
    q = Question("Q1", "text", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None)

    assert score_question(q, [], k=10).top_score is None


def test_score_question_top_score_is_recorded_even_for_a_known_absent_miss():
    """The whole point of the field: a question with no gold paper at all (the known-absent
    shape) still gets its rank-1 score recorded -- top_score is not gated on paper_rank."""
    q = Question("Q1", "text", "Known-Absent", frozenset(), gold_block_id=None)
    results = [_hit("P9", "P9:b1")]

    r = score_question(q, results, k=10)

    assert r.paper_rank is None  # no gold paper -- can never be a hit
    assert r.top_score == results[0].score


def test_run_records_no_top_score_for_an_errored_question():
    questions = [Question("Q1", "boom", "Result-Comprehension", frozenset({"P1"}), None)]
    retriever = FakeRetriever({})  # "boom" has no canned entry -> retrieve() raises

    (result,) = run(questions, retriever, k=10)

    assert result.error is not None
    assert result.top_score is None


def test_build_report_per_question_row_carries_top_score():
    questions = [Question("Q1", "q", "Result-Comprehension", frozenset({"P1"}), None)]
    retriever = FakeRetriever({"q": [_hit("P1", "P1:b1")]})

    results = run(questions, retriever, k=10)
    report = build_report(results, k=10)

    [row] = report["questions"]
    assert row["top_score"] == results[0].top_score
