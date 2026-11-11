Title: RQ-6: Diagnose why the keyword (sparse) arm scores far below plain BM25 on the main collection
Labels: wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:M

## RQ-6 -- Diagnose why the keyword (sparse) arm scores far below plain BM25 on the main collection

**Wave:** W1 no GPU (diagnosis is CPU plus read-only vector-store queries). **Type:** diagnosis; root cause first, no fix is pre-committed.

**Why.** Observed post hoc and left open in `docs/eval-reports/2026-11-11-ligature-repair-result.md` section 6. Member-passage hit@10 on the same questions:

| set | system `sparse_only` | plain BM25 floor (`scripts/bm25_floor.py`) | system fused |
|---|---|---|---|
| papers (61) | 9 (clone: 8) | 52 | 52 |
| books (69) | 5 (clone: 6) | 54 | 54 |

Paper Recall@10 shows the same gap (papers 22/61 against 60/61; books 29/69 against 64/69), so it is not a member-span scoring artefact. On the standards collection the same code path is fine (`sparse_only` 65/94 against BM25 62/94, `docs/eval-reports/2026-11-11-standards-baseline.md`), and standards `dense_only` equals fused (84/94 each). The repaired-ligature clone is equally low, so stored ligature damage does not explain it. The fused result already equals the BM25 floor on both main sets, so this is not a user-visible regression today; it matters because it blocks every sparse-side experiment (parked CQ-18, RQ-5) and may mean the keyword arm contributes less than it looks.

**Scope.** Find the root cause. Each check below is read-only (CPU, SQLite opened read-only, vector-store `query_points`/`scroll` on the live and clone collections); none needs the GPU services.

Checks, in the order that separates the hypotheses fastest:
1. **Raw sparse ranking versus the final ranking.** In the eval path `sparse_only` is `sparse_mode_weight("sparse_only", ...)` = `hybrid_dense_weight` 0.0 (`app/retrieval_eval.py::sparse_mode_weight`). That zeroes the dense contribution in `contracts/fusion.py::rrf_fuse` but dense candidates are still in the pool, and the retriever then reranks the top `rerank_depth` pool with the cross-encoder (`rag/retriever.py`, the `hybrid_hits` then `RerankCandidate` path). BM25 floor has no reranker. So first measure the raw `VectorIndex.hybrid_search` sparse ranking (no rerank): for each question in the papers and books fixtures, the rank of the gold chunk in the Qdrant sparse-only list (`query_points` with `using="sparse"`, `_sparse_vector(question)` as the query). If raw sparse hit@10 is near the BM25 floor, the weakness is downstream (pool/rerank/harness): go to checks 6 and 7. If raw sparse is also about 9/61, it is in the sparse vectors: go to checks 2 to 5.
2. **Tokenisation.** `rag/vector_index.py::_sparse_vector` lower-cases, repairs ligatures, then `text.split()` on whitespace, with no stop-word removal; each token is hashed (sha1 modulo `_SPARSE_MODULUS`, 2,147,483,647). The floor script uses `re.compile(r"[a-z0-9]+")` plus the `STOP` list (`scripts/bm25_floor.py::tokenize`, `scripts/eval_protocol_tools.py::STOP`). Whitespace splitting leaves punctuation attached ("word," and "word" are different terms), which could prevent query terms from matching chunk terms. Measure: for 20 questions, the share of query tokens (after each tokeniser) that occur in the gold chunk's token set under each tokeniser.
3. **Term weighting.** `_sparse_vector` sends raw counts; weighting is only Qdrant's IDF modifier (`_sparse_vector_params`, `Modifier.IDF`), i.e. a dot product of tf and idf with no saturation and no length normalisation, and the query side counts repeated words. The floor uses k1 = 1.2, b = 0.75 and the set of query terms (`Bm25Index.search`). Re-score the same questions offline with both weightings on the same tokens (one streaming pass over the chunks table, as `scripts/bm25_floor.py` does) to see how much of the gap each difference explains. This is an experiment on a diagnosis, not a proposal to change weighting (that is parked CQ-18).
4. **Collection configuration.** Confirm the live `papers`, the clone and `av_standards` collections report the IDF modifier on the sparse field (`VectorIndex.has_idf_modifier`), that sparse vectors exist for every point, and compare points count with documents (`app/doctor`). The main collection was moved to IDF by a later migration (`app/reindex_idf.py`) rather than created with it, so confirm the migration state per collection rather than assuming.
5. **Which text is indexed.** The point payload `text` fed to `_sparse_vector` versus the `chunks.text` the floor indexes (title and section header lines, then the body; `rag/retriever.py::body_of` defines the split). Check on a sample of points that payload text equals the stored chunk text, and whether summary points (same collection, same sparse field, 12,491 of 412,167 points) distort document frequencies. The floor's `title-ablated` and `body-only` variants show how much header text carries.
6. **Sparse-only candidate path.** Trace what the sparse-only configuration returns before and after reranking for 10 hand-picked questions (5 where the floor hits and `sparse_only` misses, 5 where both hit): candidate ids from Qdrant, the fused list from `rrf_fuse` at weight 0.0 (check ties among zero-scored dense-only candidates and their order), the pool the reranker sees, and the final top 10. The standards collection ran at `rerank_depth` 128 and the main collection at 32 for these runs, so also record how many sparse candidates reach the reranker.
7. **Harness.** Confirm `app/retrieval_eval.py` reads the ranking it should in `sparse_only` mode and that the member-passage and paper-level scoring agree on the same ranked list (re-score the per-question rows in the run directories on CPU).
8. **Hand-picked reproduction.** Do check 1 first on 10 questions on CPU: pick questions from the per-question rows of the 2026-11-11 runs (floor hit, system `sparse_only` miss), query the live collection read-only, and compare the top 10 chunk ids with the floor's. Report the ten rows; the other checks only run for the hypotheses that survive.

- Out (explicitly): any change to weighting, tokenisation, the sparse index or the collections (CQ-18, RQ-5); re-embedding; any GPU run; writing to any collection; deleting the repaired clone (separate operator decision).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-sparse-arm-diagnosis.md`
- `docs/eval-reports/data/<run-date>-sparse-arm-diagnosis/`
- `scripts/sparse_arm_diagnosis.py` (read-only analysis script, if one is needed)

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the hypotheses list, the checks, the falsifier and the stop condition below, written before any query
② check 1 and 8 (raw sparse versus final ranking, ten hand-picked questions)
③ checks 2 to 7 for the hypotheses that survived
④ report with root cause or "not found" and the remaining candidates

**Verification:**
**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- The analysis script, if added, refuses any vector-store call other than read-only `query_points`, `scroll` and `get_collection`
- Every number in the report names the file or command it came from

**Acceptance / falsification criterion.** The report states one root cause (or a short ranked list with the evidence for each) that accounts for at least 80 percent of the gap on the papers set (that is, with the cause removed offline, `sparse_only`-style hit@10 rises from 9 to at least 45 of the 52 the floor reaches), and says which of the 61 + 69 questions it does not explain. Falsifier for the sparse-vector hypothesis: if raw Qdrant sparse hit@10 (check 1, no rerank) on the papers set is within 5 of the floor's 52, the sparse vectors and tokenisation are cleared and the cause lies in the candidate pool, the reranker interaction or the harness. Falsifier for the harness hypothesis: re-scoring the stored per-question rows (check 7) reproduces 9/61.

**Stop condition.** Stop and report as soon as one cause meets the acceptance bar, or after checks 1 to 8 have been run once each (about one day), whichever is first. If none meets the bar, report "not found", the ruled-out list and the remaining candidates; do not extend into building a fix. Any fix is a separate ticket written from the finding.

**Gates / depends on.** Depends on: none (the 2026-11-11 run directories hold the per-question rows). Gates: CQ-18, RQ-5 (parked; both rest on the keyword arm being understood).

**Needs.** GPU: n · services up: vector store (CPU container), read-only; corpus database read-only · operator sign-off: n (no protected path is touched) · re-embed: n.

**Model tier and size.** Sonnet; M. Diagnosis with several competing hypotheses; escalate to Opus only if checks 1 to 7 disagree with each other.

**Risk and rollback.** Read-only throughout; the only cost is vector-store query load on the main collection (keep batches small, as the filtered-search check did). Rollback: discard the report.

**Docs to update in the same PR.** Per `docs/AGENT-PROCEDURES.md` section B: flip this ticket's row in `docs/BACKLOG.md` to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 ledger; add a row to `docs/eval-reports/EXPERIMENT-REGISTER.md` for any new result; add a section 7 doc-map row for every new `docs/*.md`. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns.
