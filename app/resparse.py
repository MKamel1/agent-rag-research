"""`python -m app.resparse` -- CQ-2: recompute SPARSE vectors only (no re-embedding, no GPU).

STUB (commit 1). Intended behaviour: `--collection` REQUIRED; default is dry-run; writing needs
`--apply` plus EITHER `--i-have-a-snapshot` (verified on disk) OR `--target-is-clone --clone-of X`;
point count verified before/after; `--verify-sample N` measures staleness read-only.

DEPLOYMENT HAZARD (CQ-1): `_sparse_vector` repairs ligature-broken tokens on BOTH index and query
side, so any collection not yet resparsed is queried with repaired tokens against unrepaired
stored vectors. Full analysis and sequencing: docs/eval-reports/2026-11-10-cq2-index-maintenance.md.
"""
