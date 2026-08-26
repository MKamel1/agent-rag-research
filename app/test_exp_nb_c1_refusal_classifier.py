# NB-C1 stage-1 frozen rule's own suite. The rule was committed BEFORE any answer was classified
# (commit 9de6da1) and may not be tuned afterwards -- so these tests pin its behavior contract:
# if anyone ever "iterates the rubric" post hoc, CI breaks here rather than drifting silently.
# Zero GPU, zero network: everything runs on synthetic strings and tmp_path fixtures.
"""`app.exp_nb_c1_refusal_classifier` test suite.

Covers the frozen v1.0 rule's contract:

- each of the 9 refusal-language classes fires on a clean lead;
- a substantive answer is not refusal-shaped;
- the numeric-commitment guard exempts calendar years but blocks any other digit (the frozen
  tradeoff behind Q-WAYB-022/Q-WAYB-039's known-absent misses);
- the lead region is min(2 sentences, 600 chars): refusal language outside it never fires;
- captured generation errors force non-refusal and are surfaced, never silently dropped;
- `_summarize` arithmetic equals the criterion's counts (absent covered / false refusals);
- joined mode assigns arms from `absence_note`, split mode rejects duplicate ids, both modes
  run end-to-end through main() writing the committed report schema;
- arg misuse (`--combined-capture` without `--gt`) exits via parser.error.
"""

import json
import sys

import pytest

from app.exp_nb_c1_refusal_classifier import (
    RULE_VERSION,
    _classify_item,
    _join_arms_from_gt,
    _lead_region,
    _split_mode_records,
    _summarize,
    classify_answer,
    main,
)

# --- one representative phrase per frozen class -------------------------------

_CLASS_PHRASES = {
    "declarative-does-not": "The passages do not contain any deductible figure.",
    "bare-no-information": "There is no information about retail pricing.",
    "not-any-information": "The sources give not any information on this.",
    "capability-negation": "I cannot determine that from the passages.",
    "not-participle": "That number is not specified in the provided material.",
    "insufficient-information": "The excerpts offer insufficient information to answer.",
    "lacks-information": "The corpus lacks information on supplier contracts.",
    "not-possible-to-answer": "It is not possible to answer from these sources.",
    "mismatch-no-such": "There is no such statistic anywhere in the corpus.",
}


@pytest.mark.parametrize("class_name", sorted(_CLASS_PHRASES))
def test_each_frozen_class_fires(class_name):
    verdict = classify_answer(_CLASS_PHRASES[class_name])
    assert verdict["refusal_shaped"] is True
    assert verdict["matched_patterns"] == [class_name]
    assert verdict["has_numeric_commitment"] is False


def test_substantive_answer_is_not_refusal_shaped():
    answer = (
        "Waymo's rider-only service reported 0.18 disengagements per 1,000 miles "
        "in its most recent California DMV filing."
    )
    verdict = classify_answer(answer)
    assert verdict["refusal_shaped"] is False
    assert verdict["matched_patterns"] == []
    assert verdict["has_numeric_commitment"] is True


def test_matching_is_case_insensitive():
    assert classify_answer("THE PASSAGES DO NOT CONTAIN THAT FIGURE.")["refusal_shaped"] is True
    assert classify_answer("the passages Cannot provide it")["refusal_shaped"] is True


# --- numeric-commitment guard (frozen tradeoff) --------------------------------


def test_calendar_year_alone_does_not_block_a_refusal():
    verdict = classify_answer("The passages do not contain that figure as of 2023.")
    assert verdict["matched_patterns"] == ["declarative-does-not"]
    assert verdict["has_numeric_commitment"] is False
    assert verdict["refusal_shaped"] is True


def test_non_year_digit_inside_a_refusal_blocks_classification():
    # The exact FAB failure shape: a number inside refusal language must NOT count as refusal.
    verdict = classify_answer("The passages do not state a per-1,000-mile collision rate.")
    assert verdict["has_numeric_commitment"] is True
    assert verdict["refusal_shaped"] is False


def test_year_guard_only_strips_calendar_years():
    # Both tokens match the frozen calendar-year regex, so neither survives stripping.
    verdict = classify_answer(
        "The corpus does not mention it; figures exist only for 1850 or 2099.")
    assert verdict["has_numeric_commitment"] is False
    assert verdict["refusal_shaped"] is True


def test_non_calendar_four_digit_number_blocks_a_refusal():
    # 1500 fails \b(18|19|20)\d{2}\b, so the digit survives and blocks classification.
    verdict = classify_answer("The passages do not state the value in table row 1500.")
    assert verdict["has_numeric_commitment"] is True
    assert verdict["refusal_shaped"] is False


# --- lead-region window --------------------------------------------------------


def test_refusal_in_third_sentence_never_fires():
    answer = (
        "This question concerns insurance pricing. The topic spans several papers here. "
        "But the passages do not contain the requested figure."
    )
    lead = _lead_region(answer)
    assert lead.endswith("The topic spans several papers here.")
    assert "do not contain" not in lead
    assert classify_answer(answer)["refusal_shaped"] is False


def test_lead_region_truncates_at_600_chars():
    padded_first_sentence = "a" * 598 + "."
    refusal_second_sentence = " The passages do not contain the figure."
    long_answer = padded_first_sentence + refusal_second_sentence
    lead = _lead_region(long_answer)
    assert len(lead) == 600
    assert "do not" not in lead
    assert classify_answer(long_answer)["refusal_shaped"] is False
    # Same refusal inside the window does fire.
    short_answer = "Short. The passages do not contain the figure."
    assert classify_answer(short_answer)["refusal_shaped"] is True


def test_two_sentence_window_admits_second_sentence_refusal():
    answer = "Pricing is discussed across actuarial papers. However, no information is given."
    assert classify_answer(answer)["refusal_shaped"] is True


# --- plumbing: errors, summarize, joins ----------------------------------------


def test_generation_error_forces_non_refusal_and_is_surfaced():
    record = _classify_item(
        "Q-X",
        {"answer_text": _CLASS_PHRASES["bare-no-information"],
         "error": "generation backend timeout"},
        arm="answerable",
    )
    assert record["generation_error"] is True
    assert record["refusal_shaped"] is False


def test_summarize_matches_criterion_counts():
    items = [
        {"question_id": "A1", "arm": "absent", "refusal_shaped": True},
        {"question_id": "A2", "arm": "absent", "refusal_shaped": False, "generation_error": True},
        {"question_id": "B1", "arm": "answerable", "refusal_shaped": True},
        {"question_id": "B2", "arm": "answerable", "refusal_shaped": False},
        {"question_id": "B3", "arm": "answerable", "refusal_shaped": False,
         "generation_error": True},
    ]
    summary = _summarize(items)
    assert summary == {
        "absent": {"n": 2, "refusal_shaped": 1, "errors": 1},
        "answerable": {"n": 3, "false_refusals": 1, "errors": 1},
    }


def test_joined_mode_assigns_arms_from_absence_note(tmp_path):
    capture = [
        {"question_id": "Q-ABS", "answer_text": "There is no such figure."},
        {"question_id": "Q-ANS", "answer_text": "The rate was 0.18 per 1,000 miles."},
        {"question_id": "Q-MISSING", "answer_text": "orphan"},
    ]
    gt_fixture = [
        {"question_id": "Q-ABS", "absence_note": "no corpus paper reports this"},
        {"question_id": "Q-ANS", "absence_note": None},
    ]
    gt_path = tmp_path / "gt.json"
    gt_path.write_text(json.dumps({"ground_truth": gt_fixture}))
    with pytest.raises(ValueError, match="Q-MISSING"):
        _join_arms_from_gt(capture, gt_path)

    records = _join_arms_from_gt(capture[:-1], gt_path)
    by_id = {r["question_id"]: r for r in records}
    assert by_id["Q-ABS"]["arm"] == "absent" and by_id["Q-ABS"]["refusal_shaped"] is True
    assert by_id["Q-ANS"]["arm"] == "answerable" and by_id["Q-ANS"]["refusal_shaped"] is False


def test_split_mode_rejects_duplicate_question_ids(tmp_path):
    dup = tmp_path / "dup.json"
    dup.write_text(json.dumps({"ground_truth": [{"question_id": "Q-DUP", "answer_text": "x"}]}))
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"ground_truth": [{"question_id": "Q-DUP", "answer_text": "y"}]}))
    with pytest.raises(ValueError, match="duplicate question_id"):
        _split_mode_records([dup], [other])


# --- end-to-end through main(): the committed report schema ---------------------


def _write_capture(path, rows):
    path.write_text(json.dumps({"ground_truth": rows}))
    return str(path)


def test_main_combined_mode_writes_committed_schema(tmp_path, monkeypatch, capsys):
    capture = _write_capture(
        tmp_path / "cap.json",
        [
            {"question_id": "Q-B", "answer_text": "There is no such figure."},
            {"question_id": "Q-A", "answer_text": "It was 41% of miles."},
        ],
    )
    gt_path = _write_capture(
        tmp_path / "gt.json",
        [
            {"question_id": "Q-B", "absence_note": "nothing states this"},
            {"question_id": "Q-A", "absence_note": None},
        ],
    )
    out = tmp_path / "out" / "report.json"
    monkeypatch.setattr(
        sys, "argv",
        ["exp_nb_c1_refusal_classifier", "--combined-capture", capture,
         "--gt", gt_path, "--out", str(out)],
    )
    main()
    assert "classified 2 items" in capsys.readouterr().out

    report = json.loads(out.read_text())
    assert set(report) == {"rule_version", "rule", "inputs", "items", "summary"}
    assert report["rule_version"] == RULE_VERSION
    assert [(i["arm"], i["question_id"]) for i in report["items"]] == [
        ("absent", "Q-B"), ("answerable", "Q-A"),
    ]
    assert report["summary"]["absent"]["refusal_shaped"] == 1
    assert report["summary"]["answerable"]["false_refusals"] == 0


def test_main_split_mode_writes_committed_schema(tmp_path, monkeypatch):
    absent = _write_capture(
        tmp_path / "absent.json",
        [{"question_id": "Q-Z", "answer_text": "The corpus lacks information on this."}],
    )
    answerable = _write_capture(
        tmp_path / "answerable.json",
        [{"question_id": "Q-Y", "answer_text": "The fleet drove 56.7 million miles."}],
    )
    out = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv",
        ["exp_nb_c1_refusal_classifier", "--absent-capture", absent,
         "--answerable-capture", answerable, "--out", str(out)],
    )
    main()
    report = json.loads(out.read_text())
    assert report["inputs"]["absent_captures"] == [absent]
    assert report["summary"] == {
        "absent": {"n": 1, "refusal_shaped": 1, "errors": 0},
        "answerable": {"n": 1, "false_refusals": 0, "errors": 0},
    }


def test_combined_mode_without_gt_exits_via_parser_error(tmp_path, monkeypatch):
    capture = _write_capture(tmp_path / "cap.json", [{"question_id": "Q-A", "answer_text": "x"}])
    out = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv",
        ["exp_nb_c1_refusal_classifier", "--combined-capture", capture, "--out", str(out)],
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 2
