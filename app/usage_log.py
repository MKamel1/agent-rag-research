"""`app/usage_log.py` -- dedicated MCP/dashboard request telemetry store (Deliverable 2 of
`docs/superpowers/specs/2026-07-30-dashboard-dropin-and-usage-design.md` §3).

Records every retrieval request (`semantic_search`/`search_papers`/`get_paper`/`get_span`, from
both the MCP server and the dashboard's `/api/search`) into a **separate** SQLite database,
`<data_dir>/mcp_usage.db` -- never a table in `papers.db`, which would need a `migrations/` entry
and foundation sign-off. Schema is created on first use (`CREATE TABLE IF NOT EXISTS`), not by a
migration.

`doc_type`/`paper_id` are denormalized out of `filters_json` into their own columns because "are
callers actually using book scoping?" is the query meant to steer the next retrieval enhancement --
it must not require JSON extraction over the whole table to answer.

Two pieces:

- `UsageLog.record()` -- one row per request. Opens, writes, and closes its own connection (no
  long-lived connection shared across `ThreadingHTTPServer` threads -- `sqlite3` connections are
  not thread-safe by default, and this is a once-per-request write, not a hot loop). **Never
  raises** -- a telemetry failure must not fail a retrieval, same posture as
  `app/telemetry.py::_query_gpu`. Logs once at WARNING, then suppresses (a `self._warned` flag) so
  a broken telemetry path can't flood the log.
- `record_usage` -- a decorator for `app/serve.py`'s four `@mcp.tool()` functions (and, in a
  follow-on change, the dashboard's `/api/search` route). Times the call, records success or
  failure, then re-raises -- it observes, it never swallows. `functools.wraps` is load-bearing,
  not cosmetic: FastMCP builds each tool's JSON schema by introspecting the wrapped function's
  signature and annotations; losing them yields a silently broken tool schema that nothing else in
  this repo currently catches.

`read_usage_summary()` is the dashboard's read side (Task 3, a separate PR): `{"available":
False}` alone when the file is missing or unreadable -- absent and zero are different facts, so
this never returns a wall of zeros pretending to be real data.
"""

from __future__ import annotations

import functools
import inspect
import logging
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

from contracts.vector_index import SearchFilters

logger = logging.getLogger(__name__)

_SCHEMA = """
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
"""

_INSERT = """
INSERT INTO requests
    (ts, source, tool, query, k, filters_json, doc_type, paper_id,
     latency_ms, result_count, candidates, error)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class UsageLog:
    """One `record()` call per request, written to `db_path` (a dedicated SQLite database, WAL
    mode -- the MCP server process and the dashboard process both write). See module docstring
    for the never-raises contract.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._warned = False

    def record(
        self,
        *,
        source: str,
        tool: str,
        query: str | None,
        k: int | None,
        filters: SearchFilters | None,
        latency_ms: float,
        result_count: int | None,
        candidates: int | None,
        error: str | None,
    ) -> None:
        try:
            filters_json = filters.model_dump_json() if filters is not None else None
            doc_type = filters.doc_type if filters is not None else None
            paper_id = filters.paper_id if filters is not None else None
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                conn.execute(
                    _INSERT,
                    (
                        datetime.now(UTC).isoformat(), source, tool, query, k, filters_json,
                        doc_type, paper_id, latency_ms, result_count, candidates, error,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001 -- telemetry must never fail the caller's request
            if not self._warned:
                logger.warning(
                    "usage_log: failed to record a usage row for %s.%s, suppressing further "
                    "warnings for this instance: %s", source, tool, e,
                )
                self._warned = True


def record_usage(get_log: Callable[[], UsageLog], *, source: str, tool: str):
    """Times the wrapped call and records one row per invocation, success or failure.

    `functools.wraps` is load-bearing, not cosmetic: FastMCP builds each tool's JSON schema by
    introspecting the wrapped function's signature and annotations. Losing them yields a silently
    broken tool schema.

    Errors are recorded and then RE-RAISED -- this decorator observes, it never swallows. Only the
    recording itself is best-effort (`UsageLog.record` never raises).

    `get_log` is a zero-arg callable rather than a `UsageLog` instance so the caller (`app/
    serve.py`) can construct the store lazily at first use instead of at import time, matching
    `app/dashboard/server.py`'s `_LazyMcpServer` reasoning for its own real-infra collaborator.

    `query`/`filters`/`k` are pulled off the wrapped function's own signature via
    `inspect.signature(...).bind` -- not fixed positional slots -- so this same decorator works
    for `semantic_search(query, filters, k)` and for `get_paper(paper_id)`/`get_span(anchor)`
    alike (both simply have no `query`/`filters`/`k` to find, so those columns are `None`).
    """

    def decorator(fn):
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            sig = None

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result: Any = None
            error_name: str | None = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                error_name = type(e).__name__
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000.0
                bound: dict[str, Any] = {}
                if sig is not None:
                    try:
                        bound = sig.bind(*args, **kwargs).arguments
                    except TypeError:
                        bound = {}
                coverage = getattr(result, "coverage", None)
                get_log().record(
                    source=source,
                    tool=tool,
                    query=bound.get("query"),
                    k=bound.get("k"),
                    filters=bound.get("filters"),
                    latency_ms=latency_ms,
                    result_count=getattr(coverage, "returned", None),
                    candidates=getattr(coverage, "candidates", None),
                    error=error_name,
                )

        return wrapper

    return decorator


def _percentile(sorted_values: list[float], p: float) -> float:
    """Lower-index percentile over an already-sorted list: `sorted[int(p/100 * (n-1))]`. With 10
    samples `0.0..9.0`, p50 lands on index 4 -> `4.0` (the lower-median convention for even n)."""
    if not sorted_values:
        return 0.0
    idx = int(p / 100.0 * (len(sorted_values) - 1))
    return sorted_values[idx]


def read_usage_summary(db_path: str | Path) -> dict[str, Any]:
    """The dashboard's read side. `{"available": False}` alone when the file is missing or
    unreadable -- absent and zero are different facts, so this never renders a wall of zeros in
    place of "no usage recorded yet".
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {"available": False}

    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT tool, latency_ms, result_count, candidates, error, doc_type, paper_id, ts "
                "FROM requests"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("usage_log: failed to read usage summary from %s: %s", db_path, e)
        return {"available": False}

    total = len(rows)
    if total == 0:
        return {
            "available": True,
            "total": 0,
            "total_24h": 0,
            "by_tool": {},
            "doc_type_share": 0.0,
            "paper_id_share": 0.0,
            "top_error": None,
        }

    by_tool_rows: dict[str, list[tuple]] = {}
    for row in rows:
        by_tool_rows.setdefault(row[0], []).append(row)

    by_tool: dict[str, dict[str, Any]] = {}
    for tool, tool_rows in by_tool_rows.items():
        latencies = sorted(r[1] for r in tool_rows)
        result_counts = [r[2] for r in tool_rows if r[2] is not None]
        candidates_vals = [r[3] for r in tool_rows if r[3] is not None]
        by_tool[tool] = {
            "count": len(tool_rows),
            "p50_latency_ms": _percentile(latencies, 50),
            "p95_latency_ms": _percentile(latencies, 95),
            "error_count": sum(1 for r in tool_rows if r[4] is not None),
            "mean_result_count": fmean(result_counts) if result_counts else None,
            "mean_candidates": fmean(candidates_vals) if candidates_vals else None,
        }

    doc_type_share = sum(1 for r in rows if r[5] is not None) / total
    paper_id_share = sum(1 for r in rows if r[6] is not None) / total

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    total_24h = 0
    for r in rows:
        try:
            ts = datetime.fromisoformat(r[7])
        except (TypeError, ValueError):
            continue
        if ts >= cutoff:
            total_24h += 1

    errors = [r[4] for r in rows if r[4] is not None]
    top_error = Counter(errors).most_common(1)[0][0] if errors else None

    return {
        "available": True,
        "total": total,
        "total_24h": total_24h,
        "by_tool": by_tool,
        "doc_type_share": doc_type_share,
        "paper_id_share": paper_id_share,
        "top_error": top_error,
    }
