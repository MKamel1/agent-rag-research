# ruff: noqa: E501  (long lines are printed report rows and usage text)
"""Read-only census of reference lists indexed as content (CQ-6, Part B).

Opens each corpus only as file:<path>?mode=ro and streams chunks in one pass.
Nothing is written to any database.

Two signals, deliberately kept separate:

  SECTION (verified against section_path): the last element of section_path (split on
  " > "), after lowercasing, stripping leading numbering such as "7." / "7 " / "VI.",
  and stripping trailing ":" or ".", is exactly one of: references, bibliography,
  works cited, literature cited, reference list.

  HEURISTIC (content, any section): a chunk is "reference-like" when it has at least
  5 CITATION LINES and its YEAR DENSITY is at least 0.5 years per non-empty line.
    - a CITATION LINE is a non-empty line that STARTS (after whitespace) with
      (a) a bracketed or dotted number such as "[12]" / "12. A", or (b) a bullet
      "-" / "•" / "*", or (c) a surname with initials "Surname, X." / "Surname, X.Y.",
      AND the line contains a 4-digit year 19xx or 20xx.
      Anchoring to the line start drops prose such as "Kim et al. (2018) considered".
      Known false negatives: wrapped entries whose first line has no marker.
      Known false positives: lists of in-text citations written as bullets.
    - YEAR DENSITY = number of year tokens (19xx|20xx, word-bounded) in the chunk
      divided by the number of non-empty lines.
  The heuristic is an estimate. It can miss wrapped entries and can flag dense
  tables of years. Its output is labelled "heuristic" everywhere.

A chunk is a STUB when its stripped text is 80 characters or fewer (typically just
the heading). A chunk is REAL BIBLIOGRAPHY when it is section-matched and not a stub.

Usage:
  conda run -n agent-rag-research python reference_census.py --db <papers.db> --name <label>
"""

import argparse
import re
import sqlite3
from collections import Counter

SECTION_NAMES = {"references", "bibliography", "works cited", "literature cited", "reference list"}
STUB_MAX = 80
MIN_CITATION_LINES = 5
MIN_YEAR_DENSITY = 0.5
TOP_N = 15
EXAMPLES = 5

RE_LEAD_NUM = re.compile(r"^\s*(?:\d+|[ivxlc]+)\s*[.)]?\s*", re.IGNORECASE)
RE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
RE_ENTRY_START = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.\s|[-\u2022*]\s|[A-Z][A-Za-z'\-]+,\s+(?:[A-Z]\.\s?){1,3})"
)


def section_is_reference(section_path: str) -> bool:
    last = (section_path or "").split(" > ")[-1]
    name = RE_LEAD_NUM.sub("", last).strip().lower().rstrip(":.").strip()
    return name in SECTION_NAMES


def is_citation_line(line: str) -> bool:
    if not RE_YEAR.search(line):
        return False
    return bool(RE_ENTRY_START.search(line))


def heuristic_reference_like(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    cite = sum(1 for ln in lines if is_citation_line(ln))
    years = len(RE_YEAR.findall(text))
    return cite >= MIN_CITATION_LINES and years / len(lines) >= MIN_YEAR_DENSITY


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    titles = dict(conn.execute("select paper_id, title from papers"))

    total_chunks = total_chars = 0
    sec_chunks = sec_chars = 0
    sec_stub = sec_real = 0
    sec_stub_chars = sec_real_chars = 0
    heur_chunks = heur_chars = 0
    heur_only_chunks = heur_only_chars = 0
    union_chunks = union_chars = 0
    docs_real = set()
    docs_any = set()
    per_doc_chars = Counter()
    per_doc_chunks = Counter()
    ex_sec_real, ex_sec_stub, ex_heur = [], [], []

    cur = conn.execute("select chunk_id, paper_id, section_path, text from chunks")
    for chunk_id, paper_id, section_path, text in cur:
        text = text or ""
        n = len(text)
        total_chunks += 1
        total_chars += n
        is_sec = section_is_reference(section_path)
        is_heur = heuristic_reference_like(text)
        if is_heur:
            heur_chunks += 1
            heur_chars += n
        if is_sec:
            sec_chunks += 1
            sec_chars += n
            if len(text.strip()) <= STUB_MAX:
                sec_stub += 1
                sec_stub_chars += n
                if len(ex_sec_stub) < EXAMPLES:
                    ex_sec_stub.append((chunk_id, section_path, text.strip()[:60]))
            else:
                sec_real += 1
                sec_real_chars += n
                docs_real.add(paper_id)
                if len(ex_sec_real) < EXAMPLES:
                    ex_sec_real.append(
                        (chunk_id, section_path, text.strip()[:60].replace("\n", " | "))
                    )
        if is_heur and not is_sec:
            heur_only_chunks += 1
            heur_only_chars += n
            if len(ex_heur) < EXAMPLES:
                ex_heur.append((chunk_id, section_path, text.strip()[:60].replace("\n", " | ")))
        if is_sec or is_heur:
            union_chunks += 1
            union_chars += n
            docs_any.add(paper_id)
            per_doc_chars[paper_id] += n
            per_doc_chunks[paper_id] += 1
    conn.close()

    def pct(a, b):
        return f"{100.0 * a / b:.2f}%" if b else "n/a"

    print(f"== {args.name}  db={args.db}")
    print(f"total chunks={total_chunks} total chars={total_chars}")
    print("-- SECTION (verified against section_path)")
    print(
        f"chunks={sec_chunks} ({pct(sec_chunks, total_chunks)})  chars={sec_chars} ({pct(sec_chars, total_chars)})"
    )
    print(f"  heading-only stubs (<= {STUB_MAX} chars): {sec_stub} chunks, {sec_stub_chars} chars")
    print(f"  real bibliography text: {sec_real} chunks, {sec_real_chars} chars")
    print(f"  documents with real bibliography text: {len(docs_real)}")
    print(
        f"-- HEURISTIC (content, any section; >= {MIN_CITATION_LINES} citation lines and year density >= {MIN_YEAR_DENSITY})"
    )
    print(
        f"chunks={heur_chunks} ({pct(heur_chunks, total_chunks)})  chars={heur_chars} ({pct(heur_chars, total_chars)})"
    )
    print(
        f"  heuristic-only (not section-matched): {heur_only_chunks} chunks, {heur_only_chars} chars"
    )
    print("-- UNION (section OR heuristic)")
    print(
        f"chunks={union_chunks} ({pct(union_chunks, total_chunks)})  chars={union_chars} ({pct(union_chars, total_chars)})"
    )
    print(f"documents with any reference chunk: {len(docs_any)}")
    print()
    print(f"-- TOP {TOP_N} DOCUMENTS BY REFERENCE CHARS (union)")
    for pid, chars in per_doc_chars.most_common(TOP_N):
        print(
            f"  {pid:24s} ref_chunks={per_doc_chunks[pid]:<4d} ref_chars={chars:<8d} {(titles.get(pid) or '')[:80]}"
        )
    print()
    print(
        "-- EXAMPLES: section-matched real bibliography (chunk_id | section_path | first 60 chars)"
    )
    for row in ex_sec_real:
        print("  " + " | ".join(row))
    print("-- EXAMPLES: section-matched heading-only stubs")
    for row in ex_sec_stub:
        print("  " + " | ".join(row))
    print("-- EXAMPLES: heuristic-only (not section-matched)")
    for row in ex_heur:
        print("  " + " | ".join(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
