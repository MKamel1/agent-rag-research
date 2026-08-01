# D-6: Downloader Tracking, Restart Control, Tag-Staleness Warning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard able to see and stop *any* live downloader, add a safe Restart control, and warn when tag edits have not yet reached the running downloader.

**Architecture:** Three additions, all read-mostly. `status.read_downloader` gains a process-table scan so an untracked `app.prefetch_pdfs` is visible instead of invisible. `controller` gains `restart_downloader` (stop + start as one locked operation) and orphan termination. `status` compares `tag_pool.json`'s mtime against the live downloader's start time to flag pending tag changes.

**Tech Stack:** Python 3.12, stdlib `os`/`pathlib`/`subprocess`, `/proc`, `filelock`, pytest, pytest-socket.

## Global Constraints

- Backlog **D-6** (`docs/BACKLOG.md`). Operator decisions (2026-08-01): fix tracking **and** add the Restart button; detect staleness by mtime comparison.
- **Do not modify** `contracts/`, `rag/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`, `app/prefetch_pdfs.py`, or `app/build_corpus.py`.
- **Do not make `prefetch_pdfs` reload config mid-loop.** Explicit non-goal: swapping query sets underneath a live harvest is a larger behavioural change than this fixes, and a restart is cheap.
- **Do not auto-restart the downloader on a tag change.** The operator decides when harvesting changes.
- **Never** write `<data_dir>/config.yaml` (mtime must stay `2026-07-17 12:22:42`), `tag_pool.json`, or `papers.db`. No ingest, rechunk, delete, snapshot.
- **Do not kill the operator's live downloader during development.** It is `run-30000-20260801_012157`, pid 655538, started 2026-08-01. Tests use fake PIDs and `tmp_path`.
- Never `git stash` (there is an unrelated `stash@{0}` on the stack — leave it). Never merge a PR; never `--admin`.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b downloader-tracking-restart origin/main`.
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

## Root cause (established 2026-08-01 — do not re-derive)

`app/build_corpus.py` is a supervisor that launches `app.prefetch_pdfs` as a child, deliberately
**without** `start_new_session` so the child shares its process group and dies with it (that
module's own "Process-group placement" note).

The orphan observed this session started **Jul 30 21:38** and was still alive ~20 hours later —
predating the last full run by a day. So a `build_corpus` supervisor ended without its prefetch
child dying, and nothing in the system noticed. Measured state:

```
prefetch.pid  -> 3757989   DEAD
manifest pid  -> 196059    DEAD   (a finished full run)
actual runner -> 3012944   ALIVE  <- tracked by NEITHER
```

The operator-facing consequence: "stop → change tags → start" fails silently. `stop` acts on the
manifest PID (dead, kills nothing), then `download` spawns a second prefetcher beside the orphan —
two processes harvesting arXiv with different query sets.

**`prefetch.pid` is written by both `build_corpus` and `controller._spawn_download` and is
reconciled by nobody.** It is still stale after this session's restart.

---

### Task 1: See every live downloader, tracked or not

**Files:** Modify `app/dashboard/status.py` (`read_downloader` ~line 490). Test: `app/dashboard/test_status.py`.

**Interfaces:** Produces `read_downloader(run_cwd, manifest_pid: int | None = None) -> dict` with the existing keys plus `live_pids: list[int]`, `orphan: bool`, `tracked_pid: int | None`.

The authority becomes **the process table**, not a pid file: scan `/proc` for processes whose
cmdline names `app.prefetch_pdfs`. A pid file can be stale; a running process cannot.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_downloader_reports_an_untracked_live_downloader_as_an_orphan(tmp_path, monkeypatch):
    """The 20-hour blind spot: a prefetch process alive but named by neither prefetch.pid nor the
    manifest was invisible to the dashboard entirely."""
    monkeypatch.setattr(status, "_live_prefetch_pids", lambda: [4242])
    out = status.read_downloader(tmp_path, manifest_pid=None)
    assert out["live_pids"] == [4242]
    assert out["orphan"] is True


def test_read_downloader_is_not_an_orphan_when_the_manifest_names_it(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "_live_prefetch_pids", lambda: [4242])
    out = status.read_downloader(tmp_path, manifest_pid=4242)
    assert out["orphan"] is False
    assert out["tracked_pid"] == 4242


def test_read_downloader_no_live_process_is_not_an_orphan(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "_live_prefetch_pids", lambda: [])
    out = status.read_downloader(tmp_path, manifest_pid=None)
    assert out["live_pids"] == []
    assert out["orphan"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -k read_downloader -v
rc=$?
```

- [ ] **Step 3: Implement**

```python
def _live_prefetch_pids() -> list[int]:
    """Every live `app.prefetch_pdfs` PID, from the process table rather than a pid file.

    `prefetch.pid` is written by BOTH `app/build_corpus.py` and
    `controller._spawn_download`, and reconciled by neither -- it was stale in every case
    observed on 2026-08-01. A running process cannot be stale, so the process table is the
    authority and the pid file becomes advisory.

    Reuses `_is_live_prefetch`'s existing cmdline identity check, so a recycled PID cannot
    masquerade as a downloader."""
```

Iterate `/proc/<pid>/cmdline`, keep entries containing `app.prefetch_pdfs`, ignore unreadable
entries (races and permission errors are normal while scanning `/proc`). Never raise into a status
poll.

`orphan` is `True` iff at least one live PID is not `manifest_pid`. Keep every existing
`read_downloader` key — `server.py` and the frontend already read them; this task is additive apart
from the new parameter.

`server.py` passes `live.get("pid") if live.get("mode") == "download" else None` as `manifest_pid`
— a full run's PID is a `build_corpus` supervisor, not a downloader, so passing it would mark a
legitimately-tracked child as an orphan.

- [ ] **Step 4: Test and commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -q
rc=$?
```

```bash
git add app/dashboard/status.py app/dashboard/test_status.py
git commit -m "read_downloader: find live downloaders in the process table, flag orphans

prefetch.pid is written by both build_corpus and controller._spawn_download and
reconciled by neither -- it was stale in every case observed on 2026-08-01,
while a real prefetch_pdfs ran for ~20 hours tracked by nothing. A pid file can
be stale; a running process cannot, so /proc is the authority and the pid file
becomes advisory."
```

### Task 2: `restart_downloader`, and a stop that reaches orphans

**Files:** Modify `app/dashboard/controller.py`. Test: `app/dashboard/test_controller.py`.

**Interfaces:** Produces `restart_downloader(data_dir, *, spawn=None, live_pids=None) -> dict` and `terminate_orphan_downloaders(data_dir, *, live_pids=None) -> list[int]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_restart_downloader_terminates_then_spawns_exactly_once(tmp_path):
    killed, spawned = [], []
    controller_mod._write_manifest(tmp_path, {
        "run_id": "dl-1", "status": "running", "pid": 4242,
        "pid_starttime": None, "pid_cmdline": None, "mode": "download", "target": 30000,
    })
    out = controller_mod.restart_downloader(
        tmp_path,
        spawn=lambda *a, **k: (spawned.append(1) or 9999),
        live_pids=lambda: [4242],
    )
    assert out["mode"] == "download"
    assert out["status"] == "running"
    assert out["pid"] == 9999
    assert spawned == [1]


def test_restart_downloader_also_terminates_an_untracked_orphan(tmp_path):
    """The 2026-08-01 bug: stop acted on a dead manifest pid and left a live orphan running,
    so a subsequent start produced TWO downloaders."""
    controller_mod._write_manifest(tmp_path, {
        "run_id": "dl-1", "status": "done", "pid": 111,   # dead
        "pid_starttime": None, "pid_cmdline": None, "mode": "download",
    })
    killed = []
    controller_mod.restart_downloader(
        tmp_path,
        spawn=lambda *a, **k: 9999,
        live_pids=lambda: [3012944],                       # orphan, named by nothing
        terminate=lambda pid: killed.append(pid) or True,
    )
    assert killed == [3012944], "the orphan must be terminated before a fresh downloader starts"


def test_terminate_orphan_downloaders_leaves_the_tracked_one_alone(tmp_path):
    controller_mod._write_manifest(tmp_path, {
        "run_id": "dl-1", "status": "running", "pid": 4242,
        "pid_starttime": None, "pid_cmdline": None, "mode": "download",
    })
    killed = []
    out = controller_mod.terminate_orphan_downloaders(
        tmp_path, live_pids=lambda: [4242, 5555],
        terminate=lambda pid: killed.append(pid) or True,
    )
    assert killed == [5555] and out == [5555]
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: implement**.

Both functions take `_control_lock(data_dir)` for their whole check-then-act, like every other
control op. `restart_downloader` = terminate the tracked downloader (if any) **plus every orphan**,
then spawn a fresh one via the existing `mode="download"` path — one locked operation, so no window
exists in which a second downloader can be started.

`live_pids` and `terminate` are injectable (defaulting to `status._live_prefetch_pids` and
`_terminate_with_escalation`) so **no test ever signals a real process**.

Termination reuses `_terminate_with_escalation`, which already does TERM → wait → KILL.

- [ ] **Step 4: Test and commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "Add restart_downloader and orphan termination

stop acted on the manifest pid alone, so a downloader orphaned by a dead
build_corpus supervisor survived it -- and a following start produced two
prefetchers harvesting different query sets. restart_downloader terminates the
tracked downloader AND every orphan, then spawns one fresh, all under a single
_control_lock so no window exists for a duplicate."
```

### Task 3: Tag-staleness warning

**Files:** Modify `app/dashboard/status.py`. Test: `app/dashboard/test_status.py`.

**The fact this rests on:** `app/prefetch_pdfs.py:433` calls `load_config()` **once**, before its
forever-loop, and never re-reads. A running downloader keeps its launch-time queries no matter what
the Tags panel shows.

- [ ] **Step 1: Write the failing tests**

```python
def test_tags_pending_when_the_pool_was_edited_after_the_downloader_started(tmp_path, monkeypatch):
    pool = tmp_path / "tag_pool.json"
    pool.write_text('{"active": ["a"], "held": []}')
    # downloader started an hour before the pool was last written
    monkeypatch.setattr(status, "_process_start_epoch", lambda pid: pool.stat().st_mtime - 3600)
    out = status.read_downloader(tmp_path, manifest_pid=4242,
                                 live_pids=lambda: [4242], data_dir=tmp_path)
    assert out["tags_pending"] is True


def test_tags_not_pending_when_the_downloader_started_after_the_last_edit(tmp_path, monkeypatch):
    pool = tmp_path / "tag_pool.json"
    pool.write_text('{"active": ["a"], "held": []}')
    monkeypatch.setattr(status, "_process_start_epoch", lambda pid: pool.stat().st_mtime + 3600)
    out = status.read_downloader(tmp_path, manifest_pid=4242,
                                 live_pids=lambda: [4242], data_dir=tmp_path)
    assert out["tags_pending"] is False


def test_tags_pending_is_none_when_no_downloader_is_running(tmp_path, monkeypatch):
    """Absent != false. With nothing running there is nothing for tags to be pending against."""
    out = status.read_downloader(tmp_path, manifest_pid=None,
                                 live_pids=lambda: [], data_dir=tmp_path)
    assert out["tags_pending"] is None
```

Adjust the exact signature to match what Tasks 1–2 produced; the assertions are what matter.

- [ ] **Step 2–3: Run, implement.** `_process_start_epoch(pid)` reads field 22 of `/proc/<pid>/stat`
(jiffies since boot), converts via `/proc/uptime` and `os.sysconf("SC_CLK_TCK")`, and returns
`None` on any failure. `tags_pending` is `True` iff a downloader is live **and**
`tag_pool.json`'s mtime is newer than that start time; `None` when no downloader is live or the
start time cannot be read — **never a fabricated `False`**.

- [ ] **Step 4: Test and commit**

```bash
git add app/dashboard/status.py app/dashboard/test_status.py
git commit -m "Warn when tag edits postdate the running downloader

prefetch_pdfs calls load_config() once before its forever-loop and never
re-reads, so a running downloader keeps its launch-time queries regardless of
the Tags panel. Comparing tag_pool.json's mtime against the process start time
needs no new state and catches edits made outside the dashboard too."
```

### Task 4: HTTP surface and UI

**Files:** Modify `app/dashboard/server.py`, `app/dashboard/static/index.html`. Test: `app/dashboard/test_server.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_route_downloader_block_exposes_orphan_and_tags_pending(running_server):
    body = _get_status(running_server)
    for key in ("live_pids", "orphan", "tags_pending"):
        assert key in body["downloader"], f"missing {key}"


def test_control_restart_downloader_calls_controller(running_server, monkeypatch):
    called = []
    monkeypatch.setattr(server_mod.controller, "restart_downloader",
                        lambda data_dir, **kw: called.append(data_dir) or {"mode": "download"})
    resp = _post_control(running_server, {"action": "restart_downloader"})
    assert resp["ok"] is True and len(called) == 1
```

Use the file's own fixtures rather than the illustrative helper names.

- [ ] **Step 2–4: Run, implement, verify.**

`server.py`: pass `manifest_pid` (only for `mode == "download"`) and `data_dir` into
`read_downloader`; add a `restart_downloader` control action.

`index.html`: a **Restart downloader** button in the downloads panel, plus two states:

- when `downloader.tags_pending` — *"Tag changes pending — restart the downloader to apply. A running downloader keeps the queries it started with."*
- when `downloader.orphan` — *"An untracked downloader is running (pid N). Restart to take control of it."*

Both sit next to the same button that fixes them. No confirm on restart: it is reversible, unlike
tag purge.

- [ ] **Step 5: Full suite and enforcement** — both `rc=0`.

- [ ] **Step 6: Live verification, GET-only**

```bash
cd /home/omar/ai-projects/research-system-rag && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

```bash
D=/home/omar/ai-projects/research-system-rag-data
curl -s -m 90 -H "X-Dashboard-Token: $(cat $D/.dashboard_token)" http://127.0.0.1:8700/api/status \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['downloader']; print({k: d.get(k) for k in ('live_pids','orphan','tracked_pid','tags_pending','prefetch_alive')})"
rc=$?
```

Expected against the live system: `live_pids` contains **655538** (the tracked downloader started
this session), `orphan: False`, `tags_pending: False`. **Do NOT press restart, do NOT terminate
anything** — the operator's downloader must keep running.

Then leave the repo on `main` with the dashboard running:

```bash
cd /home/omar/ai-projects/research-system-rag && git checkout main && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

- [ ] **Step 7: Commit, push, open the PR** titled `D-6: downloader tracking, restart control, tag-staleness warning`. Do **not** merge. Poll `gh pr checks <n>` until final; both must `pass`.

---

## Report contract

Write your report to the path given in your dispatch. Return only: status, commit SHAs, PR number, real `rc` for pytest and enforcement, the Step 6 output verbatim, confirmation that the live downloader (pid 655538) was **not** terminated and `config.yaml`/`tag_pool.json` were not modified, the final CI conclusion for each check by name, and confirmation the repo was left on `main` with the dashboard running.
