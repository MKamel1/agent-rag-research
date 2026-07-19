"""`python -m app.serve` — the real McpServer composition root, wrapped in a real MCP stdio
transport (T-DOC33) so an actual MCP client can connect and call `search_papers`/
`semantic_search`/`get_paper`/`get_span` over the wire — not just a same-process Python caller,
which is all `rag/test_composition_e2e.py` proves.

`RAG_DB_PATH`/`RAG_BLOB_DIR`/`RAG_COLLECTION`: same optional overrides `app/ingest.py`/
`app/parse_phase.py` already read for the ingest-side composition root — unset falls back to
`build_mcp_server`'s own defaults (`"papers.db"`/`"blobs"`/`"papers"`, resolved relative to cwd).

# ponytail: stdio transport only (`mcp.run()`'s default) — the standard local-process transport
# both Claude Code and Claude Desktop speak, and this is a single-operator local tool, not a
# multi-client service. FastMCP supports `transport="streamable-http"` with no change to the
# tool functions below if a remote/multi-client caller ever needs one.
"""

import os

from mcp.server.fastmcp import FastMCP

from app.assembly import build_mcp_server
from contracts.mcp_server import PaperSearchResponse, PaperSummaryView, SearchResponse
from contracts.provenance import Anchor
from contracts.vector_index import SearchFilters
from rag.config import load_config

_cfg = load_config()
_server = build_mcp_server(
    _cfg,
    db_path=os.environ.get("RAG_DB_PATH"),
    blob_dir=os.environ.get("RAG_BLOB_DIR"),
    collection=os.environ.get("RAG_COLLECTION", "papers"),
)
mcp = FastMCP("research-system-rag")


@mcp.tool()
def semantic_search(
    query: str, filters: SearchFilters | None = None, k: int | None = None
) -> SearchResponse:
    """Passage-level search over the ingested corpus. Returns cited, grounded passages
    (`GroundedResult`s) plus a `Coverage` note — never bare text. `k` left unset uses the
    server's configured default (`Config.top_k`, `_cfg` above); pass it explicitly to override.

    Note: `k` is accepted up to 100, but at most 32 results are ever returned (a TEI reranker
    vendor batch-size limit) — `Coverage.returned <= 32` with a larger `Coverage.candidates` means
    this ceiling, not a sparse corpus."""
    return _server.semantic_search(query, filters, k)


@mcp.tool()
def search_papers(
    query: str, filters: SearchFilters | None = None, k: int | None = None
) -> PaperSearchResponse:
    """Whole-paper/summary-level search over the ingested corpus. `k` left unset uses the
    server's configured default (`Config.top_k`); pass it explicitly to override.

    Note: same 32-result ceiling as `semantic_search` — see its docstring."""
    return _server.search_papers(query, filters, k)


@mcp.tool()
def get_paper(paper_id: str) -> PaperSummaryView:
    """Fetch a stored paper's summary view by id."""
    return _server.get_paper(paper_id)


@mcp.tool()
def get_span(anchor: Anchor) -> str:
    """Resolve an `Anchor` (from a prior search result's `.anchor`) back to the full verbatim
    text of the source block it points at — the citation-verification round trip."""
    return _server.get_span(anchor)


if __name__ == "__main__":
    mcp.run()
