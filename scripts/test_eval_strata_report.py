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


# ---------------------------------------------------------------------------------------------
# Independent review (EV-8 acceptance): a hand-computed end-to-end example, run through the CLI.
# Every expected number below was worked out BY HAND from the tables in this comment, before the
# script was run on it.  k = 3.
#
# DB.  P: blocks P:b0..b7 (idx 0..7); chunks c0@b0 (members b0,b1,b2), c1@b3 (b3,b4),
#      c2@b5 (b5,b6,b7; EMPTY body = stub).  Q: blocks b0..b3; chunks c0@b0 (b0,b1),
#      c1@b2 (b2,b3), c2@b2 (shared anchor with c1; c2 is a stub but c1 is not).
#      R: blocks b0,b1; chunk c0@b0 (stub).        Stub anchors = {P:b5, R:b0} (Q:b2 is not
#      a stub: a shared anchor is a stub only if ALL its chunks are).
#
# Rows (retrieved papers / anchor blocks, in rank order; only the first 3 count):
#  g1 fact       gold P blk P:b3 chunk c1 exc P:b4     [Q,P,P]   [Q:b0,P:b0,P:b3]  top 1
#  g2 fact       gold P blk P:b0 chunk c0 alt [c2]     [P,P,P]   [P:b5,P:b3,P:b0]  top 2
#  g3 fact       gold P blk P:b3 chunk c1 exc P:b4     [P,P]     [P:b0,P:b5]       top 3
#                commentary [C]
#  g4 span       gold Q blk Q:b0 chunk c0 exc Q:b3     [Q]       [Q:b2]            top 4
#  g5 span       gold Q+R, NO gold_block               [R,X,Q]   [R:b0,X:b9,Q:b0]  top 5
#  g6 span       gold Q+R blk Q:b2 exc Q:b2            [X,X,X,Q] [X:b0,X:b1,X:b2,Q:b2] top 6
#  g7 authority  gold P blk P:b3 chunk c1, comm [C]    [C,P,X]   [C:b0,P:b3,X:b0]  top 7
#  g8 edition    gold P blk P:b3 chunk c1, other [E]   [P,E]     [P:b3,E:b0]       top 8
#  g9 offtopic-legit gold O, lookalike [P]             [P,O]     [P:b0,O:b0]       top 9
#  a1 absent distractor D                              [D,P]     [D:b0,P:b0]       top 2
#  a2 absent distractor D2                             [P]       [P:b0]            top 6
#  g10 is in the GT file but not in the report.
# ---------------------------------------------------------------------------------------------
def _hand_example(tmp_path):
    import sqlite3

    path = tmp_path / "hand.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE chunks(chunk_id, paper_id, text, anchor_json);"
        "CREATE TABLE blocks(block_id, paper_id, idx, text);"
    )
    for pid, n in (("P", 8), ("Q", 4), ("R", 2)):
        for i in range(n):
            con.execute("INSERT INTO blocks VALUES(?,?,?,?)", (f"{pid}:b{i}", pid, i, "t"))
    for cid, pid, anchor, body in [
        ("P:c0", "P", "P:b0", BODY), ("P:c1", "P", "P:b3", BODY), ("P:c2", "P", "P:b5", ""),
        ("Q:c0", "Q", "Q:b0", BODY), ("Q:c1", "Q", "Q:b2", BODY), ("Q:c2", "Q", "Q:b2", ""),
        ("R:c0", "R", "R:b0", ""),
    ]:
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?)",
            (cid, pid, f"title\nsec\n\n{body}", json.dumps({"block_id": anchor})),
        )
    con.commit()
    con.close()
    return path


def _hand_files(tmp_path):
    items = [
        item("g1", "fact", gold_block_id="P:b3", gold_chunk_id="P:c1", excerpt_block_id="P:b4",
             distractor_paper_ids=["X"]),
        item("g2", "fact", gold_block_id="P:b0", gold_chunk_id="P:c0",
             alternative_gold_chunk_ids=["P:c2"], excerpt_block_id="P:b1"),
        item("g3", "fact", gold_block_id="P:b3", gold_chunk_id="P:c1", excerpt_block_id="P:b4",
             commentary_paper_ids=["C"]),
        item("g4", "span", gold_block_id="Q:b0", gold_chunk_id="Q:c0", excerpt_block_id="Q:b3"),
        item("g5", "span", additional_gold_paper_ids=["R"], distractor_paper_ids=["X"]),
        item("g6", "span", gold_block_id="Q:b2", excerpt_block_id="Q:b2",
             additional_gold_paper_ids=["R"], distractor_paper_ids=["X"]),
        item("g7", "authority", gold_block_id="P:b3", gold_chunk_id="P:c1",
             commentary_paper_ids=["C"]),
        item("g8", "edition", gold_block_id="P:b3", gold_chunk_id="P:c1",
             other_edition_paper_ids=["E"]),
        item("g9", "offtopic-legit", causal_lookalike_paper_ids=["P"]),
        item("a1", "absent-d", tests="absent", nearest_distractor_paper_id="D"),
        item("a2", "absent-d", tests="absent", nearest_distractor_paper_id="D2"),
        item("g10", "fact", gold_block_id="P:b0"),  # not in the report
    ]
    rows = [
        row("g1", ["Q", "P", "P"], ["Q:b0", "P:b0", "P:b3"], gold=("P",), score=1),
        row("g2", ["P", "P", "P"], ["P:b5", "P:b3", "P:b0"], gold=("P",), score=2),
        row("g3", ["P", "P"], ["P:b0", "P:b5"], gold=("P",), score=3),
        row("g4", ["Q"], ["Q:b2"], gold=("Q",), score=4),
        row("g5", ["R", "X", "Q"], ["R:b0", "X:b9", "Q:b0"], gold=("Q", "R"), score=5),
        row("g6", ["X", "X", "X", "Q"], ["X:b0", "X:b1", "X:b2", "Q:b2"], gold=("Q", "R"), score=6),
        row("g7", ["C", "P", "X"], ["C:b0", "P:b3", "X:b0"], gold=("P",), score=7),
        row("g8", ["P", "E"], ["P:b3", "E:b0"], gold=("P",), score=8),
        row("g9", ["P", "O"], ["P:b0", "O:b0"], gold=("O",), score=9),
        row("a1", ["D", "P"], ["D:b0", "P:b0"], gold=(), score=2),
        row("a2", ["P"], ["P:b0"], gold=(), score=6),
    ]
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps({"ground_truth": items}))
    rep = tmp_path / "rep.json"
    rep.write_text(json.dumps({"questions": rows}))
    lab = tmp_path / "labels.tsv"
    lab.write_text(
        "P\ton\tr\nQ\ton\tr\nR\ton\tr\nX\toff\tr\nC\toff\tr\nE\tborderline\tr\nD\toff\tr\nO\toff\tr\n"
    )
    return gt, rep, lab


def test_hand_computed_example_reproduces_every_number(tmp_path):
    db = _hand_example(tmp_path)
    gt, rep, lab = _hand_files(tmp_path)
    out = tmp_path / "o.json"
    assert main(["--ground-truth", str(gt), "--db", str(db), "--topic-labels", str(lab),
                 "--k", "3", "--json-out", str(out), str(rep)]) == 0
    res = json.loads(out.read_text())[str(rep)]

    assert res["n_questions"] == 11 and res["gt_items_not_in_report"] == 1

    def r(h, n):
        return {"hits": h, "n": n}

    pd = res["per_dimension"]
    # fact (g1 g2 g3): paper ranks 2,1,1 -> R 3/3, P@1 2/3. anchor ranks 3,3,miss -> 2/3, P@1 0/3.
    #   member: g1 anchor==gold (3); g2 P:b5 anchors alt chunk c2 (rank 1); g3 miss -> 2/3, P@1 1/3.
    assert pd["fact"] == {"n": 3, "paper_recall": r(3, 3), "paper_p1": r(2, 3),
                          "anchor_hit": r(2, 3), "anchor_p1": r(0, 3),
                          "member_hit": r(2, 3), "member_p1": r(1, 3)}
    # span (g4 g5 g6): paper ranks 1,1,miss(Q is 4th, beyond k) -> 2/3, P@1 2/3.
    #   passage-scored = g4,g6 only (g5 has no gold_block). anchor: g4 Q:b2!=Q:b0, g6 Q:b2 is 4th
    #   -> 0/2. member: g4 excerpt Q:b3 in members(Q:b2) -> rank 1; g6 miss -> 1/2, P@1 1/2.
    assert pd["span"] == {"n": 3, "paper_recall": r(2, 3), "paper_p1": r(2, 3),
                          "anchor_hit": r(0, 2), "anchor_p1": r(0, 2),
                          "member_hit": r(1, 2), "member_p1": r(1, 2)}
    # authority (g7): paper rank 2; anchor P:b3 at rank 2; member same.
    assert pd["authority"] == {"n": 1, "paper_recall": r(1, 1), "paper_p1": r(0, 1),
                               "anchor_hit": r(1, 1), "anchor_p1": r(0, 1),
                               "member_hit": r(1, 1), "member_p1": r(0, 1)}
    # edition (g8): everything at rank 1.
    assert pd["edition"] == {"n": 1, "paper_recall": r(1, 1), "paper_p1": r(1, 1),
                             "anchor_hit": r(1, 1), "anchor_p1": r(1, 1),
                             "member_hit": r(1, 1), "member_p1": r(1, 1)}
    # offtopic-legit (g9): paper rank 2 (O); no gold_block -> passage n = 0.
    assert pd["offtopic-legit"] == {"n": 1, "paper_recall": r(1, 1), "paper_p1": r(0, 1),
                                    "anchor_hit": r(0, 0), "anchor_p1": r(0, 0),
                                    "member_hit": r(0, 0), "member_p1": r(0, 0)}
    assert "absent-d" not in pd  # absent items never enter the answerable table

    # stub: rank-1 anchors over 11 rows: g2 P:b5 and g5 R:b0 -> 2/11.  top-3 slots: 3+3+2+1+3+3
    #   +3+2+2+2+1 = 25 slots; stubs: g2 P:b5, g3 P:b5, g5 R:b0 -> 3/25. (g6's 4th slot cut.)
    assert res["stub"] == {"rank1": r(2, 11), "topk_slots": r(3, 25)}
    # authority: items with commentary = g3 (C not retrieved -> not above gold), g7 (C rank 1 < 2).
    assert res["authority_commentary_outranks_gold"] == r(1, 2)
    # edition: g8 gold rank 1, E rank 2 -> not outranked.
    assert res["edition_other_outranks_gold"] == r(0, 1)
    # cross-document (answerable, >1 gold): g5 {Q,R} subset of top-3 {R,X,Q} yes; g6 top-3 {X} no.
    assert res["cross_document"] == {"all_gold_in_topk": r(1, 2), "any_gold_in_topk": r(1, 2)}
    # absent arm: absent scores [2, 6] -> min 2, median 4, max 6; answerable scores 1..9 -> median 5.
    ab = res["absent_arm"]
    assert ab["n_absent"] == 2
    assert ab["top_score_absent"] == {"n": 2, "min": 2, "median": 4, "max": 6}
    assert ab["top_score_answerable"] == {"n": 9, "min": 1, "median": 5, "max": 9}
    assert ab["nearest_distractor_at_rank1"] == r(1, 2)  # a1 yes, a2 (P rank 1, not D2) no

    f = res["focus"]
    # labels: off = X,C,D,O (4 of 8). on-gold answerable (gold all on): g1..g8 (g9 gold O is off).
    assert f["chance_baseline_off_share"] == r(4, 8)
    g = f["on_gold_answerable"]
    # off share of top-3 per row: g1 0, g2 0, g3 0, g4 0, g5 1/3 (X), g6 3/3, g7 2/3 (C,X), g8 0
    #   (E is borderline) -> sum 2.0 over 8 = 0.25.   off at rank 1: g6 (X), g7 (C) -> 2/8.
    #   distractor outranks gold (items with distractor_paper_ids g1,g5,g6): g1 X absent -> no;
    #   g5 X rank 2 vs gold rank 1 -> no; g6 X rank 1 vs gold beyond k -> yes -> 1/3.
    assert g["n"] == 8 and g["mean_off_share_topk"] == pytest.approx(0.25)
    assert g["off_at_rank1"] == r(2, 8) and g["distractor_outranks_gold"] == r(1, 3)
    bd = f["by_dimension"]
    assert bd["fact"]["n"] == 3 and bd["fact"]["mean_off_share_topk"] == pytest.approx(0.0)
    assert bd["fact"]["off_at_rank1"] == r(0, 3) and bd["fact"]["distractor_outranks_gold"] == r(0, 1)
    assert bd["span"]["n"] == 3 and bd["span"]["mean_off_share_topk"] == pytest.approx(4 / 9)
    assert bd["span"]["off_at_rank1"] == r(1, 3) and bd["span"]["distractor_outranks_gold"] == r(1, 2)
    assert bd["authority"]["mean_off_share_topk"] == pytest.approx(2 / 3)
    assert bd["authority"]["off_at_rank1"] == r(1, 1)
    assert bd["edition"]["n"] == 1 and bd["edition"]["mean_off_share_topk"] == pytest.approx(0.0)
    # offtopic-legit g9: lookalike P at rank 1, gold O at rank 2 -> outranks.
    assert f["offtopic_legit_lookalike_outranks_gold"] == r(1, 1)


def test_errored_rows_and_invalid_runs_are_surfaced_not_silently_scored_as_misses(db, capsys):
    """Review finding: a report row that errored (empty retrieved lists) was scored as an ordinary
    miss in every table with no mention in the strata output, and an EV-10 `run_valid: false`
    report was analysed as if valid."""
    gt = {"a": item("a", gold_block_id="P:b0"), "b": item("b", gold_block_id="P:b0")}
    bad = row("b", [], [])
    bad["error"] = "gpu lock x not acquired within 300s"
    report = {"run_valid": False, "questions": [row("a", ["P"], ["P:b0"]), bad]}
    res = analyze(report, gt, 10, *build_db_maps(db, {"P"}))
    assert res["n_errored_rows"] == 1
    assert res["run_valid"] is False
    from scripts.eval_strata_report import render

    text = render("r.json", res, 10)
    assert "WARNING" in text and "INVALID" in text
