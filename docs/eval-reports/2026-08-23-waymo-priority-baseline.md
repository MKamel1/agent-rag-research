# Waymo-priority baseline (gates A–D) — measured 2026-08-23

Protocol: `docs/eval-reports/2026-08-23-waymo-priority-benchmark-protocol.md` (frozen at `4e14d7b`,
before any GT-WMR item existed). Fixtures: `fixtures/eval/gt_wmr.json` (82 items: 70 answerable /
12 absent) and `fixtures/eval/waymo_gt_verified.json` v2 (84 items: 68 scored answerable / 14
scored absent after duplicate exclusion). Collection `waymo_av_safety` (47,893 points, verified in
sync with the corpus). Full per-question evidence: `data/2026-08-23-waymo-priority/*.json`.

## Headline: gates as frozen

| gate | metric (fused = shipped config) | measured | target | verdict |
|---|---|---|---|---|
| A | Recall@10, GT-WMR priority answerable | **0.9857** | ≥ 0.95 | **PASS** |
| B | Precision@10, GT-WMR priority answerable | 0.1057 | ≥ 0.95 | FAIL — see §1 |
| C | Recall@10, verified-84 answerable | 0.8971 | ≥ 0.95 | FAIL (dense-only: 0.9706, PASS) |
| D | Precision@10, verified-84 answerable | 0.0971 | ≥ 0.95 | FAIL — see §1 |

## §1 Gates B/D are structurally unachievable as defined — protocol definition flaw, owned here

The frozen P@10 definition (`|top-k ∩ gold| / k`, macro over queries) has a ceiling of roughly
`1/k` when each query has a single gold paper and the retriever returns k mostly-distinct papers:
even a perfect system scores ≈ 0.10. Measured ceiling across these runs: 0.1086–0.1132 — the
observed 0.0971–0.1057 is AT the ceiling, i.e. the gold paper appears in the top-10 essentially
whenever recall says it does. The definition error is mine (written into the frozen protocol); per
that protocol's own integrity clause, the gates above stand as measured and this addendum records
the correction rather than silently redefining them.

**Corrected companion metric (post-hoc, marked as such): Precision@1** — the fraction of
answerable queries whose rank-1 result is a gold paper — plus block-level precision at rank 1
(where a gold block exists):

| subset | mode | R@10 | P@1 | R@1 | block-P@1 |
|---|---|---|---|---|---|
| GT-WMR | fused | 0.9857 | 0.9143 | 0.9143 | 0.7273 |
| GT-WMR | dense_only | 0.9571 | 0.9286 | 0.9286 | 0.7121 |
| GT-WMR | sparse_only | 0.7571 | 0.7143 | 0.7143 | 0.5152 |
| ver84 | fused | 0.8971 | 0.7941 | 0.7941 | 0.3594 |
| ver84 | dense_only | 0.9706 | 0.7941 | 0.7941 | 0.3750 |
| ver84 | sparse_only | 0.6324 | 0.5441 | 0.5441 | 0.1719 |

Under no reading does precision reach 95% today: best P@1 is 92.9% (priority set, dense-only);
block-level precision at rank-1 is 72.7% (priority) / 37.5% (verified-84). **The precision half of
the operator's ≥95% goal is not met**, and the gap is a reranking/pool-depth problem, not a
recall problem.

## §2 Recall: the priority corpus passes; the full verified set passes only without fusion

* GT-WMR priority: fused 0.9857 (PASS), dense 0.9571, sparse 0.7571. On this set fusion helps
  slightly: fused-hit/dense-miss = 2 (Q-WMR-010, Q-WMR-028), dense-hit/fused-miss = 0.
* Verified-84: fused 0.8971 (FAIL), dense-only 0.9706 (would PASS). Direction strictly one-way:
  dense-hit/fused-miss = 5 (Q-GTA-010, -011, -020, -022, Q-WAYB-002), fused-hit/dense-miss = 0 —
  the same five questions BENCH-1 found, reconfirmed on the v2 fixture. The sparse arm is again a
  net negative on this corpus; the shipped hybrid config is what stands between gate C and a pass.

## §3 Absent arm (reported, per protocol — never blended)

All 26 absent queries (12 GT-WMR + 14 ver84) returned a full confident top-10. Fused top-score:
GT-WMR absent mean 0.00996 (min 0.00737, max 0.01613); ver84 absent mean 0.01102 — overlapping the
answerable score range, i.e. RI-M7's no-separable-floor finding reconfirmed on both fixtures. The
system cannot abstain; any precision target that prices wrong-side answers must be built on an
abstention mechanism that does not exist yet.

## §4 Diagnostics

* title_leak: 58/69 paper-level hits on GT-WMR carry their own paper's title verbatim in the
  passage — expected for abstract-adjacent chunks of papers that name themselves; floor semantics
  per RI-15.
* judge_eval remains unrunnable-by-design (no Judge implementation; rubric PROVISIONAL/unsigned) —
  still the honest gap for answer-quality measurement.
* Instrumentation note: `retrieved_paper_ids`/`retrieved_block_ids` were added to the per-question
  report records after the freeze (pure additive outputs, no scoring change) because the frozen
  P@10 was not computable from the original report shape. The six first-run reports (without the
  field) reproduced identical recall/MRR.

## §5 What this means for the operator's goal

* **Recall ≥ 95%: achieved on the priority corpus** (98.6% shipped config) and achievable on the
  full verified set by dropping the sparse arm (dense-only 97.1%) — that switch is an untested
  implementation change and is deliberately NOT done here; it is now the top-ranked candidate
  ticket, to be judged against these frozen numbers.
* **Precision ≥ 95%: not achieved** under the corrected metric (92.9% best P@1; 72.7% best
  block-level P@1). Ranked levers, all future work: (1) cross-encoder pool depth / rerank-k
  increase, (2) dense-only retrieval (removes the fusion rank damage), (3) an abstention floor —
  blocked on RI-M7's finding that answerable/absent score distributions do not separate.

Nothing was tuned to these numbers: the fixture was frozen before any retrieval output was seen,
the first measurement is published as-is, and every change from here starts from this baseline.
