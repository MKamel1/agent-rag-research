# Session-2 measurements: pre-registration (EV-20 shrunk, EV-21 + EV-12, EV-22 + CQ-7, EV-14 shrunk)

Written and committed 2026-11-11 BEFORE the run scripts in this directory and before any arm of any of
these measurements was run. Nothing here has been executed against a service. After this commit the
arms, fixtures, metrics, thresholds and rules below change only by a dated addendum appended to the
end of this file. Nothing is adopted or switched on by default tonight: a verdict is a recommendation;
every default change goes through operator sign-off (RIDER-1 / config edit).

Authority, in order: this file for what is run tonight; the frozen benchmark protocols
(`2026-11-10-{standards,main-corpus,topic-focus}-benchmark-protocol.md` with their 2026-11-11 addenda)
for metric definitions; the parked ticket files for the rules they already fix; the minimizer
(`2026-11-10-ticket-set-minimizer.md` rows and section 4) for kill criteria. Where two of these
disagree the disagreement is stated in section 7, not resolved silently.

## 0. Common definitions (apply to every section)

Fixtures of record (hashes frozen in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`, checked by
every script with `scripts/eval_protocol_tools.py check-hash` before a service is touched):

| set | file | collection | questions | answerable | scored (has `gold_block_id`) |
|---|---|---|---|---|---|
| `papers` | `docs/eval-reports/data/2026-11-10-papers-passage-gt/papers_passage_gt.json` | `papers` | 61 | 61 | 61 |
| `books` | `docs/eval-reports/data/2026-11-10-causal-books-gt/causal_books_gt.json` | `papers` | 74 | 69 | 69 |
| `standards` | `docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json` | `av_standards` | 128 | 106 | 94 |
| `legacy` (ligature anchor only) | `fixtures/eval/eval_ground_truth.json` | `papers` | 210 | n/a | n/a (no `dimension`/`tests`; stock metrics only) |

Both-fixtures rule: every set is reported and decided separately; nothing is averaged or pooled.

Metric of record: member-passage hit@10 (`scripts/eval_strata_report.py`: a retrieved anchor counts if it
anchors the gold chunk, an `alternative_gold_chunk_ids` chunk, or its member span contains
`excerpt_block_id`). Beside it, always: the excerpt metric (`passage_excerpt_level.hit` from
`app.retrieval_eval`, EV-8) and paper Recall@10 (`paper_level.hit`). The excerpt metric never decides a
verdict; if it disagrees in sign with the metric of record on a deciding set, the report says so.

Pairing: arms are compared question-by-question on the same fixture, same collection, same code
revision, run back to back; per metric: wins (arm hits, base misses), losses, net = wins - losses.
Computed by `scripts/session2_ab_tools.py paired`. An errored question counts as a miss in both arms and
`n_errored` is printed; an arm with `run_valid: false` or errors is not read.

Strata: the fixture's `dimension` (the strata report's per-dimension table). A GATING stratum has
answerable n >= 10. "A stratum loses more than one question" means net (arm - base) <= -2 on member-passage
hit@10 in that stratum. Gating strata at these fixtures: papers all four dimensions (14, 20, 16, 11);
books book-passage (52) and equation-context (12); standards clause-lookup 18, definition-lookup 12,
table-requirement 16, guidance-factual 14, book-passage 26, cross-document 12 (edition 4 and authority 4
are below 10).

Run-to-run validity gate (the tickets' "falsified if the baseline arm repeated here differs from the baseline
run beyond the jitter envelope", made numeric as in the standards protocol section 6): every step that
re-runs an arm the baseline also ran compares the two on member-passage hit@10; |net| <= 1 passes. A failure
marks the step NOT INTERPRETABLE and no verdict is read from it.

Minimum detectable effect at these n (what the thresholds below can and cannot mean). Paired exact sign test
on discordant pairs: the smallest result that reaches two-sided p < 0.05 is 6 wins and 0 losses (or 8:1);
5:0 is p = 0.0625 and 3:1 is p = 0.625. At n = 61 a single proportion at p = 0.5 has a Wilson half-width of
about 12 points. So a net +2 or +3 threshold is a materiality floor that stops one noise flip from adopting
something; it is NOT a significance claim, and none of these runs can establish an effect smaller than about
6 net questions. Every report states this next to the verdict.

Cost model (assumption, replaced by the first measured rate): 3.6 s/query at rerank depth 32 (measured
tonight on the main corpus); 10 s/query at depth 128 (assumption: about 1 s fixed + 2.6 s per 32 pool
candidates). `run_session2.sh` prints the totals.

## 1. EV-20 (shrunk): rerank depth 32 vs 128 at dense weight 0.5

Arms (shipped config otherwise, `--sparse-mode fused`, dense weight 0.5): `depth32` and `depth128`, each run
fresh in this step at the same commit and collection (the depth-32 arm is a re-run of the baseline arm and
doubles as the validity gate). Sets: `papers` and `books` on collection `papers` ONLY. Standards depth is
decided by the standards baseline's own depth arms (rule D-1) and is not run here; Waymo is excluded; the
0.7 and 1.0 weight arms are not run.

Precondition (minimizer row EV-20), checked from the BASELINE run's strata output: a set is run only if
headroom = scored answerable items - baseline member-passage hits at 10 is at least 6. Otherwise the script
prints `skipped: ceiling` for that set and exits 0 for it. Ceiling arithmetic: a +2 gain needs at least 2
missed items to recover; a G-1 +3 needs at least 3; headroom 6 leaves room for a 6:0 result.

Staged ablation: the title-ablated arms (control (i)) are run for a set only if the original-fixture
comparison shows 128 ahead by >= 2 (otherwise the verdict is already "prefer 32" and the ablated arms cannot
change it); they exist to evaluate G-1's "same sign" clause.

Rule (this task's brief): PREFER 32 unless 128 gains >= 2 questions (net member-passage hit@10, 128 minus 32)
on a set with no gating stratum losing more than one. If 128 wins by that rule the verdict on that set is
"prefer 128 (provisional)". Rule G-1 (runbook step 3, frozen) is evaluated and printed beside it: net >= +3,
wins:losses >= 3:1 (zero losses passes), no gating stratum losing more than one, same sign on the
title-ablated arm. A default change is recommended only if BOTH the >= 2 rule and G-1 hold on the same set;
G-1 alone decides default changes, the >= 2 rule only decides whether the ablated arms are spent and which
way the "prefer" line leans (frozen-rule precedence: see section 7, item 1). Review fallback ("otherwise reset
everything to 32/0.5") is NOT applied: defaults stay.

Cannot show: any effect below about 6 net questions; anything about weight; anything about standards or
Waymo; whether a depth difference is real for production traffic (n = 61 and 69 curated questions).

## 2. EV-12 + EV-21: stub filter A/B (`--drop-stub-chunks`)

The EV-12 addendum is appended to `docs/eval-reports/2026-11-10-cq3-stub-chunks.md` in the same commit as
this file (the original pre-registration text is not edited). Summary of what it fixes:

- Fixtures named exactly: `standards` (shipped config, depth 128), `papers`, `books` of section 0. The
  210-question and legacy books sets named by the original text have no passage gold and are NOT used.
- Arms per set: baseline and `--drop-stub-chunks`, run back to back at one commit, baseline re-run rather than
  reused. Per-question rows kept.
- Stubs identified by chunk id (`retrieved_chunk_ids`, EV-9), using the retriever's single definition
  (`rag.retriever._MIN_BODY_CHARS` = 40 characters). A rank counts as a stub only if every candidate chunk id
  at that rank is a stub (shared-anchor ambiguity resolves against calling it a stub). The 60- and 80-character
  thresholds in two other tools are non-binding.
- ADOPT only if ALL hold: (a) stub-at-rank-1 > 0 at baseline on a set S; (b) member-passage hit@10 improves
  by >= 2 questions (net) on that set S; (c) no gating stratum (n >= 10) on ANY of the sets loses more than
  one question (net <= -2) in member-passage hit@10. Otherwise REJECT and the default stays off.
- Ceiling, computed from the baseline rows by the script before any GPU use: first-order, a gain on a
  question needs a stub in its baseline top 10 AND a gold miss, so ceiling C = number of scored answerable
  questions that miss member-passage hit@10 at baseline AND have >= 1 stub in the top 10. The stub slot
  share and stub-at-rank-1 count are printed with it. A set whose C is below the minimum effect (2) is SKIPPED
  with the reason printed. Kill criterion (minimizer section 4 / EV-21 parked-until): if stub-at-rank-1 occurs
  on fewer than 3 answerable items on EVERY set, the whole step is killed (no arm run).

Cannot show: second-order effects on questions with no stub in the baseline top 10 (rows carry only the top
10; a stub deeper in the rerank pool is invisible, so C understates); any benefit of fixing the chunker;
whether a stub filter helps real queries (588 curated questions).

## 3. CQ-7 + EV-22: ligature-repaired clone and A/B

CQ-7 (CPU + vector store only, no GPU): clone `papers` into `papers__ligrepair_20261111` with
`VectorIndex.clone_points_into`, then `app.resparse --collection <clone> --target-is-clone --clone-of papers
--apply`, then `--verify-sample`. Abort rule: under 20 GB free disk (expected clone 6-8 GB). The live
collection is read only; point counts equal before measuring.

EV-22 arms: A = live `papers`, B = the clone, each in `sparse_only` and `fused` modes, on `papers`, `books`
and `legacy`. Optional control (flag `--dense-control`, off by default): `dense_only` on both collections;
any live-vs-clone difference there is pure index-build noise (identical dense vectors, separately built
graph) and calibrates the others.

What each arm really measures (verified by reading `rag/vector_index.py::_sparse_vector`, which calls
`repair_ligatures(text.lower())` and is used by both `upsert` and `hybrid_search`; there is no flag):
- Arm A (live `papers`, current code): REPAIRED query tokens against an UNREPAIRED stored sparse index
  (the CQ-2 runbook's "interim state"). It is not "pre-CQ-1".
- Arm B (clone, current code): repaired query tokens against a repaired index, including repaired document
  frequencies for the IDF modifier.
- Therefore A-vs-B isolates the INDEX-side repair (plus the IDF shift it causes). The query-side repair is
  in both arms and cannot be measured by this A/B.
- A clean "before CQ-1 vs after CQ-1" comparison would need rows produced by the pre-CQ-1 code
  (`56d24d0^1`), which do not exist: CQ-1 is already in the baseline commit. They are not reconstructed here
  (that checkout predates EV-7/EV-9 and lacks the harness flags). Mitigation: the query side is a no-op on
  these fixtures iff `repair_ligatures` leaves every question string unchanged; `run_ligature_ab.sh` checks
  that first (`session2_ab_tools.py query-repair-check`) and ABORTS if any question changes (EV-22: arm A
  would then have to run from the pre-CQ-1 checkout). When it passes, arm A equals pre-CQ-1 behaviour on
  these question sets and A-vs-B is, for them, the same as pre-CQ-1-live vs repaired-clone.
- Remaining differences between the collections besides sparse vectors: separately built HNSW graph,
  nothing else (clone_points_into copies ids, dense vectors and payloads verbatim).

Stratification: by whether the GOLD chunk contains a ligature-damaged token, computed read-only from the
corpus DB with the census patterns (`docs/eval-reports/data/2026-11-10-ligature-census/census.py`
`BROKEN_RE`), on `papers` (expected 35 damaged / 26 clean) and `books` (27 / 42). Ceiling: the gold chunk's
own sparse vector changes only when it is damaged, so a gain is expected only there; clean-gold items can
still move through competitors (damaged distractors now matching) and the IDF shift, so the clean stratum is a
regression check, not a null. About 60 damaged items in total: only an effect of about 6-10 net items is
detectable (RV-3).

Adoption rule: the one pre-registered in `2026-11-10-cq2-index-maintenance.md` section 3, restated verbatim:

> ADOPT CQ-1's ligature repair only if BOTH hold:
> (a) `sparse_only` paper Recall@10 on the main-corpus passage set (`papers_passage_gt.json`) is
> strictly higher for the candidate than the baseline; and
> (b) on EVERY fixture (passage-set, causal-books, standards), candidate fused paper Recall@10 AND
> member-passage hit@10 are each no more than ONE question below the baseline.
> Otherwise do not adopt: revert CQ-1's query-side repair too (`_sparse_vector` back to no repair on
> both sides) and delete `papers_resparse`. Do not tune the criterion after seeing numbers.
> With n=61 a one-question gain is within noise; (a) is a pre-registered gate, not a significance
> claim, and the report must say so.

Application tonight: "candidate" = arm B (clone), "baseline" = arm A (live). The standards fixture needs its
own clone of `av_standards` (not made tonight: not in this task's scope), so clause (b) is evaluated on
`papers` and `books` only. A failure of (a) or of (b) on a measured fixture is a final REJECT; if (a) and (b)
hold on the measured fixtures the verdict is "ADOPT-PENDING-STANDARDS", not ADOPT. The EV-22 stub's
description ("net gain on damaged-gold items and no loss of more than 1 on any set, both strata reported") is
reported as the descriptive reading (damaged and clean strata tables); where it differs from the CQ-2 rule the
CQ-2 rule governs. `legacy` (210) is a regression anchor: paired paper Recall@10 and the stock excerpt/anchor
metrics are reported; it is named by no clause of the rule and decides nothing. Validity gate: arm A fused
vs the baseline run's same arm, |net| <= 1.

Cannot show: the query-side repair's own effect; anything about standards or Waymo; any dense-side repair
(not doing); whether the index-side gain survives a live in-place resparse (clone differs only by HNSW build);
effects under about 6 net questions.

## 4. EV-14 (shrunk): filtered-search overlap, exact vs approximate (read only)

Method: no embedder. A seeded sample (seed 20261111) of stored points supplies the query vectors (the stored
`dense` vector of the point itself); for each filter family the sampled points are drawn from the population
that satisfies the filter. Each query is run twice against the same collection through the vector store's
REST API: default (approximate, graph) search and `params.exact = true`, k = 10 after dropping the query's
own point (k+1 requested, self removed). overlap@10 = |approx intersect exact| / |exact|, averaged per
filter. Both the `papers` and `av_standards` collections. No clone, no write: the script issues only
`GET /collections/<c>`, `POST .../points/scroll`, `POST .../points/query` and refuses any other call.
Request bodies are listed in `SESSION2-README.md`.

Filters (every one carries `kind` equality, as every production query does; the filter bodies mirror
`rag/vector_index.py::_qdrant_filter`): F1 `kind=summary`; F2 `kind=chunk`; F3 `kind=summary` + `doc_type=book`;
F4 `kind=chunk` + `doc_type=book`; F5 `kind=chunk` + `doc_type=paper` (explicit-or-missing form); F6
`kind=chunk` + `paper_id=<the sampled point's own paper>`; F7 `kind=summary` + `categories` any-of the
sampled point's categories; F8 `kind=chunk` + categories any-of. 100 queries per filter (fewer if the
population is smaller; a filter with an empty population is reported as n/a).

Pre-registered falsifier (EV-14 ticket, bound to the filters the ticket named, each already carrying
`kind`): BINDING filters are F1 (`kind=summary`, the `search_papers` path), F3 and F4 (`doc_type=book`) and
F6 (single `paper_id`). If mean overlap@10 is >= 0.99 on ALL binding filters on `papers`, payload-index
work (parked CQ-9) is closed. Any binding filter below 0.99 on `papers` means CQ-9's trigger is met.
Non-binding filters (F2, F5, F7, F8) and the `av_standards` table are reported and do not change the
verdict. Kill criterion (minimizer section 4): CQ-9 is also killed if no query returned fewer than k hits
(printed as the count of short result lists).

Cannot show: recall of the hybrid pipeline (the sparse arm is not tested and production asks the dense
side for up to 10,000 results, not 10); behaviour for real question embeddings (stored document vectors are
atypically close to their neighbours, which flatters HNSW); behaviour under concurrent load or after the
collection changes; latency. Overlap is a recall proxy for the dense arm only.

## 5. Order, side effects, what each step may modify

Order (cheapest first): 1 depth -> 2 stub -> 3 ligature A/B; the CPU-only items (clone preparation, EV-14)
are independent and need no GPU. The only thing any script here may modify is the clone
`papers__ligrepair_20261111` (created and resparsed by `prepare_ligature_clone.sh`). Fixtures, corpus
databases and live collections are read only; no script edits a hash.

## 6. Verdict wording

The report states per set: n, ceiling, net and wins:losses on the metric of record, the excerpt metric
beside it, the strata table, the validity gate result, and one of: ADOPT / REJECT / SKIPPED (reason) /
NOT INTERPRETABLE. No post-hoc metric, threshold or fixture change.

## 7. Disagreements between the sources, stated

1. EV-20: this task's brief says "prefer 32 unless 128 gains >= 2 ... with no stratum losing more than one";
   the EV-20 ticket and runbook rule G-1 (frozen) need net >= +3, wins:losses >= 3:1 and the same sign on the
   ablated arm. They are not the same bar. Both are printed; a default change needs G-1 (a frozen rule changes
   only by dated addendum). The weaker rule only says which way the "prefer" line leans.
2. EV-21 ticket says ADOPT needs net +3; this task's EV-12 addendum fixes +2 (stub-at-rank-1 > 0, net >= 2 on
   one set, no stratum losing more than one). The addendum in the CQ-3 note governs this run.
3. The CQ-2 rule names three fixtures including standards; tonight only papers and books are cloned
   (section 3). The verdict is capped at ADOPT-PENDING-STANDARDS accordingly.
