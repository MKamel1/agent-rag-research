"""Tests for scripts/rerank_score_census.py (EV-13/EV-19). Zero-GPU, zero-network."""

import json

import pytest

from scripts import rerank_score_census as rc


def _item(qid, cls, top1, words=10.0, fusion=0.5):
    return rc.Item(
        qid,
        cls,
        {
            "rerank_top1": top1,
            "rerank_mean_top3": top1,
            "rerank_margin_12": 0.1,
            "rerank_pool_best": top1,
            rc.FUSION: fusion,
            rc.LENGTH: words,
        },
    )


def _six():
    # hand-computed: absent {0.1,0.2,0.6} vs answerable {0.5,0.7,0.9};
    # absent-lower wins 8 of 9 pairs
    absent = [_item(f"a{i}", "absent", v) for i, v in enumerate((0.1, 0.2, 0.6))]
    ans = [_item(f"b{i}", "answerable", v) for i, v in enumerate((0.5, 0.7, 0.9))]
    return absent, ans


def test_auroc_matches_hand_computation_on_six_items():
    absent, ans = _six()
    assert rc._auroc("rerank_top1", absent, ans) == pytest.approx(8 / 9)


def test_wrong_direction_score_gives_auroc_below_half():
    absent, ans = _six()
    assert rc._auroc("rerank_top1", ans, absent) == pytest.approx(1 / 9)  # roles swapped


def test_bootstrap_is_seeded_and_ci_brackets_a_perfect_separation():
    absent = [_item(f"a{i}", "absent", 0.1 + i / 100) for i in range(9)]
    ans = [_item(f"b{i}", "answerable", 0.8 + i / 100) for i in range(30)]
    one = rc.bootstrap(absent, ans, seed=1, reps=200)
    assert one == rc.bootstrap(absent, ans, seed=1, reps=200)
    assert one["auroc_ci"]["rerank_top1"] == (1.0, 1.0)


def test_wilson_interval_known_values():
    lo, hi = rc.wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    assert rc.wilson_interval(0, 0) is None


def test_length_leak_is_flagged_when_length_separates_as_well_as_the_score():
    absent = [_item(f"a{i}", "absent", 0.1 + i / 100, words=30.0 + i) for i in range(9)]
    ans = [_item(f"b{i}", "answerable", 0.8 + i / 100, words=8.0 + i % 3) for i in range(30)]
    e = rc.analyse(absent, ans)["features"]
    assert e["rerank_top1"]["no_better_than_length"] is True  # both 1.0: not "better"
    assert e[rc.LENGTH]["auroc"] == 1.0


def test_standards_style_set_breaks_absent_into_classes():
    items = [
        _item("p", "partial-absent", 0.2),
        _item("a", "absent", 0.1),
        *[_item(f"b{i}", "answerable", 0.5 + i / 10) for i in range(5)],
    ]
    r = rc.analyse_set(items)
    assert set(r["by_absent_class"]) == {"absent", "partial-absent"}
    assert r["by_absent_class"]["absent"]["n_absent"] == 1


def _fake_results(lo, auc_rerank, auc_fusion, auc_len, n_absent):
    def feat(a, ci):
        return {"auroc": a, "auroc_ci95": ci}

    f = {x: feat(0.5, (0.3, 0.7)) for x in rc.FEATURES}
    f["rerank_top1"] = feat(auc_rerank, (lo, 0.99))
    f[rc.FUSION], f[rc.LENGTH] = feat(auc_fusion, (0.3, 0.8)), feat(auc_len, (0.3, 0.8))
    return {"n_absent": n_absent, "n_answerable": 50, "features": f}


def test_verdict_needs_two_qualifying_sets_all_three_conditions():
    good = _fake_results(0.75, 0.9, 0.6, 0.6, 22)
    assert rc.verdict({"s1": good, "s2": good}, set())["verdict"] == "CANDIDATE"
    # only one set passes
    assert rc.verdict({"s1": good, "s2": _fake_results(0.65, 0.8, 0.6, 0.6, 22)}, set())[
        "verdict"
    ].startswith("NO SIGNAL")
    # lower bound fine but fusion beats it
    assert rc.verdict({"s1": good, "s2": _fake_results(0.75, 0.9, 0.95, 0.6, 22)}, set())[
        "verdict"
    ].startswith("NO SIGNAL")
    # length beats it
    assert rc.verdict({"s1": good, "s2": _fake_results(0.75, 0.9, 0.6, 0.95, 22)}, set())[
        "verdict"
    ].startswith("NO SIGNAL")


def test_small_and_secondary_sets_never_count():
    good = _fake_results(0.75, 0.9, 0.6, 0.6, 22)
    v = rc.verdict(
        {"s1": good, "books": _fake_results(0.75, 0.9, 0.6, 0.6, 5), "sec": good}, {"sec"}
    )
    assert v["qualifying_sets"] == ["s1"] and v["verdict"].startswith("NO SIGNAL")
    assert v["fewer_than_two_qualifying_sets_supplied"] is True


def test_load_items_partitions_by_gold_and_requires_the_rerank_field(tmp_path):
    gt = {
        "ground_truth": [
            {
                "question_id": "A",
                "question_text": "one two three",
                "tests": "answerable",
                "source_paper_id": "P",
            },
            {
                "question_id": "X",
                "question_text": "four five",
                "tests": "absent",
                "dimension": "partial-absent",
                "source_paper_id": None,
            },
        ]
    }
    gtp = tmp_path / "gt.json"
    gtp.write_text(json.dumps(gt))
    rr = {"max": 0.9, "mean_top3": 0.8, "margin_12": 0.1, "pool_best": 0.9}
    rows = [
        {
            "question_id": "A",
            "gold_paper_ids": ["P"],
            "error": None,
            "top_score": 0.03,
            "rerank": rr,
        },
        {"question_id": "X", "gold_paper_ids": [], "error": None, "top_score": 0.02, "rerank": rr},
    ]
    rp = tmp_path / "r.json"
    rp.write_text(json.dumps({"questions": rows}))
    items, errored = rc.load_items(rp, gtp)
    assert [(i.cls, i.values[rc.LENGTH]) for i in items] == [
        ("answerable", 3.0),
        ("partial-absent", 2.0),
    ]
    assert errored == 0
    rows[0].pop("rerank")
    rp.write_text(json.dumps({"questions": rows}))
    with pytest.raises(ValueError, match="record-rerank-scores"):
        rc.load_items(rp, gtp)
