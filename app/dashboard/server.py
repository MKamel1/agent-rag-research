"""`python -m app.dashboard.server --port 8700 --data-dir <dir> [--token <tok>]` -- the Corpus
Dashboard's composition root: a stdlib `http.server` binding a network interface (Tailscale
reachability, not just localhost) that serves the static frontend, `GET /api/status`,
`GET /api/search`, and token-gated `POST /api/control`.

**`--token` is optional (T-DOC78).** Omit it and the server reads `<data-dir>/.dashboard_token`,
generating one (`secrets.token_hex(16)`, written at mode `0600`) the first time none exists --
`_load_or_create_token` below. An explicit `--token` still wins, for anyone scripting this. An
empty effective token refuses to start (RI-2): "" authenticates requests that send no
X-Dashboard-Token header at all. Generation is an atomic pid-qualified-temp + `os.replace` write,
and records its writer's identity in `<data-dir>/.dashboard_token.sidecar` (RI-6) so a LATER
GENERATION while that writer is still live -- which would hand the two dashboards divergent
tokens, resolved silently by last-writer-wins -- is refused; a start that finds the recorded
writer's token file intact hands out that same token instead, since two readers of one file
converge rather than diverge (a second dashboard on another port against the same corpus is a
supported shape -- scripts/dashboard.sh's DASHBOARD_PORT/DASHBOARD_DATA_DIR are independent). Beyond
just removing a hand-managed file convention nothing in the repo previously created or read, this
also gets the token out of `ps`/`/proc/<pid>/cmdline` output in the normal (no-`--token`) path --
any other local user could previously read a live dashboard's control token straight off the
process list.

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
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from datetime import date
from functools import lru_cache, partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.assembly import build_mcp_server
from app.dashboard import controller, status, tag_pool
from app.dashboard.controller import InvalidOverrideError
from app.usage_log import UsageLog, read_usage_summary
from contracts.config import Config
from contracts.errors import ContractError, PermanentError, TransientError
from contracts.vector_index import SearchFilters
from pydantic import ValidationError
from rag.atomic_write import atomic_write
from rag.config import load_config
from rag.mcp_server import _MAX_K as _SEARCH_MAX_K
from rag.mcp_server import _MIN_K as _SEARCH_MIN_K
import yaml

logger = logging.getLogger(__name__)


class ControlValidationError(ValueError):
    """Raised when a `POST /api/control` body fails boundary validation (OG-49#3/#6) --
    `parse_workers`/`batch_size` out of range, or an arXiv keyword/category/date that would break
    the query it eventually builds. Mapped to a 400, never reaching `controller.start`/`retarget`
    (never spawning a subprocess that would just crash later, "running")."""


# OG-49#3: parse_workers=0 spawns zero Pass-1 workers -- app.ingest reports "success" having
# parsed nothing, and build_corpus.build_to_target resubmits the same non-empty cached-not-done
# batch forever with no sleep (an infinite no-op loop that leaks build_batch_*.ids files). Rejected
# here before ever reaching controller.start/retarget.
_MIN_PARSE_WORKERS = 1
# OG-49#6/M7: same charset/format rules as rag/harvester.py's ArxivSource._build_query -- kept in
# sync by naming, not import, since this boundary check exists so a bad value 400s BEFORE a
# subprocess is even spawned (the harvester's own check is defense-in-depth for every other, non-
# dashboard caller, e.g. a hand-edited config.yaml).
_UNSAFE_KEYWORD_CHARS_RE = re.compile(r'["\\]')
_CATEGORY_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{8}$")


def _validate_editable_kwargs(kwargs: dict) -> None:
    """The DOWNLOAD-side query filters shared by every action that can launch a downloader
    (`"start"`/`"retarget"`'s full run, and T-DOC78's `"download"` action) -- pulled out of
    `_validate_control_kwargs` so `"download"` can validate just this subset without a
    target/parse_workers it never has."""
    for keyword in (kwargs.get("keywords") or []) + (kwargs.get("remove_keywords") or []):
        if _UNSAFE_KEYWORD_CHARS_RE.search(keyword):
            raise ControlValidationError(
                f"keyword {keyword!r} contains a '\"' or '\\\\', which would break the arXiv "
                "query it's added to or removed from"
            )
    for category in kwargs.get("arxiv_categories") or []:
        if not _CATEGORY_RE.match(category):
            raise ControlValidationError(
                f"arxiv_categories entry {category!r} is not a valid arXiv subject code "
                "(letters/digits/dot/dash only)"
            )
    for field in ("arxiv_date_from", "arxiv_date_to"):
        value = kwargs.get(field)
        if value is not None and not _DATE_RE.match(value):
            raise ControlValidationError(f"{field} {value!r} is not YYYY-MM-DD or YYYYMMDD")


def _validate_tags(tags: list[str]) -> None:
    """`add_tags` is the one tag-pool action that introduces brand-new query strings (`hold_tags`/
    `restore_tags` only move EXISTING pool entries around) -- same boundary check
    `_validate_editable_kwargs` already applies to `keywords`, since an added tag ends up in the
    same `focus_area_queries` an arXiv query gets built from."""
    for tag in tags:
        if _UNSAFE_KEYWORD_CHARS_RE.search(tag):
            raise ControlValidationError(
                f"tag {tag!r} contains a '\"' or '\\\\', which would break the arXiv query it's "
                "added to"
            )


def _validate_control_kwargs(target: int, parse_workers: int, kwargs: dict) -> None:
    """Raises `ControlValidationError` on the first bad field found in a `start`/`retarget`
    request. Called before `controller.start`/`retarget` -- a bad value 400s the request instead
    of spawning a subprocess that would crash later (OG-49#3/#6)."""
    if target < 1:
        # Otherwise `build_to_target`'s `n_done >= target` is trivially true for any target <= 0
        # (including a negative one) -- a silent, instant, "successful" empty run.
        raise ControlValidationError(f"target must be >= 1, got {target}")
    if parse_workers < _MIN_PARSE_WORKERS:
        raise ControlValidationError(
            f"parse_workers must be >= {_MIN_PARSE_WORKERS}, got {parse_workers}"
        )
    batch_size = kwargs.get("batch_size")
    if batch_size is not None and batch_size < 1:
        raise ControlValidationError(f"batch_size must be >= 1 (or unset), got {batch_size}")
    telemetry_poll_interval = kwargs.get("telemetry_poll_interval")
    if telemetry_poll_interval is not None and telemetry_poll_interval <= 0:
        raise ControlValidationError(
            f"telemetry_poll_interval must be > 0, got {telemetry_poll_interval}"
        )
    _validate_editable_kwargs(kwargs)


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
    "stranded_policy", "mode",
)

# `parse_batch_size`: OG-43 adds a per-run override (`start(..., parse_batch_size=...)` ->
# `run_manifest.json`'s own top-level `parse_batch_size` field, distinct from the STATIC default
# below) -- `_status_dict` prefers the manifest's value when a run has one, and falls back to this
# process-start-time `config.yaml` read (unchanged OG-42 behavior) otherwise.
# T-DOC89 §3: discovery (RAG_CONFIG -> cwd -> walk-up), not a hardcoded repo-root path -- the
# repo-root `config.yaml` this used to read directly was the TRACKED TEMPLATE (now renamed to
# config.example.yaml precisely so it's not silently loadable); a real deployment's config is
# found the same way every other `app/` entrypoint's bare `load_config()` finds it.
#
# T-DOC89 part-1-review Critical 2: LAZY, not a module-level read. Every one of this module's own
# use sites is inside a function body (`_status_dict`, `_LazyMcpServer.semantic_search`, the
# download-mode spawn helper) -- nothing needs this at import time, and `scripts/dashboard.sh`
# `cd`s to the repo root before launch, where discovery finds nothing in a checkout with no real
# deployed config.yaml (only the renamed, gitignored-away template). A module-level `load_config()`
# call made the whole server module unimportable in that shape; `lru_cache` gives the exact same
# "read once, reuse for the process lifetime" behavior the old module-level global had, just
# deferred to first actual use.
#
# T-DOC90: `data_dir`-first, discovery-fallback -- the same two-branch shape
# `controller.py::_load_base_config` already uses. A bare `load_config()` here meant every
# `GET /api/status` raised ContractError whenever the process's cwd had no config.yaml, which is
# exactly how `scripts/dashboard.sh` launches it (it cd's to the repo root). `lru_cache` is keyed
# on `data_dir` so the "read once per process" behavior is unchanged.
@lru_cache(maxsize=1)
def _static_config(data_dir: Path) -> Config:
    data_dir_config = data_dir / "config.yaml"
    if data_dir_config.exists():
        return load_config(data_dir_config)
    return load_config()


# Search-side (query-time) params, read straight off `_static_config()` -- as of 2026-07-18,
# `Config.top_k`/`Config.rerank_depth` are genuinely wired (`app/assembly.py::build_mcp_server`
# threads them into `McpServer`'s `default_k`/`Retriever`'s `rerank_pool_size`), so this display
# no longer needs to hardcode a stand-in value for either: `top_k_default` is the real
# `McpServer.semantic_search`/`search_papers` fallback when a caller's `k` is unset, and
# `rerank_pool_size` is `rerank_depth` unclamped, matching what `build_mcp_server` now passes
# `Retriever` (RI-16): the reranker's per-call vendor batch limit no longer caps the pool it can
# draw from -- it packs an oversized pool into several batches and merges their scores instead of
# truncating (`rag/reranker.py`), so a `rerank_depth` above that limit is genuinely used, not
# wasted, and this display must show it uncapped to stay trustworthy (D-10).
def _search_display(data_dir: Path) -> dict:
    return {
        "top_k_default": _static_config(data_dir).top_k,
        "rerank_pool_size": _static_config(data_dir).rerank_depth,
    }


def _editable_query_kwargs(body: dict) -> dict:
    """keywords/remove_keywords/arxiv_categories/arxiv_date_from/arxiv_date_to -- the DOWNLOAD-side
    filters shared by `"start"`/`"retarget"`'s full run and T-DOC78's `"download"` action, omitting
    any field the request didn't set (see `_control_kwargs`'s own docstring for why absence, not an
    explicit `None`/`[]`, matters on `retarget`)."""
    kwargs: dict = {}
    keywords = body.get("keywords")
    if keywords:
        kwargs["keywords"] = [str(k) for k in keywords]
    remove_keywords = body.get("remove_keywords")
    if remove_keywords:
        kwargs["remove_keywords"] = [str(k) for k in remove_keywords]
    categories = body.get("arxiv_categories")
    if categories:
        kwargs["arxiv_categories"] = [str(c) for c in categories]
    if body.get("arxiv_date_from"):
        kwargs["arxiv_date_from"] = str(body["arxiv_date_from"])
    if body.get("arxiv_date_to"):
        kwargs["arxiv_date_to"] = str(body["arxiv_date_to"])
    return kwargs


def _control_kwargs(body: dict) -> dict:
    """Pulls the OG-43 editable params out of a `POST /api/control` body for `start`/`retarget`,
    omitting any field the request didn't set -- `controller.start`'s own kwargs already default
    each of these to "unedited" (`None`/no keywords), so an absent field must stay absent here
    too, not turn into an explicit `None`/`[]` that could shadow a stored value on `retarget`."""
    kwargs = _editable_query_kwargs(body)
    if body.get("telemetry_poll_interval") is not None:
        kwargs["telemetry_poll_interval"] = float(body["telemetry_poll_interval"])
    if body.get("batch_size") is not None:
        kwargs["batch_size"] = int(body["batch_size"])
    if body.get("parse_batch_size") is not None:
        kwargs["parse_batch_size"] = int(body["parse_batch_size"])
    # OG-46: relevance-priority ordering.
    if body.get("ordering"):
        kwargs["ordering"] = str(body["ordering"])
    # How to treat papers left Pass-1-complete by an earlier pause (`Config.stranded_policy`).
    if body.get("stranded_policy"):
        kwargs["stranded_policy"] = str(body["stranded_policy"])
    return kwargs


def _status_dict(data_dir: Path, status_module, controller_module) -> dict:
    """Merges `controller.liveness()` (run identity) with `status.py`'s pure reads (funnel,
    telemetry, downloads, downloader, disk, consistency, drop-in tray) into the exact
    `/api/status` JSON shape.

    KNOWN TRAP: `_static_config(data_dir).drop_in_dir` is NEVER read directly here --
    `Config.drop_in_dir` is relative whenever config.yaml omits it, and a relative value means a
    DIFFERENT directory to this dashboard process (cwd=<repo root>) than to the
    `app.ingest_local` child `controller.start_drop_in` spawns (cwd=<data_dir>). Routing through
    `controller_module.resolve_drop_dir` (the same helper `_spawn_drop_in` uses) is what keeps
    this block honest about which directory is actually being scanned -- see that helper's own
    docstring for the full story."""
    drop_dir = controller_module.resolve_drop_dir(_static_config(data_dir))
    # Promotion runs here, before liveness/the block below are read, so a queued drop-in starts
    # as soon as the previous run goes terminal without the operator having to click anything. It
    # is lock-guarded and idempotent (controller.promote_pending_drop_in), so calling it on every
    # poll is safe.
    controller_module.promote_pending_drop_in(data_dir)
    live = controller_module.liveness(data_dir) or {}
    corpus = status_module.read_corpus(data_dir)
    done = corpus["funnel"].get("done")
    manifest_parse_batch_size = live.get("parse_batch_size")
    # T-DOC41/D-5 Part 2: the persistent tag pool (app/dashboard/tag_pool.py), NOT a second read of
    # config.yaml -- `active_count` is what Part 1's exhaustion banner names, so the two features
    # can never drift apart (both read this same composed pool).
    pool = tag_pool.load(data_dir, _static_config(data_dir).focus_area_queries)
    return {
        "funnel": corpus["funnel"],
        "by_doc_type": corpus["by_doc_type"],
        "run": {
            **{field: live.get(field) for field in _RUN_FIELDS},
            "parse_batch_size": (
                manifest_parse_batch_size if manifest_parse_batch_size is not None
                else _static_config(data_dir).parse_batch_size
            ),
            # O-1: "supply_exhausted" or None -- `run.status == "done"` alone loses WHY a run
            # finished short of target; app.build_corpus's run_outcome_<run_id>.json (read via
            # controller.outcome_for_run, never this module reading the file itself) is the only
            # source for that nuance.
            "outcome": controller_module.outcome_for_run(data_dir, live.get("run_id")),
        },
        "telemetry": status_module.read_telemetry(
            live.get("events_path"), done,
            data_dir=data_dir, started_at=live.get("started_at"), target=live.get("target"),
        ),
        # RI-30: thread the manifest's run_cwd here exactly as the downloader block below does --
        # one downloader, one log, two fields. An edited run's prefetch.log lands in its
        # override scratch dir; falling back to data_dir tails the last unedited run's stale log
        # and lets these two fields disagree about the same downloader.
        "downloads": status_module.read_downloads(
            data_dir, _static_config(data_dir).prefetch_target,
            run_cwd=live.get("run_cwd") or data_dir,
        ),
        # D-10 Task 3: manifest_pid is passed for EVERY mode now, not just "download" -- a
        # "full" run's manifest pid is a build_corpus SUPERVISOR, not a downloader, but it
        # legitimately spawns app.prefetch_pdfs as a child. Withholding the pid here (the
        # pre-D-10 behaviour) made every full run's own prefetch child misreport as an orphan;
        # status.read_downloader's descendant walk is what now tells "our child" from "a real
        # orphan" (see its own docstring).
        "downloader": status_module.read_downloader(
            live.get("run_cwd"), live.get("pid"), data_dir=data_dir,
        ),
        "disk": status_module.read_disk(data_dir),
        # The manifest's collection wins while a run is live (a run may use a run-scoped override
        # config, `.run_overrides/<run_id>`), but `"collection"` is only written there when a run
        # STARTS -- so an idle dashboard, or one brought up before its first run, has no manifest
        # value. Falling through to `read_consistency`'s own `collection or "papers"` default then
        # counted points in the DEFAULT corpus: on the Waymo data dir that reported the main
        # `papers` corpus's 412,167 points next to Waymo's own `sqlite_done: 17` and called it
        # `consistent: True` -- a false pass on the very "done rows, zero vectors" check
        # (OG-16/T-DOC35) this field exists to make. This data dir's own config is the correct
        # fallback; `verify_numbers.py` does not cross-check `consistency`, so nothing else caught it.
        "consistency": status_module.read_consistency(
            done, live.get("collection") or _static_config(data_dir).collection,
        ),
        "quarantine_reasons": corpus["quarantine_reasons"],
        "search": {
            **_search_display(data_dir),
            "hybrid_dense_weight": _static_config(data_dir).hybrid_dense_weight,
        },
        "tei": status_module.read_tei_status(),
        "drop_in": {
            **status_module.read_drop_in(drop_dir, data_dir / "papers.db"),
            "dir": str(drop_dir),
            "pending_drop_in": bool(live.get("pending_drop_in")),
        },
        "usage": read_usage_summary(data_dir / "mcp_usage.db"),
        "tags": {**pool, "active_count": len(pool["active"]), "held_count": len(pool["held"])},
    }


class _LazyMcpServer:
    """Builds the real retrieval stack (`app.assembly.build_mcp_server`) on the FIRST search
    request, not at dashboard startup -- construction touches a real `GpuLock`, a live vector
    store connection, and TEI HTTP clients (T-DOC24/25's vendor infra), none of which this
    process should reach for just to serve `/api/status` polls. Reused for every search after
    that (one build, not one per request).

    `db_path`/`blob_dir` follow the same `<data_dir>/papers.db` / `<data_dir>/blobs` convention
    `app/dashboard/status.py::read_corpus` already reads for this exact `data_dir`; `collection`
    is `_static_config().collection` (the base `config.yaml`, same source `_status_dict`'s other
    static fields already read from).

    OG-48#7: `ThreadingHTTPServer` runs every request on its own thread, so two concurrent FIRST
    searches could both see `self._server is None` and both call `build_mcp_server` -- wasteful
    duplicate GpuLock/vector-store/TEI clients, one of them just discarded. Guarded with a
    double-checked `threading.Lock`: the common case (already built) still never takes the lock at
    all.
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._server = None
        self._build_lock = threading.Lock()

    def semantic_search(self, query: str, filters: SearchFilters | None, k: int | None):
        if self._server is None:
            with self._build_lock:
                if self._server is None:  # re-check: another thread may have built it while we waited
                    self._server = build_mcp_server(
                        _static_config(self._data_dir),
                        db_path=str(self._data_dir / "papers.db"),
                        blob_dir=str(self._data_dir / "blobs"),
                        collection=_static_config(self._data_dir).collection,
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
                # "/" stays open (OG-48#1/OG-49#4) -- it's just the static frontend shell, no
                # corpus content or GPU work; the page itself supplies the token on every API call
                # it makes, same as `POST /api/control` already requires.
                self._respond(200, static_body, content_type="text/html; charset=utf-8")
            elif parsed.path == "/api/status":
                if not self._token_ok():
                    return
                # RI-27 fix 2: a broken config.yaml (operator typo while the dashboard is up)
                # used to raise straight out of _status_dict through the socket layer -- the
                # client got a connection reset with no HTTP response at all, on every poll
                # (startup never touches config, so the server came up healthy, and lru_cache
                # does not cache exceptions). The except tuple is exactly the config-error types
                # rag.config.load_config's own docstring enumerates; the response reuses
                # do_POST's {"ok": False, "message": str(e)} shape rather than a second format.
                # str(e) is safe to return here (unlike /api/search's generic message,
                # OG-48#8): the audience is the token-authenticated operator who broke their
                # own config and needs the parse/validation detail to fix it.
                try:
                    self._json(200, _status_dict(data_dir, status_module, controller_module))
                except (ContractError, yaml.YAMLError, ValidationError, FileNotFoundError) as e:
                    logger.warning("status build failed on a config error: %s", e)
                    self._json(500, {"ok": False, "message": str(e)})
                    return
            elif parsed.path == "/api/search":
                if not self._token_ok():
                    return
                self._handle_search(urllib.parse.parse_qs(parsed.query))
            else:
                self.send_error(404)

        def _token_ok(self) -> bool:
            # OG-48#1/OG-49#4: GET /api/status and /api/search had NO auth at all -- /api/search
            # does REAL GPU work (embed -> hybrid -> rerank) and returns corpus content, /api/status
            # leaks run config/focus_queries, both reachable by any tailnet host on 0.0.0.0. Same
            # constant-time check `POST /api/control` already uses, read from the same header (not
            # a query string, which would land in access logs/browser history).
            if hmac.compare_digest(self.headers.get("X-Dashboard-Token", ""), token):
                return True
            self._json(401, {"ok": False, "message": "invalid or missing X-Dashboard-Token"})
            return False

        def _handle_search(self, params: dict[str, list[str]]) -> None:
            query = (params.get("q") or [""])[0].strip()
            if not query:
                self._json(400, {"ok": False, "message": "missing required query param 'q'"})
                return
            # OG-48#5: clamp here too, before `k` ever reaches `mcp_server.semantic_search` --
            # `_LazyMcpServer`/a test fake's `semantic_search` may not be the real `McpServer`
            # (which clamps independently, rag/mcp_server.py), so this route defends the same
            # bound itself rather than trusting every possible backend to.
            k = _parse_int(params.get("k"))
            if k is not None:
                k = max(_SEARCH_MIN_K, min(k, _SEARCH_MAX_K))
            filters = _search_filters_from_params(params)
            # OG-48#9: a reversed date range (published_after > published_before) matches nothing
            # in VectorIndex -- indistinguishable from "no results for this query" unless caught
            # here, at the boundary where the raw request params are still in hand. contracts/
            # vector_index.py's SearchFilters itself is left unvalidated (foundation territory);
            # this is the caller-facing boundary check instead.
            if (
                filters is not None
                and filters.published_after is not None
                and filters.published_before is not None
                and filters.published_after > filters.published_before
            ):
                self._json(400, {
                    "ok": False,
                    "message": (
                        f"published_after ({filters.published_after.isoformat()}) must be on or "
                        f"before published_before ({filters.published_before.isoformat()})"
                    ),
                })
                return
            # Deliverable 2 §3 (docs/superpowers/plans/2026-07-30-mcp-usage-telemetry.md Task 3):
            # record this dashboard-originated search alongside the MCP tools' own recording
            # (app/serve.py's @record_usage) so the usage picture has no hole in it. UsageLog()
            # is cheap to construct (no connection opened until .record()), so a fresh instance
            # per request is fine -- same "open, write, close" posture record() already has.
            usage_log = UsageLog(data_dir / "mcp_usage.db")
            start = time.perf_counter()
            try:
                response = mcp_server.semantic_search(query, filters, k)
            except (TransientError, PermanentError, ContractError) as e:
                usage_log.record(
                    source="dashboard", tool="semantic_search", query=query, k=k, filters=filters,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    result_count=None, candidates=None, error=type(e).__name__,
                )
                # A real search reaches live infra (GpuLock/TEI/the vector store, T-DOC24/25) --
                # degrade to a clean error response, same as `/api/control`'s dispatch below,
                # never a crashed request thread (ThreadingHTTPServer runs each request on its
                # own thread, so one failed search must not affect the `/api/status` poll or any
                # other in-flight request either).
                # OG-48#8: `str(e)` here can carry internal detail (GpuLock file paths, TEI/vendor
                # URLs and status text) -- logged in full server-side, but the CLIENT gets a
                # generic message; every tailnet host that can reach this route is now an
                # authenticated one (OG-48#1/OG-49#4), not a trusted one.
                logger.warning("search failed for query=%r: %s", query, e)
                self._json(502, {"ok": False, "message": "search failed; see server logs"})
                return
            usage_log.record(
                source="dashboard", tool="semantic_search", query=query, k=k, filters=filters,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                result_count=response.coverage.returned, candidates=response.coverage.candidates,
                error=None,
            )
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
            if not self._token_ok():
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
            except (ControlValidationError, InvalidOverrideError) as e:
                # OG-49#3/#6/#11: boundary validation / a re-validated bad override -- reject
                # BEFORE controller.start/retarget ever spawns a subprocess.
                self._json(400, {"ok": False, "message": str(e)})
                return
            except (controller_module.DoubleRunError, controller_module.NoRunError,
                    controller_module.DropInPendingError,
                    KeyError, TypeError, ValueError, OSError) as e:
                # ValueError: e.g. `int(body["target"])` on a non-numeric `"target"` -- previously
                # uncaught, dropping the connection with no response body at all. OSError: e.g.
                # Task 2's resume-from-a-crashed-run spawn failure (subprocess.Popen(cwd=<missing
                # dir>) -> FileNotFoundError) -- same "uncaught, dropped connection" failure mode,
                # now a clean response instead.
                self._json(409, {"ok": False, "message": str(e)})
                return
            self._json(200, {"ok": True, "message": f"{action} ok"})

        def _dispatch(self, action: str | None, body: dict) -> None:
            if action in ("start", "retarget"):
                target = int(body["target"])
                parse_workers = int(body.get("parse_workers", 3))
                kwargs = _control_kwargs(body)
                _validate_control_kwargs(target, parse_workers, kwargs)
                if action == "start":
                    controller_module.start(data_dir, target, parse_workers, **kwargs)
                else:
                    # OG-43: "Apply new settings" while a run is already live -- stop-then-start
                    # with the edited params, instead of making the user pause/stop by hand first.
                    controller_module.retarget(data_dir, target, parse_workers, **kwargs)
            elif action == "download":
                # T-DOC78: download PDFs only -- no GPU, no pass1/pass2. Reuses the same
                # keywords/categories/dates the Apply panel already stages (mode-agnostic
                # override machinery, controller._maybe_build_override); mutual exclusion with a
                # live full run is the SAME double-run guard `"start"` already gets, for free.
                kwargs = _editable_query_kwargs(body)
                _validate_editable_kwargs(kwargs)
                controller_module.start(
                    data_dir, _static_config(data_dir).prefetch_target, 1, mode="download", **kwargs,
                )
            elif action == "start_drop_in":
                controller_module.start_drop_in(data_dir)
            elif action == "add_tags":
                tags = [str(t) for t in body.get("tags") or []]
                _validate_tags(tags)
                tag_pool.add(data_dir, _static_config(data_dir).focus_area_queries, tags)
            elif action == "hold_tags":
                tags = [str(t) for t in body.get("tags") or []]
                tag_pool.hold(data_dir, _static_config(data_dir).focus_area_queries, tags)
            elif action == "restore_tags":
                tags = [str(t) for t in body.get("tags") or []]
                tag_pool.restore(data_dir, _static_config(data_dir).focus_area_queries, tags)
            elif action == "purge_tags":
                tags = [str(t) for t in body.get("tags") or []]
                tag_pool.purge(data_dir, _static_config(data_dir).focus_area_queries, tags)
            elif action == "restart_downloader":
                # D-6 Task 4: controller.py must never import status.py (module docstrings on
                # both sides), so THIS composition root -- which already imports both -- supplies
                # the real process-table scan `restart_downloader` has no safe default for.
                # RI-19: bound here, not passed bare -- a bare reference gets called zero-arg,
                # and `_live_prefetch_pids`'s `data_dir=None` default then skips the cwd/corpus
                # qualification entirely (the machine-wide, argv-only pre-RI-8 behaviour), so
                # this corpus's restart would SIGTERM/SIGKILL another live corpus's downloader.
                # RI-8 fixed the counting path (`read_downloader`); the destructive path was
                # missed. Still satisfies `restart_downloader`'s zero-arg
                # `Callable[[], list[int]]` contract.
                controller_module.restart_downloader(
                    data_dir,
                    live_pids=partial(status_module._live_prefetch_pids, data_dir=data_dir),
                )
            elif action == "pause":
                controller_module.pause(data_dir)
            elif action == "resume":
                controller_module.resume(data_dir)
            elif action == "stop":
                controller_module.stop(data_dir)
            elif action == "free_gpu":
                controller_module.free_gpu(data_dir)
            elif action == "load_for_mcp":
                controller_module.load_for_mcp(data_dir)
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


# T-DOC78: the operator's token convention, formalized -- previously a pure hand convention
# (nothing in the repo created or read this file; the operator kept a token here and passed it as
# `--token $(cat .dashboard_token)` from memory every restart).
_TOKEN_FILENAME = ".dashboard_token"

# RI-6: provenance sidecar FOR the token file -- records WHICH process generated the current
# `.dashboard_token`, so a stale sidecar from a dead run is distinguishable from a live one. The
# token file itself stays plain text (`cat`, operator-authored tokens and verify_numbers.py all
# read it verbatim); the sidecar holds only non-secret writer identity, so it can appear without
# touching any of those contracts.
_TOKEN_SIDECAR_NAME = ".dashboard_token.sidecar"


class _LiveTokenWriterError(RuntimeError):
    """Raised when the token sidecar's recorded writer is still the live process at that pid --
    another dashboard instance appears to be running on this data dir right now."""


def _read_token_sidecar(data_dir: Path) -> dict | None:
    """Reads the writer-provenance sidecar, tolerating every malformed shape as absent (RI-6):
    missing, unreadable, torn/truncated JSON, or a `pid` that isn't a positive int all return
    `None` rather than raising. The sidecar can only ever ADD a refusal (a confirmed-live rival
    writer below) -- it must never be able to add a crash. Identity fields may be None (the
    capture is best-effort); only a sane `pid` is required."""
    try:
        record = json.loads((data_dir / _TOKEN_SIDECAR_NAME).read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        return None
    return record


def _sidecar_writer_is_live(record: dict) -> bool:
    """True only when the recorded writer is STILL the same live process -- matched on /proc
    starttime AND cmdline exactly like the run manifest's `_verified_pid` (controller.py), never
    on bare liveness: a bare check cannot tell the original writer apart from an unrelated
    process the OS has since recycled onto that pid (reboot, pid-space wraparound), and would
    refuse every restart after such a wraparound. Dead/recycled/unreadable reads as False --
    the normal restart case."""
    stored_starttime = record.get("pid_starttime")
    stored_cmdline = record.get("pid_cmdline")
    if stored_starttime is None or stored_cmdline is None:
        return False
    identity = controller._process_identity(record["pid"])
    if identity is None:
        return False
    return identity == (stored_starttime, stored_cmdline)


def _refuse_if_sidecar_writer_is_live(data_dir: Path) -> None:
    record = _read_token_sidecar(data_dir)
    if record is None or not _sidecar_writer_is_live(record):
        return
    raise _LiveTokenWriterError(
        f"{data_dir / _TOKEN_SIDECAR_NAME} records its writer as pid {record['pid']}, which is "
        "still alive -- another dashboard appears to be running on this data dir; stop it first "
        "(scripts/dashboard.sh stop), or remove the sidecar if that pid record is stale"
    )


def _write_private_file(path: Path, text: str) -> None:
    """Writes `text` to `path` atomically via the shared pid-qualified helper (`rag.atomic_write`,
    RI-21's generalization of this function), at mode 0600 -- the token file must be created
    private BEFORE any content exists, never briefly world-readable mid-write. `os.replace` is
    POSIX-atomic, so a concurrent reader sees the old content or the full new content, never a
    torn one, and a crash mid-write leaves the target untouched (RI-6's crash window: the old
    touch->chmod->write_text sequence could die between touch and write_text, persisting an EMPTY
    token file that the next start read back as ""). The pid-qualified temp name per OG-49 M12's
    two-writer convention means two concurrent first-time generators cannot interleave into one
    shared temp path."""
    atomic_write(path, text, mode=0o600)


def _load_or_create_token(data_dir: Path) -> str:
    """Read `<data_dir>/.dashboard_token`, or generate and persist a new one if there isn't a
    usable one yet (T-DOC78). An existing NON-EMPTY file is honored verbatim -- never
    regenerated, never re-chmodded: an operator-managed token must survive restarts unchanged,
    and this function has no business tightening or loosening permissions it didn't set. An
    empty or unreadable one is regenerated instead of being handed back (RI-6): "" used to feed
    RI-2's auth hole from the file side, comparing equal to `_token_ok`'s missing-header default.

    Generation writes the token atomically (`_write_private_file`) and records this process's
    identity in `<data-dir>/.dashboard_token.sidecar` -- which process generated the CURRENT
    token file. The next start validates against it IMMEDIATELY BEFORE GENERATING: a sidecar
    whose writer is still alive means that writer is running on this data dir right now, so
    replacing its token file would resolve the ambiguity silently by last-writer-wins (two live
    dashboards, divergent tokens) -- it raises `_LiveTokenWriterError` instead. A start that
    finds a usable token file returns it WITHOUT consulting the sidecar: reading one shared
    value cannot diverge, so there is nothing to refuse (and refusing would reject a supported
    second-dashboard-on-another-port start that would have been correct). A corrupt sidecar is
    tolerated as absent (provenance lost, nothing more); a failed sidecar WRITE degrades to a
    logged warning for the same reason -- the token itself is already persisted and auth does
    not depend on the sidecar.

    Never logs/prints the token value itself -- only where it was written, so the operator can
    find it (`cat <path>`) without the value passing through any log line. The sidecar likewise
    carries writer identity, never the secret."""
    token_path = data_dir / _TOKEN_FILENAME
    if token_path.exists():
        try:
            existing = token_path.read_text().strip()
        except (OSError, UnicodeDecodeError):
            existing = ""
        if existing:
            return existing

    _refuse_if_sidecar_writer_is_live(data_dir)

    token = secrets.token_hex(16)
    _write_private_file(token_path, token)
    identity = controller._process_identity(os.getpid())
    sidecar_record = {
        "pid": os.getpid(),
        "pid_starttime": identity[0] if identity else None,
        "pid_cmdline": identity[1] if identity else None,
    }
    try:
        _write_private_file(data_dir / _TOKEN_SIDECAR_NAME, json.dumps(sidecar_record))
    except OSError:
        logger.warning(
            "dashboard: could not write token-writer sidecar %s -- live-writer detection is "
            "unavailable for this token",
            data_dir / _TOKEN_SIDECAR_NAME, exc_info=True,
        )
    print(f"dashboard: generated a new token at {token_path}")
    return token


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    # No sensible default across different corpora/environments (the operator's real corpus vs. a
    # scratch/test one) the way app/serve.py's `--data-dir` has one (that flag falls back to a
    # cwd-relative config.yaml -- a different meaning entirely: this one is where papers.db/blobs/
    # the token file/run_manifest.json all live, and guessing wrong would point the dashboard at
    # the wrong corpus silently) -- left required rather than invented.
    parser.add_argument("--data-dir", required=True)
    parser.add_argument(
        "--token", default=None,
        help="X-Dashboard-Token required for POST /api/control. Omit to read/generate "
             "<data-dir>/.dashboard_token instead (T-DOC78) -- an explicit value here always wins; "
             "an empty value is refused at startup (RI-2).",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="bind interface -- default 0.0.0.0 so a Tailscale IP can reach it; pass the "
             "tailnet IP directly for a tighter bind",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    data_dir = Path(args.data_dir)
    try:
        token = args.token if args.token is not None else _load_or_create_token(data_dir)
    except _LiveTokenWriterError as e:
        print(f"dashboard: refusing to start: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    if not token:
        # RI-2, fail closed at the effective-token resolution point (not inside
        # `_load_or_create_token` -- only the flag can produce "" today, but a guard where the
        # value is resolved covers any future third source too): a configured "" token makes the
        # missing-header default in `_token_ok` (`headers.get(..., "")`) compare equal, so every
        # request with NO X-Dashboard-Token header at all authenticates. Refuse-to-start over
        # silently regenerating: an operator who typed `--token ""` has a broken invocation and
        # needs to be told.
        print(
            "dashboard: refusing to start: the effective token is empty (--token was given as "
            "an empty string, or <data-dir>/.dashboard_token is empty) -- an empty token "
            "authenticates requests that carry no X-Dashboard-Token header at all, disabling "
            "auth entirely; pass a non-empty --token or omit it to use the token file",
            file=sys.stderr,
        )
        raise SystemExit(2)
    httpd = build_server(data_dir, token, args.port, host=args.host)
    print(f"Corpus dashboard: http://{args.host}:{args.port} (data_dir={data_dir})")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
