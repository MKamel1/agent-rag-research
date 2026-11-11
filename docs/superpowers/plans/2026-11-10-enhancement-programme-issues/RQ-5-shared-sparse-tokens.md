Title: RQ-5: Extract one shared sparse_tokens() used by the index
Labels: wave:1-no-gpu, area:retrieval, size:S

## RQ-5 -- Extract one shared sparse_tokens() used by the index

**Review cross-reference:** none: RV-1 F-1.10, prerequisite of RIDER-1 item 4. **Wave:** W1 do now, no GPU.

**Why.** The fake vector store keeps its own `lower().split()` (`rag/fakes/fake_vector_store.py:131`) while the real index tokenizes and repairs ligatures in `_sparse_vector`, so a tokenizer change cannot fail any fake-backed test (review item h residual risk 2; RV-1 F-1.10). RIDER-1 item 4 makes the fake import a shared function, but that function must exist first and it is not a protected path.

**Scope.**
- In:
  - A small pure module (no vendor import, so vendor isolation holds) exposing `sparse_tokens(text)`, containing exactly today's behaviour including CQ-1's ligature repair, imported by `VectorIndex._sparse_vector`.
  - A test that pins the checksum of `rag/ligature_map.json` so the map cannot drift silently (review section 2, CQ-1: no test pins it).
- Out (explicitly):
  - Any tokenizer behaviour change (edge-punctuation stripping and BM25 weighting are CQ-17). Editing the fake (RIDER-1). A filter-parity test against an in-memory vector store (RV-1 F-1.10 part 2, not carried by the review).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/sparse_tokens.py`
- `rag/test_sparse_tokens.py`
- `rag/vector_index.py`
- `rag/test_vector_index.py`

**Commits** (① is a stub, committed before any real work):
① stub: module docstring stating 'behaviour-preserving extraction of the tokenizer in `_sparse_vector`'
② characterisation tests pinning today's tokens on a sample including damaged ligatures, and the ligature-map checksum
③ extraction to green; `_sparse_vector` calls it
④ mutation proof recorded: changing the shared function fails the vector-index tests

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/sparse_tokens.py rag/test_sparse_tokens.py rag/vector_index.py rag/test_vector_index.py`
- Identical sparse vectors before and after on 200 stored main chunks, read-only (script output quoted; no index touched)
- `conda run -n agent-rag-research python -m pytest -q rag/test_sparse_tokens.py rag/test_vector_index.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Sparse vectors for a fixed sample of chunk texts are byte-identical before and after the extraction; mutating the shared function fails the vector-index tests. Falsified if any sampled vector differs.

**Gates / depends on.** Depends on: RQ-1. Gates: EP-3, EV-14, CQ-9, CQ-17, RIDER-1.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Extraction subtly changes tokens, which would silently desynchronise stored sparse vectors from query tokens. Mitigation: the identical-vectors check. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (new `rag/` module) and the ARCHITECTURE.md module list; the ARCHITECTURE line is in this PR, the ledger via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
