"""Mechanical invariants for the imported 210-question Spike-2 eval set (`fixtures/eval/`).

`fixtures/**` is CODEOWNERS-protected (GIT-WORKFLOW.md foundation-change protocol), so this
guardrail has to live in *this* repo, not only in the sibling project that built the set
(`rag-system-eval-set/tests/test_eval_dataset.py`, outside this repo — same structural checks,
different repo, different CODEOWNERS). It re-asserts the structural half of that suite: total
count, blind/ground-truth ID alignment, zero leakage in the blind file, category-quota coverage.
It does **not** attempt the semantic half (title leakage, multi-paper scoping, excerpt
normalization) — those are disclosed as known limitations in PHASE0-RUNBOOK.md's Spike 2 section
and TEST-STRATEGY.md's "Retrieval eval set" section, not mechanically checked here.
"""

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
BLIND_PATH = FIXTURE_DIR / "eval_questions_blind.json"
GT_PATH = FIXTURE_DIR / "eval_ground_truth.json"

TOTAL_ITEMS = 210
# Category quotas per TEST-STRATEGY.md "Retrieval eval set": 100 single-paper reading-comprehension
# (split Result/Method/Assumption/Contribution-Comprehension), 10 cross-paper synthesis, 50
# single-paper deep-reasoning, 50 multi-paper deep-reasoning.
EXPECTED_TYPE_COUNTS = {
    "Result-Comprehension": 28,
    "Method-Comprehension": 51,
    "Assumption-Comprehension": 6,
    "Contribution-Comprehension": 15,
    "Multi-Paper-Synthesis": 10,
    "Single-Paper-Reasoning": 50,
    "Multi-Paper-Reasoning": 50,
}
LEAKED_FIELDS = {
    "answer_text",
    "source_paper_id",
    "source_paper_title",
    "section_path",
    "passage_excerpt",
    "difficulty",
}


def _load(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def demo():
    blind = _load(BLIND_PATH)["questions"]
    gt = _load(GT_PATH)["ground_truth"]

    # Total count == 210 for both files.
    assert len(blind) == TOTAL_ITEMS, f"blind set has {len(blind)} items, expected {TOTAL_ITEMS}"
    assert len(gt) == TOTAL_ITEMS, f"ground truth has {len(gt)} items, expected {TOTAL_ITEMS}"

    # Every blind question_id has a matching ground-truth question_id and vice versa.
    blind_ids = {item["question_id"] for item in blind}
    gt_ids = {item["question_id"] for item in gt}
    assert blind_ids == gt_ids, (
        f"blind/ground-truth ID mismatch: "
        f"in blind only={blind_ids - gt_ids}, in ground-truth only={gt_ids - blind_ids}"
    )
    assert len(blind_ids) == TOTAL_ITEMS, "duplicate question_id in blind set"

    # Zero leaked fields in the blind file.
    for item in blind:
        leaked = LEAKED_FIELDS & set(item.keys())
        assert not leaked, f"{item['question_id']} leaks fields in blind set: {leaked}"
        assert {"question_id", "question_text", "question_type"} <= set(item.keys())

    # Category quota coverage matches TEST-STRATEGY.md's documented breakdown.
    type_counts = {}
    for item in gt:
        qtype = item["question_type"]
        type_counts[qtype] = type_counts.get(qtype, 0) + 1
    assert type_counts == EXPECTED_TYPE_COUNTS, (
        f"question_type distribution drifted from the documented quotas: {type_counts}"
    )

    print("all eval fixture invariants hold")


def test_eval_fixture_invariants():
    demo()


if __name__ == "__main__":
    demo()
