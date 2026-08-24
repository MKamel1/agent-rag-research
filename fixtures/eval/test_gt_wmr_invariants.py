"""Mechanical invariants for `gt_wmr.json` (the Waymo-priority GT built under the frozen
2026-08-23 benchmark protocol).

Two tiers, mirroring the sibling suites in this directory:
  1. Structural: counts, id uniqueness, per-type grounding shape, absence items carrying live
     search logs, the vision item carrying a leak-checked note and scope tag.
  2. Live-DB: every excerpt is a normalized substring of its gold chunk's stored text; gold
     chunk/block ids resolve and agree with the recorded paper; the vision item's block/page
     agree. Auto-skips when the gitignored corpus DB is not present.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
GT_PATH = FIXTURE_DIR / "gt_wmr.json"

MIN_ITEMS = 55
QUESTION_ID_RE = re.compile(r"^Q-WMR-\d{3}$")
VALID_TESTS = {"answerable", "absent"}
VALID_DIMENSIONS = {
    "single-passage factual lookup", "multi-paper synthesis", "numeric/quantitative",
    "methodological questions", "negation and scope", "temporal/versioned",
}
MIN_ABSENT = 10
MIN_SYNTHESIS = 4

_MIN_REAL_DB_BYTES = 1_000_000


def _find_real_db_path() -> Path | None:
    for ancestor in (FIXTURE_DIR, *FIXTURE_DIR.parents):
        candidate = ancestor / "waymo" / "data" / "papers.db"
        if candidate.exists() and candidate.stat().st_size >= _MIN_REAL_DB_BYTES:
            return candidate
    return None


DB_PATH = _find_real_db_path()


def _load():
    return json.loads(GT_PATH.read_text())


def test_structural_invariants():
    data = _load()
    gt = data["ground_truth"]
    meta = data["_metadata"]
    assert len(gt) >= MIN_ITEMS, f"only {len(gt)} items"
    seen = set()
    n_absent = n_synth = 0
    for item in gt:
        qid = item["question_id"]
        assert QUESTION_ID_RE.match(qid), f"{qid}: bad id"
        assert qid not in seen, f"{qid}: duplicate"
        seen.add(qid)
        assert item["tests"] in VALID_TESTS, f"{qid}: bad tests"
        assert item.get("dimension") in VALID_DIMENSIONS, f"{qid}: bad dimension {item.get('dimension')!r}"
        assert str(item.get("question_text", "")).strip(), f"{qid}: empty question_text"
        if item["tests"] == "absent":
            n_absent += 1
            leaked = {"answer_text", "source_paper_id", "supporting_passages"} & set(item)
            assert not leaked, f"{qid}: absent item leaks {leaked}"
            searches = item.get("absence_search", {}).get("queries", [])
            assert searches, f"{qid}: no recorded absence queries"
            continue
        assert str(item.get("answer_text", "")).strip(), f"{qid}: missing answer_text"
        if "supporting_passages" in item:
            n_synth += 1
            passages = item["supporting_passages"]
            assert len(passages) >= 2 and len({p["paper_id"] for p in passages}) >= 2, (
                f"{qid}: synthesis needs >=2 passages across >=2 papers"
            )
        elif item.get("vision_derived"):
            assert item.get("gold_block_id") and item.get("page") is not None, (
                f"{qid}: vision item needs block+page"
            )
            assert "leak" in item.get("vision_note", "").lower(), (
                f"{qid}: vision_note must record the leak check"
            )
        else:
            for f in ("source_paper_id", "source_paper_title", "gold_chunk_id",
                      "gold_block_id", "passage_excerpt"):
                assert str(item.get(f, "")).strip(), f"{qid}: missing {f}"
    assert n_absent >= MIN_ABSENT, f"only {n_absent} absent items (protocol requires >= {MIN_ABSENT})"
    assert n_synth >= MIN_SYNTHESIS, f"only {n_synth} synthesis items"
    assert isinstance(meta.get("corrections"), list), "metadata.corrections missing"


@pytest.mark.skipif(DB_PATH is None, reason="real Waymo corpus DB not found near this checkout")
def test_grounding_resolves_against_corpus_db():
    gt = _load()["ground_truth"]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        titles = dict(conn.execute("SELECT paper_id, title FROM papers"))
        chunks = {cid: (pid, sec, txt, json.loads(a) if a else {})
                  for cid, pid, sec, txt, a in conn.execute(
                      "SELECT chunk_id, paper_id, section_path, text, anchor_json FROM chunks")}
        blocks = dict(conn.execute("SELECT block_id, page FROM blocks"))
    finally:
        conn.close()
    checked = 0
    for item in gt:
        qid = item["question_id"]
        if item["tests"] == "absent":
            continue
        if "supporting_passages" in item:
            for p in item["supporting_passages"]:
                pid, sec, txt, anc = chunks[p["gold_chunk_id"]]
                assert pid == p["paper_id"], f"{qid}: supporting chunk/paper mismatch"
                assert titles[pid] == p["paper_title"], f"{qid}: supporting title mismatch"
                assert anc.get("block_id") == p["gold_block_id"], f"{qid}: supporting block mismatch"
                assert " ".join(p["passage_excerpt"].split()) in " ".join((txt or "").split()), (
                    f"{qid}: supporting excerpt not verbatim in {p['gold_chunk_id']}"
                )
                checked += 1
        elif item.get("vision_derived"):
            assert item["source_paper_id"] in titles, f"{qid}: paper missing"
            assert blocks.get(item["gold_block_id"]) == item["page"], (
                f"{qid}: vision block/page mismatch"
            )
        else:
            pid, sec, txt, anc = chunks[item["gold_chunk_id"]]
            assert pid == item["source_paper_id"], f"{qid}: chunk/paper mismatch"
            assert titles[pid] == item["source_paper_title"], f"{qid}: title mismatch"
            assert anc.get("block_id") == item["gold_block_id"], f"{qid}: block mismatch"
            assert " ".join(item["passage_excerpt"].split()) in " ".join((txt or "").split()), (
                f"{qid}: excerpt not verbatim in {item['gold_chunk_id']}"
            )
            assert (item.get("section_path") or "") == (sec or ""), f"{qid}: section_path drift"
            checked += 1
    print(f"all gt_wmr groundings resolve against the live corpus DB ({checked} checks)")


if __name__ == "__main__":
    test_structural_invariants()
    if DB_PATH is not None:
        test_grounding_resolves_against_corpus_db()
