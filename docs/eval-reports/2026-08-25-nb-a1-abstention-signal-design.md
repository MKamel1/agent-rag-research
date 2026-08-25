# NB-A1 — abstention signal-source design doc (resolves the A-series fork)

> **DESIGN DOC — BUILDS NOTHING.** Ticket NB-A1, `docs/superpowers/plans/2026-08-24-next-build-programme.md`
> §4 Wave 3. Input verdict it resolves: `2026-08-25-nb-d3-abstention-census.md` ("no separation
> found", 17 features × both fixtures). Per that ticket's fork: no signal in existing retrieval-side
> quantities → this doc designs NEW signal sources, **each explicitly NOT promised to work**, each
> with a falsification criterion stated before any build, a cheap feasibility measurement someone
> could run next, and its failure mode. No abstention mechanism, threshold, or prompt change ships
> from this ticket.

Measured / written 2026-08-25. Branch `NB-A1-abstention-signal-design`, continued from stub commit
`3afae04`. Grounding numbers come from committed artifacts only (paths cited inline); no new runs,
no new scripts — the feasibility measurements below are specified, not executed.

---

## §0 What D3 ruled out, what it did not

### The null's exact scope

D3 censused 17 features on both fixtures — ver84 (`fixtures/eval/waymo_gt_verified.json`, deduped
partition 68 answerable / 14 absent) and gt_wmr (`fixtures/eval/gt_wmr.json`, 70 / 12) — over two
eras of the stack (stored w=0.5 baseline; fresh w=0.7 confirmation). Every one of those features is
an **aggregate statistic of the retrieved list**: per-arm rank-1 scores, max-of-arms, dense−sparse
gap, cross-arm rank-1 agreement, top-10 Jaccard overlaps ×3 pairs, distinct-paper counts ×3 arms,
query length, fresh rank1→rank2 gap, above-half-of-rank-1 counts. Verdict: none separates
known-absent from answerable well enough to carry a threshold — including the held-out death of the
one strong-looking candidate (`distinct_papers_fused`: gt_wmr AUROC 0.866 vs ver84 0.574), and the
rejection of query length as authoring leakage despite its replication (AUROC 0.07–0.13 both
fixtures).

One structural observation sharpens what that null is a null **about**. The shipped pipeline stage
map is `embed-query → hybrid (dense + sparse arms) → RRF fuse → BGE rerank (pool =
`Config.rerank_depth`) → truncate k → resolve` (`rag/retriever.py` header). Downstream of the fuser,
every score lives on the reciprocal-rank scale: the rank-1 value is 1/61 = 0.016393… (RRF's k=60
constant), which is exactly where both fixtures' dense-arm distributions cap
(`data/2026-08-25-nb-d3/census_full.json`: ver84 dense max 0.0163934; gt_wmr identical ceiling).
**So D3's features measure the rank geometry of retrieved lists — not term-level match content,
not embedding-space geometry (no cosine survives the fuser), not generation-stage behavior, and
nothing at any granularity other than the single full-question retrieval.** That residual space is
where every candidate below lives. The census's own REFRESH-POST-RERANK banner is inherited by
everything here: any measurement reusing stored run records describes the stack as it stood when
those records were captured.

### The second input: the signed generation-side result

`2026-08-24-waymo-refusal-affordance-ab.md` (PROVISIONAL banner; **ver84 fixture only**, raw
68-answerable/16-absent partition — see Method notes for the denominator difference vs D3's 68/14):
adding one refusal-permission clause to the generation prompt flipped wrong-side answers on the
known-absent arm from **6/16 to 1/16** (5 of FAB-1's 6 named failures flipped; holdout `Q-GTA-037`)
at a cost of **0/68 → 3/68** true full refusals of answerable questions (one clean regression,
`Q-WAYB-026`; one mixed, `Q-WAYB-027`; one arguably-correct refusal, `Q-GTA-033`).

Read as a *signal* rather than as a fix — "the answer came back refusal-shaped" as an abstention
flag — the affordance arm detects 14/16 known-absent items while refusing 3/68 answerable ones.
No retrieval-side operating point ever measured approaches that tradeoff: the best fresh fused cuts
cost gt_wmr 14/70 false refusals to catch 10/12, and ver84 11/68 to catch 6/14 (D3 §3); even
Youden-optimal dense cuts cost 22/68 (ver84) and 13/70 (gt_wmr) for fewer detections (D3 §2).
Caveats carried forward: n=16 absent-arm denominator, one reviewer's hand classification, unsigned
rubrics, one fixture, and the operating point is a property of one prompt clause — not yet a
calibrated, thresholdable quantity. It is nonetheless the only place in the committed record where
answerable and known-absent items are already separated at usable rates by anything.

### Constraint compliance stated up front

Fixtures are reported separately everywhere below; nothing averages or trades across them. No
foundation path is touched (`contracts/`, `migrations/`, `fixtures/`, `rag/config.py`, `ci/`,
`.github/`); no NB-D* file or report is modified; no mechanism/threshold/prompt is built or changed.

---

## §1 Candidate signal sources

Chosen and justified: four candidates carried to full design (C1–C4), each occupying a distinct
unmeasured space from §0 — generation-stage behavior (C1), term-level match content pre-fusion (C2),
corpus-global embedding geometry (C3), multi-query decomposition views (C4) — plus C5, judge-model
screening, presented because the ticket names it, with its pre-retrieval variant **dropped here by
analysis** and its post-retrieval twin folded behind C1. Each candidate carries the five mandatory
elements.

<!-- C1..C5 filled in subsequent commits; recommendation ordering and method notes follow. -->

## §2 Recommendation ordering

<!-- Filled after candidates: which candidate to falsify first and why, or an honest "no candidate
     clears the bar". -->

## §3 Method notes

<!-- Filled last: framing agreement/refinements, fixture-denominator discipline, score-scale note,
     refresh caveats, what was and was not run for this doc. -->
