"""Tests for scripts/nb_eval_runner.py's table math -- NB-D4.

All inputs are small synthetic reports shaped like `app/retrieval_eval.build_report`'s output;
nothing here imports the GPU-backed adapter wiring or touches the network (the repo's pytest
config disables sockets -- these tests never need it). The runner itself is exercised through
`--dry-run`, which prints the per-fixture commands without running any subprocess.
"""

import json
from pathlib import Path

from scripts.nb_eval_runner import (
    build_combined,
    extract_row,
    fixture_argv,
    load_and_verify_report,
    main,
    output_paths,
    render_markdown,
)


def _agg(ranks):
    """Mirrors app.retrieval_eval._recall_mrr so synthetic aggregates are self-consistent."""
    n = len(ranks)
    hits = sum(1 for r in ranks if r is not None)
    rr_sum = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n if n else None, "mrr": rr_sum / n if n else None, "n": n}


def _p1_rate(rows):
    if not rows:
        return None
    return sum(1 for q in rows if q["passage_level"]["rank"] == 1) / len(rows)


def make_report(row_specs, k=10):
    """A miniature build_report-shaped artifact from (gold?, paper_rank, scored?, vision?,
    p1_rank?) specs -- consistent by construction with what extract_row cross-checks."""
    questions = [
        {
            "question_id": f"q{i}",
            "question_type": "t",
            "doc_type": "paper",
            "gold_paper_ids": ["gold-x"] if spec["gold"] else [],
            "gold_block_id": "blk" if spec.get("scored") else None,
            "vision_derived": bool(spec.get("vision")),
            "error": None,
            "paper_level": {"hit": spec.get("paper_rank") is not None,
                            "rank": spec.get("paper_rank")},
            "passage_level": {"scored": bool(spec.get("scored")),
                              "hit": spec.get("p1_rank") is not None,
                              "rank": spec.get("p1_rank")},
        }
        for i, spec in enumerate(row_specs)
    ]
    answerable = [q for q in questions if q["gold_paper_ids"]]
    absent = [q for q in questions if not q["gold_paper_ids"]]
    scored_text = [
        q for q in questions if q["passage_level"]["scored"] and not q["vision_derived"]
    ]
    vision = [
        q for q in questions if q["passage_level"]["scored"] and q["vision_derived"]
    ]
    return {
        "scoring_rule": f"synthetic top-{k} truncation",
        "k": k,
        "n_questions": len(questions),
        "n_errors": 0,
        "paper_level": {
            "by_gold_status": {
                "answerable": _agg([q["paper_level"]["rank"] for q in answerable]),
                "known_absent": {
                    "n": len(absent),
                    "recall_at_k": None,
                    "mrr": None,
                    "n_with_top_result": len(absent),
                    "top_score": {"n": len(absent), "mean": 0.010, "median": 0.009,
                                  "min": 0.005, "max": 0.020},
                },
            },
        },
        "passage_level": {
            "by_vision_status": {
                "text_answerable": {
                    "rank_1_rate": _p1_rate(scored_text),
                    **_agg([q["passage_level"]["rank"] for q in scored_text]),
                },
                "vision": {"rank_1_rate": _p1_rate(vision)},
            },
        },
        "questions": questions,
    }


# 4 answerable (ranks 1, 3, miss, 2 -> R@10 = 3/4, MRR = (1 + 1/3 + 1/2) / 4); of their 4
# gold blocks exactly 1 sits at rank 1 (block-P@1 = 1/4). 2 absent items -- no gold set, no
# gold block (a known-absent item has nothing to retrieve against), so they appear ONLY in
# the absent arm.
SPECS = [
    {"gold": True, "paper_rank": 1, "scored": True, "p1_rank": 1},
    {"gold": True, "paper_rank": 3, "scored": True, "p1_rank": 2},
    {"gold": True, "paper_rank": None, "scored": True, "p1_rank": None},
    {"gold": True, "paper_rank": 2, "scored": True, "p1_rank": 4},
    {"gold": False, "paper_rank": 1},
    {"gold": False, "paper_rank": 5},
]


def _rows(names=("gt_wmr", "waymo_gt_verified")):
    return [extract_row(name, f"{name}.json", make_report(SPECS)) for name in names]


def test_extract_row_answerable_math_with_denominators():
    row = extract_row("synth", "gt.json", make_report(SPECS))
    assert row["answerable"]["hits"] == 3
    assert row["answerable"]["n"] == 4
    assert row["answerable"]["recall_at_k"] == 0.75
    assert abs(row["answerable"]["mrr"] - (1 + 1 / 3 + 1 / 2) / 4) < 1e-9


def test_extract_row_block_p1_over_text_arm_only():
    specs = [dict(s) for s in SPECS]
    specs.append({"gold": True, "paper_rank": 1, "scored": True, "p1_rank": 1,
                  "vision": True})  # excluded: answer exists only inside a figure
    row = extract_row("synth", "gt.json", make_report(specs))
    # The vision item adds neither hit nor denominator to the text arm.
    assert row["block_p_at_1"]["hits"] == 1
    assert row["block_p_at_1"]["n"] == 4
    assert abs(row["block_p_at_1"]["rate"] - 0.25) < 1e-9


def test_extract_row_absent_arm_reported_separately():
    row = extract_row("synth", "gt.json", make_report(SPECS))
    ka = row["known_absent"]
    # The absent items never enter the answerable denominators above...
    assert row["answerable"]["n"] == 4
    # ...and their own arm carries size + score distribution, no recall number.
    assert ka["n"] == 2
    assert ka["n_with_top_result"] == 2
    assert ka["top_score_median"] == 0.009
    assert ka["top_score_min"] == 0.005 and ka["top_score_max"] == 0.020


def test_extract_row_cross_check_rejects_disagreeing_truths():
    report = make_report(SPECS)
    report["paper_level"]["by_gold_status"]["answerable"]["recall_at_k"] = 1.0  # lie
    try:
        extract_row("synth", "gt.json", report)
    except SystemExit as e:
        assert "inconsistent report" in str(e)
    else:
        raise AssertionError("corrupted aggregate passed without a cross-check failure")


def test_extract_row_works_without_vision_split():
    report = make_report(SPECS)
    del report["passage_level"]["by_vision_status"]  # pre-VARM-1 shape
    row = extract_row("synth", "gt.json", report)
    assert row["block_p_at_1"]["hits"] == 1 and row["block_p_at_1"]["n"] == 4
    assert abs(row["block_p_at_1"]["rate"] - 0.25) < 1e-9


def test_extract_row_requires_per_question_rows():
    report = make_report(SPECS)
    del report["questions"]
    try:
        extract_row("synth", "gt.json", report)
    except SystemExit as e:
        assert "per-question" in str(e)
    else:
        raise AssertionError("missing per-question rows went unnoticed")


def test_silent_death_guard(tmp_path):
    try:
        load_and_verify_report(tmp_path / "nope.json")
    except SystemExit as e:
        assert "not written" in str(e)
    else:
        raise AssertionError("missing report file accepted")

    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    try:
        load_and_verify_report(empty)
    except SystemExit as e:
        assert "nothing was scored" in str(e)
    else:
        raise AssertionError("empty report accepted")

    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json")
    try:
        load_and_verify_report(garbage)
    except SystemExit as e:
        assert "not valid JSON" in str(e)
    else:
        raise AssertionError("unparseable report accepted")

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"n_questions": 7}))
    assert load_and_verify_report(good)["n_questions"] == 7


def test_fixture_argv_threads_the_reuse_seams_own_flags():
    argv = fixture_argv(
        "py", "app.retrieval_eval", "fixtures/eval/gt_wmr.json", "/cfg.yaml",
        "waymo_av_safety", 10, Path("/r.json"), "fused", None, None,
    )
    joined = " ".join(argv[1:])
    assert "-m app.retrieval_eval" in joined
    assert "--collection waymo_av_safety" in joined
    assert "--config /cfg.yaml" in joined
    assert "--k 10" in joined
    assert "--sparse-mode fused" in joined
    assert "--dense-weight" not in joined and "--limit" not in joined

    argv_full = fixture_argv(
        "py", "app.retrieval_eval", "gt.json", "/cfg.yaml", "coll", 5,
        Path("/r.json"), "dense_only", 0.7, 3,
    )
    jf = " ".join(argv_full[1:])
    assert "--dense-weight 0.7" in jf and "--limit 3" in jf


def test_output_paths_are_dated_and_tagged():
    out_json, out_md, raw_dir = output_paths(
        Path("docs/eval-reports/data"), "2026-08-25", "SAMPLE"
    )
    stem = "2026-08-25-nb-d4-dual-fixture-SAMPLE"
    assert out_json.name == f"{stem}.json"
    assert out_md.name == f"{stem}.md"
    assert raw_dir.name == stem


class _Args:
    date, tag, k = "2026-08-25", "SAMPLE", 10
    config, collection = "/cfg.yaml", "waymo_av_safety"
    sparse_mode, dense_weight, limit = "fused", None, None


def test_build_combined_records_run_identity_and_both_fixtures():
    args = _Args()
    raw = {name: Path(f"{name}.json") for name in ("gt_wmr", "waymo_gt_verified")}
    combined = build_combined(_rows(), args, raw)
    assert combined["date"] == "2026-08-25" and combined["tag"] == "SAMPLE"
    assert combined["collection"] == "waymo_av_safety"
    assert [r["fixture"] for r in combined["combined_table"]] == [
        "gt_wmr", "waymo_gt_verified"]
    assert "never blend" in combined["never_blend_note"].lower()


def test_render_markdown_shows_fractions_and_separate_absent_table():
    md = render_markdown(build_combined(_rows(), _Args(), {}))
    # Exact denominators appear as fractions, not bare floats...
    assert "3/4 = 0.7500" in md
    assert "1/4 = 0.2500" in md
    # ...and the absent arm gets its own never-blended table.
    assert "Known-absent arm" in md and "never blended" in md
    assert "| gt_wmr | 2 | 2 |" in md


def test_main_dry_run_prints_both_fixture_commands_without_running_anything(capsys):
    rc = main([
        "--dry-run", "--tag", "SMOKE", "--date", "2026-08-25",
        "--out-dir", str(Path("/tmp/opencode/nb-d4-dry-run")),
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[dry-run] gt_wmr:" in out and "[dry-run] waymo_gt_verified:" in out
    assert "--collection waymo_av_safety" in out
    assert "would write" in out and "2026-08-25-nb-d4-dual-fixture-SMOKE.md" in out
