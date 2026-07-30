"""Unit tests for `app/usage_log.py` -- the dedicated MCP/dashboard request telemetry store
(`UsageLog`, `record_usage`, `read_usage_summary`). See that module's docstring for the
never-raises contract and the doc_type/paper_id denormalization rationale.
"""

import inspect
import sqlite3

import pytest

from app import usage_log
from contracts.errors import PermanentError
from contracts.mcp_server import Coverage, SearchResponse
from contracts.vector_index import SearchFilters


# --- Task 1: UsageLog + read_usage_summary -------------------------------------------------


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


# --- Task 2: record_usage decorator ---------------------------------------------------------


def test_record_usage_preserves_signature_and_annotations():
    """FastMCP derives each tool's schema from the wrapped function's signature. Losing it
    produces a silently broken MCP tool schema that nothing else here would catch."""

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
