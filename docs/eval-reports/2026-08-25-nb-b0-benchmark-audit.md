# NB-B0 — benchmark audit: do we have the RIGHT benchmarks for a 0.95-precision + agentic-RAG push?

Written 2026-08-25, branch `NB-B0-benchmark-audit`. **Read-only audit.** No fixture was edited, no
pipeline code touched, no new eval item authored, no retrieval re-run. Every number below is either
quoted from a committed report (cited inline) or recomputed read-only from the committed fixtures and
stored run records (`fixtures/eval/*.json`, `docs/eval-reports/data/2026-08-23-waymo-priority/*.json`)
via one-off inspection scripts that were not retained — each such computation is stated so it can be
re-derived in seconds. Deliverable: this document, §1–§4.

Question of record: before any optimization toward the operator's **precision ≥ 0.95 + agentic-RAG**
goal — do the instruments this repo actually owns support an *honest* 0.95 claim, and what benchmark
authoring is missing for the agentic half?

## Method notes

**Binding house rules applied throughout:**

- **Lessons §7.2** (`docs/AGENT-OPERATIONS-LESSONS.md`): every metric definition endorsed here
  carries its achievability bound as explicit arithmetic, computed from committed data, before any
  recommendation — "a frozen metric needs an achievability bound computed at freeze time". The P@10
  gate failure (below) is the cautionary tale this audit refuses to repeat in the other direction:
  we will not endorse a 0.95 target on any metric whose ceiling arithmetic has not been shown.
- **PREC-1 §5** (`2026-08-24-passage-precision-diagnosis.md`): block-P@1 is fixture-conditioned;
  `waymo_gt_verified.json` and `gt_wmr.json` are *structurally different instruments*, not two
  samples of one thing. Nothing below averages, compares across, or trades between them. Every count
  carries its denominator.

**Pre-committed verdict rubric** (fixed before §1 was written, so the audit cannot move goalposts
mid-report): an instrument is

- **SOUND** for a 0.95 claim iff its computed achievability bound is ≥ 0.95 in its shipped shape;
- **CONDITIONAL** iff the bound reaches 0.95 only under stated dependencies (a named config variant,
  a named upstream fix, or as a companion to a primary metric);
- **UNSOUND** iff it is structurally incapable of 0.95 under every reading (bound < 0.95 even under
  perfect execution), or if it does not measure what a "precision" claim needs.

**Three data corrections to the ticket brief** (data wins, per the NB-D3 precedent of checking
denominators against the loader rather than the brief):

1. **verified-84 scored denominators**: the file holds 84 items (68 answerable / 16 absent, incl.
   4 vision-derived). Both `duplicate_of` rows sit in the **absent arm** (Q-GTA-036/037 duplicate
   Q-WAYB-034/Q-WAYB-009), so after `load_questions` dedup the scored population is **82 =
   68 answerable / 14 absent** — the partition every stored run record and NB-D3 uses.
2. **Multi-paper exposure, precisely** (matters for §3): at paper level (`gold_paper_ids > 1` in the
   run records) ver84 exposes **9** items — 5 of them passage-scored; gt_wmr exposes **4**
   (Q-WMR-090..093) — **0** passage-scored, because those four carry `supporting_passages` but no
   single gold block. The brief's "~5 exposed / 0 scored" describes the passage-scored slice; the
   fuller counts are the honest denominator basis for agentic-gap sizing.
3. **Block-scored denominators**: ver84 **64** (= 68 answerable − Q-WAYB-010..013, the
   supporting-passage multi-paper items without a single gold block; ver84's four vision items all
   *do* carry `gold_block_id`), gt_wmr **66** (= 70 − Q-WMR-090..093; gt_wmr's one vision item,
   Q-WMR-094, also carries a gold block). Text-answerable arms (NB-D1's reading): **60 / 65**.

**Framing endorsement, plus one addition the brief did not ask for.** I endorse attaching the 0.95
target to rank-1 metrics, computed per fixture. The addition: lessons §7.2 also forces an
achievability statement for any precision definition priced over the **full question population** —
with no abstention mechanism (RI-M7; NB-D3), such a definition is capped at
N_answerable / N_total = 70/82 = **0.8537** (gt_wmr) and 68/82 = **0.8293** (ver84) *regardless of
retrieval quality*. That arithmetic is in §2 because "precision ≥ 0.95" without stating its
denominator is exactly how frozen gates B/D died.

---

## §1 Instrument inventory

*(to land in commit 2)*

## §2 The metric definition for THIS push

*(to land in commit 3)*

## §3 Gap analysis: agentic-RAG evaluation

*(to land in commit 4)*

## §4 Confidence-benchmark gap

*(to land in commit 4)*

## Verdict

*(to land in commit 4)*
