"""Recover titles and abstracts for already-ingested drop-in (`local:`) papers.

Two data-quality defects, both invisible to the pipeline's own checks (`app.corpus_integrity` only
asserts every done paper has chunks and blocks, which these papers do):

1. **Junk titles.** `mint_local_ref`'s title chain trusted PDF metadata, so an authoring tool's
   default became the paper's identity: the Waymo Safety Report was stored as "February 2021", an
   IWAI poster as "PowerPoint Presentation", one paper as "1". The ingest-time fix is in
   `app/ingest_local.py::_looks_like_a_title`; this repairs rows ingested before it.

2. **Empty abstracts.** Every one of the `local:` rows has `abstract = ''` -- `mint_local_ref` never
   extracted one, because a drop-in PDF has no arXiv metadata to copy it from. The abstract is
   recoverable from the parsed blocks that are already stored, so no re-parse is needed.

Read-only by default; `--apply` writes. Never touches arXiv-sourced papers, whose metadata came
from the arXiv API and is authoritative.
"""

import argparse
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ABSTRACT_HEAD = re.compile(r"^\s*abstract\b[:.\s-]*", re.IGNORECASE)


def _load_title_checker():
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    from app.ingest_local import _looks_like_a_title
    return _looks_like_a_title


def recover_title(blocks, looks_like_a_title) -> str | None:
    """First title-shaped line from the paper's opening blocks -- the same judgement the ingest
    path now applies, run against stored text instead of a freshly-opened PDF."""
    for _page, _section, text in blocks[:6]:
        for line in (text or "").splitlines():
            stripped = line.strip()
            if looks_like_a_title(stripped):
                return stripped[:300]
    return None


def recover_abstract(blocks) -> str | None:
    """Text of the block whose section or opening word is 'Abstract'.

    Falls back to the block FOLLOWING an 'Abstract' heading when the heading sits alone in its own
    block, which is how a two-column parse usually splits it.
    """
    for index, (_page, section, text) in enumerate(blocks[:20]):
        body = (text or "").strip()
        in_abstract_section = "abstract" in (section or "").lower()
        starts_with_abstract = bool(_ABSTRACT_HEAD.match(body))
        if not (in_abstract_section or starts_with_abstract):
            continue
        stripped = _ABSTRACT_HEAD.sub("", body).strip()
        if len(stripped.split()) >= 20:
            return stripped[:4000]
        if index + 1 < len(blocks):           # heading alone in its block
            following = (blocks[index + 1][2] or "").strip()
            if len(following.split()) >= 20:
                return following[:4000]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(REPO_ROOT / "waymo/data/papers.db"))
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()

    looks_like_a_title = _load_title_checker()
    conn = sqlite3.connect(args.db)
    rows = conn.execute(
        "SELECT paper_id, title, abstract FROM papers WHERE paper_id LIKE 'local:%'"
    ).fetchall()

    title_fixes, abstract_fixes = [], []
    for paper_id, title, abstract in rows:
        blocks = conn.execute(
            "SELECT page, section_path, text FROM blocks WHERE paper_id=? ORDER BY idx LIMIT 20",
            (paper_id,),
        ).fetchall()
        if not looks_like_a_title(title):
            recovered = recover_title(blocks, looks_like_a_title)
            if recovered and recovered != title:
                title_fixes.append((paper_id, title, recovered))
        if not (abstract or "").strip():
            recovered_abstract = recover_abstract(blocks)
            if recovered_abstract:
                abstract_fixes.append((paper_id, recovered_abstract))

    print(f"local: papers: {len(rows)}")
    print(f"  junk titles recoverable : {len(title_fixes)}")
    print(f"  empty abstracts recoverable: {len(abstract_fixes)}\n")
    for paper_id, before, after in title_fixes:
        print(f"  {paper_id}\n    was: {before!r}\n    now: {after[:80]!r}")

    if not args.apply:
        print("\n(dry run -- pass --apply to write)")
        return 0
    with conn:
        conn.executemany("UPDATE papers SET title=? WHERE paper_id=?",
                         [(after, pid) for pid, _before, after in title_fixes])
        conn.executemany("UPDATE papers SET abstract=? WHERE paper_id=?",
                         [(text, pid) for pid, text in abstract_fixes])
    print(f"\napplied: {len(title_fixes)} titles, {len(abstract_fixes)} abstracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
