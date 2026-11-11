# Ligature-repaired clone (CQ-7) and ligature A/B (EV-22): result, 2026-11-11

**Verdict (pre-registered CQ-2 rule, `RESULT.txt`): REJECT.** Clause (a) fails: `sparse_only` paper Recall@10 on the passage set is
22 for both the live collection and the repaired clone (not strictly higher). Clause (b) holds on the two measured fixtures
(fused paper Recall@10 and member hit@10 are no more than one question below on papers and on books). The CQ-7 clone build itself
succeeded. Nothing was adopted or reverted; the exact consequence of REJECT as worded in the rule is discussed in section 5.

Run exit status: `ligab2 exit=0` at 14:00:50 (`gpu_queue3.status`). Two earlier attempts aborted (section 2).
Pre-registration: `docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` section 3; adoption rule restated from
`2026-11-10-cq2-index-maintenance.md` section 3. Register: `EXPERIMENT-REGISTER.md`.

## 1. Questions asked

CQ-7: can a ligature-repaired clone of `papers` be built on CPU without touching the live collection? EV-22: does repairing the
stored sparse vectors (index side) raise retrieval on the damaged-gold questions, without harming the rest? Query-side repair
(CQ-1) is in both arms and is NOT measured by this A/B (preregistration section 3).

## 2. What was run

### CQ-7 clone build (source `ligclone-20261111T115922/`)

| item | value | source |
|---|---|---|
| commit | `03cfd1854b7d37c8116d35545c3f54a309e6da40` | `GIT_COMMIT` |
| window | 11:59:23 to 12:19:49 (-07:00), 20 min 26 s: clone 741 s, `app.resparse --apply` 273 s | `MANIFEST.txt` |
| clone | `papers__ligrepair_20261111`, 412,167 points = live `papers` 412,167 | `MANIFEST.txt`, `CONSOLE.txt` |
| disk | 78 GB free of 3.6 TB (98% used) before the clone; abort rule was under 20 GB | `MANIFEST.txt` |
| resparse dry run | would change 138,484 of 412,167 points (chunk 138,451 of 399,676 = 34.6%; summary 33 of 12,491); 273,683 unchanged | `resparse-dry-run.txt` |
| resparse applied | changed 138,484, preserved 412,167 points, point-for-count guard matched `papers`, post-check 0/200 stale | `resparse-apply.txt` |
| stale-sample check (2,000 sampled points) | clone before 655 (32.8%) stale, after 0 (0.0%); live before 708 (35.4%), after 652 (32.6%) (random samples, not the same points; live untouched) | `clone-stale-*.txt`, `live-stale-*.txt` |

### EV-22 A/B (source `ligab-20261111T122952/`)

| item | value | source |
|---|---|---|
| code commit | `9179c0d976421cadb688d61650776bacd7019a1e` (PB worktree; the same one-line change to `scripts/session2_ab_tools.py` is cherry-picked on this branch as `f1e9160`) | `GIT_COMMIT` |
| window | 2026-11-11 12:29:57 to 14:00:50 (-07:00), 1 h 30 min 53 s | `MANIFEST.txt` |
| arms | A = live `papers`, B = clone; each in `sparse_only` and `fused`; sets papers (61), books (74, 69 answerable), legacy (210). `dense_only` control not run (flag off) | `MANIFEST.txt` |
| per-arm wall-clock (start-to-start, from `q3_ligab2.log`) | papers sparse_only 4 min 24 s (live) and 4 min 38 s (clone), fused 3 min 40 s and 3 min 48 s; books sparse_only 5 min 10 s and 5 min 23 s, fused 4 min 31 s and 4 min 45 s; legacy sparse_only 14 min 45 s and 15 min 12 s, fused 12 min 2 s and 12 min 35 s | `q3_ligab2.log` arm lines |
| fixture hash check | `hash check OK (4 fixtures)`: papers_passage_gt `58cdbf47...`, causal_books_gt `3c21d57b...`, eval_ground_truth `61e52db8...`, hashes file `7f2fa1fc...`; point counts live 412,167 = clone 412,167 | `MANIFEST.txt`, `q3_ligab2.log` |
| query-side no-op check | 0 question strings changed by `repair_ligatures` in papers, books and legacy fixtures, so arm A equals pre-CQ-1 behaviour on these questions | `q3_ligab2.log` |
| strata (gold chunk ligature-damaged vs clean) | papers 35 damaged / 26 clean; books 27 damaged / 42 clean (5 absent items unflagged) | `flags-papers.txt`, `flags-books.txt` |
| errors | 0 in every pair; `run_valid` true | `pair-*.txt` |

Aborted attempts, kept for the record: `ligab-20261111T121949/` (started 12:19:57, queue logged `ligab exit=12` after 8 s) and
`ligab-20261111T122923/` (started 12:29:28, flags files only, then superseded by the run above). Per the brief both were caused by
the bug fixed in `9179c0d`: `ligature-flag` treated absent items, which carry no gold chunk, as bad input. They contain no arm
results and are not evidence about the question.

Evidence committed: `docs/eval-reports/data/2026-11-11-session2/runs/{ligclone-20261111T115922,ligab-20261111T121949,ligab-20261111T122923,ligab-20261111T122952}/`.
The final A/B directory was 5.4 MB, over the 5 MB bar, so the 24 per-arm `*.log` console files (about 2.5 MB) were left out; they live
in the PB worktree under `docs/eval-reports/data/2026-11-11-session2/runs/ligab-20261111T122952/*.log` (untracked there) and the
whole console is `.../scratchpad/q3_ligab2.log`. All JSON, pair, strata, flag, MANIFEST and RESULT files are committed.

## 3. Results (arm B clone minus arm A live; source: `pair-<set>.<mode>.txt`)

| set | mode | metric | A live | B clone | ratio A -> B | wins:losses | net |
|---|---|---|---|---|---|---|---|
| papers (n 61) | sparse_only | paper Recall@10 | 22 | 22 | 0.361 -> 0.361 | 0:0 | 0 |
| papers | sparse_only | member hit@10 | 9 | 8 | 0.148 -> 0.131 | 0:1 | -1 |
| papers | fused | paper Recall@10 | 57 | 57 | 0.934 | 0:0 | 0 |
| papers | fused | member hit@10 | 52 | 52 | 0.852 | 0:0 | 0 |
| books (n 69) | sparse_only | paper Recall@10 | 29 | 30 | 0.420 -> 0.435 | 1:0 | +1 |
| books | sparse_only | member hit@10 | 5 | 6 | 0.072 -> 0.087 | 1:0 | +1 |
| books | fused | paper Recall@10 | 60 | 59 | 0.870 -> 0.855 | 0:1 | -1 |
| books | fused | member hit@10 | 54 | 53 | 0.783 -> 0.768 | 0:1 | -1 |
| legacy (n 210, stock paper metric only; decides nothing) | sparse_only | paper Recall@10 | 110 | 113 | 0.524 -> 0.538 | 4:1 | +3 |
| legacy | fused | paper Recall@10 | 207 | 206 | 0.986 -> 0.981 | 0:1 | -1 |

Excerpt and anchor metrics agree in sign with member hit@10 except books sparse_only anchor 5 -> 5 (0, against member +1).

Strata by ligature damage of the gold chunk, member hit@10 (source: same pair files):

| set | mode | damaged gold A -> B | clean gold A -> B |
|---|---|---|---|
| papers (35 / 26) | sparse_only | 8 -> 7 (-1) | 1 -> 1 (0) |
| papers | fused | 29 -> 29 (0) | 23 -> 23 (0) |
| books (27 / 42) | sparse_only | 2 -> 3 (+1) | 3 -> 3 (0) |
| books | fused | 20 -> 20 (0) | 34 -> 33 (-1) |

Per-dimension gating strata (nets, member hit@10) never move by more than 1 (papers sparse_only method-detail -1; books fused
book-passage -1); see `pair-*.txt`. The clone's change to 138,484 stored sparse vectors (34.6% of chunks) moved at most 1 question
per set and mode in the passage sets, and 3 net paper hits in the 210-question sparse_only legacy arm.

## 4. Rule evaluated literally (`RESULT.txt`; `verdict ligature` output)

> ADOPT CQ-1's ligature repair only if BOTH hold: (a) `sparse_only` paper Recall@10 on the main-corpus passage set is strictly higher
> for the candidate than the baseline; and (b) on EVERY fixture, candidate fused paper Recall@10 AND member-passage hit@10 are each no
> more than ONE question below the baseline. Otherwise do not adopt.

| clause | evaluation |
|---|---|
| (a) papers `sparse_only` paper Recall@10, clone vs live | 22 vs 22, not strictly higher: **false** (`a_sparse_only_papers_recall_strictly_higher: false`) |
| (b) fused, papers | paper 0, member 0: pass |
| (b) fused, books | paper -1, member -1: pass (not more than 1 below) |
| (b) fused, standards | not run (no `av_standards` clone); the pre-registration caps the best outcome at ADOPT-PENDING-STANDARDS |
| validity gate: live fused arm vs baseline run, \|net\| <= 1 | papers 0 (52/52), books 0 (54/54), legacy 0 (207/207, 0:0): pass (`pair-*.jitter.txt`) |
| **verdict** | **REJECT** (a fails; (b) holds on measured fixtures; no clause could be tuned afterwards) |

## 5. Ambiguities and limits (stated, not resolved)

- Clause (a) says "paper Recall@10"; the stricter member-passage metric would also fail it (9 vs 8), so the verdict does not depend
  on the reading.
- The rule's consequence for "otherwise" is "revert CQ-1's query-side repair too (`_sparse_vector` back to no repair on both sides) and
  delete `papers_resparse`". This A/B measured only the INDEX-side repair; the query-side repair is in both arms and was a verified
  no-op on these question sets. So REJECT here does not measure query-side repair. Whether to apply the revert wording is an operator
  decision; nothing was reverted or deleted.
- Power: a 1-question difference is within noise at n = 61; only about 6 to 10 net damaged-gold items would have been detectable
  (prereg section 3, RV-3). The observed nets are -1 to +1 per cell, so the data show no detectable effect, not a proven zero.
- Arm B differs from arm A in the sparse vectors and in a separately built HNSW graph; no `dense_only` control was run to calibrate
  graph-build noise.
- Standards were not tested; the dense side is not repaired (dense vectors are copied verbatim).
- The CQ-7 / EV-22 trigger arithmetic (descriptive, from the live fused arms): damaged-gold member hit@10 papers 29/35 = 0.829 vs clean
  23/26 = 0.885; books 20/27 = 0.741 vs 34/42 = 0.810.

## 6. Additional finding (post-hoc, descriptive, OPEN, uninvestigated): the system's `sparse_only` arm scores far below plain BM25

Not part of any pre-registered rule. Observed while reading section 3. Member-passage hit@10 on the SAME questions, live `papers`:

| set | system `sparse_only` (live) | system `sparse_only` (clone) | system fused (live) | plain BM25 floor (EV-15, standard variant) |
|---|---|---|---|---|
| papers (61) | 9 = 0.148 | 8 = 0.131 | 52 = 0.852 | 52 = 0.852 |
| books (69) | 5 = 0.072 | 6 = 0.087 | 54 = 0.783 | 54 = 0.783 |

Paper Recall@10: system `sparse_only` live papers 22/61 = 0.361 and books 29/69 = 0.420, against BM25 floor papers 60/61 = 0.984 and
books 64/69 = 0.928.

Sources: system arms `strata-papers.sparse_only.txt`, `strata-books.sparse_only.txt`, `pair-*.sparse_only.txt` (this run directory);
BM25 `docs/eval-reports/data/2026-11-10-bm25-floor/{papers,books}-standard.strata.txt` (member hits summed over dimensions:
papers 7 + 17 + 16 + 12 = 52, books 39 + 11 + 4 = 54); the BM25 report is `2026-11-10-bm25-floor.md`.
For contrast, on the standards collection the baseline reports `depth128-sparse_only` member 65/94 against a BM25 floor of 62/94
(`2026-11-11-standards-baseline.md`, the `depth128-sparse_only` row of its arm table, and its BM25 comparison).

The shortfall is the same on the repaired clone, so it is not explained by ligature damage in the stored sparse index. The run's scoring-rule
line states `sparse_only` is `hybrid_dense_weight=0.0`, which "zeroes a score contribution, does not remove that arm's candidates from the
fused pool" (the "Scoring rule" line each arm prints, e.g. in `papers.sparse_only.live.log` in the PB worktree and in `q3_ligab2.log`).

What would need checking (no explanation is offered): what candidates and ordering the `sparse_only` retrieval mode actually produces
before and after reranking; whether the stored sparse vectors, IDF modifier and query tokenisation in the vector store reproduce the
BM25 scoring in `scripts/bm25_floor.py` (tokeniser, k1/b, IDF, stopwords, what text is indexed); whether the main collection's sparse
index differs from the standards one (the latter is near BM25); whether the harness reads the right ranking in this mode. Status: OPEN.

## 7. Do not re-run unless

1. `papers` was re-chunked, re-embedded or re-sparsed in place, or the ligature map (`rag/ligature_map.json`, 227 entries) or
   `repair_ligatures` / `_sparse_vector` changed. Check: point count 412,167; `git diff 03cfd18 -- rag/ligatures.py rag/ligature_map.json rag/vector_index.py`;
   `python -m app.resparse --collection papers --verify-sample 2000` (about 33% stale on the live collection is the state measured here).
2. A different fixture set with materially more damaged-gold items (the rule needs about 6 to 10 net items detectable; 35 and 27 damaged
   items cannot show less) or the standards clone exists and clause (b) on standards is wanted (the best possible outcome stays capped).
3. The `sparse_only` mode or the sparse scoring path changed (section 6): after that open finding is explained, the A/B in `sparse_only`
   is not comparable to this one, because arm values here are very low (8 to 9 hits of 61).
4. The adoption rule or thresholds changed (dated addendum). The per-question rows are in the run directory, so re-scoring is CPU-only.
5. Dense-side repair (re-embedding repaired text) is proposed: that is a different experiment; the clone shares dense vectors.

The clone `papers__ligrepair_20261111` still exists (about 6 to 8 GB); the script suggests deleting it with
`curl -X DELETE http://localhost:6333/collections/papers__ligrepair_20261111` when no longer needed. It was not deleted by this write-up.
