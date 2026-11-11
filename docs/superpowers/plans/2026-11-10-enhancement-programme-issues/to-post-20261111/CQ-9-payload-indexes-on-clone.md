Title: CQ-9: Resolve the filtered-search trigger, then add idempotent payload indexes and verify them on a clone
Labels: wave:3-gated-change, area:corpus, area:retrieval, needs-services, size:M

## CQ-9 -- Resolve the filtered-search trigger, then add idempotent payload indexes and verify them on a clone

**Review cross-reference:** S-22. **Wave:** W3 gated changes after baselines.

**Status, 2026-11-11.** EV-14 (`docs/eval-reports/2026-11-11-filtered-search-result.md`) measured filtered approximate search against exact search on `papers` (412,167 points) and the standards collection (36,031 points), read-only, 100 sampled queries per filter, seed 20261111. Result on `papers`: filter F1 (`kind=summary`) mean overlap@10 0.988, against the 0.99 bar, so the trigger text is met by 0.002; F3, F4 and F6 are 1.000. The kill clause "no query returned fewer than k hits" is also literally satisfied (0 short result lists on `papers`). The pre-registration states both rules and does not say which wins; the printed verdict was TRIGGER MET. The 0.002 shortfall is one sample at one seed (8 of 100 queries below perfect, minimum 0.6), so its sampling variability is unmeasured. Informational standards numbers (not decisive by rule): F4 (`kind=chunk` plus `doc_type=book`) 0.886 with minimum 0.0, F6 (`kind=chunk` plus own `paper_id`) 0.939 with 4 short lists, the rest 0.998 to 1.000. Both collections report no payload indexes. Overlap is a recall proxy for the dense arm only, with stored vectors as queries, which flatters the index.

**Why.** If filtered HNSW search loses neighbours against exact search, payload indexes are the repair; they rebuild HNSW links, a CPU and disk cost, so they must be proven on a clone first (review S-22; RV-1 F-1.2). If the confirmation below shows overlap of at least 0.99, this ticket is closed unstarted.

**Scope.**
- In:
  - **Step 0 (CPU, read-only, no GPU, about 8 minutes per collection): resolve the ambiguity before any build.** Re-run F1 on `papers` with at least five new seeds and 300 or more queries each, using the existing check (`docs/eval-reports/data/2026-11-11-session2/filtered_search_check.py`, launched by `run_filtered_search_check.sh`, the one that wrote the 2026-11-11 result; seed and n fixed in a dated addendum to `docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` before the run). Report the mean, the spread across seeds and a bootstrap interval. Decision rule fixed in the addendum: if the interval's upper bound is below 0.99, the trigger stands and Step 1 starts; if the lower bound is at or above 0.99, close CQ-9 as killed; if it straddles 0.99, stop and ask the operator which clause governs (the ambiguity is theirs to resolve, not ours). In the same run, report the standards collection's F4 and F6 with their minima examined (are the 0.0 minima single odd queries or a pattern?).
  - Step 1 (only if Step 0 keeps the trigger): `ensure_payload_indexes()` in `VectorIndex` (idempotent; keyword indexes for `kind`, `doc_type`, `paper_id`, `author_orgs`, `curated_author_orgs`, `categories`; datetime for `published`) and a call from `_ensure_collection` for new collections only. On a clone: build the indexes, re-run the check, report overlap with and without the index, the count of queries returning fewer than k, build time, added disk and p50 query latency.
- Out (explicitly): applying to any live collection (follow-on ticket, written only on ADOPT, with explicit operator approval, because it changes candidate sets slightly everywhere); any GPU use; the sparse arm and real query vectors (a different experiment).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py` (Step 1 only)
- `rag/test_vector_index.py` (Step 1 only)
- `docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` (dated addendum only)
- `docs/eval-reports/<run-date>-filtered-search-confirmation.md`
- `docs/eval-reports/<run-date>-payload-index-clone.md` (Step 1 only)
- `docs/eval-reports/data/<run-date>-payload-index-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: addendum fixing seeds, n and the Step 0 decision rule, plus the Step 1 report skeleton with the rule written before the clone is touched: ADOPT if overlap with the index is at least 0.99 and strictly greater than without, and queries returning fewer than k fall to 0
② Step 0 run and verdict (stop here if killed or if the operator is asked)
③ `ensure_payload_indexes` with tests on mocked clients
④ clone: build the indexes, time and size recorded
⑤ re-run on the indexed clone; verdict; clone deleted

**Verification:**
**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py` (Step 1)
- Step 0 touches only the read-only calls the script already restricts itself to; the report states the HTTP call counts
- `df -h /` before the clone; abort under 20 GB free (Step 1)
- Unit test: calling `ensure_payload_indexes()` twice changes nothing (Step 1)

**Acceptance / falsification criterion.** Step 0: a verdict from the pre-fixed rule with the per-seed table. Step 1: the verdict applies the stated rule to each binding filter separately; falsified if overlap with the index is not strictly greater than without it.

**Gates / depends on.** Depends on: EV-14 (done). Operator answers: F2 (vector store use). Gates: none. RQ-5 and RQ-1 listed earlier as dependencies only order edits to `rag/vector_index.py`; check whether they are still needed before Step 1.

**Needs.** GPU: n · services up: vector store (CPU container); no GPU services · operator sign-off: n (no protected path is touched) · re-embed: n. Step 1 also needs 6 to 8 GB free for one clone.

**Model tier and size.** Sonnet; M (Step 0 alone is S).

**Risk and rollback.** Index build on a large clone could fill the disk or slow other work. Mitigation: free-space abort rule, one clone, deleted after. Rollback: delete the clone; revert the code (no live collection touched).

**Docs to update in the same PR.** Per `docs/AGENT-PROCEDURES.md` section B: flip this ticket's row in `docs/BACKLOG.md` to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 ledger; add a row to `docs/eval-reports/EXPERIMENT-REGISTER.md` for any new result; add a section 7 doc-map row for every new `docs/*.md`. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns.
