# NB-R0 — ranked candidate fixes (completes PREC-1 §6)

Written 2026-08-25 by the orchestrator from the four landed Wave-1 evidence sources; independent
review dispatched concurrently (verdict appended when it returns). This document decides what the
X-series measures and in what order. Every number cites its source report; nothing here is new
measurement.

## Evidence inputs

| input | finding that drives ranking | source |
|---|---|---|
| Pool-depth instrumentation | All **23/23 non-vision right-paper-wrong-block items on verified-84 are exposed by K=64**; GT-WMR's 11/11 near-misses were already in top-10 (depth adds nothing there). Bottomless-pool block-P@1 ceilings: GT-WMR 0.9848 (≥0.95 already at K=32); ver84 **0.8750 all-arm / 0.9333 text-arm** | `docs/eval-reports/2026-08-25-nb-d1-pool-depth.md` |
| Promotion proof | `Q-WAYB-031`: absent from pool@32 → reranked **#1** at pool@64 — the cross-encoder promotes fusion-buried candidates when the pool lets it see them | same |
| Newcomer hazard | Deeper pools push already-exposed gold deeper (newcomers outrank it) — depth gains are not free; realized gain depends on reranker ordering quality over the larger pool | same |
| Boundary misses | same_chunk + adjacent_chunk = **9/27 (33%) of ver84 near-misses, 3/12 (25%) GT-WMR** — chunk-boundary effects are material, not noise | `docs/eval-reports/2026-08-25-nb-d2-block-adjacency.md` |
| Anchor/citation artifacts | Q-WAYB-027, Q-WMR-094 (+Q-WMR-036 straddle): gold text physically inside the rank-1 served chunk but metric scores miss because anchor ≠ gold block exactly (~1–2 items/fixture) | same |
| Abstention | No retrieval-score feature separates known-absent from answerable (17 features × 2 fixtures) → abstention needs a new signal source, not retrieval tuning | `docs/eval-reports/2026-08-25-nb-d3-abstention-census.md` |
| Vision slice | The only items absent from every pool size (4 ver84 + 1 GT-WMR) are the vision-derived ones — structurally unreachable by any text-side fix | NB-D1 report |
| Baseline context | Reorder-only ceilings over today's top-10: ver84 0.7812 / GT-WMR 0.9394; fusion evicts on full corpus (dense-only top-10 hits 50/60 vs fused 43, one-way) | PREC-1 §1; priority-baseline §2 |

## Ranking

**1. X-P — deep-pool production tables (K ∈ {32, 64}, shipped reranker, w=0.7 frozen).**
The single biggest measured lever: exposure goes 24→47 of 64 scored ver84 items' worth of
near-miss population by K=64. Measurement-only (no config flip): run the full standard dual-fixture
table at each depth using the production retrieve→rerank pipeline. Answers the decision question
directly: *what do R@10/block-P@1 actually become at depth?* Predicted ceiling per fixture:
GT-WMR ≥0.95 plausible immediately; ver84 bounded by 0.9333 text-arm even with perfect ordering.
Cost class: scripts-level, zero contracts impact.

**2. X-F — fusion-shape variants (measurement, not flips).**
Dense-only vs shipped-fused vs w∈{0.8, 1.0} full tables via the landed runner. Tests whether the
eviction finding survives depth (with K=64 pools, does dense-only's pool advantage still matter,
or does the reranker neutralize it?). Interacts with X-P: if depth subsumes eviction, X-F's verdict
is "config stays, depth does the work". Cost class: pure runner invocations.

**3. X-O — reranker ordering quality (DECIDED BY X-P's data, ticket written then).**
Once pools deepen, ordering quality becomes the binding constraint (newcomer hazard above). If
X-P shows gold outranked-by-newcomer losses, the ticket is a reranker improvement/swap measured
against the other fixture as held-out control. Do not start before X-P lands.

**4. X-C — citation refinement for anchor-exactness artifacts (small, rides with any PR).**
Map cited spans back to exact member blocks within the served chunk at citation time (generation-
side or post-processing). Fixes ~1–2 real mis-groundings per fixture AND converts their metric
misses honestly (the right words were already being served; the citation pointed at the wrong
block). Not urgent for the benchmark; high value-for-effort for actual users of the system.

**5. X-H — hard-difficulty / negation strata (last, least certain).**
ver84 hard-collapse (block-P@1 0.167 vs 0.519 medium) likely needs query-side work whose cost/
certainty profile is worse than everything above. Revisit only if X-P/X-O leave a stratum-shaped
residual.

## Honest ceiling statement (read before believing any X-series win)

Perfect execution of 1+2+3 combined cannot clear the 95% passage target on verified-84 all-arm:
bottomless-pool ceiling is 0.8750 all-arm / 0.9333 text-arm. The residual lives upstream
(chunk-boundary long tail: 63–75% of near-misses are same_doc_elsewhere) and in the vision slice
(unreachable by text). GT-WMR can clear 95%. **The programme should say this now rather than after
the experiments**: either the operator accepts the two-arm statement (priority ✓, full-corpus
text-arm ~0.93 achievable, all-arm bounded by extraction/vision limits) or commissions upstream
re-chunking work beyond this programme's scope. Per lessons §7.2, this achievability bound is
computed BEFORE the experiments, not discovered after them.

## What this ranking deliberately does not do

- No config change (Decision A: w=0.7 stays until X-verdicts exist).
- No abstention mechanism (A-series fork resolved toward signal-source design; NB-A1 in flight).
- No vision/VLM build (NB-6 scoping gated on Decision C's unique-information-yield analysis).
- No foundation-path changes anticipated by ranks 1–2; rank 4 touches generation/citation code and
  will get its own design note before any dispatch.

— Orchestrator, NB programme. Independent review: appended below when it returns.
