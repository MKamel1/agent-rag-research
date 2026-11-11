Title: OP-2: Construct the vector index lazily so the server starts without it
Labels: wave:1-no-gpu, area:ops, area:mcp, size:M

## OP-2 -- Construct the vector index lazily so the server starts without it

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Why.** OP-1 made a down vector store exit with an actionable message, but the server still cannot start without it: `build_mcp_server` constructs the vector index eagerly and that constructor makes a network call. `app/serve.py` carries the note 'SQLite-only tools could run without it if the vector index were constructed lazily (follow-up ticket)'. Eight of the ten MCP tools need only SQLite.

**Scope.**
- In:
  - Construct the vector index on first use (or through a lazy proxy) so `get_paper`, `get_span`, `get_section`, `scan_corpus`, `scan_methods`, `list_methods`, `get_figures` and `corpus_stats` work with the vector store down; `semantic_search` and `search_papers` raise the existing actionable transient error.
  - Call `require_existing_db()` (OP-6) in both `app/serve.py` branches (the serve part of review S-07).
  - Replace the OP-1 'follow-up ticket' comment.
- Out (explicitly):
  - Changing how TEI or the GPU lock are handled (OP-1, OP-5). Any tool signature or contract change. Health-checking the store at startup beyond what doctor does.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/assembly.py`
- `app/test_assembly.py`
- `app/serve.py`
- `app/test_serve.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating which tools work with the store down and which raise
② failing tests: factory that raises TransientError at construction -> server builds, a SQLite tool answers, a search tool raises the actionable error, `list_tools` still lists ten tools
③ implementation to green
④ serve.py: exists-check call sites and comment replaced

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/assembly.py app/test_assembly.py app/serve.py app/test_serve.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_assembly.py app/test_serve.py -o addopts="--disable-socket"`
- `list_tools` dump (no GPU) shows ten tools

**Acceptance / falsification criterion.** With the vector store construction failing, the server builds and the eight SQLite tools answer on fakes; the two search tools raise the actionable error naming `python -m app.doctor --cpu-only`; the tool list is unchanged. Falsified if any SQLite tool touches the vector index or if a search tool returns an empty result instead of raising.

**Gates / depends on.** Depends on: OP-5, OP-6, MC-3. Gates: EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Misconfiguration (wrong collection) surfaces on first search instead of at startup. Mitigation: doctor still checks the pairing (OP-6); the first-use error names the collection. Rollback: revert; behaviour returns to eager construction.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (serve behaviour) via EP-3; RUNBOOK mention via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
