"""Unit tests for `app/score_distribution_census.py` (RI-M7). Zero-GPU, zero-network: the
comparison logic (`distribution_stats`/`collect_top_scores`/`build_census`) is exercised against
hand-built reports and synthetic score lists; the one end-to-end test drives the real
`load_questions`/`run`/`build_report` (reused, unmodified, from `app.retrieval_eval`) with a
`FakeRetriever`, the same "small fixture" posture `app/test_retrieval_eval.py` uses throughout.
"""

from pathlib import Path

import pytest

from app.retrieval_eval import Question, build_report, load_questions, run
from app.score_distribution_census import (
    _KNOWN_ABSENT_LIMITATION_NOTE,
    build_census,
    collect_top_scores,
    distribution_stats,
)
from app.test_retrieval_eval import FakeRetriever
from contracts.provenance import Anchor
from contracts.retriever import Citation, GroundedResult

# --- distribution_stats ---------------------------------------------------------------------


def test_distribution_stats_empty_list():
    stats = distribution_stats([])
    assert stats == {
        "n": 0, "mean": None, "median": None, "stdev": None,
        "min": None, "max": None, "p25": None, "p75": None,
    }


def test_distribution_stats_single_value_has_no_stdev_but_every_other_field_is_the_value():
    stats = distribution_stats([0.42])
    assert stats["n"] == 1
    assert stats["stdev"] is None
    for field in ("mean", "median", "min", "max", "p25", "p75"):
        assert stats[field] == pytest.approx(0.42), field


def test_distribution_stats_multiple_values_matches_hand_computed_reference():
    stats = distribution_stats([1.0, 2.0, 3.0, 4.0])
    assert stats["n"] == 4
    assert stats["mean"] == pytest.approx(2.5)
    assert stats["median"] == pytest.approx(2.5)
    assert stats["min"] == 1.0
    assert stats["max"] == 4.0
    assert stats["stdev"] == pytest.approx(1.290994, abs=1e-5)  # sample stdev of [1,2,3,4]
    # statistics.quantiles([1,2,3,4], n=4) -> [1.25, 2.5, 3.75] (its default "exclusive" method).
    assert stats["p25"] == pytest.approx(1.25)
    assert stats["p75"] == pytest.approx(3.75)


# --- collect_top_scores ----------------------------------------------------------------------


def test_collect_top_scores_filters_out_none_values():
    report = {"questions": [
        {"top_score": 0.9}, {"top_score": None}, {"top_score": 0.1},
    ]}
    assert collect_top_scores(report) == [0.9, 0.1]


def test_collect_top_scores_raises_when_questions_array_is_missing():
    """A silently-empty [] here would let a census run over an accidentally-empty arm without
    anyone noticing -- RI-M7's whole point is that the verdict must be trustworthy."""
    with pytest.raises(ValueError, match="questions"):
        collect_top_scores({"n_questions": 0})


# --- build_census -----------------------------------------------------------------------------


def _report_with_scores(scores: list[float | None]) -> dict:
    """A minimal build_report()-shaped dict: just enough for build_census to read (n_questions,
    questions[].top_score) -- built directly rather than through run()/score_question so the
    distribution comparison logic is tested in isolation from retrieval.
    """
    return {
        "n_questions": len(scores),
        "questions": [{"top_score": s} for s in scores],
    }


def test_build_census_reports_separation_when_iqrs_do_not_overlap():
    answerable = _report_with_scores([0.80, 0.82, 0.85, 0.90, 0.95])
    known_absent = _report_with_scores([0.05, 0.10, 0.12, 0.15, 0.20])

    census = build_census(answerable, known_absent)

    assert census["distributions_separate"] is True
    assert census["verdict"].startswith("the distributions separate")
    assert census["answerable"]["n"] == 5
    assert census["known_absent"]["n"] == 5
    assert census["answerable"]["n_excluded"] == 0
    assert census["known_absent"]["n_excluded"] == 0


def test_build_census_reports_no_separation_when_iqrs_overlap():
    answerable = _report_with_scores([0.40, 0.50, 0.60, 0.70, 0.80])
    known_absent = _report_with_scores([0.30, 0.45, 0.55, 0.65, 0.75])

    census = build_census(answerable, known_absent)

    assert census["distributions_separate"] is False
    assert census["verdict"].startswith("the distributions do not separate")


# --- known-absent construction limitation (reviewer objection on RI-M7) ----------------------
#
# The known-absent arm's fabricated-entity design guarantees the sparse/lexical arm a zero
# exact-term match by construction, which a real-but-uncovered topic would not get -- so
# separation measured against this arm is plausibly an upper bound, not a measurement, of what a
# real uncovered topic would show. That limitation must travel with the verdict inside the
# emitted report itself (not just a docstring or the fixture's own _metadata), worded so a
# "separate" verdict cannot be quoted as a bare conclusion.


def test_build_census_emits_the_known_absent_limitation_note_verbatim():
    """The full caveat must be readable straight out of the JSON report, every time -- not only
    when the verdict happens to be "separate"."""
    answerable = _report_with_scores([0.80, 0.82, 0.85, 0.90, 0.95])
    known_absent = _report_with_scores([0.05, 0.10, 0.12, 0.15, 0.20])

    census = build_census(answerable, known_absent)

    assert census["known_absent_limitation"] == _KNOWN_ABSENT_LIMITATION_NOTE
    assert "fabricated" in _KNOWN_ABSENT_LIMITATION_NOTE.lower()
    assert "upper bound" in _KNOWN_ABSENT_LIMITATION_NOTE.lower()


def test_build_census_separate_verdict_states_the_upper_bound_direction_inline():
    """The direction most at risk of misquotation: a bare "the distributions separate" could be
    lifted out of context to justify revisiting a relevance floor. The verdict string itself must
    carry the upper-bound caveat, not defer it to a field a reader might not open."""
    answerable = _report_with_scores([0.80, 0.82, 0.85, 0.90, 0.95])
    known_absent = _report_with_scores([0.05, 0.10, 0.12, 0.15, 0.20])

    census = build_census(answerable, known_absent)

    assert "upper bound" in census["verdict"].lower()
    assert "known_absent_limitation" in census["verdict"]


def test_build_census_no_separation_verdict_notes_the_limitation_does_not_weaken_it():
    answerable = _report_with_scores([0.40, 0.50, 0.60, 0.70, 0.80])
    known_absent = _report_with_scores([0.30, 0.45, 0.55, 0.65, 0.75])

    census = build_census(answerable, known_absent)

    assert "known_absent_limitation" in census["verdict"]
    assert "does not weaken" in census["verdict"]


def test_build_census_counts_excluded_none_scores_per_arm():
    answerable = _report_with_scores([0.9, None, 0.8])
    known_absent = _report_with_scores([0.1])

    census = build_census(answerable, known_absent)

    assert census["answerable"]["n"] == 2
    assert census["answerable"]["n_excluded"] == 1
    assert census["known_absent"]["n"] == 1
    assert census["known_absent"]["n_excluded"] == 0


def test_build_census_is_undetermined_when_an_arm_has_zero_scored_questions():
    answerable = _report_with_scores([None, None])
    known_absent = _report_with_scores([0.1, 0.2])

    census = build_census(answerable, known_absent)

    assert census["distributions_separate"] is None
    assert "undetermined" in census["verdict"]


def test_build_census_separation_is_direction_agnostic():
    """The rule doesn't presume which arm scores higher -- swapping the two arms above must still
    report separation, just with the roles reversed."""
    high = _report_with_scores([0.80, 0.82, 0.85, 0.90, 0.95])
    low = _report_with_scores([0.05, 0.10, 0.12, 0.15, 0.20])

    census = build_census(low, high)  # known-absent arm scores HIGHER here

    assert census["distributions_separate"] is True


# --- end-to-end: real load_questions/run/build_report (reused, unmodified) + FakeRetriever ------


def _scored_hit(paper_id: str, block_id: str, score: float) -> GroundedResult:
    """Same shape as `app/test_retrieval_eval.py`'s `_hit`, but with a caller-chosen `score` --
    that helper hardcodes `score=1.0`, which can't demonstrate two arms separating."""
    return GroundedResult(
        passage_text="some chunk text",
        anchor=Anchor(
            paper_id=paper_id, block_id=block_id, page=0, bbox=(0.0, 0.0, 1.0, 1.0),
            snippet="snippet", section_path="3 Method",
        ),
        paper_id=paper_id,
        score=score,
        citation=Citation(
            paper_id=paper_id, title="A Paper", authors=["A. Author"],
            arxiv_url=f"https://arxiv.org/abs/{paper_id}", section_path="3 Method",
        ),
    )


def test_census_end_to_end_over_a_small_two_arm_fixture():
    """Proves the whole reused pipeline together on a small, hand-built fixture: the SAME
    run()/build_report() this ticket's sibling (RI-M3) and the rest of the eval programme use,
    feeding a clearly-separated pair of arms through to a plain verdict.
    """
    answerable_questions = [
        Question("QA1", "known query one", "Result-Comprehension", frozenset({"P1"}), None),
        Question("QA2", "known query two", "Result-Comprehension", frozenset({"P2"}), None),
    ]
    known_absent_questions = [
        Question("QB1", "absent query one", "Known-Absent", frozenset(), None),
        Question("QB2", "absent query two", "Known-Absent", frozenset(), None),
    ]
    retriever = FakeRetriever({
        "known query one": [_scored_hit("P1", "P1:b1", score=0.90)],
        "known query two": [_scored_hit("P2", "P2:b1", score=0.85)],
        "absent query one": [_scored_hit("P9", "P9:b1", score=0.10)],
        "absent query two": [_scored_hit("P8", "P8:b1", score=0.05)],
    })

    answerable_results = run(answerable_questions, retriever, k=10)
    known_absent_results = run(known_absent_questions, retriever, k=10)
    answerable_report = build_report(answerable_results, k=10)
    known_absent_report = build_report(known_absent_results, k=10)

    census = build_census(answerable_report, known_absent_report)

    assert census["answerable"]["n"] == 2
    assert census["known_absent"]["n"] == 2
    assert census["distributions_separate"] is True
    assert census["verdict"].startswith("the distributions separate")


def test_the_committed_known_absent_fixture_loads_with_no_gold_paper_and_the_right_type():
    """Schema smoke test over the real, committed fixture (RI-M7) -- catches a shape mistake in
    fixtures/eval/eval_known_absent.json without needing to run retrieval over all 24 items."""
    questions = load_questions(Path("fixtures/eval/eval_known_absent.json"))

    assert len(questions) == 24
    assert {q.question_id for q in questions} == {f"Q-ABS-{i:03d}" for i in range(1, 25)}
    for q in questions:
        assert q.gold_paper_ids == frozenset()  # no gold paper, by construction
        assert q.question_type == "Known-Absent"
        assert q.question_text.strip()
