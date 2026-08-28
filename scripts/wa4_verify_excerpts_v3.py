#!/usr/bin/env python3
"""Verify all supported sub-part excerpts match DB chunks (v3)"""
import sqlite3
import json
import sys
from difflib import SequenceMatcher

DB_PATH = "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db"

def verify_excerpt(chunk_text, excerpt):
    """Excerpt must be an EXACT (whitespace-normalized) substring of chunk_text.

    ponytail note: v3 of this script accepted a >=85% difflib ratio as a "pass" for
    non-exact matches. That is precisely the hole that let V3-007/008/009's hand-typed
    excerpts through -- a paraphrase can score 85%+ similar without being present in
    the DB at all. The rule this GT set needs is "the excerpt is a real DB span", which
    is binary: exact substring or fail. The ratio is still reported (diagnostic only,
    e.g. to help find the nearest real span when repairing a failure) but never used
    to pass an item.
    """
    chunk_norm = " ".join(chunk_text.split())
    excerpt_norm = " ".join(excerpt.split())

    if excerpt_norm in chunk_norm:
        return True, 1.0, "exact"

    ratio = SequenceMatcher(None, excerpt_norm, chunk_norm).ratio()
    return False, ratio, "fail"

conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)

DEFAULT_TARGET = "docs/eval-reports/data/2026-08-28-wa4-gt/author-B/wa4_items_v3.json"
target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET

with open(target) as f:
    data = json.load(f)

results = {"pass": 0, "fail": 0, "failures": []}

for item in data["items"]:
    for sp in item["sub_parts"]:
        if sp["status"] == "supported":
            ref = sp["gold_ref"]
            chunk_id = ref["block_id"]
            excerpt = ref["excerpt"]
            
            row = conn.execute(
                "SELECT text FROM chunks WHERE chunk_id = ?",
                (chunk_id,)
            ).fetchone()
            
            if not row:
                results["fail"] += 1
                results["failures"].append({
                    "item": item["id"],
                    "chunk_id": chunk_id,
                    "reason": "chunk_not_found"
                })
                continue
            
            passed, coverage, detail = verify_excerpt(row[0], excerpt)
            if passed:
                results["pass"] += 1
            else:
                results["fail"] += 1
                results["failures"].append({
                    "item": item["id"],
                    "chunk_id": chunk_id,
                    "coverage": coverage,
                    "detail": detail
                })

conn.close()

print(f"Excerpt verification results:")
print(f"  Pass: {results['pass']}")
print(f"  Fail: {results['fail']}")
print(f"  Total: {results['pass'] + results['fail']}")

if results["failures"]:
    print(f"\nFailures:")
    for f in results["failures"]:
        print(f"  {f['item']}: {f.get('reason', f.get('detail'))}")
    sys.exit(1)
else:
    print("\n✓ All excerpts verified")
    sys.exit(0)
