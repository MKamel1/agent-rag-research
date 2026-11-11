Title: CQ-17: Add BM25 saturation and length normalisation to the sparse arm behind a flag
Labels: wave:3-gated-change, area:corpus, area:retrieval, size:M

## CQ-17 -- Add BM25 saturation and length normalisation to the sparse arm behind a flag

**Review cross-reference:** S-25. **Wave:** W3 gated changes after baselines.

**Why.** The sparse arm is raw term frequency times IDF with no saturation or length normalisation although its docstring says 'BM25-style' (`rag/vector_index.py:112`); legacy main chunks are unbounded (8,487 chunks over 8,000 characters), so long chunks can dominate (RV-1 F-1.6). A sparse recompute is CPU-only, so bundling it with ligature repair 'to save cost' is wrong and would confound attribution (review S-25).

**Scope.**
- In:
  - Index-time weight `tf*(k1+1)/(tf + k1*(1-b+b*len/avglen))` behind an explicit option, `avglen` measured once per corpus from stored chunks (CPU) and recorded; applies only when (re)computing sparse vectors (`app.resparse` on a clone); default off.
  - Starts only after EV-22 (S-17 done).
- Out (explicitly):
  - Edge-punctuation stripping in the tokenizer (measured effect on 12-26% of tokens, but it changes tokens; include only if the operator wants it in this A/B: stated as a separate flag, never bundled). Applying to any live collection. The A/B (CQ-18).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `rag/sparse_tokens.py`
- `rag/test_sparse_tokens.py`
- `app/resparse.py`
- `app/test_resparse.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring with the formula, parameters (k1, b, avglen), the default-off guarantee and the one-recompute-per-arm rule
② failing tests: option off leaves vectors byte-identical; option on gives the expected weights on a toy corpus
③ implementation to green
④ avglen measurement helper and recorded constants per corpus

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py rag/sparse_tokens.py rag/test_sparse_tokens.py app/resparse.py app/test_resparse.py`
- Identical sparse vectors with the option off on 200 stored chunks (RQ-5 check reused)
- `conda run -n agent-rag-research python -m pytest -q rag/test_vector_index.py rag/test_sparse_tokens.py app/test_resparse.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Option off: byte-identical vectors; option on: weights match a hand-computed toy example; avglen constants recorded with the command that produced them. Falsified if default behaviour changes by one byte.

**Gates / depends on.** Depends on: EV-22, CQ-9, RQ-5. Gates: CQ-18, EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Query-side tokens stay binary while index weights change, which a later reader might misread as a bug. Mitigation: documented in the docstring. Rollback: revert; no index depends on it.

**Docs to update in the same PR.** PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
