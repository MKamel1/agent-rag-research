"""Unit tests for `app/exp_agentic_loop_v0.py` (SB-3). Zero-GPU, zero-network (TEST-STRATEGY.md
golden rule): commit (1) covers only pure functions -- the frozen routing rule, the frozen
(illustrative) action mapping, the AUROC implementation, and the W-A4 loader against a small
in-memory fixture. LLM-adapter tests land in the commits that add those adapters.
"""

import json
from pathlib import Path

import pytest

from app.exp_agentic_loop_v0 import (
    evaluator_action,
    load_raw_records,
    load_wa4_usable,
    route_to_decompose,
    auroc_pos_higher,
)


# ---------------------------------------------------------------------------
# evaluator_action: frozen, illustrative tertile split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sufficiency,expected",
    [(1.0, "proceed"), (0.66, "proceed"), (0.65, "decompose"), (0.33, "decompose"), (0.32, "abstain"), (0.0, "abstain")],
)
def test_evaluator_action_thresholds(sufficiency, expected):
    assert evaluator_action(sufficiency) == expected


# ---------------------------------------------------------------------------
# route_to_decompose: frozen routing rule
# ---------------------------------------------------------------------------


def test_route_to_decompose_hard_difficulty_routes_regardless_of_dimension():
    assert route_to_decompose("single-passage factual lookup", "hard") is True


def test_route_to_decompose_multi_paper_synthesis_routes_even_if_easy():
    assert route_to_decompose("multi-paper synthesis", "easy") is True


def test_route_to_decompose_negation_and_scope_routes():
    assert route_to_decompose("negation and scope", "medium") is True


def test_route_to_decompose_plain_medium_lookup_does_not_route():
    assert route_to_decompose("single-passage factual lookup", "medium") is False


# ---------------------------------------------------------------------------
# load_raw_records: question_id -> raw record join
# ---------------------------------------------------------------------------


def test_load_raw_records_joins_by_question_id(tmp_path: Path):
    gt = {
        "ground_truth": [
            {"question_id": "Q-1", "dimension": "numeric/quantitative", "difficulty": "easy"},
            {"question_id": "Q-2", "dimension": "negation and scope", "difficulty": "hard"},
        ]
    }
    path = tmp_path / "gt.json"
    path.write_text(json.dumps(gt))

    records = load_raw_records(path)

    assert records["Q-1"]["difficulty"] == "easy"
    assert records["Q-2"]["dimension"] == "negation and scope"


# ---------------------------------------------------------------------------
# auroc_pos_higher: known closed-form cases, self-verified against brute force internally
# ---------------------------------------------------------------------------


def test_auroc_perfect_separation_is_one():
    assert auroc_pos_higher(pos=[0.9, 0.8, 0.7], neg=[0.1, 0.2, 0.3]) == 1.0


def test_auroc_perfect_inversion_is_zero():
    assert auroc_pos_higher(pos=[0.1, 0.2], neg=[0.8, 0.9]) == 0.0


def test_auroc_all_tied_is_one_half():
    assert auroc_pos_higher(pos=[0.5, 0.5], neg=[0.5, 0.5]) == 0.5


def test_auroc_empty_arm_raises():
    with pytest.raises(ValueError):
        auroc_pos_higher(pos=[], neg=[0.1])


# ---------------------------------------------------------------------------
# load_wa4_usable: filters to accepted/accepted_with_correction, derives required sub-parts
# ---------------------------------------------------------------------------


def _wa4_entry(item_id: str, status: str, sub_parts: list[dict]) -> dict:
    return {
        "id": item_id,
        "adjudication_status": status,
        "item": {"id": item_id, "question": f"question for {item_id}", "sub_parts": sub_parts},
    }


def test_load_wa4_usable_excludes_rejected(tmp_path: Path):
    data = {
        "items": [
            _wa4_entry("Q-A", "accepted", [{"text": "s1", "status": "supported", "gold_ref": {"block_id": "p:b1"}}]),
            _wa4_entry("Q-B", "accepted_with_correction", [{"text": "s1", "status": "absent"}]),
            _wa4_entry("Q-C", "rejected", [{"text": "s1", "status": "supported", "gold_ref": {"block_id": "p:b9"}}]),
        ]
    }
    path = tmp_path / "wa4.json"
    path.write_text(json.dumps(data))

    items = load_wa4_usable(path)

    assert {it.item_id for it in items} == {"Q-A", "Q-B"}


def test_load_wa4_usable_required_sub_parts_is_supported_only(tmp_path: Path):
    data = {
        "items": [
            _wa4_entry(
                "Q-A", "accepted",
                [
                    {"text": "s1", "status": "supported", "gold_ref": {"block_id": "p:b1"}},
                    {"text": "s2", "status": "absent"},
                ],
            ),
        ]
    }
    path = tmp_path / "wa4.json"
    path.write_text(json.dumps(data))

    items = load_wa4_usable(path)

    assert len(items[0].sub_parts) == 2
    assert len(items[0].required_sub_parts) == 1
    assert items[0].required_sub_parts[0].gold_block_id == "p:b1"


def test_load_wa4_usable_absent_sub_part_has_no_gold_block_id(tmp_path: Path):
    data = {"items": [_wa4_entry("Q-A", "accepted", [{"text": "s1", "status": "absent"}])]}
    path = tmp_path / "wa4.json"
    path.write_text(json.dumps(data))

    items = load_wa4_usable(path)

    assert items[0].sub_parts[0].gold_block_id is None


def test_load_wa4_usable_real_fixture_is_31_items_with_31_required_subgoals():
    """Cross-checks against the real committed W-A4 file, not just a synthetic one -- the counts
    the ticket itself names (31 usable of 33)."""
    real_path = Path(__file__).resolve().parent.parent / (
        "docs/eval-reports/data/2026-08-28-wa4-gt/crossverify/wa4_adjudicated.json"
    )
    items = load_wa4_usable(real_path)
    assert len(items) == 31
    assert sum(len(it.required_sub_parts) for it in items) == 31
