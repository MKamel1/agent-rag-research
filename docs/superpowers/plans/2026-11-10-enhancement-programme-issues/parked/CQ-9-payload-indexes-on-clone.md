Title: CQ-9: Add idempotent payload indexes and verify them on a clone
Labels: wave:3-gated-change, area:corpus, area:retrieval, needs-services, size:M, parked
Parked-until: start only if EV-14 reports overlap below 0.99 on at least one of the three filters. Kill criterion: killed if EV-14 overlap is at least 0.99 on all three filters, or no baseline query returned fewer than k hits.

## CQ-9 -- Add idempotent payload indexes and verify them on a clone

**Review cross-reference:** S-22. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if EV-14 reports overlap below 0.99 on at least one of the three filters. Kill criterion: killed if EV-14 overlap is at least 0.99 on all three filters, or no baseline query returned fewer than k hits.

**Why.** If EV-14 shows filtered HNSW search loses neighbours against exact search, payload indexes are the repair; they rebuild HNSW links, a CPU and disk cost, so they must be proven on a clone first (review S-22; RV-1 F-1.2). If EV-14 shows overlap of at least 0.99, this ticket is closed unstarted.

**Scope.**
- In:
  - `ensure_payload_indexes()` in `VectorIndex` (idempotent; keyword indexes for `kind`, `doc_type`, `paper_id`, `author_orgs`, `curated_author_orgs`, `categories`; datetime for `published`) and a call from `_ensure_collection` for new collections only.
  - On a clone: build the indexes, re-run the EV-14 script, report overlap with and without the index and the count of queries returning fewer than k.
- Out (explicitly):
  - Applying to any live collection (follow-on ticket, written only on ADOPT, with explicit operator approval, because it changes candidate sets slightly everywhere). Any GPU use.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `docs/eval-reports/<run-date>-payload-index-clone.md`
- `docs/eval-reports/data/<run-date>-payload-index-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule written before the clone is touched: ADOPT if overlap with the index is at least 0.99 and strictly greater than without, and queries returning fewer than k fall to 0
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ `ensure_payload_indexes` with tests on mocked clients
④ clone: build indexes, time and size recorded
⑤ re-run of the EV-14 script on the indexed clone; verdict; clone deleted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py`
- `df -h /` before the clone; abort under 20 GB free
- Unit test: calling `ensure_payload_indexes()` twice changes nothing

**Acceptance / falsification criterion.** Verdict applies the stated rule to the three filters separately; build time, added disk and p50 query latency before and after are reported. Falsified if overlap with the index is not strictly greater than without it.

**Gates / depends on.** Depends on: EV-14, RQ-5, RQ-1. Operator answers: F2. Gates: none.

**Needs.** GPU: n · services up: vector store (CPU container) up; no GPU services · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (F2); 6-8 GB free for one clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Index build on a large clone could fill the disk or slow other work. Mitigation: free-space abort rule, one clone, deleted after. Rollback: delete the clone; revert the code (no live collection touched).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
