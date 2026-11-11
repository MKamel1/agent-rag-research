"""Tests for scripts/bm25_floor.py on a 3-chunk toy corpus with hand-computed BM25 scores."""

import json
import sqlite3

import pytest

from scripts.bm25_floor import Bm25Index, run_floor, tokenize
from scripts.eval_strata_report import analyze, build_db_maps

# Toy corpus (N=3). Standard tokens (header included, stopwords dropped):
#   c1 "alpha sec cat dog cat" |d|=5, c2 "beta sec dog bird" |d|=4,
#   c3 "gamma sec fish" |d|=3, avgdl=4.
# idf(cat)=ln(1+2.5/1.5)=0.98083, idf(dog)=ln(1+1.5/2.5)=0.47000, idf(alpha)=idf(cat);
# k1=1.2, b=0.75.
#   score(c1 | "cat dog") = 0.98083*2*2.2/(2+1.2*(.25+.75*5/4))
#                          + 0.47*1*2.2/(1+1.2*(.25+.75*5/4)) = 1.6864
#   score(c2 | "cat dog") = 0.47*2.2/(1+1.2*(.25+.75*4/4)) = 0.4700
# Body-only: |d| = 3, 2, 1, avgdl=2 -> c1 = 1.5726, c2 = 0.4700;
# "alpha" (a title-only word) then matches nothing.
CHUNKS = [
    ("c1", "p1", "Alpha\nsec\n\ncat dog cat", "b1"),
    ("c2", "p2", "Beta\nsec\n\ndog bird", "b2"),
    ("c3", "p3", "Gamma\nsec\n\nfish", "b3"),
]


@pytest.fixture
def toy(tmp_path):
    db = tmp_path / "papers.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE chunks (chunk_id TEXT, paper_id TEXT, text TEXT, anchor_json TEXT)")
    con.execute("CREATE TABLE blocks (block_id TEXT, paper_id TEXT, idx INTEGER)")
    for i, (cid, pid, text, block) in enumerate(CHUNKS):
        con.execute(
            "INSERT INTO chunks VALUES (?,?,?,?)", (cid, pid, text, json.dumps({"block_id": block}))
        )
        con.execute("INSERT INTO blocks VALUES (?,?,?)", (block, pid, i))
    con.commit()
    con.close()
    items = [
        {
            "question_id": "q1",
            "question_text": "the alpha cat dog bird",
            "tests": "answerable",
            "dimension": "d",
            "source_paper_id": "p1",
            "gold_block_id": "b1",
            "source_paper_title": "Alpha",
        },
        {
            "question_id": "q2",
            "question_text": "alpha",
            "tests": "answerable",
            "dimension": "d",
            "source_paper_id": "p1",
            "gold_block_id": "b1",
            "source_paper_title": "Other Words Here",
        },
        {
            "question_id": "q3",
            "question_text": "cat dog",
            "tests": "absent",
            "dimension": "absent",
            "source_paper_id": None,
            "gold_block_id": None,
        },
    ]
    gt = tmp_path / "gt.json"
    gt.write_text(json.dumps({"_metadata": {}, "ground_truth": items}))
    return db, gt


def _index(body_only=False):
    from rag.retriever import body_of

    idx = Bm25Index({"cat", "dog", "alpha"})
    for cid, pid, text, _ in CHUNKS:
        idx.add(cid, pid, body_of(text) if body_only else text)
    return idx


def test_tokenize_lowercases_splits_and_drops_stopwords():
    assert tokenize("The Cat's eﬀect, ISO-26262") == ["cat", "s", "e", "ect", "iso", "26262"]


def test_hand_computed_scores_and_ranking():
    hits = _index().search("cat dog", 10)
    assert [h[0] for h in hits] == ["c1", "c2"]  # c3 matches nothing
    assert [round(h[2], 4) for h in hits] == [1.6864, 0.4700]
    assert [round(h[2], 4) for h in _index().search("alpha", 10)] == [0.8898]


def test_body_only_differs_from_standard():
    hits = _index(body_only=True).search("cat dog", 10)
    assert [round(h[2], 4) for h in hits] == [1.5726, 0.4700]
    assert _index(body_only=True).search("alpha", 10) == []  # the title token is gone


def test_report_hits_ranks_and_absent_never_hit(toy):
    db, gt = toy
    rep = run_floor(gt, str(db), 10, "standard")
    rows = {r["question_id"]: r for r in rep["questions"]}
    assert rows["q1"]["retrieved_chunk_ids"] == ["c1", "c2"]
    assert rows["q1"]["retrieved_block_ids"] == ["b1", "b2"]
    assert rows["q1"]["retrieved_paper_ids"] == ["p1", "p2"]
    assert rows["q1"]["paper_level"] == {"hit": True, "rank": 1}
    assert rows["q1"]["passage_level"] == {"scored": True, "hit": True, "rank": 1}
    assert rows["q3"]["retrieved_chunk_ids"] == ["c1", "c2"]  # it retrieves, but...
    assert rows["q3"]["paper_level"]["hit"] is False  # ...an absent item has no gold: never a hit
    assert rows["q3"]["passage_level"]["scored"] is False
    assert rep["bm25_floor"]["n_chunks"] == 3 and rep["k"] == 10


def test_body_only_variant_loses_title_only_question(toy):
    db, gt = toy
    std = {r["question_id"]: r for r in run_floor(gt, str(db), 10, "standard")["questions"]}
    body = {r["question_id"]: r for r in run_floor(gt, str(db), 10, "body-only")["questions"]}
    assert std["q2"]["paper_level"]["hit"] and not body["q2"]["paper_level"]["hit"]


def test_title_ablated_drops_title_words_and_keeps_shape(toy):
    db, gt = toy
    rep = run_floor(gt, str(db), 10, "title-ablated")
    # q1 loses "alpha" (in its gold title); q2 (1 word) and the absent q3 are omitted by the helper
    assert [r["question_id"] for r in rep["questions"]] == ["q1"]
    assert rep["questions"][0]["retrieved_chunk_ids"] == ["c1", "c2"]


def test_output_feeds_eval_strata_report_unchanged(toy):
    db, gt = toy
    rep = run_floor(gt, str(db), 10, "standard")
    gt_items = {i["question_id"]: i for i in json.loads(gt.read_text())["ground_truth"]}
    maps = build_db_maps(db, {"p1", "p2", "p3"})
    res = analyze(rep, gt_items, 10, *maps)
    d = res["per_dimension"]["d"]
    assert d["n"] == 2 and d["paper_recall"] == {"hits": 2, "n": 2}
    assert d["anchor_hit"] == {"hits": 2, "n": 2}
    assert res["absent_arm"]["n_absent"] == 1


def test_database_is_opened_read_only(toy):
    db, _ = toy
    from scripts.bm25_floor import connect_ro

    with pytest.raises(sqlite3.OperationalError):
        connect_ro(str(db)).execute("DELETE FROM chunks")
