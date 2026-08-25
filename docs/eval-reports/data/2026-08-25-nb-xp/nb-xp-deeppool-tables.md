# Deep-pool production tables — NB-X-P

Config: `/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml` · collection: `waymo_av_safety` · arms K=[10] (first = baseline) · generated 2026-08-25T13:10:14

## Serving-depth view — runner-native aggregates at each arm's own k

| fixture | K | answerable R@K | MRR@K | block-P@1 (text arm) | known-absent n |
|---|---|---|---|---|---|
| gt_wmr | 10 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 | 12 |
| waymo_gt_verified | 10 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 | 14 |

## Top-10-restricted view — the production top-10 drawn from each depth

| fixture | K | R@10 | MRR@10 | block-P@1 |
|---|---|---|---|---|
| gt_wmr | 10 | 68/70 = 0.9714 | 0.9393 | 48/65 = 0.7385 |
| waymo_gt_verified | 10 | 65/68 = 0.9559 | 0.8335 | 22/60 = 0.3667 |

## Newcomer effect vs baseline (gold-block first-hit ranks)

| fixture | K | lost rank | of which fell out of top-10 | gained into top-10 | improved |
|---|---|---|---|---|---|

Known-absent arm never blended into any headline (BENCH-1); fixtures never averaged or compared across (PREC-1 §5).
