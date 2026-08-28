# Dual-fixture retrieval evaluation — NB-D4 runner

Date: **2026-08-28** · tag: **sb1a-latechunk**
Config: `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` · collection: `waymo_av_safety_sb1_latechunk` · k=10 · sparse-mode: fused

| fixture | R@10 (answerable) | MRR | block-P@1 |
|---|---|---|---|
| gt_wmr | 69/70 = 0.9857 | 0.9431 | 49/65 = 0.7538 |
| waymo_gt_verified | 64/68 = 0.9412 | 0.8354 | 24/60 = 0.4000 |

## Known-absent arm (reported separately — never blended)

| fixture | n | with a top result | top-score median | range |
|---|---|---|---|---|
| gt_wmr | 12 | 12 | 0.0108 | [0.0089, 0.0162] |
| waymo_gt_verified | 14 | 14 | 0.0130 | [0.0096, 0.0158] |

Notes: Known-absent items have an empty gold set and miss by construction; blending them into recall deflates the headline with guaranteed misses (BENCH-1). Their arm is reported through its size and top-score distribution only. block-P@1 covers the VARM-1 text_answerable passage-scored arm; vision_derived items keep their own denominator in the raw per-fixture JSON and are never blended in here.

Per-fixture raw reports (verbatim `app/retrieval_eval.py` output): `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1a-latechunk/gt_wmr.json`, `docs/eval-reports/data/2026-08-28-sb1/2026-08-28-nb-d4-dual-fixture-sb1a-latechunk/waymo_gt_verified.json`
