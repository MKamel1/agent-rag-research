"""Mechanical invariants for `waymo_gt_b.json` (GT-B: a 40-item, independently-authored deep

ground-truth set for evaluating retrieval/reading-comprehension quality against the Waymo
AV-safety corpus).

This is a sibling fixture to `eval_ground_truth_waymo.json` / `test_eval_ground_truth_waymo_
invariants.py` (the 15-item seed set), not a replacement -- GT-B goes further in depth and
coverage (six evaluation dimensions, known-answerable and known-absent items, one
vision-derived item) and was built independently of any other ground-truth set over this
corpus, by design (see the fixture's own `_metadata.independence_note`).

Follows the same two-tier pattern as the seed set's invariants module:
  1. Structural invariants that need no live data -- shape, required fields per item type,
     id well-formedness, dimension/tests vocabulary, no duplicate ids.
  2. An optional live-DB cross-check tier -- confirms every answerable item's
     source_paper_id/gold_chunk_id/gold_block_id/passage_excerpt (or, for multi-paper items,
     each entry in supporting_passages) actually resolves in the real corpus DB
     (waymo/data/papers.db, gitignored and not checked out in CI) and that passage_excerpt is
     a genuine substring of the resolved chunk's stored text. This tier auto-skips when that
     DB isn't found on the machine running the test.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
GT_PATH = FIXTURE_DIR / "waymo_gt_b.json"

TOTAL_ITEMS = 40

        # Normalized 2026-08-23 to GT-A's short forms (docs/eval-reports/
        # 2026-08-23-waymo-vision-arm.md) -- this fixture used to write these three as
        # "numeric/quantitative claims", "methodological questions", "temporal/versioned
        # claims", which silently forked each into a second, undersized stratum in any
        # dimension-grouped report next to GT-A's short forms. A closed set here (not a
        # superset covering both stylings) is the guard: it fails loudly if a future author
        # reintroduces one of the retired "claims"/"questions" variants.
VALID_DIMENSIONS = {
    "single-passage factual lookup",
    "multi-paper synthesis",
    "numeric/quantitative",
    "methodological",
    "negation and scope",
    "temporal/versioned",
}
VALID_TESTS = {"answerable", "absent"}

QUESTION_ID_RE = re.compile(r"^Q-WAYB-\d{3}$")

SINGLE_PASSAGE_FIELDS = (
    "source_paper_id",
    "source_paper_title",
    "section_path",
    "passage_excerpt",
    "gold_chunk_id",
    "gold_block_id",
)
SUPPORTING_PASSAGE_FIELDS = (
    "paper_id",
    "paper_title",
    "section_path",
    "passage_excerpt",
    "gold_chunk_id",
    "gold_block_id",
)
VISION_FIELDS = ("source_paper_id", "source_paper_title", "page", "vision_note", "gold_block_id")
ABSENT_FIELDS = ("absence_note", "absence_search")

# The real corpus DB lives inside the main repo tree (`waymo/data/papers.db`) but is gitignored
# and not checked out in CI. A worktree checkout of this repo nests under `.worktrees/<name>/`,
# so walk every ancestor of this file looking for that sibling layout rather than assuming a
# fixed depth (same approach as test_eval_ground_truth_waymo_invariants.py).
_MIN_REAL_DB_BYTES = 1_000_000  # real corpus db is well over 1GB; a stub schema would be tiny


def _find_real_db_path() -> Path | None:
    for ancestor in (FIXTURE_DIR, *FIXTURE_DIR.parents):
        candidate = ancestor / "waymo" / "data" / "papers.db"
        if candidate.exists() and candidate.stat().st_size >= _MIN_REAL_DB_BYTES:
            return candidate
    return None


DB_PATH = _find_real_db_path()


def _load():
    with open(GT_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def test_structural_invariants():
    data = _load()
    gt = data["ground_truth"]
    meta = data["_metadata"]

    assert len(gt) == TOTAL_ITEMS, f"ground truth has {len(gt)} items, expected {TOTAL_ITEMS}"

    ids = [item["question_id"] for item in gt]
    assert len(set(ids)) == TOTAL_ITEMS, "duplicate question_id in ground truth"
    for qid in ids:
        assert QUESTION_ID_RE.match(qid), f"malformed question_id: {qid!r}"

    for item in gt:
        qid = item["question_id"]
        assert item.get("dimension") in VALID_DIMENSIONS, (
            f"{qid}: bad dimension {item.get('dimension')!r}"
        )
        assert item.get("tests") in VALID_TESTS, f"{qid}: bad tests value {item.get('tests')!r}"
        assert isinstance(item.get("vision_derived"), bool), f"{qid}: vision_derived must be bool"
        assert item.get("difficulty") in {"easy", "medium", "hard"}, f"{qid}: bad difficulty"
        assert isinstance(item.get("provenance"), str) and item["provenance"].strip(), (
            f"{qid}: provenance must be a non-empty string"
        )

        if item["tests"] == "absent":
            for field in ABSENT_FIELDS:
                assert field in item, f"{qid}: absent item missing {field!r}"
            assert isinstance(item["absence_note"], str) and item["absence_note"].strip()
            assert isinstance(item["absence_search"], list) and item["absence_search"], (
                f"{qid}: absence_search must be a non-empty list of queries run"
            )
            # An absent item must not also carry answerable grounding fields.
            leaked = {"answer_text", "source_paper_id", "supporting_passages"} & set(item)
            assert not leaked, f"{qid}: absent item leaks answerable fields: {leaked}"
            assert not item["vision_derived"], f"{qid}: no vision-derived absent items defined"
            continue

        # tests == "answerable"
        assert isinstance(item.get("answer_text"), str) and item["answer_text"].strip(), (
            f"{qid}: answerable item missing non-empty answer_text"
        )

        if item["vision_derived"]:
            for field in VISION_FIELDS:
                assert field in item, f"{qid}: vision item missing {field!r}"
            assert isinstance(item["page"], int) and item["page"] >= 0, (
                f"{qid}: page must be a non-negative int"
            )
            assert isinstance(item["vision_note"], str) and len(item["vision_note"]) >= 40, (
                f"{qid}: vision_note must substantively describe what was read"
            )
            assert "passage_excerpt" not in item, (
                f"{qid}: vision item should not carry passage_excerpt"
            )
            continue

        if "supporting_passages" in item:
            passages = item["supporting_passages"]
            assert isinstance(passages, list) and len(passages) >= 2, (
                f"{qid}: multi-paper synthesis item must have >=2 supporting_passages"
            )
            paper_ids = {p["paper_id"] for p in passages}
            assert len(paper_ids) >= 2, f"{qid}: supporting_passages must span >=2 distinct papers"
            for p in passages:
                for field in SUPPORTING_PASSAGE_FIELDS:
                    assert field in p and str(p[field]).strip(), (
                        f"{qid}: supporting_passage missing {field!r}"
                    )
                assert p["gold_block_id"].startswith(f"{p['paper_id']}:b"), (
                    f"{qid}: gold_block_id {p['gold_block_id']!r} not under paper {p['paper_id']!r}"
                )
                assert p["gold_chunk_id"].startswith(f"{p['paper_id']}:c"), (
                    f"{qid}: gold_chunk_id {p['gold_chunk_id']!r} not under paper {p['paper_id']!r}"
                )
                assert len(p["passage_excerpt"].strip()) >= 20, f"{qid}: passage_excerpt too short"
            assert "source_paper_id" not in item, (
                f"{qid}: multi-paper item should use supporting_passages, not source_paper_id"
            )
            continue

        # single-paper answerable item
        for field in SINGLE_PASSAGE_FIELDS:
            value = item.get(field)
            assert isinstance(value, str) and value.strip(), (
                f"{qid}: {field!r} must be a non-empty string"
            )
        pid = item["source_paper_id"]
        assert item["gold_block_id"].startswith(f"{pid}:b"), (
            f"{qid}: gold_block_id {item['gold_block_id']!r} not under paper {pid!r}"
        )
        assert item["gold_chunk_id"].startswith(f"{pid}:c"), (
            f"{qid}: gold_chunk_id {item['gold_chunk_id']!r} not under paper {pid!r}"
        )
        assert len(item["passage_excerpt"].strip()) >= 20, f"{qid}: passage_excerpt too short"

    # Dimension coverage: every one of the six evaluation dimensions must appear, and the
    # fixture's own recorded dimension_counts must match what's actually in the array (guards
    # against the metadata drifting out of sync with the data on a future hand-edit).
    from collections import Counter

    dim_counts = Counter(item["dimension"] for item in gt)
    assert set(dim_counts) == VALID_DIMENSIONS, (
        f"missing dimension coverage: {VALID_DIMENSIONS - set(dim_counts)}"
    )
    assert dim_counts == Counter(meta["dimension_counts"]), (
        f"_metadata.dimension_counts drifted from actual data: {dict(dim_counts)} vs "
        f"{meta['dimension_counts']}"
    )

    tests_counts = Counter(item["tests"] for item in gt)
    assert tests_counts == Counter(meta["tests_counts"]), (
        f"_metadata.tests_counts drifted: {dict(tests_counts)} vs {meta['tests_counts']}"
    )
    assert tests_counts["absent"] >= 6, (
        "known-absent items should be a substantial fraction, not token coverage"
    )

    vision_count = sum(1 for item in gt if item["vision_derived"])
    assert vision_count == meta["vision_derived_count"], (
        "_metadata.vision_derived_count drifted from actual data"
    )
    assert vision_count >= 1, "no vision-derived item found -- expected at least one"

    print("all waymo_gt_b structural invariants hold")


# Labels retired by the 2026-08-23 normalization (docs/eval-reports/2026-08-23-waymo-vision-arm.md):
# this fixture used to write these as GT-B's own noun-form wording, splitting each into a second,
# undersized stratum next to GT-A's short forms under any dimension-grouped report. Checked
# explicitly (not just via VALID_DIMENSIONS above) so a future widening of VALID_DIMENSIONS to
# "be safe" can't silently let one of these back in.
RETIRED_DIMENSION_VARIANTS = {
    "numeric/quantitative claims",
    "methodological questions",
    "temporal/versioned claims",
}


def test_dimension_vocabulary_is_closed():
    gt = _load()["ground_truth"]
    used = {item["dimension"] for item in gt}
    reintroduced = used & RETIRED_DIMENSION_VARIANTS
    assert not reintroduced, f"retired dimension variant(s) back in the data: {reintroduced}"
    assert used <= VALID_DIMENSIONS, f"dimension(s) outside the closed vocabulary: {used - VALID_DIMENSIONS}"


def _iter_single_paper_checks(gt):
    """Yield (qid, paper_id, paper_title, chunk_id, block_id, excerpt) for every text-grounded
    single-paper claim in the fixture (answerable, non-vision items)."""
    for item in gt:
        if item["tests"] != "answerable" or item["vision_derived"]:
            continue
        if "supporting_passages" in item:
            for p in item["supporting_passages"]:
                yield (
                    item["question_id"],
                    p["paper_id"],
                    p["paper_title"],
                    p["gold_chunk_id"],
                    p["gold_block_id"],
                    p["passage_excerpt"],
                )
        else:
            yield (
                item["question_id"],
                item["source_paper_id"],
                item["source_paper_title"],
                item["gold_chunk_id"],
                item["gold_block_id"],
                item["passage_excerpt"],
            )


@pytest.mark.skipif(
    DB_PATH is None,
    reason=(
        "real Waymo corpus DB (waymo/data/papers.db) not found near this checkout -- it is "
        "gitignored and not checked out in CI; this cross-check is a local/manual "
        "re-verification tool, see module docstring"
    ),
)
def test_gold_ids_resolve_against_corpus_db():
    data = _load()
    gt = data["ground_truth"]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        titles = dict(conn.execute("SELECT paper_id, title FROM papers"))
        chunks = {
            row[0]: (row[1], row[2], row[3])  # chunk_id -> (paper_id, text, anchor_json)
            for row in conn.execute("SELECT chunk_id, paper_id, text, anchor_json FROM chunks")
        }
    finally:
        conn.close()

    checked = 0
    for qid, pid, title, chunk_id, block_id, excerpt in _iter_single_paper_checks(gt):
        assert pid in titles, f"{qid}: paper_id {pid!r} not in papers.db"
        assert titles[pid] == title, (
            f"{qid}: recorded title {title!r} does not match the corpus's own title "
            f"{titles[pid]!r} for {pid!r}"
        )
        assert chunk_id in chunks, f"{qid}: gold_chunk_id {chunk_id!r} not in chunks table"
        chunk_paper_id, chunk_text, anchor_json = chunks[chunk_id]
        assert chunk_paper_id == pid, (
            f"{qid}: gold_chunk_id belongs to paper {chunk_paper_id!r}, not {pid!r}"
        )
        anchor_block_id = json.loads(anchor_json)["block_id"]
        assert anchor_block_id == block_id, (
            f"{qid}: gold_chunk_id's own anchor.block_id ({anchor_block_id!r}) does not match "
            f"gold_block_id ({block_id!r})"
        )
        norm_excerpt = " ".join(excerpt.split())
        norm_haystack = " ".join(chunk_text.split())
        assert norm_excerpt in norm_haystack, (
            f"{qid}: passage_excerpt is not a substring of the gold chunk's text"
        )
        checked += 1

    # Vision item: verify paper/title resolve, and that the cited page is in range for the PDF
    # anchor convention used elsewhere in this DB (best-effort -- we don't re-render the PDF here,
    # just sanity-check the paper exists and the page number is plausible).
    for item in gt:
        if item["tests"] == "answerable" and item["vision_derived"]:
            pid = item["source_paper_id"]
            qid = item["question_id"]
            assert pid in titles, f"{qid}: vision item paper_id {pid!r} not in papers.db"
            assert titles[pid] == item["source_paper_title"], f"{qid}: vision item title mismatch"
            vconn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            try:
                block_ids = {
                    bid
                    for (bid,) in vconn.execute(
                        "SELECT block_id FROM blocks WHERE paper_id=?", (pid,)
                    )
                }
            finally:
                vconn.close()
            assert item["gold_block_id"] in block_ids, (
                f"{qid}: vision gold_block_id not in blocks for {pid!r}"
            )

    print(f"all waymo_gt_b records resolve against the real corpus DB ({checked} passage checks)")


if __name__ == "__main__":
    test_structural_invariants()
    test_dimension_vocabulary_is_closed()
    if DB_PATH is not None:
        test_gold_ids_resolve_against_corpus_db()
    else:
        print("skipping DB cross-check -- no real Waymo corpus DB found near this checkout")
