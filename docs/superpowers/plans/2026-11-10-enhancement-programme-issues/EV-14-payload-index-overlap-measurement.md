Title: EV-14: Measure filtered-search overlap with exact search on a clone
Labels: wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:M

## EV-14 -- Measure filtered-search overlap with exact search on a clone

**Review cross-reference:** S-15. **Wave:** W1 do now, no GPU.

**Why.** No payload index exists on any live collection (every segment's `payload_index/config.json` is `{"indexed_fields":{}}`; 8, 7 and 8 segments), yet every query is filtered. The recall loss is inferred from the vector store's documented design, not measured; the real risk band is mid-selectivity filters (`kind=summary` is 3% of points and is the whole `search_papers` path; `doc_type=book`) (review item b; RV-1 F-1.2).

**Scope.**
- In:
  - On a clone made with `VectorIndex.clone_points_into` (never the live collection): use 100 stored summary vectors as queries and compare exact search with the default HNSW search for `kind=summary`, `doc_type=book` and a single `paper_id`; report overlap@k per filter. Reuse CQ-2's read-only sampling helpers; if an exact-search method is missing from `VectorIndex`, add one small read-only method there (vendor SDK calls stay inside that adapter).
  - Pre-registered falsifier (commit 1): HNSW overlap with exact is at least 0.99 on all three filters, then payload-index work (CQ-9) is closed.
- Out (explicitly):
  - Creating payload indexes (CQ-9). Touching the live collection. Any GPU use: stored vectors are the queries, nothing is embedded.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `scripts/payload_index_overlap.py`
- `scripts/test_payload_index_overlap.py`
- `docs/eval-reports/data/<run-date>-payload-index-overlap/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the pre-registered 0.99 falsifier and the three filters, committed before the clone is made
② exact-search read-only method and the script, unit-tested against mocked clients
③ clone created; dry run on 10 queries; free space recorded
④ full run; report with the overlap table and the verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py scripts/payload_index_overlap.py scripts/test_payload_index_overlap.py`
- `df -h /` before cloning (needs 6-8 GB free per clone, review F2)
- `conda run -n agent-rag-research python scripts/payload_index_overlap.py --help` shows required `--collection` and a `--target-is-clone` guard
- Report table has one row per filter with overlap@10 and the count of queries returning fewer than k

**Acceptance / falsification criterion.** Report states overlap of HNSW versus exact for each of the three filters. Verdict is mechanical: all three at least 0.99 closes the finding; any below 0.99 opens CQ-9. Falsified (finding closed) if all three are 0.99 or more. The clone is deleted afterwards and its deletion is recorded.

**Gates / depends on.** Depends on: RQ-5, OP-4. Operator answers: F2. Gates: EP-3, CQ-9.

**Needs.** GPU: n · services up: vector store (CPU container) up; no embedder, no reranker · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (operator question F2) and 6-8 GB free for one clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Cloning on a 98%-full disk. Mitigation: OP-4 first, free-space check, one clone at a time, deleted after. The live collection is only read. Rollback: delete the clone.

**Docs to update in the same PR.** Report is the doc; PROJECT-STATUS section 5/6 via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
