# Dashboard drop-in control + MCP usage telemetry — design spec

**Date:** 2026-07-30
**Owner:** @MKamel1
**Status:** approved (owner, 2026-07-30)

## Objectives

Four deliverables, sequenced. Each lands as its own PR.

0. **Fix `GET /api/status`** — currently returns 500, leaving the dashboard blind
   ("run - unknown / stale / reconnecting"). Gates everything else.
1. **Drop-in as a first-class run type** — expose check + run in the dashboard, distinguish
   *dropped* from *processed*, and give drop-in runs priority over downloads.
2. **MCP usage telemetry** — record every retrieval request to a dedicated SQLite database so
   real usage can steer the next RAG enhancements.
3. **Test audit** — read-only inventory of stale tests, reported for approval before any rewrite.

## Non-goals (explicit)

- No change to `app/ingest_local.py`'s staging pipeline. It already works; this exposes it.
- No preemption of a running job. Priority is queue-jump only (see §2.3).
- No change to `contracts/` or `rag/mcp_server.py`. Both are foundation-protected or
  foundation-adjacent; the design deliberately routes around them.
- No writes to `papers.db` from any new code. Read-only via `status._ro_connect`.
- No test rewrites in deliverable 3 — audit and report only.

---

## 1. Deliverable 0 — `/api/status` regression fix

### The defect

`app/dashboard/server.py:163`:

```python
@lru_cache(maxsize=1)
def _static_config() -> Config:
    return load_config()
```

`_search_display()` (`server.py:176`) calls this on every `GET /api/status`. T-DOC89 (commit
`ce8bb1b`, 2026-07-28) changed `load_config()` discovery to `RAG_CONFIG` → `config.yaml` in cwd →
walk up. `scripts/dashboard.sh` `cd`s to the repo root, which has no deployed `config.yaml` — the
real one lives in the data dir. Every status poll raises:

```
contracts.errors.ContractError: no config.yaml found. Tried:
  - /home/omar/ai-projects/research-system-rag/config.yaml
```

The previously-running dashboard process started 2026-07-25, three days before the change, so the
regression was invisible until the process was restarted on 2026-07-30.

### The fix

`controller.py:474` already has the correct pattern. Mirror it:

```python
@lru_cache(maxsize=1)
def _static_config(data_dir: Path) -> Config:
    data_dir_config = data_dir / "config.yaml"
    if data_dir_config.exists():
        return load_config(data_dir_config)
    return load_config()
```

`data_dir` threads from the server's existing `--data-dir` argument through `_status_dict` into
`_search_display(data_dir)`. `lru_cache` keyed on `data_dir` preserves the existing
"read once per process" behavior.

### Test

`app/dashboard/test_server.py`: a `GET /api/status` served from a cwd containing **no**
`config.yaml`, with `--data-dir` pointing at a scratch dir that **does** have one. Asserts HTTP 200
and that `top_k_default` matches the data-dir config's value, not a default. This is the exact
shape that broke; without the cwd condition the test passes against the buggy code.

---

## 2. Deliverable 1 — Drop-in as a first-class run type

### 2.1 Existing state (do not rebuild)

`app/ingest_local.py` implements the pipeline: `scan_drop_dir`, `stage_file`, `mint_local_ref`,
`_quarantine`, `_write_manifest`, `_report_dry_run`. On-disk layout under `cfg.drop_in_dir`:

```
drop_in/
  papers/     books/          # inbox — user drops files here
  done/                       # staged into pdf_cache successfully
  failed/                     # quarantined, each with a sibling <name>.err
  excluded/                   # operator-excluded, never staged
  manifest-<UTC>.txt          # one paper_id per line, per staging run
```

### 2.2 Tracking — `status.read_drop_in` (ask 2)

New function in `app/dashboard/status.py`, following `read_downloads`/`read_downloader`:
pure read, tolerant of every directory being absent, never raises into the status handler.

```python
def read_drop_in(drop_dir: str | Path, db_path: str | Path) -> dict
```

Returns:

| key | meaning | source |
|---|---|---|
| `pending_papers` | files awaiting staging | count of `drop_in/papers/*.pdf` |
| `pending_books` | files awaiting staging | count of `drop_in/books/*.pdf` |
| `staged` | staged into `pdf_cache` | count of `drop_in/done/` |
| `failed` | quarantined | count of `drop_in/failed/*.pdf` |
| `failure_reasons` | `[(reason, count)]`, top 5 | parsed from `drop_in/failed/*.err` |
| `excluded` | operator-excluded | count of `drop_in/excluded/` |
| **`processed`** | **actually in the corpus** | manifest `paper_id`s joined against `papers.db` |
| `processed_books` / `processed_papers` | split by `doc_type` | same join |
| `latest_manifest` | filename + item count | newest `manifest-*.txt` |

**The `staged` vs `processed` distinction is the point of this deliverable.** `done/` only means the
PDF was copied into `pdf_cache` and a `paper_id` minted. It says nothing about whether the document
was parsed, chunked, summarized, embedded, or stored — or whether it was quarantined downstream.
`processed` is computed by reading every `manifest-*.txt`, collecting the `paper_id`s, and joining
them against `papers.db` for rows at stage `done`. A file can sit in `done/` for days while
`processed` stays 0; that gap is exactly what an operator needs to see.

The join uses `status._ro_connect` (already present, opens `file:...?mode=ro`). If the DB is
missing or unreadable, `processed` is `None`, not 0 — absent and zero are different facts, and
conflating them is the "confident fake empty result" failure mode `app/assembly.py` already warns
about.

Counts are `sum(1 for _ in dir.iterdir())` — never a materialized list. Any per-file detail
returned (`failure_reasons`, file names) is capped at **20 entries**, with a `truncated: true` flag
when more exist. A drop folder holding 10,000 files must not turn a status poll into a multi-second
stat storm or a megabyte JSON response.

### 2.3 Priority — queue-jump via `reconcile` (ask 3)

**Decided: queue-jump, no preemption.** A running `prefetch_pdfs`/`ingest` pass is never signalled
or killed, so there is no partial-write exposure against `papers.db`.

Rather than introduce a scheduler, this reuses the seam that already exists. `controller.reconcile()`
runs on every status poll and every control op, and already detects when a run has reached a
terminal state. The rule set:

| situation | behavior |
|---|---|
| drop-in requested, nothing running | spawn `app.ingest_local` immediately |
| drop-in requested, run in flight | set `pending_drop_in: true` in `run_manifest.json`, **do not spawn** |
| `reconcile()` observes the live run terminal **and** `pending_drop_in` set | spawn the drop-in run, clear the flag |
| `start()` called for a download/ingest run while `pending_drop_in` set | **refuse** (`DoubleRunError` sibling) |
| `stop()` called while `pending_drop_in` set | clear the flag — the operator's escape hatch (§7) |

The last row is load-bearing. Without it a download can be started the instant the previous one
ends, starving the drop-in run indefinitely — "priority" that never fires.

All transitions happen under the existing `_control_lock` (`.control.lock`), which already spans
the whole check-then-act for every control op. No new lock, no new lock ordering.

### 2.4 Control action — `controller.start_drop_in`

```python
def start_drop_in(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict
```

Spawns `python -m app.ingest_local` reusing `_spawn`/`_build_manifest`/`_control_lock`.
`run_manifest.json` already carries a `mode` field (currently always `"download"`); this adds
`"drop_in"`. The injectable `spawn` parameter matches `resume`/`retarget`, so tests never fork a
real process.

`pause`/`resume`/`stop` work unchanged on a drop-in run — they operate on the manifest's PID, and
`ingest_local` is signal-compatible with the existing handling.

### 2.5 HTTP surface

- `GET /api/status` gains a `drop_in` block: the whole of §2.2 plus `pending_drop_in`.
- `POST /api/control` gains `action: "start_drop_in"`.

**No separate "check"/"scan" action.** A check is a read; it belongs in `GET /api/status`, not
`POST /api/control`. The operator sees what is waiting without clicking anything.

### 2.6 Frontend

One panel in `app/dashboard/static/`: pending papers/books, staged, **processed**, failed (with top
reasons), and a "Run drop-in now" button. When `pending_drop_in` is set, the button shows queued
state and names the run being waited on.

---

## 3. Deliverable 2 — MCP usage telemetry

### 3.1 Store

Dedicated database at `<data_dir>/mcp_usage.db`. **Not** a table in `papers.db`: that would need a
migration and foundation-owner sign-off, and `papers.db` is write-protected in this workflow.
A separate file has neither constraint.

WAL mode — the MCP server process and the dashboard process both write.

```sql
CREATE TABLE IF NOT EXISTS requests (
  id            INTEGER PRIMARY KEY,
  ts            TEXT    NOT NULL,   -- ISO-8601 UTC
  source        TEXT    NOT NULL,   -- 'mcp' | 'dashboard'
  tool          TEXT    NOT NULL,   -- semantic_search|search_papers|get_paper|get_span
  query         TEXT,               -- NULL for get_paper/get_span
  k             INTEGER,
  filters_json  TEXT,               -- full SearchFilters as JSON, NULL if none
  doc_type      TEXT,               -- denormalized from filters
  paper_id      TEXT,               -- denormalized from filters
  latency_ms    REAL    NOT NULL,
  result_count  INTEGER,            -- Coverage.returned
  candidates    INTEGER,            -- Coverage.candidates
  error         TEXT                -- exception class name, NULL on success
);
CREATE INDEX IF NOT EXISTS idx_requests_ts   ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_tool ON requests(tool);
```

`doc_type` and `paper_id` are denormalized out of `filters_json` on purpose: "are callers actually
using book scoping?" is the query that steers the next enhancement, and it should not require JSON
extraction over the whole table.

### 3.2 Seam — the composition root, not `McpServer`

New module `app/usage_log.py`:

```python
class UsageLog:
    def __init__(self, db_path: Path) -> None: ...
    def record(self, *, source, tool, query, k, filters, latency_ms,
               result_count, candidates, error) -> None: ...
```

The four `@mcp.tool()` functions in `app/serve.py` time their call and record the outcome.
`rag/mcp_server.py` and `contracts/mcp_server.py` are **not modified** — no foundation review, and
the RAG modules gain no dependency on a telemetry store. `app/serve.py` is already the composition
root that owns process-level concerns, which is where cross-cutting instrumentation belongs.

The dashboard's own search endpoint records with `source="dashboard"`, so the usage picture has no
hole in it.

### 3.3 Failure posture

`record()` is best-effort and **must never raise into the request path**: a telemetry failure must
not fail a retrieval. Same posture as `app/telemetry.py::_query_gpu()`, which already swallows every
failure and returns `None`. Errors are logged once at WARNING, then suppressed.

Requests are recorded on both success and failure — an `error` row is more interesting than a
missing one.

### 3.4 Dashboard surface

`GET /api/status` gains a `usage` block, read-only against `mcp_usage.db`:

- calls per tool, last 24h and all-time
- share of requests passing `doc_type`, and share passing `paper_id`
- p50 / p95 `latency_ms` per tool
- error count and top error class
- mean `result_count` vs `candidates`

If `mcp_usage.db` does not exist yet, the block reports `available: false` rather than zeros — same
absent-vs-zero rule as §2.2.

---

## 4. Deliverable 3 — Test audit

**Read-only. No test is modified, deleted, or added in this deliverable.**

Output: `docs/TEST-AUDIT-2026-07-30.md`, a table of findings with file, line, and category:

| category | what it means |
|---|---|
| `asserts-nothing` | test runs code but makes no meaningful assertion |
| `superseded` | asserts behavior a later change intentionally replaced |
| `stale-constant` | pinned to a value the experiments moved (`_MAX_HITS_PER_PAPER`, IDF on/off, 40-vs-115 question set, cap 3 vs 50) |
| `dead` | tests a code path that no longer exists |
| `over-mocked` | fakes so much that a real regression could not fail it |

Each finding carries a proposed action and a one-line risk note. The owner approves the fix list
before any rewrite is dispatched. A test that looks redundant may be the only thing catching a real
regression; deleting it silently is the failure this checkpoint exists to prevent.

---

## 5. Testing strategy

Per `TEST-STRATEGY.md`: zero-GPU, zero-network, fakes over live services.

| unit | how it's tested |
|---|---|
| `_static_config` fix | `GET /api/status` from a cwd with no `config.yaml`, `--data-dir` with one |
| `read_drop_in` | `tmp_path` drop tree + scratch SQLite; covers all-dirs-absent, DB-absent (`processed is None`), and staged-but-not-processed |
| `start_drop_in` | injected `spawn`, never forks |
| queue-jump | injected `spawn` + a fake live PID: assert no spawn while running, spawn on reconcile-after-terminal, and refusal of a competing `start()` |
| `UsageLog` | `tmp_path` DB; assert schema, a recorded success row, a recorded error row, and that a write failure against an unwritable path does **not** raise |
| usage aggregation | seeded DB, assert percentiles and shares |

Existing suites (`test_server.py`, `test_controller.py`, `test_status.py`) are extended, not
replaced. All new tests run under `--disable-socket`.

## 6. Sequencing

Strictly sequential — deliverables 0, 1, and 2 all touch `app/dashboard/`, so parallel agents would
conflict.

```
0 (blocker fix)  →  1 (drop-in)  →  2 (usage telemetry)  →  3 (test audit)
```

Deliverable 3 runs last by design: it audits tests that 0–2 are actively changing.

## 7. Risks

- **`processed` join cost.** Reading every manifest and querying `papers.db` on each status poll
  could be slow once manifests accumulate. Mitigation: cache the manifest→`paper_id` set keyed on
  the newest manifest's mtime; re-read only when it changes.
- **Queue-jump starvation, inverted.** The §2.3 refusal rule blocks downloads while a drop-in is
  pending. If `ingest_local` wedges, downloads stay blocked. Mitigation: the flag is a plain field
  in `run_manifest.json` and `stop` clears it, so the operator has an escape hatch.
- **`mcp_usage.db` unbounded growth.** No rotation in V0. A row is ~200 bytes; at 1,000
  requests/day that is ~70 MB/year. Revisit if it becomes real, not before.
