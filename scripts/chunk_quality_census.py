"""Chunk-quality census: how much of a corpus's index is noise, measured from SQLite alone.

Zero GPU, zero network, read-only. Counts, per corpus and per document:

  * stub chunks       -- body (text under the `title\\nsection_path` header) shorter than
                         `--stub-chars`; a heading with nothing under it
  * bare-number stubs -- body is only a clause/term number ("3.159")
  * oversized chunks  -- longer than `--oversize-chars` (candidates for embed-side truncation)
  * duplicate bodies  -- byte-identical body shared by 2+ chunks of the same document
  * thin documents    -- fewer than `--thin-chunks` chunks (previews, stubs, failed parses)

    python scripts/chunk_quality_census.py ../research-system-rag-standards/data/papers.db
    python scripts/chunk_quality_census.py DB --stub-ids-out stubs.txt   # ids, for an A/B

Instrument only: it reports, it never edits a corpus.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict

_BARE_NUMBER = re.compile(r"\d+(?:\.\d+)+\.?")


def body_of(text: str) -> str:
    """A chunk's text is `title\\nsection_path\\n\\nbody` (rag/chunker.py::_build_chunk)."""
    return text.split("\n\n", 1)[1].strip() if "\n\n" in text else ""


def census(db_path: str, stub_chars: int, oversize_chars: int, thin_chunks: int) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    titles = dict(con.execute("select paper_id, title from papers"))
    per_doc = defaultdict(Counter)
    bodies = defaultdict(Counter)
    stub_ids = []
    total = Counter()
    for chunk_id, paper_id, text in con.execute("select chunk_id, paper_id, text from chunks"):
        body = body_of(text)
        doc = per_doc[paper_id]
        doc["chunks"] += 1
        if len(body) < stub_chars:
            doc["stub"] += 1
            stub_ids.append(chunk_id)
            if _BARE_NUMBER.fullmatch(body):
                doc["bare_number"] += 1
        if len(text) > oversize_chars:
            doc["oversized"] += 1
        bodies[paper_id][body] += 1
    for paper_id, counts in bodies.items():
        per_doc[paper_id]["duplicate"] = sum(n - 1 for b, n in counts.items() if n > 1 and b)
    for doc in per_doc.values():
        total.update(doc)
    n = total["chunks"] or 1
    worst = sorted(per_doc.items(), key=lambda kv: -kv[1]["stub"])[:10]
    return {
        "db": db_path,
        "documents": len(per_doc),
        "chunks": total["chunks"],
        "stub": total["stub"], "stub_pct": round(100 * total["stub"] / n, 2),
        "bare_number": total["bare_number"],
        "oversized": total["oversized"], "oversized_pct": round(100 * total["oversized"] / n, 2),
        "duplicate": total["duplicate"],
        "thin_documents": sorted(
            (c["chunks"], p, (titles.get(p) or "")[:70])
            for p, c in per_doc.items() if c["chunks"] < thin_chunks
        ),
        "worst_stub_documents": [
            {"paper_id": p, "title": (titles.get(p) or "")[:70], "stub": c["stub"],
             "chunks": c["chunks"]} for p, c in worst if c["stub"]
        ],
        "_stub_ids": stub_ids,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("db", nargs="+", help="path(s) to a corpus papers.db")
    ap.add_argument("--stub-chars", type=int, default=40)
    ap.add_argument("--oversize-chars", type=int, default=8000)
    ap.add_argument("--thin-chunks", type=int, default=20)
    ap.add_argument("--stub-ids-out", help="write stub chunk ids here (single db only)")
    ap.add_argument("--json", action="store_true", help="full JSON instead of the summary")
    args = ap.parse_args()
    for path in args.db:
        report = census(path, args.stub_chars, args.oversize_chars, args.thin_chunks)
        stub_ids = report.pop("_stub_ids")
        if args.stub_ids_out:
            with open(args.stub_ids_out, "w") as f:
                f.write("\n".join(stub_ids) + "\n")
        if args.json:
            print(json.dumps(report, indent=1))
            continue
        print(f"{path}\n  {report['documents']} docs, {report['chunks']} chunks | "
              f"stub {report['stub']} ({report['stub_pct']}%), of which bare-number "
              f"{report['bare_number']} | oversized {report['oversized']} "
              f"({report['oversized_pct']}%) | duplicate {report['duplicate']} | "
              f"thin docs {len(report['thin_documents'])}")


def _self_check() -> None:
    assert body_of("Title\n3 Terms\n\n3.159") == "3.159"
    assert body_of("Title\nHeading\n\n") == ""
    assert _BARE_NUMBER.fullmatch("3.159") and not _BARE_NUMBER.fullmatch("3.159 audit")


if __name__ == "__main__":
    _self_check()
    main()
