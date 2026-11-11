Title: EV-14: Measure filtered-search overlap with exact search on the live collection (read-only)
Labels: wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:S

## EV-14 -- Measure filtered-search overlap with exact search on the live collection (read-only)

**Review cross-reference:** S-15. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** no clone is made: search is read-only, so exact versus HNSW runs on the live collection; the OP-4 and RQ-5 dependencies are dropped. CPU-only (the vector store container, no embedder, no reranker), so it can run while the GPU is busy.

**Why.** No payload index exists on any live collection (every segment's `payload_index/config.json` is `{"indexed_fields":{}}`; 8, 7 and 8 segments), yet every query is filtered. The recall loss is inferred from the vector store's documented design, not measured (the minimizer notes the harm is inferred, not observed; this is the cheap closer); the real risk band is mid-selectivity filters (`kind=summary` is 3% of points and is the whole `search_papers` path; `doc_type=book`) (review item b; RV-1 F-1.2).

**Scope.**
- In:
  - Read-only on the live collection (never a write, never an index change): use 100 stored summary vectors as queries and compare exact search with the default HNSW search for `kind=summary`, `doc_type=book` and a single `paper_id`; report overlap@k per filter. Reuse CQ-2's read-only sampling helpers; if an exact-search method is missing from `VectorIndex`, add one small read-only method there (vendor SDK calls stay inside that adapter).
  - Pre-registered falsifier (commit 1): HNSW overlap with exact is at least 0.99 on all three filters, then payload-index work (parked CQ-9) is closed.
- Out (explicitly):
  - Cloning the collection. Creating payload indexes (parked CQ-9). Any write to the collection. Any GPU use: stored vectors are the queries, nothing is embedded.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `scripts/payload_index_overlap.py`
- `scripts/test_payload_index_overlap.py`
- `docs/eval-reports/data/<run-date>-payload-index-overlap/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the pre-registered 0.99 falsifier and the three filters, committed before any query is sent
② exact-search read-only method (only if missing) and the script, unit-tested against mocked clients
③ dry run on 10 queries against the live collection
④ full run; report with the overlap table and the verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py scripts/payload_index_overlap.py scripts/test_payload_index_overlap.py`
- `conda run -n agent-rag-research python scripts/payload_index_overlap.py --help` shows required `--collection`; the script issues no write call (a unit test asserts the client double records none)
- Report table has one row per filter with overlap@10 and the count of queries returning fewer than k

**Acceptance / falsification criterion.** Report states overlap of HNSW versus exact for each of the three filters on the live collection. Verdict is mechanical: all three at least 0.99 closes the finding (parked CQ-9 is then killed); any below 0.99 satisfies CQ-9's trigger. Falsified (finding closed) if all three are 0.99 or more. No write to the collection occurred.

**Gates / depends on.** Depends on: none. Operator answers: F2. Gates: CQ-9 (parked).

**Needs.** GPU: n · services up: vector store (CPU container) up; no embedder, no reranker · operator sign-off: n (no protected path is touched); operator answers: F2 (start the vector store container) · re-embed: n.

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Adding a method to `rag/vector_index.py` that is read-only by construction; the live collection is only read. Rollback: revert.

**Docs to update in the same PR.** The overlap report is a new doc (section 7 doc-map row); section 5/6 gets the verdict (finding closed or CQ-9 trigger met). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
