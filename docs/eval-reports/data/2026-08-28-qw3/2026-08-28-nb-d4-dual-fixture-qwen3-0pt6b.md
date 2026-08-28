# Dual-fixture retrieval evaluation — NB-D4 runner

Date: **2026-08-28** · tag: **qwen3-0pt6b**
Config: `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` · collection: `waymo_av_safety` · k=10 · sparse-mode: fused

| fixture | R@10 (answerable) | MRR | block-P@1 |
|---|---|---|---|
| gt_wmr | 66/70 = 0.9429 | 0.5968 | 2/65 = 0.0308 |
| waymo_gt_verified | 61/68 = 0.8971 | 0.5429 | 2/60 = 0.0333 |

## Known-absent arm (reported separately — never blended)

| fixture | n | with a top result | top-score median | range |
|---|---|---|---|---|
| gt_wmr | 12 | 12 | 0.0100 | [0.0084, 0.0148] |
| waymo_gt_verified | 14 | 14 | 0.0097 | [0.0082, 0.0144] |

Notes: Known-absent items have an empty gold set and miss by construction; blending them into recall deflates the headline with guaranteed misses (BENCH-1). Their arm is reported through its size and top-score distribution only. block-P@1 covers the VARM-1 text_answerable passage-scored arm; vision_derived items keep their own denominator in the raw per-fixture JSON and are never blended in here.

Per-fixture raw reports (verbatim `app/retrieval_eval.py` output): `docs/eval-reports/data/2026-08-28-qw3/2026-08-28-nb-d4-dual-fixture-qwen3-0pt6b/gt_wmr.json`, `docs/eval-reports/data/2026-08-28-qw3/2026-08-28-nb-d4-dual-fixture-qwen3-0pt6b/waymo_gt_verified.json`
