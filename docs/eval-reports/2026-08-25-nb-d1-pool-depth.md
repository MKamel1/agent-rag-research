# NB-D1 — pool-depth instrumentation: is the gold block in the deeper candidate pool? (PREC-1 §2)

**Status: COMPLETE.** Ticket NB-D1, Wave 1 of the next-build programme
(`docs/superpowers/plans/2026-08-24-next-build-programme.md` §4), completing PREC-1 §2
(`docs/eval-reports/2026-08-24-passage-precision-diagnosis.md`). Branch `NB-D1-pool-depth`.
Config frozen at the corpus's shipped values (`hybrid_dense_weight=0.7`, `rerank_depth=32`,
operator decision A — nothing overridden); collection `waymo_av_safety` named explicitly on
every Qdrant-touching invocation; read-only on SQLite/Qdrant throughout. No service errors:
both fixtures ran clean end to end, zero errored questions.

## Question

For scored items whose rank-1 paper is correct but whose gold block is not at rank 1 — the C1
population (gold block inside the returned top-10, ranks 2–10) and the C2 population (gold block
absent from the top-10 entirely) — does the gold chunk exist deeper in the candidate pool? Would
retrieving k ∈ {32, 64, 128} candidates before the rerank-to-10 expose it (and at what depth),
or is it absent from every pool size?

## Answer (per fixture × population × pool size)

**Yes for every non-vision item in the right-paper-wrong-block population; the only items absent
from every pool size are exactly the vision-derived ones.**

* **GT-WMR** (population 12/66): all 11 C1 members' gold blocks are already inside the shipped
  top-10 (ranks 2–8) at every pool size — depth adds nothing for them. The single C2 member
  (`Q-WMR-094`) is vision-derived and absent from the 32-, 64-, AND 128-deep pools. Every
  non-vision population member: **11/11 reachable (already at K=10)**.
* **verified-84** (population 27/64): 19 C1 members hold gold in the top-10 throughout. Of the
  8 C2 members, **4 are vision-derived and absent from every pool size** (structural — their
  answers live in figures no text retrieval can rank; VARM-1's arm, not a pool-depth failure).
  The 4 non-vision C2 items are ALL eventually exposed: three appear in the 32-deep pool
  (depths 13–18) and one (`Q-WAYB-031`) is absent at K=32 yet enters the pool at K=64 where the
  cross-encoder ranks it **#1**. Every non-vision population member: **23/23 reachable by
  K=64**.
* Deeper pools do not only add candidates below: newcomers the cross-encoder likes can also
  push already-exposed gold deeper (ver84 C1 ranks drift down as K grows, e.g. 3→4→5), so X-P
  gains are not free — measured, not modeled, here.

### Ceiling-table extension (completes PREC-1 §1's hard-ceiling table)

block-P@1 achievable by a *perfect reranker*, under two regimes — reordering today's top-10
(PREC-1 §1, recomputed on this run's own k=10 pass) vs. drawing from a depth-K pool. Same-run
numbers, one variable changed per column; fixtures never averaged or compared across.

| fixture | n_scored | reorder-only ceiling (top-10) | +pool K=32 | +pool K=64 | +pool K=128 |
|---|---|---|---|---|---|
| GT-WMR (fused w=0.7) | 66 | 62/66 = 0.9394 | 63/66 = **0.9545** | 63/66 = 0.9545 | 65/66 = **0.9848** |
| verified-84 (fused w=0.7) | 64 | 49/64 = 0.7656 | 53/64 = 0.8281 | 55/64 = 0.8594 | 56/64 = **0.8750** |

Text-answerable arm only (VARM-1's reading of the ≥0.95 target — excludes the vision-derived
items no text retriever can serve):

| fixture | n (text arm) | reorder-only | K=32 | K=64 | K=128 |
|---|---|---|---|---|---|
| GT-WMR | 65 | 62/65 = 0.9538 | 63/65 = 0.9692 | 63/65 = 0.9692 | 65/65 = **1.0000** |
| verified-84 | 60 | 49/60 = 0.8167 | 53/60 = 0.8833 | 55/60 = 0.9167 | 56/60 = **0.9333** |

Reading for R0:

* **GT-WMR is already past the bar at any pool ≥ 32** under a perfect reranker (all-arm 0.9545,
  text arm 0.9692); its residual is ordering (C1 = 11 of 12 population items), i.e. X-O-class
  work, not pool depth. Depth to 128 buys two more blocks from the D/E buckets (0.9848).
* **Pool depth alone cannot get verified-84 to the bar**: even bottomless-at-128 tops out at
  0.8750 all-arm / 0.9333 text-arm, short of 0.95 on BOTH readings. The remaining gap behind
  pool depth lives upstream of ranking — chunking/retrieval (D2's question) — or in the
  reranker's inability to promote what the hybrid fusion buried below position 32 (one item
  proves promotion works when given the chance: `Q-WAYB-031`, fused-position >32 → reranked #1).

### Where gold sits when present deeper than the top-10 (depth histogram)

Population items' gold-block positions in the depth-K reranked list (1-based):

| fixture | K | ≤10 | 11–32 | 33–64 | 65–128 | absent from pool |
|---|---|---|---|---|---|---|
| GT-WMR | 32 | 11 | 0 | — | — | 1 |
| GT-WMR | 64 | 11 | 0 | 0 | — | 1 |
| GT-WMR | 128 | 11 | 0 | 0 | 0 | 1 |
| verified-84 | 32 | 19 | 3 | — | — | 5 |
| verified-84 | 64 | 20 | 2 | 1 | — | 4 |
| verified-84 | 128 | 20 | 2 | 1 | 0 | 4 |

The "<=10" counts grow with K only because newly-exposed items can enter ABOVE rank 10 (the
K=64 row includes `Q-WAYB-031` at rank 1). No population item's gold was ever found beyond rank
48 (`Q-WAYB-025`: 18 → 34 → 48 across K=32/64/128). The text-arm reorder-only figures above
drop the vision items — all four ver84 + the one GT-WMR item sit absent-from-top-10, i.e. none
of them was a reorder-only hit — from both numerator and denominator of the all-arm count.

### Population detail (identities, for R0's per-item audit)

GT-WMR C1 = Q-WMR-009/022/025/036/037/039/045/048/050/055/061 (shipped ranks 2–8, unchanged by
depth); C2 = Q-WMR-094 (vision). verified-84 C1 = Q-GTA-002/005/009/012/013/019/024/026/027/
028/030/031/032, Q-WAYB-004/018/026/030/033/037; C2 = Q-GTA-023 (d18→23→28), Q-WAYB-003
(d13→16→21), Q-WAYB-025 (d18→34→48), Q-WAYB-031 (absent@32 → **rank 1**@64/128) — all
reachable — plus Q-GTA-042/043/044, Q-WAYB-027 (vision, unreachable at every depth).
Non-population items newly exposed by deeper pools: GT-WMR Q-WMR-052 (@32), Q-WMR-028,
Q-WMR-062 (@128); verified-84 Q-GTA-011 plus population items Q-GTA-023/Q-WAYB-003/Q-WAYB-025
(@32), Q-GTA-006 + Q-WAYB-031 (@64), Q-GTA-029 (@128).

### Joint decomposition on this run's shipped-shape pass (ties back to PREC-1 §1)

| bucket | GT-WMR w=0.7 (/66) | verified-84 w=0.7 (/64) |
|---|---|---|
| A — gold block at rank 1 | 48 | 22 |
| C1 — rank-1 paper right, gold block elsewhere in top-10 | 11 | 19 |
| C2 — rank-1 paper right, gold block absent from top-10 | 1 | 8 |
| D — gold paper in top-10 but not rank 1 | 4 | 12 |
| E — gold paper absent from top-10 | 2 | 3 |

GT-WMR matches PREC-1 §1's published gtwmr-fused row except one item on the D/E boundary
(ours D=4/E=2 vs published D=5/E=1); its reorder-only ceiling reproduces the published 62/66 =
0.9394 **exactly**, which is the harness-validity cross-check. verified-84's row differs from
both PREC-1 published arms (dense A24/C118/C29, fused-era A23/C116/C211) as expected: this run
is the shipped w=0.7 operating point, a different arm than either — its numbers stand alone.

## Method notes

Reuse-first; the only new code is the measurement loop (`scripts/nb_d1_pool_depth.py`):

* **Reused unchanged:** `app.retrieval_eval.load_questions` (same duplicate_of exclusion,
  multi-gold folding, vision flag as every published eval), `app.retrieval_eval.score_question`
  (the hit/rank rules PREC-1 §0's field semantics were established against), and the whole
  production wiring path `load_config` → `app.assembly.build_mcp_server` exactly as
  `app/retrieval_eval.py::main()` uses it. Nothing else in the repo exposes deeper-than-10
  ordering, which is why new instrumentation exists at all.
* **The depth knob needed no new seam.** `Retriever.retrieve(q, None, K)` fetches
  `max(K, rerank_depth)` hybrid candidates, reranks the whole pool (token-budgeted batches,
  length-preserving global sort — rag/reranker.py T-DOC39), then truncates to K
  (rag/retriever.py T-DOC24). So retrieve(..., K) IS the depth-K experiment, and the returned
  list contains every resolvable pool candidate in rerank order: absence from it means the
  chunk never entered the hybrid pool. Both arms query Qdrant at `_FUSION_DEPTH_CAP`=10,000
  regardless of K (rag/vector_index.py), so growing K extends the rerank pool's prefix of the
  SAME fused list — cross-K differences here are pool mechanics, not query changes.
* **Populations defined once per fixture** from a dedicated shipped-shape pass
  (k=10 ⇒ pool=max(10,32)=32 → rerank → truncate 10, byte-for-byte the shipped path), using
  PREC-1 §1's one-bucket-each decomposition, then tracked across K ∈ {32, 64, 128}. Per-question
  rows with every rank travel in the committed JSONs.
* **Ceiling-check before trusting the new metric** (programme constraint 11): the reorder-only
  column recomputed on our own k=10 pass hits the published PREC-1 value exactly for GT-WMR
  (62/66), and pre-rerank candidate_count == requested K on every question at every K (no pool
  exhaustion anywhere; the store holds well over 128 candidates per query). Definition:
  bottomless(K) = share of scored items whose gold block appears ANYWHERE in the depth-K
  reranked list — what a perfect reranker drawing from that pool scores at rank 1, since it
  reorders the whole pool before any truncation.
* **Determinism probe:** a full duplicate verified-84 run reproduced all 256 rank measurements
  (64 questions × {shipped, 32, 64, 128}) with ZERO differences, so the cross-K movements above
  are real pool-prefix effects, not ANN jitter.
* **Fixture conditioning respected** (PREC-1 §5): separate invocations, separate JSONs, separate
  tables; denominators next to every count; nothing averaged or compared across fixtures.
* **Disagreement register:** none — the briefed method was sound as given and is what ran. One
  addition beyond the letter of the brief: the determinism probe above (cheap, and it upgrades
  every cross-K claim from "observed once" to "reproduced").

## Reproduction

```bash
cd <worktree root> && export PYTHONPATH=$PWD
CFG=/home/omar/ai-projects/research-system-rag/waymo/data/config.yaml   # gitignored, absolute
conda run -n agent-rag-research python scripts/nb_d1_pool_depth.py \
  --ground-truth fixtures/eval/gt_wmr.json --config "$CFG" --collection waymo_av_safety \
  --pool-sizes 32 64 128 --out-json docs/eval-reports/data/2026-08-25-nb-d1-pool-depth/gt_wmr.json
conda run -n agent-rag-research python scripts/nb_d1_pool_depth.py \
  --ground-truth fixtures/eval/waymo_gt_verified.json --config "$CFG" --collection waymo_av_safety \
  --pool-sizes 32 64 128 --out-json docs/eval-reports/data/2026-08-25-nb-d1-pool-depth/waymo_gt_verified.json
```

Each run prints its summary lines (decomposition, ceilings, per-K population/histogram rows);
every number in this report is one of those printed fields or is computed programmatically from
the committed JSONs' `rows` (population identities, vision splits, drift narratives,
text-arm denominators). ~12 min per fixture, services up, read-only.

## Blockers

None. No config touched, no foundation paths touched, no re-ingest, no infra improvisation.

*(Pending at PR time, deliberately not done here to keep concurrent Wave-1 lanes conflict-free —
shared-file ownership, programme constraint 6: BACKLOG row + PROJECT-STATUS ledger entry for
NB-D1, per AGENT-PROCEDURES §B.)*
