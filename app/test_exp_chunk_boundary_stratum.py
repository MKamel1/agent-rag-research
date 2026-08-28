"""Tests for `app/exp_chunk_boundary_stratum.py` -- SB-1's D2-reuse stratum harness.

Zero-GPU, zero-network. Exercises the harness against the REAL frozen 2026-08-23 D2 data
(`docs/eval-reports/data/2026-08-23-waymo-priority/*.json`) and the real `papers.db` in read-only
mode -- the same posture `nb_d2_block_adjacency.py`'s own module docstring describes for itself
("no retrieval runs, no GPU, no network"). This is the harness's own self-check: if it can't
reproduce D2's already-published, already-verified numbers byte-for-byte through the dynamic-
import path, it must not be trusted to grade a new arm either.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.exp_chunk_boundary_stratum import analyze, load_d2_module, stage_report

_D2_DATA_DIR = Path(
    "docs/eval-reports/data/2026-08-23-waymo-priority"
)
# Absolute: waymo/data/ is gitignored and shared across worktrees, not present in this worktree's
# own tree -- see app/exp_chunk_boundary_stratum.py's _DEFAULT_DB comment.
_DB = Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db")


def _skip_if_missing():
    import pytest

    if not _DB.exists() or not _D2_DATA_DIR.exists():
        pytest.skip("real papers.db / frozen D2 fixture data not present in this environment")


def test_load_d2_module_exposes_analyze_config_and_bucket_order():
    _skip_if_missing()
    d2 = load_d2_module()
    assert hasattr(d2, "analyze_config")
    assert hasattr(d2, "open_db_ro")
    assert d2.BUCKET_ORDER == [
        "cross_gold_paper", "same_chunk", "adjacent_chunk", "same_section", "same_doc_elsewhere",
    ]


def test_analyze_reproduces_published_headline_ver84_dense_only():
    """D2's own §1 headline table: ver84 x dense_only, n_scored=64, near-miss=27, buckets
    1/8/0/17 (cross_gold_paper/same_chunk/adjacent_chunk/same_section/same_doc_elsewhere order is
    cross_gold_paper=1, same_chunk=1, adjacent_chunk=8, same_section=0, same_doc_elsewhere=17)."""
    _skip_if_missing()
    d2 = load_d2_module()
    result = analyze(d2, _DB, _D2_DATA_DIR, "ver84", "dense_only")
    assert result["n_scored"] == 64
    assert result["n_near_miss"] == 27
    assert result["buckets"] == {
        "cross_gold_paper": 1,
        "same_chunk": 1,
        "adjacent_chunk": 8,
        "same_section": 0,
        "same_doc_elsewhere": 17,
    }
    assert result["g1_matches_prec1_table"] is True


def test_analyze_reproduces_published_headline_gt_wmr_fused():
    _skip_if_missing()
    d2 = load_d2_module()
    result = analyze(d2, _DB, _D2_DATA_DIR, "gt_wmr", "fused")
    assert result["n_scored"] == 66
    assert result["n_near_miss"] == 12
    assert result["buckets"] == {
        "cross_gold_paper": 0,
        "same_chunk": 1,
        "adjacent_chunk": 2,
        "same_section": 0,
        "same_doc_elsewhere": 9,
    }


def test_analyze_new_mode_label_skips_g1_gate_instead_of_crashing(tmp_path):
    """A mode string not in D2's own PREC1_DECOMPOSITION table (every SB-1 arm label) must not
    raise -- it reports g1_matches_prec1_table == "not_tabulated" (module docstring's own
    documented behavior), which is exactly what lets this harness grade a brand-new arm."""
    _skip_if_missing()
    d2 = load_d2_module()
    # Reuse a real, valid report under a label D2 never tabulated a PREC-1 count for.
    staged = stage_report(
        _D2_DATA_DIR / "ver84_dense_only.json", tmp_path, "ver84", "sb1_smoketest"
    )
    assert staged.exists()
    result = analyze(d2, _DB, tmp_path, "ver84", "sb1_smoketest")
    assert result["g1_matches_prec1_table"] == "not_tabulated"
    # Same underlying report as the dense_only headline test above -- same counts.
    assert result["n_scored"] == 64
    assert result["n_near_miss"] == 27


def test_stage_report_copies_byte_for_byte(tmp_path):
    src = tmp_path / "src.json"
    payload = {"questions": [{"question_id": "Q-1"}]}
    src.write_text(json.dumps(payload))
    dest_dir = tmp_path / "staged"

    dest = stage_report(src, dest_dir, "ver84", "my_arm")

    assert dest == dest_dir / "ver84_my_arm.json"
    assert json.loads(dest.read_text()) == payload
