# Dual-fixture retrieval evaluation — NB-D4 runner

Date: **2026-08-28** · tag: **sb1b-smooth**
Config: `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` · collection: `waymo_av_safety` · k=10 · sparse-mode: fused

| fixture | R@10 (answerable) | MRR | block-P@1 |
|---|---|---|---|
| gt_wmr ⚠️ VOID (3 errored) | 65/70 = 0.9286 | 0.8957 | 45/65 = 0.6923 |
| waymo_gt_verified | 66/68 = 0.9706 | 0.8316 | 22/60 = 0.3667 |

**VOID: do not trust the row(s) above.** gt_wmr: 3 question(s) never actually ran (see that fixture's raw report's per-question `error` field) and were counted as ordinary misses. Re-run with no concurrent GPU-lock contention before using this number.

## Known-absent arm (reported separately — never blended)

| fixture | n | with a top result | top-score median | range |
|---|---|---|---|---|
| gt_wmr | 12 | 12 | 0.0104 | [0.0082, 0.0160] |
| waymo_gt_verified | 14 | 14 | 0.0097 | [0.0077, 0.0158] |

Notes: Known-absent items have an empty gold set and miss by construction; blending them into recall deflates the headline with guaranteed misses (BENCH-1). Their arm is reported through its size and top-score distribution only. block-P@1 covers the VARM-1 text_answerable passage-scored arm; vision_derived items keep their own denominator in the raw per-fixture JSON and are never blended in here.

Per-fixture raw reports (verbatim `app/retrieval_eval.py` output): `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1b-smooth/gt_wmr.json`, `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1b-smooth/waymo_gt_verified.json`
