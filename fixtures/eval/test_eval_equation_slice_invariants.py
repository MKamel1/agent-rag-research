"""Mechanical invariants for `eval_equation_slice.json` (T-DOC41, Contextual Retrieval spike) —
the passage-level companion to the 210-question `eval_ground_truth.json` (see
`test_eval_fixture_invariants.py`, same rationale for why this guardrail lives in *this* repo:
`fixtures/**` is CODEOWNERS-protected).

Two tiers, same split `test_eval_fixture_invariants.py` uses:
  1. Structural invariants (always run, zero I/O beyond this one JSON file): valid ids, non-empty
     fields, the documented 35/5 Equation-Retrieval/Algorithm-Retrieval quota, a well-formed
     `gold_block_id`/`gold_chunk_id` pair per record.
  2. An optional cross-check against the real corpus DB (`papers.db`) confirming
     `source_paper_id`/`gold_block_id`/`gold_chunk_id` actually exist and that `passage_excerpt`
     is a genuine substring of the resolved chunk's stored text. `papers.db` lives in a sibling
     data directory OUTSIDE this git repo (never committed, multi-GB) — a CI runner that only
     checks out the repo will not have it, so this tier auto-skips when the file isn't found at
     the documented `../research-system-rag-data/papers.db` location (relative to repo root)
     instead of hard-failing every push. It was run and passed against the real corpus during
     authoring (see the eval-slice PR body) — this tier exists so a future edit to the fixture (or
     a corpus re-ingest) can be re-verified locally, not to gate CI on data CI doesn't have.
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
SLICE_PATH = FIXTURE_DIR / "eval_equation_slice.json"
# `research-system-rag-data/papers.db` (the real, multi-GB corpus) lives as a sibling of the repo
# checkout -- "<repo_root>/../research-system-rag-data/papers.db", per AGENTS.md/the ticket brief.
# A git *worktree* (this file may run from one) can nest at any depth under the real repo root, so
# "go up exactly N directories" isn't reliable -- instead walk every ancestor of this file looking
# for that sibling layout, and require a real (multi-MB) file, not a same-named empty/stub sqlite
# db some other tool/worktree may have left behind at a shallower ancestor's sibling path.
_MIN_REAL_DB_BYTES = 10_000_000  # real corpus db is ~1.2GB; a schema-only stub is <100KB


def _find_real_db_path() -> Path | None:
    for ancestor in FIXTURE_DIR.parents:
        candidate = ancestor.parent / "research-system-rag-data" / "papers.db"
        if candidate.exists() and candidate.stat().st_size >= _MIN_REAL_DB_BYTES:
            return candidate
    return None


DB_PATH = _find_real_db_path()

TOTAL_ITEMS = 40
EXPECTED_TYPE_COUNTS = {
    "Equation-Retrieval": 35,
    "Algorithm-Retrieval": 5,
}
VALID_DIFFICULTIES = {"easy", "medium", "hard", "expert"}
QUESTION_ID_RE = re.compile(r"^Q-EQ-\d{3}$")
REQUIRED_STRING_FIELDS = (
    "question_text",
    "source_paper_id",
    "source_paper_title",
    "section_path",
    "gold_block_id",
    "gold_chunk_id",
    "passage_excerpt",
)


def _load_slice():
    with open(SLICE_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def test_structural_invariants():
    data = _load_slice()
    records = data["ground_truth"]

    assert data["_metadata"]["total_items"] == TOTAL_ITEMS
    assert len(records) == TOTAL_ITEMS, f"slice has {len(records)} items, expected {TOTAL_ITEMS}"

    ids = [r["question_id"] for r in records]
    assert len(set(ids)) == TOTAL_ITEMS, "duplicate question_id in equation slice"
    for qid in ids:
        assert QUESTION_ID_RE.match(qid), f"malformed question_id: {qid!r}"

    type_counts: dict[str, int] = {}
    for r in records:
        type_counts[r["question_type"]] = type_counts.get(r["question_type"], 0) + 1
    assert type_counts == EXPECTED_TYPE_COUNTS, (
        f"question_type distribution drifted from the documented 35/5 quota: {type_counts}"
    )

    for r in records:
        for field in REQUIRED_STRING_FIELDS:
            value = r.get(field)
            assert isinstance(value, str) and value.strip(), (
                f"{r['question_id']}: {field!r} must be a non-empty string, got {value!r}"
            )
        assert r["difficulty"] in VALID_DIFFICULTIES, (
            f"{r['question_id']}: unknown difficulty {r['difficulty']!r}"
        )
        # gold_block_id/gold_chunk_id must live under the record's own source_paper_id, and the
        # block/chunk id "namespace" prefixes (DATA-CONTRACTS.md "IDs -- the spine") must match
        # the block/chunk conventions (":b<n>" / ":c<n>") rag/chunker.py and the parser emit.
        pid = r["source_paper_id"]
        assert r["gold_block_id"].startswith(f"{pid}:b"), (
            f"{r['question_id']}: gold_block_id {r['gold_block_id']!r} not under paper {pid!r}"
        )
        assert r["gold_chunk_id"].startswith(f"{pid}:c"), (
            f"{r['question_id']}: gold_chunk_id {r['gold_chunk_id']!r} not under paper {pid!r}"
        )
        # passage_excerpt must be non-trivial verbatim content, not a placeholder/stub.
        assert len(r["passage_excerpt"].strip()) >= 20, (
            f"{r['question_id']}: passage_excerpt too short to be a real equation/algorithm quote"
        )

    print("all equation-slice structural invariants hold")


@pytest.mark.skipif(
    DB_PATH is None,
    reason=(
        "real corpus DB (research-system-rag-data/papers.db) not found near this checkout -- it "
        "lives outside this git repo and is not checked out in CI; this cross-check is a "
        "local/manual re-verification tool, see module docstring"
    ),
)
def test_gold_ids_resolve_against_corpus_db():
    data = _load_slice()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        paper_ids = {row[0] for row in conn.execute("SELECT paper_id FROM papers")}
        blocks = {
            row[0]: (row[1], row[2])  # block_id -> (paper_id, text)
            for row in conn.execute("SELECT block_id, paper_id, text FROM blocks")
        }
        chunks = {
            row[0]: (row[1], row[2], row[3])  # chunk_id -> (paper_id, text, anchor_json)
            for row in conn.execute("SELECT chunk_id, paper_id, text, anchor_json FROM chunks")
        }
    finally:
        conn.close()

    for r in data["ground_truth"]:
        qid = r["question_id"]
        assert r["source_paper_id"] in paper_ids, f"{qid}: source_paper_id not in papers.db"

        assert r["gold_block_id"] in blocks, f"{qid}: gold_block_id not in blocks.db"
        block_paper_id, _block_text = blocks[r["gold_block_id"]]
        assert block_paper_id == r["source_paper_id"], (
            f"{qid}: gold_block_id belongs to paper {block_paper_id!r}, not {r['source_paper_id']!r}"
        )

        assert r["gold_chunk_id"] in chunks, f"{qid}: gold_chunk_id not in chunks.db"
        chunk_paper_id, chunk_text, anchor_json = chunks[r["gold_chunk_id"]]
        assert chunk_paper_id == r["source_paper_id"], (
            f"{qid}: gold_chunk_id belongs to paper {chunk_paper_id!r}, not {r['source_paper_id']!r}"
        )
        anchor_block_id = json.loads(anchor_json)["block_id"]
        assert anchor_block_id == r["gold_block_id"], (
            f"{qid}: gold_chunk_id's own anchor.block_id ({anchor_block_id!r}) does not match "
            f"gold_block_id ({r['gold_block_id']!r})"
        )

        excerpt = _normalize(r["passage_excerpt"])
        assert excerpt in _normalize(chunk_text), (
            f"{qid}: passage_excerpt is not a substring of the gold chunk's stored text"
        )

    print("all equation-slice records resolve against the real corpus DB")


if __name__ == "__main__":
    test_structural_invariants()
    if DB_PATH is not None:
        test_gold_ids_resolve_against_corpus_db()
    else:
        print("skipping DB cross-check -- no real corpus DB found near this checkout")
