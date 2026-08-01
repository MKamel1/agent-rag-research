# O-1: finish cleanly when arXiv has no more papers

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a run has processed everything available and the downloader can find no new papers, it should wait ~15 minutes, then **finish as completed** with a message naming the real reason — not sit for an hour and end as `failed` blaming the operator's configuration.

**Architecture:** `build_corpus` distinguishes *supply exhaustion* (nothing left on arXiv for the configured queries) from *processing failure* (batches running but making no progress), shortens the supply-exhausted wait to ~15 minutes, and records the outcome so `controller.reconcile()` can mark the run `done` rather than `failed`.

**Tech Stack:** Python 3.12, stdlib `json`/`pathlib`, pytest.

---

## Operator requirement (2026-08-01, verbatim intent)

> "if the run couldn't find new paper to download and processed all existing downloads then it
> should try for 15 minutes to fetch new papers and report back that target could not [be] met as
> the no paper to download on arxiv and the run should finish/completed."

## Current behaviour, measured

Run `run-12500-20260801_173341` ended like this:

```
build_corpus: caught up with the cache (12390/12500 done) -- waiting 300s for the downloader
   ... repeated ...
build_corpus: stalled -- a batch of 16 ran but made zero net progress (12374/13000 done)
   after 12 consecutive idle pass(es) (max_idle=12), giving up --
   check parse_workers/parse_batch_size aren't misconfigured
```

and the manifest reconciled to **`failed`**.

Three things are wrong with that:

1. **It waits ~60 minutes.** `_DEFAULT_MAX_IDLE = 12` × `_DEFAULT_POLL_INTERVAL_S = 300s`.
2. **The message blames the wrong thing.** "check parse_workers/parse_batch_size aren't misconfigured" is right for a processing stall; it is wrong and misleading when the true cause is that arXiv has nothing left. The prefetcher already knows: `prefetch stalled: 11654/30000 cached, only 0 new available`.
3. **The status is `failed`.** `controller._crashed_before_target` marks any run with `done_count < target` as failed. But a run that processed everything obtainable did not fail — the target was simply unreachable. Two runs in a row ended this way, so `failed` is now the *normal* outcome, which drains the status of meaning.

## Design

### 1. Tell the two stalls apart

`build_corpus`'s idle loop currently has one `max_idle` guard covering both cases. Split them:

| condition | meaning | new behaviour |
|---|---|---|
| cache drained, downloader alive, **and the downloader reports no new papers available** | supply exhausted | wait `_SUPPLY_EXHAUSTED_MAX_IDLE` (≈15 min), then finish **completed** |
| batches running but making zero net progress | processing stall | unchanged: existing `max_idle`, existing message, still a failure |

**How to detect "no new papers available" without importing the downloader:** `app/prefetch_pdfs.py`
already logs, every stalled pass, into the run's `prefetch.log`:

```
prefetch_pdfs: prefetch stalled: 11654/30000 cached, only 0 new available, next attempt in 3600s
```

`build_corpus` already owns `run_cwd` and knows where that log is. Read its tail and match the same
line `status.py::_DOWNLOAD_STALL_RE` matches:

```python
r"prefetch stalled: (\d+)/(\d+) cached, only (\d+) new available"
```

Treat `new available == 0` on the most recent stall line as "supply exhausted". If the log is
missing or has no stall line, fall back to today's behaviour — **absence is not exhaustion**.

Do **not** import `app/dashboard/status.py` from `app/build_corpus.py`. Duplicate the small regex
with a comment pointing at the other copy, matching this repo's existing "own your own copies"
convention (`status.py` does exactly this for `_PREFETCH_PID_NAME`).

### 2. Timing

```python
# ~15 minutes: the operator's chosen patience for "arXiv may publish something in the next few
# minutes" before declaring the corpus complete for the configured queries (2026-08-01).
# Deliberately much shorter than the processing-stall guard: a supply stall is a fact about the
# world, not something more waiting will fix, whereas a processing stall may clear itself.
_SUPPLY_EXHAUSTED_MAX_IDLE = 3      # x _DEFAULT_POLL_INTERVAL_S (300s) = 15 minutes
```

Leave `_DEFAULT_MAX_IDLE = 12` alone for the processing-stall path.

### 3. The completion message

On supply exhaustion, log at INFO and make the reason unmistakable:

```
build_corpus: target not reachable -- 12390/12500 done, and arXiv has no new papers for the
configured queries (downloader reported 0 new available over 3 consecutive checks / 15 min).
Corpus is complete for the current focus_area_queries; widen them or lower the target to change
this. Finishing as COMPLETED, not failed.
```

### 4. Persist the outcome so `reconcile()` can read it

`controller.reconcile()` sees only: pid gone, `done_count`, `target`. It cannot see an exit code.
So `build_corpus` must record the outcome durably.

Write `<data_dir>/run_outcome_<run_id>.json` immediately before returning:

```json
{"run_id": "...", "outcome": "supply_exhausted", "done": 12390, "target": 12500,
 "reason": "no new papers available on arXiv for the configured queries",
 "finished_at": "2026-08-01T…Z"}
```

**Put it in `data_dir`, not `run_cwd`** — `run_cwd` is a scratch dir that `_cleanup_run_cwd` deletes,
and this file must outlive the run. It sits beside the existing per-run artifacts
(`ingest_run-<run_id>.log`, `ingest_events_<run_id>.jsonl`), matching that convention.

Then in `controller._crashed_before_target`, before the `done_count < target` comparison:

```python
# O-1: a run that processed everything obtainable did NOT crash -- the target was unreachable
# because arXiv had nothing left for the configured queries. build_corpus records that
# explicitly; without this check every such run reconciles to "failed" and the status stops
# meaning anything (two consecutive runs ended this way on 2026-08-01).
```

If `run_outcome_<run_id>.json` exists and `outcome == "supply_exhausted"`, return `False` (not a
crash) — so `reconcile()` marks the run `done`.

Read it defensively: missing file, unreadable JSON, or an unrecognised `outcome` all fall through
to today's behaviour. A malformed outcome file must never crash a status poll.

### 5. Surface it (small)

`status.read_corpus`/`server._status_dict` need no change. But `run.status == "done"` alone loses
the nuance, so add the outcome to the `run` block when the file exists:

```python
"outcome": "supply_exhausted"   # or None
```

and have `index.html` show, when present: **"Completed — arXiv exhausted for the current queries
(12,390 of 12,500)."** One line, in the run panel. No new panel.

## Non-goals

- Do **not** change `prefetch_target` or `focus_area_queries`. Whether to widen the queries is the
  operator's decision (backlog O-1); this ticket only makes the *outcome reporting* honest.
- Do **not** make the processing-stall path lenient. A batch running with zero net progress is
  still a failure and still says so.
- Do **not** auto-lower the target. Reporting the truth is the fix; silently rewriting the
  operator's goal is not.

---

## Global Constraints

- **Do not modify** `contracts/`, `rag/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`, or `app/prefetch_pdfs.py`. `app/build_corpus.py` and `app/dashboard/*` **are** in scope for this ticket.
- **Never** write `<data_dir>/config.yaml`, `tag_pool.json`, or `papers.db`. No ingest, rechunk, delete, snapshot, or corpus run. Tests use `tmp_path`.
- Do not restart the dashboard; nothing here needs it.
- Never `git stash`; never merge a PR; never `--admin`.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b supply-exhausted-completion origin/main`.
- Run pytest in the **foreground**; read its exit code. Do NOT write output to a shared `/tmp` path and poll for a summary string.
- Enforcement — **`number`/`labels` go INSIDE `pull_request`**:

  ```bash
  EV=$(mktemp) && printf '{"pull_request":{"number":0,"labels":[],"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- `rag/parser.py` is the only file that may name `mineru`/`grobid` tokens; `app/build_corpus.py` may name `prefetch_pdfs` (it already launches it), but check `ci/checks/vendor_isolation.py` before adding any vendor token elsewhere.
- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`.

---

### Task 1: Detect supply exhaustion in `build_corpus`

**Files:** `app/build_corpus.py`. Test: `app/test_build_corpus.py`.

- [ ] **Step 1: Write the failing tests** — inject a fake `sleep` and a `tmp_path` run dir; no test may sleep for real or spawn a process.

```python
def test_supply_exhausted_finishes_after_the_short_wait_not_the_long_one(tmp_path, ...):
    """15 minutes (3 x 300s), not 60. The downloader reporting 0 new available is a fact about
    the world; waiting longer cannot change it."""
    _write_prefetch_log(tmp_path, "prefetch stalled: 11654/30000 cached, only 0 new available, next attempt in 3600s")
    slept = []
    build_corpus.run(..., sleep=slept.append, ...)
    assert len(slept) == 3          # _SUPPLY_EXHAUSTED_MAX_IDLE, not _DEFAULT_MAX_IDLE


def test_supply_exhausted_writes_a_run_outcome_file(tmp_path, ...):
    ...
    out = json.loads((tmp_path / "run_outcome_run-1.json").read_text())
    assert out["outcome"] == "supply_exhausted"
    assert out["done"] == 12390 and out["target"] == 12500


def test_a_processing_stall_is_still_a_failure_and_still_waits_the_long_guard(tmp_path, ...):
    """Batches running with zero net progress is a real problem -- unchanged behaviour."""
    _write_prefetch_log(tmp_path, "prefetch stalled: 11654/30000 cached, only 42 new available, next attempt in 3600s")
    ...
    assert len(slept) == 12
    assert not (tmp_path / "run_outcome_run-1.json").exists()


def test_missing_prefetch_log_falls_back_to_the_existing_behaviour(tmp_path, ...):
    """Absence is not exhaustion."""
    ...
    assert len(slept) == 12
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement** per the design above. **Step 4: Test.**

- [ ] **Step 5: Commit**

```bash
git add app/build_corpus.py app/test_build_corpus.py
git commit -m "build_corpus: finish as completed when arXiv has no papers left

A run that drained the cache and whose downloader reports '0 new available'
waited the full 60-minute processing-stall guard and then logged 'giving up --
check parse_workers/parse_batch_size aren't misconfigured' -- blaming config for
a supply fact. It now waits 15 minutes, says arXiv has nothing left for the
configured queries, and records run_outcome_<run_id>.json so the run can be
reconciled as done rather than failed.

The processing-stall path (batches running, zero net progress) is unchanged --
that is still a real failure and still says so."
```

### Task 2: Reconcile supply-exhausted runs as `done`

**Files:** `app/dashboard/controller.py` (`_crashed_before_target`). Test: `app/dashboard/test_controller.py`.

- [ ] Test: manifest with `done < target` **plus** a `supply_exhausted` outcome file ⇒ `reconcile` yields `done`.
- [ ] Test: manifest with `done < target` and **no** outcome file ⇒ still `failed` (the crash signal must survive).
- [ ] Test: malformed/unreadable outcome JSON ⇒ falls back to `failed`, does **not** raise.
- [ ] Test: an outcome file naming a *different* `run_id` is ignored.
- [ ] Commit: `Reconcile a supply-exhausted run as done, not failed`

### Task 3: Surface the outcome

**Files:** `app/dashboard/server.py`, `app/dashboard/static/index.html`. Test: `app/dashboard/test_server.py`.

- [ ] `run.outcome` appears in `/api/status` when the file exists, `None` otherwise.
- [ ] `index.html` shows one line in the run panel when `outcome == "supply_exhausted"`.
- [ ] **`verify_numbers` must still pass** — if you add a field it cross-checks, add its ground truth too.
- [ ] Commit: `Show the supply-exhausted outcome in the run panel`

### Task 4: Verify and PR

- [ ] Full suite + enforcement, both `rc=0`.
- [ ] Run the cross-check read-only and report its output verbatim:

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m app.dashboard.verify_numbers --data-dir /home/omar/ai-projects/research-system-rag-data
rc=$?
```

- [ ] PR titled `O-1: finish as completed when arXiv is exhausted, not failed`. Do not merge. Poll `gh pr checks <n>` until final; both must `pass`.

---

## Report contract

Return only: status, commit SHAs, PR number, real `rc` for pytest and enforcement, the `verify_numbers` output verbatim, confirmation that the processing-stall path still fails and still waits the long guard, and the final CI conclusion for each check by name.
