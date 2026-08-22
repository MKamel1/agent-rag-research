"""Mechanical invariants for `eval_ground_truth_waymo.json` / `eval_questions_blind_waymo.json`
(RI-M5: a grounded eval fixture for the second, Waymo AV-safety, corpus).

Follows the two established patterns already in this directory rather than inventing a third:
  1. The blind/ground-truth pairing and leak checks from `test_eval_fixture_invariants.py`
     (the 210-item causal-corpus set) -- id alignment, zero leaked fields in the blind file,
     question_type quota coverage.
  2. The optional live-DB cross-check tier from `test_eval_equation_slice_invariants.py` --
     confirming `source_paper_id`/`gold_block_id`/`gold_chunk_id` actually resolve in the real
     corpus DB and that `passage_excerpt` is a genuine substring of the resolved chunk's stored
     text. That DB is `waymo/data/papers.db`, gitignored and not checked out in CI (see
     `.gitignore`, `docs/PROJECT-STATUS.md` §1) -- this tier auto-skips when it isn't found on
     the machine running the test, instead of hard-failing every push.

This is a 15-item hand-picked seed set, not a 210-item parity set with the causal corpus -- see
the fixture's own `_metadata.seed_set_note`.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
GT_PATH = FIXTURE_DIR / "eval_ground_truth_waymo.json"
BLIND_PATH = FIXTURE_DIR / "eval_questions_blind_waymo.json"

TOTAL_ITEMS = 15
EXPECTED_TYPE_COUNTS = {
    "Result-Comprehension": 7,
    "Method-Comprehension": 4,
    "Contribution-Comprehension": 3,
    "Assumption-Comprehension": 1,
}
LEAKED_FIELDS = {
    "answer_text",
    "source_paper_id",
    "source_paper_title",
    "section_path",
    "passage_excerpt",
    "difficulty",
    "gold_chunk_id",
    "gold_block_id",
}
QUESTION_ID_RE = re.compile(r"^Q-WAY-\d{3}$")
REQUIRED_STRING_FIELDS = (
    "answer_text",
    "source_paper_id",
    "source_paper_title",
    "section_path",
    "passage_excerpt",
    "gold_chunk_id",
    "gold_block_id",
)

# The real corpus DB lives inside the main repo tree (`waymo/data/papers.db`) but is gitignored
# and not checked out in CI. A worktree checkout of this repo nests under `.worktrees/<name>/`,
# so walk every ancestor of this file looking for that sibling layout rather than assuming a
# fixed depth.
_MIN_REAL_DB_BYTES = 1_000_000  # real corpus db is well over 1GB; a stub schema would be tiny


def _find_real_db_path() -> Path | None:
    for ancestor in (FIXTURE_DIR, *FIXTURE_DIR.parents):
        candidate = ancestor / "waymo" / "data" / "papers.db"
        if candidate.exists() and candidate.stat().st_size >= _MIN_REAL_DB_BYTES:
            return candidate
    return None


DB_PATH = _find_real_db_path()


def _load(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def test_structural_invariants():
    gt = _load(GT_PATH)["ground_truth"]
    blind = _load(BLIND_PATH)["questions"]

    assert len(gt) == TOTAL_ITEMS, f"ground truth has {len(gt)} items, expected {TOTAL_ITEMS}"
    assert len(blind) == TOTAL_ITEMS, f"blind set has {len(blind)} items, expected {TOTAL_ITEMS}"

    gt_ids = {item["question_id"] for item in gt}
    blind_ids = {item["question_id"] for item in blind}
    assert gt_ids == blind_ids, (
        f"blind/ground-truth ID mismatch: "
        f"in blind only={blind_ids - gt_ids}, in ground-truth only={gt_ids - blind_ids}"
    )
    assert len(gt_ids) == TOTAL_ITEMS, "duplicate question_id in ground truth"

    for qid in gt_ids:
        assert QUESTION_ID_RE.match(qid), f"malformed question_id: {qid!r}"

    # Zero leaked fields in the blind file.
    for item in blind:
        leaked = LEAKED_FIELDS & set(item.keys())
        assert not leaked, f"{item['question_id']} leaks fields in blind set: {leaked}"
        assert {"question_id", "question_text", "question_type"} <= set(item.keys())

    # question_type quota coverage matches the fixture's own documented distribution.
    type_counts: dict[str, int] = {}
    for item in gt:
        qtype = item["question_type"]
        type_counts[qtype] = type_counts.get(qtype, 0) + 1
    assert type_counts == EXPECTED_TYPE_COUNTS, (
        f"question_type distribution drifted from the seed set's own quotas: {type_counts}"
    )

    for r in gt:
        for field in REQUIRED_STRING_FIELDS:
            value = r.get(field)
            assert isinstance(value, str) and value.strip(), (
                f"{r['question_id']}: {field!r} must be a non-empty string, got {value!r}"
            )
        pid = r["source_paper_id"]
        assert r["gold_block_id"].startswith(f"{pid}:b"), (
            f"{r['question_id']}: gold_block_id {r['gold_block_id']!r} not under paper {pid!r}"
        )
        assert r["gold_chunk_id"].startswith(f"{pid}:c"), (
            f"{r['question_id']}: gold_chunk_id {r['gold_chunk_id']!r} not under paper {pid!r}"
        )
        assert len(r["passage_excerpt"].strip()) >= 20, (
            f"{r['question_id']}: passage_excerpt too short to be a real quoted passage"
        )

    print("all waymo eval fixture structural invariants hold")


@pytest.mark.skipif(
    DB_PATH is None,
    reason=(
        "real Waymo corpus DB (waymo/data/papers.db) not found near this checkout -- it is "
        "gitignored and not checked out in CI; this cross-check is a local/manual "
        "re-verification tool, see module docstring"
    ),
)
def test_gold_ids_resolve_against_corpus_db():
    gt = _load(GT_PATH)["ground_truth"]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        titles = dict(conn.execute("SELECT paper_id, title FROM papers"))
        chunks = {
            row[0]: (row[1], row[2], row[3])  # chunk_id -> (paper_id, text, anchor_json)
            for row in conn.execute("SELECT chunk_id, paper_id, text, anchor_json FROM chunks")
        }
    finally:
        conn.close()

    for r in gt:
        qid = r["question_id"]
        pid = r["source_paper_id"]
        assert pid in titles, f"{qid}: source_paper_id {pid!r} not in papers.db"
        assert titles[pid] == r["source_paper_title"], (
            f"{qid}: source_paper_title {r['source_paper_title']!r} does not match the "
            f"corpus's own title {titles[pid]!r} for {pid!r}"
        )

        assert r["gold_chunk_id"] in chunks, f"{qid}: gold_chunk_id not in chunks table"
        chunk_paper_id, chunk_text, anchor_json = chunks[r["gold_chunk_id"]]
        assert chunk_paper_id == pid, (
            f"{qid}: gold_chunk_id belongs to paper {chunk_paper_id!r}, not {pid!r}"
        )
        anchor_block_id = json.loads(anchor_json)["block_id"]
        assert anchor_block_id == r["gold_block_id"], (
            f"{qid}: gold_chunk_id's own anchor.block_id ({anchor_block_id!r}) does not match "
            f"gold_block_id ({r['gold_block_id']!r})"
        )

        excerpt = " ".join(r["passage_excerpt"].split())
        haystack = " ".join(chunk_text.split())
        assert excerpt in haystack, (
            f"{qid}: passage_excerpt is not a substring of the gold chunk's stored text"
        )

    print("all waymo eval fixture records resolve against the real corpus DB")


if __name__ == "__main__":
    test_structural_invariants()
    if DB_PATH is not None:
        test_gold_ids_resolve_against_corpus_db()
    else:
        print("skipping DB cross-check -- no real Waymo corpus DB found near this checkout")
