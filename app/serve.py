"""`python -m app.serve` — the real McpServer composition root, wrapped in a real MCP stdio
transport (T-DOC33) so an actual MCP client can connect and call `search_papers`/
`semantic_search`/`get_paper`/`get_span` over the wire — not just a same-process Python caller,
which is all `rag/test_composition_e2e.py` proves.

`--data-dir DIR`: loads `DIR/config.yaml` and resolves `db_path`/`blob_dir` absolute against `DIR`
(argparse, not an env var -- CONVENTIONS.md §3 reserves process-environment reads for
`rag/config.py` alone; this composition root used to violate that with `RAG_DB_PATH`/
`RAG_BLOB_DIR`/`RAG_COLLECTION` env-var reads, an audit finding fixed here). Omit `--data-dir` to
fall back to plain `load_config()` (config.yaml resolved relative to cwd) -- the same default
`app/ingest.py` uses. `collection` always comes from the loaded Config, never a separate override.

`--data-dir` also fails loudly (clear stderr message, nonzero exit) if the resolved `db_path` file
doesn't exist, rather than silently opening/creating an empty database at the wrong path -- the
exact "confident fake empty result" failure mode `app/assembly.py::_resolve_store_paths`'s
docstring already warns about elsewhere in this codebase.
# ponytail: the plain (no `--data-dir`) fallback path does NOT get this existence check --
# unchanged from before this fix, and it's also what `app/test_serve.py`'s fakes exercise. Add the
# same check there too if a bare `python -m app.serve` (no flag, wrong cwd) against a missing
# corpus ever turns out to be a real incident, not just a-data-dir-typo one.

# ponytail: stdio transport only (`mcp.run()`'s default) — the standard local-process transport
# both Claude Code and Claude Desktop speak, and this is a single-operator local tool, not a
# multi-client service. FastMCP supports `transport="streamable-http"` with no change to the
# tool functions below if a remote/multi-client caller ever needs one.
"""

import argparse
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.assembly import build_mcp_server
from contracts.mcp_server import PaperSearchResponse, PaperSummaryView, SearchResponse
from contracts.provenance import Anchor
from contracts.vector_index import SearchFilters
from rag.config import load_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", default=None,
        help="Directory holding this corpus's config.yaml. db_path/blob_dir resolve absolute "
             "against it; collection comes from that config.yaml. Omit to use plain load_config() "
             "(config.yaml resolved relative to cwd), same default app/ingest.py uses.",
    )
    # parse_known_args: this module also loads under pytest (app/test_serve.py reloads it
    # in-process), whose own argv (test paths, -q, ...) isn't --data-dir's to reject.
    args, _unknown = parser.parse_known_args()
    return args


_args = _parse_args()
if _args.data_dir is not None:
    _data_dir = Path(_args.data_dir)
    _cfg = load_config(_data_dir / "config.yaml")
    _db_path = str((_data_dir / _cfg.db_path).resolve())
    _blob_dir = str((_data_dir / _cfg.blob_dir).resolve())
    if not Path(_db_path).exists():
        sys.exit(
            f"app.serve: --data-dir={_args.data_dir!r} resolves db_path to {_db_path!r}, which "
            "does not exist -- refusing to start against a missing/wrong corpus (opening a "
            "nonexistent sqlite path would silently create an empty one and return confident "
            "fake-empty results instead of a real error). Check --data-dir points at the corpus's "
            "actual directory."
        )
else:
    _cfg = load_config()
    _db_path = _cfg.db_path
    _blob_dir = _cfg.blob_dir

_server = build_mcp_server(_cfg, db_path=_db_path, blob_dir=_blob_dir, collection=_cfg.collection)
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
