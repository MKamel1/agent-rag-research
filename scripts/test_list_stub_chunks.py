"""Tests for scripts/list_stub_chunks.py (SQLite only, no network/GPU)."""

import json
import sqlite3

from scripts.list_stub_chunks import ab_facts, rank_shares, stub_chunks


def _db(tmp_path, bodies):
    path = tmp_path / "p.db"
    con = sqlite3.connect(path)
    con.execute("create table chunks (chunk_id, paper_id, text, anchor_json)")
    for i, (paper, body) in enumerate(bodies):
        con.execute(
            "insert into chunks values (?,?,?,?)",
            (
                f"{paper}:c{i}",
                paper,
                f"T\nSec\n\n{body}",
                json.dumps({"block_id": f"{paper}:b{i}"}),
            ),
        )
    con.commit()
    con.close()
    return str(path)


def test_stub_chunks_lists_ids_and_anchor_blocks(tmp_path):
    db = _db(
        tmp_path,
        [
            ("a", ""),
            ("a", "3.159"),
            ("a", "computer program used in the development of an item"),
            ("b", "x" * 100),
        ],
    )
    assert stub_chunks(db) == [("a:c0", "a:b0", "a"), ("a:c1", "a:b1", "a")]


def test_stub_chunks_db_is_opened_read_only(tmp_path):
    db = _db(tmp_path, [("a", "")])
    before = open(db, "rb").read()
    stub_chunks(db)
    assert open(db, "rb").read() == before


def _q(qid, blocks, rank, scored=True, doc_type="paper"):
    return {
        "question_id": qid,
        "question_type": "t",
        "doc_type": doc_type,
        "error": None,
        "retrieved_block_ids": blocks,
        "paper_level": {"hit": rank is not None, "rank": rank},
        "passage_level": {"scored": scored, "hit": rank is not None, "rank": rank},
    }


def test_rank_shares_and_ab_facts():
    stubs = {"s1"}
    base = {"questions": [_q("q1", ["s1", "g1"], 2), _q("q2", ["g2", "x"], 1)]}
    drop = {"questions": [_q("q1", ["g1", "x"], 1), _q("q2", ["g2", "x"], 1)]}
    assert rank_shares(base, stubs)["stub_at_rank1_share"] == 0.5
    facts = ab_facts(base, drop, stubs)
    assert facts["criterion_1_stub_at_rank1_positive"] and facts["criterion_3_p1_or_hit_improves"]
    assert (
        facts["passage_p_at_1_change"] == 1 and facts["criterion_2_no_stratum_drops_more_than_one"]
    )


def test_ab_facts_flags_a_two_question_regression():
    base = {"questions": [_q("q1", ["a"], 1), _q("q2", ["b"], 1)]}
    drop = {"questions": [_q("q1", ["a"], None), _q("q2", ["b"], None)]}
    assert not ab_facts(base, drop, set())["criterion_2_no_stratum_drops_more_than_one"]
