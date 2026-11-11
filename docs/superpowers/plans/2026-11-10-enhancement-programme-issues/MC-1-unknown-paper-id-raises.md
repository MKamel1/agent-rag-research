Title: MC-1: Raise an error for an unknown paper_id filter instead of returning empty
Labels: wave:1-no-gpu, area:mcp, size:S

## MC-1 -- Raise an error for an unknown paper_id filter instead of returning empty

**Review cross-reference:** S-08. **Wave:** W1 do now, no GPU.

**Why.** `filters.paper_id` with an unknown or wrongly formed id returns an empty result with no error, while `get_paper` raises for the same id. In the standards usage log one call with an `arxiv:`-prefixed id (row 327) returned empty and the next with the bare stored id (row 337) succeeded (RV-4 F-4.2, confirmed by the review). An agent reads the empty result as 'this standard does not discuss X'.

**Scope.**
- In:
  - In `McpServer.semantic_search` and `search_papers`: when `filters.paper_id` is set, resolve it against the document store; on a miss raise `ContractError` with the same wording style as `get_paper` plus a hint when the id starts with `arxiv:` (the stored form has no prefix).
  - Reuse the existing `get_paper` resolution and error construction; no new lookup path.
- Out (explicitly):
  - Dropping the absolute database path from error text and other error rewording (RV-4 F-4.9, not carried by the review). Fuzzy nearest-id suggestions. Any contract change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/mcp_server.py`
- `rag/test_mcp_server.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring lines stating the new precondition and error
② failing tests: unknown id raises; `arxiv:`-prefixed id raises with the stripped hint; known id still returns results
③ implementation to green
④ docstring updated

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/mcp_server.py rag/test_mcp_server.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_mcp_server.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Unit tests: an unknown id raises `ContractError`; the `arxiv:`-prefixed form produces the hint; a valid id is unchanged. Mutation proof: remove the resolve call and the unknown-id test fails. Falsified if the unknown-id test passes with the resolve call removed.

**Gates / depends on.** Depends on: none. Gates: MC-2.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A valid-but-unindexed paper id now errors where it used to return empty. That is intended; it is also the same behaviour `get_paper` already has. Rollback: revert.

**Docs to update in the same PR.** Section 2: the unknown-`paper_id` error. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
