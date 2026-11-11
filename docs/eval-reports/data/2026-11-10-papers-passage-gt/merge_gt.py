"""Merge every author-*/items.json into standards_gt.json, re-verifying each against the DB first.

    python merge_gt.py            # refuses to write if any author file fails verification
"""
import collections
import glob
import json
import sys

import gt_tools

paths = sorted(glob.glob("author-*/items.json"))
if any(gt_tools.verify(p, write=True) for p in paths):
    sys.exit("verification failed -- nothing merged")
items = [it for p in paths for it in json.load(open(p))["ground_truth"]]
ids = [it["question_id"] for it in items]
assert len(ids) == len(set(ids)), "duplicate question_id across authors"
meta = {
    "description": "Passage-level retrieval ground truth over a seeded random sample of 64 papers from the main corpus (one deep-passage item per paper). Complements the paper-level 210-question set. Items carry paper_topic so off-topic papers can be excluded.",
    "protocol": "docs/eval-reports/data/2026-11-10-standards-gt/AUTHORING-PROTOCOL.md",
    "corpus": "papers (main corpus)",
    "sources": paths,
    "n": len(items),
    "by_tests": collections.Counter(it["tests"] for it in items),
    "by_paper_topic": collections.Counter(it["paper_topic"] for it in items),
    "by_dimension": collections.Counter(it["dimension"] for it in items),
    "regrounding": "chunk ids move on a rechunk; excerpt_block_id + passage_excerpt do not. "
                   "Re-run merge_gt.py after any rechunk to refresh gold_chunk_id/gold_block_id.",
}
json.dump({"_metadata": meta, "ground_truth": items}, open("papers_passage_gt.json", "w"),
          indent=1, ensure_ascii=False)
print(json.dumps(meta, indent=1))
