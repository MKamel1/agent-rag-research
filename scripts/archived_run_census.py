"""RI-M1: census over archived prefetch run logs -- D-7/D-11 (`app/dashboard/controller.py`'s
`_archive_run_artifacts`) copy each run's `prefetch.log` and effective `config.yaml` out of its
scratch dir into `<data_dir>/prefetch_{run_id}.log` / `<data_dir>/config_{run_id}.yaml` on both
the `done` and `failed` manifest transitions, before the scratch dir is deleted. Those archives
have accumulated and nothing has ever read them back.

INSTRUMENT ONLY (docs/superpowers/plans/2026-08-22-review-implementation.md, wave 4): this module
counts what the archived files already contain. Running it over the operator's real data dir and
acting on the numbers is operator work -- neither this file nor its tests do that.

    python scripts/archived_run_census.py --data-dir waymo/data

What this CAN answer from the archive, per run: how it ended (reached its target, gave up after
`--max-idle` idle passes, or the log simply stops with no terminal line at all -- a crash or an
external kill, never distinguishable from each other here), how many re-harvest stalls it logged,
how many downloads failed permanently vs. exhausted their retry budget, and a coarse whole-run
wall-clock span (see `wall_clock_span_seconds`'s docstring for exactly how approximate that is).

What this CANNOT answer, and why (see `format_report`'s "not recoverable" section, always
printed, never silently omitted):

- **Per-stall duration and true download throughput.** `app/prefetch_pdfs.py`'s `main()` calls
  `logging.basicConfig(level=logging.INFO)` with no `format=`/`datefmt=`, so the default
  formatter (`"%(levelname)s:%(name)s:%(message)s"`) never writes a timestamp. Every fact this
  census extracts comes from message CONTENT and line ORDER, never from time. The stall interval
  and retry ceiling reported in the log text are the CONFIGURED constants
  (`_RE_HARVEST_INTERVAL_SECONDS`/`_MAX_DOWNLOAD_RETRIES` in `app/prefetch_pdfs.py`), logged
  verbatim on every occurrence -- so the log can show how often the ceiling was HIT, never the
  distribution of how long a real wait or a real retry actually took.
- **Resume boundaries within one archived log.** `_spawn_download` opens `prefetch.log` in
  append mode (`log_path.open("a")`), and a paused-then-resumed run keeps writing to the SAME
  file across separate process launches with no separator line between them. This census cannot
  tell a single long run from several resumed segments concatenated together -- multiple terminal
  markers in one file are reported as a count, not resolved into separate segments.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.census_common import rank_by_count  # noqa: E402

_CONFIG_NAME_RE = re.compile(r"^config_(.+)\.yaml$")
_LOG_NAME_RE = re.compile(r"^prefetch_(.+)\.log$")

# Message fragments below are matched verbatim against app/prefetch_pdfs.py's own logger.info/
# logger.warning call sites -- see that module for the source of truth. A future wording change
# there silently stops matching here rather than raising, which is why `format_report` always
# prints how many lines in each log went unrecognized (see `RunFindings.unmatched_lines`).
_PASS_COMPLETE_RE = re.compile(r"pass complete, \+(\d+) this pass, (\d+)/(\d+) cached")
_STALLED_RE = re.compile(r"prefetch stalled: (\d+)/(\d+) cached, only (\d+) new available")
_TARGET_UNREACHABLE_RE = re.compile(
    r"target unreachable -- only (\d+)/(\d+) papers available, stopping after (\d+) consecutive "
    r"idle pass\(es\) with no new downloads \(--max-idle=(\d+)\)"
)
_TARGET_REACHED_RE = re.compile(r"target of (\d+) reached, exiting\.")
_QUARANTINED_RE = re.compile(r"paper_id=\S+ permanently failed, quarantined locally:")
_RETRIES_EXHAUSTED_RE = re.compile(r"paper_id=\S+ gave up after (\d+) retries")
_HARVEST_COMPLETE_RE = re.compile(
    r"harvest phase complete: (\d+) candidate papers found, (\d+) already cached/claimed, "
    r"(\d+) to download"
)
# Recognized but not (yet) a census question -- included below only so a normal line doesn't
# inflate `unmatched_lines`.
_HARVEST_START_RE = re.compile(r"harvest phase start: \d+ focus quer(?:y|ies), harvest cap \d+")
_DOWNLOAD_PROGRESS_RE = re.compile(r"downloaded \d+ / target \d+ \(cache now \d+\)")

# Any recognized line matches one of these -- checked in `_classify_line` so an unmatched line
# (see module docstring) is "none of the above", not "silently miscounted as one of them".
_RECOGNIZED_LINE_RES = (
    _PASS_COMPLETE_RE, _STALLED_RE, _TARGET_UNREACHABLE_RE, _TARGET_REACHED_RE,
    _QUARANTINED_RE, _RETRIES_EXHAUSTED_RE, _HARVEST_COMPLETE_RE, _HARVEST_START_RE,
    _DOWNLOAD_PROGRESS_RE,
)

_TERMINAL_UNKNOWN = "unknown -- log ends with no terminal line (crash or external kill, or the "\
    "run is still in progress)"
_TERMINAL_REACHED = "reached its target"
_TERMINAL_MAX_IDLE = "gave up after --max-idle idle passes"


@dataclass
class RunFindings:
    """What a single archived run's log/config pair supports -- see the module docstring for the
    two questions this deliberately leaves unanswered and why."""

    run_id: str
    has_log: bool
    has_config: bool
    passes_seen: int = 0
    new_downloads: int = 0  # sum of "+N this pass" -- see `_parse_log` for why not "N cached"
    last_cached_total: int | None = None
    target: int | None = None
    stall_count: int = 0
    quarantined_permanent: int = 0
    retries_exhausted: int = 0
    terminal: str = _TERMINAL_UNKNOWN
    terminal_line_count: int = 0  # >1 => multiple resumed segments concatenated (see docstring)
    max_idle_configured: int | None = None  # only ever known if `terminal == _TERMINAL_MAX_IDLE`
    unmatched_lines: int = 0
    wall_clock_span_seconds: float | None = None
    span_note: str = ""


@dataclass
class ArchivedRunCensus:
    runs: dict[str, RunFindings]

    @property
    def log_only(self) -> list[str]:
        return sorted(r for r, f in self.runs.items() if f.has_log and not f.has_config)

    @property
    def config_only(self) -> list[str]:
        return sorted(r for r, f in self.runs.items() if f.has_config and not f.has_log)


# --------------------------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------------------------


def discover_archived_runs(data_dir: Path) -> dict[str, dict[str, Path]]:
    """Pairs `prefetch_{run_id}.log` / `config_{run_id}.yaml` files in `data_dir` by run_id.

    A run_id with only one of the two is real, not a scan bug: `_archive_run_artifacts`'s own
    docstring says "a missing source file is normal ... not an error" -- e.g. a run that
    quarantined every candidate before ever spawning `app.prefetch_pdfs` has a config but no log.
    """
    found: dict[str, dict[str, Path]] = {}
    for path in sorted(data_dir.iterdir()):
        if not path.is_file():
            continue
        if match := _LOG_NAME_RE.match(path.name):
            found.setdefault(match.group(1), {})["log"] = path
        elif match := _CONFIG_NAME_RE.match(path.name):
            found.setdefault(match.group(1), {})["config"] = path
    return found


# --------------------------------------------------------------------------------------------
# Per-run parsing
# --------------------------------------------------------------------------------------------


def _classify_line(line: str) -> bool:
    """True if `line` matched one of the known message shapes -- see `RunFindings.unmatched_lines`
    for why an unrecognized line is counted rather than ignored."""
    return any(pattern.search(line) for pattern in _RECOGNIZED_LINE_RES)


def _parse_log(text: str, findings: RunFindings) -> None:
    for line in text.splitlines():
        if match := _PASS_COMPLETE_RE.search(line):
            findings.passes_seen += 1
            findings.new_downloads += int(match.group(1))
            findings.last_cached_total = int(match.group(2))
            findings.target = int(match.group(3))
        elif match := _HARVEST_COMPLETE_RE.search(line):
            pass  # harvest-side counts (candidates/already-cached) -- not yet a census question
        elif _STALLED_RE.search(line):
            findings.stall_count += 1
        elif match := _TARGET_UNREACHABLE_RE.search(line):
            findings.terminal = _TERMINAL_MAX_IDLE
            findings.terminal_line_count += 1
            findings.max_idle_configured = int(match.group(4))
        elif _TARGET_REACHED_RE.search(line):
            findings.terminal = _TERMINAL_REACHED
            findings.terminal_line_count += 1
        elif _QUARANTINED_RE.search(line):
            findings.quarantined_permanent += 1
        elif _RETRIES_EXHAUSTED_RE.search(line):
            findings.retries_exhausted += 1
        elif line.strip() and not _classify_line(line):
            findings.unmatched_lines += 1


def _wall_clock_span(log_path: Path, config_path: Path) -> tuple[float | None, str]:
    """`config_{run_id}.yaml`'s mtime is (almost always) when the run's override config was first
    written -- once per run_id, reused verbatim across pause/resume (`_write_override_config_dir`)
    unless a reboot forced `_rebuild_missing_run_cwd` to rewrite it. `prefetch_{run_id}.log`'s
    mtime is `shutil.copy2`'s preserved copy of the LAST time the (possibly resumed, append-mode)
    source log was written -- i.e. close to when the run actually stopped.

    This is a real signal, not a guess, but it is NOT a precise run duration: it includes any
    paused wall-clock time between resumes, and undercounts nothing but can overcount by however
    long the run sat paused. Always returned with the hedge attached (`span_note`) rather than a
    bare number -- see the module docstring's "not recoverable" list for the sharper claim this
    does NOT make (true per-download throughput)."""
    span = log_path.stat().st_mtime - config_path.stat().st_mtime
    if span <= 0:
        return None, (
            "config file mtime is not earlier than the log's -- config was likely rewritten "
            "after the run started (e.g. _rebuild_missing_run_cwd after a reboot); span unusable"
        )
    return span, (
        "approximate: config-file mtime to log-file mtime, includes any paused wall-clock time"
    )


def census_one_run(run_id: str, paths: dict[str, Path]) -> RunFindings:
    findings = RunFindings(run_id=run_id, has_log="log" in paths, has_config="config" in paths)
    if findings.has_log:
        _parse_log(paths["log"].read_text(), findings)
    if findings.has_log and findings.has_config:
        span, note = _wall_clock_span(paths["log"], paths["config"])
        findings.wall_clock_span_seconds = span
        findings.span_note = note
    return findings


def build_census(data_dir: Path) -> ArchivedRunCensus:
    discovered = discover_archived_runs(data_dir)
    runs = {run_id: census_one_run(run_id, paths) for run_id, paths in discovered.items()}
    return ArchivedRunCensus(runs=runs)


# --------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------

_NOT_RECOVERABLE = (
    "- per-stall duration and true download throughput: not recoverable from the archive -- "
    "app/prefetch_pdfs.py's logging.basicConfig() carries no timestamp, so nothing here is a "
    "measured time, only a configured constant logged verbatim, or the coarse whole-run "
    "wall-clock span below (config-file mtime to log-file mtime).",
    "- resume boundaries within one archived log: not recoverable -- prefetch.log is opened in "
    "append mode across pause/resume with no separator line, so a run with more than one "
    "terminal marker is reported as a count, never split into its real segments.",
)


def format_report(census: ArchivedRunCensus) -> str:
    lines = [f"archived runs found: {len(census.runs)}"]
    if census.log_only:
        lines.append(f"  log with no config: {census.log_only}")
    if census.config_only:
        lines.append(f"  config with no log: {census.config_only}")

    terminal_counts: dict[str, int] = {}
    for findings in census.runs.values():
        if findings.has_log:
            terminal_counts[findings.terminal] = terminal_counts.get(findings.terminal, 0) + 1
    lines.append("how archived runs ended:")
    for terminal, count in rank_by_count(terminal_counts, n=len(terminal_counts)):
        lines.append(f"  {terminal}: {count}")

    stall_counts = {r: f.stall_count for r, f in census.runs.items()}
    quarantine_counts = {r: f.quarantined_permanent for r, f in census.runs.items()}
    retry_counts = {r: f.retries_exhausted for r, f in census.runs.items()}
    lines.append("top runs by stall count:")
    for run_id, count in rank_by_count(stall_counts):
        lines.append(f"  {run_id}: {count} stalls")
    lines.append("top runs by permanently-quarantined downloads:")
    for run_id, count in rank_by_count(quarantine_counts):
        lines.append(f"  {run_id}: {count}")
    lines.append("top runs by retry-budget-exhausted downloads:")
    for run_id, count in rank_by_count(retry_counts):
        lines.append(f"  {run_id}: {count}")

    spans = {
        r: f.wall_clock_span_seconds for r, f in census.runs.items()
        if f.wall_clock_span_seconds is not None
    }
    if spans:
        lines.append("wall-clock span (approximate -- see module docstring):")
        for run_id, span in spans.items():
            downloads = census.runs[run_id].new_downloads
            rate = f", {downloads / (span / 3600):.1f} downloads/hour" if span > 0 else ""
            lines.append(f"  {run_id}: {span:.0f}s{rate}")

    unmatched = {r: f.unmatched_lines for r, f in census.runs.items()}
    total_unmatched = sum(unmatched.values())
    lines.append(f"unrecognized log lines (message wording may have drifted): {total_unmatched}")
    if total_unmatched:
        for run_id, count in rank_by_count(unmatched):
            lines.append(f"  {run_id}: {count}")

    lines.append("")
    lines.append("NOT recoverable from this archive:")
    lines.extend(_NOT_RECOVERABLE)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, help="corpus data dir holding the archives")
    args = parser.parse_args(argv)

    census = build_census(Path(args.data_dir))
    print(format_report(census))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
