"""Tests for scripts/session2_ab_tools.py and the EV-14 HTTP script (offline, synthetic data)."""

import importlib.util
import random
import re
import sqlite3
from pathlib import Path

import pytest

from scripts import session2_ab_tools as t

HTTP_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "docs/eval-reports/data/2026-11-11-session2/filtered_search_check.py"
)
spec = importlib.util.spec_from_file_location("filtered_search_check", HTTP_SCRIPT)
fsc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fsc)


def _row(qid, blocks, papers, chunks=None, gold="P1"):
    return {
        "question_id": qid,
        "question_type": "x",
        "error": None,
        "gold_paper_ids": [gold],
        "retrieved_paper_ids": papers,
        "retrieved_block_ids": blocks,
        "retrieved_chunk_ids": chunks
        if chunks is not None
        else [[b.replace("b", "c")] for b in blocks],
    }


def _gt(n, dim="d"):
    return {
        f"q{i}": {
            "question_id": f"q{i}",
            "tests": "answerable",
            "dimension": dim,
            "gold_block_id": f"P1:b{i}",
            "gold_chunk_id": f"P1:c{i}",
        }
        for i in range(n)
    }


def _maps():
    return ({}, {})  # chunk_id->anchor, anchor->members: gold match falls back to gold_block_id


def test_headroom_counts_scored_minus_hits():
    s = {
        "/r/papers.json": {
            "per_dimension": {
                "a": {"member_hit": {"hits": 40, "n": 50}},
                "b": {"member_hit": {"hits": 5, "n": 11}},
            },
            "n_errored_rows": 0,
            "run_valid": True,
        }
    }
    h = t.headroom(s, "/papers.json")
    assert h["headroom"] == 16 and h["scored"] == 61


def test_headroom_requires_exactly_one_match():
    with pytest.raises(SystemExit):
        t.headroom({}, "/papers.json")


def test_paired_wins_losses_and_gating_stratum():
    gt = _gt(12)
    base = {
        "questions": [
            _row(f"q{i}", [f"P1:b{i}"] if i < 6 else ["P1:bX"], ["P1"]) for i in range(12)
        ]
    }
    arm = {
        "questions": [
            _row(f"q{i}", [f"P1:b{i}"] if i < 3 else ["P1:bX"], ["P1"]) for i in range(12)
        ]
    }
    p = t.paired(base, arm, gt, _maps(), 10)
    m = p["metrics"]["member"]
    assert (m["base"], m["arm"], m["wins"], m["losses"], m["net"]) == (6, 3, 0, 3, -3)
    assert p["worst_stratum_net"] == -3  # one dimension with n=12 >= 10


def test_small_stratum_cannot_veto():
    gt = _gt(5)
    base = {"questions": [_row(f"q{i}", [f"P1:b{i}"], ["P1"]) for i in range(5)]}
    arm = {"questions": [_row(f"q{i}", ["P1:bX"], ["P1"]) for i in range(5)]}
    assert t.paired(base, arm, gt, _maps(), 10)["worst_stratum_net"] == 0


def test_paired_refuses_different_id_sets():
    gt = _gt(2)
    with pytest.raises(SystemExit):
        t.paired(
            {"questions": [_row("q0", [], [])]},
            {"questions": [_row("q1", [], [])]},
            gt,
            _maps(),
            10,
        )


def test_stub_ceiling_counts_only_misses_with_stub_in_topk():
    gt = _gt(3)
    rows = [
        _row("q0", ["S:b0", "P1:bX"], ["P1"], [["S:c0"], ["P1:cX"]]),  # stub at 1, miss -> ceiling
        _row("q1", ["S:b1", "P1:b1"], ["P1"], [["S:c1"], ["P1:c1"]]),  # stub but already hit
        _row("q2", ["P1:bX"], ["P1"], [["P1:cX"]]),  # miss, no stub
    ]
    res = t.stub_ceiling({"questions": rows}, gt, _maps(), {"S:c0", "S:c1"}, 10, 2)
    assert res["stub_rank1_answerable"] == 2 and res["ceiling"] == 1 and res["run"] is False
    assert res["stub_slots_topk"] == 2 and res["slots_topk"] == 5


def test_stub_ceiling_ambiguous_rank_is_not_a_stub():
    gt = _gt(1)
    rows = [_row("q0", ["S:b0"], ["P1"], [["S:c0", "S:c0b"]])]
    res = t.stub_ceiling({"questions": rows}, gt, _maps(), {"S:c0"}, 10, 1)
    assert res["stub_rank1_answerable"] == 0


def test_stub_ceiling_needs_chunk_ids():
    r = _row("q0", ["a"], ["P1"])
    del r["retrieved_chunk_ids"]
    with pytest.raises(SystemExit):
        t.stub_ceiling({"questions": [r]}, _gt(1), _maps(), set(), 10, 2)


def _pair(label, net, worst=0, tags=None, wins=None, losses=0, paper=None):
    m = {"net": net, "wins": net if wins is None else wins, "losses": losses}
    metrics = {"member": m}
    if paper is not None:
        metrics["paper"] = {"net": paper}
    return {"label": label, "metrics": metrics, "worst_stratum_net": worst, "tags": tags or {}}


def test_depth_verdict_ge2_vs_g1():
    v = t.verdict_depth(_pair("papers", 2), None)
    assert v["rule_ge2_prefers"].startswith("128") and not v["recommend_default_change"]
    v = t.verdict_depth(_pair("papers", 4), _pair("papers", 1))
    assert v["recommend_default_change"]
    v = t.verdict_depth(_pair("papers", 4, worst=-2), None)
    assert v["rule_ge2_prefers"] == "32"


def test_stub_verdict_needs_rank1_gain_and_no_veto():
    mk = lambda lab, net, r1, w=0: _pair(lab, net, w, {"ceiling": {"stub_rank1_answerable": r1}})  # noqa: E731
    assert t.verdict_stub([mk("a", 2, 3), mk("b", 0, 1)])["verdict"] == "ADOPT"
    assert t.verdict_stub([mk("a", 2, 0)])["verdict"] == "REJECT"
    assert t.verdict_stub([mk("a", 2, 3), mk("b", 0, 1, -2)])["verdict"] == "REJECT"


def test_ligature_verdict_rule():
    def pr(label, mode, paper, member=0):
        p = _pair(label, member, 0, {"mode": mode}, paper=paper)
        return p

    ok = [pr("papers", "sparse_only", 1), pr("papers", "fused", -1, -1), pr("books", "fused", 0)]
    assert t.verdict_ligature(ok)["verdict"] == "ADOPT-PENDING-STANDARDS"
    bad = [pr("papers", "sparse_only", 0), pr("papers", "fused", 0), pr("books", "fused", 0)]
    assert t.verdict_ligature(bad)["verdict"] == "REJECT"
    reg = [pr("papers", "sparse_only", 2), pr("papers", "fused", -2), pr("books", "fused", 0)]
    assert t.verdict_ligature(reg)["verdict"] == "REJECT"
    assert t.verdict_ligature(ok[:2])["verdict"].startswith("INCOMPLETE")


def test_ligature_flags_read_only(tmp_path):
    db = tmp_path / "p.db"
    con = sqlite3.connect(db)
    con.execute("create table chunks (chunk_id, text)")
    con.executemany(
        "insert into chunks values (?,?)", [("c1", "the efect of x"), ("c2", "the effect")]
    )
    con.commit()
    con.close()
    before = db.read_bytes()
    gt = {"a": {"gold_chunk_id": "c1"}, "b": {"gold_chunk_id": "c2"}, "c": {"gold_chunk_id": "zz"}}
    flags = t.ligature_flags(gt, str(db), re.compile(r"\befects?\b"))
    assert flags == {"a": True, "b": False, "c": None}
    assert db.read_bytes() == before


def test_query_repair_check_mirrors_lowercase_then_repair():
    gt = {"a": {"question_text": "The Efect"}, "b": {"question_text": "fine"}}
    assert t.changed_by_query_repair(gt, lambda s: s.replace("efect", "effect")) == ["a"]


def test_real_repair_leaves_plain_question_alone():
    from rag.ligatures import repair_ligatures

    gt = {"a": {"question_text": "What is the average treatment effect?"}}
    assert t.changed_by_query_repair(gt, repair_ligatures) == []


# ---- EV-14 HTTP script
def test_overlap():
    assert fsc.overlap(["a", "b"], ["a", "c"]) == 0.5
    assert fsc.overlap([], []) == 1.0


def test_filters_all_carry_kind_equality():
    for name in fsc.FILTERS:
        flt = fsc.query_filter(name, {"paper_id": "p", "categories": ["stat.ME"]})
        assert {
            "key": "kind",
            "match": {"value": fsc.FILTERS[name][1][0]["match"]["value"]},
        } in flt["must"]


def test_categories_filter_needs_categories():
    assert fsc.query_filter("F7", {"categories": []}) is None


def test_http_wrapper_refuses_writes():
    http = fsc.ReadOnlyHttp("http://x", "c")
    for bad in ("points", "points/delete", "index", "points/payload"):
        with pytest.raises(ValueError):
            http.post(bad, {})
    assert http.calls == 0


class _Fake:
    """Approximate search misses one of the 10 exact neighbours for every query."""

    def __init__(self):
        self.bodies = []

    def post(self, endpoint, body):
        self.bodies.append((endpoint, body))
        if endpoint == "points/scroll":
            return {
                "points": [
                    {
                        "id": f"id{len(self.bodies)}",
                        "vector": {"dense": [0.0]},
                        "payload": {"paper_id": "p", "categories": ["c"]},
                    }
                ]
            }
        ids = [f"n{i}" for i in range(11)]
        if not body["params"]["exact"]:
            ids[3] = "other"
        return {"points": [{"id": i} for i in ids]}


def test_run_filter_overlap_and_exact_flag():
    r = fsc.run_filter(_Fake(), "F1", 4, 10, random.Random(1))
    assert r["n"] == 4 and abs(r["mean_overlap"] - 0.9) < 1e-9 and r["n_short_lists"] == 0
    res = {f: {"n": 4, "mean_overlap": 0.9, "n_short_lists": 0} for f in fsc.FILTERS}
    assert fsc.verdict(res).startswith("CQ-9 TRIGGER")
    res = {f: {"n": 4, "mean_overlap": 1.0, "n_short_lists": 0} for f in fsc.FILTERS}
    assert fsc.verdict(res).startswith("CLOSE CQ-9")


def test_sampling_is_seeded():
    a, b = _Fake(), _Fake()
    fsc.sample_points(a, "F2", 3, random.Random(5))
    fsc.sample_points(b, "F2", 3, random.Random(5))
    assert [x[1]["offset"] for x in a.bodies] == [x[1]["offset"] for x in b.bodies]
