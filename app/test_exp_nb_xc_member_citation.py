"""Unit tests for NB-XC's member-citation instrument (app/exp_nb_xc_member_citation.py).

Offline by construction: the "corpus" is a synthetic papers.db in tmp_path using the exact
columns the instrument reads (blocks: block_id/paper_id/idx/type/section_path/text;
chunks: chunk_id/paper_id/text/anchor_json/section_path). No GPU, no network, no real data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.exp_nb_xc_member_citation import (
    GateError,
    PaperGeometry,
    analyze_config,
    decompose_joint,
    member_lookup,
    paper_prefix,
)

# --- synthetic corpus --------------------------------------------------------


def _anchor_json(paper: str, block: str, idx: int) -> str:
    return json.dumps(
        {
            "paper_id": paper,
            "block_id": f"{paper}:{block}",
            "page": 0,
            "bbox": [0.0, 0.0, 1.0, 1.0],
            "snippet": f"snip {block}",
            "section_path": "sec",
        }
    )


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "papers.db")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE blocks (block_id TEXT PRIMARY KEY, paper_id TEXT, idx INT, type TEXT,"
        " section_path TEXT, text TEXT)"
    )
    con.execute(
        "CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, paper_id TEXT, text TEXT,"
        " anchor_json TEXT, section_path TEXT, parent_id TEXT)"
    )

    def add_paper(paper: str, n_blocks: int, anchors: list[int]) -> None:
        for i in range(n_blocks):
            con.execute(
                "INSERT INTO blocks VALUES (?,?,?,?,?,?)",
                (f"{paper}:b{i}", paper, i, "prose", "sec", f"text {paper} {i}"),
            )
        # Chunks partition block space by their anchors: consecutive suffixes required by G3.
        for n, a in enumerate(anchors):
            nxt = anchors[n + 1] if n + 1 < len(anchors) else n_blocks
            con.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                (
                    f"{paper}:c{n}",
                    paper,
                    f"{paper} body {a}..{nxt - 1}",
                    _anchor_json(paper, f"b{a}", a),
                    "sec",
                    f"{paper}:b{a}",
                ),
            )
            assert nxt > a  # partition sanity of the fixture itself

    add_paper("p", 6, [0, 2, 4])  # spans: c0=[0,2) c1=[2,4) c2=[4,6)
    add_paper("local:h", 4, [0, 2])  # twin identity, same shape
    con.commit()
    yield con
    con.close()


# --- units -------------------------------------------------------------------


def test_paper_prefix_strips_only_final_block_component() -> None:
    assert paper_prefix("2208.12833:b188") == "2208.12833"
    assert paper_prefix("local:94bdd3d09df1:b186") == "local:94bdd3d09df1"


def test_membership_inside_rank1_chunk(conn: sqlite3.Connection) -> None:
    geo = PaperGeometry(conn, "p")
    hit = member_lookup({}, conn, lambda c, cache, p: geo, "p:b3", ["p:b2"])
    assert hit is not None
    assert hit.serving_position == 0
    assert hit.at_rank_1
    assert (hit.span_start, hit.span_end) == (2, 4)


def test_gold_elsewhere_in_chunk_but_wrong_serving_anchor(conn: sqlite3.Connection) -> None:
    """Gold sits in c1's span, but only c2's anchor was served -- no honest claim."""
    geo = PaperGeometry(conn, "p")
    assert member_lookup({}, conn, lambda c, cache, p: geo, "p:b3", ["p:b4"]) is None


def test_overlap_block_is_not_a_member(conn: sqlite3.Connection) -> None:
    """The contract says a split sub-chunk's prepended overlap changes text only -- so a gold
    block from the PREVIOUS sub-chunk must not be claimed as this chunk's member."""
    geo = PaperGeometry(conn, "p")
    assert member_lookup({}, conn, lambda c, cache, p: geo, "p:b1", ["p:b2"]) is None


def test_dual_identity_never_vouches_cross_prefix(conn: sqlite3.Connection) -> None:
    """A `local:<hash>` twin anchor never vouches for a canonical gold block."""
    geo = PaperGeometry(conn, "p")
    assert member_lookup({}, conn, lambda c, cache, p: geo, "p:b0", ["local:h:b0"]) is None


def test_baseline_hit_always_has_membership(conn: sqlite3.Connection) -> None:
    """Monotonicity premise: an anchor is a member of its own chunk."""
    geo = PaperGeometry(conn, "p")
    hit = member_lookup({}, conn, lambda c, cache, p: geo, "p:b4", ["p:b0", "p:b4"])
    assert hit is not None and hit.serving_position == 1


def test_geometry_rejects_duplicate_anchor(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO chunks VALUES ('p:cX','p','dup',?, 'sec','p:b0')",
        (_anchor_json("p", "b0", 0),),
    )
    with pytest.raises(GateError, match="anchors two chunks"):
        PaperGeometry(conn, "p")


# --- config-level analysis over fabricated records ---------------------------


def _record(qid: str, gold: str, retrieved: list[str], hit: bool, rank: int | None,
            papl_rank: int | None, papl_hit: bool) -> dict:
    return {
        "question_id": qid,
        "passage_level": {"scored": True, "hit": hit, "rank": rank},
        "paper_level": {"hit": papl_hit, "rank": papl_rank},
        "gold_block_id": gold,
        "retrieved_block_ids": retrieved,
        "retrieved_paper_ids": [],
        "gold_paper_ids": [paper_prefix(gold)],
    }


def _write_fixture(data_dir: Path, fixture: str, mode: str, questions: list[dict]) -> None:
    payload = {
        "scoring_rule": "test",
        "k": 10,
        "n_questions": len(questions),
        "questions": questions,
    }
    (data_dir / f"{fixture}_{mode}.json").write_text(json.dumps(payload))


def test_analyze_counts_conversion_and_enforces_gates(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    records = [
        # Converts: baseline miss, gold inside rank-1 served chunk as non-anchor member.
        _record("q1", "p:b3", ["p:b2"], False, None, 1, True),
        # Already-hit C1 item: stays a hit, never counted as converted.
        _record("q2", "p:b4", ["p:b0", "p:b4"], True, 2, 1, True),
        # Baseline miss with NO membership anywhere: not converted.
        _record("q3", "p:b1", ["p:b4"], False, None, 1, False),
    ]
    _write_fixture(tmp_path, "fx", "m", records)
    result = analyze_config(
        conn, {}, {}, tmp_path, "fx", "m",
        watch_items={"q1": "expect conversion"},
    )
    assert result["n_scored"] == 3
    assert result["n_baseline_hits"] == 1
    assert result["n_converted_anywhere_top_k"] == 1
    assert result["n_converted_at_rank_1"] == 1
    conv = result["conversions"][0]
    assert conv["question_id"] == "q1"
    assert conv["joint_bucket"] == "C2"
    assert result["watch_items"]["q1"].startswith("q1: baseline_hit=False")


def test_analyze_raises_on_g1_record_fidelity_violation(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    """Stored pl.hit contradicts the raw retrieved ids -- refuse to emit."""
    bad = _record("q1", "p:b3", ["p:b2"], True, None, 1, True)  # hit=True but b3 not served
    _write_fixture(tmp_path, "fx", "m", [bad])
    with pytest.raises(GateError, match="G1"):
        analyze_config(conn, {}, {}, tmp_path, "fx", "m", {})


def test_decompose_joint_matches_prec1_ordering() -> None:
    def rec(pl_hit: bool, pl_rank: int | None, papl_rank: int | None) -> dict:
        return {
            "passage_level": {"scored": True, "hit": pl_hit, "rank": pl_rank},
            "paper_level": {"rank": papl_rank, "hit": papl_rank == 1 or papl_rank == 3},
        }

    assert decompose_joint(rec(True, 1, 1)) == "A"
    assert decompose_joint(rec(False, None, 1)) == "C2"
    assert decompose_joint(rec(False, None, 3)) == "D"
    assert decompose_joint(rec(False, None, None)) == "E"
    unscored = {
        "passage_level": {"scored": False, "hit": False, "rank": None},
        "paper_level": {"rank": 1, "hit": True},
    }
    assert decompose_joint(unscored) is None
