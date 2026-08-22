"""Tests for scripts/archived_run_census.py (RI-M1) -- fixture archives built to match the real
message templates in app/prefetch_pdfs.py, not real corpus/operator data (this instrument is
proved on fixtures; running it against a real data dir is operator work)."""

import os
import time

from scripts.archived_run_census import (
    _TERMINAL_MAX_IDLE,
    _TERMINAL_REACHED,
    _TERMINAL_UNKNOWN,
    RunFindings,
    _parse_log,
    build_census,
    discover_archived_runs,
    format_report,
)

# Real default logging.basicConfig() format ("%(levelname)s:%(name)s:%(message)s") -- the census
# regexes use `.search`, so this prefix is incidental, but including it keeps the fixture honest
# about what app/prefetch_pdfs.py's archived log actually looks like.
_PREFIX = "INFO:app.prefetch_pdfs:"


def _line(text: str) -> str:
    return f"{_PREFIX}{text}"


# --------------------------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------------------------


def test_discover_pairs_log_and_config_by_run_id(tmp_path):
    (tmp_path / "prefetch_run-1.log").write_text("")
    (tmp_path / "config_run-1.yaml").write_text("")
    (tmp_path / "prefetch_run-2.log").write_text("")

    found = discover_archived_runs(tmp_path)

    assert set(found["run-1"]) == {"log", "config"}
    assert set(found["run-2"]) == {"log"}


def test_discover_ignores_unrelated_files(tmp_path):
    (tmp_path / "papers.db").write_text("")
    (tmp_path / "run_manifest.json").write_text("{}")

    assert discover_archived_runs(tmp_path) == {}


def test_census_reports_config_only_and_log_only_runs(tmp_path):
    (tmp_path / "prefetch_orphan-log.log").write_text(_line("prefetch_pdfs: pass complete, "
                                                              "+1 this pass, 1/10 cached\n"))
    (tmp_path / "config_orphan-config.yaml").write_text("prefetch_target: 10\n")

    census = build_census(tmp_path)

    assert census.log_only == ["orphan-log"]
    assert census.config_only == ["orphan-config"]


# --------------------------------------------------------------------------------------------
# Log parsing: stalls, quarantines, retries, terminal state
# --------------------------------------------------------------------------------------------


def test_parse_log_counts_stalls_quarantines_retries_and_downloads():
    log_text = "\n".join([
        _line("prefetch_pdfs: harvest phase start: 3 focus queries, harvest cap 13000"),
        _line("prefetch_pdfs: harvest phase complete: 40 candidate papers found, "
              "35 already cached/claimed, 5 to download"),
        _line("prefetch_pdfs: paper_id=2506.00001 permanently failed, quarantined locally: "
              "404 Not Found"),
        _line("prefetch_pdfs: paper_id=2506.00002 gave up after 3 retries (will retry on a "
              "later pass): timeout"),
        _line("prefetch_pdfs: downloaded 25 / target 13000 (cache now 360)"),
        _line("prefetch_pdfs: pass complete, +3 this pass, 363/13000 cached"),
        _line("prefetch_pdfs: prefetch stalled: 363/13000 cached, only 0 new available, next "
              "attempt in 3600s"),
    ])
    findings = RunFindings(run_id="r", has_log=True, has_config=False)

    _parse_log(log_text, findings)

    assert findings.passes_seen == 1
    assert findings.new_downloads == 3
    assert findings.last_cached_total == 363
    assert findings.target == 13000
    assert findings.stall_count == 1
    assert findings.quarantined_permanent == 1
    assert findings.retries_exhausted == 1
    assert findings.terminal == _TERMINAL_UNKNOWN  # no terminal line in this excerpt
    assert findings.unmatched_lines == 0


def test_terminal_reached():
    log_text = _line("prefetch_pdfs: target of 13000 reached, exiting.")
    findings = RunFindings(run_id="r", has_log=True, has_config=False)

    _parse_log(log_text, findings)

    assert findings.terminal == _TERMINAL_REACHED
    assert findings.terminal_line_count == 1


def test_terminal_max_idle_captures_the_configured_bound():
    log_text = _line(
        "prefetch_pdfs: target unreachable -- only 340/13000 papers available, stopping after "
        "5 consecutive idle pass(es) with no new downloads (--max-idle=5)"
    )
    findings = RunFindings(run_id="r", has_log=True, has_config=False)

    _parse_log(log_text, findings)

    assert findings.terminal == _TERMINAL_MAX_IDLE
    assert findings.max_idle_configured == 5


def test_terminal_unknown_means_no_terminal_line_at_all():
    # e.g. a killed/crashed process: the log just stops mid-pass.
    log_text = _line("prefetch_pdfs: pass complete, +2 this pass, 40/13000 cached")
    findings = RunFindings(run_id="r", has_log=True, has_config=False)

    _parse_log(log_text, findings)

    assert findings.terminal == _TERMINAL_UNKNOWN
    assert findings.terminal_line_count == 0


def test_unmatched_lines_counts_only_genuinely_unrecognized_text():
    log_text = "\n".join([
        _line("prefetch_pdfs: pass complete, +1 this pass, 2/10 cached"),
        _line("some future log line this census has never seen before"),
    ])
    findings = RunFindings(run_id="r", has_log=True, has_config=False)

    _parse_log(log_text, findings)

    assert findings.unmatched_lines == 1


# --------------------------------------------------------------------------------------------
# Wall-clock span (mtime-derived, always hedged)
# --------------------------------------------------------------------------------------------


def test_wall_clock_span_uses_config_then_log_mtime(tmp_path):
    config_path = tmp_path / "config_run-1.yaml"
    log_path = tmp_path / "prefetch_run-1.log"
    config_path.write_text("prefetch_target: 10\n")
    log_path.write_text(_line("prefetch_pdfs: target of 10 reached, exiting.\n"))

    now = time.time()
    os.utime(config_path, (now, now))
    os.utime(log_path, (now + 120, now + 120))

    census = build_census(tmp_path)

    findings = census.runs["run-1"]
    assert findings.wall_clock_span_seconds is not None
    assert 119 <= findings.wall_clock_span_seconds <= 121
    assert "approximate" in findings.span_note


def test_wall_clock_span_flags_a_rewritten_config_as_unusable(tmp_path):
    config_path = tmp_path / "config_run-1.yaml"
    log_path = tmp_path / "prefetch_run-1.log"
    log_path.write_text(_line("prefetch_pdfs: target of 10 reached, exiting.\n"))
    config_path.write_text("prefetch_target: 10\n")  # written AFTER the log -- config newer

    now = time.time()
    os.utime(log_path, (now, now))
    os.utime(config_path, (now + 60, now + 60))

    census = build_census(tmp_path)

    findings = census.runs["run-1"]
    assert findings.wall_clock_span_seconds is None
    assert "rewritten" in findings.span_note or "unusable" in findings.span_note


# --------------------------------------------------------------------------------------------
# Report: honesty section always present
# --------------------------------------------------------------------------------------------


def test_format_report_always_states_what_is_not_recoverable(tmp_path):
    (tmp_path / "prefetch_run-1.log").write_text(
        _line("prefetch_pdfs: target of 10 reached, exiting.\n")
    )
    (tmp_path / "config_run-1.yaml").write_text("prefetch_target: 10\n")

    report = format_report(build_census(tmp_path))

    assert "NOT recoverable from this archive" in report
    assert "timestamp" in report


def test_format_report_ranks_runs_by_stall_count(tmp_path):
    for run_id, stalls in (("quiet", 0), ("loud", 3)):
        text = "\n".join(
            [_line("prefetch_pdfs: prefetch stalled: 1/10 cached, only 0 new available, next "
                    "attempt in 3600s")] * stalls
        )
        (tmp_path / f"prefetch_{run_id}.log").write_text(text)
        (tmp_path / f"config_{run_id}.yaml").write_text("prefetch_target: 10\n")

    report = format_report(build_census(tmp_path))

    assert "loud: 3 stalls" in report
    assert "quiet" not in report.split("top runs by stall count:")[1].split("top runs by "
                                                                             "permanently")[0]
