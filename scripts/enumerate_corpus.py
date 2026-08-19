"""CLI over `DocumentStore.scan_blocks` -- "which papers contain this pattern", exhaustively.

The same thing `McpServer.scan_corpus` exposes over MCP, for use from a shell without an MCP
client. Deliberately a thin wrapper: the scanning logic lives in the store (one implementation,
one set of tests) and this file only formats.

Use this, not a semantic query, when the answer is a LIST OF PAPERS. Ranked retrieval samples the
top `k` of a relevance ordering and cannot tell you what it missed; measured on this corpus, an
enumeration answered by retrieval alone found 3 of 4 qualifying papers, and this finds 4 of 4.
The cost is lexical false positives, which `section_path` makes cheap to reject.

    python scripts/enumerate_corpus.py 'bootstrap|resampl' --author-org Waymo
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rag.document_store import DocumentStore  # noqa: E402  (after sys.path bootstrap)

_CITING = ("related work", "literature", "background", "introduction", "references", "discussion")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pattern", help="Python regex, case-insensitive")
    parser.add_argument("--data-dir", default=str(REPO_ROOT / "waymo/data"))
    parser.add_argument("--author-org", default="Waymo",
                        help="restrict to papers CURATED as authored by this org; "
                             "pass '' to scan every paper")
    parser.add_argument("--paper-id", default=None, help="scope to one paper (definition lookup)")
    parser.add_argument("--per-paper", type=int, default=2)
    parser.add_argument("--context", type=int, default=180)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    store = DocumentStore(str(data_dir / "papers.db"), str(data_dir / "blobs"))
    rows, scanned, matched, truncated = store.scan_blocks(
        args.pattern, paper_id=args.paper_id, curated_org=args.author_org or None,
        context=args.context, max_per_paper=args.per_paper,
    )

    scope = f"curated author_org={args.author_org}" if args.author_org else "ALL PAPERS"
    print(f"scope: {scope} | pattern: {args.pattern!r}")
    print(f"papers scanned: {scanned} | papers matched: {matched}"
          f"{' | some evidence truncated' if truncated else ''}\n")
    current = None
    for paper_id, title, _block_id, page, section_path, snippet in rows:
        if paper_id != current:
            current = paper_id
            print(f"{'='*92}\n{paper_id}  {title[:66]}")
        # A hint, never a filter: section detection fails on some PDFs, and auto-excluding on it
        # would reintroduce exactly the recall hole this tool exists to close.
        hint = "  <- citing section, likely a MENTION" if any(
            c in section_path.lower() for c in _CITING) else ""
        print(f"  p.{page} [{section_path or '(no section detected -- judge from text)'}]{hint}")
        print(f"    ...{snippet}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
