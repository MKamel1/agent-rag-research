"""Mechanical invariants for the book eval set (`eval_book_questions.json`,
docs/DESIGN-book-chapters-and-hierarchy.md Part 3 Step 1). Same posture as
`test_eval_fixture_invariants.py` for the 210-question set: structural checks only, run in CI with
no papers.db/vector-store access (that file lives outside this repo on the ingest machine and is
read-only by convention -- see the module the harness itself lives in, app/retrieval_eval.py). The
content-level claims (gold_block_id really contains passage_excerpt, gold_chapter_title really
matches that block's chapter under today's split, gold_chunk_id's live anchor equals gold_block_id)
were verified directly against papers.db (file:...?mode=ro, uri=True) at authoring time -- for
QB-001..QB-040 see this file's original PR description, for QB-041..QB-115 (T-DOC-BOOK-EVAL-115) see
docs/eval-reports/2026-07-29-evalset-115-authoring-notes.md -- not re-checked here since that would
make CI depend on a local corpus path.
"""

import json
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parent / "eval_book_questions.json"

TOTAL_ITEMS = 115
ALLOWED_PAPER_IDS = {
    "local:14b7e283bdcd", "local:f0929288d4f3", "local:f6c64e1e8c7d",
    "local:dfe850b3281a", "local:54d6ca71dda9",
}
# docs/PLAN-book-rag-experiments.md §1's original 40 (8/book) was sized to prove the format, not to
# resolve an effect size -- that same section's power calculation (~114 questions to resolve an
# 18-point chapter-routing swing at α=0.05/power=0.80) is what T-DOC-BOOK-EVAL-115 sized this to:
# 23/book x 5 books = 115. An exact per-book count, not just "at least 1" -- a book with fewer/more
# than 23 is exactly the kind of silent imbalance that would let one book's questions dominate the
# aggregate metric without anyone noticing.
QUESTIONS_PER_BOOK = 23
REQUIRED_FIELDS = {
    "question_id", "question_text", "doc_type", "source_paper_id", "source_paper_title",
    "question_type", "gold_chapter_title", "gold_chapter_index", "gold_chunk_id",
    "gold_block_id", "excerpt_block_id", "section_path", "page", "passage_excerpt",
}
# T-DOC-BOOK-EVAL-115's schema addition (question_type stays "Book-Chapter-Recall" on every record
# for backward compatibility -- see _metadata.facet_vocabulary in the fixture itself). Present on
# QB-041.. only, by design -- QB-001..QB-040 were not backfilled (the task forbade guessing a facet
# beyond what each question's own recorded excerpt supports).
FACET_VALUES = {
    "definition", "numeric-result", "named-concept", "method-procedure", "comparison",
    "caveat-condition",
}
FIRST_115_TASK_ID = "QB-041"  # QB-041..QB-115 are the 75 added by T-DOC-BOOK-EVAL-115
# Chapter units that share their title with another unit of the SAME paper (papers.db summaries
# table, verified read-only at authoring time -- 4 of dfe850b3281a's 7 units, 12 of
# 54d6ca71dda9's 44; 0 for the other 3 books) -- a question scored against one of these titles is
# unwinnable by construction (search_papers' chapter-routing hit check is title-string equality,
# so it cannot distinguish two same-titled chapters of the same paper_id). QB-001..QB-040 already
# contains a few of these as documented, deliberate exceptions (QB-028/029/030/031/034) -- kept
# unchanged per the task's "keep all 40 existing questions unchanged" instruction. T-DOC-BOOK-EVAL-
# 115's new questions (QB-041..) must not add any more.
KNOWN_DUPLICATE_CHAPTER_TITLES = {
    "local:dfe850b3281a": {"Part 2: Causal Inference", "Part 3: Causal Discovery"},
    "local:54d6ca71dda9": {
        "7. Pruning the Tree Using Cost-Complexity",
        "10. Final Prediction for New Observations",
        "8. Cross-Validation to Select Optimal Tree Size",
        "5. Recursive Partitioning: Split Left and Right Nodes",
        "4. Choose Optimal Split Point for Each Variable",
        "1. Setup: Define the Problem and Data",
    },
}


def _load():
    return json.loads(FIXTURE_PATH.read_text())["ground_truth"]


def demo():
    records = _load()

    assert len(records) == TOTAL_ITEMS, f"{len(records)} items, expected {TOTAL_ITEMS}"

    ids = [r["question_id"] for r in records]
    assert len(set(ids)) == len(ids), "duplicate question_id"

    per_paper: dict[str, int] = {}
    # (paper_id, gold_chapter_title) -> the set of gold_chapter_index values recorded against it
    # across QB-041+. More than one index for the same title means two records disagree about
    # which chapter a title belongs to -- exactly the ambiguity KNOWN_DUPLICATE_CHAPTER_TITLES
    # exists to keep new questions away from; this catches it even for a title not already in that
    # hardcoded set (e.g. a transcription slip that reused a title at the wrong index).
    title_indexes: dict[tuple[str, str], set[int]] = {}
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

        if r["question_id"] >= FIRST_115_TASK_ID:
            assert r.get("facet") in FACET_VALUES, (
                f"{r['question_id']}: facet {r.get('facet')!r} not in the closed vocabulary "
                f"{FACET_VALUES}"
            )
            dupes = KNOWN_DUPLICATE_CHAPTER_TITLES.get(r["source_paper_id"], set())
            assert r["gold_chapter_title"] not in dupes, (
                f"{r['question_id']}: gold_chapter_title {r['gold_chapter_title']!r} is one of "
                f"{r['source_paper_id']}'s known duplicate-titled chapter units -- new questions "
                f"(QB-041+) must avoid these, per the task's duplicate-title rule"
            )
            key = (r["source_paper_id"], r["gold_chapter_title"])
            title_indexes.setdefault(key, set()).add(r["gold_chapter_index"])
        else:
            assert "facet" not in r, (
                f"{r['question_id']}: facet must not be backfilled onto the original 40 by guessing"
            )

        per_paper[r["source_paper_id"]] = per_paper.get(r["source_paper_id"], 0) + 1

    for (paper_id, title), indexes in title_indexes.items():
        assert len(indexes) == 1, (
            f"{paper_id}: gold_chapter_title {title!r} used with more than one gold_chapter_index "
            f"({indexes}) among QB-041+ -- ambiguous chapter title, unwinnable for chapter-"
            f"routing scoring"
        )

    # Both outline regimes from the design doc are represented: local:14b7e283bdcd has no PDF
    # outline, local:f0929288d4f3 has a 223-entry/4-level one.
    assert set(per_paper) == ALLOWED_PAPER_IDS, f"missing a book: {per_paper}"
    assert all(n >= 1 for n in per_paper.values())
    # docs/PLAN-book-rag-experiments.md §1 + T-DOC-BOOK-EVAL-115: exactly 23 per book, not just
    # "at least 1" -- see QUESTIONS_PER_BOOK's comment for why this is a separate, stronger check
    # rather than a replacement of the line above.
    assert per_paper == {pid: QUESTIONS_PER_BOOK for pid in ALLOWED_PAPER_IDS}, (
        f"expected exactly {QUESTIONS_PER_BOOK} questions per book, got {per_paper}"
    )

    print("all book eval fixture invariants hold")


def test_eval_book_questions_invariants():
    demo()


if __name__ == "__main__":
    demo()
