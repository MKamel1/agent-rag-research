"""Mechanical invariants for the seed book eval set (`eval_book_questions.json`,
docs/DESIGN-book-chapters-and-hierarchy.md Part 3 Step 1). Same posture as
`test_eval_fixture_invariants.py` for the 210-question set: structural checks only, run in CI with
no papers.db/vector-store access (that file lives outside this repo on the ingest machine and is
read-only by convention -- see the module the harness itself lives in, app/retrieval_eval.py). The
content-level claims (gold_block_id really contains passage_excerpt, gold_chapter_title really
matches that block's chapter under today's split) were verified once, directly against papers.db
(file:...?mode=ro, uri=True) at authoring time -- see this file's PR description -- not re-checked
here since that would make CI depend on a local corpus path.
"""

import json
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parent / "eval_book_questions.json"

TOTAL_ITEMS = 15
ALLOWED_PAPER_IDS = {"local:14b7e283bdcd", "local:f0929288d4f3"}
REQUIRED_FIELDS = {
    "question_id", "question_text", "doc_type", "source_paper_id", "source_paper_title",
    "question_type", "gold_chapter_title", "gold_chapter_index", "gold_chunk_id",
    "gold_block_id", "excerpt_block_id", "section_path", "page", "passage_excerpt",
}


def _load():
    return json.loads(FIXTURE_PATH.read_text())["ground_truth"]


def demo():
    records = _load()

    assert len(records) == TOTAL_ITEMS, f"{len(records)} items, expected {TOTAL_ITEMS}"

    ids = [r["question_id"] for r in records]
    assert len(set(ids)) == len(ids), "duplicate question_id"

    per_paper: dict[str, int] = {}
    for r in records:
        missing = REQUIRED_FIELDS - set(r.keys())
        assert not missing, f"{r['question_id']} missing fields: {missing}"

        assert r["doc_type"] == "book", f"{r['question_id']}: doc_type must be 'book'"
        assert r["source_paper_id"] in ALLOWED_PAPER_IDS, (
            f"{r['question_id']}: source_paper_id {r['source_paper_id']!r} not in the 2 seed books"
        )
        assert r["gold_chapter_title"], f"{r['question_id']}: gold_chapter_title must be non-empty"
        # gold_block_id (the CHUNK's real anchor block -- what passage-level scoring compares
        # against GroundedResult.anchor.block_id, same convention as eval_equation_slice.json's
        # gold_block_id/gold_chunk_id) and excerpt_block_id (the block passage_excerpt/
        # section_path/page were actually read from -- provenance, not a scoring id, and usually
        # a DIFFERENT block than gold_block_id since a chunk's anchor is its first block, not
        # necessarily the block carrying the fact) must both belong to source_paper_id -- a book
        # question scoring a different paper's block would silently pass chapter-routing's
        # paper_id-in-gold-set check for the wrong reason.
        for field in ("gold_block_id", "excerpt_block_id"):
            assert r[field].startswith(r["source_paper_id"] + ":b"), (
                f"{r['question_id']}: {field} {r[field]!r} doesn't belong to source_paper_id "
                f"{r['source_paper_id']!r}"
            )
        assert r["gold_chunk_id"].startswith(r["source_paper_id"] + ":c"), (
            f"{r['question_id']}: gold_chunk_id {r['gold_chunk_id']!r} doesn't belong to "
            f"source_paper_id {r['source_paper_id']!r}"
        )
        assert isinstance(r["page"], int) and r["page"] >= 0
        assert r["passage_excerpt"].strip(), f"{r['question_id']}: passage_excerpt must be non-empty"

        per_paper[r["source_paper_id"]] = per_paper.get(r["source_paper_id"], 0) + 1

    # Both outline regimes from the design doc are represented: local:14b7e283bdcd has no PDF
    # outline, local:f0929288d4f3 has a 223-entry/4-level one.
    assert set(per_paper) == ALLOWED_PAPER_IDS, f"missing a seed book: {per_paper}"
    assert all(n >= 1 for n in per_paper.values())

    print("all book eval fixture invariants hold")


def test_eval_book_questions_invariants():
    demo()


if __name__ == "__main__":
    demo()
