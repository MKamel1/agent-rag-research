"""Tests for `app.dashboard.verify_numbers` -- every ground truth here is recomputed straight from
a scratch `tmp_path` corpus (SQLite, filesystem), never by calling `status.py`'s own readers, so a
bug shared between the dashboard and its check cannot hide. Every test uses `tmp_path` -- never the
real data dir."""

import json
import sqlite3
import subprocess

import app.dashboard.verify_numbers as verify_numbers
from migrations.migrate import migrate


def _make_scratch_corpus(tmp_path, **stage_counts):
    """Migrates a fresh `papers.db` at `tmp_path` and inserts `n` distinct `ingest_state` rows at
    each `stage=n` kwarg (e.g. `_make_scratch_corpus(tmp_path, done=5, chunked=2)`)."""
    db_path = tmp_path / "papers.db"
    migrate(str(db_path))
    conn = sqlite3.connect(str(db_path))
    i = 0
    for stage, n in stage_counts.items():
        for _ in range(n):
            conn.execute(
                "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, ?)",
                (f"p{i}", stage, "2026-01-01T00:00:00"),
            )
            i += 1
    conn.commit()
    conn.close()


def _add_rows(tmp_path, stage, n, start_at=1000):
    conn = sqlite3.connect(str(tmp_path / "papers.db"))
    for i in range(n):
        conn.execute(
            "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, ?)",
            (f"new{start_at + i}", stage, "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()


def _status_for(**funnel_overrides):
    funnel = {
        "harvested": 7, "parsed": 7, "chunked": 7, "summarized": 5, "embedded": 5, "stored": 5,
        "done": 5, "quarantined": 0,
    }
    funnel.update(funnel_overrides)
    return {"funnel": funnel}


# --- funnel: matches, wrong value, and the frozen-value (stale) failure mode --------------------


def test_verify_reports_no_discrepancies_when_dashboard_matches_ground_truth(tmp_path):
    _make_scratch_corpus(tmp_path, done=5, chunked=2)
    status = _status_for()
    assert verify_numbers.verify(tmp_path, status) == []


def test_verify_catches_a_wrong_funnel_number(tmp_path):
    _make_scratch_corpus(tmp_path, done=5, chunked=2)
    status = _status_for(done=999)
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "funnel.done" and x.ground_truth == 5 for x in d)


def test_verify_catches_a_stale_number_that_did_not_track_a_change(tmp_path):
    """The frozen-value failure mode: the dashboard reported a number that WAS right before the
    corpus changed and is wrong now."""
    _make_scratch_corpus(tmp_path, done=5)
    status = _status_for(
        harvested=5, parsed=5, chunked=5, summarized=5, embedded=5, stored=5, done=5,
    )
    assert verify_numbers.verify(tmp_path, status) == []
    _add_rows(tmp_path, "done", 3)
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "funnel.done" and x.ground_truth == 8 for x in d)


def test_verify_funnel_is_cumulative_not_per_stage(tmp_path):
    """Moving a row chunked -> done increases `done` by 1 while the CUMULATIVE `chunked` figure
    (chunked-or-later) stays the same -- the subtlest case in the ground-truth table."""
    _make_scratch_corpus(tmp_path, done=5, chunked=2)
    status = _status_for(chunked=7, done=5)  # cumulative: chunked-or-later = 7, done = 5
    assert verify_numbers.verify(tmp_path, status) == []

    # Move one row from chunked to done.
    conn = sqlite3.connect(str(tmp_path / "papers.db"))
    conn.execute(
        "UPDATE ingest_state SET stage='done' WHERE paper_id = "
        "(SELECT paper_id FROM ingest_state WHERE stage='chunked' LIMIT 1)"
    )
    conn.commit()
    conn.close()

    # A stale dashboard (still reporting the old done=5) must be caught...
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "funnel.done" and x.ground_truth == 6 for x in d)
    assert not any(x.field == "funnel.chunked" for x in d)  # chunked-or-later is unchanged

    # ...and a dashboard that correctly tracked the move (done/stored/embedded/summarized +1 each,
    # chunked-or-later unchanged) passes clean.
    status_after = _status_for(summarized=6, embedded=6, stored=6, done=6)
    assert verify_numbers.verify(tmp_path, status_after) == []


def test_verify_quarantine_excludes_papers_that_later_succeeded(tmp_path):
    _make_scratch_corpus(tmp_path, done=1)
    migrate(str(tmp_path / "papers.db"))  # no-op re-run, keeps this test self-contained
    conn = sqlite3.connect(str(tmp_path / "papers.db"))
    conn.execute(
        "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES ('p0', 'parsed', 'boom', ?)",
        ("2026-01-01T00:00:00",),
    )  # p0 is quarantined but ALSO already 'done' -- OG-44: must not count as stuck
    conn.execute(
        "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES ('pQ', 'parsed', 'boom', ?)",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()
    assert verify_numbers.verify(tmp_path, {"funnel": {"quarantined": 1}}) == []
    d = verify_numbers.verify(tmp_path, {"funnel": {"quarantined": 2}})
    assert any(x.field == "funnel.quarantined" and x.ground_truth == 1 for x in d)


# --- by_doc_type -------------------------------------------------------------------------------


def _insert_paper(conn, paper_id, doc_type):
    conn.execute(
        "INSERT INTO papers (paper_id, version, title, abstract, authors_json, categories_json, "
        "published, updated, pdf_path, markdown_path, doc_type) VALUES "
        "(?, 'v1', 't', 'a', '[]', '[]', '2026-01-01', '2026-01-01', 'p.pdf', 'p.md', ?)",
        (paper_id, doc_type),
    )


def test_verify_by_doc_type_catches_a_wrong_book_funnel(tmp_path):
    _make_scratch_corpus(tmp_path)
    conn = sqlite3.connect(str(tmp_path / "papers.db"))
    _insert_paper(conn, "b0", "book")
    conn.execute("INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES ('b0', 'done', ?)",
                 ("2026-01-01T00:00:00",))
    conn.commit()
    conn.close()
    status = {
        "by_doc_type": {
            "book": {"harvested": 1, "parsed": 1, "chunked": 1, "summarized": 1, "embedded": 1,
                      "stored": 1, "done": 99, "quarantined": 0},
        },
    }
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "by_doc_type.book.done" and x.ground_truth == 1 for x in d)


# --- the D-6 orphan-check bug: a run's own child is not an orphan -------------------------------


def test_verify_flags_an_orphan_only_when_the_pid_is_not_a_descendant_of_the_run(tmp_path):
    """The live 2026-08-01 false positive: build_corpus legitimately spawns prefetch_pdfs as a
    child during a `full` run, and it was reported as an orphan."""
    status = {"downloader": {"live_pids": [222], "orphan": True}}
    d = verify_numbers.verify(
        tmp_path, status, _pid_parent=lambda p: 111 if p == 222 else None, _manifest_pid=111,
    )
    assert any(x.field == "downloader.orphan" for x in d)


def test_verify_does_not_flag_a_correctly_reported_child_as_a_discrepancy(tmp_path):
    status = {"downloader": {"live_pids": [222], "orphan": False}}
    d = verify_numbers.verify(
        tmp_path, status, _pid_parent=lambda p: 111 if p == 222 else None, _manifest_pid=111,
    )
    assert not any(x.field == "downloader.orphan" for x in d)


def test_verify_flags_a_true_orphan(tmp_path):
    """The real 20-hour case D-6 was built for: a live pid whose parent chain never reaches the
    manifest pid must still be caught."""
    status = {"downloader": {"live_pids": [222], "orphan": False}}
    d = verify_numbers.verify(
        tmp_path, status, _pid_parent=lambda p: 1 if p == 222 else None, _manifest_pid=111,
    )
    assert any(x.field == "downloader.orphan" and x.ground_truth is True for x in d)


# --- D-12: the pgrep ground truth must not share status.py's old loose predicate ----------------


def test_live_prefetch_pids_via_pgrep_rejects_a_pgrep_only_match(monkeypatch):
    """D-12: `pgrep -f app.prefetch_pdfs` alone -- the exact predicate `status.py` used to have --
    would count a diagnostic `pgrep -af "app.prefetch_pdfs"` process just for naming the pattern.
    Inject that candidate (pgrep surfaces it, but it is neither a python `exe` nor has an
    `-m`-adjacent argv -- exactly what such a process structurally looks like) and confirm the new
    ground truth rejects it: a bug shared with status.py's old substring check can no longer make
    both sides agree."""
    fake_result = subprocess.CompletedProcess(
        args=["pgrep", "-f", "app.prefetch_pdfs"], returncode=0, stdout="999901\n", stderr="",
    )
    monkeypatch.setattr(verify_numbers.subprocess, "run", lambda *a, **k: fake_result)
    monkeypatch.setattr(verify_numbers, "_exe_is_python", lambda pid: False)
    monkeypatch.setattr(verify_numbers, "_has_prefetch_module_flag", lambda pid: True)

    assert verify_numbers._live_prefetch_pids_via_pgrep() == []


def test_live_prefetch_pids_via_pgrep_accepts_a_structurally_real_downloader(monkeypatch):
    fake_result = subprocess.CompletedProcess(
        args=["pgrep", "-f", "app.prefetch_pdfs"], returncode=0, stdout="999902\n", stderr="",
    )
    monkeypatch.setattr(verify_numbers.subprocess, "run", lambda *a, **k: fake_result)
    monkeypatch.setattr(verify_numbers, "_exe_is_python", lambda pid: True)
    monkeypatch.setattr(verify_numbers, "_has_prefetch_module_flag", lambda pid: True)

    assert verify_numbers._live_prefetch_pids_via_pgrep() == [999902]


# --- downloads (pdf_cache/, config.yaml) ---------------------------------------------------------


def test_verify_catches_a_wrong_staged_pdf_count(tmp_path):
    cache = tmp_path / "pdf_cache"
    cache.mkdir()
    (cache / "a.pdf").write_bytes(b"")
    (cache / "b.pdf").write_bytes(b"")
    (cache / "a.json").write_text("{}")
    status = {"downloads": {"staged_pdfs": 999, "sidecars": 1}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "downloads.staged_pdfs" and x.ground_truth == 2 for x in d)
    assert not any(x.field == "downloads.sidecars" for x in d)


def test_verify_catches_a_wrong_prefetch_target(tmp_path):
    (tmp_path / "config.yaml").write_text("focus_area_queries: [x]\nprefetch_target: 12345\n")
    status = {"downloads": {"prefetch_target": 1}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "downloads.prefetch_target" and x.ground_truth == 12345 for x in d)


# --- tags (tag_pool.json) -------------------------------------------------------------------------


def test_verify_catches_wrong_tag_counts(tmp_path):
    (tmp_path / "tag_pool.json").write_text(json.dumps({"active": ["a", "b"], "held": ["c"]}))
    status = {"tags": {"active_count": 1, "held_count": 1}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "tags.active_count" and x.ground_truth == 2 for x in d)
    assert not any(x.field == "tags.held_count" for x in d)


def test_verify_tags_absent_pool_yields_no_discrepancy(tmp_path):
    status = {"tags": {"active_count": 5, "held_count": 0}}
    assert verify_numbers.verify(tmp_path, status) == []


# --- drop_in tray -------------------------------------------------------------------------------


def test_verify_catches_wrong_drop_in_pending_count(tmp_path):
    drop_dir = tmp_path / "drop_in"
    (drop_dir / "papers").mkdir(parents=True)
    (drop_dir / "papers" / "x.pdf").write_bytes(b"")
    status = {"drop_in": {"dir": str(drop_dir), "pending_papers": 0}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "drop_in.pending_papers" and x.ground_truth == 1 for x in d)


def test_verify_drop_in_processed_excludes_staging_from_processing(tmp_path):
    """`staged` (in done/) is NOT `processed` (reached stage='done' in the corpus) -- the
    distinction the whole drop-in feature exists for."""
    db_path = tmp_path / "papers.db"
    migrate(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES ('m0', 'chunked', ?)",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()

    drop_dir = tmp_path / "drop_in"
    drop_dir.mkdir()
    (drop_dir / "manifest-1.txt").write_text("m0\n")
    status = {"drop_in": {"dir": str(drop_dir), "processed": 1}}  # dashboard wrongly says processed
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "drop_in.processed" and x.ground_truth == 0 for x in d)


# --- O-1: run.outcome, against a ground truth read straight from run_outcome_<run_id>.json ------


def _write_manifest(tmp_path, run_id):
    (tmp_path / "run_manifest.json").write_text(json.dumps({"run_id": run_id, "pid": 12345}))


def test_verify_run_reports_no_discrepancy_when_outcome_matches(tmp_path):
    _write_manifest(tmp_path, "run-1")
    (tmp_path / "run_outcome_run-1.json").write_text(json.dumps({
        "run_id": "run-1", "outcome": "supply_exhausted",
    }))
    status = {"run": {"outcome": "supply_exhausted"}}
    assert verify_numbers.verify(tmp_path, status) == []


def test_verify_run_catches_a_dashboard_outcome_not_backed_by_a_file(tmp_path):
    """The dashboard says supply_exhausted but no outcome file exists on disk at all -- a real
    discrepancy, not absence-is-not-disagreement (the field IS present in the payload)."""
    _write_manifest(tmp_path, "run-1")
    status = {"run": {"outcome": "supply_exhausted"}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "run.outcome" and x.ground_truth is None for x in d)


def test_verify_run_catches_a_missed_supply_exhausted_outcome(tmp_path):
    """The reverse direction: the outcome file on disk says supply_exhausted but the dashboard
    reported None -- also a discrepancy."""
    _write_manifest(tmp_path, "run-1")
    (tmp_path / "run_outcome_run-1.json").write_text(json.dumps({
        "run_id": "run-1", "outcome": "supply_exhausted",
    }))
    status = {"run": {"outcome": None}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(
        x.field == "run.outcome" and x.dashboard is None and x.ground_truth == "supply_exhausted"
        for x in d
    )


def test_verify_run_ignores_an_outcome_file_naming_a_different_run_id(tmp_path):
    """A stale outcome file from an earlier run_id must not be treated as this run's ground
    truth -- the dashboard reporting supply_exhausted off that stale file is itself the bug this
    check exists to catch."""
    _write_manifest(tmp_path, "run-1")
    (tmp_path / "run_outcome_run-1.json").write_text(json.dumps({
        "run_id": "some-other-run", "outcome": "supply_exhausted",
    }))
    status = {"run": {"outcome": "supply_exhausted"}}
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "run.outcome" and x.ground_truth is None for x in d)


def test_verify_run_absent_field_yields_no_discrepancy(tmp_path):
    """A status payload with no "run" block, or a "run" block with no "outcome" key at all, is
    absence -- not disagreement."""
    assert verify_numbers.verify(tmp_path, {}) == []
    assert verify_numbers.verify(tmp_path, {"run": {}}) == []


def test_verify_run_no_manifest_on_disk_and_dashboard_reports_none_matches(tmp_path):
    status = {"run": {"outcome": None}}
    assert verify_numbers.verify(tmp_path, status) == []


# --- disk headroom (racy: tolerance, not exact) ---------------------------------------------------


def test_verify_disk_within_tolerance_is_not_a_discrepancy(tmp_path):
    import shutil

    free_gb = shutil.disk_usage(tmp_path).free / 1e9
    status = {"disk": {"free_gb": free_gb}}
    assert verify_numbers.verify(tmp_path, status) == []


def test_verify_disk_far_off_is_reported_as_racy(tmp_path):
    status = {"disk": {"free_gb": -1_000_000.0}}
    d = verify_numbers.verify(tmp_path, status)
    assert len(d) == 1
    assert d[0].field == "disk.free_gb"
    assert d[0].note.startswith("racy")


# --- CLI: exits 1 on a hard discrepancy, prints the field -----------------------------------------


def test_main_reports_failure_and_exits_1_when_status_is_wrong(tmp_path, monkeypatch, capsys):
    _make_scratch_corpus(tmp_path, done=5, chunked=2)
    (tmp_path / ".dashboard_token").write_text("tok")
    monkeypatch.setattr(
        verify_numbers, "_fetch_status", lambda data_dir, host, port: _status_for(done=999),
    )
    rc = verify_numbers.main(["--data-dir", str(tmp_path)])
    assert rc == 1
    assert "funnel.done" in capsys.readouterr().out


def test_main_exits_0_when_everything_matches(tmp_path, monkeypatch):
    _make_scratch_corpus(tmp_path, done=5, chunked=2)
    (tmp_path / ".dashboard_token").write_text("tok")
    monkeypatch.setattr(
        verify_numbers, "_fetch_status", lambda data_dir, host, port: _status_for(),
    )
    rc = verify_numbers.main(["--data-dir", str(tmp_path)])
    assert rc == 0
