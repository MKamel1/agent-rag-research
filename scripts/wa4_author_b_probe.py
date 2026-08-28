#!/usr/bin/env python3
"""
W-A4 Author B probing and extraction script.

Usage:
  python scripts/wa4_author_b_probe.py --search <query> [--k 10]
  python scripts/wa4_author_b_probe.py --extract <paper_id> <block_id>
  python scripts/wa4_author_b_probe.py --probe-lexical <query>
  python scripts/wa4_author_b_probe.py --probe-semantic <query>
"""

import sqlite3
import json
import sys
import argparse
from pathlib import Path
import difflib

def get_db_path():
    """Get the absolute path to papers.db"""
    # Check if we're in a worktree or main checkout
    cwd = Path.cwd()

    # Try multiple possible locations
    candidates = [
        Path("/home/omar/ai-projects/research-system-rag/waymo/data/papers.db"),
        cwd / "waymo/data/papers.db",
        cwd.parent.parent / "waymo/data/papers.db",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"papers.db not found. Tried: {candidates}")


def get_db_conn(read_only=True):
    """Open a read-only connection to papers.db"""
    db_path = get_db_path()
    if read_only:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def cmd_extract_block(paper_id, block_id):
    """Extract text from a specific block"""
    conn = get_db_conn()
    row = conn.execute(
        "SELECT block_id, text, section_path FROM blocks WHERE block_id = ?",
        (block_id,)
    ).fetchone()

    if not row:
        print(f"ERROR: block not found: {block_id}", file=sys.stderr)
        sys.exit(1)

    result = {
        "block_id": row["block_id"],
        "text": row["text"],
        "section_path": row["section_path"],
    }
    print(json.dumps(result, indent=2))
    conn.close()


def cmd_extract_chunk(chunk_id):
    """Extract text from a specific chunk"""
    conn = get_db_conn()
    row = conn.execute(
        "SELECT chunk_id, text, anchor_json, section_path FROM chunks WHERE chunk_id = ?",
        (chunk_id,)
    ).fetchone()

    if not row:
        print(f"ERROR: chunk not found: {chunk_id}", file=sys.stderr)
        sys.exit(1)

    anchor = json.loads(row["anchor_json"])
    result = {
        "chunk_id": row["chunk_id"],
        "text": row["text"],
        "section_path": row["section_path"],
        "anchor": anchor,
    }
    print(json.dumps(result, indent=2))
    conn.close()


def cmd_probe_lexical(query):
    """Probe for a query using lexical search (SQL LIKE)"""
    conn = get_db_conn()

    # Search in chunks (preferred)
    chunk_hits = conn.execute(
        "SELECT COUNT(*) as cnt FROM chunks WHERE text LIKE ?",
        (f"%{query}%",)
    ).fetchone()["cnt"]

    # Count total chunks
    total_chunks = conn.execute(
        "SELECT COUNT(*) as cnt FROM chunks"
    ).fetchone()["cnt"]

    # Get sample matches
    samples = conn.execute(
        "SELECT chunk_id, text FROM chunks WHERE text LIKE ? LIMIT 3",
        (f"%{query}%",)
    ).fetchall()

    result = {
        "query": query,
        "hits": chunk_hits,
        "denominator": total_chunks,
        "hit_rate": chunk_hits / total_chunks if total_chunks > 0 else 0,
        "sample_matches": [
            {"chunk_id": s["chunk_id"], "text": s["text"][:200]}
            for s in samples
        ]
    }

    print(json.dumps(result, indent=2))
    conn.close()


def cmd_check_excerpt_fidelity(chunk_id, excerpt_text):
    """Check if an excerpt is a good match for a chunk using difflib"""
    conn = get_db_conn()
    row = conn.execute(
        "SELECT text FROM chunks WHERE chunk_id = ?",
        (chunk_id,)
    ).fetchone()

    if not row:
        print(f"ERROR: chunk not found: {chunk_id}", file=sys.stderr)
        sys.exit(1)

    chunk_text = row["text"]

    # Normalize whitespace
    excerpt_norm = " ".join(excerpt_text.split())
    chunk_norm = " ".join(chunk_text.split())

    # Check if excerpt is a substring of chunk (normalized)
    if excerpt_norm in chunk_norm:
        print(json.dumps({
            "status": "exact_match",
            "coverage": 1.0,
            "message": "Excerpt is exact substring of chunk text (whitespace normalized)"
        }, indent=2))
    else:
        # Use SequenceMatcher to get coverage estimate
        matcher = difflib.SequenceMatcher(None, excerpt_norm, chunk_norm)
        ratio = matcher.ratio()
        print(json.dumps({
            "status": "partial_match" if ratio >= 0.85 else "poor_match",
            "coverage": ratio,
            "message": f"Difflib coverage: {ratio:.1%}",
            "recommendation": "ACCEPT" if ratio >= 0.85 else "REJECT - substitute exact DB span"
        }, indent=2))

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="W-A4 Author B probing script")
    subparsers = parser.add_subparsers(dest="command")

    extract_block = subparsers.add_parser("extract-block", help="Extract block text")
    extract_block.add_argument("paper_id")
    extract_block.add_argument("block_id")

    extract_chunk = subparsers.add_parser("extract-chunk", help="Extract chunk text")
    extract_chunk.add_argument("chunk_id")

    probe_lex = subparsers.add_parser("probe-lexical", help="Lexical probe (SQL LIKE)")
    probe_lex.add_argument("query")

    fidelity = subparsers.add_parser("check-fidelity", help="Check excerpt fidelity")
    fidelity.add_argument("chunk_id")
    fidelity.add_argument("excerpt_text")

    args = parser.parse_args()

    if args.command == "extract-block":
        cmd_extract_block(args.paper_id, args.block_id)
    elif args.command == "extract-chunk":
        cmd_extract_chunk(args.chunk_id)
    elif args.command == "probe-lexical":
        cmd_probe_lexical(args.query)
    elif args.command == "check-fidelity":
        cmd_check_excerpt_fidelity(args.chunk_id, args.excerpt_text)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
