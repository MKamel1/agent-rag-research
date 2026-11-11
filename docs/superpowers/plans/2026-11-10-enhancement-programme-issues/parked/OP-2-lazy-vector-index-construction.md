Title: OP-2: Construct the vector index lazily so the server starts without it
Labels: wave:1-no-gpu, area:ops, area:mcp, size:M, parked
Parked-until: only after the operator needs the MCP server to start with the services down. Kill criterion: none.

## OP-2 -- Construct the vector index lazily so the server starts without it

**Review cross-reference:** S-07. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after the operator needs the MCP server to start with the services down. Kill criterion: none.

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

**Gates / depends on.** Depends on: OP-5, OP-6, MC-3 (ordering only: shared `app/serve.py`). Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Misconfiguration (wrong collection) surfaces on first search instead of at startup. Mitigation: doctor still checks the pairing (OP-6); the first-use error names the collection. Rollback: revert; behaviour returns to eager construction.

**Docs to update in the same PR.** Section 2: serve behaviour. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
