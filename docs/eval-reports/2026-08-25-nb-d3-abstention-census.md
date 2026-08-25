# NB-D3 — abstention feasibility census v2 (both fixtures, feature-wide) — measured 2026-08-25

> **REFRESH-POST-RERANK:** every number below describes the retrieval stack as it stood when
> measured — stored runs: 2026-08-23 baseline at `hybrid_dense_weight=0.5` (the then-shipped value,
> see PROJECT-STATUS's tuning-decision section); fresh confirmation runs: 2026-08-25 at the current
> frozen `hybrid_dense_weight=0.7`. Score and rank distributions shift if retrieval changes
> (reranker, pool depth, fusion weight). Re-run the scripts in §5 before reusing any threshold here
> against a changed stack.

Ticket: NB-D3, `docs/superpowers/plans/2026-08-24-next-build-programme.md` §4 Wave 1. Question: does
ANY observable quantity in existing run records separate known-absent items from answerable ones?
The prior 0/24 finding (`2026-08-23-waymo-priority-baseline.md` §3; programme plan §5) used fused
top-score alone; this census widens the feature set before concluding "no signal exists". This
ticket only measures; it builds no abstention mechanism. Gates A-1's design fork.

---

## Verdict

**no separation found**

No observable quantity measured here separates known-absent from answerable items well enough to
carry an abstention threshold on either fixture — including the features the prior census could not
compute (rank1→rank2 score gap, above-threshold result counts). Details and the three candidates
that were scrutinized before settling on the null are in §4; caveats that do NOT change the verdict
are in §5.

---

## §1 Data, arms, provenance

| source | config | questions per fixture | absent arm (by `by_gold_status.known_absent`) |
|---|---|---|---|
| stored runs `docs/eval-reports/data/2026-08-23-waymo-priority/{ver84,gt_wmr}_{dense_only,fused,sparse_only}.json` | w=**0.5** era | ver84 n=82, gt_wmr n=82 | ver84 **14**, gt_wmr **12** |
| fresh runs (this ticket, 2026-08-25) `data/2026-08-25-nb-d3/{ver84,gt_wmr}_fresh.json` | w=**0.7** (frozen), collection `waymo_av_safety` explicit | same items (`load_questions` dedup identical → same denominators), full 10-rank score vectors captured | same partition |

Fixtures are reported separately throughout; no number below averages or trades across them.
Denominators: ver84 = 68 answerable / 14 absent; gt_wmr = 70 / 12. (Ticket brief said "ver84: 16";
the data's own partition says 14 — the two extras are the `duplicate_of` rows excluded by
`load_questions`' dedup, which is also how the 2026-08-23 baseline reached its 26 = 12+14 total.
Data wins.)

Features censused (17): per-arm rank-1 scores ×3; max-of-arms; dense−sparse gap; cross-arm rank-1
agreement count; top-10 Jaccard overlap ×3 pairs; distinct-paper counts ×3 arms; query length
(chars/words) joined from the fixtures; and — fresh runs only, since stored records persist only the
rank-1 score — fresh rank-1 score, fresh rank1→rank2 gap, count of results ≥50% of rank-1.

## §2 Offline census over the stored runs (w=0.5 era)

AUROC = P(absent item scores higher than an answerable one), ties = ½; implementation verified
against brute-force pairwise counting. Threshold rule: best-Youden-J cut over every observed value,
orientation chosen by the data; FP = false refusals (answerable flagged for abstention), FN =
missed detections (absent not flagged).

### ver84 — n=82 (68 answerable / 14 absent)

| feature | AUROC | direction | threshold rule | FP | FN | Youden J |
|---|---|---|---|---|---|---|
| top_score_dense | 0.2852 | absent lower | abstain if < 0.01460 | 22/68 | 3/14 | 0.462 |
| top_score_fused | 0.4674 | ~none | abstain if < 0.01128 | 33/68 | 4/14 | 0.229 |
| top_score_sparse | 0.5226 | ~none | abstain if > 0.01419 | 28/68 | 5/14 | 0.231 |
| score_max_arms | 0.2988 | absent lower | abstain if < 0.01527 | 25/68 | 3/14 | 0.418 |
| score_gap_dense_minus_sparse | 0.2957 | absent lower | abstain if < 0.00191 | 41/68 | 1/14 | 0.326 |
| arm_rank1_agreement | 0.4044 | ~none | abstain if < 1 agreement pair | 4/68 | 11/14 | 0.155 |
| jaccard_fused_dense | 0.3834 | absent lower | abstain if < 0.388 | 23/68 | 6/14 | 0.233 |
| jaccard_fused_sparse | 0.7321 | absent higher | abstain if > 0.423 | 34/68 | 0/14 | 0.500 |
| jaccard_dense_sparse | 0.6040 | ~none | abstain if > 0.225 | 28/68 | 5/14 | 0.231 |
| distinct_papers_fused | 0.5735 | ~none | abstain if > 9.5 | 3/68 | 11/14 | 0.170 |
| distinct_papers_dense | 0.4942 | ~none | abstain if < 6.5 | 57/68 | 0/14 | 0.162 |
| distinct_papers_sparse | 0.5037 | ~none | abstain if < 4.5 | 10/68 | 11/14 | 0.067 |
| query_len_chars | 0.1250 | absent lower | abstain if < 173.5 chars | 10/68 | 3/14 | 0.639 |
| query_len_words | 0.0735 | absent lower | abstain if < 27.5 words | 14/68 | 1/14 | 0.723 |

### gt_wmr — n=82 (70 answerable / 12 absent)

| feature | AUROC | direction | threshold rule | FP | FN | Youden J |
|---|---|---|---|---|---|---|
| top_score_dense | 0.2851 | absent lower | abstain if < 0.01460 | 13/70 | 5/12 | 0.398 |
| top_score_fused | 0.2798 | absent lower | abstain if < 0.01166 | 29/70 | 1/12 | 0.502 |
| top_score_sparse | 0.4542 | ~none | abstain if < 0.01212 | 13/70 | 7/12 | 0.231 |
| score_max_arms | 0.3881 | absent lower | abstain if < 0.01482 | 7/70 | 7/12 | 0.317 |
| score_gap_dense_minus_sparse | 0.3667 | absent lower | abstain if < −0.000067 | 14/70 | 4/12 | 0.467 |
| arm_rank1_agreement | 0.1911 | absent lower | abstain if < 2 agreement pairs | 20/70 | 1/12 | 0.631 |
| jaccard_fused_dense | 0.2321 | absent lower | abstain if < 0.354 | 11/70 | 5/12 | 0.426 |
| jaccard_fused_sparse | 0.6583 | absent higher | abstain if > 0.423 | 32/70 | 3/12 | 0.293 |
| jaccard_dense_sparse | 0.4214 | ~none | abstain if < 0.084 | 5/70 | 8/12 | 0.262 |
| distinct_papers_fused | 0.8661 | absent higher | abstain if > 5.5 | 14/70 | 2/12 | 0.633 |
| distinct_papers_dense | 0.7768 | absent higher | abstain if > 4.5 | 15/70 | 4/12 | 0.452 |
| distinct_papers_sparse | 0.6798 | absent higher | abstain if > 5.5 | 43/70 | 1/12 | 0.302 |
| query_len_chars | 0.1000 | absent lower | abstain if < 113 chars | 15/70 | 1/12 | 0.702 |
| query_len_words | 0.1315 | absent lower | abstain if < 16.5 words | 17/70 | 1/12 | 0.674 |

Arm-level rank-1 score distributions (mean, IQR), stored runs:

| fixture/arm | answerable | known_absent |
|---|---|---|
| ver84 dense | 0.01487 [0.01408, 0.01613] | 0.01335 [0.01136, 0.01449] |
| ver84 fused | 0.01128 [0.00868, 0.01388] | 0.01102 [0.00863, 0.01439] |
| ver84 sparse | 0.01358 [0.01220, 0.01515] | 0.01377 [0.01235, 0.01471] |
| gt_wmr dense | 0.01543 [0.01493, 0.01639] | 0.01393 [0.01235, 0.01587] |
| gt_wmr fused | 0.01239 [0.00975, 0.01515] | 0.00996 [0.00862, 0.01057] |
| gt_wmr sparse | 0.01403 [0.01266, 0.01538] | 0.01373 [0.01163, 0.01538] |

Reading: fused IQRs overlap almost completely on both fixtures (the RI-M7/baseline finding,
reconfirmed). Dense leans consistently "absent lower" but is unusable as a rule: even its
Youden-optimal cut refuses 19–32% of answerable questions while still missing 21–42% of absent
ones.

## §3 Fresh confirmation runs (w=0.7, live stack, 2026-08-25)

One pass per fixture over all 82 questions each, 0 errors both, full score vectors captured
(`app/exp_nb_d3_fresh_capture.py`, reusing `retrieval_eval.load_questions` unmodified).

Fused rank-1 distributions moved with the config change (answerable mean up ~0.0010–0.0013;
absent flat on ver84, up ~0.0006 on gt_wmr) but the conclusion does not change:

| fixture | answerable mean [IQR] | absent mean [IQR] | AUROC | best-cut cost |
|---|---|---|---|---|
| ver84 | 0.01257 [0.01063, 0.01485] (n=68) | 0.01110 [0.00891, 0.01441] (n=14) | 0.3340 | 11/68 FP for 6/14 caught |
| gt_wmr | 0.01338 [0.01166, 0.01535] (n=70) | 0.01057 [0.00864, 0.01141] (n=12) | 0.2071 | 14/70 FP for 10/12 caught |

The two features the stored records could not support:

| fresh feature | ver84 AUROC | gt_wmr AUROC | reading |
|---|---|---|---|
| rank1→rank2 score gap | 0.3897 (absent lower) | 0.4702 (~none) | no separation; best cuts cost 40/68 and 25/70 false refusals |
| count of results ≥ 50% of rank-1 | 0.5074 (~none) | 0.5000 (none) | degenerate: fused score profiles are essentially flat — nearly always all 10 results sit above half the top score |

## §4 What would have changed the verdict, and why it didn't

Three candidates deserved scrutiny before settling on the null:

1. **`distinct_papers_fused` on GT-WMR looked strong (AUROC 0.866)** — and fails the programme's
   held-out-control rule outright: the same feature on ver84 is 0.574 (coin-flip territory).
   With 17 features × 2 fixtures = 34 tests, a few |AUROC−0.5|≈0.3+ outliers are exactly what a
   global null produces; replication across fixtures is the filter, and this one dies in it.
2. **Query length orders strongly and replicates**: AUROC 0.07–0.13 on BOTH fixtures (absent
   questions shorter). It is nonetheless not counted as a signal — it measures how the two fixture
   authors wrote questions, not whether the corpus covers them. An abstention rule built on length
   refuses every short factual ask ("how many scenes…?") regardless of coverage while answering
   long rambling questions about absent topics; that is fixture-authoring leakage of the same kind
   as §5's title_leak exclusion, just subtler. Reported in full so A-1 can see it and reject it
   explicitly.
3. **Cross-arm disagreement (the ticket's named hypothesis)**: direction is right — absent topics
   make the three arms disagree more (lower rank-1 agreement, lower fused∩dense overlap on both
   fixtures) — but magnitudes are inconsistent across fixtures (agreement 0.40 vs 0.19;
   jaccard_fused_dense 0.38 vs 0.23) and operating points stay expensive (best cuts cost 4–23
   false refusals per fixture while still missing 1–11 of that fixture's absent items). A real but
   weak tendency, not a thresholdable signal.

Per-feature verdicts therefore reduce uniformly to: no usable separation on this data.

## §5 Method notes

- **FP/FN semantics** (both tables): FP = false refusal among ANSWERABLE items (denominator
  n_answerable); FN = missed detection among ABSENT items (denominator n_absent). Thresholds are
  Youden-optimal in-sample — they flatter the features, which makes the null stronger, not weaker:
  even optimistically chosen cuts fail.
- **`title_leak` was censused and EXCLUDED as leaky-by-construction**: it tests retrieved passages
  against the question's GOLD papers' titles; a known-absent question has an empty gold set, so the
  flag is False for all 26 absent items regardless of retrieval output (0/14, 0/12 measured). Its
  naive AUROC (0.09–0.11) encodes the label, not behaviour.
- **Score-gap and above-threshold features were impossible offline** (stored records carry only the
  rank-1 score) and were measured on the fresh runs instead — the one fresh run per fixture also
  serves as the w=0.5→w=0.7 confirmation, since the stored baseline predates decision A.
- The fresh capture used a thin harness (`app/exp_nb_d3_fresh_capture.py`) over
  `app.retrieval_eval.load_questions` + the standard server assembly rather than
  `app/retrieval_eval.py`'s report path itself, because that report persists only rank-1; question
  loading, dedup, k, and retrieval calls are the runner's own, so denominators match the baseline
  exactly.
- **Docs obligations (BACKLOG row, PROJECT-STATUS ledger) deferred to the merge orchestrator**:
  D1/D2/D4 lanes were live in parallel worktrees when this lane ran; constraint 6 forbids two
  concurrent branches editing the same file, and those tickets ship into the same shared docs.
- Reproduction (from repo root, env `agent-rag-research`; fresh capture needs services UP and takes
  ~3.5 min/fixture):

```bash
# §2 offline census (stored runs)
python -m scripts.abstention_feature_census \
  --out docs/eval-reports/data/2026-08-25-nb-d3/census_stored.json
# §§2–3 full census incl. fresh-run features
python -m scripts.abstention_feature_census \
  --fresh-dir docs/eval-reports/data/2026-08-25-nb-d3 \
  --out docs/eval-reports/data/2026-08-25-nb-d3/census_full.json
# regenerate the fresh-run captures themselves
python -m app.exp_nb_d3_fresh_capture
```

All committed artifacts: `scripts/abstention_feature_census.py`,
`app/exp_nb_d3_fresh_capture.py`, `docs/eval-reports/data/2026-08-25-nb-d3/*.json`.
