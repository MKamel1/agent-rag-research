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
    "description": "Standards-corpus (av_standards) retrieval ground truth. Authored blind to "
                   "retrieval output; every excerpt machine-verified verbatim against its gold "
                   "chunk; every absence scan re-run at merge time.",
    "protocol": "docs/eval-reports/data/2026-11-10-standards-gt/AUTHORING-PROTOCOL.md",
    "corpus": "av_standards",
    "sources": paths,
    "n": len(items),
    "by_tests": collections.Counter(it["tests"] for it in items),
    "by_dimension": collections.Counter(it["dimension"] for it in items),
    "regrounding": "chunk ids move on a rechunk; excerpt_block_id + passage_excerpt do not. "
                   "Re-run merge_gt.py after any rechunk to refresh gold_chunk_id/gold_block_id.",
}
json.dump({"_metadata": meta, "ground_truth": items}, open("standards_gt.json", "w"),
          indent=1, ensure_ascii=False)
print(json.dumps(meta, indent=1))
