# NB-D1 — pool-depth instrumentation: is the gold block in the deeper candidate pool? (PREC-1 §2)

**Status: IN PROGRESS — stub committed (NB-D1 commit 1). This report will extend PREC-1 §1's
ceiling table with a bottomless-pool column per fixture/population, plus the depth histogram of
where gold sits when present.**

Ticket: NB-D1, Wave 1 of the next-build programme
(`docs/superpowers/plans/2026-08-24-next-build-programme.md` §4). Branch `NB-D1-pool-depth`.
Config frozen at the corpus's shipped values (`hybrid_dense_weight=0.7`, operator decision A);
read-only on SQLite/Qdrant; collection `waymo_av_safety` named explicitly everywhere.

## Question

For items whose rank-1 paper is correct but whose gold block is not at rank 1 — the C1 population
(gold block in the returned top-10 at ranks 2–10) and the C2 population (gold block absent from
the top-10) — does the gold chunk exist deeper in the candidate pool? Would retrieving
k ∈ {32, 64, 128} candidates before the rerank-to-10 expose it (at what depth), or is it absent
from every pool size?

## Method notes

*(pending — filled in with the committed script)*

## Results

*(pending — one table per fixture × pool size; denominators next to every count; fixtures never
averaged or compared across, per PREC-1 §5.)*

### fixture: gt_wmr.json

*(pending)*

### fixture: waymo_gt_verified.json

*(pending)*

## Ceiling-table extension (the deliverable)

*(pending — "block-P@1 ceiling if the pool were bottomless" alongside PREC-1 §1's
"if reordered only".)*

## Blockers / service errors

*(none so far)*
