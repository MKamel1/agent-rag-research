# Ordering-quality sweep — NB-X-O (raw tables; narrative lives in the dated report)

Config: `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` · collection: `waymo_av_safety` · all arms serve k=10 · baseline + rerank-64 arm REUSED from NB-X-P same-day raw reports

## Top-10-restricted view — R@10 / MRR@10 / block-P@1 (text arm) per fixture per arm

| fixture | arm | R@10 | MRR@10 | block-P@1 |
|---|---|---|---|---|
| gt_wmr | baseline_pool32 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 |
| gt_wmr | r64s10_rerank64 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 |
| gt_wmr | p16 | 67/70 = 0.9571 | 0.9214 | 45/65 = 0.6923 |
| waymo_gt_verified | baseline_pool32 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 |
| waymo_gt_verified | r64s10_rerank64 | 64/68 = 0.9412 | 0.8268 | 23/60 = 0.3833 |
| waymo_gt_verified | p16 | 62/68 = 0.9118 | 0.8487 | 24/60 = 0.4000 |

## Newcomer effect vs baseline (gold-block ranks; identities in the JSON)

| fixture | arm | lost rank | fell out of top-10 | gained into top-10 | improved |
|---|---|---|---|---|---|
| gt_wmr | baseline_pool32 | 0 | 0 | 0 | 0 |
| gt_wmr | r64s10_rerank64 | 0 | 0 | 0 | 0 |
| gt_wmr | p16 | 1 | 2 | 1 | 1 |
| waymo_gt_verified | baseline_pool32 | 0 | 0 | 0 | 0 |
| waymo_gt_verified | r64s10_rerank64 | 11 | 2 | 2 | 0 |
| waymo_gt_verified | p16 | 0 | 8 | 1 | 7 |

Known-absent arm never blended into any headline (BENCH-1); fixtures never averaged (PREC-1 §5); cross-fixture held-out rule applies to any claimed win.
