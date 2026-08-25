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

TODO-SECTION-1

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
