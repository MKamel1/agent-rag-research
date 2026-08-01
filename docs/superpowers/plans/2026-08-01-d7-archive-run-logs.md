# D-7: Preserve per-run logs before cleanup — spec + implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop destroying a run's harvest diagnostics. Archive `prefetch.log` and the run's effective `config.yaml` into the data dir before the override scratch directory is deleted.

**Architecture:** One helper called from inside `controller._cleanup_run_cwd`, immediately before its `shutil.rmtree`. All four cleanup call sites route through that function, so fixing it there covers every path rather than patching each caller.

**Tech Stack:** Python 3.12, stdlib `shutil`/`pathlib`, pytest.

---

## The problem (measured 2026-08-01)

The operator added a tag, ran a build, and saw no change in the metrics. The explanation was in
the run's `prefetch.log`:

```
harvest phase start: 34 focus queries, harvest cap 30000
harvest phase complete: 4044 candidate papers found, 4031 already cached/claimed, 13 to download
pass complete, +12 this pass, 11624/30000 cached
```

The new tag matched 4,044 papers of which 4,031 were already held — 99.7% redundant with the
existing queries. That is exactly the diagnostic an operator needs.

**And it is deleted when the run ends.** The file lives in the run's override scratch directory:

```
<data_dir>/.run_overrides/<run_id>/
  ├── config.yaml      <- the queries this run ACTUALLY used
  ├── prefetch.log     <- the harvest diagnostics above
  └── prefetch.pid
```

`controller._cleanup_run_cwd` (`controller.py:592`) ends with `shutil.rmtree(run_cwd)` once a run
settles into `done`/`failed`. Called from four sites: `reconcile` (471), `_start_locked` (912),
`_start_drop_in_locked` (970), `_stop_locked` (1120).

**Every dashboard-started run is affected now.** Since D-5, tag edits compose into an override, so
essentially every run gets a scratch dir — and loses its harvest log when it finishes.

The main ingest log (`<data_dir>/ingest_run-<run_id>.log`) is unaffected; it already lives in the
data dir and survives. Only the override dir's contents are lost.

## Design

**Archive inside `_cleanup_run_cwd`, before the `rmtree`.** One choke point, four callers covered
for free. Patching the call sites individually would be four chances to miss one, and the next
caller added would miss it too.

Destination follows the flat, per-run convention `<data_dir>` already uses for
`ingest_run-<run_id>.log` and `ingest_events_<run_id>.jsonl`:

| source (deleted) | archived to |
|---|---|
| `<run_cwd>/prefetch.log` | `<data_dir>/prefetch_<run_id>.log` |
| `<run_cwd>/config.yaml` | `<data_dir>/config_<run_id>.yaml` |

`config.yaml` is archived alongside the log because "which queries did this run actually use?" is
the other half of the same question — and after cleanup there is otherwise no record of it.
`prefetch.pid` is deliberately **not** archived: it is process state, meaningless once the run ends.

**Best-effort, never blocking.** Archiving failures must not prevent cleanup or raise into a status
poll — `_cleanup_run_cwd` is reached from `reconcile()`, which runs on every `/api/status` poll.
Log once at WARNING and proceed to the `rmtree` regardless. A missing `prefetch.log` (a run that
never spawned a downloader) is normal, not an error.

**No-op when there is no override.** `_cleanup_run_cwd` already returns early when
`run_cwd == data_dir`. An unedited run writes `prefetch.log` directly into the data dir, where it
is already durable — archiving would copy a file onto itself.

### Non-goals

- **No retention policy or rotation.** 23 `ingest_run-*.log` files have accumulated since July with
  no complaint; adding rotation now is speculative. Revisit if disk becomes a real issue.
- **No change to the pause path.** `pause` does not call `_cleanup_run_cwd` (a later `resume`
  reuses `run_cwd` verbatim), so nothing is at risk there.
- **No new dashboard UI.** These are debugging artifacts read from the filesystem, not something
  the panel needs to render. Surface them later if that turns out to be wanted.

## Global Constraints

- Backlog **D-7**.
- **Do not modify** `contracts/`, `rag/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`, `app/prefetch_pdfs.py`, or `app/build_corpus.py`.
- **Never** write `<data_dir>/config.yaml` (mtime must stay `2026-07-17 12:22:42`), `tag_pool.json`, or `papers.db`.
- **A run is live right now** (`run-30000-20260801_033744`, pid 842575, with prefetch child 842587). Do NOT stop it, do NOT trigger cleanup against the real data dir, and do NOT delete `.run_overrides/run-30000-20260801_033744/`. Tests use `tmp_path` exclusively.
- Never `git stash`; never merge a PR; never `--admin`.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b archive-run-logs origin/main`.
- Run pytest in the **foreground**; read its exit code. Do NOT write output to a shared `/tmp` path and poll for a summary string.
- Enforcement needs a synthesized payload (`labels` read without `.get`; `number` optional):

  ```bash
  EV=$(mktemp) && printf '{"number":0,"labels":[],"pull_request":{"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`.

---

### Task 1: Archive before cleanup

**Files:** Modify `app/dashboard/controller.py` (`_cleanup_run_cwd`, line 592). Test: `app/dashboard/test_controller.py`.

**Interfaces:** Adds `_archive_run_artifacts(data_dir: Path, run_cwd: Path, run_id: str) -> list[Path]` (module-private; returns what it copied, for the test to assert on).

- [ ] **Step 1: Write the failing tests**

```python
def test_cleanup_archives_prefetch_log_and_config_before_deleting_run_cwd(tmp_path):
    """D-7: the harvest diagnostics that explain 'I added a tag and nothing changed' lived only
    inside the override dir and were destroyed by _cleanup_run_cwd's rmtree."""
    run_cwd = tmp_path / ".run_overrides" / "run-1"
    run_cwd.mkdir(parents=True)
    (run_cwd / "prefetch.log").write_text(
        "prefetch_pdfs: harvest phase complete: 4044 candidate papers found, "
        "4031 already cached/claimed, 13 to download\n"
    )
    (run_cwd / "config.yaml").write_text("focus_area_queries:\n- causal inference\n")
    (run_cwd / "prefetch.pid").write_text("4242")

    controller_mod._cleanup_run_cwd(
        tmp_path, {"run_id": "run-1", "run_cwd": str(run_cwd)},
    )

    assert not run_cwd.exists(), "the scratch dir must still be removed"
    archived_log = tmp_path / "prefetch_run-1.log"
    archived_cfg = tmp_path / "config_run-1.yaml"
    assert "4031 already cached/claimed" in archived_log.read_text()
    assert "causal inference" in archived_cfg.read_text()
    # process state is not worth keeping
    assert not (tmp_path / "prefetch_run-1.pid").exists()


def test_cleanup_still_removes_run_cwd_when_archiving_fails(tmp_path, monkeypatch):
    """Archiving is best-effort: _cleanup_run_cwd is reached from reconcile(), which runs on every
    /api/status poll. A copy failure must never block cleanup or raise into a status poll."""
    run_cwd = tmp_path / ".run_overrides" / "run-2"
    run_cwd.mkdir(parents=True)
    (run_cwd / "prefetch.log").write_text("x")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(controller_mod.shutil, "copy2", boom)
    controller_mod._cleanup_run_cwd(tmp_path, {"run_id": "run-2", "run_cwd": str(run_cwd)})
    assert not run_cwd.exists()


def test_cleanup_tolerates_a_run_that_never_spawned_a_downloader(tmp_path):
    """No prefetch.log is normal -- a full run that never reached its download phase."""
    run_cwd = tmp_path / ".run_overrides" / "run-3"
    run_cwd.mkdir(parents=True)
    (run_cwd / "config.yaml").write_text("focus_area_queries: []\n")

    controller_mod._cleanup_run_cwd(tmp_path, {"run_id": "run-3", "run_cwd": str(run_cwd)})

    assert not run_cwd.exists()
    assert (tmp_path / "config_run-3.yaml").exists()
    assert not (tmp_path / "prefetch_run-3.log").exists()


def test_cleanup_without_an_override_archives_nothing(tmp_path):
    """run_cwd == data_dir: an unedited run already writes prefetch.log durably into the data dir.
    Copying it onto itself would be wrong; the existing early return must be preserved."""
    (tmp_path / "prefetch.log").write_text("original")
    controller_mod._cleanup_run_cwd(tmp_path, {"run_id": "run-4", "run_cwd": str(tmp_path)})
    assert (tmp_path / "prefetch.log").read_text() == "original"
    assert not (tmp_path / "prefetch_run-4.log").exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_controller.py -k "archiv or cleanup" -v
rc=$?
```

Expected: the first three FAIL (nothing is archived today); the fourth should already PASS via the existing `run_cwd == data_dir` early return — if it fails, you have broken that guard.

- [ ] **Step 3: Implement**

Add above `_cleanup_run_cwd`:

```python
# D-7: what gets rescued from a run's override scratch dir before it is deleted, and the flat
# per-run name it lands under in the data dir -- matching the existing
# `ingest_run-<run_id>.log` / `ingest_events_<run_id>.jsonl` convention.
#
# `prefetch.log` holds the harvest diagnostics that answer "I added a tag and nothing changed"
# ("4044 candidate papers found, 4031 already cached/claimed, 13 to download" -- 2026-08-01).
# `config.yaml` is the other half of that question: which queries this run actually used. Neither
# exists anywhere else once the scratch dir is gone. `prefetch.pid` is deliberately excluded --
# process state, meaningless after the run ends.
_ARCHIVED_RUN_ARTIFACTS = (("prefetch.log", "prefetch_{run_id}.log"),
                           ("config.yaml", "config_{run_id}.yaml"))


def _archive_run_artifacts(data_dir: Path, run_cwd: Path, run_id: str) -> list[Path]:
    """Copy a run's durable-worth artifacts out of its scratch dir into `data_dir`.

    Best-effort by contract: `_cleanup_run_cwd` is reached from `reconcile()`, which runs on every
    `/api/status` poll, so a copy failure must never raise or prevent the cleanup it precedes. A
    missing source file is normal (a run that never spawned a downloader), not an error."""
```

Then in `_cleanup_run_cwd`, immediately before `shutil.rmtree(run_cwd, ignore_errors=True)`:

```python
    _archive_run_artifacts(data_dir, Path(run_cwd), str(manifest.get("run_id") or "unknown"))
```

The whole archive body sits in one `try/except Exception` that logs at WARNING and returns.
Use `shutil.copy2` (preserves mtime, which is what makes the archived log's age meaningful).
Do **not** move the run_id fallback into the format string — a manifest with no `run_id` should
produce `prefetch_unknown.log`, not a crash.

- [ ] **Step 4: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_controller.py -q
rc=$?
```

Expected `rc=0`, with every pre-existing `test_controller.py` test still passing — particularly the
existing `_cleanup_run_cwd` tests around `pause`/`resume` behavior, which must be unaffected.

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "Archive a run's prefetch.log and config before deleting its scratch dir

The harvest diagnostics that explain 'I added a tag and nothing changed' --
'4044 candidate papers found, 4031 already cached/claimed, 13 to download' --
lived only inside the run's override dir and were destroyed by
_cleanup_run_cwd's rmtree. Since D-5 composed tag edits into an override, that
is now every dashboard-started run.

Archived from inside _cleanup_run_cwd rather than at its four call sites: one
choke point, every path covered, and the next caller added gets it too. The
run's effective config.yaml goes with it -- 'which queries did this run use?'
is the other half of the same question and has no other record. Best-effort:
_cleanup_run_cwd is reached from reconcile() on every status poll, so a copy
failure must never block cleanup."
```

- [ ] **Step 6: Full suite and enforcement**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && python -m pytest -q
rc=$?
```

Then enforcement, per Global Constraints. Both `rc=0`.

- [ ] **Step 7: Verify against the live system — READ ONLY**

Confirm the live run's override dir still holds the artifacts this change will preserve, and that
you have **not** disturbed it:

```bash
ls -la /home/omar/ai-projects/research-system-rag-data/.run_overrides/run-30000-20260801_033744/
rc=$?
```

```bash
ps -p 842575 -o pid,etime= 2>/dev/null; ps -p 842587 -o pid,etime= 2>/dev/null
rc=$?
```

Both PIDs must still be alive. **Do not stop the run, do not delete the directory, do not trigger
cleanup against the real data dir.** Report both outputs.

- [ ] **Step 8: Push and open the PR** titled `D-7: archive per-run prefetch log and config before cleanup`. Do **not** merge. Poll `gh pr checks <n>` until final; both must `pass`.

---

## Report contract

Write your report to the path given in your dispatch. Return only: status, commit SHA, PR number, real `rc` for pytest and enforcement, the Step 7 output verbatim, explicit confirmation that PIDs 842575/842587 are still alive and the live override dir is intact, the `config.yaml` mtime, the final CI conclusion for each check by name, and confirmation the repo was left on `main` with the dashboard running.
