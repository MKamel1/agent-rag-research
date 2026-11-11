Title: EV-9: Record retrieved chunk ids in eval rows; match stubs by chunk id
Labels: wave:1-no-gpu, area:eval, size:S

## EV-9 -- Record retrieved chunk ids in eval rows; match stubs by chunk id

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Why.** Report rows carry only `retrieved_block_ids` (`app/retrieval_eval.py:229,371,551`), and `scripts/list_stub_chunks.py` identifies a stub by its anchor block, which is ambiguous for the 7.5% of standards chunks that share an anchor (35,714 chunks, 33,053 distinct anchors; RV-1 F-1.3, review section 2 on CQ-3). The CQ-3 addendum (EV-12) needs per-chunk identity.

**Scope.**
- In:
  - Add `retrieved_chunk_ids` to the per-question row. `GroundedResult` has no chunk id, so recover it from (paper id, anchor block id, passage text) through the document store the harness already holds; where two chunks match, record both and mark the row ambiguous.
  - `scripts/list_stub_chunks.py --ab` matches stubs by chunk id.
- Out (explicitly):
  - Any `contracts/` change. If chunk ids cannot be recovered without one, STOP and report: that is a RIDER-1 candidate, not an edit.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`
- `scripts/list_stub_chunks.py`
- `scripts/test_list_stub_chunks.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of the recovery rule and the ambiguity marker
② failing tests: unique recovery; duplicate-text ambiguity marked; stub-at-rank-1 share computed by chunk id equals anchor-based share where anchors are unique, and differs on a shared-anchor fixture
③ implementation to green
④ list_stub_chunks wired

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py scripts/list_stub_chunks.py scripts/test_list_stub_chunks.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py scripts/test_list_stub_chunks.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** On a fixture with two chunks sharing one anchor, the stub-at-rank-1 share is computed per chunk and the anchor-based figure is shown to differ; ambiguous rows are counted, not hidden. Falsified if recovery silently picks one of two matching chunks.

**Gates / depends on.** Depends on: EV-8. Gates: EP-3, EV-10, EV-12, EV-21.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Recovery by text may be slow on 30,000-chunk papers. Mitigation: per-paper lookup, cached. Rollback: revert; additive field.

**Docs to update in the same PR.** PROJECT-STATUS section 2 via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
