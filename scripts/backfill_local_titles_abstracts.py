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


# Titles that no heuristic can recover, because the PDF's own metadata (which authoring tools fill
# with the FILE NAME) is word-shaped and so passes `_looks_like_a_title`: "Safety Impact Crash Type
# Manuscript", "Automated Brake Response Onset_submission". The paper's real title is printed on its
# page 1 in every case; each value below was read off that page and is the operator asserting an
# identity, the same role `ingest_local.TITLE_PREFIX` plays at ingest time. Kept as data rather than
# as more regexes: the failure class is "metadata is a filename", which has no reliable pattern.
_TITLE_CORRECTIONS = {
    "local:4087ccce4c01": "RAVE Checklist: Recommendations for Overcoming Challenges in "
                          "Retrospective Safety Studies of Automated Driving Systems",
    "local:ac6107f22da9": "Automated Brake Onset Detection in Naturalistic Driving Data",
    "local:750223d487eb": "Developing a Safety Management System for the Autonomous Vehicle "
                          "Industry",
    "local:73b22bed599f": "Building Scientific Consensus on the Crash Safety Performance of "
                          "Automated Driving Systems",
    "local:6b9ccd0431f6": "Comparison of Waymo Rider-Only Crash Rates by Crash Type to Human "
                          "Benchmarks at 56.7 Million Miles",
    "local:b12ef27e3cd6": "Refinements in Benchmarking for Vulnerable Road User Collisions by "
                          "Comparing Naturalistic Driving and Police-Report Data",
    "local:24cb2ca8ce9b": "Potential Safety Benefits Associated with Speed Limit Compliance in "
                          "San Francisco and Phoenix",
    "local:aa069e80dac9": "Representative Pedestrian Collision Injury Risk Distributions for a "
                          "Dense-Urban US ODD Using Naturalistic Dash Camera Data",
    "local:e402895b56ca": "Building a Credible Case for Safety: Waymo’s Approach for the "
                          "Determination of Absence of Unreasonable Risk",
    "local:5a2917ce1032": "A Survey of Autonomous Driving: Common Practices and Emerging "
                          "Technologies",
    # Causal corpus (--db ../research-system-rag-data/papers.db). The first is the worst case seen
    # in either corpus: a LaTeX toolchain wrote the author's own Windows path into the metadata.
    # The books need asserting rather than recovering -- a book's page 1 is a cover whose largest
    # line is often the author list, so line-based recovery picks the wrong thing.
    "local:57e9cb2fa076": "Improving the Sensitivity of Online Controlled Experiments by "
                          "Utilizing Pre-Experiment Data",
    "local:7423c6d63786": "Peeking at A/B Tests: Why It Matters, and What to Do About It",
    "local:dfe850b3281a": "Causal Inference and Discovery in Python: Unlock the Secrets of Modern "
                          "Causal Machine Learning with DoWhy, EconML, PyTorch and More",
    "local:f0929288d4f3": "Causal Inference in Python: Applying Causal Inference in the Tech "
                          "Industry",
    "local:f6c64e1e8c7d": "Elements of Causal Inference: Foundations and Learning Algorithms",
    "local:14b7e283bdcd": "Trustworthy Online Controlled Experiments: A Practical Guide to A/B "
                          "Testing",
    "local:54d6ca71dda9": "Causal Inference and Machine Learning in Economics, Social, and Health "
                          "Sciences",
}


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
        # An asserted correction outranks recovery: it was read off the paper, not guessed.
        corrected = _TITLE_CORRECTIONS.get(paper_id)
        if corrected is None and not looks_like_a_title(title):
            corrected = recover_title(blocks, looks_like_a_title)
        if corrected and corrected != title:
            title_fixes.append((paper_id, title, corrected))
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
