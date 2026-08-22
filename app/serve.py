"""`python -m app.serve` — the real McpServer composition root, wrapped in a real MCP stdio
transport (T-DOC33) so an actual MCP client can connect and call `search_papers`/
`semantic_search`/`get_paper`/`get_span` over the wire — not just a same-process Python caller,
which is all `rag/test_composition_e2e.py` proves.

`--data-dir DIR`: loads `DIR/config.yaml` and resolves `db_path`/`blob_dir` absolute against `DIR`
(argparse, not an env var -- CONVENTIONS.md §3 reserves process-environment reads for
`rag/config.py` alone; this composition root used to violate that with `RAG_DB_PATH`/
`RAG_BLOB_DIR`/`RAG_COLLECTION` env-var reads, an audit finding fixed here). Omit `--data-dir` to
fall back to plain `load_config()` (T-DOC89 §3 discovery: `RAG_CONFIG` -> `config.yaml` in cwd ->
walk up) -- the same default `app/ingest.py` uses. `collection` always comes from the loaded
Config, never a separate override.

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
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.assembly import build_mcp_server
from app.usage_log import UsageLog, record_usage
from contracts.mcp_server import (
    PaperSearchResponse,
    PaperSummaryView,
    ScanResponse,
    SearchResponse,
)
from contracts.provenance import Anchor
from contracts.vector_index import SearchFilters
from rag.config import load_config

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", default=None,
        help="Directory holding this corpus's config.yaml. db_path/blob_dir resolve absolute "
             "against it; collection comes from that config.yaml. Omit to use plain load_config() "
             "(T-DOC89 §3 discovery), same default app/ingest.py uses.",
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

# T-DOC89 §4: report what was resolved, same pattern as app/delete_docs.py -- an operator (or an
# MCP client's launch cwd/--data-dir) pointed at the wrong place should see it here, not guess.
logging.basicConfig(level=logging.INFO)
logger.info(
    "serve: resolved db_path=%s blob_dir=%s collection=%s", _db_path, _blob_dir, _cfg.collection,
)

_server = build_mcp_server(_cfg, db_path=_db_path, blob_dir=_blob_dir, collection=_cfg.collection)
mcp = FastMCP("research-system-rag")

# Request telemetry (T-DOC-usage-telemetry): a dedicated <data_dir>/mcp_usage.db, sibling to the
# resolved db_path -- never a table in papers.db itself, which would need a migrations/ entry.
# Built lazily on first use, not at import time, same "construct the real collaborator late"
# reasoning as app/dashboard/server.py's _LazyMcpServer for its own real-infra dependency; here
# the constructor itself is cheap (no I/O until .record() opens a connection), so the "lazy"
# part is really about handing app/usage_log.py::record_usage a zero-arg callable per its own
# interface rather than an eagerly-built instance.
_usage_log_path = Path(_db_path).parent / "mcp_usage.db"
_usage_log: UsageLog | None = None


def _get_usage_log() -> UsageLog:
    global _usage_log
    if _usage_log is None:
        _usage_log = UsageLog(_usage_log_path)
    return _usage_log


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="semantic_search")
def semantic_search(
    query: str, filters: SearchFilters | None = None, k: int | None = None
) -> SearchResponse:
    """Passage-level search over the ingested corpus. Returns cited, grounded passages
    (`GroundedResult`s) plus a `Coverage` note — never bare text. `k` left unset uses the
    server's configured default (`Config.top_k`, `_cfg` above); pass it explicitly to override.

    The old "at most 32 results ever" ceiling is GONE (2026-08-19): the reranker used to truncate
    any batch over TEI's 32-item vendor limit, so the candidate pool was pinned to 32 no matter
    what `k` asked for. It now chunks oversized batches and merges them by score, and the pool
    follows `Config.rerank_depth`.

    Set `filters.max_hits_per_paper` when asking "which papers…" so one verbose paper cannot fill
    the page. Better still, for a question whose answer is a LIST OF PAPERS, use `scan_corpus` —
    ranked top-k retrieval samples, it does not enumerate, and it cannot tell you what it missed."""
    return _server.semantic_search(query, filters, k)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="scan_corpus")
def scan_corpus(
    pattern: str, paper_id: str | None = None, author_org: str | None = None,
    max_matches_per_paper: int = 3, context: int = 200,
) -> ScanResponse:
    """Exhaustive regex scan over every stored block — the tool for "WHICH PAPERS contain X".

    `semantic_search` ranks and samples; it cannot promise completeness, and it cannot tell you
    what it missed. This examines every block, so recall is 1.0 for the pattern you give — at the
    price of lexical false positives you reject by reading them. Recall cannot be repaired after
    the fact; precision can.

    Pattern is a Python regex, case-insensitive. Widen the vocabulary rather than trusting one
    spelling (`bootstrap|resampl|jackknife`), because a paper that never names the technique will
    not match. Every hit carries `section_path`, which is what separates a method NAMED in Related
    Work (a citation) from one USED in Methods.

    `paper_id` narrows to a single document — the right way to resolve a definition or an
    abbreviation, which retrieval handles badly. `author_org` restricts to papers carrying a
    curated (enumerated, not heuristic) authorship tag for that organisation."""
    return _server.scan_corpus(pattern, paper_id, author_org, max_matches_per_paper, context)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="search_papers")
def search_papers(
    query: str, filters: SearchFilters | None = None, k: int | None = None
) -> PaperSearchResponse:
    """Whole-paper/summary-level search over the ingested corpus. `k` left unset uses the
    server's configured default (`Config.top_k`); pass it explicitly to override.

    Same `k` semantics as `semantic_search` — see its docstring for the clamp and the removal of
    the old result-count ceiling."""
    return _server.search_papers(query, filters, k)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="get_paper")
def get_paper(paper_id: str) -> PaperSummaryView:
    """Fetch a stored paper's summary view by id."""
    return _server.get_paper(paper_id)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="get_span")
def get_span(anchor: Anchor) -> str:
    """Resolve an `Anchor` (from a prior search result's `.anchor`) back to the full verbatim
    text of the source block it points at — the citation-verification round trip."""
    return _server.get_span(anchor)


if __name__ == "__main__":
    mcp.run()
