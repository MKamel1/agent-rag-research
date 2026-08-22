"""Mechanical invariants for `eval_known_absent.json` (RI-M7) -- the known-absent arm of the
retrieval score-distribution census, the companion to `test_eval_fixture_invariants.py`'s
210-question set and `test_eval_equation_slice_invariants.py`'s equation slice. Same rationale
for why this guardrail lives in *this* repo: `fixtures/**` is CODEOWNERS-protected.

Two tiers, same split the equation-slice suite uses:
  1. Structural invariants (always run, zero I/O beyond this one JSON file): valid ids, the
     documented item count, every record shaped as "no gold paper" (`source_paper_id: null`,
     no `additional_gold_paper_ids`), a non-trivial `fabricated_entity` per record.
  2. An absence cross-check against the real corpus DB (`papers.db`): for every record, a
     case-insensitive substring search for `fabricated_entity` against `papers.title`,
     `papers.abstract`, `chunks.text`, and `blocks.text` must return zero rows. This is the
     mechanical, re-runnable form of the claim in `eval_known_absent.json`'s own
     `_metadata.absence_verification` -- not just documentation of a one-time check, a test that
     would catch a future corpus re-ingest silently introducing a paper that happens to use one
     of these invented terms. Same auto-skip posture as the equation slice's own DB tier:
     `papers.db` lives in a sibling data directory OUTSIDE this git repo (never committed,
     multi-GB), so a CI runner that only checks out the repo skips this tier instead of failing
     on missing data it was never given.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
FIXTURE_PATH = FIXTURE_DIR / "eval_known_absent.json"

# Same walk-every-ancestor lookup as test_eval_equation_slice_invariants.py's `_find_real_db_path`
# -- duplicated rather than imported (each fixture invariants file is a standalone guardrail, same
# posture as the sibling files it mirrors) -- see that module's docstring for why "go up N dirs"
# isn't reliable from inside a worktree and why a same-named stub db must not count as "found".
_MIN_REAL_DB_BYTES = 10_000_000  # real corpus db is multi-GB; a schema-only stub is <100KB


def _find_real_db_path() -> Path | None:
    for ancestor in FIXTURE_DIR.parents:
        candidate = ancestor.parent / "research-system-rag-data" / "papers.db"
        if candidate.exists() and candidate.stat().st_size >= _MIN_REAL_DB_BYTES:
            return candidate
    return None


DB_PATH = _find_real_db_path()

TOTAL_ITEMS = 24
QUESTION_ID_RE = re.compile(r"^Q-ABS-\d{3}$")


def _load_fixture():
    with open(FIXTURE_PATH, encoding="utf-8") as fp:
        return json.load(fp)


def test_structural_invariants():
    data = _load_fixture()
    records = data["ground_truth"]

    assert data["_metadata"]["total_items"] == TOTAL_ITEMS
    assert len(records) == TOTAL_ITEMS, f"fixture has {len(records)} items, expected {TOTAL_ITEMS}"

    ids = [r["question_id"] for r in records]
    assert len(set(ids)) == TOTAL_ITEMS, "duplicate question_id in known-absent fixture"
    for qid in ids:
        assert QUESTION_ID_RE.match(qid), f"malformed question_id: {qid!r}"

    for r in records:
        qid = r["question_id"]
        # The defining shape: no gold paper at all, by construction -- app/retrieval_eval.py's
        # load_questions() turns source_paper_id=None into an EMPTY gold_paper_ids (never a
        # false hit against a real paper_id), and this fixture must never smuggle a real gold id
        # in through additional_gold_paper_ids either.
        assert r["source_paper_id"] is None, f"{qid}: known-absent record must have no gold paper"
        assert not r.get("additional_gold_paper_ids"), (
            f"{qid}: known-absent record must not carry additional_gold_paper_ids"
        )
        assert r["question_type"] == "Known-Absent", f"{qid}: unexpected question_type"

        for field in ("question_text", "fabricated_entity", "fabrication_kind"):
            value = r.get(field)
            assert isinstance(value, str) and value.strip(), (
                f"{qid}: {field!r} must be a non-empty string, got {value!r}"
            )
        # The fabricated entity must actually appear in the question, or the "verified absent"
        # claim below would be a non-sequitur -- it would be checking a term the question never
        # asks about.
        assert r["fabricated_entity"] in r["question_text"], (
            f"{qid}: fabricated_entity {r['fabricated_entity']!r} does not appear verbatim in "
            f"question_text -- the absence check would be verifying the wrong string"
        )

    # No two records may reuse the same fabricated entity -- each is meant to probe a distinct
    # point in the corpus's topic space (see _metadata.provenance).
    entities = [r["fabricated_entity"] for r in records]
    assert len(set(entities)) == TOTAL_ITEMS, "a fabricated_entity is reused across records"

    print("all known-absent fixture structural invariants hold")


@pytest.mark.skipif(
    DB_PATH is None,
    reason=(
        "real corpus DB (research-system-rag-data/papers.db) not found near this checkout -- it "
        "lives outside this git repo and is not checked out in CI; this cross-check is a "
        "local/manual re-verification tool, see module docstring"
    ),
)
def test_fabricated_entities_are_absent_from_the_real_corpus():
    data = _load_fixture()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        for r in data["ground_truth"]:
            qid = r["question_id"]
            entity = r["fabricated_entity"]
            like = f"%{entity}%"

            cur.execute(
                "SELECT COUNT(*) FROM papers WHERE title LIKE ? COLLATE NOCASE "
                "OR abstract LIKE ? COLLATE NOCASE",
                (like, like),
            )
            n_papers = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE ? COLLATE NOCASE", (like,))
            n_chunks = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM blocks WHERE text LIKE ? COLLATE NOCASE", (like,))
            n_blocks = cur.fetchone()[0]

            assert n_papers == 0 and n_chunks == 0 and n_blocks == 0, (
                f"{qid}: fabricated_entity {entity!r} is NOT absent from the corpus "
                f"(papers={n_papers}, chunks={n_chunks}, blocks={n_blocks}) -- this record no "
                f"longer belongs in the known-absent arm"
            )
    finally:
        conn.close()

    print("all known-absent fixture entities verified absent from the real corpus")


if __name__ == "__main__":
    test_structural_invariants()
    if DB_PATH is not None:
        test_fabricated_entities_are_absent_from_the_real_corpus()
    else:
        print("skipping DB cross-check -- no real corpus DB found near this checkout")
