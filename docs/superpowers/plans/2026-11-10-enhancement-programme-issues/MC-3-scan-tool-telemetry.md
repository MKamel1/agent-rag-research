Title: MC-3: Record arguments and errors for scan and get tools in the usage log
Labels: wave:1-no-gpu, area:mcp, size:S

## MC-3 -- Record arguments and errors for scan and get tools in the usage log

**Review cross-reference:** S-11. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** bind pattern/args and the error message only; the `--client-label` flag is cut (no MCP work is scheduled that consumes it). Decoupled from OP-2 (parked). The MC-2 -> MC-3 edge is an ownership order only (both own `app/serve.py`), not a data dependency.

**Why.** 213 scan calls (18% of all 1,198 logged calls) have no pattern recorded, `get_section`, `get_span` and `get_paper` rows carry no arguments, errors store only the exception class name, and `source` is constant, so harness replays look like agent sessions (RV-4 F-4.5; review S-11). The usage log is the only evidence base for any future MCP work, and it is blind exactly where agents behave most like brute force.

**Scope.**
- In:
  - Bind pattern, method or section path into the existing `query` column, the argument `paper_id`, `result_count` from the result length and `str(e)[:200]` into `error`. No schema change; existing rows stay valid.
- Out (explicitly):
  - A `--client-label` flag and any change to `source` (cut by the minimizer). New columns (top score, returned ids: RV-6 F-A9, dropped). Dashboard changes. Any retrieval change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/usage_log.py`
- `app/test_usage_log.py`
- `app/serve.py`
- `app/test_serve.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the per-tool binding table
② failing tests per tool (scan_corpus, scan_methods, get_section, get_span, get_paper, errors)
③ implementation to green

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/usage_log.py app/test_usage_log.py app/serve.py app/test_serve.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_usage_log.py app/test_serve.py -o addopts="--disable-socket"`
- On a scratch usage database: one mixed fake session then `select tool, query from requests where tool like 'scan%'` shows no NULL query

**Acceptance / falsification criterion.** After one scripted mixed session on fakes, no scan row has a NULL `query` and every get_* row has its `paper_id`; error rows carry the message prefix. Falsified if any tool still writes a NULL where its argument exists.

**Gates / depends on.** Depends on: MC-2 (ordering only: same file, not a data dependency). Gates: OP-2 (parked), MC-4 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Logging full regex patterns could store sensitive text. Mitigation: the log is local and already stores queries; length is capped. Rollback: revert; rows written stay valid.

**Docs to update in the same PR.** Section 2: what the usage log now records for scan and get tools. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
