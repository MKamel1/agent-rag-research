"""Find the same paper ingested twice under two different ids.

The pipeline's only dedup is (1) `mint_local_ref`'s sha256 over PDF BYTES -- so an identical file
under a different name is idempotent -- and (2) `detect_arxiv_id`, which folds a drop-in copy onto
its arXiv id when the id is in the filename or page-1 text. Neither compares titles or body text,
so the same paper arriving as two differently-encoded PDFs with no detectable arXiv id is ingested
twice. `papers.abstract` cannot be used to catch it either: every `local:` (drop-in) row has an
empty abstract. This compares CHUNK TEXT instead, which every stored paper has.

Two-stage so it stays cheap on a 1,745-paper corpus: block on shared title tokens to get candidate
pairs, then confirm with 5-gram shingle Jaccard over each paper's first 40 chunks. Measured
separation is wide -- true duplicates score 0.68-1.00, genuinely different papers with near-identical
titles (e.g. the 2023 vs 2024 CommonRoad competition reports) score 0.002-0.12 -- so 0.30 sits in
empty space rather than on a slope.

Read-only. Prints; deletes nothing. Use `python -m app.delete_docs <id> --yes` to act on a finding.
"""

import argparse
import itertools
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DUPLICATE_THRESHOLD = 0.30
_STOPWORDS = {"using", "with", "from", "that", "this", "their", "have", "been",
              "which", "were", "based", "paper", "study"}


def title_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (title or "").lower())} - _STOPWORDS


def shingles(conn, paper_id: str, k: int = 5, chunk_limit: int = 40) -> set[tuple[str, ...]]:
    text = " ".join(
        row[0] for row in conn.execute(
            "select text from chunks where paper_id=? order by rowid limit ?",
            (paper_id, chunk_limit),
        )
    )
    words = re.findall(r"[a-z]{3,}", text.lower())[:8000]
    return {tuple(words[i:i + k]) for i in range(max(0, len(words) - k))}


def candidate_pairs(rows) -> set[tuple[str, str]]:
    """Block on title tokens. A bucket bigger than `max_bucket` is a junk title shared by many
    papers ("untitled", "Research article" -- drop-in PDFs whose title extraction failed), not a
    real signal, so it is skipped rather than emitting a quadratic blowup of false pairs."""
    buckets = defaultdict(list)
    for paper_id, title in rows:
        for token in sorted(title_tokens(title))[:6]:
            buckets[token].append(paper_id)
    pairs = set()
    for bucket in buckets.values():
        if len(bucket) <= 60:
            for a, b in itertools.combinations(sorted(bucket), 2):
                pairs.add((a, b))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(REPO_ROOT / "waymo/data/papers.db"))
    parser.add_argument("--curated", default=str(REPO_ROOT / "fixtures/waymo/waymo_authored_ids.txt"))
    parser.add_argument("--threshold", type=float, default=DUPLICATE_THRESHOLD)
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = conn.execute("select paper_id, title from papers").fetchall()
    titles = dict(rows)
    curated = {line.strip() for line in Path(args.curated).read_text().splitlines() if line.strip()}

    pairs = candidate_pairs(rows)
    cache: dict[str, set] = {}
    found = []
    for a, b in pairs:
        ta, tb = title_tokens(titles[a]), title_tokens(titles[b])
        if not ta or not tb or len(ta & tb) / len(ta | tb) < 0.35:
            continue
        for pid in (a, b):
            if pid not in cache:
                cache[pid] = shingles(conn, pid)
        if not cache[a] or not cache[b]:
            continue
        score = len(cache[a] & cache[b]) / len(cache[a] | cache[b])
        if score >= args.threshold:
            found.append((score, a, b))

    found.sort(reverse=True)
    print(f"{len(rows)} papers, {len(pairs)} candidate pairs -> {len(found)} duplicate pairs\n")
    both = one = neither = 0
    for score, a, b in found:
        if a in curated and b in curated:
            tag, both = "BOTH CURATED (a curated query can cite it twice)", both + 1
        elif (a in curated) ^ (b in curated):
            tag, one = "ONE CURATED (the other copy answers 'not Waymo')", one + 1
        else:
            tag, neither = "neither curated", neither + 1
        print(f"  {score:.3f}  {a:22s} {b:22s}  {tag}")
        print(f"          {(titles[a] or '')[:70]}")
    print(f"\nboth curated: {both} | one curated: {one} | neither: {neither}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
