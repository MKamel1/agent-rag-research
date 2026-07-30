# Drop-in as a First-Class Run Type — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the existing `app/ingest_local.py` drop-in pipeline in the corpus dashboard — show what is waiting versus what actually reached the corpus, let the operator run it from the UI, and make a drop-in run take priority over downloads without ever interrupting one.

**Architecture:** Three seams, one per existing dashboard module, plus the frontend. `status.py` gains a pure filesystem+read-only-SQLite reader (`read_drop_in`). `controller.py` gains a spawn path (`start_drop_in`) and a queue-jump mechanism (`pending_drop_in` flag + `promote_pending_drop_in`). `server.py` exposes both over the existing `GET /api/status` / `POST /api/control` routes. No change to `app/ingest_local.py` itself — it already works.

**Tech Stack:** Python 3.12, stdlib `http.server`, `sqlite3` (read-only URI mode), `filelock`, pytest, pytest-socket.

## Global Constraints

- Deliverable 1 of `docs/superpowers/specs/2026-07-30-dashboard-dropin-and-usage-design.md` §2.
- **Depends on** the `dashboard-status-config-fix` branch (T-DOC90) being merged first. Rebase onto `main` before starting; if `_static_config` still takes no argument, that PR has not landed — stop and report `BLOCKED`.
- **Do not modify** `contracts/`, `rag/config.py`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/` — CODEOWNERS foundation-freeze.
- **Do not modify** `app/ingest_local.py`. It is the pipeline this exposes, not part of this work.
- **Never** write to `/home/omar/ai-projects/research-system-rag-data/papers.db`. Every DB read in this plan goes through `status._ro_connect`, which opens `file:...?mode=ro`.
- Never run `git stash`.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Do not merge any PR. Never pass `--admin` or a branch-protection bypass.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — chained in ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- Enforcement must be run as `GITHUB_EVENT_NAME=pull_request python -m ci.run_enforcement`. A `push`-scoped local pass has previously coexisted with a `pull_request`-scoped CI failure on the same branch.
- Absent and zero are different facts. Where a source is missing or unreadable, return `None`, never `0`.
- Tests run with `--disable-socket`. No test may fork a real subprocess: inject `spawn`.

## KNOWN TRAP — `Config.drop_in_dir` comes back RELATIVE

Verified on 2026-07-30 against the operator's real config:

```python
load_config('/home/omar/ai-projects/research-system-rag-data/config.yaml').drop_in_dir
# -> 'drop_in'          <-- RELATIVE
# ...while db_path      -> '/home/omar/.../research-system-rag-data/papers.db'  (absolute)
```

`rag/config.py::_resolve_paths` resolves a path field only when that field is **present in the
loaded YAML**. The operator's `config.yaml` does not set `drop_in_dir`, so the pydantic default
`"drop_in"` is applied *after* resolution and stays relative. A relative value then resolves against
whatever the reading process's cwd happens to be.

This matters twice, in opposite directions:

- The **dashboard** runs with `cwd=<repo root>`, where `drop_in/` really does exist and holds the
  operator's tray.
- `_spawn_drop_in` launches `app.ingest_local` with `cwd=data_dir`, and
  `/home/omar/ai-projects/research-system-rag-data/drop_in` **does not exist**. Left alone, a
  drop-in run would scan an empty/absent directory, stage nothing, log "drop dir empty", and exit 0
  — a silent no-op that looks like success.

**Required handling (do not skip, do not "fix" it in `rag/config.py`, which is foundation-frozen):**

1. Add one helper in `app/dashboard/controller.py` and use it in **both** places:

```python
def resolve_drop_dir(cfg: Config) -> Path:
    """`Config.drop_in_dir` is relative whenever config.yaml omits it (`rag/config.py::_resolve_paths`
    only resolves fields actually present in the YAML). A relative value would otherwise mean a
    different directory to the dashboard (cwd=<repo root>) than to the `app.ingest_local` child
    (cwd=<data_dir>) -- the dashboard would report a full tray while the run scanned an empty one
    and exited 0. Anchored on the repo root, which is where the tray actually lives and where the
    dashboard's own cwd already points."""
    d = Path(cfg.drop_in_dir)
    return d if d.is_absolute() else (_REPO_ROOT / d).resolve()
```

2. `_spawn_drop_in` must pass the resolved path **explicitly** to the child:
   `[..., "-m", "app.ingest_local", "--drop-dir", str(drop_dir)]`. The `--drop-dir` flag already
   exists (`app/ingest_local.py::_parse_args`); use it rather than relying on the child's cwd.

3. `_status_dict` must call `read_drop_in(controller_module.resolve_drop_dir(cfg), ...)`, and the
   `drop_in` block must include the resolved absolute path as `"dir"` so the operator can see which
   directory is being read instead of inferring it.

If a future `config.yaml` sets an absolute `drop_in_dir`, the helper passes it through unchanged and
all three call sites follow it automatically.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/dashboard/status.py` | pure reads, no writes, no imports of `controller` | add `read_drop_in` |
| `app/dashboard/controller.py` | run lifecycle via `run_manifest.json` + signals | add `_spawn_drop_in`, `start_drop_in`, `promote_pending_drop_in`; amend `_start_locked`, `_stop_locked` |
| `app/dashboard/server.py` | HTTP composition root | add `drop_in` status block, `start_drop_in` control action |
| `app/dashboard/static/` | frontend | add drop-in panel |

`status.py` must not import `controller.py` or vice versa — `run_manifest.json` on disk is their only shared channel (see `app/dashboard/__init__.py`). Task 1 touches only `status.py`; do not reach for controller state there.

---

### Task 1: `status.read_drop_in` — staged vs processed

**Files:**
- Modify: `app/dashboard/status.py` (append after `read_downloads`, ~line 390)
- Test: `app/dashboard/test_status.py`

**Interfaces:**
- Consumes: `status._ro_connect(db_path: Path) -> sqlite3.Connection | None` (already exists, line 126).
- Produces: `read_drop_in(drop_dir: str | Path, db_path: str | Path) -> dict` with the keys in Step 3. Task 4 calls it from `server.py::_status_dict`.

**Background the implementer needs:** `app/ingest_local.py` lays out the drop tree as `papers/` and `books/` (inbox), `done/` (staged into `pdf_cache`), `failed/` (quarantined, each PDF beside a `<name>.err` text file), `excluded/` (operator-excluded), plus `manifest-<UTC>.txt` files holding one `paper_id` per line.

The distinction this task exists to expose: a file in `done/` was only **staged** — copied into `pdf_cache` with a `paper_id` minted. It may still be unparsed, unembedded, or quarantined downstream. **Processed** means the corpus actually has it. That is the manifest `paper_id`s joined against `papers.db`.

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_status.py`:

```python
def test_read_drop_in_counts_each_bucket(tmp_path):
    drop = tmp_path / "drop_in"
    for sub in ("papers", "books", "done", "failed", "excluded"):
        (drop / sub).mkdir(parents=True)
    (drop / "papers" / "a.pdf").write_bytes(b"%PDF-1.4")
    (drop / "papers" / "b.pdf").write_bytes(b"%PDF-1.4")
    (drop / "books" / "c.pdf").write_bytes(b"%PDF-1.4")
    (drop / "done" / "a.pdf").write_bytes(b"%PDF-1.4")
    (drop / "failed" / "d.pdf").write_bytes(b"%PDF-1.4")
    (drop / "failed" / "d.pdf.err").write_text("unreadable PDF: bad xref")
    (drop / "excluded" / "e.pdf").write_bytes(b"%PDF-1.4")

    out = status.read_drop_in(drop, tmp_path / "nonexistent.db")

    assert out["pending_papers"] == 2
    assert out["pending_books"] == 1
    assert out["staged"] == 1
    assert out["failed"] == 1
    assert out["excluded"] == 1
    assert out["failure_reasons"] == [("unreadable PDF: bad xref", 1)]


def test_read_drop_in_processed_is_none_when_db_unreadable(tmp_path):
    """Absent and zero are different facts: a missing papers.db must not read as
    'zero dropped documents made it into the corpus'."""
    drop = tmp_path / "drop_in"
    drop.mkdir()
    (drop / "manifest-20260730T000000Z.txt").write_text("local:aaaaaaaaaaaa\n")

    out = status.read_drop_in(drop, tmp_path / "nonexistent.db")

    assert out["processed"] is None
    assert out["processed_papers"] is None
    assert out["processed_books"] is None


def test_read_drop_in_processed_counts_only_manifest_ids_at_stage_done(tmp_path):
    import sqlite3
    drop = tmp_path / "drop_in"
    drop.mkdir()
    (drop / "manifest-20260730T000000Z.txt").write_text(
        "local:aaaaaaaaaaaa\nlocal:bbbbbbbbbbbb\nlocal:cccccccccccc\n"
    )
    db = tmp_path / "papers.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE papers (paper_id TEXT PRIMARY KEY, stage TEXT, doc_type TEXT)")
    conn.executemany(
        "INSERT INTO papers VALUES (?, ?, ?)",
        [
            ("local:aaaaaaaaaaaa", "done", "paper"),   # counted
            ("local:bbbbbbbbbbbb", "done", "book"),    # counted
            ("local:cccccccccccc", "parsed", "book"),  # staged but NOT processed
            ("2501.00001", "done", "paper"),           # not from drop_in, must not count
        ],
    )
    conn.commit()
    conn.close()

    out = status.read_drop_in(drop, db)

    assert out["processed"] == 2
    assert out["processed_papers"] == 1
    assert out["processed_books"] == 1


def test_read_drop_in_tolerates_missing_tree(tmp_path):
    out = status.read_drop_in(tmp_path / "no_such_dir", tmp_path / "no.db")
    assert out["pending_papers"] == 0
    assert out["staged"] == 0
    assert out["processed"] is None
    assert out["latest_manifest"] is None
```

**Before writing the implementation, verify the real schema.** The test above assumes a `papers` table with `paper_id`, `stage`, and `doc_type` columns. Confirm against the live DB and adjust both test and implementation to the real names if they differ:

```bash
sqlite3 "file:/home/omar/ai-projects/research-system-rag-data/papers.db?mode=ro" ".schema papers"
rc=$?
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -k read_drop_in -v
rc=$?
```

Expected: FAIL, `AttributeError: module 'app.dashboard.status' has no attribute 'read_drop_in'`.

- [ ] **Step 3: Implement `read_drop_in`**

Append to `app/dashboard/status.py`, after `read_downloads`:

```python
# --- drop-in tray (app/ingest_local.py's drop_in/ tree) ------------------------------------------

_DROP_IN_DETAIL_CAP = 20  # per-file detail returned to the UI; counts are never capped

# `done/` means "staged into pdf_cache with a paper_id minted" -- NOT "in the corpus". A staged
# file can still be unparsed, unembedded, or quarantined downstream. The only honest source for
# "processed" is the manifest's paper_ids joined against papers.db, which is what `_processed_*`
# below does. Reporting `done/`'s count as progress would tell an operator the corpus has
# documents it does not have.
def read_drop_in(drop_dir: str | Path, db_path: str | Path) -> dict:
    drop_dir = Path(drop_dir)
    manifest_ids, latest_manifest = _read_drop_in_manifests(drop_dir)
    processed = _processed_counts(Path(db_path), manifest_ids)
    failure_reasons, truncated = _drop_in_failure_reasons(drop_dir / "failed")
    return {
        "pending_papers": _count_pdfs(drop_dir / "papers"),
        "pending_books": _count_pdfs(drop_dir / "books"),
        "staged": _count_pdfs(drop_dir / "done"),
        "failed": _count_pdfs(drop_dir / "failed"),
        "excluded": _count_pdfs(drop_dir / "excluded"),
        "failure_reasons": failure_reasons,
        "failure_reasons_truncated": truncated,
        "manifest_ids": len(manifest_ids),
        "latest_manifest": latest_manifest,
        **processed,
    }


def _count_pdfs(d: Path) -> int:
    """Counted without materializing a list -- a drop folder can hold thousands of files and this
    runs on every status poll."""
    if not d.is_dir():
        return 0
    return sum(1 for p in d.iterdir() if p.suffix.lower() == ".pdf")


def _read_drop_in_manifests(drop_dir: Path) -> tuple[set[str], str | None]:
    """Every `manifest-*.txt`'s paper_ids, unioned, plus the newest manifest's filename. Every
    manifest is read, not just the newest: each staging run writes its own, and a document staged
    three runs ago is still a dropped document."""
    if not drop_dir.is_dir():
        return set(), None
    manifests = sorted(drop_dir.glob("manifest-*.txt"))
    ids: set[str] = set()
    for m in manifests:
        try:
            ids.update(line.strip() for line in m.read_text().splitlines() if line.strip())
        except OSError:
            continue
    return ids, (manifests[-1].name if manifests else None)


def _processed_counts(db_path: Path, manifest_ids: set[str]) -> dict:
    """How many manifest paper_ids actually reached stage `done` in the corpus, split by doc_type.
    `None` (not 0) when the DB is missing/unreadable or there are no manifest ids to ask about --
    "we cannot tell" and "none made it" are different answers."""
    null = {"processed": None, "processed_papers": None, "processed_books": None}
    if not manifest_ids:
        return null
    conn = _ro_connect(db_path)
    if conn is None:
        return null
    try:
        placeholders = ",".join("?" * len(manifest_ids))
        rows = conn.execute(
            f"SELECT doc_type, COUNT(*) FROM papers "  # noqa: S608 - placeholders are '?' only
            f"WHERE stage = 'done' AND paper_id IN ({placeholders}) GROUP BY doc_type",
            tuple(manifest_ids),
        ).fetchall()
    except sqlite3.Error:
        return null
    finally:
        conn.close()
    by_type = {str(r[0]): int(r[1]) for r in rows}
    return {
        "processed": sum(by_type.values()),
        "processed_papers": by_type.get("paper", 0),
        "processed_books": by_type.get("book", 0),
    }


def _drop_in_failure_reasons(failed_dir: Path) -> tuple[list[tuple[str, int]], bool]:
    """`(reason, count)` pairs from `failed/*.err`, most common first, capped at
    `_DROP_IN_DETAIL_CAP`. The bool is True when reasons were dropped by that cap."""
    if not failed_dir.is_dir():
        return [], False
    counts: dict[str, int] = {}
    for err in failed_dir.glob("*.err"):
        try:
            reason = err.read_text().strip().splitlines()[0].strip()
        except (OSError, IndexError):
            continue
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ordered[:_DROP_IN_DETAIL_CAP], len(ordered) > _DROP_IN_DETAIL_CAP
```

If the `sqlite3` import is not already at the top of `status.py`, it is — line 126's `_ro_connect` uses it. Do not add a duplicate import.

**A note on the `IN (...)` query:** `manifest_ids` can grow unbounded. SQLite's default host-parameter limit is 32,766 in modern builds but was 999 historically. If `len(manifest_ids) > 900`, chunk the query into batches of 900 and sum the results rather than issuing one oversized statement.

- [ ] **Step 4: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -v
rc=$?
```

Expected: PASS, `rc=0`. Every pre-existing `test_status.py` test must still pass.

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/status.py app/dashboard/test_status.py
git commit -m "Add status.read_drop_in: staged vs processed drop-in tracking

done/ means 'staged into pdf_cache', not 'in the corpus'. read_drop_in reports
both: bucket counts straight off the drop tree, plus a 'processed' count that
joins every manifest's paper_ids against papers.db at stage=done, split by
doc_type. processed is None (not 0) when the DB is unreadable -- absent and
zero are different facts."
```

---

### Task 2: `controller.start_drop_in` — spawn a drop-in run

**Files:**
- Modify: `app/dashboard/controller.py` (`_spawn_drop_in` beside `_spawn_download` ~line 122; `start_drop_in` beside `start` ~line 774)
- Test: `app/dashboard/test_controller.py`

**Interfaces:**
- Consumes: `_control_lock(data_dir) -> filelock.FileLock`; `_build_manifest(...)`; `reconcile(data_dir) -> dict | None`; `_LIVE_STATUSES`; `DoubleRunError`.
- Produces: `start_drop_in(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict` returning the written manifest. Task 3 amends it; Task 4 calls it from `server.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_start_drop_in_spawns_ingest_local_and_writes_manifest(tmp_path):
    calls = []

    def fake_spawn(data_dir, target, parse_workers, events_path, log_path, **kwargs):
        calls.append(log_path)
        return 4242

    manifest = controller_mod.start_drop_in(tmp_path, spawn=fake_spawn)

    assert manifest["mode"] == "drop_in"
    assert manifest["status"] == "running"
    assert manifest["pid"] == 4242
    assert len(calls) == 1


def test_start_drop_in_refuses_while_another_run_is_live(tmp_path):
    """Guarded by the same DoubleRunError contract `start` uses -- Task 3 replaces this
    with queue-jump behavior."""
    controller_mod._write_manifest(tmp_path, {
        "run_id": "run-1", "status": "running", "pid": os.getpid(),
        "pid_starttime": None, "pid_cmdline": None, "mode": "download",
    })
    with pytest.raises(controller_mod.DoubleRunError):
        controller_mod.start_drop_in(tmp_path, spawn=lambda *a, **k: 1)
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_controller.py -k start_drop_in -v
rc=$?
```

Expected: FAIL, `AttributeError: ... has no attribute 'start_drop_in'`.

- [ ] **Step 3: Implement `_spawn_drop_in`**

Add beside `_spawn_download` in `app/dashboard/controller.py`. Same launch shape: `env PYTHONPATH=<repo>`, `cwd=data_dir`, own process group so `pause`/`stop`'s `os.killpg` reaches it.

```python
def _spawn_drop_in(data_dir: Path, target: int, parse_workers: int, events_path: Path,
                   log_path: Path) -> int:
    """Launches `app.ingest_local`, which stages everything under `cfg.drop_in_dir` into
    `pdf_cache` and then runs the normal ingest over the staged ids. Matches `SpawnFn`'s shape so
    `_call_spawn`/`pause`/`stop` need no changes; `target`/`parse_workers`/`events_path` do not
    apply (ingest_local's work is bounded by what is in the drop tray, not by a target) and are
    ignored, same as `_spawn_download` ignores them.

    `start_new_session=True` gives it its own process group, so `pause`/`stop`'s `os.killpg`
    reaches it exactly as it does a download or a full build."""
    drop_dir = resolve_drop_dir(_load_base_config(data_dir))
    cmd = ["env", f"PYTHONPATH={_REPO_ROOT}", sys.executable, "-m", "app.ingest_local",
           "--drop-dir", str(drop_dir)]
    log_f = log_path.open("a")
    proc = subprocess.Popen(
        cmd, cwd=str(data_dir), stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True,
    )
    return proc.pid
```

- [ ] **Step 4: Implement `start_drop_in`**

Add beside `start`. Read `_start_locked`'s existing body first and reuse its manifest-building calls rather than inventing new ones — in particular `_build_manifest`'s real signature, which this plan does not restate because it must match the code exactly.

```python
def start_drop_in(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict:
    """Start a drop-in ingest run (`app.ingest_local`) over whatever is sitting in the drop tray.

    `target`/`parse_workers` are not operator-settable for this run type: the work is bounded by
    the drop tray's contents. `target=0` is recorded in the manifest so `_crashed_before_target`
    (`done_count < target`) can never misclassify a clean drop-in finish as a crash."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _start_drop_in_locked(data_dir, spawn=spawn)


def _start_drop_in_locked(data_dir: Path, *, spawn: SpawnFn | None = None) -> dict:
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        raise DoubleRunError(
            f"run {manifest['run_id']!r} is still live (status={manifest['status']!r}) -- "
            "pause or stop it before starting a drop-in run"
        )
    if manifest is not None:
        _cleanup_run_cwd(data_dir, manifest)
    run_id = f"dropin-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    log_path = data_dir / "ingest_local.log"
    events_path = data_dir / f"ingest_events_{run_id}.jsonl"
    spawn_fn = spawn if spawn is not None else _spawn_drop_in
    pid = spawn_fn(data_dir, 0, 1, events_path, log_path)
    manifest = _build_manifest(
        run_id, pid, 0, 1, events_path, log_path, data_dir / "papers.db",
        run_cwd=data_dir, effective_cfg=_load_base_config(data_dir), mode="drop_in",
    )
    _write_manifest(data_dir, manifest)
    return manifest
```

`_build_manifest`'s real signature (`controller.py:703`) is
`(run_id, pid, target, parse_workers, events_path, log_path, db_path, paper_ids_file=None, *, run_cwd, effective_cfg, telemetry_poll_interval=None, batch_size=None, mode="full")`.
It already calls `_capture_identity(pid)` internally, which is what makes `_verified_pid` able to
tell a live drop-in run from a recycled PID — do not write a separate manifest builder that skips it.

- [ ] **Step 5: Verify `mode` is already surfaced**

`server.py:138`'s `_RUN_FIELDS` already includes `"mode"`, so `/api/status` reports `run.mode == "drop_in"` with no server change. Confirm:

```bash
grep -n '"mode"' app/dashboard/server.py
rc=$?
```

- [ ] **Step 6: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_controller.py -q
rc=$?
```

Expected: PASS, `rc=0`. No test may fork a real process — every one injects `spawn`.

- [ ] **Step 7: Commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "Add controller.start_drop_in: drop-in as a run mode

Spawns app.ingest_local through the same _control_lock / manifest / process-group
machinery every other run type uses, with mode='drop_in'. target=0 so
_crashed_before_target can never misread a clean drop-in finish as a crash.
_RUN_FIELDS already carries 'mode', so /api/status reports it unchanged."
```

---

### Task 3: Queue-jump priority

**Files:**
- Modify: `app/dashboard/controller.py` (`_start_drop_in_locked`, `_start_locked`, `_stop_locked`, new `promote_pending_drop_in`)
- Test: `app/dashboard/test_controller.py`

**Interfaces:**
- Produces: `promote_pending_drop_in(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict | None`. Task 4 calls it from `server.py::_status_dict`.

**Design note — why this is not done inside `reconcile()`.** The spec sketched "`reconcile()` spawns the pending run." That is unsafe as written: `reconcile` is called from `liveness()` with **no lock held**, and `server.py` runs on a `ThreadingHTTPServer`, so two concurrent `/api/status` polls could both observe `terminal + pending` and both spawn a drop-in run. The promotion therefore lives in its own function that takes `_control_lock` and re-reconciles inside it. `reconcile` stays a cheap, idempotent read as documented.

- [ ] **Step 1: Write the failing tests**

```python
def test_drop_in_queues_instead_of_raising_when_a_run_is_live(tmp_path):
    controller_mod._write_manifest(tmp_path, {
        "run_id": "run-1", "status": "running", "pid": os.getpid(),
        "pid_starttime": None, "pid_cmdline": None, "mode": "download", "target": 100,
    })
    spawned = []
    out = controller_mod.start_drop_in(tmp_path, spawn=lambda *a, **k: spawned.append(1))

    assert out["pending_drop_in"] is True
    assert spawned == [], "must NOT spawn while another run is live"


def test_promote_spawns_the_queued_drop_in_once_the_live_run_is_terminal(tmp_path):
    controller_mod._write_manifest(tmp_path, {
        "run_id": "run-1", "status": "done", "pid": 999999,
        "pid_starttime": None, "pid_cmdline": None, "mode": "download",
        "pending_drop_in": True,
    })
    spawned = []

    def fake_spawn(*a, **k):
        spawned.append(1)
        return 5150

    out = controller_mod.promote_pending_drop_in(tmp_path, spawn=fake_spawn)

    assert spawned == [1]
    assert out["mode"] == "drop_in"
    assert out["status"] == "running"
    assert not out.get("pending_drop_in")


def test_promote_is_a_noop_while_the_live_run_is_still_running(tmp_path):
    controller_mod._write_manifest(tmp_path, {
        "run_id": "run-1", "status": "running", "pid": os.getpid(),
        "pid_starttime": None, "pid_cmdline": None, "mode": "download", "target": 100,
        "pending_drop_in": True,
    })
    spawned = []
    out = controller_mod.promote_pending_drop_in(tmp_path, spawn=lambda *a, **k: spawned.append(1))

    assert spawned == []
    assert out is None


def test_start_refuses_a_download_while_a_drop_in_is_pending(tmp_path):
    """Without this, a download started the instant the previous one ends starves the queued
    drop-in indefinitely -- 'priority' that never fires."""
    controller_mod._write_manifest(tmp_path, {
        "run_id": "run-1", "status": "done", "pid": 999999,
        "pid_starttime": None, "pid_cmdline": None, "mode": "download",
        "pending_drop_in": True,
    })
    with pytest.raises(controller_mod.DropInPendingError):
        controller_mod.start(tmp_path, target=100, spawn=lambda *a, **k: 1)


def test_stop_clears_the_pending_flag(tmp_path):
    """The operator's escape hatch: if ingest_local wedges, `stop` must unblock downloads."""
    controller_mod._write_manifest(tmp_path, {
        "run_id": "run-1", "status": "running", "pid": os.getpid(),
        "pid_starttime": None, "pid_cmdline": None, "mode": "download",
        "pending_drop_in": True,
    })
    controller_mod.stop(tmp_path)
    assert not controller_mod._read_manifest(tmp_path).get("pending_drop_in")
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_controller.py -k "drop_in or promote" -v
rc=$?
```

Expected: FAIL.

- [ ] **Step 3: Add `DropInPendingError` beside `DoubleRunError`**

```python
class DropInPendingError(RuntimeError):
    """A drop-in run is queued and must go first. Raised when a download/full run is started
    while `pending_drop_in` is set -- without this refusal a fresh download can be started the
    instant the previous one ends, starving the queued drop-in forever."""
```

- [ ] **Step 4: Change `_start_drop_in_locked` to queue instead of raise**

Replace the `DoubleRunError` branch written in Task 2:

```python
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        # Queue-jump, not preemption: the live run is never signalled. `promote_pending_drop_in`
        # spawns this the moment that run reaches a terminal state.
        manifest["pending_drop_in"] = True
        _write_manifest(data_dir, manifest)
        return manifest
```

Delete the Task 2 test `test_start_drop_in_refuses_while_another_run_is_live` — Task 3 deliberately replaces that contract, and `test_drop_in_queues_instead_of_raising_when_a_run_is_live` is its successor. Note the deletion and the reason in your report.

- [ ] **Step 5: Implement `promote_pending_drop_in`**

```python
def promote_pending_drop_in(data_dir: str | Path, *,
                            spawn: SpawnFn | None = None) -> dict | None:
    """Spawn a queued drop-in run if the previously live run has reached a terminal state.
    Returns the new drop-in manifest, or `None` when there is nothing to promote.

    Takes `_control_lock` and re-reconciles INSIDE it. `reconcile()` itself must not spawn:
    `liveness()` calls it with no lock held, and `server.py` is a ThreadingHTTPServer, so two
    concurrent `/api/status` polls would otherwise both see `terminal + pending` and both spawn.
    Idempotent and safe to call on every status poll."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        manifest = reconcile(data_dir)
        if manifest is None or not manifest.get("pending_drop_in"):
            return None
        if manifest.get("status") in _LIVE_STATUSES:
            return None
        return _start_drop_in_locked(data_dir, spawn=spawn)
```

`_start_drop_in_locked` writes a fresh manifest for the new run, so `pending_drop_in` does not carry over — it lived on the *previous* run's manifest. Assert that in the test rather than clearing it explicitly.

- [ ] **Step 6: Add the refusal to `_start_locked` and the clear to `_stop_locked`**

In `_start_locked`, immediately after its existing `reconcile` + `DoubleRunError` check:

```python
    if manifest is not None and manifest.get("pending_drop_in"):
        raise DropInPendingError(
            "a drop-in run is queued and must run first -- it will start automatically, or "
            "stop() to clear it"
        )
```

In `_stop_locked`, clear the flag on the manifest it writes:

```python
    manifest["pending_drop_in"] = False
```

- [ ] **Step 7: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/ -q
rc=$?
```

Expected: PASS, `rc=0`.

- [ ] **Step 8: Commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "Queue-jump priority for drop-in runs

A drop-in requested while a run is live sets pending_drop_in instead of raising;
promote_pending_drop_in spawns it once that run is terminal. Promotion takes
_control_lock and re-reconciles inside it rather than spawning from reconcile(),
which liveness() calls unlocked on a ThreadingHTTPServer -- two concurrent status
polls would otherwise both spawn. start() refuses a download while a drop-in is
pending (otherwise the queued run starves); stop() clears the flag."
```

---

### Task 4: HTTP surface and frontend panel

**Files:**
- Modify: `app/dashboard/server.py` (`_status_dict`, the `POST /api/control` dispatch)
- Modify: `app/dashboard/static/` (the frontend file that renders the status blocks)
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `status.read_drop_in(drop_dir, db_path) -> dict` (Task 1); `controller.start_drop_in(data_dir, spawn=None) -> dict` and `controller.promote_pending_drop_in(data_dir, spawn=None) -> dict | None` (Tasks 2–3).

- [ ] **Step 1: Write the failing tests**

```python
def test_status_route_includes_drop_in_block(running_server):
    body = _get_status(running_server)
    block = body["drop_in"]
    for key in ("pending_papers", "pending_books", "staged", "processed",
                "failed", "excluded", "latest_manifest", "pending_drop_in"):
        assert key in block, f"missing {key}"


def test_control_start_drop_in_calls_controller(running_server, monkeypatch):
    called = []
    monkeypatch.setattr(
        server_mod.controller, "start_drop_in",
        lambda data_dir, **kw: called.append(data_dir) or {"run_id": "dropin-1", "mode": "drop_in"},
    )
    resp = _post_control(running_server, {"action": "start_drop_in"})
    assert resp["ok"] is True
    assert len(called) == 1
```

Use whatever `running_server` / status-GET / control-POST helpers `test_server.py` already defines rather than the `_get_status`/`_post_control` names above, which are illustrative. Match the file's existing conventions.

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_server.py -k drop_in -v
rc=$?
```

Expected: FAIL, `KeyError: 'drop_in'`.

- [ ] **Step 3: Add the `drop_in` block to `_status_dict`**

The drop directory comes from the config, not a hardcoded path — `Config.drop_in_dir` is the field `app/ingest_local.py` itself reads. In `_status_dict`:

```python
    # Promotion runs here, before the block is read, so a queued drop-in starts as soon as the
    # previous run goes terminal without the operator having to click anything. It is lock-guarded
    # and idempotent (controller.promote_pending_drop_in), so calling it on every poll is safe.
    controller_module.promote_pending_drop_in(data_dir)
```

and in the returned dict:

```python
        "drop_in": {
            **status_module.read_drop_in(drop_dir, data_dir / "papers.db"),
            "dir": str(drop_dir),
            "pending_drop_in": bool(live.get("pending_drop_in")),
        },
```

where `drop_dir = controller_module.resolve_drop_dir(_static_config(data_dir))`, computed once near
the top of `_status_dict`. **Do not** pass `_static_config(data_dir).drop_in_dir` directly — see the
KNOWN TRAP section: it is relative, and the dashboard and the spawned child have different working
directories, so a raw value would have the dashboard reporting a full tray while the run scans an
empty one.

`live` is already `controller_module.liveness(data_dir) or {}` at the top of `_status_dict`. Move the `promote_pending_drop_in` call **above** that `liveness` call so the block reflects the promotion that just happened, and re-read `live` after it.

`Config.drop_in_dir` exists (`contracts/config.py:76`, default `"drop_in"`). Do not add fields to
`contracts/config.py` — it is foundation-frozen.

- [ ] **Step 4: Add the `start_drop_in` control action**

In the `POST /api/control` dispatch, alongside the existing `start`/`pause`/`resume`/`stop`/`retarget` actions:

```python
            elif action == "start_drop_in":
                result = controller_module.start_drop_in(data_dir)
```

Map `DropInPendingError` to the same HTTP status the dispatch already uses for `DoubleRunError` — find that mapping and reuse it; do not invent a new status code.

**No `scan`/`check` action.** A check is a read and lives in `GET /api/status`.

- [ ] **Step 5: Add the frontend panel**

`app/dashboard/static/index.html` is the entire frontend — a single ~45 KB file with inline markup, CSS, and JS. Add a "Drop-in tray" panel there, matching the existing panels' structure and styling rather than inventing a new idiom. It renders: pending papers, pending books, staged, **processed** (with `processed_papers` / `processed_books` beneath), failed with the top `failure_reasons`, excluded, and the resolved `dir` so the operator can see which directory is being read. Add a "Run drop-in now" button that POSTs `{"action": "start_drop_in"}` with the `X-Dashboard-Token` header, exactly as the existing control buttons do.

When `drop_in.pending_drop_in` is true, the button shows a queued state and the panel names the run it is waiting on (`run.run_id`). When `processed` is `null`, render "unknown" — **not** `0`; the whole point of the field is that those are different facts.

- [ ] **Step 6: Run the full suite and enforcement**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest -q
rc=$?
```

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  GITHUB_EVENT_NAME=pull_request python -m ci.run_enforcement
rc=$?
```

Expected: both `rc=0`.

- [ ] **Step 7: Live verification**

```bash
cd /home/omar/ai-projects/research-system-rag && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

```bash
D=/home/omar/ai-projects/research-system-rag-data
curl -s -m 60 -H "X-Dashboard-Token: $(cat $D/.dashboard_token)" \
  http://127.0.0.1:8700/api/status | python3 -c "import json,sys; print(json.load(sys.stdin)['drop_in'])"
rc=$?
```

Expected: the real drop-in block for the operator's tray. `GET` only; nothing is written and no run is started. Report the actual output.

- [ ] **Step 8: Commit and open the PR**

```bash
git add app/dashboard/server.py app/dashboard/test_server.py app/dashboard/static/
git commit -m "Expose the drop-in tray and its run control in the dashboard

GET /api/status gains a drop_in block (bucket counts, processed-vs-staged, top
failure reasons, pending_drop_in); POST /api/control gains start_drop_in. Queued
drop-ins are promoted on each poll via the lock-guarded, idempotent
promote_pending_drop_in. No scan/check action: a check is a read, so it lives in
GET /api/status."
git push -u origin HEAD
```

Open the PR describing all four tasks. Do **not** merge. Report the PR number.

---

## Report contract

Write your full report to the report file path given in your dispatch. Return only: status, commit SHAs, PR number, a one-line test summary with real `rc` values, the Step 7 `drop_in` output, and any concerns — including the Task 3 Step 4 test deletion and its reason.
