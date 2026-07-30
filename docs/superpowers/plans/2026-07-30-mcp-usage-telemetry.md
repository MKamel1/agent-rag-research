# MCP Usage Telemetry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every retrieval request the MCP server and the dashboard serve, into a dedicated SQLite database, so real usage can steer the next RAG enhancements.

**Architecture:** A new `app/usage_log.py` owns the store and a recording decorator. `app/serve.py`'s four `@mcp.tool()` functions and the dashboard's `/api/search` route are decorated. `rag/mcp_server.py` and `contracts/` are untouched — instrumentation belongs at the composition root, not inside the retrieval modules, and both of those are foundation-frozen or foundation-adjacent.

**Tech Stack:** Python 3.12, stdlib `sqlite3` (WAL), `functools.wraps`, pytest, pytest-socket.

## Global Constraints

- Deliverable 2 of `docs/superpowers/specs/2026-07-30-dashboard-dropin-and-usage-design.md` §3.
- **Do not modify** `contracts/`, `rag/mcp_server.py`, `rag/config.py`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`.
- **Never** write to `/home/omar/ai-projects/research-system-rag-data/papers.db`. This work creates a **separate** database, `<data_dir>/mcp_usage.db`.
- Never run `git stash`. Never merge a PR. Never pass `--admin` or a branch-protection bypass.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — chained in ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Before starting:** `git fetch origin && git checkout -b mcp-usage-telemetry origin/main`. Branching from a stale local `main` previously caused CI check (e) to flag foundation files this branch never touched.
- **Enforcement, run correctly.** The env var alone crashes (`KeyError: 'pull_request'`) — `ci/checks/changed_files.py::compute_diff_base` reads the parsed `GITHUB_EVENT_PATH`:

  ```bash
  EV=$(mktemp) && printf '{"pull_request":{"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- **The PR must have both `enforcement` and `unit-tests` reporting `pass` before you report DONE.** Poll `gh pr checks <n>` until every check has a final conclusion. If a check fails, capture the real reason with `gh run view <run-id> --log-failed` and report it verbatim.

---

### Task 1: `app/usage_log.py` — the store

**Files:**
- Create: `app/usage_log.py`
- Test: `app/test_usage_log.py`

**Interfaces:**
- Produces:
  - `UsageLog(db_path: Path)` with `record(*, source, tool, query, k, filters, latency_ms, result_count, candidates, error) -> None`
  - `read_usage_summary(db_path: Path) -> dict` (Task 3 calls this from the dashboard)

- [ ] **Step 1: Write the failing tests**

```python
def test_record_writes_a_row_and_creates_the_schema(tmp_path):
    log = usage_log.UsageLog(tmp_path / "mcp_usage.db")
    log.record(source="mcp", tool="semantic_search", query="do-calculus", k=10,
               filters=None, latency_ms=12.5, result_count=8, candidates=40, error=None)

    conn = sqlite3.connect(tmp_path / "mcp_usage.db")
    row = conn.execute(
        "SELECT source, tool, query, k, latency_ms, result_count, candidates, error "
        "FROM requests"
    ).fetchone()
    conn.close()
    assert row == ("mcp", "semantic_search", "do-calculus", 10, 12.5, 8, 40, None)


def test_record_denormalizes_doc_type_and_paper_id_out_of_filters(tmp_path):
    """'Are callers actually using book scoping?' is the query that steers the next
    enhancement -- it must not require JSON extraction over the whole table."""
    log = usage_log.UsageLog(tmp_path / "mcp_usage.db")
    log.record(source="mcp", tool="search_papers", query="q", k=5,
               filters=SearchFilters(doc_type="book", paper_id="local:abc123def456"),
               latency_ms=3.0, result_count=5, candidates=20, error=None)

    conn = sqlite3.connect(tmp_path / "mcp_usage.db")
    doc_type, paper_id, filters_json = conn.execute(
        "SELECT doc_type, paper_id, filters_json FROM requests"
    ).fetchone()
    conn.close()
    assert doc_type == "book"
    assert paper_id == "local:abc123def456"
    assert "book" in filters_json


def test_record_never_raises_when_the_db_is_unwritable(tmp_path):
    """A telemetry failure must never fail a retrieval. Same posture as
    app/telemetry.py::_query_gpu, which swallows every failure and returns None."""
    unwritable = tmp_path / "nonexistent_dir" / "mcp_usage.db"
    log = usage_log.UsageLog(unwritable)
    log.record(source="mcp", tool="get_paper", query=None, k=None, filters=None,
               latency_ms=1.0, result_count=None, candidates=None, error=None)
    # No assertion on the DB -- the point is that the call above did not raise.


def test_record_stores_error_rows(tmp_path):
    log = usage_log.UsageLog(tmp_path / "mcp_usage.db")
    log.record(source="mcp", tool="get_span", query=None, k=None, filters=None,
               latency_ms=2.0, result_count=None, candidates=None, error="PermanentError")

    conn = sqlite3.connect(tmp_path / "mcp_usage.db")
    assert conn.execute("SELECT error FROM requests").fetchone()[0] == "PermanentError"
    conn.close()


def test_read_usage_summary_reports_shares_and_percentiles(tmp_path):
    log = usage_log.UsageLog(tmp_path / "mcp_usage.db")
    for i in range(10):
        log.record(source="mcp", tool="semantic_search", query="q", k=10,
                   filters=SearchFilters(doc_type="book") if i < 4 else None,
                   latency_ms=float(i), result_count=5, candidates=25, error=None)

    out = usage_log.read_usage_summary(tmp_path / "mcp_usage.db")
    assert out["available"] is True
    assert out["by_tool"]["semantic_search"]["count"] == 10
    assert out["doc_type_share"] == 0.4
    assert out["paper_id_share"] == 0.0
    assert out["by_tool"]["semantic_search"]["p50_latency_ms"] == 4.0


def test_read_usage_summary_reports_unavailable_when_db_missing(tmp_path):
    """available: false, not a wall of zeros -- absent and zero are different facts."""
    out = usage_log.read_usage_summary(tmp_path / "no_such.db")
    assert out["available"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/test_usage_log.py -v
rc=$?
```

Expected: FAIL — `app/usage_log.py` does not exist.

- [ ] **Step 3: Implement `app/usage_log.py`**

Schema, verbatim:

```sql
CREATE TABLE IF NOT EXISTS requests (
  id            INTEGER PRIMARY KEY,
  ts            TEXT    NOT NULL,
  source        TEXT    NOT NULL,
  tool          TEXT    NOT NULL,
  query         TEXT,
  k             INTEGER,
  filters_json  TEXT,
  doc_type      TEXT,
  paper_id      TEXT,
  latency_ms    REAL    NOT NULL,
  result_count  INTEGER,
  candidates    INTEGER,
  error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_ts   ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_tool ON requests(tool);
```

Requirements the tests above pin:

- `PRAGMA journal_mode=WAL` — the MCP server process and the dashboard process both write.
- Schema created on first use (`CREATE TABLE IF NOT EXISTS`), not by a migration. This DB is **not** `papers.db` and must never acquire a `migrations/` entry.
- `ts` is ISO-8601 UTC (`datetime.now(UTC).isoformat()`).
- `filters` is a `SearchFilters | None`; serialize with `filters.model_dump_json()` when present, and pull `doc_type`/`paper_id` off the model for their own columns.
- **`record()` must never raise.** Wrap the whole body in `try/except Exception`, log once at WARNING, and suppress thereafter (a per-instance `self._warned` flag) so a broken telemetry path cannot flood the log or fail a query.
- `record()` opens, writes, and closes its own connection. Do not hold a long-lived connection on an object shared across `ThreadingHTTPServer` threads — `sqlite3` connections are not thread-safe by default, and this is a once-per-request write, not a hot loop.
- `read_usage_summary` returns `{"available": False}` alone when the file is missing or unreadable. When available: `by_tool` (per tool: `count`, `p50_latency_ms`, `p95_latency_ms`, `error_count`, `mean_result_count`, `mean_candidates`), `doc_type_share`, `paper_id_share`, `total`, `total_24h`, `top_error`.
- Percentiles: use `statistics.quantiles` or an explicit sorted-index formula, and make the test's expectation match your choice exactly. With 10 samples `0.0..9.0`, the plan's test expects `p50 == 4.0` — the lower-median convention (`sorted[len//2 - 1]` for even n) or `sorted[int(0.5 * (n-1))]`. Pick one, and if your implementation yields a different value for that input, fix the **test's expected number** to match a defensible convention rather than contorting the implementation.

- [ ] **Step 4: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/test_usage_log.py -v
rc=$?
```

Expected: PASS, `rc=0`.

- [ ] **Step 5: Commit**

```bash
git add app/usage_log.py app/test_usage_log.py
git commit -m "Add app/usage_log.py: dedicated MCP request telemetry store

Separate <data_dir>/mcp_usage.db, WAL, schema created on first use -- not a
table in papers.db, which would need a migration and foundation sign-off.
doc_type and paper_id are denormalized out of filters_json because 'are callers
using book scoping?' is the query that steers the next enhancement. record()
never raises: a telemetry failure must not fail a retrieval."
```

---

### Task 2: Instrument `app/serve.py`

**Files:**
- Modify: `app/serve.py:86-124`
- Test: `app/test_serve.py`

**Interfaces:**
- Consumes: `UsageLog.record(...)` from Task 1.
- Produces: a `record_usage` decorator in `app/usage_log.py`.

**Critical constraint — `functools.wraps` is load-bearing.** FastMCP builds each tool's JSON schema by introspecting the decorated function's signature and type annotations. A decorator that loses them silently produces a broken or empty tool schema that no test in this repo currently catches. Use `functools.wraps`, and assert the preserved signature in a test.

- [ ] **Step 1: Write the failing tests**

```python
def test_record_usage_preserves_signature_and_annotations():
    """FastMCP derives each tool's schema from the wrapped function's signature. Losing it
    produces a silently broken MCP tool schema that nothing else here would catch."""
    import inspect

    @usage_log.record_usage(lambda: None, source="mcp", tool="semantic_search")
    def semantic_search(query: str, filters: SearchFilters | None = None,
                        k: int | None = None) -> SearchResponse: ...

    sig = inspect.signature(semantic_search)
    assert list(sig.parameters) == ["query", "filters", "k"]
    assert sig.return_annotation is SearchResponse
    assert semantic_search.__name__ == "semantic_search"


def test_record_usage_records_success_with_coverage(tmp_path):
    log = usage_log.UsageLog(tmp_path / "u.db")
    fake_response = SearchResponse(results=[], coverage=Coverage(returned=3, candidates=17))

    @usage_log.record_usage(lambda: log, source="mcp", tool="semantic_search")
    def semantic_search(query, filters=None, k=None):
        return fake_response

    semantic_search("q", None, 10)

    conn = sqlite3.connect(tmp_path / "u.db")
    row = conn.execute("SELECT tool, result_count, candidates, error FROM requests").fetchone()
    conn.close()
    assert row == ("semantic_search", 3, 17, None)


def test_record_usage_records_the_error_then_reraises(tmp_path):
    log = usage_log.UsageLog(tmp_path / "u.db")

    @usage_log.record_usage(lambda: log, source="mcp", tool="get_paper")
    def get_paper(paper_id):
        raise PermanentError("nope")

    with pytest.raises(PermanentError):
        get_paper("x")

    conn = sqlite3.connect(tmp_path / "u.db")
    assert conn.execute("SELECT error FROM requests").fetchone()[0] == "PermanentError"
    conn.close()
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/test_usage_log.py -k record_usage -v
rc=$?
```

Expected: FAIL — `record_usage` does not exist.

- [ ] **Step 3: Implement the decorator**

In `app/usage_log.py`. The log is supplied by a zero-arg callable, not an instance, so `app/serve.py` can construct the store lazily at first use rather than at import time — matching `_LazyMcpServer`'s reasoning in the dashboard.

```python
def record_usage(get_log, *, source: str, tool: str):
    """Times the wrapped call and records one row per invocation, success or failure.

    `functools.wraps` is load-bearing, not cosmetic: FastMCP builds each tool's JSON schema by
    introspecting the wrapped function's signature and annotations. Losing them yields a silently
    broken tool schema.

    Errors are recorded and then RE-RAISED -- this decorator observes, it never swallows. Only the
    recording itself is best-effort (`UsageLog.record` never raises)."""
```

Extract `result_count`/`candidates` from a returned object's `.coverage.returned` / `.coverage.candidates` when present, and leave both `None` otherwise (`get_paper`/`get_span` return no `Coverage`). Use `getattr` chains — do not import `contracts.mcp_server` types just to isinstance-check them.

- [ ] **Step 4: Apply it in `app/serve.py`**

Add a lazily-constructed module-level log beside the existing `_server`:

```python
_usage_log_path = _data_dir_for_config() / "mcp_usage.db"
```

Derive the path from the same resolved config `app/serve.py` already loads — the directory holding `db_path`, i.e. `Path(_cfg.db_path).parent`. Do **not** invent a new CLI flag and do **not** read an environment variable (CONVENTIONS §3 reserves process-environment reads for `rag/config.py`).

Decorate all four tools, order mattering: `@mcp.tool()` outermost, `@record_usage(...)` inside it, so FastMCP registers the wrapped function.

```python
@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="semantic_search")
def semantic_search(...):
```

Keep every existing docstring exactly as-is — they are the tool descriptions the MCP client shows.

- [ ] **Step 5: Verify the tool schemas still register**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -c "
import app.serve as s, asyncio, inspect
for name in ('semantic_search','search_papers','get_paper','get_span'):
    fn = getattr(s, name)
    print(name, list(inspect.signature(fn).parameters), fn.__doc__ is not None)
"
rc=$?
```

Expected: each tool prints its real parameter list and `True` for the docstring. If any parameter list is empty or a docstring is `None`, `functools.wraps` was not applied correctly — fix it before proceeding.

- [ ] **Step 6: Run the suite and commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest -q
rc=$?
```

Expected: `rc=0`.

```bash
git add app/serve.py app/usage_log.py app/test_usage_log.py app/test_serve.py
git commit -m "Record MCP tool usage from app/serve.py

record_usage times each tool call and writes one row per invocation, success or
failure, then re-raises -- it observes, never swallows. functools.wraps is
load-bearing: FastMCP builds each tool's JSON schema from the wrapped function's
signature and annotations. Instrumented at the composition root so
rag/mcp_server.py and contracts/ stay untouched."
```

---

### Task 3: Dashboard `usage` block

**Files:**
- Modify: `app/dashboard/server.py` (`_status_dict`, and the `/api/search` route to record with `source="dashboard"`)
- Modify: `app/dashboard/static/index.html`
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `usage_log.read_usage_summary(db_path) -> dict` and `usage_log.UsageLog` from Tasks 1–2.

- [ ] **Step 1: Write the failing test**

```python
def test_status_route_includes_usage_block(running_server):
    body = _get_status(running_server)
    assert "usage" in body
    assert "available" in body["usage"]
```

Use whatever status-GET helper `test_server.py` already defines rather than the illustrative `_get_status` name.

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_server.py -k usage_block -v
rc=$?
```

Expected: FAIL, `KeyError: 'usage'`.

- [ ] **Step 3: Add the block and record dashboard searches**

In `_status_dict`:

```python
        "usage": usage_log.read_usage_summary(data_dir / "mcp_usage.db"),
```

In the `/api/search` handler, record with `source="dashboard"` so the usage picture has no hole in it. The route already has a `try/except (TransientError, PermanentError, ContractError)` around `mcp_server.semantic_search` — record inside both the success and the failure paths, and do not change the existing error-response behavior.

- [ ] **Step 4: Frontend**

Add a "Usage" panel to `app/dashboard/static/index.html`, matching the existing panels' structure and styling: calls per tool, p50/p95 latency, `doc_type_share` and `paper_id_share` as percentages, and error count. When `usage.available` is false, render "no usage recorded yet" — **not** a wall of zeros.

- [ ] **Step 5: Full suite, enforcement, PR**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest -q
rc=$?
```

Then enforcement using the synthesized-event form in Global Constraints. Then commit, push, and open the PR. **Do not merge.** Poll `gh pr checks <n>` until every check has a final conclusion and report each by name — both must be `pass`.

---

## Report contract

Write your full report to the report file path given in your dispatch. Return only: status, commit SHAs, PR number, real `rc` values for pytest and enforcement, the Task 2 Step 5 tool-schema output, and the final CI conclusion for every check by name.
