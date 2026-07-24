# Design — Dashboard "Download Now" control + quarantine count/reason fixes

*T-DOC78 hardening. Two independent fixes bundled because both touch the same dashboard
control-plane/status area and are each small: (1) let the operator download PDFs ahead of time
without committing GPU time to pass1/pass2, so a "GPU busy" window doesn't block building the
cache; (2) fix a real quarantine-count disagreement between the dashboard and the end-of-run
summary, and add the pipeline stage to the quarantine reason breakdown so "why" is answerable
without a manual SQL query.*

## Part 1 — Download-only control

### Why (plain English)
`app/prefetch_pdfs.py` already exists as a standalone, GPU-free PDF downloader — it never touches
MinerU, never runs pass1/pass2. Today it's only reachable as a child of `app.build_corpus`, which
the dashboard's "Apply"/Start button always launches together with a full parse+embed run. There's
no dashboard control to run *just* the downloader and defer pass1/pass2 to whenever the GPU frees
up.

### The one hard constraint that shapes the design
The dashboard's control plane (`app/dashboard/controller.py`) already has everything a second,
independent lifecycle would have to re-invent: one `run_manifest.json` per data dir, a
`.control.lock`, a double-run guard, PID-based pause/resume/stop with process-group signaling, and
run-scoped config overrides for keywords/categories/dates/ordering
(`_maybe_build_override`/`_write_override_config_dir`). Building a second, parallel lifecycle for
"download-only" would duplicate all of that and then need its own mutual-exclusion logic against
the first. Instead, download-only becomes a **mode of the existing single-run lifecycle**:

- One manifest can describe either mode (`"mode": "full" | "download"`).
- The existing double-run guard (`_start_locked`'s `DoubleRunError` when a manifest is already
  live) *is* the mutual-exclusion the owner asked for — a download-only run and a full run can
  never be live at the same time, with no new locking code.
- Pause/Resume/Stop stay generic — they already act on "whatever PID the live manifest holds,"
  regardless of what was spawned.
- `_maybe_build_override` is already mode-agnostic, so a download-only run gets the same
  keywords/categories/dates/ordering the operator has staged in the Apply panel, for free.

### Architecture

```
controller.start(data_dir, target, parse_workers, *, mode="full", ...)
```

`mode` defaults to `"full"` — every existing caller/test is byte-for-byte unchanged. `mode="download"`
changes exactly one thing: which command gets spawned.

- New `_spawn_download(data_dir, target, parse_workers, events_path, log_path) -> int` — matches
  `SpawnFn`'s existing shape so `_call_spawn`/`resume` need no changes. Ignores
  `target`/`parse_workers`/`events_path` (not meaningful for a download-only run) and:
  - launches `env PYTHONPATH=<repo> python -m app.prefetch_pdfs` with `cwd=data_dir` (the run's
    `run_cwd` — the real data dir, or a keywords/dates override scratch dir), `start_new_session=True`
    (own process group, same as `_spawn` today).
  - writes `<data_dir>/prefetch.pid` — the **same filename** `app/build_corpus.py::_spawn_prefetch`
    already writes. This is the key reuse: `app/dashboard/status.py::read_downloader` and
    `app/build_corpus.py::ensure_prefetch_running` only check "is a live `app.prefetch_pdfs` at this
    path," never who launched it — so both keep working against a download-only run with **zero
    changes**.
  - redirects stdout/stderr to `<data_dir>/prefetch.log` — same reasoning, matches
    `status.py::read_downloader`'s hardcoded log name so download pace still renders.
- `_start_locked` computes `log_path = run_cwd / "prefetch.log"` when `mode == "download"` (instead
  of the usual `ingest_<run_id>.log`), so `_spawn_download` receives the right path through the
  existing `log_path` parameter rather than hardcoding it twice.
- `_build_manifest` gains one field: `"mode": mode`.
- `resume()`/`_resume_locked()`: `spawn` becomes `SpawnFn | None = None`; when `None` (every
  production call site), it's resolved from `manifest.get("mode", "full")` — `_spawn_download` for
  `"download"`, `_spawn` otherwise. Tests that inject a fake spawn still override it directly and are
  unaffected by this resolution.
- `retarget()` is **not** touched — "download now" only ever starts fresh via `start()`; retargeting
  a bare downloader (no target/parse_workers to retarget) isn't a real use case, and leaving it out
  keeps the diff smaller.

### `server.py` / API
- New `POST /api/control` action `"download"`. Validates only the fields that apply
  (keywords/remove_keywords/arxiv_categories/arxiv_date_from/arxiv_date_to — the same per-field
  checks `_validate_control_kwargs` already has, pulled into a shared `_validate_editable_kwargs`
  helper so the regex/charset checks aren't duplicated). Calls
  `controller.start(data_dir, target=_STATIC_CONFIG.prefetch_target, parse_workers=1, mode="download",
  **kwargs)` — `target`/`parse_workers` are stored on the manifest for display only; download mode's
  own stopping condition is `config.prefetch_target`, read inside `app.prefetch_pdfs` itself,
  unchanged.
- `_RUN_FIELDS` gains `"mode"` so `/api/status`'s `run` object exposes it.

### UI
One new **"Download Now"** button next to Apply, sending `action: "download"` with the same staged
keyword/subject/date state `buildApplyPayload()` already collects (a subset — no
target/parse_workers/parse_batch_size/telemetry_poll/batch_size, none of which apply). A small
`mode` badge next to the run-status indicator shows "download-only" vs "full run" so the existing
Pause/Resume/Stop buttons' effect is unambiguous. No other UI changes — the downloader
alive/pace fields (`#prefetchAlive`/`#prefetchPace`) already render correctly for either mode.

### What this deliberately does not do
- No "auto-transition" from a finished/stopped download-only run into a full run — the operator
  clicks Start when they're ready, same as today. The value is that whatever's already in
  `pdf_cache/` at that point is reused immediately (`app.build_corpus`'s existing `cached_not_done`
  cache-first logic), not that the download process itself survives the handoff.
- No separate progress/target UI for download-only beyond the existing downloader pace fields —
  `config.prefetch_target` is the one target that already exists and is already displayed.
- No guard against "Download Now" clobbering a **paused full run**'s staged edits. `_start_locked`'s
  existing "abandon a non-live prior run" branch (`_cleanup_run_cwd`) already deletes a paused run's
  override scratch dir — its staged keywords/categories/dates `config.yaml` — the moment a fresh
  `start()` is called; this is pre-existing, intentional behavior for "Apply" replacing a paused run.
  "Download Now" reuses the same `start()` path and therefore hits the same branch: clicking it
  silently discards a paused full run's staged edits too, same as Apply already does today, not new
  logic. Left as-is deliberately (no new blocking logic) — but it's a more surprising trade for
  "Download Now" than for Apply, given the button's "no GPU" framing suggests it's unrelated to a
  paused full run.

## Part 2 — Quarantine count + reason fixes

### The bug (confirmed by reading both call sites)
`app/dashboard/status.py::read_corpus`'s quarantine count excludes `paper_id`s that were quarantined
but later reached `stage='done'` on a retry (OG-44: "an append-only dead-letter log ... a paper that
later succeeded stays in it forever, so a naive count overstates 'truly stuck'"). `app/telemetry.py
::summarize_run` — the end-of-run printed summary — computes `n_quarantined` as a plain
`SELECT count(*) FROM quarantine` with no such exclusion. The two numbers are computing different
things and can legitimately disagree; that disagreement is what looks like "not counted properly."

### Fix — one query, not two
Extract a single function, owned by `status.py` (the module that already has the correct,
review-derived query):

```python
def quarantine_summary(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, int]]]:
    """(count, [(reason, count), ...]) excluding paper_ids that reached 'done'. `reason` is
    already formatted as f"{error_type} @ {stage}" -- callers get an opaque display string, not
    a triple to reassemble themselves."""
```

- `read_corpus` calls it against its own `mode=ro` connection (unchanged behavior, just routed
  through the shared function).
- `telemetry.summarize_run` imports `quarantine_summary` from `app.dashboard.status` and calls it
  against its own already-open connection instead of running its own copy of the query. (`status.py`
  has no internal-project imports today — pure stdlib — so this import direction introduces no
  cycle.)

This is the root-cause fix: a future change to "what counts as quarantined" now has exactly one
place to change, and the two callers can't drift again by construction.

### Reason detail — add stage to the tally
Per the answered question, extend to the "aggregate + stage" tier rather than a full per-paper
browsable list. The query becomes a `LEFT JOIN` (so an undiagnosed row — quarantined before
`quarantine_diagnostics` existed — still contributes its real `stage`, just an `"unknown (quarantined
before diagnostics were recorded)"` error_type):

```sql
SELECT q.stage, COALESCE(qd.error_type, :undiagnosed) AS error_type, count(*) AS n
FROM quarantine q
LEFT JOIN quarantine_diagnostics qd ON qd.paper_id = q.paper_id
WHERE NOT EXISTS (SELECT 1 FROM ingest_state s WHERE s.paper_id = q.paper_id AND s.stage = 'done')
GROUP BY q.stage, error_type
ORDER BY n DESC, q.stage, error_type
```

`:undiagnosed` is the single `_UNDIAGNOSED_REASON` constant, bound once and reused as both the
`COALESCE` default and the `GROUP BY`/display value -- one string, not two spellings of "no
diagnostics yet". (The `NOT EXISTS` form, not `NOT IN`, because `NOT IN` against a subquery
silently returns zero rows if the subquery ever produces a NULL; `NOT EXISTS` doesn't have that
trap.) The `ORDER BY` tiebreak on `q.stage, error_type` exists because SQLite doesn't guarantee
row order among equal-`n` ties, and grouping by stage now produces many more of them.

Formatted as a single reason string `f"{error_type} @ {stage}"` (e.g. `"PermanentError @ parsed"`,
`"TransientError @ embedded"`) — the existing `{"reason": str, "count": int}` shape (status.py) and
`dict[str, int]` shape (telemetry.py) are both unchanged, so no downstream schema/UI change is
needed: `index.html`'s reason-row rendering and `RunSummary.format()`'s reason line already treat
`reason` as an opaque string.

### What this deliberately does not do
- No per-paper quarantine browsing table (the fuller option offered and not chosen) — the stage
  breakdown answers "which pipeline stage keeps failing" at the aggregate level the owner asked for;
  a per-paper list is a bigger, separate UI addition to revisit if the aggregate view turns out to be
  insufficient.
- No change to `quarantine`/`quarantine_diagnostics` schema or to `SqliteIngestState.quarantine()`'s
  write path — this is a read-side fix only.

## Testing
- `app/dashboard/test_controller.py`: `mode="download"` spawns the right command, writes the right
  manifest field, refuses when a full run is live (and vice versa), and `resume()` picks the stored
  mode's spawn function when none is injected.
- `app/dashboard/test_server.py`: `POST /api/control {"action": "download"}` dispatches correctly,
  rejects a target/parse_workers-shaped payload's invalid keyword/category/date fields the same way
  `"start"` does, and `/api/status`'s `run.mode` reflects the manifest.
- `app/dashboard/test_status.py`: `quarantine_summary` — excludes a recovered (later-`done`) paper_id,
  includes stage in undiagnosed rows, matches today's `read_corpus` behavior byte-for-byte when no
  paper has recovered.
- `app/test_telemetry.py`: `summarize_run`'s `n_quarantined`/`quarantine_reasons` now agree with
  `status.quarantine_summary` given the same fixture DB, including the recovered-paper exclusion case
  that previously made them disagree.
