# Dual-fixture retrieval evaluation — NB-D4 runner

Date: **2026-08-25** · tag: **nbxf-w100**
Config: `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` · collection: `waymo_av_safety` · k=10 · sparse-mode: fused · dense-weight: 1.0

| fixture | R@10 (answerable) | MRR | block-P@1 |
|---|---|---|---|
| gt_wmr | 67/70 = 0.9571 | 0.9357 | 46/65 = 0.7077 |
| waymo_gt_verified | 66/68 = 0.9706 | 0.8476 | 24/60 = 0.4000 |

## Known-absent arm (reported separately — never blended)

| fixture | n | with a top result | top-score median | range |
|---|---|---|---|---|
| gt_wmr | 12 | 12 | 0.0144 | [0.0110, 0.0164] |
| waymo_gt_verified | 14 | 14 | 0.0129 | [0.0109, 0.0164] |

Notes: Known-absent items have an empty gold set and miss by construction; blending them into recall deflates the headline with guaranteed misses (BENCH-1). Their arm is reported through its size and top-score distribution only. block-P@1 covers the VARM-1 text_answerable passage-scored arm; vision_derived items keep their own denominator in the raw per-fixture JSON and are never blended in here.

Per-fixture raw reports (verbatim `app/retrieval_eval.py` output): `docs/eval-reports/data/2026-08-25-nb-xf/2026-08-25-nb-d4-dual-fixture-nbxf-w100/gt_wmr.json`, `docs/eval-reports/data/2026-08-25-nb-xf/2026-08-25-nb-d4-dual-fixture-nbxf-w100/waymo_gt_verified.json`
