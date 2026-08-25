"""Tests for scripts/nb_xp_deeppool_tables.py's pure aggregation math -- NB-X-P.

All inputs are small synthetic reports shaped like `app/retrieval_eval.build_report`'s output;
nothing here imports the GPU-backed adapter wiring or touches the network (the repo's pytest
config disables sockets). The sweep itself is exercised through `--dry-run`, which prints each
arm's command without running any subprocess.
"""

import pytest

from scripts.nb_xp_deeppool_tables import (
    assert_deterministic_pair,
    load_reusable_report,
    main,
    newcomer_effect,
    top10_restricted,
)


def _agg(ranks):
    n = len(ranks)
    hits = sum(1 for r in ranks if r is not None)
    rr = sum(1.0 / r for r in ranks if r is not None)
    return {"recall_at_k": hits / n if n else None, "mrr": rr / n if n else None, "n": n}


def make_report(specs, k):
    """specs: list of (paper_rank, passage_rank, scored, vision, error) tuples."""
    questions = [
        {
            "question_id": f"q{i}",
            "question_type": "t",
            "doc_type": "paper",
            "gold_paper_ids": [] if err else ["gold-x"],
            "gold_block_id": "blk" if scored else None,
            "vision_derived": bool(vision),
            "error": err,
            "paper_level": {"hit": pr is not None, "rank": pr},
            "passage_level": {"scored": bool(scored), "hit": prk is not None, "rank": prk},
        }
        for i, (pr, prk, scored, vision, err) in enumerate(specs)
    ]
    answerable = [q for q in questions if q["gold_paper_ids"]]
    absent = [q for q in questions if not q["gold_paper_ids"]]
    scored_text = [q for q in questions if q["passage_level"]["scored"]
                   and not q["vision_derived"]]
    return {
        "scoring_rule": f"synthetic top-{k} truncation",
        "k": k,
        "n_questions": len(questions),
        "n_errors": sum(1 for s in specs if s[4]),
        "paper_level": {
            "by_gold_status": {
                "answerable": _agg([q["paper_level"]["rank"] for q in answerable]),
                "known_absent": {
                    "n": len(absent), "recall_at_k": None, "mrr": None,
                    "n_with_top_result": len(absent),
                    "top_score": {"n": len(absent), "mean": 0.01, "median": 0.01,
                                  "min": 0.01, "max": 0.01},
                },
            },
        },
        "passage_level": {
            "n_scored": sum(1 for s in specs if s[2]),
            "by_vision_status": {
                "text_answerable": {
                    **_agg([q["passage_level"]["rank"] for q in scored_text]),
                    "rank_1_rate": (
                        sum(1 for q in scored_text if q["passage_level"]["rank"] == 1)
                        / len(scored_text)
                    ) if scored_text else None,
                },
            },
        },
        "questions": questions,
    }


def test_top10_restricted_counts_only_ranks_within_ten():
    # paper ranks: 3 (in), 12 (out), 7 (in), None (miss) -> R@10' = 2/4, MRR@10' = (1/3+1/7)/4
    report = make_report([(3, None, False, False, None), (12, None, False, False, None),
                          (7, None, False, False, None), (None, None, False, False, None)], k=64)
    t = top10_restricted(report)
    assert t["recall_at_10"] == {"hits": 2, "n": 4, "rate": 0.5}
    assert t["mrr_at_10"] == pytest.approx((1 / 3 + 1 / 7) / 4)


def test_top10_restricted_excludes_errored_rows():
    report = make_report([(2, None, False, False, None), (None, None, False, False, "boom")],
                         k=32)
    t = top10_restricted(report)
    assert t["recall_at_10"]["n"] == 1
    assert t["recall_at_10"]["hits"] == 1


def test_newcomer_categories_and_errored_accounting():
    baseline = make_report(
        [(1, 1, True, False, None),      # q0: exposed @1
         (3, 5, True, False, None),      # q1: exposed @5
         (None, 12, True, False, None),  # q2: exposed beyond top-10
         (None, None, True, False, None),  # q3: never exposed
         (2, 2, True, False, None)],     # q4: exposed @2
        k=10,
    )
    arm = make_report(
        [(4, 4, True, False, None),      # q0: LOST 1->4
         (3, 5, True, False, None),      # q1: unchanged
         (1, 2, True, False, None),      # q2: GAINED into top-10 (12->2)
         (None, None, True, False, None),  # q3: still unexposed
         (None, None, True, False, "boom")],  # q4: errored in arm -> accounted, not dropped
        k=64,
    )
    eff = newcomer_effect(baseline, arm)
    gb = eff["gold_block"]
    assert gb["lost_rank_count"] == 1
    assert gb["lost_rank"] == [{"question_id": "q0", "baseline_rank": 1, "arm_rank": 4}]
    assert gb["lost_from_top10_ids"] == []
    assert [g["question_id"] for g in gb["gained_into_top10"]] == ["q2"]
    # q2 (12->2) is BOTH a top-10 gain and strictly shallower; categories are independent reads.
    assert gb["improved"] == [{"question_id": "q2", "baseline_rank": 12, "arm_rank": 2}]
    assert eff["errored_in_either_run"] == ["q4"]
    # paper level: q0 1->4 lost; q2's None->1 is a first exposure, not an "improvement"
    # (that category needs a baseline rank to improve from); paper gains live in R@k instead.
    assert eff["gold_paper"]["lost_rank_count"] == 1
    assert eff["gold_paper"]["improved_count"] == 0


def test_lost_from_top10_when_pushed_past_ten_or_gone():
    baseline = make_report([(9, 9, True, False, None), (8, 8, True, False, None)], k=10)
    arm = make_report([(None, 11, True, False, None), (None, None, True, False, None)], k=64)
    gb = newcomer_effect(baseline, arm)["gold_block"]
    assert sorted(gb["lost_from_top10_ids"]) == ["q0", "q1"]
    assert gb["lost_rank_count"] == 1  # only q0 still found (deeper); q1 vanished entirely


def test_determinism_guard_passes_on_identical_and_fails_on_any_rank_drift():
    base = make_report([(1, 1, True, False, None), (5, 7, True, False, None)], k=10)
    same = make_report([(1, 1, True, False, None), (5, 7, True, False, None)], k=32)
    assert_deterministic_pair(base, same)  # no raise
    drifted = make_report([(2, 1, True, False, None), (5, 7, True, False, None)], k=32)
    with pytest.raises(SystemExit, match="disagrees"):
        assert_deterministic_pair(base, drifted)


def test_error_state_change_also_trips_the_guard():
    base = make_report([(1, None, False, False, None)], k=10)
    arm = make_report([(None, None, False, False, "late boom")], k=32)
    with pytest.raises(SystemExit, match="error state differs"):
        assert_deterministic_pair(base, arm)


def test_reusable_report_requires_existing_verifying_right_k(tmp_path):
    p = tmp_path / "gt_wmr.k10.json"
    assert load_reusable_report(p, 10) is None  # missing
    p.write_text("not json")
    assert load_reusable_report(p, 10) is None  # unparseable
    p.write_text('{"k": 32, "n_questions": 5}')
    assert load_reusable_report(p, 10) is None  # wrong-k leftover
    p.write_text('{"k": 10, "n_questions": 0}')
    assert load_reusable_report(p, 10) is None  # empty run
    p.write_text('{"k": 10, "n_questions": 70}')
    assert load_reusable_report(p, 10) == {"k": 10, "n_questions": 70}


def test_dry_run_prints_every_arm_fixture_pair_without_subprocesses(capsys):
    rc = main([
        "--dry-run", "--ks", "10", "32",
        "--out-dir", "/tmp/opencode/nb-xp-test-out",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    # two arms x two fixtures = four planned invocations, all naming the reuse seam explicitly
    assert out.count("-m app.retrieval_eval") == 4
    assert "--collection waymo_av_safety" in out
    assert "nb-xp-test-out/raw/gt_wmr.k32.json" in out
