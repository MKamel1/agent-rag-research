Title: EV-9: Record retrieved chunk ids in eval rows
Labels: wave:1-no-gpu, area:eval, size:S

## EV-9 -- Record retrieved chunk ids in eval rows

**Review cross-reference:** S-05. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** only the additive `retrieved_chunk_ids` row field stays (rows from the 1-2 h standards run cannot be recollected cheaply, and EV-18 prints the structure-gate count from them); the `scripts/list_stub_chunks.py --ab` rewiring is cut and is done only if EV-21 is commissioned. The EV-9 -> EV-10 edge is a file-ownership order only (both own `app/retrieval_eval.py`), not a data dependency.

**Why.** Report rows carry only `retrieved_block_ids` (`app/retrieval_eval.py:229,371,551`), and `scripts/list_stub_chunks.py` identifies a stub by its anchor block, which is ambiguous for the 7.5% of standards chunks that share an anchor (35,714 chunks, 33,053 distinct anchors; RV-1 F-1.3, review section 2 on CQ-3). EV-18's structure-gate count and any later stub analysis (parked EV-21) need per-chunk identity in the rows.

**Scope.**
- In:
  - Add `retrieved_chunk_ids` to the per-question row. `GroundedResult` has no chunk id, so recover it from (paper id, anchor block id, passage text) through the document store the harness already holds; where two chunks match, record both and mark the row ambiguous.
- Out (explicitly):
  - `scripts/list_stub_chunks.py --ab` matching by chunk id (parked EV-21 does that if it is commissioned).
  - Any `contracts/` change. If chunk ids cannot be recovered without one, STOP and report: that is a RIDER-1 candidate, not an edit.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring of the recovery rule and the ambiguity marker
② failing tests: unique recovery; duplicate-text ambiguity marked; a shared-anchor fixture yields both chunk ids and the ambiguous flag
③ implementation to green

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** On a fixture with two chunks sharing one anchor, the row lists both chunk ids and is marked ambiguous; ambiguous rows are counted in the report, not hidden. Falsified if recovery silently picks one of two matching chunks.

**Gates / depends on.** Depends on: EV-8 (ordering only: same file, not a data dependency). Gates: EV-10, EV-6b, EV-12 (parked), EV-16, EV-18, EV-21 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Recovery by text may be slow on 30,000-chunk papers. Mitigation: per-paper lookup, cached. Rollback: revert; additive field.

**Docs to update in the same PR.** Section 2: the new `retrieved_chunk_ids` row field. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
