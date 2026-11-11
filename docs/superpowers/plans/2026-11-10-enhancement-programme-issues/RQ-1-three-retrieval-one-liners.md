Title: RQ-1: Fix three one-line retrieval defects (payload, partial rerank, cap)
Labels: wave:1-no-gpu, area:retrieval, size:S

## RQ-1 -- Fix three one-line retrieval defects (payload, partial rerank, cap)

**Review cross-reference:** S-09. **Wave:** W1 do now, no GPU.

**Why.** (1) `hybrid_search` requests the full payload (including chunk text) for up to 10,000 hits per arm but uses two fields (`rag/vector_index.py:286,296`; about 50 MB per main query, latency inferred). (2) A malformed partial reranker reply silently drops candidates: nothing checks the scored indices form a permutation before `rag/reranker.py:231`. (3) `max_hits_per_paper` applied together with `paper_id` returns fewer than `k` (RV-1 F-1.7, F-1.8 #7, RV-4 F-4.11; review S-09).

**Scope.**
- In:
  - `with_payload=[_EXT_ID_KEY, "kind"]` on both arms, after a grep proving no other payload field is read downstream (CONVENTIONS section 14: carry the check).
  - Raise `PermanentError` when the returned index set is not a permutation of the sent indices.
  - Skip the per-paper cap when `paper_id` is set.
- Out (explicitly):
  - Retry around vector-store calls, fusion depth changes, a reranker-failure fallback (all behaviour changes). Any ranking change: this ticket must leave `Hit` lists identical for queries without a `paper_id` filter.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `rag/reranker.py`
- `rag/test_reranker.py`
- `rag/retriever.py`
- `rag/test_retriever.py`

**Commits** (① is a stub, committed before any real work):
① stub: three docstring lines, one per defect, with the intended behaviour
② failing tests: identical `Hit` lists before and after on the fake; a stub client returning 31 of 32 indices raises; `paper_id` plus cap returns `k`
③ three fixes, one commit each, each green
④ grep evidence for 'payload fields read downstream' recorded in the commit body

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py rag/reranker.py rag/test_reranker.py rag/retriever.py rag/test_retriever.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_vector_index.py rag/test_reranker.py rag/test_retriever.py -o addopts="--disable-socket"`
- Sibling-path check: state in the PR what happens with `paper_id` set and no cap, and with a cap and no `paper_id`

**Acceptance / falsification criterion.** Not a ranking change, so no A/B: the falsifier is that `Hit` id and score lists are identical before and after on the fake for any query without a `paper_id`+cap combination; the 31-of-32 stub raises; the `paper_id`+cap test returns `k`. The EV-16 baselines run on this code, so any real-index difference would show as an unexplained delta against the pre-change commit recorded in each run manifest. Falsified if the identical-hits test fails.

**Gates / depends on.** Depends on: none. Gates: EP-3, RQ-5, RQ-2, EV-13, EV-16, CQ-9, RQ-4.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Narrowing the payload could break a reader that silently used another field. Mitigation: the grep and the identical-hits test. Rollback: revert (three independent commits).

**Docs to update in the same PR.** PROJECT-STATUS ledger via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
