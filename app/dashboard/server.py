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
_RUN_FIELDS = (
    "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
)

# `parse_batch_size` (OG-42) has no per-run override anywhere in the launch path (unlike
# `target`/`parse_workers`, it is never threaded onto the `app.build_corpus`/`app.ingest` command
# line) -- the value that actually governs every run IS the static `config.yaml` default, read
# once at process start the same way `controller.py`'s own `_build_manifest` already loads it.
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_STATIC_CONFIG = load_config(_CONFIG_PATH)


def _status_dict(data_dir: Path, status_module, controller_module) -> dict:
    """Merges `controller.liveness()` (run identity) with `status.py`'s pure reads (funnel,
    telemetry, downloads, consistency) into the exact `/api/status` JSON shape."""
    live = controller_module.liveness(data_dir) or {}
    corpus = status_module.read_corpus(data_dir)
    done = corpus["funnel"].get("done")
    return {
        "funnel": corpus["funnel"],
        "run": {
            **{field: live.get(field) for field in _RUN_FIELDS},
            "parse_batch_size": _STATIC_CONFIG.parse_batch_size,
        },
        "telemetry": status_module.read_telemetry(
            live.get("events_path"), done,
            data_dir=data_dir, started_at=live.get("started_at"), target=live.get("target"),
        ),
        "downloads": status_module.read_downloads(data_dir, live.get("target")),
        "consistency": status_module.read_consistency(done, live.get("collection")),
        "quarantine_reasons": corpus["quarantine_reasons"],
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
            if action == "start":
                controller_module.start(
                    data_dir, int(body["target"]), int(body.get("parse_workers", 3))
                )
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
