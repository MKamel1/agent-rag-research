Title: MC-2: Make the MCP server describe its corpus, filters and limits
Labels: wave:1-no-gpu, area:mcp, size:M

## MC-2 -- Make the MCP server describe its corpus, filters and limits

**Review cross-reference:** S-10. **Wave:** W1 do now, no GPU.

**Why.** A cold agent sees no server instructions, zero field descriptions in the `SearchFilters` schema, and docstring guidance that FastMCP never exposes; `doc_type` was used 0 times in 1,198 logged calls, and wrong-corpus queries appear in the main log (ids 8, 21-24) (RV-4 F-4.3, F-4.4; review S-10). Hard-coded counts and a stale 32-ceiling paragraph in docstrings can disagree with the corpus.

**Scope.**
- In:
  - Pass `instructions=` to `FastMCP`, generated at startup from `corpus_stats()` (what the corpus is, counts, date range, document kinds, which filters are meaningful, a five-line tool map), under 250 tokens.
  - A compact filter legend in the `semantic_search` tool docstring (the field schema is protected). Delete hard-coded counts and the 32-ceiling paragraph.
  - `corpus_stats` gains a compact `documents` list (id, title, kind, year, status) when the corpus has 500 documents or fewer; kind and status are read from the standards metadata tags if present (CQ-5), omitted otherwise (no hard dependency).
- Out (explicitly):
  - Field descriptions on `SearchFilters` (contracts edit, RIDER-1 territory). A per-corpus card file or Config key. Federation across corpora. Response slimming (MC-4).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/serve.py`
- `app/test_serve.py`
- `rag/mcp_server.py`
- `rag/test_mcp_server.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the instructions contract (generated, under 250 tokens, no literal counts)
② failing tests: `instructions` present and under budget; every filter named in the legend; no number in any description absent from `corpus_stats`; `documents` present only at 500 documents or fewer
③ implementation to green
④ docstring cleanup commit

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/serve.py app/test_serve.py rag/mcp_server.py rag/test_mcp_server.py`
- `list_tools` and `initialize().instructions` dump built on fakes (no GPU, no store); output quoted in the PR
- `conda run -n agent-rag-research python -m pytest -q app/test_serve.py rag/test_mcp_server.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Instructions exist and stay under 250 tokens on a standards-sized and a main-sized fake; every filter appears in the legend; no description contains a literal count that disagrees with `corpus_stats`. Falsified if a description number is not derived from `corpus_stats`.

**Gates / depends on.** Depends on: MC-1. Gates: EP-3, MC-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Generated text that is wrong for a corpus misleads every cold session. Mitigation: the text is derived from `corpus_stats` only; a test pins that. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (what the server advertises) via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
