# VARM-1 — passage-level three-arm split: the ≥0.95 target made reachable

**Reporting change only. No fixture item was deleted, reworded, or reclassified; no retrieval code,
config, or corpus content was touched.** Branch `VARM-1-vision-arm`, measured 2026-08-24 against
`fixtures/eval/waymo_gt_verified.json` (82 questions loaded: 68 answerable, 14 known-absent;
64 passage-scored) via `python -m app.retrieval_eval --collection waymo_av_safety --k 10`.
Raw run: [`2026-08-24-vision-arm-split.json`](2026-08-24-vision-arm-split.json) (per-question rows
included; every number below is recomputable from it).

**Weight caveat:** this run used `hybrid_dense_weight=0.7` — the live config value after FUSE-1's
tuning (changed from 0.5 earlier today). It is stamped in the JSON's `scoring_rule`. Numbers here
are not comparable to reports produced under 0.5 without that caveat attached.

Operator target: passage-level precision **≥ 0.95**. Before this change that target was not merely
unmet — it was unsatisfiable by construction, because four answerable items whose answers exist
only inside a figure sat in the passage-level denominator.

## The three arms

`passage_level.by_vision_status`, same hit rule as always (`gold_block_id` anywhere in the returned
top-10 = hit; P@1 = gold block at rank exactly 1):

| arm | n | block R@10 | block MRR | block P@1 | paper R@10 |
|---|---|---|---|---|---|
| `text_answerable` (the ≥0.95 arm) | **60** | 0.8167 (49/60) | 0.5223 | 0.3667 (22/60) | 0.9500 |
| `vision` | **4** | 0.0000 (0/4) | 0.0000 | 0.0000 (0/4) | **1.0000 (4/4)** |
| `overall` (retained unpartitioned, for diff compatibility) | 64 | 0.7656 (49/64) | 0.4896 | 0.3438 (22/64) | — |

The four vision items (`Q-WAYB-027`, `Q-GTA-042`, `Q-GTA-043`, `Q-GTA-044`) each retrieved their
gold paper at rank **1** and still missed the gold block everywhere in the top-10.

## What the split changes about the target

* Before: even a hypothetically perfect retriever scores blended block-P@1 at most
  **60/64 = 0.9375** while the vision items stay in the denominator — strictly below 0.95. The
  target was unreachable, so missing it carried no information.
* After: the text arm's ceiling is **60/60 = 1.0**, so the ≥0.95 target is at least expressible.
  Reachable is not met: the text arm measures P@1 = 0.3667 today, and its own R@10 (0.8167) bounds
  any fix that only reorders the current top-10 — the remaining ground is pool depth and ranking,
  consistent with PREC-1's reranker-ceiling analysis of the frozen baseline.

## What the vision arm says about a VLM

The vision arm's numbers — paper recall 4/4 with every gold paper at rank 1, against passage recall
0/4 — mean retrieval has already handed the pipeline exactly the right page and the answer exists
only in its figure, so a VLM reading that page would convert four guaranteed misses into answers,
which no amount of text-retriever tuning can do.

## Provenance

* Collection: `waymo_av_safety` (passed explicitly; the runner's default collection is a different
  corpus). Identity cross-check: the answerable arm's paper-level hits are computed against the
  fixture's Waymo-corpus gold ids and score 0.95 — only the right collection contains those papers.
* Scoring rule (verbatim from the JSON): top-10 truncation; sparse_mode=fused
  (hybrid_dense_weight=0.7); paper-level hit = first rank r ≤ 10 with result.paper_id in
  question.gold_paper_ids; passage-level hit = first rank r ≤ 10 with result.anchor.block_id ==
  question.gold_block_id.
* Regression guarantee pinned by
  `test_build_report_no_vision_fixture_text_arm_equals_overall_and_vision_empty`: on a fixture with
  no vision-derived items, `text_answerable`'s recall/MRR/n equal `overall`'s exactly and the vision
  arm is empty — 210-set and equation-slice reports are numerically identical to pre-VARM-1 runs.
