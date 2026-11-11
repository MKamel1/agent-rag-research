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
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import WithJsonSchema

from app.assembly import build_mcp_server
from app.usage_log import UsageLog, record_usage
from contracts.errors import TransientError
from contracts.mcp_server import (
    PaperSearchResponse,
    PaperSummaryView,
    ScanResponse,
    SearchResponse,
)
from contracts.provenance import Anchor
from contracts.vector_index import SearchFilters
from rag.config import load_config
from rag.mcp_server import build_instructions

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

try:
    _server = build_mcp_server(
        _cfg, db_path=_db_path, blob_dir=_blob_dir, collection=_cfg.collection
    )
except TransientError as _error:
    # OP-1: build_mcp_server's vector-store constructor does a network round trip, so a down vector
    # store used to kill this process with a raw traceback at import time -- which an MCP client
    # only ever sees as "Connection closed". Say what is wrong and how to fix it instead.
    # ponytail: the whole server still needs the vector store to start; SQLite-only tools could
    # run without it if the vector index were constructed lazily (follow-up ticket).
    sys.exit(
        f"app.serve: cannot start -- the vector store is unreachable ({_error}). It is a CPU-only "
        "container and does not need the GPU: run `python -m app.doctor --cpu-only`, then "
        "reconnect the MCP client."
    )
# MC-2: self-describing server. `instructions` come from the live corpus facts (SQLite only, via
# `corpus_stats`), never hand-written per corpus -- five corpora share this entry point.
mcp = FastMCP("research-system-rag", instructions=build_instructions(_server.corpus_stats()))

# MC-2: `SearchFilters` (contracts/, protected) has no field descriptions, so a cold agent sees bare
# names in the tool schema. The descriptions live here instead and are injected into the schema of
# the `filters` parameter only (`WithJsonSchema`); validation still uses the real `SearchFilters`,
# so the retriever receives exactly the same object as before. Texts carry no corpus facts or
# digits (those belong in `instructions`, generated from `corpus_stats`).
_FILTER_DESCRIPTIONS = {
    "categories": "Keep documents carrying ANY of these category tags (see corpus_stats top_categories).",
    "published_after": "Inclusive lower bound on the document's published date (ISO date).",
    "published_before": "Inclusive upper bound on the document's published date (ISO date).",
    "kind": "Match passages (chunk) or whole-document summaries (summary); leave unset normally.",
    "doc_type": "Restrict to one document kind: paper or book. Books suit definitions and foundations.",
    "paper_id": "Scope to ONE document, by its stored id exactly as get_paper accepts it (no arxiv: "
                "prefix). An unknown id raises an error instead of returning nothing.",
    "author_org": "Restrict to documents tagged as authored by this organisation. Without "
                  "author_org_curated_only this also matches heuristic tags, which are often wrong.",
    "author_org_curated_only": "With author_org: match only the exact, enumerated tier. "
                               "No effect without author_org.",
    "max_hits_per_paper": "Subtractive cap on passages per document in one result set; useful for "
                          "which-documents questions, but it can leave fewer than k results.",
    "min_distinct_papers": "Additive: append passages until at least this many distinct documents "
                           "appear (the result can exceed k).",
}


def _described_filters_schema() -> dict:
    schema = SearchFilters.model_json_schema()
    for name, description in _FILTER_DESCRIPTIONS.items():
        schema["properties"][name]["description"] = description
    return schema


_Filters = Annotated[
    SearchFilters | None,
    WithJsonSchema({"anyOf": [_described_filters_schema(), {"type": "null"}], "default": None}),
]

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
    query: str, filters: _Filters = None, k: int | None = None
) -> SearchResponse:
    """Passage-level search over the ingested corpus. Returns cited, grounded passages
    (`GroundedResult`s) plus a `Coverage` note — never bare text. `k` left unset uses the
    server's configured default (`Config.top_k`, `_cfg` above); pass it explicitly to override.

    No stage of this pipeline rejects a candidate for scoring low in absolute terms -- there is
    no relevance floor. A full `k`-sized result set is the `k` best-available passages, not `k`
    endorsements that any of them answer your question; judge relevance from the passage text
    itself. (A floor was proposed and rejected in review -- it stays rejected until a
    score-distribution census over known-answerable vs. known-absent queries, RI-M7, shows the
    score distributions actually separate. Do not add one here.)

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
    query: str, filters: _Filters = None, k: int | None = None
) -> PaperSearchResponse:
    """Whole-paper/summary-level search over the ingested corpus. `k` left unset uses the
    server's configured default (`Config.top_k`); pass it explicitly to override.

    Same `k` semantics as `semantic_search` — see its docstring for the clamp and the removal of
    the old result-count ceiling, and for why a full result set is not evidence that any of the
    returned papers actually address the query (no relevance floor exists, and one stays
    rejected pending RI-M7)."""
    return _server.search_papers(query, filters, k)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="scan_methods")
def scan_methods(
    method: str, paper_id: str | None = None, author_org: str | None = None,
    max_matches_per_paper: int = 3, context: int = 200,
) -> ScanResponse:
    """`scan_corpus` with the synonym layer built in — "WHICH PAPERS use method X" where X may be
    known by several names ("RRF" / "reciprocal rank fusion" / "rank fusion"; "GIDAS" / "German
    in-depth accident study"; "reranking" / "reranked" / "reranker").

    The method is resolved against a curated alias map (see `list_methods` for every known family)
    and the family's surface forms are scanned exactly like `scan_corpus`: every block examined,
    recall 1.0 FOR THE ALIAS GROUP, lexical false positives you reject by reading. An unknown
    method scans its literal name; an input ambiguous between families raises rather than guesses.

    Same scope boundary as `scan_corpus` versus `semantic_search`: this enumerates vocabulary, it
    does not rank meaning. A paper that uses the method under a name the map has not learned will
    not match — for that case use `semantic_search` (semantic, non-enumerative) or `scan_corpus`
    with your own pattern. `author_org` is the curated (enumerated) tier only."""
    return _server.scan_methods(method, paper_id, author_org, max_matches_per_paper, context)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="list_methods")
def list_methods() -> list[str]:
    """Canonical names of every method family `scan_methods` knows, sorted. Use it to discover
    what can be asked about (e.g. "NIEON (non-impaired eyes-on driver reference model)") before
    calling `scan_methods`. Metadata, not evidence."""
    return _server.list_methods()


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="get_figures")
def get_figures(paper_id: str, kind: str = "all") -> list[dict]:
    """The figures and/or tables stored for one paper, ordered by page — the structured artifact
    surface. `kind`: "figure", "table", or "all" (default). Figure keys: {kind, id, page, caption,
    image_path, bbox}; table keys: {kind, id, page, caption, markdown, bbox} — a table's
    `markdown` IS its content, so table facts are answerable without vision. Pair with
    `get_paper` (section list) and `get_section` (reading). Raises for an unknown paper_id;
    caption can be empty (parsing does not always recover one)."""
    return _server.get_figures(paper_id, kind)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="get_section")
def get_section(paper_id: str, section_path: str) -> list:
    """One section of a paper as its blocks in reading order — linear reading over MCP. Get valid
    `section_path` values from `get_paper`'s `section_paths`. Returns [] for a known paper with
    no blocks under that path (heading recovery is imperfect); raises for an unknown paper_id.
    Blocks are the same provenance type `get_span` resolves, so any block here is citable."""
    return _server.get_section(paper_id, section_path)


@mcp.tool()
@record_usage(_get_usage_log, source="mcp", tool="corpus_stats")
def corpus_stats() -> dict:
    """Corpus-level aggregates: paper/block/chunk/figure/table counts, published-date range,
    doc_type histogram, top categories. Call before searching — knowing which corpus you are
    talking to and how large it is changes how to scope everything else."""
    return _server.corpus_stats()


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
