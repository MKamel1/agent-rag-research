Title: MC-4: Slim the MCP wire by projecting duplicated envelope fields away
Labels: wave:3-gated-change, area:mcp, size:S

## MC-4 -- Slim the MCP wire by projecting duplicated envelope fields away

**Review cross-reference:** S-26. **Wave:** W3 gated changes after baselines.

**Why.** 57-58% of a standards `semantic_search` response is envelope rather than passage (k=10 is about 4.2k tokens; a Waymo call averages about 10.8k): `bbox`, a `snippet` that lies inside `passage_text` for 94-100% of results, and repeated `paper_id`/`block_id`. Agents already lower `k` to cope (RV-4 F-4.6; review S-26).

**Scope.**
- In:
  - In `app/serve.py`, project the response with `model_dump(exclude=...)` for `bbox`, the duplicated `anchor.snippet` and the repeated `anchor.paper_id`/`citation.paper_id`; the contract objects are untouched.
  - Starts only if the operator answers F5 yes (the wire may be a projection of the frozen envelope).
- Out (explicitly):
  - Snippet-only passages by default (the logs show search-then-`get_span` verification habits). Changing `search_papers` section paths (`PaperSummaryView`, a contract change). `get_span` behaviour.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/serve.py`
- `app/test_serve.py`
- `scripts/mcp_wire_tokens.py`
- `scripts/test_mcp_wire_tokens.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the projection list and the invariant that `passage_text`, `citation` and `get_span(anchor)` round-trip are unchanged
② failing tests: projected JSON lacks the four fields; `passage_text` and `citation` equal the unprojected values; `get_span` on a projected anchor still resolves
③ implementation to green
④ token-count script (skips cleanly if the tokenizer package is absent) and measurement on standards- and Waymo-sized fixtures

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/serve.py app/test_serve.py scripts/mcp_wire_tokens.py scripts/test_mcp_wire_tokens.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_serve.py scripts/test_mcp_wire_tokens.py -o addopts="--disable-socket"`
- Token count before/after on a realistic response fixture quoted in the PR

**Acceptance / falsification criterion.** Token count of a standards k=10 response falls by at least 25% with identical `passage_text` and citation content; `get_span` still round-trips. Falsified if `passage_text` differs anywhere or the drop is under 25%.

**Gates / depends on.** Depends on: MC-3. Operator answers: F5. Gates: EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched); operator answers: F5 · re-embed: n. Also: operator answer F5 (wire as a projection of the frozen envelope).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A client that read a dropped field breaks. Mitigation: only fields no LLM can use are dropped; the dropped list is documented in the server instructions. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
