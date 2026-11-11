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


# --- MC-3: scan/get tools log their arguments; errors log the message ------------------------


def _tool_rows(tmp_path, calls):
    """Run each `(tool_name, fn, kwargs)` through `record_usage` and return its rows."""
    log = usage_log.UsageLog(tmp_path / "mcp_usage.db")
    for tool, fn, kwargs in calls:
        try:
            usage_log.record_usage(lambda: log, source="mcp", tool=tool)(fn)(**kwargs)
        except ValueError:
            pass
    conn = sqlite3.connect(tmp_path / "mcp_usage.db")
    rows = conn.execute(
        "SELECT tool, query, paper_id, error, error_message FROM requests ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def test_scan_and_get_tools_record_their_arguments_and_errors(tmp_path):
    from contracts.provenance import Anchor

    def scan_corpus(pattern, paper_id=None, author_org=None): return None
    def scan_methods(method, paper_id=None): return None
    def get_section(paper_id, section_path): return []
    def get_figures(paper_id, kind="all"): return []
    def get_span(anchor): return "text"
    def get_paper(paper_id): raise ValueError("unknown paper_id 'x' [serving collection=c]")

    anchor = Anchor(paper_id="p1", block_id="p1:b3", page=0, bbox=(0.0, 0.0, 1.0, 1.0),
                    snippet="s", section_path="")
    rows = _tool_rows(tmp_path, [
        ("scan_corpus", scan_corpus, {"pattern": "bootstrap|resampl", "paper_id": "p9"}),
        ("scan_corpus", scan_corpus, {"pattern": "x" * 900}),
        ("scan_methods", scan_methods, {"method": "RRF"}),
        ("get_section", get_section, {"paper_id": "p1", "section_path": "3. Method"}),
        ("get_figures", get_figures, {"paper_id": "p2"}),
        ("get_span", get_span, {"anchor": anchor}),
        ("get_paper", get_paper, {"paper_id": "x"}),
    ])
    assert rows[0] == ("scan_corpus", "bootstrap|resampl", "p9", None, None)
    assert len(rows[1][1]) == 500  # long patterns are capped
    assert rows[2][:3] == ("scan_methods", "RRF", None)
    assert rows[3][:3] == ("get_section", "3. Method", "p1")
    assert rows[4][:3] == ("get_figures", None, "p2")
    assert rows[5][:3] == ("get_span", "p1:b3", "p1")
    assert rows[6] == (
        "get_paper", None, "x", "ValueError", "unknown paper_id 'x' [serving collection=c]")


def test_error_message_is_truncated_to_200_chars(tmp_path):
    def get_paper(paper_id): raise ValueError("e" * 1000)
    assert len(_tool_rows(tmp_path, [("get_paper", get_paper, {"paper_id": "x"})])[0][4]) == 200


def test_a_log_created_by_the_old_schema_is_upgraded_in_place_and_old_rows_stay_readable(tmp_path):
    db = tmp_path / "mcp_usage.db"
    conn = sqlite3.connect(db)
    conn.executescript(  # the pre-MC-3 schema, verbatim, plus one old row
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, source TEXT NOT NULL, "
        "tool TEXT NOT NULL, query TEXT, k INTEGER, filters_json TEXT, doc_type TEXT, "
        "paper_id TEXT, "
        "latency_ms REAL NOT NULL, result_count INTEGER, candidates INTEGER, error TEXT);"
        "INSERT INTO requests (ts, source, tool, latency_ms, error) "
        "VALUES ('2026-08-01T00:00:00+00:00', 'mcp', 'get_paper', 1.0, 'ContractError');"
    )
    conn.commit()
    conn.close()

    log = usage_log.UsageLog(db)
    for _ in range(2):  # second write proves the migration is idempotent
        log.record(source="mcp", tool="get_paper", query=None, k=None, filters=None, latency_ms=2.0,
                   result_count=None, candidates=None, error="ContractError",
                   error_message="unknown paper_id", paper_id="p")

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT error, error_message, paper_id FROM requests ORDER BY id").fetchall()
    conn.close()
    new = ("ContractError", "unknown paper_id", "p")
    assert rows == [("ContractError", None, None), new, new]
    assert usage_log.read_usage_summary(db)["total"] == 3  # the dashboard's read side still works
