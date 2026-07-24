# Quarantine Count + Reason Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a real disagreement between the dashboard's live quarantine count and the end-of-run printed summary, and make the quarantine reason breakdown name the pipeline stage, not just the coarse exception class.

**Architecture:** Extract the one correct query (`app/dashboard/status.py`'s OG-44-fixed "exclude papers that later succeeded" logic) into a single shared function, `quarantine_summary(conn)`, and have `app/telemetry.py::summarize_run` call it instead of maintaining its own un-fixed duplicate. Extend that one query to group by `(stage, error_type)` instead of `error_type` alone.

**Tech Stack:** Python 3 stdlib (`sqlite3`).

## Global Constraints

- `quarantine_summary`'s count and reasons must always reconcile: `sum(count for _, count in reasons) == total_count`, for every input (this is what breaks today between `status.py` and `telemetry.py`).
- The public shapes `read_corpus` returns (`{"reason": str, "count": int}` list) and `summarize_run` returns (`quarantine_reasons: dict[str, int]`) do not change — only the string values inside `reason`/the dict keys change (now `"<error_type> @ <stage>"` instead of bare `<error_type>`). No frontend (`index.html`) or `RunSummary.format()` changes needed — both already treat the reason as an opaque string.
- Spec: `docs/DESIGN-download-only-and-quarantine-fixes.md`, "Part 2 — Quarantine count + reason fixes".

---

### Task 1: `status.py` — shared `quarantine_summary()`, stage-qualified reasons

**Files:**
- Modify: `app/dashboard/status.py` (`read_corpus`, ~line 54-100)
- Test: `app/dashboard/test_status.py`

**Interfaces:**
- Produces: `status.quarantine_summary(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, int]]]` — `(total_count, [(reason, count), ...])`, both excluding paper_ids that reached `stage='done'`. `reason` is `"<error_type> @ <stage>"`.
- Consumes: an already-open `sqlite3.Connection` (the caller owns open/close — `read_corpus`'s existing `mode=ro` connection here, `telemetry.py`'s plain read-write connection in Task 2).

- [ ] **Step 1: Write the failing tests**

`app/dashboard/test_status.py` already has quarantine-reason tests (`test_read_corpus_quarantine_reasons_grouped_and_sorted` etc., ~line 74-139) that assert the OLD bare-`error_type` reason strings. These must be updated to the new `"<error_type> @ <stage>"` format (every quarantine row `_seed` writes is hardcoded to `stage='parsed'`, per its own body — see `_seed`'s `"INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, 'parsed', ...)"`), and one new test added proving two different stages are NOT collapsed together.

Replace `test_read_corpus_quarantine_reasons_grouped_and_sorted` (~line 74-82):

```python
def test_read_corpus_quarantine_reasons_grouped_and_sorted(tmp_path):
    _seed(
        tmp_path / "papers.db", {"done": 1},
        quarantine=[("q1", "TransientError"), ("q2", "TransientError"), ("q3", "PermanentError")],
    )
    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 3
    assert result["quarantine_reasons"][0] == {"reason": "TransientError @ parsed", "count": 2}
    assert {"reason": "PermanentError @ parsed", "count": 1} in result["quarantine_reasons"]
```

Replace `test_read_corpus_quarantine_reasons_surfaces_an_unknown_bucket_for_pre_diagnostics_rows` (~line 85-114):

```python
def test_read_corpus_quarantine_reasons_surfaces_an_unknown_bucket_for_pre_diagnostics_rows(
    tmp_path,
):
    """`quarantine_diagnostics` (T-DOC17/PR #83) postdates `quarantine` itself -- a paper
    quarantined before that landed has a `quarantine` row but no matching `quarantine_diagnostics`
    one. Observed live: funnel said 32 quarantined, the reasons breakdown alone summed to only 22,
    a silent, confusing gap. The reason breakdown must not just under-report -- the difference is
    surfaced as its own "unknown" bucket (still with a real stage, from `quarantine` itself) so the
    two numbers always reconcile."""
    db_path = tmp_path / "papers.db"
    _seed(
        db_path, {"done": 1},
        quarantine=[("q1", "TransientError"), ("q2", "PermanentError")],
    )
    # A legacy row: `quarantine` only, no `quarantine_diagnostics` -- unlike `_seed`'s own
    # quarantine entries, which always write both together.
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES ('q3', 'parsed', 'boom', ?)",
        ("2026-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()

    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 3
    reasons_total = sum(r["count"] for r in result["quarantine_reasons"])
    assert reasons_total == 3  # now reconciles with funnel["quarantined"]
    assert {
        "reason": "unknown (quarantined before diagnostics were recorded) @ parsed", "count": 1,
    } in result["quarantine_reasons"]
```

Replace `test_read_corpus_quarantine_reasons_omits_unknown_bucket_when_fully_diagnosed` (~line 117-123):

```python
def test_read_corpus_quarantine_reasons_omits_unknown_bucket_when_fully_diagnosed(tmp_path):
    """The common case (every quarantine row has a matching diagnostics row, as `_seed` always
    writes) must not grow a spurious "unknown, count 0" entry."""
    _seed(tmp_path / "papers.db", {"done": 1}, quarantine=[("q1", "TransientError")])
    result = status_mod.read_corpus(tmp_path)
    assert all(
        "unknown (quarantined before diagnostics were recorded)" not in r["reason"]
        for r in result["quarantine_reasons"]
    )
```

Replace `test_read_corpus_excludes_quarantined_papers_that_later_succeeded` (~line 126-139):

```python
def test_read_corpus_excludes_quarantined_papers_that_later_succeeded(tmp_path):
    """OG-44: `quarantine` is an append-only dead-letter log, never reconciled -- a paper that was
    quarantined and later succeeded on retry (now `stage='done'`) must not still count as
    quarantined. 3 quarantined, 2 later recovered -> only 1 truly stuck."""
    db_path = tmp_path / "papers.db"
    _seed(
        db_path, {"done": 1},
        quarantine=[("q1", "TransientError"), ("q2", "TransientError"), ("q3", "PermanentError")],
    )
    _mark_done(db_path, "q1")
    _mark_done(db_path, "q2")
    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 1
    assert result["quarantine_reasons"] == [{"reason": "PermanentError @ parsed", "count": 1}]
```

Add a new test right after it, proving stage-grouping itself (needs two DIFFERENT stages, which `_seed`'s hardcoded `'parsed'` can't produce -- inserted directly, same style as the pre-diagnostics test above):

```python
def test_read_corpus_quarantine_reasons_group_by_stage_not_just_error_type(tmp_path):
    """T-DOC78: two papers with the SAME error_type but DIFFERENT pipeline stages must NOT be
    collapsed into one reason -- "PermanentError @ parsed" and "PermanentError @ embedded" answer
    a genuinely different "why" (a bad PDF vs. a broken embedding call)."""
    db_path = tmp_path / "papers.db"
    _seed(db_path, {"done": 1})
    conn = sqlite3.connect(str(db_path))
    for paper_id, stage in (("q1", "parsed"), ("q2", "embedded")):
        conn.execute(
            "INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, ?, 'boom', ?)",
            (paper_id, stage, "2026-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO quarantine_diagnostics (paper_id, error_type, diagnostics_json) "
            "VALUES (?, 'PermanentError', '{}')",
            (paper_id,),
        )
    conn.commit()
    conn.close()

    result = status_mod.read_corpus(tmp_path)
    assert result["funnel"]["quarantined"] == 2
    assert {"reason": "PermanentError @ parsed", "count": 1} in result["quarantine_reasons"]
    assert {"reason": "PermanentError @ embedded", "count": 1} in result["quarantine_reasons"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_status.py -k quarantine -v`
Expected: FAIL — current `read_corpus` reasons are bare `error_type` strings (no `" @ parsed"` suffix), so every updated assertion mismatches, and the new group-by-stage test collapses both rows into one `"PermanentError"` bucket with `count: 2`.

- [ ] **Step 3: Add `quarantine_summary`, refactor `read_corpus`**

In `app/dashboard/status.py`, replace `read_corpus` (~line 54-100) with:

```python
# T-DOC78: shared with `app/telemetry.py::summarize_run` -- both need "how many quarantined, and
# why" against an open connection. Previously computed with two independently-drifting queries:
# telemetry's own copy never got the OG-44 "exclude papers that later succeeded" fix this one has,
# so the dashboard's live count and the end-of-run printed summary could legitimately disagree.
_UNDIAGNOSED_REASON = "unknown (quarantined before diagnostics were recorded)"


def quarantine_summary(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, int]]]:
    """`(count, [(reason, count), ...])` -- total quarantined and a reason breakdown, BOTH
    excluding any paper_id that has since reached `stage='done'` (OG-44: `quarantine` is an
    append-only dead-letter log, never reconciled, so a paper that later succeeded on retry must
    not still count as stuck). `reason` is `"<error_type> @ <stage>"` (e.g.
    `"PermanentError @ parsed"`) -- `stage` comes from `quarantine` itself (always present);
    `error_type` comes from `quarantine_diagnostics` via a LEFT JOIN, since that table (T-DOC17/PR
    #83) postdates `quarantine` -- a pre-existing row has no diagnostics match and is labelled
    `_UNDIAGNOSED_REASON` rather than silently dropped. Grouping by stage too (not just
    error_type) means the reason breakdown ALWAYS sums to `count` by construction -- no separate
    "top up the gap" step needed, unlike the previous single-column GROUP BY. Sorted by count,
    descending. Takes an already-open connection (a `mode=ro` URI connection in `read_corpus`
    below, a plain read-write one in `app/telemetry.py`) rather than opening its own, so either
    caller's connection semantics apply."""
    count = conn.execute(
        "SELECT count(*) FROM quarantine WHERE paper_id NOT IN "
        "(SELECT paper_id FROM ingest_state WHERE stage = 'done')"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT q.stage, COALESCE(qd.error_type, ?) AS error_type, count(*) AS n "
        "FROM quarantine q LEFT JOIN quarantine_diagnostics qd ON qd.paper_id = q.paper_id "
        "WHERE q.paper_id NOT IN (SELECT paper_id FROM ingest_state WHERE stage = 'done') "
        "GROUP BY q.stage, error_type ORDER BY n DESC",
        (_UNDIAGNOSED_REASON,),
    ).fetchall()
    return count, [(f"{error_type} @ {stage}", n) for stage, error_type, n in rows]


def read_corpus(data_dir: str | Path) -> dict:
    """Stage funnel (+ quarantine count) and top quarantine reasons, from `<data_dir>/papers.db`
    -- always the same fixed path (matches the HARD CONSTRAINT that this reader never touches
    anything but `papers.db`; every observed run's manifest `db_path` is this same path anyway).
    Returns `{"funnel": {...}, "quarantine_reasons": [...]}`."""
    db_path = Path(data_dir) / _DEFAULT_DB_NAME
    conn = _ro_connect(db_path)
    if conn is None:
        return {"funnel": _null_funnel(), "quarantine_reasons": []}
    try:
        stage_counts = dict(
            conn.execute("SELECT stage, count(*) FROM ingest_state GROUP BY stage").fetchall()
        )
        quarantine_count, reason_pairs = quarantine_summary(conn)
    except sqlite3.Error:
        return {"funnel": _null_funnel(), "quarantine_reasons": []}
    finally:
        conn.close()

    funnel = _funnel_from_stage_counts(stage_counts)
    funnel["quarantined"] = quarantine_count
    quarantine_reasons = [{"reason": reason, "count": count} for reason, count in reason_pairs]
    return {"funnel": funnel, "quarantine_reasons": quarantine_reasons}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_status.py -k quarantine -v`
Expected: PASS

- [ ] **Step 5: Run the full status test suite**

Run: `pytest app/dashboard/test_status.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/status.py app/dashboard/test_status.py
git commit -m "T-DOC78: add status.quarantine_summary(); reasons now include pipeline stage"
```

---

### Task 2: `telemetry.py` — use the shared query, fixing the count mismatch

**Files:**
- Modify: `app/telemetry.py` (`summarize_run`, ~line 295-330, plus its imports)
- Test: `app/test_telemetry.py`

**Interfaces:**
- Consumes: `app.dashboard.status.quarantine_summary(conn)` (Task 1).
- `RunSummary.n_quarantined`/`RunSummary.quarantine_reasons` are unchanged types (`int`/`dict[str, int]`); only their VALUES now match `status.quarantine_summary`'s (excluding later-recovered papers, keyed by `"<error_type> @ <stage>"`).

- [ ] **Step 1: Write the failing tests**

In `app/test_telemetry.py`, update `test_summarize_run_counts_done_and_quarantined_with_reasons` (~line 276-292) — `_seed_db`'s quarantine rows are hardcoded to `stage='parsed'` (see its body, `"INSERT INTO quarantine (paper_id, stage, error, ts) VALUES (?, 'parsed', ...)"`), so the expected reason keys now carry `" @ parsed"`:

```python
def test_summarize_run_counts_done_and_quarantined_with_reasons(tmp_path):
    db_path = str(tmp_path / "papers.db")
    _seed_db(
        db_path,
        done_ids=["a", "b", "c"],
        quarantined=[("d", "PermanentError"), ("e", "PermanentError"), ("f", "TransientError")],
    )

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=3600.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: 999,
    )

    assert summary.n_done == 3
    assert summary.n_quarantined == 3
    assert summary.quarantine_reasons == {
        "PermanentError @ parsed": 2, "TransientError @ parsed": 1,
    }
    assert summary.papers_per_hour == pytest.approx(3.0)
```

Add a new regression test right after it -- the direct proof the original bug (dashboard vs. end-of-run summary disagreeing) is fixed:

```python
def test_summarize_run_excludes_quarantined_papers_that_later_succeeded(tmp_path):
    """OG-44 regression, now applied here too: `quarantine` is an append-only dead-letter log,
    never reconciled -- a paper quarantined and later succeeded on retry (now stage='done') must
    not still count as quarantined in the end-of-run summary. Before T-DOC78, this module computed
    its own un-fixed `SELECT count(*) FROM quarantine` with no such exclusion, so it could disagree
    with `app/dashboard/status.py::read_corpus`'s (already-fixed) live count for the exact same
    database -- this is the regression test for that disagreement."""
    db_path = str(tmp_path / "papers.db")
    _seed_db(db_path, quarantined=[("d", "PermanentError"), ("e", "PermanentError")])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES ('d', 'done', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    summary = telemetry.summarize_run(
        db_path, wall_clock_s=10.0, collection="papers", gpu_samples=[],
        query_point_count=lambda host, port, collection: 10,
    )

    assert summary.n_quarantined == 1
    assert summary.quarantine_reasons == {"PermanentError @ parsed": 1}
```

This new test needs `sqlite3` imported at module level (the existing `_seed_db` does a local `import sqlite3` inside its own function body instead) -- add to the top-level imports (~line 10-15):

```python
from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from types import SimpleNamespace
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/test_telemetry.py -k "summarize_run_counts_done_and_quarantined or summarize_run_excludes_quarantined" -v`
Expected: FAIL — `summarize_run`'s current reasons are bare `error_type` (no stage suffix), and the new exclusion test's `n_quarantined` is `2` (no exclusion applied), not the expected `1`.

- [ ] **Step 3: Wire `summarize_run` to `quarantine_summary`**

In `app/telemetry.py`, add the import near the top (~line 46-60, alongside the other stdlib imports):

```python
from app.dashboard.status import quarantine_summary
```

Find `summarize_run` (~line 295-330) and replace its DB-read block:

```python
    try:
        conn = sqlite3.connect(db_path)
        try:
            n_done = conn.execute(
                "SELECT count(*) FROM ingest_state WHERE stage = 'done'"
            ).fetchone()[0]
            n_quarantined, reason_pairs = quarantine_summary(conn)
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.critical(
            "telemetry.summarize_run: could not read %r for the end-of-run summary: %s",
            db_path, e, exc_info=True,
        )
        n_done, n_quarantined, reason_pairs = 0, 0, []
```

And update the `RunSummary(...)` construction a few lines below to use `reason_pairs` instead of the old `reason_rows`:

```python
    return RunSummary(
        run_id=run_id,
        n_done=n_done,
        n_quarantined=n_quarantined,
        quarantine_reasons=dict(reason_pairs),
        wall_clock_s=wall_clock_s,
        papers_per_hour=papers_per_hour,
        vector_store_point_count=point_count,
        sqlite_done_count=n_done,
        consistent=consistent,
```

(The rest of `summarize_run` — `papers_per_hour`, `point_count`, `consistent` — is unchanged; only the two lines computing `n_quarantined`/the reasons variable, and the one line that packs `dict(reason_pairs)` now instead of `dict(reason_rows)`, change.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/test_telemetry.py -k "summarize_run" -v`
Expected: PASS

- [ ] **Step 5: Run the full telemetry test suite, and status.py's (shared function, both sides)**

Run: `pytest app/test_telemetry.py app/dashboard/test_status.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/telemetry.py app/test_telemetry.py
git commit -m "T-DOC78: summarize_run uses the shared quarantine_summary; fixes count mismatch"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 implements "one query, not two" (the shared `quarantine_summary`) and the stage-qualified reason format; Task 2 implements "telemetry.py calls it instead of its own copy," the direct fix for the count-mismatch bug. Both spec subsections ("Fix — one query, not two", "Reason detail — add stage to the tally") are covered.
- **Placeholder scan:** no TBD/TODO; every step has literal code and literal test assertions.
- **Type consistency:** `quarantine_summary(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, int]]]` is defined once in Task 1 and consumed identically in Task 2 (`n_quarantined, reason_pairs = quarantine_summary(conn)`) — same unpacking shape in both callers. `RunSummary.quarantine_reasons: dict[str, int]` (existing dataclass field, unchanged) still receives `dict(reason_pairs)`, just with new key strings.
- **No circular import risk:** `app/dashboard/status.py` has zero internal-project imports (pure stdlib) per its current header, so `app/telemetry.py` importing from it introduces no cycle.
