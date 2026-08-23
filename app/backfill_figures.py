# RI-32 — figures/tables backfill tool: re-parse already-ingested papers' cached PDFs through the
# parse adapter and persist ONLY their Figure/TableItem rows, leaving every other table alone
# (the write path itself is engine-enforced figures/tables-only -- see
# rag/document_store.py::put_figures_and_tables). Zero network at import time; the parser seam is
# an injected callable so tests run without the real PDF pipeline.
"""`python -m app.backfill_figures` — backfill `figures`/`tables` rows for an already-built corpus.

RI-18 made the parser extract Figure/TableItem artifacts and migration 0006 gave them tables, but
every corpus ingested before that discarded them at the storage boundary — so existing corpora have
zero figure/table rows and the only recovery is re-parsing each paper's cached PDF. This tool does
exactly that, one paper at a time, with the narrowest write surface that can do the job:

- WHY NOT `put()`: a full `DocumentStore.put()` deletes and reinserts the paper's blocks/chunks/
  summaries row sets and rewrites its `papers` row; the orchestrator keeps the vector index in sync
  with those tables only at ingest time, so a backfill through `put()` would strand vectors to add
  data that lives in two entirely different tables. `put_figures_and_tables` writes three statement
  kinds scoped to one `paper_id`, and a connection authorizer makes anything wider fail loudly
  inside SQLite instead of trusting this tool to stay careful.
- DONE-MARKERS, not row-presence: "already backfilled" is derived from a `<paper_id>.done` marker
  file under `--markers-dir`, NOT from the paper having figure rows — a paper whose re-parse
  legitimately yields zero artifacts would otherwise be re-parsed by every future resume forever.
  Markers are written AFTER `put_figures_and_tables` commits, so every crash window converges: a
  kill mid-write rolls back with no marker (next run re-parses and replaces), a kill between commit
  and marker costs one redundant parse whose replace is idempotent. A failed parse writes no marker,
  so it is retried naturally by the next run rather than dead-lettered here.
- PER-PAPER FAILURE ISOLATION: any exception from parse or persist is recorded as a `failed`
  outcome and the run continues — a corpus-wide backfill must not lose six hours of remaining work
  to one unparseable PDF. The catch is deliberately broad (`Exception`, named) because the point is
  survivability; the error text lands in the outcome and the log for triage.
- DETACHED-RUN SAFETY: progress goes through `logging` (one flushed, timestamped line per record —
  RI-17), a heartbeat thread logs "still working" every `_HEARTBEAT_SECONDS` so an operator can
  tell a slow paper from a wedged parse, and resume-after-kill is exactly restart-the-command:
  markers make completed work free to skip. Assume the process WILL be killed mid-run; nothing
  above depends on it exiting cleanly.
- `--limit N` counts only papers this run actually processed or would process (`backfilled`/
  `would_backfill`) — skips must not consume a trial budget. `--dry-run` classifies every paper
  (would_backfill / skipped_done / skipped_no_cache) without calling the parser once, writing a
  row, or creating a marker — it exists to price a run before burning GPU-hours on it.

Read-only on everything except `figures`/`tables` and the marker directory. The database path is a
command-line argument, never hardcoded: this runs against whichever corpus's config points at it.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from contracts.parser import ParsedDoc
from rag.atomic_write import atomic_write
from rag.document_store import DocumentStore, table_fingerprints

__all__ = [
    "PROTECTED_TABLES",
    "BackfillOutcome",
    "run_backfill",
    "table_fingerprints",
]

logger = logging.getLogger(__name__)

# The tables RI-32's safety property names: a backfill run must leave these byte-identical (content
# hashes via table_fingerprints, not just row counts). Kept here rather than imported from
# document_store.py because the property is THIS tool's contract, and the store module should not
# grow tool-specific vocabulary.
PROTECTED_TABLES = ("papers", "blocks", "chunks", "summaries")

# Outcome statuses. Strings, not an enum: they appear verbatim in operator-facing logs and were
# pinned as plain strings by app/test_backfill_figures.py before this module existed.
STATUS_BACKFILLED = "backfilled"
STATUS_SKIPPED_DONE = "skipped_done"
STATUS_FAILED = "failed"
STATUS_SKIPPED_NO_CACHE = "skipped_no_cache"
STATUS_WOULD_BACKFILL = "would_backfill"

# Heartbeat cadence for detached runs: frequent enough that "no output for N minutes" means wedged
# rather than working, sparse enough not to drown the per-paper lines over a multi-hour run.
_HEARTBEAT_SECONDS = 300.0

_DEFAULT_LOG_EVERY = 10


@dataclass(frozen=True)
class BackfillOutcome:
    """One paper's result. `figures`/`tables` are the row counts written for `backfilled` outcomes;
    `error` carries `"<ErrorType>: <message>"` for `failed` ones."""

    paper_id: str
    status: str
    figures: int = 0
    tables: int = 0
    error: str | None = None


def _marker_path(markers_dir: Path, paper_id: str) -> Path:
    return markers_dir / f"{paper_id}.done"


class _Heartbeat:
    """Background thread logging a periodic "still alive" line for detached runs.

    A single parse can legitimately take tens of seconds and a wedged one can take forever; with
    only per-paper completion lines, an operator tailing a log cannot distinguish the two until
    they've wasted hours. The heartbeat labels each interval with the paper currently being worked
    on (or "(between papers)"). Daemon thread + event-based shutdown, so it can never outlive or
    block the run; a momentarily stale label across a paper boundary is harmless in a log line.
    """

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._current: str | None = None
        self._started_at = time.monotonic()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="backfill-heartbeat", daemon=True)
        self._thread.start()

    def set_current(self, paper_id: str) -> None:
        self._current = paper_id

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            logger.info(
                "backfill heartbeat: working on %s (%.0fs elapsed)",
                self._current or "(between papers)", time.monotonic() - self._started_at,
            )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)


def run_backfill(
    store: DocumentStore,
    parser: Callable[[bytes, str], ParsedDoc],
    cache_dir: str | Path,
    markers_dir: str | Path,
    paper_ids: Sequence[str],
    limit: int | None = None,
    dry_run: bool = False,
    log_every: int = _DEFAULT_LOG_EVERY,
) -> list[BackfillOutcome]:
    """Backfill figures/tables for `paper_ids`, skipping work already done. Returns one outcome per
    paper actually classified (a `--limit` cut short leaves the tail unclassified).

    Order of gates per paper — cheap and side-effect-free first:
      1. done-marker present -> skipped_done (resume/idempotency: never re-parsed);
      2. cached PDF absent -> skipped_no_cache (nothing to parse FROM; the cache is the source of
         the raw bytes, populated by the prefetcher at ingest time — this tool never downloads);
      3. dry_run -> would_backfill (classification only);
      4. parse + put_figures_and_tables + marker -> backfilled, or any exception -> failed.

    `limit` bounds gate-3/gate-4 papers only, so a trial budget isn't eaten by skips. `dry_run`
    never reaches gate 4: no parser call, no rows, no markers.
    """
    cache_dir = Path(cache_dir)
    markers_dir = Path(markers_dir)
    # atomic_write's O_CREAT|O_EXCL temp file needs its parent to exist; the ingest layout this
    # tool reuses (<blob-dir>/figures) may not have been created yet on a first-ever backfill.
    markers_dir.mkdir(parents=True, exist_ok=True)
    outcomes: list[BackfillOutcome] = []
    durations: list[float] = []
    eligible_done = 0
    heartbeat = _Heartbeat(_HEARTBEAT_SECONDS)
    if not dry_run:
        # Dry-run classification is instant; a heartbeat would be pure noise there.
        heartbeat.start()
    try:
        for position, paper_id in enumerate(paper_ids):
            if limit is not None and eligible_done >= limit:
                break

            if _marker_path(markers_dir, paper_id).exists():
                outcomes.append(BackfillOutcome(paper_id, STATUS_SKIPPED_DONE))
                continue

            pdf_path = cache_dir / f"{paper_id}.pdf"
            if not pdf_path.exists():
                logger.warning("backfill: %s has no cached PDF at %s, skipping", paper_id, pdf_path)
                outcomes.append(BackfillOutcome(paper_id, STATUS_SKIPPED_NO_CACHE))
                continue

            if dry_run:
                outcomes.append(BackfillOutcome(paper_id, STATUS_WOULD_BACKFILL))
                eligible_done += 1
                continue

            started = time.monotonic()
            heartbeat.set_current(paper_id)
            try:
                doc = parser(pdf_path.read_bytes(), paper_id)
                store.put_figures_and_tables(paper_id, doc.figures, doc.tables)
            except Exception as error:  # noqa: BLE001 -- one bad paper must not kill the run
                # Broad BY DESIGN (see module docstring); the type name keeps triage possible from
                # the outcome alone. No marker -> the next run retries this paper naturally.
                message = f"{type(error).__name__}: {error}"
                logger.warning("backfill: %s FAILED, continuing: %s", paper_id, message)
                outcomes.append(
                    BackfillOutcome(paper_id, STATUS_FAILED, error=message),
                )
                continue

            atomic_write(
                _marker_path(markers_dir, paper_id),
                f"figures={len(doc.figures)} tables={len(doc.tables)}\n",
            )
            duration = time.monotonic() - started
            durations.append(duration)
            eligible_done += 1
            outcomes.append(
                BackfillOutcome(
                    paper_id, STATUS_BACKFILLED,
                    figures=len(doc.figures), tables=len(doc.tables),
                ),
            )
            if eligible_done % log_every == 0:
                mean_s = sum(durations) / len(durations)
                remaining_bound = len(paper_ids) - position - 1
                logger.info(
                    "backfill progress: %d parsed, %d/%d papers examined, %.1fs/paper mean, "
                    "ETA <= %.1fh if every remaining paper needs parsing",
                    eligible_done, position + 1, len(paper_ids), mean_s,
                    mean_s * remaining_bound / 3600.0,
                )
    finally:
        heartbeat.stop()

    return outcomes


def _done_paper_ids(db_path: str) -> list[str]:
    """Papers fully ingested (`ingest_state.stage='done'`), deterministically ordered so a
    `--limit` trial is reproducible and sharded/resumed runs see the same sequence. Read-only
    connection: enumeration must never migrate or lock the target database."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT paper_id FROM ingest_state WHERE stage = 'done' ORDER BY paper_id",
        ).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", required=True, help="corpus papers.db (never hardcoded)")
    parser.add_argument("--blob-dir", required=True, help="the corpus's blob directory (as configured)")
    parser.add_argument("--cache-dir", required=True, help="directory holding <paper_id>.pdf cache entries")
    parser.add_argument(
        "--markers-dir", default=None,
        help="done-marker directory (default: <blob-dir>/figures, matching the ingest layout)",
    )
    parser.add_argument(
        "--paper-ids-file", default=None,
        help="one paper_id per line; default enumerates ingest_state.stage='done' from --db",
    )
    parser.add_argument("--limit", type=int, default=None, metavar="N", help="stop after N eligible papers")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="classify only -- no parser calls, no writes, no markers",
    )
    parser.add_argument(
        "--log-every", type=int, default=_DEFAULT_LOG_EVERY, metavar="N",
        help=f"log a rate/ETA progress line every N parsed papers (default {_DEFAULT_LOG_EVERY})",
    )
    return parser.parse_args(argv)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args()
    markers_dir = (
        Path(args.markers_dir) if args.markers_dir else Path(args.blob_dir) / "figures"
    )

    if args.paper_ids_file:
        paper_ids = [
            line.strip()
            for line in Path(args.paper_ids_file).read_text().splitlines()
            if line.strip()
        ]
        source = f"--paper-ids-file {args.paper_ids_file}"
    else:
        paper_ids = _done_paper_ids(args.db)
        source = "ingest_state stage='done'"

    logger.info(
        "backfill start: %d candidate paper(s) from %s, db=%s, cache=%s, markers=%s, "
        "limit=%s, dry_run=%s",
        len(paper_ids), source, args.db, args.cache_dir, markers_dir, args.limit, args.dry_run,
    )

    store = DocumentStore(db_path=args.db, blob_dir=args.blob_dir)
    started = time.monotonic()
    outcomes = run_backfill(
        store,
        _default_parse,
        cache_dir=args.cache_dir,
        markers_dir=markers_dir,
        paper_ids=paper_ids,
        limit=args.limit,
        dry_run=args.dry_run,
        log_every=args.log_every,
    )

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    elapsed = time.monotonic() - started
    rate = ""
    if counts.get(STATUS_BACKFILLED, 0) > 0:
        rate = f", {elapsed / counts[STATUS_BACKFILLED]:.1f}s/paper observed"
    logger.info(
        "backfill done: %d outcome(s) in %.1fs -- %s%s",
        len(outcomes), elapsed,
        ", ".join(f"{status}={n}" for status, n in sorted(counts.items())) or "nothing to do",
        rate,
    )


def _default_parse(raw: bytes, paper_id: str) -> ParsedDoc:
    # Imported lazily so `--help`/unit tests never pay for the PDF pipeline's own imports.
    from rag.parser import parse

    return parse(raw, paper_id)


if __name__ == "__main__":
    main()
