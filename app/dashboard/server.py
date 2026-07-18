"""`python -m app.dashboard.server --port 8700 --data-dir <dir> --token <tok>` -- the Corpus
Dashboard's composition root: a stdlib `http.server` binding a network interface (Tailscale
reachability, not just localhost) that serves the static frontend, `GET /api/status`,
`GET /api/search`, and token-gated `POST /api/control`.

`ThreadingHTTPServer` (finding #7): each request runs on its own thread, so a `POST /api/control`
(which may block for seconds inside `controller.pause`/`stop`/`resume` waiting for a process to
die) never queues behind the frontend's every-~4s `GET /api/status` poll, or vice versa.

`GET /api/status` composes the response from `controller.liveness()` (the sole `run_manifest.json`
reader) and `status.py`'s pure `ingest_state`/telemetry reads (principal-design-review finding
#6) -- `_status_dict` is the one place that does the merge, matching the API contract's exact
shape (`docs/DESIGN-corpus-dashboard.md`).

`GET /api/search` (2026-07-18, the "Try a search" panel) runs a REAL grounded search against the
finished corpus -- unlike everything else in this file, it is not a read of `ingest_state`/the
manifest. It reuses `app.assembly.build_mcp_server` (the same composition root `app/serve.py`
uses) rather than reimplementing any part of the embed/hybrid/RRF/rerank pipeline -- see
`_LazyMcpServer` below for why that build is deferred to the first actual search request.

`POST /api/control` is gated on `X-Dashboard-Token` via `hmac.compare_digest` (constant-time, so a
byte-by-byte-mismatch timing side channel can't leak the token) -- Tailscale is the network
boundary, this token stops any other tailnet node from issuing control commands.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import urllib.parse
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.assembly import build_mcp_server
from app.dashboard import controller, status
from contracts.errors import ContractError, PermanentError, TransientError
from contracts.vector_index import SearchFilters
from rag.config import load_config
from rag.reranker import _MAX_BATCH_SIZE as _RERANKER_MAX_BATCH_SIZE

logger = logging.getLogger(__name__)

_STATIC_INDEX = Path(__file__).parent / "static" / "index.html"
# OG-42: `params` (which carries `telemetry_poll_interval`) was missing here -- the manifest had
# the value, it just never reached the API payload.
# OG-43: `paper_ids_file` added -- the frontend's "mode: cache-first" indicator needs it to note
# an explicit id-scoped run.
# OG-45/OG-46: `arxiv_categories`/`arxiv_date_from`/`arxiv_date_to`/`ordering` -- the DOWNLOAD
# filters and ordering mode actually in effect for the current/last run (manifest carries the
# unedited base-config value even when a run didn't override them, see `controller._build_manifest`).
_RUN_FIELDS = (
    "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
    "paper_ids_file", "arxiv_categories", "arxiv_date_from", "arxiv_date_to", "ordering",
)

# `parse_batch_size`: OG-43 adds a per-run override (`start(..., parse_batch_size=...)` ->
# `run_manifest.json`'s own top-level `parse_batch_size` field, distinct from the STATIC default
# below) -- `_status_dict` prefers the manifest's value when a run has one, and falls back to this
# process-start-time `config.yaml` read (unchanged OG-42 behavior) otherwise.
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_STATIC_CONFIG = load_config(_CONFIG_PATH)

# Search-side (query-time) params, read straight off `_STATIC_CONFIG` -- as of 2026-07-18,
# `Config.top_k`/`Config.rerank_depth` are genuinely wired (`app/assembly.py::build_mcp_server`
# threads them into `McpServer`'s `default_k`/`Retriever`'s `rerank_pool_size`), so this display
# no longer needs to hardcode a stand-in value for either: `top_k_default` is the real
# `McpServer.semantic_search`/`search_papers` fallback when a caller's `k` is unset, and
# `rerank_pool_size` mirrors the same `min(rerank_depth, _RERANKER_MAX_BATCH_SIZE)` clamp
# `build_mcp_server` applies (a value above 32 is silently truncated by TEI's `/rerank` batch
# limit either way -- `rag/reranker.py`'s `_MAX_BATCH_SIZE`).
def _search_display() -> dict:
    return {
        "top_k_default": _STATIC_CONFIG.top_k,
        "rerank_pool_size": min(_STATIC_CONFIG.rerank_depth, _RERANKER_MAX_BATCH_SIZE),
    }


def _control_kwargs(body: dict) -> dict:
    """Pulls the OG-43 editable params out of a `POST /api/control` body for `start`/`retarget`,
    omitting any field the request didn't set -- `controller.start`'s own kwargs already default
    each of these to "unedited" (`None`/no keywords), so an absent field must stay absent here
    too, not turn into an explicit `None`/`[]` that could shadow a stored value on `retarget`."""
    kwargs: dict = {}
    if body.get("telemetry_poll_interval") is not None:
        kwargs["telemetry_poll_interval"] = float(body["telemetry_poll_interval"])
    if body.get("batch_size") is not None:
        kwargs["batch_size"] = int(body["batch_size"])
    if body.get("parse_batch_size") is not None:
        kwargs["parse_batch_size"] = int(body["parse_batch_size"])
    keywords = body.get("keywords")
    if keywords:
        kwargs["keywords"] = [str(k) for k in keywords]
    # OG-45: arXiv DOWNLOAD-side filters -- REPLACE (not augment) the base config's value.
    categories = body.get("arxiv_categories")
    if categories:
        kwargs["arxiv_categories"] = [str(c) for c in categories]
    if body.get("arxiv_date_from"):
        kwargs["arxiv_date_from"] = str(body["arxiv_date_from"])
    if body.get("arxiv_date_to"):
        kwargs["arxiv_date_to"] = str(body["arxiv_date_to"])
    # OG-46: relevance-priority ordering.
    if body.get("ordering"):
        kwargs["ordering"] = str(body["ordering"])
    return kwargs


def _status_dict(data_dir: Path, status_module, controller_module) -> dict:
    """Merges `controller.liveness()` (run identity) with `status.py`'s pure reads (funnel,
    telemetry, downloads, downloader, disk, consistency) into the exact `/api/status` JSON shape."""
    live = controller_module.liveness(data_dir) or {}
    corpus = status_module.read_corpus(data_dir)
    done = corpus["funnel"].get("done")
    manifest_parse_batch_size = live.get("parse_batch_size")
    return {
        "funnel": corpus["funnel"],
        "run": {
            **{field: live.get(field) for field in _RUN_FIELDS},
            "parse_batch_size": (
                manifest_parse_batch_size if manifest_parse_batch_size is not None
                else _STATIC_CONFIG.parse_batch_size
            ),
        },
        "telemetry": status_module.read_telemetry(
            live.get("events_path"), done,
            data_dir=data_dir, started_at=live.get("started_at"), target=live.get("target"),
        ),
        "downloads": status_module.read_downloads(data_dir, live.get("target")),
        "downloader": status_module.read_downloader(live.get("run_cwd"), live.get("log_path")),
        "disk": status_module.read_disk(data_dir),
        "consistency": status_module.read_consistency(done, live.get("collection")),
        "quarantine_reasons": corpus["quarantine_reasons"],
        "search": {
            **_search_display(),
            "hybrid_dense_weight": _STATIC_CONFIG.hybrid_dense_weight,
        },
    }


class _LazyMcpServer:
    """Builds the real retrieval stack (`app.assembly.build_mcp_server`) on the FIRST search
    request, not at dashboard startup -- construction touches a real `GpuLock`, a live vector
    store connection, and TEI HTTP clients (T-DOC24/25's vendor infra), none of which this
    process should reach for just to serve `/api/status` polls. Reused for every search after
    that (one build, not one per request).

    `db_path`/`blob_dir` follow the same `<data_dir>/papers.db` / `<data_dir>/blobs` convention
    `app/dashboard/status.py::read_corpus` already reads for this exact `data_dir`; `collection`
    is `_STATIC_CONFIG.collection` (the base `config.yaml`, same source `_status_dict`'s other
    static fields already read from).
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._server = None

    def semantic_search(self, query: str, filters: SearchFilters | None, k: int | None):
        if self._server is None:
            self._server = build_mcp_server(
                _STATIC_CONFIG,
                db_path=str(self._data_dir / "papers.db"),
                blob_dir=str(self._data_dir / "blobs"),
                collection=_STATIC_CONFIG.collection,
            )
        return self._server.semantic_search(query, filters, k)


def _parse_int(values: list[str] | None) -> int | None:
    if not values or not values[0]:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def _parse_date(values: list[str] | None) -> date | None:
    if not values or not values[0]:
        return None
    try:
        return date.fromisoformat(values[0])
    except ValueError:
        return None


def _search_filters_from_params(params: dict[str, list[str]]) -> SearchFilters | None:
    """`categories` is comma-separated (matches the dashboard control panel's own subject-tag
    convention, `index.html`'s `#newSubject`); `published_after`/`published_before` are ISO
    `YYYY-MM-DD` (an `<input type="date">`'s native value format). All three already flow
    end-to-end through `Retriever`/`VectorIndex` (`SearchFilters.categories`/`published_after`/
    `published_before`) -- this just parses them off the query string. `None` (no filter at all)
    when none of the three params were given, matching `semantic_search`'s own `filters=None`
    "no restriction" convention.
    """
    raw_categories = (params.get("categories") or [""])[0]
    categories = [c.strip() for c in raw_categories.split(",") if c.strip()] or None
    published_after = _parse_date(params.get("published_after"))
    published_before = _parse_date(params.get("published_before"))
    if categories is None and published_after is None and published_before is None:
        return None
    return SearchFilters(
        categories=categories, published_after=published_after, published_before=published_before
    )


def make_handler(
    data_dir: Path, token: str, *,
    status_module=status, controller_module=controller, mcp_server_factory=None,
) -> type[BaseHTTPRequestHandler]:
    """`status_module`/`controller_module` are injectable (default: the real modules) so a route
    smoke test can pass a fake status provider without a real DB, manifest, or subprocess.
    `mcp_server_factory` is the same idea for `/api/search`: default `_LazyMcpServer(data_dir)`
    (the real, lazily-built retrieval stack); a test passes an object with its own
    `semantic_search(query, filters, k)` (e.g. an `McpServer` built over `FakeVectorStore`/
    `FakeReranker`/`FakeEmbedder`) instead -- see `rag/fakes` -- so this route never has to touch
    a real GPU lock or vector store just to prove the route itself works.
    """
    static_body = _STATIC_INDEX.read_bytes()
    mcp_server = mcp_server_factory if mcp_server_factory is not None else _LazyMcpServer(data_dir)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path in ("/", "/index.html"):
                self._respond(200, static_body, content_type="text/html; charset=utf-8")
            elif parsed.path == "/api/status":
                self._json(200, _status_dict(data_dir, status_module, controller_module))
            elif parsed.path == "/api/search":
                self._handle_search(urllib.parse.parse_qs(parsed.query))
            else:
                self.send_error(404)

        def _handle_search(self, params: dict[str, list[str]]) -> None:
            query = (params.get("q") or [""])[0].strip()
            if not query:
                self._json(400, {"ok": False, "message": "missing required query param 'q'"})
                return
            k = _parse_int(params.get("k"))
            filters = _search_filters_from_params(params)
            try:
                response = mcp_server.semantic_search(query, filters, k)
            except (TransientError, PermanentError, ContractError) as e:
                # A real search reaches live infra (GpuLock/TEI/the vector store, T-DOC24/25) --
                # degrade to a clean error response, same as `/api/control`'s dispatch below,
                # never a crashed request thread (ThreadingHTTPServer runs each request on its
                # own thread, so one failed search must not affect the `/api/status` poll or any
                # other in-flight request either).
                logger.warning("search failed for query=%r: %s", query, e)
                self._json(502, {"ok": False, "message": str(e)})
                return
            self._json(200, {
                "ok": True,
                "coverage": {
                    "returned": response.coverage.returned,
                    "candidates": response.coverage.candidates,
                },
                "results": [
                    {
                        "paper_id": r.paper_id,
                        "title": r.citation.title,
                        "section_path": r.citation.section_path,
                        "snippet": r.passage_text,
                        "score": r.score,
                    }
                    for r in response.results
                ],
            })

        def do_POST(self) -> None:
            if self.path != "/api/control":
                self.send_error(404)
                return
            if not hmac.compare_digest(self.headers.get("X-Dashboard-Token", ""), token):
                self._json(401, {"ok": False, "message": "invalid or missing X-Dashboard-Token"})
                return

            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"ok": False, "message": "invalid JSON body"})
                return

            action = body.get("action")
            try:
                self._dispatch(action, body)
            except (controller_module.DoubleRunError, controller_module.NoRunError,
                    KeyError, TypeError) as e:
                self._json(409, {"ok": False, "message": str(e)})
                return
            self._json(200, {"ok": True, "message": f"{action} ok"})

        def _dispatch(self, action: str | None, body: dict) -> None:
            if action in ("start", "retarget"):
                target = int(body["target"])
                parse_workers = int(body.get("parse_workers", 3))
                kwargs = _control_kwargs(body)
                if action == "start":
                    controller_module.start(data_dir, target, parse_workers, **kwargs)
                else:
                    # OG-43: "Apply new settings" while a run is already live -- stop-then-start
                    # with the edited params, instead of making the user pause/stop by hand first.
                    controller_module.retarget(data_dir, target, parse_workers, **kwargs)
            elif action == "pause":
                controller_module.pause(data_dir)
            elif action == "resume":
                controller_module.resume(data_dir)
            elif action == "stop":
                controller_module.stop(data_dir)
            else:
                raise KeyError(f"unknown action {action!r}")

        def _json(self, code: int, obj: dict) -> None:
            self._respond(code, json.dumps(obj).encode(), content_type="application/json")

        def _respond(self, code: int, body: bytes, *, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # quiet stderr; use logging instead
            logger.info("%s - %s", self.address_string(), fmt % args)

    return Handler


def build_server(
    data_dir: Path, token: str, port: int, host: str = "0.0.0.0", *,
    status_module=status, controller_module=controller, mcp_server_factory=None,
) -> ThreadingHTTPServer:
    handler = make_handler(
        data_dir, token, status_module=status_module, controller_module=controller_module,
        mcp_server_factory=mcp_server_factory,
    )
    return ThreadingHTTPServer((host, port), handler)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--token", required=True, help="required in X-Dashboard-Token for POST /api/control")
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="bind interface -- default 0.0.0.0 so a Tailscale IP can reach it; pass the "
             "tailnet IP directly for a tighter bind",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    data_dir = Path(args.data_dir)
    httpd = build_server(data_dir, args.token, args.port, host=args.host)
    print(f"Corpus dashboard: http://{args.host}:{args.port} (data_dir={data_dir})")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
