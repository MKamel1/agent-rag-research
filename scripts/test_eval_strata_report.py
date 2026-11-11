"""Tests for scripts/eval_strata_report.py -- synthetic dicts + temp SQLite DB."""

import json
import sqlite3

import pytest

from scripts.eval_strata_report import (
    analyze,
    build_db_maps,
    fmt,
    join_ground_truth,
    load_labels,
    main,
)

# Paper P: blocks b0..b5; chunks c0 anchor b0 (members b0,b1), c1 anchor b2 (b2,b3), c2 anchor b4
# (b4,b5; empty body = stub). Paper Q: one chunk.
BODY = "x" * 60


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "papers.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE chunks(chunk_id, paper_id, text, anchor_json);"
        "CREATE TABLE blocks(block_id, paper_id, idx, text);"
    )
    for pid, n in (("P", 6), ("Q", 1)):
        for i in range(n):
            con.execute("INSERT INTO blocks VALUES(?,?,?,?)", (f"{pid}:b{i}", pid, i, "t"))
    for cid, pid, anchor, body in [
        ("P:c0", "P", "P:b0", BODY),
        ("P:c1", "P", "P:b2", BODY),
        ("P:c2", "P", "P:b4", ""),
        ("Q:c0", "Q", "Q:b0", BODY),
    ]:
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?)",
            (cid, pid, f"title\nsec\n\n{body}", json.dumps({"block_id": anchor})),
        )
    con.commit()
    con.close()
    return path


def item(qid, dim="d", tests="answerable", **kw):
    return {"question_id": qid, "dimension": dim, "tests": tests, **kw}


def row(qid, papers, blocks, gold=("P",), score=1.0):
    return {
        "question_id": qid,
        "gold_paper_ids": list(gold),
        "retrieved_paper_ids": papers,
        "retrieved_block_ids": blocks,
        "top_score": score,
    }


def run(gt_items, rows, db, labels=None, k=10):
    gt = {i["question_id"]: i for i in gt_items}
    maps = build_db_maps(db, {"P", "Q", "R"})
    return analyze({"questions": rows}, gt, k, *maps, labels=labels)


def test_db_maps(db):
    ca, members, stubs = build_db_maps(db, {"P", "Q"})
    assert ca["P:c1"] == "P:b2"
    assert members["P:b2"] == {"P:b2", "P:b3"}
    assert members["P:b4"] == {"P:b4", "P:b5"}
    assert stubs == {"P:b4"}


def test_member_hit_without_anchor_hit_and_alt_chunk(db):
    gt = [
        item("a", gold_block_id="P:b2", excerpt_block_id="P:b3", gold_chunk_id="P:c1"),
        item("b", gold_block_id="P:b0", gold_chunk_id="P:c0", alternative_gold_chunk_ids=["P:c1"]),
        item("c", gold_block_id="P:b0", gold_chunk_id="P:c0"),
    ]
    rows = [
        row("a", ["P"], ["P:b4"]),  # wrong chunk: miss both
        row("b", ["P"], ["P:b2"]),  # alt chunk: member only
        row("c", ["P"], ["P:b1"]),  # b1 not an anchor, no excerpt: miss
    ]
    t = run(gt, rows, db)["per_dimension"]["d"]
    assert (t["anchor_hit"]["hits"], t["member_hit"]["hits"], t["anchor_hit"]["n"]) == (0, 1, 3)
    gt = [item("a", gold_block_id="P:b2", excerpt_block_id="P:b3", gold_chunk_id="P:c1")]
    t = run(gt, [row("a", ["P"], ["P:b0", "P:b2"])], db)["per_dimension"]["d"]
    assert t["anchor_hit"]["hits"] == 1  # anchor == gold_block_id at rank 2
    gt = [item("a", gold_block_id="P:b3", excerpt_block_id="P:b3", gold_chunk_id="P:c1")]
    t = run(gt, [row("a", ["P"], ["P:b2"])], db)["per_dimension"]["d"]
    assert (t["anchor_hit"]["hits"], t["member_hit"]["hits"], t["member_p1"]["hits"]) == (0, 1, 1)


def test_stub_rank1_and_slots(db):
    res = run(
        [item("a"), item("b")],
        [row("a", ["P", "Q"], ["P:b4", "Q:b0"]), row("b", ["Q"], ["Q:b0"])],
        db,
    )
    assert res["stub"]["rank1"] == {"hits": 1, "n": 2}
    assert res["stub"]["topk_slots"] == {"hits": 1, "n": 3}


def test_authority_and_edition(db):
    gt = [
        item("a", commentary_paper_ids=["C"]),
        item("b", commentary_paper_ids=["C"]),
        item("c", other_edition_paper_ids=["E"]),
    ]
    rows = [row("a", ["C", "P"], []), row("b", ["P", "C"], []), row("c", ["X"], [])]
    res = run(gt, rows, db)
    assert res["authority_commentary_outranks_gold"] == {"hits": 1, "n": 2}
    assert res["edition_other_outranks_gold"] == {"hits": 0, "n": 1}


def test_cross_document_and_absent_excluded_from_recall(db):
    gt = [
        item("a", additional_gold_paper_ids=["Q"]),
        item("b", additional_gold_paper_ids=["Q"]),
        item("z", tests="absent", nearest_distractor_paper_id="D"),
    ]
    rows = [row("a", ["P", "Q"], []), row("b", ["P"], []), row("z", ["D"], [], gold=(), score=0.5)]
    res = run(gt, rows, db)
    assert res["cross_document"]["all_gold_in_topk"] == {"hits": 1, "n": 2}
    assert res["cross_document"]["any_gold_in_topk"] == {"hits": 2, "n": 2}
    assert res["per_dimension"]["d"]["n"] == 2  # absent not counted
    ab = res["absent_arm"]
    assert ab["n_absent"] == 1 and ab["top_score_absent"]["max"] == 0.5
    assert ab["top_score_answerable"]["n"] == 2
    assert ab["nearest_distractor_at_rank1"] == {"hits": 1, "n": 1}


def test_focus_contamination(db, tmp_path):
    lab = tmp_path / "l.tsv"
    lab.write_text("P\ton\tr\nO\toff\tr\nB\tborderline\tr\nO2\toff\tr\n")
    labels = load_labels(lab)
    gt = [
        item("a", "collision", distractor_paper_ids=["O"]),
        item("b", "collision", distractor_paper_ids=["O"]),
        item("l", "offtopic-legit", causal_lookalike_paper_ids=["P"]),
    ]
    rows = [
        row("a", ["O", "P", "B", "X"], []),
        row("b", ["P", "X", "X", "X"], []),
        row("l", ["P", "O2"], [], gold=("O2",)),
    ]
    f = run(gt, rows, db, labels=labels)["focus"]
    g = f["on_gold_answerable"]
    assert g["n"] == 2
    assert g["mean_off_share_topk"] == pytest.approx((0.25 + 0.0) / 2)
    assert g["off_at_rank1"] == {"hits": 1, "n": 2}
    assert g["distractor_outranks_gold"] == {"hits": 1, "n": 2}
    assert f["by_dimension"]["collision"]["n"] == 2
    assert f["offtopic_legit_lookalike_outranks_gold"] == {"hits": 1, "n": 1}
    assert f["chance_baseline_off_share"] == {"hits": 2, "n": 4}


def test_unknown_question_id_fails_loudly():
    with pytest.raises(ValueError, match="not in ground truth"):
        join_ground_truth({"questions": [{"question_id": "nope"}]}, {})


def test_fmt():
    assert fmt({"hits": 1, "n": 4}) == "1/4 = 0.250"
    assert fmt({"hits": 0, "n": 0}) == "0/0 = n/a"


def test_cli_roundtrip(db, tmp_path, capsys):
    gt = tmp_path / "gt.json"
    gt.write_text(
        json.dumps({"ground_truth": [item("a", gold_block_id="P:b0", gold_chunk_id="P:c0")]})
    )
    rep = tmp_path / "r.json"
    rep.write_text(json.dumps({"questions": [row("a", ["P"], ["P:b0"])]}))
    out = tmp_path / "o.json"
    assert main(["--ground-truth", str(gt), "--db", str(db), "--json-out", str(out), str(rep)]) == 0
    assert "anchor hit@k 1/1 = 1.000" in capsys.readouterr().out
    assert json.loads(out.read_text())[str(rep)]["per_dimension"]["d"]["member_p1"]["hits"] == 1
