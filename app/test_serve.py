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
def serve_module(monkeypatch):
    fake_server = _FakeMcpServer()
    monkeypatch.setattr(
        rag.config, "load_config", lambda *a, **k: Config(focus_area_queries=["x"])
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


# --- CONVENTIONS.md §3 conformance ("No module calls os.getenv... outside" rag/config.py) --------
# Sibling composition roots app/ingest.py and app/parse_phase.py pass `cfg.db_path`/`cfg.blob_dir`/
# `cfg.collection` (T-DOC29) instead of reading RAG_DB_PATH/RAG_BLOB_DIR/RAG_COLLECTION from the
# process environment. app/serve.py (built later, T-DOC33) was missed by that migration -- it still
# reads `os.environ.get(...)` directly at import time for all three. Pinned below as a red/xfail
# test recording the CORRECT canonical behavior; not fixed here -- app/mcp_verify_client.py's
# docstring and app/run_prefetch_loop.sh's comments still describe the env-var path as current
# usage, so the real fix needs to touch more than app/serve.py alone (see the audit report's
# follow-up-PR recommendation).


@pytest.mark.xfail(
    strict=True,
    reason="app/serve.py reads RAG_DB_PATH/RAG_BLOB_DIR/RAG_COLLECTION via os.environ.get(...) "
    "instead of the loaded Config's own db_path/blob_dir/collection fields -- CONVENTIONS.md §3 "
    "violation, see audit finding (app/serve.py missed by the T-DOC29 env-read migration).",
)
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

    # Correct canonical behavior: the loaded Config's own fields win, never an os.environ override
    # app/serve.py invents on its own (no other composition root has one).
    assert captured["kwargs"].get("db_path") == "cfg.db"
    assert captured["kwargs"].get("blob_dir") == "cfg-blobs"
    assert captured["kwargs"].get("collection") == "cfg-col"
