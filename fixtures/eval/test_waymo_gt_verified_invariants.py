"""Mechanical invariants for `waymo_gt_verified.json` (GT-X cross-verification merge).

This fixture is the verified union of two independently-authored Waymo ground-truth sets:
GT-A (`waymo_gt_a.json`, branch GT-A-oxalpha-waymo-groundtruth) and GT-B (`waymo_gt_b.json`,
branch GT-B-claude-waymo-groundtruth). The cross-verification run (2026-08-22,
docs/eval-reports/2026-08-22-waymo-groundtruth-cross-verification.md) checked every item of
both sets against the live corpus DB and against each other; only survivors were merged, and
each carries a `verification` block naming its source set and what was checked.

Follows the same two-tier pattern as the sibling suites in this directory
(test_eval_ground_truth_waymo_invariants.py, test_waymo_gt_b_invariants.py):
  1. Structural invariants needing no live data -- counts per source set, id well-formedness
     and cross-set uniqueness, grounding-shape rules per item type, presence and shape of the
     `verification` block, absence items carrying their independent re-verification evidence,
     and the vision item carrying its explicit visual-claim-unverified note.
  2. An optional live-DB cross-check tier -- re-resolves every answerable item's ids/excerpts
     (primary, supporting_passages, and GT-A-style supporting_sources) plus the vision item's
     paper/title/block/page against the real corpus DB. Auto-skips when that gitignored DB
     is not found on the machine running the test.
"""

import json
import re
import sqlite3
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
GT_PATH = FIXTURE_DIR / "waymo_gt_verified.json"

TOTAL_ITEMS = 84
PER_SET_COUNTS = {"GT-A": 44, "GT-B": 40}
# Q-GTA-036/Q-GTA-037 independently rediscover facts already covered by GT-B items; they are
# kept under their own ids with explicit pointers, and aggregate scoring counts each group once.
EXPECTED_DUPLICATES = {"Q-GTA-036": "Q-WAYB-034", "Q-GTA-037": "Q-WAYB-009"}

QUESTION_ID_RES = {
    "GT-A": re.compile(r"^Q-GTA-\d{3}$"),
    "GT-B": re.compile(r"^Q-WAYB-\d{3}$"),
}
VALID_TESTS = {"answerable", "absent"}
# The two authors used partially different dimension vocabularies for three of the six
# dimensions; the merged fixture preserves each label verbatim (see the fixture's own
# _metadata.dimension_labels_note) so the valid set here is the union, not one style.
VALID_DIMENSIONS = {
    "single-passage factual lookup",
    "multi-paper synthesis",
    "numeric/quantitative claims",
    "numeric/quantitative",
    "methodological questions",
    "methodological",
    "negation and scope",
    "temporal/versioned claims",
    "temporal/versioned",
}
REQUIRED_VERIFICATION_FIELDS = ("source_set", "source_fixture", "verified_at", "checks")

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
ABSENT_LEAKED_FIELDS = {"answer_text", "source_paper_id", "supporting_passages"}

_MIN_REAL_DB_BYTES = 1_000_000


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

    per_set: dict[str, int] = {}
    seen_ids: set[str] = set()
    for item in gt:
        qid = item["question_id"]
        assert qid not in seen_ids, f"duplicate question_id across merged sets: {qid!r}"
        seen_ids.add(qid)

        ver = item.get("verification")
        assert isinstance(ver, dict), f"{qid}: missing verification block"
        for field in REQUIRED_VERIFICATION_FIELDS:
            assert field in ver, f"{qid}: verification missing {field!r}"
        src_set = ver["source_set"]
        assert src_set in PER_SET_COUNTS, f"{qid}: unknown source_set {src_set!r}"
        assert QUESTION_ID_RES[src_set].match(qid), (
            f"{qid}: id does not match the {src_set} id pattern"
        )
        assert ver["source_fixture"] == f"waymo_gt_{src_set[-1].lower()}.json", (
            f"{qid}: source_fixture does not match source_set"
        )
        pass_name = ver.get("verification_pass", "pass-1")
        assert pass_name in meta["verification_dates"], (
            f"{qid}: unknown verification_pass {pass_name!r}"
        )
        assert ver["verified_at"] == meta["verification_dates"][pass_name], (
            f"{qid}: verified_at/{pass_name} date drift"
        )
        assert isinstance(ver["checks"], list) and ver["checks"], (
            f"{qid}: checks must be a non-empty list"
        )
        per_set[src_set] = per_set.get(src_set, 0) + 1

        assert item.get("tests") in VALID_TESTS, f"{qid}: bad tests value {item.get('tests')!r}"
        assert item.get("dimension") in VALID_DIMENSIONS, f"{qid}: bad dimension label"

        if item["tests"] == "absent":
            # An absent item must not smuggle answerable grounding back in, and -- unlike the
            # source sets -- must carry the cross-verifier's own re-search evidence, either as
            # an absence-specific check id or in notes.
            leaked = ABSENT_LEAKED_FIELDS & set(item.keys())
            assert not leaked, f"{qid}: absent item leaks answerable fields: {leaked}"
            evidence = " ".join(ver["checks"]) + " " + " ".join(ver.get("notes", []))
            assert "absence_re_established" in evidence, (
                f"{qid}: absent item lacks independent re-verification evidence"
            )
            assert str(item.get("absence_search") or "").strip(), (
                f"{qid}: absent item carries no recorded absence search log"
            )
            continue

        assert isinstance(item.get("answer_text"), str) and item["answer_text"].strip(), (
            f"{qid}: answerable item missing non-empty answer_text"
        )

        if item.get("vision_derived"):
            assert "passage_excerpt" not in item, f"{qid}: vision item should not carry excerpt"
            notes = " ".join(ver.get("notes", []))
            assert "unverified" in notes, (
                f"{qid}: vision item must state plainly that its visual claim is unverified "
                "by the cross-verifier"
            )
            continue

        if "supporting_passages" in item:
            passages = item["supporting_passages"]
            assert len(passages) >= 2, f"{qid}: multi-paper item needs >=2 supporting_passages"
            assert len({p["paper_id"] for p in passages}) >= 2, (
                f"{qid}: supporting_passages must span >=2 distinct papers"
            )
            assert "source_paper_id" not in item, (
                f"{qid}: multi-paper item should not also carry source_paper_id"
            )
        else:
            # section_path may legitimately be empty: front-matter/title-block chunks carry
            # section_path=="" in the corpus itself (three GT-A items cite exactly such
            # chunks), so only type-check it here; the DB tier asserts it equals the chunk's
            # stored value, which is the real invariant.
            for field in SINGLE_PASSAGE_FIELDS:
                value = item.get(field)
                if field == "section_path":
                    assert isinstance(value, str), f"{qid}: {field!r} must be a string"
                    continue
                assert isinstance(value, str) and value.strip(), (
                    f"{qid}: {field!r} must be a non-empty string"
                )
            pid = item["source_paper_id"]
            assert item["gold_block_id"].startswith(f"{pid}:b"), f"{qid}: block id under paper"
            assert item["gold_chunk_id"].startswith(f"{pid}:c"), f"{qid}: chunk id under paper"

        for p in item.get("supporting_passages", []) + [
            s for s in item.get("supporting_sources", []) if s.get("gold_chunk_id")
        ]:
            for field in SUPPORTING_PASSAGE_FIELDS:
                assert field in p and str(p[field]).strip(), (
                    f"{qid}: supporting passage missing {field!r}"
                )

    assert per_set == PER_SET_COUNTS, f"per-set survival counts drifted: {per_set}"

    # Duplicate-of bookkeeping: exactly the two known rediscoveries, pointing at in-file items.
    dups = {i["question_id"]: i["duplicate_of"] for i in gt if "duplicate_of" in i}
    assert dups == EXPECTED_DUPLICATES, f"duplicate_of map drifted: {dups}"
    by_id = {i["question_id"] for i in gt}
    for sec, prim in dups.items():
        assert prim in by_id, f"{sec}: duplicate_of target {prim!r} not in fixture"
        sec_item = next(i for i in gt if i["question_id"] == sec)
        prim_item = next(i for i in gt if i["question_id"] == prim)
        assert sec_item["tests"] == prim_item["tests"] == "absent", (
            f"{sec}: duplicates must both be absent items"
        )

    print("all waymo_gt_verified structural invariants hold")


def _iter_single_paper_checks(gt):
    """Yield (qid, paper_id, title, chunk_id, block_id, excerpt) for every text-grounded claim
    in the fixture: single-paper primaries, every supporting passage, and GT-A's
    supporting_sources entries (which carry gold ids but use a different key layout)."""
    for item in gt:
        if item["tests"] != "answerable" or item.get("vision_derived"):
            continue
        qid = item["question_id"]
        for p in item.get("supporting_passages", []):
            yield (qid, p["paper_id"], p["paper_title"], p["gold_chunk_id"],
                   p["gold_block_id"], p["passage_excerpt"])
        for s in item.get("supporting_sources", []):
            if s.get("gold_chunk_id"):
                yield (qid, s["paper_id"], s["paper_title"], s["gold_chunk_id"],
                       s["gold_block_id"], s["passage_excerpt"])
        if "supporting_passages" not in item:
            yield (qid, item["source_paper_id"], item["source_paper_title"],
                   item["gold_chunk_id"], item["gold_block_id"], item["passage_excerpt"])


@pytest.mark.skipif(
    DB_PATH is None,
    reason=(
        "real Waymo corpus DB (waymo/data/papers.db) not found near this checkout -- it is "
        "gitignored and not checked out in CI; this cross-check is a local/manual "
        "re-verification tool, see module docstring"
    ),
)
def test_gold_ids_resolve_against_corpus_db():
    gt = _load()["ground_truth"]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        titles = dict(conn.execute("SELECT paper_id, title FROM papers"))
        chunks = {
            row[0]: (row[1], row[2], json.loads(row[3]) if row[3] else {})
            for row in conn.execute("SELECT chunk_id, paper_id, text, anchor_json FROM chunks")
        }
        blocks = dict(
            (row[0], row[1])
            for row in conn.execute("SELECT block_id, page FROM blocks")
        )
    finally:
        conn.close()

    checked = 0
    for qid, pid, title, chunk_id, block_id, excerpt in _iter_single_paper_checks(gt):
        assert pid in titles, f"{qid}: paper_id {pid!r} not in papers.db"
        assert titles[pid] == title, f"{qid}: recorded title {title!r} != corpus {titles[pid]!r}"
        assert chunk_id in chunks, f"{qid}: gold_chunk_id {chunk_id!r} not in chunks table"
        c_pid, c_text, anchor = chunks[chunk_id]
        assert c_pid == pid, f"{qid}: chunk belongs to {c_pid!r}, not {pid!r}"
        assert anchor.get("block_id") == block_id, f"{qid}: anchor block mismatch"
        norm_excerpt = " ".join(excerpt.split())
        norm_haystack = " ".join((c_text or "").split())
        assert norm_excerpt in norm_haystack, (
            f"{qid}: passage_excerpt not a substring of the gold chunk's stored text"
        )
        checked += 1

    # Section-path agreement (the structural tier deliberately only type-checks this field):
    # every recorded section_path must equal the cited chunk's own stored section_path.
    conn2 = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        stored = dict(conn2.execute("SELECT chunk_id, section_path FROM chunks"))
    finally:
        conn2.close()
    for item in gt:
        if item["tests"] != "answerable" or item.get("vision_derived"):
            continue
        qid = item["question_id"]
        pairs = []
        if "supporting_passages" not in item:
            pairs.append((item["section_path"], item["gold_chunk_id"]))
        for p in item.get("supporting_passages", []):
            pairs.append((p["section_path"], p["gold_chunk_id"]))
        for s in item.get("supporting_sources", []):
            if s.get("gold_chunk_id"):
                pairs.append((s["section_path"], s["gold_chunk_id"]))
        for recorded, cid in pairs:
            if recorded is None:
                continue
            assert (recorded or "") == (stored.get(cid) or ""), (
                f"{qid}: section_path {recorded!r} != chunk {cid}'s stored "
                f"{stored.get(cid)!r}"
            )

    for item in gt:
        if item["tests"] != "answerable" or not item.get("vision_derived"):
            continue
        qid = item["question_id"]
        pid = item["source_paper_id"]
        assert pid in titles, f"{qid}: vision paper {pid!r} not in papers.db"
        assert titles[pid] == item["source_paper_title"], f"{qid}: vision title mismatch"
        page = blocks.get(item["gold_block_id"])
        assert page is not None, f"{qid}: vision gold_block_id not in blocks table"
        assert item["page"] == page, (
            f"{qid}: cited page {item['page']} != block's stored page {page}"
        )

    print(f"all waymo_gt_verified records resolve against the real corpus DB ({checked} checks)")


if __name__ == "__main__":
    test_structural_invariants()
    if DB_PATH is not None:
        test_gold_ids_resolve_against_corpus_db()
    else:
        print("skipping DB cross-check -- no real Waymo corpus DB found near this checkout")
