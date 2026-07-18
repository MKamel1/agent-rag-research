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
