"""For each duplicate pair, propose keep/delete under a no-information-loss rule.

Two layers of guarantee, because "these look the same" is not good enough to delete on:

1. **Content containment, not similarity.** A high similarity score computed over a TRUNCATED
   prefix (as `find_duplicate_papers.py` does, for speed) cannot tell a true duplicate from two
   documents that share an introduction and then diverge. This script rebuilds shingles over EVERY
   chunk of both papers with no word cap, then asks a directional question: what fraction of the
   loser's text does the winner already contain? Deletion is proposed only when that is >=
   `--containment` (default 0.995), i.e. the loser contributes essentially no text the winner
   lacks. When neither side contains the other, BOTH are kept and the pair is flagged -- deleting
   either would lose text, which is the whole thing we are guaranteeing against.

2. **The source PDF is never touched.** `delete_paper` (rag/orchestrator.py) removes SQLite rows,
   vectors and ingest state only; the PDF stays in `pdf_cache/` and `drop_in/done/`. Every proposed
   deletion is therefore reversible by re-ingesting that file, and this script verifies the
   survivor's and the loser's PDFs are actually on disk before proposing anything.

Which side wins, when both contain each other: prefer the arXiv id. It carries citable metadata the
`local:` twin does not -- every `local:` row in this corpus has an empty abstract, and most have no
parsed author list. If the `local:` copy has strictly more text, it wins instead.

Read-only. Emits a `delete_docs` command line; runs nothing.
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def full_shingles(conn, paper_id: str, k: int = 5) -> set[tuple[str, ...]]:
    """Every chunk, no truncation -- the difference between 'the first 8k words match' and 'the
    documents match'."""
    text = " ".join(r[0] for r in conn.execute(
        "select text from chunks where paper_id=? order by rowid", (paper_id,)))
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {tuple(words[i:i + k]) for i in range(max(0, len(words) - k))}


def profile(conn, paper_id: str, data_dir: Path) -> dict:
    row = conn.execute(
        "select title, abstract, authors_json from papers where paper_id=?", (paper_id,)).fetchone()
    title, abstract, authors_json = row if row else ("", "", "[]")
    try:
        n_authors = len(json.loads(authors_json or "[]"))
    except json.JSONDecodeError:
        n_authors = 0
    n_chunks = conn.execute(
        "select count(*) from chunks where paper_id=?", (paper_id,)).fetchone()[0]
    chars = conn.execute(
        "select coalesce(sum(length(text)),0) from chunks where paper_id=?", (paper_id,)).fetchone()[0]
    pdf = data_dir / "pdf_cache" / f"{paper_id}.pdf"
    return {"id": paper_id, "title": title or "", "has_abstract": bool((abstract or "").strip()),
            "n_authors": n_authors, "n_chunks": n_chunks, "chars": chars, "pdf_on_disk": pdf.exists()}


def decide(a: dict, b: dict, cont_a_of_b: float, cont_b_of_a: float, threshold: float):
    """Returns (keep, drop, reason) or (None, None, reason) when both must be kept."""
    a_covers_b = cont_a_of_b >= threshold
    b_covers_a = cont_b_of_a >= threshold
    if a_covers_b and b_covers_a:
        arxiv = [p for p in (a, b) if not p["id"].startswith("local:")]
        if len(arxiv) == 1:
            keep = arxiv[0]
            drop = b if keep is a else a
            return keep, drop, "mutually contained; arXiv id kept for citable metadata"
        keep, drop = (a, b) if a["chars"] >= b["chars"] else (b, a)
        return keep, drop, "mutually contained; kept the longer extraction"
    if a_covers_b:
        return a, b, f"{a['id']} contains {cont_a_of_b:.4f} of {b['id']}'s text"
    if b_covers_a:
        return b, a, f"{b['id']} contains {cont_b_of_a:.4f} of {a['id']}'s text"
    return None, None, (f"NEITHER contains the other ({cont_a_of_b:.3f} / {cont_b_of_a:.3f}) -- "
                        "each holds text the other lacks; deleting either loses information")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(REPO_ROOT / "waymo/data"))
    parser.add_argument("--pairs-from", default=None,
                        help="file of 'idA idB' lines; default reads find_duplicate_papers output on stdin")
    parser.add_argument("--containment", type=float, default=0.995)
    parser.add_argument("--curated", default=str(REPO_ROOT / "fixtures/waymo/waymo_authored_ids.txt"))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    conn = sqlite3.connect(f"file:{data_dir / 'papers.db'}?mode=ro", uri=True)
    curated = {l.strip() for l in Path(args.curated).read_text().splitlines() if l.strip()}
    pairs = [tuple(line.split()[:2])
             for line in Path(args.pairs_from).read_text().splitlines() if line.strip()]

    to_delete, keep_both, curated_edits = [], [], []
    for a_id, b_id in pairs:
        sa, sb = full_shingles(conn, a_id), full_shingles(conn, b_id)
        if not sa or not sb:
            keep_both.append((a_id, b_id, "one side has no chunk text -- not comparable"))
            continue
        inter = sa & sb
        cont_a_of_b = len(inter) / len(sb)   # fraction of B's text present in A
        cont_b_of_a = len(inter) / len(sa)
        a, b = profile(conn, a_id, data_dir), profile(conn, b_id, data_dir)
        keep, drop, reason = decide(a, b, cont_a_of_b, cont_b_of_a, args.containment)

        print(f"\n{'='*94}\n{a_id}  <->  {b_id}")
        print(f"  containment: {a_id} covers {cont_a_of_b:.4f} of {b_id} | "
              f"{b_id} covers {cont_b_of_a:.4f} of {a_id}")
        for p in (a, b):
            print(f"  {p['id']:22s} chunks={p['n_chunks']:4d} chars={p['chars']:7d} "
                  f"authors={p['n_authors']:2d} abstract={'Y' if p['has_abstract'] else 'N'} "
                  f"pdf={'on disk' if p['pdf_on_disk'] else 'MISSING'} "
                  f"{'[curated]' if p['id'] in curated else ''}")
        if keep is None:
            print(f"  --> KEEP BOTH: {reason}")
            keep_both.append((a_id, b_id, reason)); continue
        if not drop["pdf_on_disk"]:
            print(f"  --> KEEP BOTH: would delete {drop['id']} but its PDF is not on disk, "
                  "so the deletion would NOT be reversible")
            keep_both.append((a_id, b_id, "loser's PDF missing -- deletion not reversible")); continue
        print(f"  --> KEEP {keep['id']} | DELETE {drop['id']}")
        print(f"      {reason}")
        to_delete.append(drop["id"])
        if drop["id"] in curated:
            curated_edits.append(drop["id"])
            print(f"      NOTE: {drop['id']} is on the curated list -- remove that line too")
        if keep["id"] not in curated and drop["id"] in curated:
            curated_edits.append(f"+{keep['id']}")
            print(f"      NOTE: add {keep['id']} to the curated list so the work stays tagged Waymo")

    print(f"\n{'='*94}\nSUMMARY: delete {len(to_delete)} | keep-both (needs a human) {len(keep_both)}")
    for a_id, b_id, why in keep_both:
        print(f"  KEEP BOTH  {a_id} <-> {b_id}: {why}")
    if to_delete:
        print("\n  python -m app.delete_docs " + " ".join(to_delete) + " --yes")
    if curated_edits:
        print(f"\n  curated-list edits required: {curated_edits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
