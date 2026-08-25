# NB-D3 — abstention feasibility census v2 (both fixtures, feature-wide) — measured 2026-08-25

> **REFRESH-POST-RERANK:** every number below describes the retrieval stack as it stood when
> measured (stored runs: 2026-08-23 baseline; fresh confirmation runs: 2026-08-25, config frozen at
> `hybrid_dense_weight=0.7`). Score and rank distributions shift if retrieval changes (reranker,
> pool, fusion weight); re-run `scripts/abstention_feature_census.py` before reusing any threshold
> here against a changed stack.

Ticket: NB-D3 in `docs/superpowers/plans/2026-08-24-next-build-programme.md` §4 (Wave 1).
Question: does ANY observable quantity in existing run records separate known-absent items from
answerable ones? The prior 0/24 finding (`2026-08-23-waymo-priority-baseline.md` §3; programme plan
§5) used fused top-score alone. This census widens the feature set before concluding "no signal
exists". This ticket only measures; it builds no abstention mechanism.

STATUS: **STUB — committed before analysis work** (programme constraint 1: a dead dispatch must be
resumable from committed state). Sections fill in as green steps land:

- §1 Data + arms (fixtures separately, every cell with n)
- §2 Offline census over stored 2026-08-23 runs — per-feature separation table
- §3 Fresh confirmation runs (one per fixture, full score vectors)
- §4 Verdict (exact form required by the ticket)
- §5 Method notes

Reproduction: `scripts/abstention_feature_census.py` (offline sections), plus the fresh-run capture
it documents. Data inputs: `docs/eval-reports/data/2026-08-23-waymo-priority/*.json` (6 files:
{ver84,gt_wmr} × {dense_only,fused,sparse_only}) and this ticket's own fresh-run JSONs.
