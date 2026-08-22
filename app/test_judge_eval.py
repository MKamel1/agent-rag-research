"""Unit tests for `app/judge_eval.py` (RI-M2 fabrication audit / RI-M6 groundedness -- one shared
harness). Zero-GPU, zero-network by construction: `Judge` is a `Protocol` and this module ships
no real implementation, so there is nothing here that could reach a live model even by accident --
every test drives the harness with `FakeJudge`, a local double with canned verdicts.
"""

import json
from pathlib import Path

import pytest

from app.judge_eval import (
    DISCLAIMER,
    AuditItem,
    Claim,
    build_report,
    load_items,
    run_audit,
)


class FakeJudge:
    """Returns a canned `list[Claim]` per `item.question_id`, ignoring the rubric text (a real
    judge would honor it; the harness's job is only to pass it through unmodified -- pinned by
    `test_run_audit_passes_the_rubric_text_through_unmodified`)."""

    def __init__(
        self,
        claims_by_question_id: dict[str, list[Claim]],
        rubrics_seen: list[str] = None,
    ):
        self._claims_by_question_id = claims_by_question_id
        self._rubrics_seen = rubrics_seen if rubrics_seen is not None else []

    def __call__(self, item: AuditItem, rubric: str) -> list[Claim]:
        self._rubrics_seen.append(rubric)
        if item.question_id not in self._claims_by_question_id:
            raise KeyError(f"FakeJudge has no canned claims for {item.question_id!r}")
        return self._claims_by_question_id[item.question_id]


def _item(question_id: str = "Q-1") -> AuditItem:
    return AuditItem(
        question_id=question_id,
        question_text="What did the paper find?",
        passages=("The passage says X causes a 10% reduction in Y.",),
        answer="X causes a 10% reduction in Y.",
    )


def test_claim_rejects_unknown_verdict():
    with pytest.raises(ValueError, match="unknown verdict"):
        Claim(text="some claim", verdict="maybe", rationale="not one of the three")


def test_run_audit_covers_all_three_verdicts():
    claims = [
        Claim(
            text="X causes a 10% reduction in Y", verdict="supported", rationale="passage says so"
        ),
        Claim(text="Z was also measured", verdict="unsupported", rationale="no passage mentions Z"),
        Claim(
            text="the effect was an increase",
            verdict="contradicted",
            rationale="passage says reduction",
        ),
    ]
    judge = FakeJudge({"Q-1": claims})
    results = run_audit([_item()], judge, rubric="irrelevant to a FakeJudge")

    assert len(results) == 1
    assert results[0].question_id == "Q-1"
    assert results[0].error is None
    assert {c.verdict for c in results[0].claims} == {"supported", "unsupported", "contradicted"}


def test_run_audit_records_a_judge_failure_without_aborting_the_run():
    judge = FakeJudge({"Q-1": [Claim("c", "supported", "r")]})  # no entry for Q-2
    results = run_audit([_item("Q-1"), _item("Q-2")], judge, rubric="r")

    assert results[0].error is None
    assert results[1].error is not None and "Q-2" in results[1].error
    assert results[1].claims == ()


def test_run_audit_passes_the_rubric_text_through_unmodified():
    seen: list[str] = []
    judge = FakeJudge({"Q-1": []}, rubrics_seen=seen)
    run_audit([_item()], judge, rubric="THE EXACT RUBRIC TEXT")

    assert seen == ["THE EXACT RUBRIC TEXT"]


def test_build_report_computes_rates_and_retains_unsupported_and_contradicted(tmp_path):
    rubric_path = tmp_path / "rubric.md"
    rubric_path.write_text("a rubric")

    claims = [
        Claim("a", "supported", "r-a"),
        Claim("b", "unsupported", "r-b"),
        Claim("c", "unsupported", "r-c"),
        Claim("d", "contradicted", "r-d"),
    ]
    judge = FakeJudge({"Q-1": claims})
    results = run_audit([_item("Q-1")], judge, rubric="a rubric")
    report = build_report(results, rubric_path)

    assert report["n_items"] == 1
    assert report["n_errors"] == 0
    assert report["n_claims"] == 4
    assert report["counts"] == {"supported": 1, "unsupported": 2, "contradicted": 1}
    assert report["rates"]["supported"] == pytest.approx(0.25)
    assert report["rates"]["unsupported"] == pytest.approx(0.5)
    assert report["rates"]["contradicted"] == pytest.approx(0.25)

    # Retained for inspection, not just counted -- every unsupported/contradicted claim's own
    # text and rationale must survive into the report, tagged with its question_id.
    unsupported_texts = {c["claim"] for c in report["unsupported_claims"]}
    assert unsupported_texts == {"b", "c"}
    assert all(c["question_id"] == "Q-1" for c in report["unsupported_claims"])
    contradicted_texts = {c["claim"] for c in report["contradicted_claims"]}
    assert contradicted_texts == {"d"}


def test_build_report_omits_errored_items_from_claim_counts(tmp_path):
    rubric_path = tmp_path / "rubric.md"
    rubric_path.write_text("a rubric")

    judge = FakeJudge({"Q-1": [Claim("a", "supported", "r")]})  # Q-2 will error
    results = run_audit([_item("Q-1"), _item("Q-2")], judge, rubric="a rubric")
    report = build_report(results, rubric_path)

    assert report["n_items"] == 2
    assert report["n_errors"] == 1
    assert report["n_claims"] == 1  # only Q-1's claim, Q-2's error contributes nothing


def test_build_report_handles_zero_claims_without_dividing_by_zero(tmp_path):
    rubric_path = tmp_path / "rubric.md"
    rubric_path.write_text("a rubric")
    report = build_report([], rubric_path)

    assert report["n_claims"] == 0
    assert report["rates"] == {"supported": None, "unsupported": None, "contradicted": None}


def test_build_report_stamps_rubric_path_and_a_content_hash_so_versions_are_never_confused(
    tmp_path,
):
    rubric_a = tmp_path / "rubric_a.md"
    rubric_a.write_text("version one")
    rubric_b = tmp_path / "rubric_b.md"
    rubric_b.write_text("version two")

    report_a = build_report([], rubric_a)
    report_b = build_report([], rubric_b)

    assert report_a["rubric_path"] == str(rubric_a)
    assert report_a["rubric_sha256_12"] != report_b["rubric_sha256_12"]


def test_build_report_carries_the_judge_fallibility_and_no_baseline_disclaimer(tmp_path):
    rubric_path = tmp_path / "rubric.md"
    rubric_path.write_text("a rubric")
    report = build_report([], rubric_path)

    assert report["disclaimer"] == DISCLAIMER
    assert "fallible" in report["disclaimer"]
    assert "not a baseline" in report["disclaimer"]


def test_load_items_reuses_answer_text_and_passage_excerpt_with_no_new_labelling(tmp_path):
    ground_truth_path = tmp_path / "eval_ground_truth_x.json"
    ground_truth_path.write_text(
        json.dumps(
            {
                "ground_truth": [
                    {
                        "question_id": "Q-1",
                        "answer_text": "the reference answer",
                        "passage_excerpt": "the retrieved passage",
                        "source_paper_id": "1234.5678",
                        "question_type": "Result-Comprehension",
                    }
                ]
            }
        )
    )

    items = load_items(ground_truth_path)

    assert len(items) == 1
    assert items[0].question_id == "Q-1"
    assert items[0].answer == "the reference answer"
    assert items[0].passages == ("the retrieved passage",)
    assert items[0].question_text == ""  # no blind sibling, no question_text in-record either


def test_load_items_joins_question_text_from_the_sibling_blind_file(tmp_path):
    ground_truth_path = tmp_path / "eval_ground_truth_x.json"
    ground_truth_path.write_text(
        json.dumps(
            {
                "ground_truth": [
                    {
                        "question_id": "Q-1",
                        "answer_text": "the reference answer",
                        "passage_excerpt": "the retrieved passage",
                    }
                ]
            }
        )
    )
    blind_path = tmp_path / "eval_questions_blind_x.json"
    blind_path.write_text(
        json.dumps({"questions": [{"question_id": "Q-1", "question_text": "the real question?"}]})
    )

    items = load_items(ground_truth_path)

    assert items[0].question_text == "the real question?"


def test_load_items_works_against_the_real_waymo_fixture():
    """Proves the harness plumbing on real, grounded fixture data (RI-M5's own fixture) -- not a
    corpus finding, just confirmation the shapes line up end to end."""
    repo_root = Path(__file__).resolve().parent.parent
    fixture_path = repo_root / "fixtures" / "eval" / "eval_ground_truth_waymo.json"
    items = load_items(fixture_path)

    assert len(items) == 15
    assert all(item.answer and item.passages and item.question_text for item in items)
