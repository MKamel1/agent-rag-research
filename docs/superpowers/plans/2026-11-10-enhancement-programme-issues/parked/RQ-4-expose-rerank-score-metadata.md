Title: RQ-4: Expose the cross-encoder score in result metadata
Labels: wave:4-rider, area:retrieval, area:mcp, needs-signoff, size:S, parked
Parked-until: only after an abstention feature is commissioned, the EV-19 census gate can open (60+ distinct absent items) and RIDER-1 has landed. Kill criterion: killed if the EV-19 census CI contains 0.5 on two of three sets.

## RQ-4 -- Expose the cross-encoder score in result metadata

**Review cross-reference:** S-20. **Wave:** W4 rider and what it unblocks.

**Parked, do not start.** Parked-until: only after an abstention feature is commissioned, the EV-19 census gate can open (60+ distinct absent items) and RIDER-1 has landed. Kill criterion: killed if the EV-19 census CI contains 0.5 on two of three sets.

**Why.** Only if the census (EV-19) shows the reranker score separates answerable from absent: callers today get the fusion score, which carries no absolute relevance, so no abstention or focus signal can be built on it (review item a; RV-4 F-4.1). `GroundedResult.metadata` is the contract-reserved slot, so populating it is the rider's act.

**Scope.**
- In:
  - After the rider note merges: populate `metadata["rerank_score"]` from the experiment-only `rerank_scored()` path (promoted to the normal rerank path), keep `score` exactly as it is.
- Out (explicitly):
  - Changing `score` semantics. Building a floor or abstention from it (needs 60 or more distinct absent items and a pre-registered falsifier; RV-3 F-1.10).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/retriever.py`
- `rag/test_retriever.py`
- `rag/reranker.py`
- `rag/test_reranker.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating `metadata['rerank_score']` and that `score` is unchanged
② failing tests: metadata present and equal to the reranker score; `score` and order unchanged on the fake
③ implementation to green
④ docs line for DATA-CONTRACTS section M7 cross-checked against the rider's wording

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/retriever.py rag/test_retriever.py rag/reranker.py rag/test_reranker.py`
- Existing retriever and reranker tests unchanged and green
- Identity check: result order and `score` byte-equal to the pre-change commit on the fake

**Acceptance / falsification criterion.** Metadata carries the reranker score; `score`, order and `passage_text` are byte-identical to before on the fake; the EV-16 rows reproduced on a small live sample match order exactly. Falsified if any order or `score` differs.

**Gates / depends on.** Depends on: RIDER-1, EV-19, RQ-1. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: y: blocked by RIDER-1 item 3 (contract note) merging · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A caller treating the new field as calibrated confidence. Mitigation: the contract note says 'uncalibrated rank-order score'. Rollback: revert.

**Docs to update in the same PR.** DATA-CONTRACTS section M7 paragraph rides the RIDER-1 amendment that adopts this item. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
