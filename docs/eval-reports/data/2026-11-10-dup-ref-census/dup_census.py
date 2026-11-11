# ruff: noqa: E501  (long lines are printed report rows and usage text)
"""Read-only duplicate-document census for a papers.db corpus (CQ-6, Part A).

Two independent candidate signals, both computed by streaming the corpus:

  (i)  title: papers whose titles are equal after lowercasing and removing every
       non-alphanumeric character (punctuation and whitespace). Titles shorter than
       10 normalised characters are ignored (too little signal).
  (ii) text: papers whose first 2,000 characters of concatenated chunk text are
       identical. Chunks are concatenated in rowid order, separated by a single
       newline. Papers whose prefix is shorter than 200 characters are ignored.
       A second, looser tier compares the same prefix after collapsing whitespace
       and lowercasing, reported separately.

Output is printed to stdout. Nothing is written to the corpus. The database is
opened only as file:<path>?mode=ro.

Usage:
  conda run -n agent-rag-research python dup_census.py --db <papers.db> [--table]
  conda run -n agent-rag-research python dup_census.py --db <papers.db> --pair ID_A ID_B [--pair ID_C ID_D ...]

  --table   also print one line per paper (id, chunks, chars, title) for hand checks
  --pair    print full-text 5-word shingle Jaccard and containment for each pair
"""

import argparse
import hashlib
import re
import sqlite3
from collections import defaultdict

PREFIX_CHARS = 2000
MIN_PREFIX = 200
MIN_TITLE = 10


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def loose(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def open_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def stream_papers(conn):
    """Yield (paper_id, title, n_chunks, n_chars, prefix) with one pass over chunks."""
    titles = dict(conn.execute("select paper_id, title from papers"))
    cur = conn.execute("select paper_id, text from chunks order by paper_id, rowid")
    current, parts, n, chars = None, [], 0, 0

    def finish(pid):
        prefix = "\n".join(parts)[:PREFIX_CHARS]
        return pid, titles.get(pid, ""), n, chars, prefix

    for pid, text in cur:
        if pid != current:
            if current is not None:
                yield finish(current)
            current, parts, n, chars = pid, [], 0, 0
        parts.append(text)
        n += 1
        chars += len(text)
    if current is not None:
        yield finish(current)


def groups_by(key_of, rows):
    buckets = defaultdict(list)
    for row in rows:
        key = key_of(row)
        if key:
            buckets[key].append(row)
    return [g for g in buckets.values() if len(g) > 1]


def shingle_set(text: str, k: int = 5) -> set:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i : i + k]) for i in range(max(0, len(words) - k + 1))}


def full_text(conn, pid: str) -> str:
    return "\n".join(
        r[0]
        for r in conn.execute("select text from chunks where paper_id=? order by rowid", (pid,))
    )


def report_group(kind, g):
    print(f"[{kind}] group of {len(g)}")
    for pid, title, n, chars, prefix in g:
        h = hashlib.sha1(prefix.encode()).hexdigest()[:10]
        print(f"    {pid:24s} chunks={n:<5d} chars={chars:<9d} prefix_sha1={h}  {title[:90]}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--pair", nargs=2, action="append", metavar=("ID_A", "ID_B"))
    args = ap.parse_args()

    conn = open_ro(args.db)
    rows = list(stream_papers(conn))
    print(f"db: {args.db}")
    print(
        f"papers with chunks: {len(rows)}  (papers table rows: {conn.execute('select count(*) from papers').fetchone()[0]})"
    )
    print(
        f"total chunks: {sum(r[2] for r in rows)}  total chunk chars: {sum(r[3] for r in rows)}\n"
    )

    if args.table:
        for pid, title, n, chars, _ in sorted(rows):
            print(f"ROW {pid}\t{n}\t{chars}\t{title}")
        print()

    title_rows = [r for r in rows if len(norm_title(r[1])) >= MIN_TITLE]
    title_groups = groups_by(lambda r: norm_title(r[1]), title_rows)
    text_rows = [r for r in rows if len(r[4]) >= MIN_PREFIX]
    text_groups = groups_by(lambda r: r[4], text_rows)
    loose_groups = groups_by(lambda r: loose(r[4]), text_rows)
    # keep loose groups that are not already exact text groups
    exact_ids = {tuple(sorted(r[0] for r in g)) for g in text_groups}
    loose_only = [g for g in loose_groups if tuple(sorted(r[0] for r in g)) not in exact_ids]

    def redundant(groups):
        return sum(len(g) - 1 for g in groups)

    print("== SUMMARY")
    print(f"title-equal groups: {len(title_groups)}  redundant docs: {redundant(title_groups)}")
    print(
        f"prefix-equal (exact 2000 chars) groups: {len(text_groups)}  redundant docs: {redundant(text_groups)}"
    )
    print(
        f"prefix-equal after lowercase+whitespace collapse, not exact: {len(loose_only)}  redundant docs: {redundant(loose_only)}"
    )
    print()

    print("== TITLE-EQUAL GROUPS")
    for g in sorted(title_groups, key=lambda g: -len(g)):
        report_group("title", g)
    print("== PREFIX-EQUAL GROUPS (exact)")
    for g in sorted(text_groups, key=lambda g: -len(g)):
        report_group("prefix", g)
    print("== PREFIX-EQUAL GROUPS (loose, not exact)")
    for g in sorted(loose_only, key=lambda g: -len(g)):
        report_group("loose", g)

    if args.pair:
        print("== PAIR CHECKS (full text, 5-word shingles)")
        for a, b in args.pair:
            sa, sb = shingle_set(full_text(conn, a)), shingle_set(full_text(conn, b))
            inter = len(sa & sb)
            jac = inter / len(sa | sb) if sa | sb else 0.0
            cont_a = inter / len(sa) if sa else 0.0
            cont_b = inter / len(sb) if sb else 0.0
            ta = conn.execute("select title from papers where paper_id=?", (a,)).fetchone()
            tb = conn.execute("select title from papers where paper_id=?", (b,)).fetchone()
            print(
                f"{a} vs {b}: jaccard={jac:.3f} contain(a in b)={cont_a:.3f} contain(b in a)={cont_b:.3f} "
                f"shingles={len(sa)}/{len(sb)}"
            )
            print(f"    A: {(ta[0] if ta else '')[:100]}")
            print(f"    B: {(tb[0] if tb else '')[:100]}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
