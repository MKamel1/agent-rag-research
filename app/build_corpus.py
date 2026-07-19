"""`python -m app.build_corpus` — the continuous cache-first corpus builder (OG-40/OG-41).

**Why this exists.** `app.prefetch_pdfs` downloads PDFs (network-bound, ~240/hr) faster than
`app.ingest` parses them (GPU-bound, ~180/hr) -- running both together is free throughput, and the
cache stays ahead of the parser. But `app.ingest` invoked directly still defaults to re-running its
own query *discovery* (`harvest_refs` -> `orchestrator.harvest`), which caps at far fewer distinct
papers than the downloader already has cached (`reviews/OPERATIONAL-GAPS.md` OG-40: a 3K run capped
at 809/3000 while prefetch held 3,909+ PDFs). This module is the thin supervisor that closes that
gap: it keeps `app.prefetch_pdfs` running, and repeatedly hands `app.ingest` a batch of exactly the
cached-but-not-yet-done paper ids (`--paper-ids-file`, OG-40) until the corpus reaches `--target`
done papers, is exhausted, or stalls. See `docs/DESIGN-continuous-cache-first-build.md`.

**Not an ingest refactor.** `app.ingest` is two-pass with VRAM isolation (Pass 1 parses a paper
set, Pass 2 embeds the SAME set -- both call `harvest_refs`, ARCHITECTURE.md §3) -- so each
invocation needs a FIXED snapshot of ids, exactly what `--paper-ids-file` already guarantees. This
module never touches `app.ingest`'s or `app.prefetch_pdfs`'s internals; it only launches/re-launches
them with a computed id list.

**Cold start needs no special case.** If the cache is empty and the downloader hasn't produced
anything yet, `cached_not_done` below returns `[]` and `prefetch_alive()` is `True` -- the loop
just waits for the first PDFs, the same branch as any other "caught up with the cache" pause. No
separate "cold start" code path exists on purpose: the ordinary wait branch already IS the
cold-start behavior the design doc calls for. `app.ingest`'s own query-harvest fallback (used when
invoked directly with neither `--paper-ids-file` nor a cache) is untouched -- it stays the
bootstrap/eval-set path, just no longer the thing a dashboard-launched run does by default.

**Process-group placement.** `app.prefetch_pdfs` is launched here with no `start_new_session` --
it inherits THIS process's group, so `app/dashboard/controller.py`'s `os.killpg` pause/stop (aimed
at build_corpus, the group leader the dashboard actually spawns) reaches it too. Same for every
`app.ingest` batch this loop runs (a plain blocking `subprocess.run`, no session of its own).

**Prefetch's own target.** `app.prefetch_pdfs` reads its download target from
`config.prefetch_target` (no `--target` flag exists on it today) -- if `--target` here exceeds
that, the downloader only ever fills to `prefetch_target` and this loop stops short, cleanly, via
the ordinary "cache exhausted and downloader stopped" branch below. A follow-up could add a
`--target` passthrough to `app.prefetch_pdfs` if that ever needs to differ per build; not done here
(config.yaml is foundation-protected, and there's exactly one build running at a time today).
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from rag.config import load_config
from rag.harvester import ArxivSource, Harvester

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]

_PREFETCH_PID_NAME = "prefetch.pid"

# How long to wait, once the cache is fully drained but the downloader is still alive, before
# re-checking `cached_not_done` -- long enough to accumulate a real batch at prefetch's ~240/hr
# pace (roughly 20 new PDFs at the default), short enough that a build doesn't visibly stall for
# a full prefetch re-harvest cycle (3600s, `app/prefetch_pdfs.py::_RE_HARVEST_INTERVAL_SECONDS`).
_DEFAULT_POLL_INTERVAL_S = 300.0

# Consecutive "cache empty, downloader still alive" cycles (at the poll interval above) before
# giving up as stalled instead of waiting forever -- mirrors `app/prefetch_pdfs.py`'s own
# `--max-idle` guard, sized to roughly one prefetch re-harvest cycle's worth of patience.
_DEFAULT_MAX_IDLE = 12


# --- cache-first to-do list (OG-40/OG-41) --------------------------------------------------------


def _ro_connect(db_path: str) -> sqlite3.Connection | None:
    """Guaranteed-read-only connection (`mode=ro` URI) -- same pattern as
    `app/dashboard/status.py::_ro_connect`. Degrades to `None` (never raises) on a missing/
    unmigrated/locked db: a fresh corpus build's very first pass runs before `papers.db` exists."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.execute("SELECT 1")
        return conn
    except sqlite3.Error:
        return None


def _done_ids(db_path: str) -> set[str]:
    conn = _ro_connect(db_path)
    if conn is None:
        return set()
    try:
        rows = conn.execute("SELECT paper_id FROM ingest_state WHERE stage='done'").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _normalize_date(value: str) -> str:
    """`Config.arxiv_date_from`/`arxiv_date_to` accept ISO `YYYY-MM-DD` or arXiv's compact
    `YYYYMMDD` (same two formats `rag/harvester.py::ArxivSource._validated_date` accepts) --
    `papers.published` is always stored ISO (`date.isoformat()`, DATA-CONTRACTS.md's SQLite
    schema), so a compact value must be reformatted before it can be compared against that
    column with a plain string `>=`/`<=`."""
    return value if "-" in value else f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def done_count(
    db_path: str, *,
    date_from: str | None = None, date_to: str | None = None,
    categories: list[str] | None = None,
) -> int:
    """How many papers `ingest_state` currently has at stage='done' -- the loop's own stop
    condition (`>= target`), read fresh on every iteration so a concurrent `app.ingest` batch's
    progress is always seen.

    `date_from`/`date_to` (optional, `Config.arxiv_date_from`/`arxiv_date_to`) and `categories`
    (optional, `Config.arxiv_categories`, OR-matched -- same semantics as
    `rag/harvester.py::ArxivSource`'s own `cat:` clause: a paper counts if ANY of its
    `categories_json` entries is in the requested list): when any is set, joins onto `papers` and
    only counts 'done' papers matching every active filter. Without this, a run scoped to a date
    window and/or a subject filter would stop the instant the corpus's TOTAL done-count (papers
    outside the filter included) already exceeds `target`, even though zero matching papers had
    actually been ingested -- the "reached target" no-op a retarget to a new date range or
    category set would otherwise silently hit (T-DOC71 fixed the date half; this extends it to
    categories, the identically-shaped gap called out in that PR).
    """
    conn = _ro_connect(db_path)
    if conn is None:
        return 0
    try:
        if date_from is None and date_to is None and not categories:
            return conn.execute(
                "SELECT count(*) FROM ingest_state WHERE stage='done'"
            ).fetchone()[0]
        query = (
            "SELECT count(*) FROM ingest_state s JOIN papers p ON p.paper_id = s.paper_id "
            "WHERE s.stage='done'"
        )
        params: list[str] = []
        if date_from is not None:
            query += " AND p.published >= ?"
            params.append(_normalize_date(date_from))
        if date_to is not None:
            query += " AND p.published <= ?"
            params.append(_normalize_date(date_to))
        if categories:
            placeholders = ", ".join("?" * len(categories))
            query += (
                f" AND EXISTS (SELECT 1 FROM json_each(p.categories_json) c "
                f"WHERE c.value IN ({placeholders}))"
            )
            params.extend(categories)
        return conn.execute(query, params).fetchone()[0]
    finally:
        conn.close()


def cached_not_done(cache_dir: Path, db_path: str) -> list[str]:
    """The cache-first to-do list: basenames of `cache_dir/*.pdf` (same naming as
    `app/prefetch_pdfs.py::_pdf_path`) minus ids `ingest_state` already has at stage='done'.
    Sorted, so repeated calls against an unchanged cache/db return a stable batch."""
    cached = {p.stem for p in cache_dir.glob("*.pdf")}
    if not cached:
        return []
    return sorted(cached - _done_ids(db_path))


# --- ensure_prefetch_running: reuse a live downloader, never launch a duplicate ------------------


def _prefetch_pid_path(data_dir: Path) -> Path:
    return data_dir / _PREFETCH_PID_NAME


def _read_prefetch_pid(data_dir: Path) -> int | None:
    try:
        return int(_prefetch_pid_path(data_dir).read_text().strip())
    except (OSError, ValueError):
        return None


def _write_prefetch_pid(data_dir: Path, pid: int) -> None:
    _prefetch_pid_path(data_dir).write_text(str(pid))


def _is_live_prefetch(pid: int) -> bool:
    """pid+cmdline identity check: alive AND its `/proc/<pid>/cmdline` actually names
    `app.prefetch_pdfs` -- guards against a stale `prefetch.pid` whose PID has since been recycled
    onto an unrelated process. Same rigor as `app/dashboard/controller.py::_process_identity`
    minus its start-time tracking: a coincidental cmdline collision with an unrelated process is
    not a realistic risk for a single-purpose script name like this one."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
    except OSError:
        return False
    if "app.prefetch_pdfs" not in cmdline:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _spawn_prefetch(data_dir: Path) -> int:
    """Launches `app.prefetch_pdfs` as a child in THIS process's group -- no `start_new_session`,
    so it inherits build_corpus's group and `os.killpg` (dashboard controller pause/stop) reaches
    it too. Same `env PYTHONPATH=<repo>` / `cwd=data_dir` launch shape as
    `app/dashboard/controller.py::_spawn`."""
    cmd = ["env", f"PYTHONPATH={_REPO_ROOT}", sys.executable, "-m", "app.prefetch_pdfs"]
    proc = subprocess.Popen(cmd, cwd=str(data_dir))
    return proc.pid


def ensure_prefetch_running(data_dir: Path, *, spawn=_spawn_prefetch) -> Callable[[], bool]:
    """Ensures `app.prefetch_pdfs` is running: reuses an existing live one already tracked by
    `<data_dir>/prefetch.pid` if there is one, launches a fresh one otherwise -- never a duplicate
    downloader double-checking/double-downloading the same backlog. Returns a zero-arg liveness
    probe for whichever process it ends up owning, for the build loop's "is the downloader still
    working" checks."""
    pid = _read_prefetch_pid(data_dir)
    if pid is None or not _is_live_prefetch(pid):
        pid = spawn(data_dir)
        _write_prefetch_pid(data_dir, pid)
    return lambda: _is_live_prefetch(pid)


# --- the ingest runner: one fixed-set two-pass app.ingest invocation per batch -------------------


def _write_batch_ids(data_dir: Path, ids: list[str]) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    path = data_dir / f"build_batch_{ts}.ids"
    path.write_text("\n".join(ids) + "\n")
    return path


def _run_ingest(
    batch_file: Path, parse_workers: int, events_path: Path, data_dir: Path, *,
    telemetry_poll_interval: float | None = None,
) -> None:
    """One `app.ingest --paper-ids-file <batch_file>` invocation, blocking until that batch's full
    two-pass parse+finish completes. Same `env PYTHONPATH=<repo>` / `cwd=data_dir` launch shape as
    `app/dashboard/controller.py::_spawn`. `check=True`: a non-zero exit raises
    `subprocess.CalledProcessError` and stops the build loop rather than looping forever on a batch
    that never got marked done -- `ingest_state`'s checkpoints make a later retry pick back up,
    same as any other `app.ingest` failure/restart (matches that module's own "let it raise" style,
    see its `__main__`).

    `telemetry_poll_interval` (default `None`, matching `app.ingest`'s own CLI default): forwarded
    as `--telemetry-poll-interval` only when set, so the default-flags call is byte-for-byte the
    original command."""
    cmd = [
        "env", f"PYTHONPATH={_REPO_ROOT}",
        sys.executable, "-m", "app.ingest",
        "--paper-ids-file", str(batch_file),
        "--parse-workers", str(parse_workers),
        "--events-path", str(events_path),
    ]
    if telemetry_poll_interval is not None:
        cmd += ["--telemetry-poll-interval", str(telemetry_poll_interval)]
    subprocess.run(cmd, cwd=str(data_dir), check=True)


def _call_done_count(
    done_count, db_path: str, date_from: str | None, date_to: str | None,
    categories: list[str] | None,
) -> int:
    """Passes `date_from`/`date_to`/`categories` to `done_count` only when at least one is set --
    same "don't hand the injected test fake a kwarg it doesn't accept" convention as
    `_call_run_ingest`/`app/dashboard/controller.py::_call_spawn`: every existing test's
    `done_count` fake takes a single positional `db_path` and must keep working unmodified when
    no filter is active."""
    if date_from is None and date_to is None and not categories:
        return done_count(db_path)
    return done_count(db_path, date_from=date_from, date_to=date_to, categories=categories)


def _call_run_ingest(
    run_ingest, batch_file: Path, parse_workers: int, events_path: Path, data_dir: Path,
    telemetry_poll_interval: float | None,
) -> None:
    """Passes `telemetry_poll_interval` to `run_ingest` only when set -- same "don't hand the
    injected test fake a kwarg it doesn't accept" convention as
    `app/dashboard/controller.py::_call_spawn`."""
    if telemetry_poll_interval is None:
        run_ingest(batch_file, parse_workers, events_path, data_dir)
    else:
        run_ingest(
            batch_file, parse_workers, events_path, data_dir,
            telemetry_poll_interval=telemetry_poll_interval,
        )


# --- relevance ordering (OG-46: "new keyword jumps the queue") --------------------------------

# Cap on the metadata-only ranking harvest below -- big enough to usually cover one iteration's
# `cached_not_done` batch, small enough that the rate-limited (3s/page, `rag.harvester`) arXiv
# metadata fetch doesn't stall the loop for long.
_RELEVANCE_RANK_CAP = 500


def _relevance_rank(focus_area_queries: list[str]) -> list[str]:
    """One metadata-only `ordering="relevance"` harvest for `focus_area_queries` -- arXiv's own
    `sortBy=relevance` (rag/harvester.py), NO PDF download (`Harvester`/`ArxivSource` only hit the
    Atom metadata API). Returns base paper_ids, best match first.

    ponytail: built directly from `rag.harvester` rather than routing through `app.assembly`'s
    `harvest_refs`/`IngestionOrchestrator` -- the latter's composition root pulls in every other
    real adapter's heavy client (embedder, summarizer, vector store) this supervisor has no other
    use for, just to reach one `.harvest()` call.
    Also ignores `arxiv_categories`/`arxiv_date_from`/`arxiv_date_to`: the ranked list only
    REORDERS an already-filtered `cached_not_done` batch (`_order_by_relevance` below), so a
    wider/narrower candidate set here just weakens the priority signal -- it never changes what
    gets processed. Add categories/date passthrough if that signal turns out to matter in
    practice.
    """
    source = Harvester(ArxivSource())
    refs = source.harvest(focus_area_queries, _RELEVANCE_RANK_CAP, "relevance")
    return [ref.paper_id for ref in refs]


def _order_by_relevance(ids: list[str], ranked_ids: list[str]) -> list[str]:
    """`ids` (a `cached_not_done` batch), reordered so whichever ones also appear in
    `ranked_ids` (arXiv's own relevance order for the current focus, best first) come first, in
    that rank order; every other id keeps following, sorted, same as the un-reordered default.
    Pure reordering -- every id in `ids` is still present in the result, once (an ORDER, not a
    filter, per OG-46's spec)."""
    ids_set = set(ids)
    ranked_present = [pid for pid in ranked_ids if pid in ids_set]
    remaining = sorted(ids_set - set(ranked_present))
    return ranked_present + remaining


# --- the loop -------------------------------------------------------------------------------------


def build_to_target(
    data_dir: Path,
    db_path: str,
    cache_dir: Path,
    target: int,
    parse_workers: int,
    events_path: Path,
    *,
    batch_size: int | None = None,
    telemetry_poll_interval: float | None = None,
    ordering: str = "freshest_first",
    focus_area_queries: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    categories: list[str] | None = None,
    ensure_prefetch=ensure_prefetch_running,
    run_ingest=_run_ingest,
    cached_not_done=cached_not_done,
    done_count=done_count,
    relevance_rank=_relevance_rank,
    sleep=time.sleep,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    max_idle: int = _DEFAULT_MAX_IDLE,
) -> None:
    """Build the corpus to `target` done papers, cache-first: ensure the downloader is running,
    then repeatedly ingest whatever's cached-but-not-done until `done_count(db_path) >= target`,
    the cache is drained with the downloader dead (can't reach target), or `max_idle` consecutive
    caught-up-and-waited cycles pass with nothing new (stalled).

    Every external effect -- `ensure_prefetch`, `run_ingest`, `cached_not_done`, `done_count`,
    `relevance_rank`, `sleep` -- is an injectable seam (same style as
    `app/prefetch_pdfs.py::prefetch_loop` and `app/dashboard/controller.py::_spawn`), so a test
    drives this against fakes instead of a real GPU/network/subprocess.

    `ordering="relevance"` (OG-46, `Config.ordering`): each iteration's `cached_not_done` batch is
    reordered so the papers most relevant to `focus_area_queries` (arXiv's own ranking,
    `relevance_rank`) come first -- see `_order_by_relevance`. The rank is computed once, lazily,
    and memoized for this call's whole run: `focus_area_queries` is fixed for one `build_corpus`
    process's lifetime by construction (a dashboard keyword edit relaunches a brand-new process
    via `app/dashboard/controller.py::retarget`, it never mutates a live one), so there is no
    "focus changed mid-run" case here to invalidate against -- "cache within a run" degenerates to
    "compute once." Left as a `ponytail:` simplification: re-computing every iteration would add a
    real, rate-limited arXiv round trip to the hot loop, which would violate the "GPU never waits"
    invariant this module exists to protect; a later run's newly-downloaded papers just fall into
    the unranked "remaining" bucket if they weren't covered by the one ranking harvest's cap
    (`_RELEVANCE_RANK_CAP`) -- still processed (an ORDER, not a filter), just without a priority
    boost. Upgrade path if that's ever a real problem: re-rank when `cached_not_done` runs out of
    ranked ids, not every iteration.

    `date_from`/`date_to`/`categories` (`Config.arxiv_date_from`/`arxiv_date_to`/
    `arxiv_categories`): when any is set, `target` means "done papers matching this filter," not
    "done papers total" -- see `done_count`'s docstring. All unset (default) is byte-for-byte the
    old unscoped behavior.
    """
    prefetch_alive = ensure_prefetch(data_dir)
    idle_passes = 0
    ranked_ids: list[str] | None = None

    while True:
        n_done = _call_done_count(done_count, db_path, date_from, date_to, categories)
        if n_done >= target:
            logger.info("build_corpus: reached target -- %d/%d done", n_done, target)
            return

        ids = cached_not_done(cache_dir, db_path)
        if ordering == "relevance" and ids:
            if ranked_ids is None:
                ranked_ids = relevance_rank(focus_area_queries or [])
            ids = _order_by_relevance(ids, ranked_ids)
        if batch_size is not None:
            ids = ids[:batch_size]

        if not ids:
            if not prefetch_alive():
                logger.info(
                    "build_corpus: cache exhausted and the downloader has stopped -- stopping "
                    "short at %d/%d done",
                    n_done, target,
                )
                return
            idle_passes += 1
            if idle_passes >= max_idle:
                logger.info(
                    "build_corpus: stalled -- %d/%d done, no new cached papers after %d "
                    "consecutive idle pass(es) (max_idle=%d), giving up",
                    n_done, target, idle_passes, max_idle,
                )
                return
            logger.info(
                "build_corpus: caught up with the cache (%d/%d done) -- waiting %.0fs for the "
                "downloader",
                n_done, target, poll_interval_s,
            )
            sleep(poll_interval_s)
            continue

        batch_file = _write_batch_ids(data_dir, ids)
        logger.info(
            "build_corpus: ingesting a batch of %d cached-not-done paper(s) (%d/%d done so far)",
            len(ids), n_done, target,
        )
        _call_run_ingest(
            run_ingest, batch_file, parse_workers, events_path, data_dir, telemetry_poll_interval,
        )

        # OG-49#3/#4: a batch that ran but made ZERO net done_count progress (e.g.
        # `parse_workers=0` silently "succeeds" having parsed nothing, or a config bug re-submits
        # the identical cached_not_done batch every time) is a stall too, not just an empty
        # cached_not_done list -- without this, the loop would resubmit the same non-empty batch
        # forever with NO sleep between attempts, leaking a fresh `build_batch_*.ids` file per
        # iteration. Reuses the same `idle_passes`/`max_idle` guard as the empty-cache stall above.
        n_done_after = _call_done_count(done_count, db_path, date_from, date_to, categories)
        if n_done_after <= n_done:
            idle_passes += 1
            if idle_passes >= max_idle:
                logger.info(
                    "build_corpus: stalled -- a batch of %d ran but made zero net progress "
                    "(%d/%d done) after %d consecutive idle pass(es) (max_idle=%d), giving up -- "
                    "check parse_workers/parse_batch_size aren't misconfigured",
                    len(ids), n_done_after, target, idle_passes, max_idle,
                )
                return
            logger.info(
                "build_corpus: batch of %d ran but made zero net progress (%d/%d done, idle "
                "pass %d/%d) -- waiting %.0fs before retrying",
                len(ids), n_done_after, target, idle_passes, max_idle, poll_interval_s,
            )
            sleep(poll_interval_s)
        else:
            idle_passes = 0


# --- CLI ------------------------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", type=int, required=True,
        help="stop once ingest_state has this many papers at stage='done'",
    )
    parser.add_argument("--parse-workers", type=int, default=1)
    parser.add_argument(
        "--events-path", default="build_events.jsonl",
        help="passed through to every app.ingest invocation this loop runs -- same events file "
             "across iterations, so the dashboard's funnel/telemetry stays cumulative across "
             "however many RUN_START/RUN_END segments a multi-batch build produces",
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="cap the number of cached-not-done ids fed to a single app.ingest invocation; "
             "default processes the whole current cache each iteration (fewer, bigger batches -- "
             "better GPU batching, model-load/TEI-restart overhead amortized)",
    )
    parser.add_argument(
        "--telemetry-poll-interval", type=float, default=None,
        help="forwarded to every app.ingest invocation this loop runs as its own "
             "--telemetry-poll-interval; default (unset) omits the flag, so app.ingest's own "
             "default (telemetry.DEFAULT_GPU_POLL_INTERVAL_SECONDS) applies unchanged",
    )
    return parser.parse_args(argv)


def _validate_cli_args(args: argparse.Namespace) -> None:
    """OG-49#3: defensive boundary check, mirroring `app.ingest`'s own `_validate_parse_workers`
    and `app/dashboard/server.py`'s `/api/control` validation -- `--parse-workers 0`/a negative
    `--batch-size` reaching THIS process (e.g. a manual invocation, bypassing the dashboard's own
    boundary check) must be rejected here too, not silently produce an infinite no-op loop."""
    if args.parse_workers < 1:
        print(
            f"app.build_corpus: --parse-workers must be >= 1, got {args.parse_workers}",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.batch_size is not None and args.batch_size < 1:
        print(
            f"app.build_corpus: --batch-size must be >= 1 (or unset), got {args.batch_size}",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    _validate_cli_args(args)
    cfg = load_config()
    # Matches `app.ingest`'s own convention: no explicit --data-dir flag, the process's cwd IS the
    # data dir (the dashboard controller launches both this way, `cwd=str(data_dir)`).
    data_dir = Path.cwd()

    build_to_target(
        data_dir, cfg.db_path, Path(cfg.pdf_cache_dir), args.target, args.parse_workers,
        Path(args.events_path), batch_size=args.batch_size,
        telemetry_poll_interval=args.telemetry_poll_interval,
        # OG-46: no CLI flag -- `ordering`/`focus_area_queries` are Config-derived, same channel
        # a dashboard-launched run's keyword/ordering edits already reach this process through
        # (app/dashboard/controller.py's run-scoped override config.yaml).
        ordering=cfg.ordering, focus_area_queries=cfg.focus_area_queries,
        # Same channel: a dashboard retarget's arxiv_date_from/date_to/arxiv_categories (OG-45)
        # land in this same override config.yaml -- previously read here only for the downloader,
        # never for the target check itself (done_count's docstring).
        date_from=cfg.arxiv_date_from, date_to=cfg.arxiv_date_to,
        categories=cfg.arxiv_categories,
    )


if __name__ == "__main__":
    main()
