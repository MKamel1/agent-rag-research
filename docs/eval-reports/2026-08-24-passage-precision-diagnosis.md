# PREC-1 — passage-precision diagnosis: why block-level P@1 misses the bar

**Diagnosis only. No config was changed, no retrieval code was touched, nothing was tuned.**
Branch `PREC-1-passage-precision`, measured 2026-08-24 against the stored per-question records of
the frozen 2026-08-23 Waymo-priority baseline (`data/2026-08-23-waymo-priority/*.json`, both
fixtures × dense_only/fused/sparse_only) plus targeted re-measurements noted inline.

Operator target: recall **and precision ≥ 95%** on the Waymo corpus. Published state:

| metric | verified-84 | GT-WMR priority |
|---|---|---|
| Recall@10 | 0.9706 (dense-only) | 0.9857 (fused) |
| P@1, paper level | 0.7941 | 0.9286 |
| P@1, block level | **0.3750** | 0.7273 |

---

## 0. Method and metric semantics (read first — the stored fields do not mean what their names suggest)

Every number in this report is computed from the per-question records in
`docs/eval-reports/data/2026-08-23-waymo-priority/{ver84,gt_wmr}_{dense_only,fused,sparse_only}.json`
(82 question records each; scored denominators 64 verified-84 / 66 GT-WMR after each fixture's own
absent-item exclusion — see the baseline protocol for the freeze provenance).

Field semantics, established by reproduction before use:

* `passage_level.hit` = the item's `gold_block_id` appears **anywhere in the returned top-10**
  (it is a recall-style flag, *not* a rank-1 test). `passage_level.rank` is where it sits (1-based;
  `null` = not in the top-10).
* Published **block-P@1** = share of passage-scored items whose gold block sits at rank **exactly 1**:
  verified-84 dense-only 24/64 = 0.3750 ✓, GT-WMR fused 48/66 = 0.7273 ✓ — both reproduce exactly,
  as do all six R@10/P@1 headline numbers. Every denominator below is stated next to its count.
* Paper-level `hit`/`rank`: first rank whose retrieved paper id ∈ `gold_paper_ids`. Id forms match
  directly between fixture and retrieval output (both sides carry `local:<hash>` ids for
  drop-ingested Waymo documents and bare arXiv ids for harvested ones); no normalization was needed
  and none was applied.
* Reproduction command: the counts in §1 come from a read-only script over these six JSON files
  (`analyze.py`, methodology archived alongside this report in the branch history); no retrieval was
  re-run to produce §1–§2.

## 1. Q1 — where does the gold block actually rank?

Population: passage-scored items whose **rank-1 paper is correct** but whose **gold block is not at
rank 1** — literally "found the right document, pointed at the wrong paragraph."

verified-84 dense-only (n_scored=64): 24 at rank 1; **27** items in the population above =
42% of the scored set. Where the gold block holds:

| gold block location | count (/64) | share of the 27 |
|---|---|---|
| in top-10, rank 2 | 7 | 26% |
| in top-10, rank 3 | 5 | 19% |
| in top-10, ranks 4–10 | 6 | 22% |
| **not in the returned top-10 at all** | **9** | **33%** |

GT-WMR fused (n_scored=66): 48 at rank 1; 18 items in the population = 27% of the scored set:

| gold block location | count (/66) | share of the 18 |
|---|---|---|
| in top-10, rank 2 | 8 | 44% |
| in top-10, ranks 3–7 | 4 | 22% |
| **not in the returned top-10 at all** | **6** | **33%** |

(6 = 5 items whose gold *paper* isn't rank 1 + 1 whose gold block is absent despite the right
rank-1 paper — full joint decomposition below.)

### Joint failure decomposition (every scored item, one bucket each)

| bucket | ver84 dense | ver84 fused | gtwmr fused |
|---|---|---|---|
| A — gold block at rank 1 | 24 | 23 | 48 |
| C1 — rank-1 paper right, gold block elsewhere in top-10 | 18 | 16 | 11 |
| C2 — rank-1 paper right, gold block absent from top-10 | 9 | 11 | 1 |
| D — gold paper in top-10 but not rank 1 | 11 | 7 | 5 |
| E — gold paper absent from top-10 | 2 | 7 | 1 |
| total scored | 64 | 64 | 66 |

**Answer to Q1: it is both, roughly half and half.** Among the "right paper, wrong paragraph"
population, ~two-thirds hold the gold block inside the returned top-10 (ranks 2–10; heavily
concentrated at rank 2: 7/18 verified-84, 8/12 GT-WMR) — an ordering/reranking problem a cheap fix
can reach. But a full third of that population has the gold block **outside the returned set
entirely**, which no reordering of the top-10 can fix.

### What perfect ordering of the current top-10 would buy (hard ceiling)

| set/mode | block-P@1 now | ceiling if a perfect reranker reordered the existing top-10 | Δ |
|---|---|---|---|
| ver84 dense | 0.3750 | 50/64 = **0.7812** | +40.6 pts |
| ver84 fused | 0.3594 | 43/64 = 0.6719 | +31.3 pts |
| gtwmr fused | 0.7273 | 62/66 = **0.9394** | +21.2 pts |
| gtwmr dense | 0.7121 | 61/66 = 0.9242 | +21.2 pts |

This is the single most decision-relevant number so far: **even a hypothetically perfect reranker
over today's top-10 does not reach the 95% bar on either fixture** (78.1% best case verified-84,
93.9% GT-WMR). Any plan that consists only of "rerank better" is capped below target; the residual
~6–22 points live behind pool depth (§2) and chunking/retrieval (§3).

## 2. Q2 — is the gold block in the 32-deep candidate pool but dropped from the top-10?

*(section being measured — re-run instrumentation pending)*

## 3. Q3 — chunking artifact: adjacent / same-section / unrelated

*(pending — needs papers.db block adjacency, read-only)*

## 4. Q4 — correlation with dimension, difficulty, multi-paper

Block-P@1 by the fixture's own metadata fields, headline configs (every cell carries n):

verified-84 dense-only (64 scored):

| stratum | n | block-P@1 |
|---|---|---|
| dimension: numeric/quantitative | 20 | 11/20 = 0.550 |
| dimension: methodological | 16 | 5/16 = 0.313 |
| dimension: single-passage factual lookup | 13 | 4/13 = 0.308 |
| dimension: negation and scope | 7 | **1/7 = 0.143** |
| dimension: temporal/versioned | 6 | 2/6 = 0.333 |
| dimension: multi-paper synthesis | 2 | 1/2 |
| difficulty: medium | 27 | 14/27 = 0.519 |
| difficulty: easy | 13 | 6/13 = 0.462 |
| difficulty: hard | 24 | **4/24 = 0.167** |
| multi-paper (gold_paper_ids > 1) | 5 | 1/5 |

GT-WMR fused (66 scored): flat by comparison — numeric 27/36=0.750, methodological 13/19=0.684,
factual 7/9=0.778, negation 1/2; easy 15/19=0.789, medium 25/35=0.714, **hard 8/12=0.667**;
multi-paper items: none exist in the scored set.

**Named collapse point: `difficulty=hard` on verified-84** — 0.167 vs 0.519 on its own medium
stratum, a 3.1× drop that does not exist on GT-WMR. Secondary: `negation and scope` is the worst
dimension on verified-84 (1/7), driven by C2absent failures (2/7 gold blocks entirely absent from
the top-10 despite the right rank-1 paper). Multi-paper cannot be assessed: 5 exposed items on one
fixture, 0 on the other — no denominator worth quoting beyond this sentence.

## 5. Q5 — why is GT-WMR (0.727) nearly twice verified-84 (0.375)?

Three independent measurements, all pointing the same way:

**(a) The fixtures are structurally different instruments, not two samples of one thing.**

| property (scored answerable items) | verified-84 | GT-WMR |
|---|---|---|
| n | 64 | 66 |
| median question length | 33.5 words | 19 words |
| difficulty mix | 42% hard (27/64) | 22% hard (18/82 total items) |
| dominant dimension | numeric 20/64 | numeric 36/66 (55%) |
| gold-block position in doc (block index p25/p50/p75) | 5 / 29 / 85 | 22 / 44.5 / 70 |
| items with supporting-source authoring | 9 (incl. multi-paper) | **0** |
| distinct gold papers | 28 | 21 |

verified-84's gold blocks skew to the front of documents (a quarter sit at block index < 10 —
title/abstract region), where any topical query matches the paper's own abstract chunk; GT-WMR's
gold blocks sit mid-document where sibling-chunk competition is weaker.

**(b) Dimension-mix reweighting explains only ~6 of the 35 points.** Applying GT-WMR's dimension
mix to verified-84's own per-dimension rates predicts block-P@1 ≈ 0.436 (vs actual 0.375). Mix
moves the number a sixth of the way to 0.727; the rest is within-stratum.

**(c) Head-to-head on identical dimensions and identical papers still shows the full gap.**

Same dimension, both fixtures: numeric 0.550 vs 0.750 · methodological 0.313 vs 0.684 ·
single-passage factual 0.308 vs 0.778. Same difficulty label: hard 0.167 vs 0.667.

The cleanest control — **papers scored by both fixtures (10 papers, 38 verified-84 vs 16 GT-WMR
items)**: verified-84 15/38 = **0.395**, GT-WMR 12/16 = **0.750**. On the very same documents the
gap is undiminished, so it is not which papers each fixture reads.

**Answer to Q5: the difference is a property of how the two sets were authored, not of system
behaviour on different material.** verified-84 asks longer, harder, more negation/scope-shaped
questions whose gold spans often live in front-matter; GT-WMR asks short numeric/factual questions
with mid-document single gold spans. Both numbers are real measurements of *this* retriever against
*different* instruments: block-P@1 as currently measured is fixture-conditioned, and the two
fixtures' numbers must not be averaged, compared across, or traded against each other. Any fix
bought to raise one set's number should be validated against the other set as a held-out control
before it is believed.

*(One caveat kept explicit: item-level pairing between the two fixtures does not exist — no question
is asked twice — so the attribution rests on stratum controls (b)/(c), not on matched pairs.)*

## 6. Ranked candidate fixes

*(withheld until §2–§5 land — deliberately not ranked yet rather than invented early)*
