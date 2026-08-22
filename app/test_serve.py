"""Unit tests for `app/serve.py` -- the thin FastMCP tool wrappers (`semantic_search`/
`search_papers`/`get_paper`/`get_span`) around `McpServer` (`_server`, built once at import time
via `app.assembly.build_mcp_server`).

HARD GUARDRAIL: `app.serve`'s own module-level code constructs a REAL `GpuLock`, a REAL
`VectorIndex` (a live vector-store connection at construction time), and REAL TEI HTTP clients --
it is a composition root, not an importable library. Merely `import app.serve` unpatched would
reach for that live infra. Both collaborators it reads at import time (`rag.config.load_config`,
`app.assembly.build_mcp_server`) are monkeypatched to fakes BEFORE `app.serve` is (re)imported, so
this stays fully offline -- see `serve_module` below. `importlib.reload` re-executes `app.serve`'s
top-level `from ... import ...` statements against the now-patched module attributes, which is
what makes the patch take effect even if some earlier test already imported the real module.
"""

from __future__ import annotations

import importlib
import inspect
import sqlite3
import sys

import pytest

import app.assembly
import rag.config
from contracts.config import Config
from contracts.mcp_server import Coverage, PaperSearchResponse, SearchResponse
from contracts.vector_index import SearchFilters


class _FakeMcpServer:
    """Records every call each tool wrapper makes -- proves `app/serve.py` forwards `query`/
    `filters`/`k` through unmodified, nothing more."""

    def __init__(self):
        self.semantic_search_calls: list[tuple] = []
        self.search_papers_calls: list[tuple] = []
        self.get_paper_calls: list[str] = []
        self.get_span_calls: list[object] = []

    def semantic_search(self, query, filters, k):
        self.semantic_search_calls.append((query, filters, k))
        return SearchResponse(results=[], coverage=Coverage(returned=0, candidates=0))

    def search_papers(self, query, filters, k):
        self.search_papers_calls.append((query, filters, k))
        return PaperSearchResponse(results=[], coverage=Coverage(returned=0, candidates=0))

    def get_paper(self, paper_id):
        self.get_paper_calls.append(paper_id)
        raise AssertionError("get_paper not exercised by these tests")

    def get_span(self, anchor):
        self.get_span_calls.append(anchor)
        return "verbatim source text"


@pytest.fixture
def serve_module(monkeypatch, tmp_path):
    fake_server = _FakeMcpServer()
    # db_path pinned under tmp_path (not the default relative "papers.db") so the usage-telemetry
    # wiring this fixture now also exercises (app/serve.py derives _usage_log_path from db_path's
    # own directory) writes mcp_usage.db into a throwaway tmp dir, never into the repo checkout.
    monkeypatch.setattr(
        rag.config, "load_config",
        lambda *a, **k: Config(focus_area_queries=["x"], db_path=str(tmp_path / "papers.db")),
    )
    monkeypatch.setattr(app.assembly, "build_mcp_server", lambda *a, **k: fake_server)

    if "app.serve" in sys.modules:
        serve_mod = importlib.reload(sys.modules["app.serve"])
    else:
        serve_mod = importlib.import_module("app.serve")

    yield serve_mod, fake_server


def test_semantic_search_forwards_query_filters_and_explicit_k(serve_module):
    serve_mod, fake_server = serve_module
    filters = SearchFilters(categories=["stat.ME"])

    serve_mod.semantic_search("estimator", filters, 5)

    assert fake_server.semantic_search_calls == [("estimator", filters, 5)]


def test_semantic_search_default_k_is_none_not_a_hardcoded_10(serve_module):
    # 2026-07-18: k's own default flows through as None (letting McpServer's `default_k`,
    # `Config.top_k`, apply) -- NOT a hardcoded 10 baked into this tool wrapper's own signature.
    serve_mod, fake_server = serve_module

    serve_mod.semantic_search("estimator", None)

    assert fake_server.semantic_search_calls == [("estimator", None, None)]


def test_search_papers_forwards_query_filters_and_explicit_k(serve_module):
    serve_mod, fake_server = serve_module
    filters = SearchFilters(published_after=None)

    serve_mod.search_papers("estimator", filters, 3)

    assert fake_server.search_papers_calls == [("estimator", filters, 3)]


def test_search_papers_default_k_is_none_not_a_hardcoded_10(serve_module):
    serve_mod, fake_server = serve_module

    serve_mod.search_papers("estimator", None)

    assert fake_server.search_papers_calls == [("estimator", None, None)]


def test_get_paper_delegates_to_the_server(serve_module):
    serve_mod, fake_server = serve_module

    with pytest.raises(AssertionError):
        serve_mod.get_paper("2506.01234")

    assert fake_server.get_paper_calls == ["2506.01234"]


def test_get_span_delegates_to_the_server(serve_module):
    serve_mod, fake_server = serve_module

    span = serve_mod.get_span("some-anchor")

    assert span == "verbatim source text"
    assert fake_server.get_span_calls == ["some-anchor"]


# --- Usage telemetry wiring (T-DOC-usage-telemetry Task 2) ---------------------------------------
# `@record_usage(...)` sits INSIDE `@mcp.tool()` on all four tools -- FastMCP registers the
# wrapped function, so its schema comes from whatever signature/annotations survive the
# decorator. `functools.wraps` (inside `app/usage_log.py::record_usage`) is what makes that
# survive; losing it would silently break every tool's JSON schema with nothing here to catch it,
# which is exactly what the first test below pins.


def test_tool_signatures_and_docstrings_preserved_after_usage_wiring(serve_module):
    serve_mod, _ = serve_module

    assert list(inspect.signature(serve_mod.semantic_search).parameters) == [
        "query", "filters", "k",
    ]
    assert list(inspect.signature(serve_mod.search_papers).parameters) == [
        "query", "filters", "k",
    ]
    assert list(inspect.signature(serve_mod.get_paper).parameters) == ["paper_id"]
    assert list(inspect.signature(serve_mod.get_span).parameters) == ["anchor"]
    for name in ("semantic_search", "search_papers", "get_paper", "get_span"):
        fn = getattr(serve_mod, name)
        assert fn.__name__ == name
        assert fn.__doc__


def test_served_search_docstrings_do_not_claim_the_removed_32_result_ceiling(serve_module):
    # RI-10: `search_papers`' served docstring pointed readers at "same 32-result ceiling as
    # `semantic_search`" three weeks after that ceiling was deleted (2026-08-19) -- and after
    # `semantic_search`'s own docstring had started saying so, making this file contradict
    # itself. An MCP client introspects tool docstrings to decide usage; a stale cap claim makes
    # it never ask for k > 32 while the server would honor it.
    serve_mod, _ = serve_module
    assert "32-result ceiling" not in serve_mod.search_papers.__doc__
    assert "ceiling is GONE" in serve_mod.semantic_search.__doc__  # the correct note survives


def test_served_search_docstrings_state_absence_honesty_and_the_rejected_floor(serve_module):
    # RI-10 part 2: the tool docstrings an MCP client actually sees over the wire must carry the
    # same absence-honesty statement as rag/mcp_server.py's own docstrings -- no relevance floor
    # exists, a full k-sized result set is not proof any result answers the query, and a floor
    # stays rejected pending RI-M7's score-distribution census.
    serve_mod, _ = serve_module
    assert "relevance floor" in serve_mod.semantic_search.__doc__
    assert "RI-M7" in serve_mod.semantic_search.__doc__
    assert "relevance floor" in serve_mod.search_papers.__doc__
    assert "RI-M7" in serve_mod.search_papers.__doc__


def test_semantic_search_records_a_usage_row(serve_module):
    serve_mod, _ = serve_module
    filters = SearchFilters(doc_type="book")

    serve_mod.semantic_search("estimator", filters, 5)

    conn = sqlite3.connect(serve_mod._usage_log_path)
    row = conn.execute(
        "SELECT source, tool, query, k, doc_type, error FROM requests"
    ).fetchone()
    conn.close()
    assert row == ("mcp", "semantic_search", "estimator", 5, "book", None)


def test_get_paper_error_is_recorded_then_reraised(serve_module):
    serve_mod, fake_server = serve_module

    with pytest.raises(AssertionError):
        serve_mod.get_paper("2506.01234")

    conn = sqlite3.connect(serve_mod._usage_log_path)
    row = conn.execute("SELECT tool, error FROM requests").fetchone()
    conn.close()
    assert row == ("get_paper", "AssertionError")


# --- CONVENTIONS.md §3 conformance (only rag/config.py may read the process environment) ---------
# Sibling composition roots app/ingest.py and app/parse_phase.py pass `cfg.db_path`/`cfg.blob_dir`/
# `cfg.collection` (T-DOC29) instead of reading RAG_DB_PATH/RAG_BLOB_DIR/RAG_COLLECTION from the
# process environment. app/serve.py (built later, T-DOC33) was missed by that migration -- fixed
# here: it now passes the loaded Config's own db_path/blob_dir/collection fields (optionally
# resolved against --data-dir, see the tests below), never a process-environment read.


def test_build_mcp_server_receives_config_values_not_os_environ(monkeypatch):
    captured: dict = {}

    def fake_build_mcp_server(config, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeMcpServer()

    monkeypatch.setattr(
        rag.config,
        "load_config",
        lambda *a, **k: Config(
            focus_area_queries=["x"], db_path="cfg.db", blob_dir="cfg-blobs", collection="cfg-col"
        ),
    )
    monkeypatch.setattr(app.assembly, "build_mcp_server", fake_build_mcp_server)
    monkeypatch.setenv("RAG_DB_PATH", "/env/should-not-win.db")
    monkeypatch.setenv("RAG_BLOB_DIR", "/env/should-not-win-blobs")
    monkeypatch.setenv("RAG_COLLECTION", "env-should-not-win")

    if "app.serve" in sys.modules:
        importlib.reload(sys.modules["app.serve"])
    else:
        importlib.import_module("app.serve")

    # Correct canonical behavior: the loaded Config's own fields win, never a process-environment
    # override app/serve.py invents on its own (no other composition root has one).
    assert captured["kwargs"].get("db_path") == "cfg.db"
    assert captured["kwargs"].get("blob_dir") == "cfg-blobs"
    assert captured["kwargs"].get("collection") == "cfg-col"


def test_module_level_logs_resolved_paths(monkeypatch, caplog):
    # T-DOC89 §4: the log line fires at module IMPORT time (this module has no main() to hook a
    # line into -- every real statement runs at the top level), so caplog's level must be set
    # BEFORE triggering the reload below, not after -- setting it inside a shared serve_module
    # fixture's body would be too late for THIS test (the fixture's own reload already ran).
    monkeypatch.setattr(
        rag.config,
        "load_config",
        lambda *a, **k: Config(
            focus_area_queries=["x"], db_path="/data/papers.db", blob_dir="/data/blobs",
            collection="papers",
        ),
    )
    monkeypatch.setattr(app.assembly, "build_mcp_server", lambda *a, **k: _FakeMcpServer())
    caplog.set_level("INFO")

    if "app.serve" in sys.modules:
        importlib.reload(sys.modules["app.serve"])
    else:
        importlib.import_module("app.serve")

    assert "db_path=/data/papers.db" in caplog.text
    assert "blob_dir=/data/blobs" in caplog.text
    assert "collection=papers" in caplog.text


def test_data_dir_resolves_db_path_and_blob_dir_under_it(tmp_path, monkeypatch):
    """`--data-dir DIR`: config.yaml is loaded from DIR, and db_path/blob_dir resolve absolute
    against DIR (not cwd) -- the deployment path the real MCP registration uses."""
    (tmp_path / "config.yaml").write_text(
        "focus_area_queries: ['x']\n"
        "db_path: papers.db\n"
        "blob_dir: blobs\n"
        "collection: real-collection\n"
    )
    (tmp_path / "papers.db").touch()  # exists -> the loud-fail check below must not trip

    captured: dict = {}

    def fake_build_mcp_server(config, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeMcpServer()

    monkeypatch.setattr(app.assembly, "build_mcp_server", fake_build_mcp_server)
    monkeypatch.setattr(sys, "argv", ["app.serve", "--data-dir", str(tmp_path)])

    if "app.serve" in sys.modules:
        importlib.reload(sys.modules["app.serve"])
    else:
        importlib.import_module("app.serve")

    assert captured["kwargs"]["db_path"] == str((tmp_path / "papers.db").resolve())
    assert captured["kwargs"]["blob_dir"] == str((tmp_path / "blobs").resolve())
    assert captured["kwargs"]["collection"] == "real-collection"


def test_data_dir_with_missing_db_fails_loudly(tmp_path, monkeypatch):
    """No papers.db under --data-dir -> a clear SystemExit, not a silently-created empty database
    (the "confident fake-empty results" failure mode this check exists to prevent)."""
    (tmp_path / "config.yaml").write_text("focus_area_queries: ['x']\n")
    # deliberately no papers.db written here

    monkeypatch.setattr(app.assembly, "build_mcp_server", lambda *a, **k: _FakeMcpServer())
    monkeypatch.setattr(sys, "argv", ["app.serve", "--data-dir", str(tmp_path)])

    with pytest.raises(SystemExit, match="does not exist"):
        if "app.serve" in sys.modules:
            importlib.reload(sys.modules["app.serve"])
        else:
            importlib.import_module("app.serve")
