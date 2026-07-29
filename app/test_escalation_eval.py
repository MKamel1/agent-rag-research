"""Unit tests for `app/escalation_eval.py`. Zero-GPU, zero-network -- a local `FakeRetriever`
double only, same posture as `app/test_retrieval_eval.py`.
"""

from contracts.mcp_server import PaperSearchResult, PaperSummaryView
from contracts.retriever import Citation
from contracts.vector_index import SearchFilters

from app.escalation_eval import (
    EscalationResult,
    build_report,
    escalating_retrieve_papers,
    run,
    top_hit_not_book,
)
from app.retrieval_eval import Question


def _hit(paper_id: str, chapter: str | None, doc_type: str = "book") -> PaperSearchResult:
    return PaperSearchResult(
        view=PaperSummaryView(
            paper_id=paper_id, title="A Doc", authors=["A. Author"], summary_text="summary",
            section_paths=[],
            citation=Citation(
                paper_id=paper_id, title="A Doc", authors=["A. Author"],
                arxiv_url=f"https://example/{paper_id}", section_path="", doc_type=doc_type,
            ),
        ),
        score=1.0,
        chapter=chapter,
    )


class FakeRetriever:
    """`.retrieve_papers(query, filters, k)` with two canned response sets, keyed by whether
    `filters` requests `doc_type="book"` -- lets a test control exactly what the unfiltered call
    vs. the escalated retry each return for the same query text.
    """

    def __init__(self, unfiltered: dict[str, list], book_filtered: dict[str, list] | None = None):
        self._unfiltered = unfiltered
        self._book_filtered = book_filtered or {}
        self.calls: list[tuple[str, str | None]] = []  # (query, doc_type filter or None)

    def retrieve_papers(self, query: str, filters, k: int):
        doc_type = filters.doc_type if filters is not None else None
        self.calls.append((query, doc_type))
        if doc_type == "book":
            if query not in self._book_filtered:
                raise RuntimeError(f"FakeRetriever: no canned book-filtered response for {query!r}")
            return self._book_filtered[query][:k], None
        if query not in self._unfiltered:
            raise RuntimeError(f"FakeRetriever: no canned unfiltered response for {query!r}")
        return self._unfiltered[query][:k], None


# --- top_hit_not_book (the default insufficiency signal) ----------------------------------------


def test_top_hit_not_book_true_when_no_results():
    assert top_hit_not_book([]) is True


def test_top_hit_not_book_true_when_top_hit_is_a_paper():
    assert top_hit_not_book([_hit("P1", "Ch1", doc_type="paper")]) is True


def test_top_hit_not_book_false_when_top_hit_is_a_book():
    assert top_hit_not_book([_hit("B1", "Ch1", doc_type="book")]) is False


# --- escalating_retrieve_papers -------------------------------------------------------------


def test_no_escalation_when_first_call_top_hit_is_already_a_book():
    retriever = FakeRetriever({"q": [_hit("B1", "Ch1", doc_type="book")]})

    results, escalated = escalating_retrieve_papers(retriever, "q", k=10)

    assert escalated is False
    assert results == [_hit("B1", "Ch1", doc_type="book")]
    assert retriever.calls == [("q", None)]  # only the unfiltered call fired


def test_escalates_and_retries_with_doc_type_book_when_top_hit_is_a_paper():
    retriever = FakeRetriever(
        unfiltered={"q": [_hit("P1", None, doc_type="paper")]},
        book_filtered={"q": [_hit("B1", "Ch1", doc_type="book")]},
    )

    results, escalated = escalating_retrieve_papers(retriever, "q", k=10)

    assert escalated is True
    assert results == [_hit("B1", "Ch1", doc_type="book")]
    assert retriever.calls == [("q", None), ("q", "book")]


def test_escalates_when_first_call_returns_nothing():
    retriever = FakeRetriever(
        unfiltered={"q": []},
        book_filtered={"q": [_hit("B1", "Ch1", doc_type="book")]},
    )

    results, escalated = escalating_retrieve_papers(retriever, "q", k=10)

    assert escalated is True
    assert results == [_hit("B1", "Ch1", doc_type="book")]


def test_custom_insufficient_predicate_is_honored():
    # A predicate that never escalates, regardless of the default heuristic's own verdict.
    retriever = FakeRetriever({"q": [_hit("P1", None, doc_type="paper")]})

    results, escalated = escalating_retrieve_papers(
        retriever, "q", k=10, insufficient=lambda results: False
    )

    assert escalated is False
    assert retriever.calls == [("q", None)]


# --- run --------------------------------------------------------------------------------------


def _book_question(qid: str, query: str, paper_id: str, chapter: str) -> Question:
    return Question(
        question_id=qid, question_text=query, question_type="Book-Chapter-Recall",
        gold_paper_ids=frozenset({paper_id}), gold_block_id=None, doc_type="book",
        gold_chapter_title=chapter,
    )


def test_run_scores_chapter_hit_after_escalation():
    questions = [_book_question("QB1", "q1", "B1", "Chapter Three")]
    retriever = FakeRetriever(
        unfiltered={"q1": [_hit("P9", None, doc_type="paper")]},  # wrong doc_type -> escalate
        book_filtered={"q1": [_hit("B1", "Chapter Three", doc_type="book")]},
    )

    results = run(questions, retriever, k=10)

    assert len(results) == 1
    assert results[0].chapter_rank == 1
    assert results[0].escalated is True


def test_run_skips_questions_with_no_gold_chapter_title():
    """A plain paper question (no gold_chapter_title) isn't chapter-routable -- must be skipped
    entirely, not scored as an automatic miss, mirroring retrieval_eval's own chapter-level gate.
    """
    questions = [
        Question(
            "Q1", "paper query", "Result-Comprehension", frozenset({"P1"}), gold_block_id=None,
        ),
        _book_question("QB1", "q1", "B1", "Chapter Three"),
    ]
    retriever = FakeRetriever(
        unfiltered={"q1": [_hit("B1", "Chapter Three", doc_type="book")]},
    )

    results = run(questions, retriever, k=10)

    assert len(results) == 1
    assert results[0].question_id == "QB1"
    assert ("paper query", None) not in retriever.calls


def test_run_records_error_without_aborting_whole_run():
    questions = [
        _book_question("QB1", "boom", "B1", "Chapter Three"),  # no canned response -> raises
        _book_question("QB2", "q2", "B2", "Chapter One"),
    ]
    retriever = FakeRetriever(
        unfiltered={"q2": [_hit("B2", "Chapter One", doc_type="book")]},
    )

    results = run(questions, retriever, k=10)

    assert results[0].error is not None
    assert results[0].chapter_rank is None
    assert results[1].error is None
    assert results[1].chapter_rank == 1


def test_run_right_book_wrong_chapter_is_a_miss():
    questions = [_book_question("QB1", "q1", "B1", "Chapter Three")]
    retriever = FakeRetriever(
        unfiltered={"q1": [_hit("B1", "Chapter One", doc_type="book")]},  # same book, wrong chapter
    )

    results = run(questions, retriever, k=10)

    assert results[0].chapter_rank is None
    assert results[0].escalated is False  # top hit was already doc_type=book -> no retry


# --- build_report -------------------------------------------------------------------------------


def test_build_report_aggregates_recall_mrr_and_escalation_rate():
    results = [
        EscalationResult("QB1", chapter_rank=1, escalated=True),
        EscalationResult("QB2", chapter_rank=None, escalated=True),
        EscalationResult("QB3", chapter_rank=2, escalated=False),
        EscalationResult("QB4", chapter_rank=None, escalated=False),
    ]

    report = build_report(results, k=10)

    assert report["n_questions"] == 4
    assert report["n_escalated"] == 2
    assert report["escalation_rate"] == 0.5
    assert report["chapter_level"]["n"] == 4
    assert report["chapter_level"]["recall_at_k"] == 0.5  # QB1, QB3 hit; QB2, QB4 miss
    assert report["chapter_level"]["mrr"] == (1.0 + 0.5) / 4


def test_build_report_empty_results_is_none_not_zero_division():
    report = build_report([], k=10)

    assert report["chapter_level"] == {"recall_at_k": None, "mrr": None, "n": 0}
    assert report["escalation_rate"] is None


def test_build_report_counts_errors_separately_from_misses():
    results = [
        EscalationResult("QB1", chapter_rank=None, escalated=False, error="boom"),
        EscalationResult("QB2", chapter_rank=1, escalated=False),
    ]

    report = build_report(results, k=10)

    assert report["n_errors"] == 1
    # errored question still contributes an n=2, chapter_rank=None miss to the denominator --
    # same "counted, not silently dropped" posture as retrieval_eval's own error handling.
    assert report["chapter_level"]["n"] == 2
    assert report["chapter_level"]["recall_at_k"] == 0.5
