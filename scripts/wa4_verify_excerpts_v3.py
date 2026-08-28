#!/usr/bin/env python3
"""Verify all supported sub-part excerpts match DB chunks (v3)"""
import sqlite3
import json
import sys
from difflib import SequenceMatcher

DB_PATH = "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db"

def verify_excerpt(chunk_text, excerpt):
    """Check if excerpt is a substring of chunk_text (whitespace-normalized)"""
    chunk_norm = " ".join(chunk_text.split())
    excerpt_norm = " ".join(excerpt.split())
    
    if excerpt_norm in chunk_norm:
        return True, 1.0, "exact"
    
    matcher = SequenceMatcher(None, excerpt_norm, chunk_norm)
    ratio = matcher.ratio()
    status = "pass" if ratio >= 0.85 else "fail"
    return ratio >= 0.85, ratio, status

conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)

with open("docs/eval-reports/data/2026-08-28-wa4-gt/author-B/wa4_items_v3.json") as f:
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
