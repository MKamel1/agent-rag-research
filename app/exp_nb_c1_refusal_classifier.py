"""NB-C1 stage-1: fixed refusal-shape classification rule over captured generation runs.

Ticket NB-C1 (programme plan §4 Wave 3 successor; mandate
docs/eval-reports/2026-08-25-nb-a1-abstention-signal-design.md §C1). This module is the ONE fixed
classification rule required by C1's falsification criterion, committed BEFORE any answer was
classified. After results exist, no rubric iteration, threshold tuning, or rewording is permitted
to rescue a failure -- which is why this file contains no tunable parameters at all: every
constant below is part of the frozen rule (RULE_VERSION).

The rule is BLIND BY CONSTRUCTION: `classify_answer()` sees only the generated answer text. Gold
status (known-absent vs answerable) is joined afterwards, purely to compute the criterion's
coverage/false-refusal counts -- it can never influence a classification.

FROZEN RULE (v1.0):

    lead_region   = first min(2 sentences, 600 characters) of the answer
                    (sentences split on /(?<=[.!?])\\s+/)
    REFUSAL       = any of REFUSAL_PATTERNS matches anywhere in lead_region (case-insensitive)
    NUM_COMMIT    = any digit survives in lead_region after stripping calendar-year tokens
                    \\b(?:18|19|20)\\d{2}\\b
    refusal-shaped := REFUSAL AND NOT NUM_COMMIT

Rationale, fixed before seeing any classified answer: the A/B evidence (its §1–§3 hand
classifications) shows refusals lead with explicit insufficiency language ("The information
provided in the passages does not specify...", "...is not explicitly mentioned...", "it is not
possible to answer..."), while wrong-side answers assert a concrete figure ("905 nm",
"0.18 disengagements/1,000 mi"). A refusal phrase that ALSO carries a number is an
invented-number-inside-a-refusal (the exact FAB failure shape) and must NOT count as refusal,
because downstream anything reading the detector would take that number as the answer. Known
scope limits, accepted as part of the freeze: numbers written as words ("sixty-five percent") are
not detected as commitments; entity-only commitments (a named underwriter with no figure) are not
detected either -- the commitment check is deliberately digits-and-years only.

Usage (both modes write the same output schema):

    # ver84: captures already split per arm
    python -m app.exp_nb_c1_refusal_classifier \\
        --absent-capture \\
          fixtures/eval/runs/2026-08-24-waymo-generation-run-affordance.absent.json \\
        --answerable-capture \\
          fixtures/eval/runs/2026-08-24-waymo-generation-run-affordance.answerable.json \\
        --out docs/eval-reports/data/2026-08-25-nb-c1/ver84_classifications.json

    # gt_wmr: one combined capture; arms joined from the fixture's absence_note field
    python -m app.exp_nb_c1_refusal_classifier \\
        --combined-capture \\
          docs/eval-reports/data/2026-08-25-nb-c1/gt_wmr-generation-affordance.json \\
        --gt fixtures/eval/gt_wmr.json \\
        --out docs/eval-reports/data/2026-08-25-nb-c1/gt_wmr_classifications.json

Read-only over inputs; writes only the --out path. Zero GPU, zero network.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

RULE_VERSION = "1.0"

# --- frozen rule constants -------------------------------------------------

_LEAD_MAX_SENTENCES = 2
_LEAD_MAX_CHARS = 600
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_YEAR_TOKEN = re.compile(r"\b(?:18|19|20)\d{2}\b")
_ANY_DIGIT = re.compile(r"\d")

# Each pattern is a refusal-language class, searched case-insensitively in the lead region.
# Classes (fixed order is display order only):
#   1. declarative "does not <communication verb>" incl. contractions
#   2. bare "no information/details/figures/..."
#   3. "not (any) information/details/..." noun-form
#   4. capability negation: cannot / can't / could not / unable to
#   5. "not [adverb(s)] stated/specified/mentioned/..." participle form
#   6. "insufficient information/detail/..."
#   7. "lacks (the) information/detail/..." verb form
#   8. "not possible to answer/determine/provide"
#   9. "no such/relevant/corresponding/matching X" mismatch form
_REFUSAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "declarative-does-not",
        r"\b(?:do|does|did)\s+not\s+(?:\w+\s+){0,1}?"
        r"(?:contain|provide|include|specify|state|mention|discuss|describe|address|give|offer"
        r"|report|indicate|identify|name|support|cover)"
        r"\b|\b(?:don't|doesn't|didn't)\s+"
        r"(?:contain|provide|include|specify|state|mention|discuss|describe|address|give|offer"
        r"|report|indicate|identify|name|support|cover)\b",
    ),
    (
        "bare-no-information",
        r"\bno\s+(?:information|details?|data|figures?|numbers?|statistics?|statements?|record"
        r"|mention|specifics?)\b",
    ),
    (
        "not-any-information",
        r"\bnot\s+(?:any\s+)?(?:information|details?|data|figures?|numbers?|specifics?)\b",
    ),
    (
        "capability-negation",
        r"\bcannot\b|\bcan't\b|\bcould\s*not\b|\bcouldn't\b|\bunab(?:le|ly)\b|\bunable\s+to\b",
    ),
    (
        "not-participle",
        r"\bnot\s+(?:\w+\s+){0,2}?"
        r"(?:specified|stated|mentioned|described|provided|available|documented|reported"
        r"|disclosed|found|given|included|present|contained|listed|recorded|revealed)\b",
    ),
    (
        "insufficient-information",
        r"\binsufficient\s+(?:information|detail|data|context|specificity)\b",
    ),
    (
        "lacks-information",
        r"\blacks?\s+(?:the\s+)?(?:information|detail|data|specificity|specifics|support"
        r"|evidence|coverage)\b|\blacking\s+(?:information|detail|data|specificity)\b",
    ),
    (
        "not-possible-to-answer",
        r"\bnot\s+possible\s+to\s+(?:answer|determine|provide|identify|say)\b",
    ),
    (
        "mismatch-no-such",
        r"\bno\s+(?:such|relevant|corresponding|matching|comparable|equivalent)\b",
    ),
)

# --- classification (blind: answer text only) -------------------------------


def _lead_region(answer_text: str) -> str:
    """First min(_LEAD_MAX_SENTENCES, _LEAD_MAX_CHARS) of the answer."""
    sentences = _SENTENCE_SPLIT.split(answer_text.strip())
    lead = " ".join(sentences[:_LEAD_MAX_SENTENCES])
    return lead[:_LEAD_MAX_CHARS]


def classify_answer(answer_text: str) -> dict:
    """Apply the frozen rule to one answer. Sees NOTHING but the answer string."""
    lead = _lead_region(answer_text)
    matched = [name for name, pattern in _REFUSAL_PATTERNS if re.search(pattern, lead, re.I)]
    residual_digits = _ANY_DIGIT.search(_YEAR_TOKEN.sub(" ", lead)) is not None
    return {
        "refusal_shaped": bool(matched) and not residual_digits,
        "lead_region": lead,
        "matched_patterns": matched,
        "has_numeric_commitment": residual_digits,
    }


# --- capture-file plumbing --------------------------------------------------


def _iter_capture_items(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    items = data["ground_truth"]
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a 'ground_truth' list")
    return items


def _classify_item(question_id: str, item: dict, arm: str | None) -> dict:
    answer = item.get("answer_text") or ""
    verdict = classify_answer(answer)
    record = {"question_id": question_id, "arm": arm, **verdict}
    if item.get("error"):
        # Captured generation errors exist as a possibility (A/B logged 0); a missing answer is
        # not a refusal. Classify as non-refusal and surface it rather than silently dropping.
        record["generation_error"] = True
        record["refusal_shaped"] = False
    return record


def _summarize(items: list[dict]) -> dict:
    absent = [i for i in items if i["arm"] == "absent"]
    answerable = [i for i in items if i["arm"] == "answerable"]
    return {
        "absent": {
            "n": len(absent),
            "refusal_shaped": sum(1 for i in absent if i["refusal_shaped"]),
            "errors": sum(1 for i in absent if i.get("generation_error")),
        },
        "answerable": {
            "n": len(answerable),
            "false_refusals": sum(1 for i in answerable if i["refusal_shaped"]),
            "errors": sum(1 for i in answerable if i.get("generation_error")),
        },
    }


def _join_arms_from_gt(capture_items: list[dict], gt_path: Path) -> list[dict]:
    """Attach absent/answerable arms from the fixture's absence_note field.

    Classification has ALREADY happened (per-item, answer-text-only) before this join runs; the
    join exists only so coverage/false-refusal denominators can be computed.
    """
    gt = json.loads(gt_path.read_text())["ground_truth"]
    absent_ids = {g["question_id"] for g in gt if g.get("absence_note")}
    known_ids = {g["question_id"] for g in gt}
    records = []
    for item in capture_items:
        qid = item["question_id"]
        if qid not in known_ids:
            raise ValueError(f"capture question {qid} not present in {gt_path}")
        arm = "absent" if qid in absent_ids else "answerable"
        records.append(_classify_item(qid, item, arm))
    return records


def _split_mode_records(absent_paths: list[Path], answerable_paths: list[Path]) -> list[dict]:
    records = []
    for path in absent_paths:
        records.extend(
            _classify_item(i["question_id"], i, "absent") for i in _iter_capture_items(path)
        )
    for path in answerable_paths:
        records.extend(
            _classify_item(i["question_id"], i, "answerable") for i in _iter_capture_items(path)
        )
    ids = [r["question_id"] for r in records]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate question_id across captures: {dupes}")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--absent-capture", nargs="*", default=[],
        help="capture JSON(s) whose items are all known-absent (pre-split mode)",
    )
    parser.add_argument(
        "--answerable-capture", nargs="*", default=[],
        help="capture JSON(s) whose items are all answerable (pre-split mode)",
    )
    parser.add_argument(
        "--combined-capture", default=None,
        help="one capture JSON over both arms; requires --gt (joined mode)",
    )
    parser.add_argument(
        "--gt", default=None,
        help="ground-truth fixture providing absence_note labels for --combined-capture",
    )
    parser.add_argument("--out", required=True, help="path for the classification report JSON")
    args = parser.parse_args()

    if args.combined_capture:
        if not args.gt or args.absent_capture or args.answerable_capture:
            parser.error("--combined-capture requires exactly --gt and no split captures")
        capture_items = _iter_capture_items(Path(args.combined_capture))
        records = _join_arms_from_gt(capture_items, Path(args.gt))
        inputs = {"combined_capture": args.combined_capture, "gt": args.gt}
    else:
        if not args.absent_capture and not args.answerable_capture:
            parser.error("give either --combined-capture/--gt or split captures")
        records = _split_mode_records(
            [Path(p) for p in args.absent_capture],
            [Path(p) for p in args.answerable_capture],
        )
        inputs = {
            "absent_captures": args.absent_capture,
            "answerable_captures": args.answerable_capture,
        }

    report = {
        "rule_version": RULE_VERSION,
        "rule": {
            "lead": f"first min({_LEAD_MAX_SENTENCES} sentences, {_LEAD_MAX_CHARS} chars)",
            "refusal_patterns": [name for name, _ in _REFUSAL_PATTERNS],
            "numeric_commitment_exemption": r"\b(?:18|19|20)\d{2}\b calendar years",
            "verdict": "refusal-shaped := refusal pattern in lead AND no non-year digit in lead",
        },
        "inputs": inputs,
        "items": sorted(records, key=lambda r: (r["arm"], r["question_id"])),
        "summary": _summarize(records),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    summary = report["summary"]
    print(f"classified {len(records)} items (rule v{RULE_VERSION}) -> {out_path}")
    print(
        f"absent: {summary['absent']['refusal_shaped']}/{summary['absent']['n']} refusal-shaped"
        f" | answerable: {summary['answerable']['n'] - summary['answerable']['false_refusals']}"
        f"/{summary['answerable']['n']} answered,"
        f" {summary['answerable']['false_refusals']} false refusals"
    )


if __name__ == "__main__":
    main()
