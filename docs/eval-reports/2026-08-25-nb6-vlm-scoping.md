# NB-6 — VLM/vision project scoping: does unique figure information justify the project?

**Status: SCOPING IN PROGRESS** (stub — sections filling in numbered commits; this header flips to
COMPLETE when all four land). Ticket NB-6, standing independent lane of the next-build programme
(`docs/superpowers/plans/2026-08-24-next-build-programme.md` §4, gated only on operator decision C,
answered conditional 2026-08-25 in that programme's §1). Branch `NB-6-vlm-scoping`. This document
scopes; it builds nothing — no model downloads, no config changes, no service changes, no foundation
paths (programme §2 constraints 9; ticket brief).

Every number cites its source file. Where something is estimated rather than measured, the word
ESTIMATE appears next to it; where a number is extrapolated beyond its measured denominator, the
extrapolation is labeled inline.

## Inputs this scoping stands on

| fact | value | source |
|---|---|---|
| Measured floor: items absent from EVERY pool size | 5 scored items = ver84 Q-GTA-042/043/044 + Q-WAYB-027, GT-WMR Q-WMR-094 | `docs/eval-reports/2026-08-25-nb-d1-pool-depth.md` (population detail + depth histogram) |
| Extraction-gap caveat | Q-GTA-044's nine inset values ARE selectable via `fitz.get_text()`; dropped by this corpus's block/chunk extractor — an extraction-pipeline gap, not a true vision requirement; two independent reviewers | `docs/superpowers/plans/2026-08-23-openevidence-programme.md` §3 |
| Opportunity size | figures 24,708 rows / tables 8,266; `vlm_description` populated on 0 | `docs/PROJECT-STATUS.md` Waymo-priority section; `migrations/0006_figures_tables.sql`; `DATA-CONTRACTS.md` figures/tables schema |
| VRAM co-residency trap | MinerU footprint not flat: ~13GB routine peak, observed ~23.7GB/24GB (96.4%); TEI embedder+reranker ~9.4GB resident | `docs/PROJECT-STATUS.md` §4 T-DOC15 |
| Vision arm shape | all 4 ver84 vision items right paper at rank 1, gold block unreachable by text; page-level retrieval 4/4 at n=4 | programme plan §0 (handoff §5.3); `docs/superpowers/plans/2026-08-22-openevidence-gap-and-benchmark.md` |

## §1 Unique-information-yield analysis (the Decision C gate)

Operator decision C (`docs/superpowers/plans/2026-08-24-next-build-programme.md` §1): proceed only
if VLM earns its cost by information *only it* can reach. This section measures that population and
prices what is honestly known about it.

### The measured floor: 5 items no text path can reach, proven exhausted

NB-D1 asked, for every right-paper-wrong-block item across both fixtures, whether the gold block
appears anywhere in the reranked candidate pool at K ∈ {32, 64, 128} (on top of the shipped K=10
path). The items absent from every pool size are exactly the vision-derived ones
(`docs/eval-reports/2026-08-25-nb-d1-pool-depth.md`):

| fixture | scored n | near-miss population | unreachable by ANY text fix | identities |
|---|---|---|---|---|
| verified-84 | 64 | 27 (C1∪C2) | **4** = 14.8% of the population; 6.25% of scored | Q-GTA-042, Q-GTA-043, Q-GTA-044, Q-WAYB-027 |
| GT-WMR | 66 | 12 (C1∪C2) | **1** = 8.3% of the population; 1.52% of scored | Q-WMR-094 |
| both | 130 | 39 | **5** = 12.8% of populations; 3.85% of scored | — |

Structurally means: their answers live in figure/chart content that no text chunk carries, so no
retrieval-side or reranking-side fix (X-P/X-O/X-F classes) can rank them — D1's own reading ("their
answers live in figures no text retrieval can rank"). The programme's shorthand "the 15% unreachable
slice" (programme plan §4 NB-6) maps to the 4/27 ver84 population fraction above; this doc cites the
exact fractions everywhere.

### The discount: Q-GTA-044 is not a true vision requirement

Q-GTA-044's nine inset values *are* selectable in the raw PDF via `fitz.get_text()`; only this
corpus's block/chunk extractor drops them (`docs/superpowers/plans/2026-08-23-openevidence-programme.md`
§3; two independent reviewers). It measures an extraction-pipeline gap — potentially closable
text-side by a parser/chunker fix — not a requirement that pixels be read.

**Discounted floor: 4 true-vision items** (ver84 Q-GTA-042/043 + Q-WAYB-027; GT-WMR Q-WMR-094,
which carries no such caveat in any source reviewed). The pilot's Stage 0 (§3) re-audits all five
per-item rather than trusting this discount statically.

### Honest denominators

Vision ground truth is **n = 4 (verified-84) + 1 (GT-WMR) = 5 items ever authored**, against 68+70 =
138 authored answerable items (`docs/superpowers/plans/2026-08-23-openevidence-programme.md` §3;
`docs/PROJECT-STATUS.md` Waymo-priority section). Every number below inherits that caveat:

- Unreachable share of *scored* items: 5/130 = 3.85% measured; after discount 4/130 = 3.08%.
- Unreachable share of *authored answerable* items: 5/138 = 3.6%; after discount 4/138 = 2.9%.
- Fixture authoring rates for context: vision = 4/68 answerable on verified-84 (4.8%, openevidence
  §4), 1/70 on GT-WMR (1.4%).

**EXTRAPOLATION, labeled:** these rates measure what fixture *authors chose to ask*, not what the
operator actually asks. No organic query log exists in this repo. Extrapolating "≈3–5% of
operator-relevant questions need figure-only content" from hand-authored fixtures assumes the
fixture mix resembles the operator's real question mix — an assumption with zero measurement behind
it. §3's pilot is partly designed to produce the first demand-side evidence; until then the honest
statement is: *the prevalence of figure-only questions in real usage is unmeasured.*

### Opportunity size vs. yield

The corpus holds figures 24,708 rows / tables 8,266 with `vlm_description` populated on 0
(`docs/PROJECT-STATUS.md` Waymo-priority section; `migrations/0006_figures_tables.sql`; location
ready via `image_path` + caption + page + `bbox_json`, content empty — `DATA-CONTRACTS.md`). This is
opportunity size, NOT yield: 24,708 unpopulated descriptions say nothing about how many operator
questions need them. Conflating the two would be the same error as MinerU's flat-footprint estimate
(T-DOC15): arithmetic optimism standing in for a measurement. Page-level anchors already work —
page-level retrieval went 4/4 at n=4 (`2026-08-22-openevidence-gap-and-benchmark.md`) while block-
level stayed unreachable — so the missing piece is genuinely content, not location.

### What a VLM would and would not buy, against the frozen target

The operator target is recall and precision ≥ 95% on the Waymo corpus (frozen before implementation;
`docs/PROJECT-STATUS.md` Waymo-priority section). Current ceilings (D1, bottomless-at-K=128 under a
perfect reranker): ver84 all-arm 56/64 = 0.8750, text-arm 56/60 = 0.9333; the four vision items are
exactly the residual between those two readings. Serving all four vision items perfectly would lift
the all-arm cap only to 60/64 = 0.9375 — **still below 0.95** (the 2026-08-23 openevidence programme's §8 records the same cap
under today's text-only accounting). So a VLM closes the *structural* gap (items no text path can
touch) but does not by itself rescue the ≥0.95 passage target on verified-84; the remaining miss is
ordering quality, a separate workstream (programme X-O lane). How vision items would be counted
post-VLM — scoped-out arm, own arm, or served-in-place — is an operator protocol decision among the three options that programme's §8 already
lists.

### Verdict line

Bar used (stated before verdict): a VLM project is worth starting iff BOTH hold —

- **B1 structural exclusivity, measured:** a non-zero ground-truth set requires figure/table content
  no text path reaches, with text remedies *proven exhausted* (not merely failing today).
- **B2 prevalence, evidenced:** such questions plausibly occur often enough in the operator's real
  usage to justify GPU co-residency risk plus build cost.

B1: **clears decisively** — n=5 measured (floor 4 after the Q-GTA-044 discount), absent from every
pool size through K=128, on both fixtures, with the page-level path already proven at 4/4. B2:
**unmeasured** — no query log exists; fixture authoring rates are proxies for author choice, not
operator demand.

**Verdict: CONDITIONAL CLEAR.** The unique-information case clears the bar's measured half and
fails its evidence half for lack of any measurement — which is exactly the shape decision C's
"conditional" anticipated. It justifies a bounded falsification pilot (§3) whose explicit secondary
deliverable is the first demand-side evidence; it does NOT justify a project-scale build commitment.
If the pilot passes its pre-committed criteria, B2 returns to the operator with numbers instead of
proxies.

## §2 Candidate architecture sketch

TODO-SECTION-2

## §3 Falsification-style build criteria (pre-committed)

TODO-SECTION-3

## §4 Cost summary

TODO-SECTION-4

## Method notes & disagreement register

TODO-METHOD-NOTES

*(Docs obligations — BACKLOG row + PROJECT-STATUS ledger entry per AGENT-PROCEDURES §B — are
deliberately deferred to PR time, same pattern as the NB-D1 report, to keep concurrent lanes'
shared-file ownership conflict-free: programme constraint 6.)*
