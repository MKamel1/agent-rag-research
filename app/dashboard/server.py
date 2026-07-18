"""`python -m app.dashboard.server --port 8700 --data-dir <dir> --token <tok>` -- the Corpus
Dashboard's composition root: a stdlib `http.server` binding a network interface (Tailscale
reachability, not just localhost) that serves the static frontend, `GET /api/status`, and
token-gated `POST /api/control`.

`ThreadingHTTPServer` (finding #7): each request runs on its own thread, so a `POST /api/control`
(which may block for seconds inside `controller.pause`/`stop`/`resume` waiting for a process to
die) never queues behind the frontend's every-~4s `GET /api/status` poll, or vice versa.

`GET /api/status` composes the response from `controller.liveness()` (the sole `run_manifest.json`
reader) and `status.py`'s pure `ingest_state`/telemetry reads (principal-design-review finding
#6) -- `_status_dict` is the one place that does the merge, matching the API contract's exact
shape (`docs/DESIGN-corpus-dashboard.md`).

`POST /api/control` is gated on `X-Dashboard-Token` via `hmac.compare_digest` (constant-time, so a
byte-by-byte-mismatch timing side channel can't leak the token) -- Tailscale is the network
boundary, this token stops any other tailnet node from issuing control commands.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.dashboard import controller, status
from rag.config import load_config

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

# Search-side (query-time) params, DISPLAY-ONLY here -- editing them is a separate step (the query
# server, `app.serve`/`rag/retriever.py`, not this build-run control panel). Values are duplicated
# as plain constants rather than imported from `app.serve`/`rag/retriever.py` (this dashboard
# process stays lightweight -- `app.serve`'s own import graph pulls in `mcp`/`app.assembly`) --
# see the module docstrings cited below for the real source of truth on each.
#
# `Config.top_k` (=10) and `Config.rerank_depth` (=50) are DEAD fields -- a 2026-07-18 code sweep
# found no code path that reads either. The REAL knobs are `app/serve.py`'s per-query `k` default
# (`semantic_search`/`search_papers`, k=10) and `rag/retriever.py`'s hardcoded
# `_RERANK_POOL_SIZE=32` (itself capped by `rag/reranker.py`'s `_MAX_BATCH_SIZE=32`) -- displayed
# below instead of binding this UI to the dead Config fields.
_SEARCH_DISPLAY = {
    "top_k_default": 10,  # app/serve.py semantic_search/search_papers k=10, NOT Config.top_k
    "rerank_pool_size": 32,  # rag/retriever.py _RERANK_POOL_SIZE, reranker caps it at 32 too
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
            **_SEARCH_DISPLAY,
            "hybrid_dense_weight": _STATIC_CONFIG.hybrid_dense_weight,
        },
    }


def make_handler(
    data_dir: Path, token: str, *, status_module=status, controller_module=controller
) -> type[BaseHTTPRequestHandler]:
    """`status_module`/`controller_module` are injectable (default: the real modules) so a route
    smoke test can pass a fake status provider without a real DB, manifest, or subprocess."""
    static_body = _STATIC_INDEX.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._respond(200, static_body, content_type="text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._json(200, _status_dict(data_dir, status_module, controller_module))
            else:
                self.send_error(404)

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
    status_module=status, controller_module=controller,
) -> ThreadingHTTPServer:
    handler = make_handler(
        data_dir, token, status_module=status_module, controller_module=controller_module
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
