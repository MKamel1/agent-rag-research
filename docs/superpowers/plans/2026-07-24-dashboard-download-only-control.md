# Dashboard Download-Only Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the dashboard operator download PDFs (via the existing standalone `app.prefetch_pdfs`) without committing GPU time to pass1/pass2, then run the full pipeline later once the GPU is free.

**Architecture:** Add a `mode: "full" | "download"` flag to the existing single-run dashboard control-plane (`app/dashboard/controller.py`'s manifest/lock/spawn machinery) instead of building a second parallel lifecycle. `mode="download"` changes only which command gets spawned (`app.prefetch_pdfs` instead of `app.build_corpus`) — everything else (double-run guard, pause/resume/stop, keyword/date/category override reuse) already works unchanged because it operates on "whatever the live manifest says," not on what was launched.

**Tech Stack:** Python 3 stdlib (`subprocess`, `sqlite3`, `http.server`), `filelock`, `pydantic` (`contracts.config.Config`), vanilla JS/HTML (no framework) for the dashboard frontend.

## Global Constraints

- Every existing caller/test that omits `mode`/doesn't inject a `spawn` fake must see byte-for-byte unchanged behavior (`mode` defaults to `"full"`, which resolves to today's real `_spawn`/`app.build_corpus`).
- `app/dashboard/status.py::read_downloader` and `app/build_corpus.py::ensure_prefetch_running` must need **zero code changes** — a download-only run's PID/log files must land at the exact paths those already read (`<run_cwd>/prefetch.pid`, `<run_cwd>/prefetch.log`).
- No new dependency lock/manifest file — download-only reuses `run_manifest.json` + `.control.lock`, so mutual exclusion with a full run is automatic (the existing `DoubleRunError` guard).
- Spec: `docs/DESIGN-download-only-and-quarantine-fixes.md`, "Part 1 — Download-only control".

---

### Task 1: `controller.py` — `mode="download"` can start a run

**Files:**
- Modify: `app/dashboard/controller.py` (imports/constants ~line 79-111, `_start_locked`/`start` ~line 720-816, `_build_manifest` ~line 651-696)
- Test: `app/dashboard/test_controller.py`

**Interfaces:**
- Produces: `controller._spawn_download(data_dir: Path, target: int, parse_workers: int, events_path: Path, log_path: Path) -> int` — matches `SpawnFn`'s shape (`Callable[[Path, int, int, Path, Path], int]`), writes `<data_dir>/prefetch.pid`.
- Produces: `controller.start(data_dir, target, parse_workers=3, *, mode: str = "full", ..., spawn: SpawnFn | None = None) -> dict` — `mode` is a new keyword-only param; `spawn`'s default changes from `_spawn` to `None` (resolved internally by mode when the caller doesn't inject one).
- Produces: manifest dicts now always carry a `"mode"` key (`"full"` or `"download"`).
- Consumes: existing `_call_spawn`, `_maybe_build_override`, `_build_manifest`, `reconcile`, `_write_manifest`, `_REPO_ROOT`, `_cleanup_run_cwd` — unchanged signatures except `_build_manifest` (see below).

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_controller.py`, near the existing `# --- start: the double-run guard` section (after `test_start_allowed_again_once_prior_run_confirmed_dead`, ~line 88):

```python
# --- T-DOC78: mode="download" -- a bare-downloader run sharing the same manifest/lock ----------


def test_start_default_mode_is_full_and_recorded_in_manifest(tmp_path):
    """Every existing caller/test omits `mode` -- must resolve to `"full"`, today's exact
    behavior, not silently become download-only."""
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        assert manifest["mode"] == "full"
    finally:
        _cleanup(manifest)


def test_start_with_mode_download_records_mode_in_manifest(tmp_path):
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        assert manifest["mode"] == "download"
        assert manifest["status"] == "running"
    finally:
        _cleanup(manifest)


def test_start_download_refused_while_a_full_run_is_live(tmp_path):
    """Mutual exclusion is the EXISTING double-run guard, mode-agnostic -- no new locking code."""
    full = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        with pytest.raises(DoubleRunError):
            controller_mod.start(
                tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
            )
    finally:
        _cleanup(full)


def test_start_full_refused_while_a_download_only_run_is_live(tmp_path):
    download = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        with pytest.raises(DoubleRunError):
            controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    finally:
        _cleanup(download)


def test_start_download_writes_prefetch_log_at_run_cwd_not_ingest_log(tmp_path):
    """`app/dashboard/status.py::read_downloader` hardcodes the log filename `prefetch.log` -- a
    download-only run's manifest must point at that exact name, not the usual
    `ingest_<run_id>.log`, or the dashboard's downloader-pace display goes blank."""
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        assert manifest["log_path"] == str(tmp_path / "prefetch.log")
    finally:
        _cleanup(manifest)


def test_start_full_still_writes_ingest_log_unchanged(tmp_path):
    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        assert manifest["log_path"] == str(tmp_path / f"ingest_{manifest['run_id']}.log")
    finally:
        _cleanup(manifest)


def test_start_download_reuses_keywords_override_same_as_a_full_run(tmp_path):
    """T-DOC78: "download now" must use the same keywords staged in the Apply panel --
    `_maybe_build_override` is mode-agnostic; this proves `mode="download"` reaches it too, via
    the same override path `test_start_with_keywords_augments_not_replaces_and_writes_override_config`
    already proves for a full run."""
    calls = []
    base_cfg = controller_mod.load_config(controller_mod._REPO_ROOT / "config.yaml")
    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download",
        keywords=["zzz-test-keyword"], spawn=_kwargs_spawn(calls),
    )
    try:
        override_dir = calls[0]["cwd"]
        assert override_dir != tmp_path  # launched in a scratch dir, not the real data_dir
        assert manifest["run_cwd"] == str(override_dir)
        written_cfg = controller_mod.load_config(Path(override_dir) / "config.yaml")
        assert written_cfg.focus_area_queries == base_cfg.focus_area_queries + ["zzz-test-keyword"]
        assert manifest["mode"] == "download"
    finally:
        _cleanup(manifest)


def test_real_spawn_download_launches_prefetch_pdfs_not_build_corpus(tmp_path, monkeypatch):
    """T-DOC78: `mode="download"`'s real launch command must be `python -m app.prefetch_pdfs` --
    no --target/--parse-workers/--events-path flags (it has none), no GPU, no pass1/pass2. Also
    writes `<data_dir>/prefetch.pid` -- the SAME filename `app/build_corpus.py::_spawn_prefetch`
    already writes, so `app/dashboard/status.py::read_downloader` and
    `app/build_corpus.py::ensure_prefetch_running` need zero changes to find it."""
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            self.pid = 999997

    monkeypatch.setattr(controller_mod.subprocess, "Popen", _FakePopen)
    log_path = tmp_path / "prefetch.log"

    pid = controller_mod._spawn_download(tmp_path, 30000, 1, tmp_path / "events.jsonl", log_path)

    assert pid == 999997
    cmd = captured["cmd"]
    assert "app.prefetch_pdfs" in cmd
    assert "app.build_corpus" not in cmd
    assert "--target" not in cmd
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["start_new_session"] is True
    assert (tmp_path / "prefetch.pid").read_text() == "999997"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_controller.py -k "download or mode_is_full or ingest_log_unchanged" -v`
Expected: FAIL — `TypeError: start() got an unexpected keyword argument 'mode'` (and `_spawn_download` doesn't exist yet).

- [ ] **Step 3: Add `_spawn_download` and the `mode` field**

In `app/dashboard/controller.py`, add right after the `SpawnFn` type alias (~line 111, before `class DoubleRunError`):

```python
# Same filename `app/build_corpus.py::_spawn_prefetch`/`_write_prefetch_pid` already write --
# duplicated rather than imported (this module's own "own your own copies" convention, e.g.
# `_OVERRIDE_PATH_FIELDS` above) so `app/dashboard/status.py::read_downloader` and
# `app/build_corpus.py::ensure_prefetch_running` (which only check "is a live app.prefetch_pdfs at
# this path," never who launched it) keep working against a download-only run with zero changes.
_PREFETCH_PID_NAME = "prefetch.pid"


def _spawn_download(data_dir: Path, target: int, parse_workers: int, events_path: Path,
                     log_path: Path) -> int:
    """T-DOC78: launches `app.prefetch_pdfs` directly -- no MinerU/GPU, no pass1/pass2 -- instead
    of `app.build_corpus`. Matches `SpawnFn`'s shape so `_call_spawn`/`resume` need no changes;
    `target`/`parse_workers`/`events_path` don't apply to a bare downloader and are ignored
    (`app.prefetch_pdfs` reads its own stopping point from `config.prefetch_target`, unaffected by
    this run's `target`). `log_path` is expected to already be `<run_cwd>/prefetch.log` --
    `_start_locked` computes that when `mode == "download"` -- so
    `status.py::read_downloader`'s hardcoded log name keeps finding real pace lines.

    Same launch shape as `_spawn`: `env PYTHONPATH=<repo>`, `cwd=data_dir`, its own process group
    (`start_new_session=True`) so pause/stop's `os.killpg` reaches it."""
    cmd = ["env", f"PYTHONPATH={_REPO_ROOT}", sys.executable, "-m", "app.prefetch_pdfs"]
    log_f = log_path.open("a")
    proc = subprocess.Popen(
        cmd, cwd=str(data_dir), stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True,
    )
    (data_dir / _PREFETCH_PID_NAME).write_text(str(proc.pid))
    return proc.pid
```

- [ ] **Step 4: Thread `mode` through `_build_manifest`**

Find `_build_manifest` (~line 651). Change its signature and the returned dict:

```python
def _build_manifest(
    run_id: str, pid: int, target: int, parse_workers: int, events_path: Path, log_path: Path,
    db_path: Path, paper_ids_file: Path | None = None, *,
    run_cwd: Path, effective_cfg: Config,
    telemetry_poll_interval: float | None = None, batch_size: int | None = None,
    mode: str = "full",
) -> dict:
    starttime, cmdline = _capture_identity(pid)
    return {
        "run_id": run_id,
        "pid": pid,
        "pid_starttime": starttime,
        "pid_cmdline": cmdline,
        "status": "running",
        "mode": mode,
        "target": target,
```

(Everything else in the returned dict is unchanged — just insert the `"mode": mode,` line right after `"status": "running",`.)

- [ ] **Step 5: Thread `mode` through `start`/`_start_locked`**

Find `_start_locked` (~line 763). Replace its signature and body:

```python
def _start_locked(data_dir: Path, target: int, parse_workers: int = 3, *,
                   paper_ids_file: str | Path | None = None,
                   telemetry_poll_interval: float | None = None, batch_size: int | None = None,
                   keywords: list[str] | None = None, remove_keywords: list[str] | None = None,
                   parse_batch_size: int | None = None,
                   arxiv_categories: list[str] | None = None,
                   arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
                   ordering: str | None = None,
                   stranded_policy: str | None = None,
                   mode: str = "full",
                   spawn: SpawnFn | None = None) -> dict:
    """`start`'s actual body -- called with `_control_lock(data_dir)` already held (by `start`
    itself, or by `retarget` wrapping both halves in one acquisition).

    T-DOC78: `mode="download"` launches `app.prefetch_pdfs` (`_spawn_download`) instead of
    `app.build_corpus` (`_spawn`) -- no GPU, no pass1/pass2. `spawn`'s default is resolved HERE
    (not bound as a default parameter value) so a production caller that never passes `spawn`
    still gets the real `_spawn`/`_spawn_download` picked by `mode`; a test that injects a fake
    `spawn` bypasses this resolution entirely, unaffected by `mode`."""
    manifest = reconcile(data_dir)
    if manifest is not None and manifest.get("status") in _LIVE_STATUSES:
        raise DoubleRunError(
            f"run {manifest['run_id']!r} is still live (status={manifest['status']!r}) -- "
            "pause or stop it before starting a fresh run"
        )
    if manifest is not None:
        _cleanup_run_cwd(data_dir, manifest)

    paper_ids_file = Path(paper_ids_file) if paper_ids_file is not None else None
    run_id = f"run-{target}-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    events_path = data_dir / f"ingest_events_{run_id}.jsonl"
    db_path = data_dir / "papers.db"

    base_cfg = _load_base_config(data_dir)
    effective_cfg, override_dir = _maybe_build_override(
        base_cfg, keywords, parse_batch_size, data_dir=data_dir, run_id=run_id,
        remove_keywords=remove_keywords,
        arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
        arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
    )
    run_cwd = override_dir if override_dir is not None else data_dir

    # T-DOC78: a download-only run's log MUST be named exactly "prefetch.log" in run_cwd --
    # status.py::read_downloader tails that hardcoded filename for pace, regardless of who
    # launched it. A full run keeps its usual per-run ingest log name, unchanged.
    log_path = (
        run_cwd / "prefetch.log" if mode == "download" else data_dir / f"ingest_{run_id}.log"
    )
    spawn = spawn or (_spawn_download if mode == "download" else _spawn)

    pid = _call_spawn(
        spawn, run_cwd, target, parse_workers, events_path, log_path, paper_ids_file,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
    )
    manifest = _build_manifest(
        run_id, pid, target, parse_workers, events_path, log_path, db_path, paper_ids_file,
        run_cwd=run_cwd, effective_cfg=effective_cfg,
        telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
        mode=mode,
    )
    _write_manifest(data_dir, manifest)
    return manifest
```

Then find `start` (~line 720, the public wrapper) and add `mode` as a keyword param, and change its `spawn` default:

```python
def start(data_dir: str | Path, target: int, parse_workers: int = 3, *,
          paper_ids_file: str | Path | None = None,
          telemetry_poll_interval: float | None = None, batch_size: int | None = None,
          keywords: list[str] | None = None, remove_keywords: list[str] | None = None,
          parse_batch_size: int | None = None,
          arxiv_categories: list[str] | None = None,
          arxiv_date_from: str | None = None, arxiv_date_to: str | None = None,
          ordering: str | None = None,
          stranded_policy: str | None = None,
          mode: str = "full",
          spawn: SpawnFn | None = None) -> dict:
```

(Keep the rest of `start`'s docstring; add one line noting `mode` — `"full"` (default, launches `app.build_corpus`) or `"download"` (T-DOC78, launches `app.prefetch_pdfs` alone — no GPU, no pass1/pass2).) Update its body's call to `_start_locked` to forward `mode=mode`:

```python
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _start_locked(
            data_dir, target, parse_workers, paper_ids_file=paper_ids_file,
            telemetry_poll_interval=telemetry_poll_interval, batch_size=batch_size,
            keywords=keywords, remove_keywords=remove_keywords, parse_batch_size=parse_batch_size,
            arxiv_categories=arxiv_categories, arxiv_date_from=arxiv_date_from,
            arxiv_date_to=arxiv_date_to, ordering=ordering, stranded_policy=stranded_policy,
            mode=mode,
            spawn=spawn,
        )
```

Do **not** touch `retarget()` — it always starts in `mode="full"` (its own call to `_start_locked` never passes `mode`, so the default applies); download-only only ever starts fresh via `start()`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_controller.py -k "download or mode_is_full or ingest_log_unchanged" -v`
Expected: PASS (all 7 new tests)

- [ ] **Step 7: Run the full controller test suite to check nothing regressed**

Run: `pytest app/dashboard/test_controller.py -v`
Expected: PASS (every pre-existing test, since every one passes `spawn=` explicitly and `mode` defaults to `"full"`)

- [ ] **Step 8: Commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "T-DOC78: controller.start(mode=\"download\") launches app.prefetch_pdfs standalone"
```

---

### Task 2: `controller.py` — resume respects the stored mode

**Files:**
- Modify: `app/dashboard/controller.py` (`resume`/`_resume_locked`, ~line 842-901)
- Test: `app/dashboard/test_controller.py`

**Interfaces:**
- Consumes: `_spawn_download`/`_spawn` (Task 1), `manifest["mode"]` (Task 1's `_build_manifest`).
- Produces: `controller.resume(data_dir, *, spawn: SpawnFn | None = None) -> dict` — `spawn`'s default changes from `_spawn` to `None`, resolved from the manifest's stored `mode` when the caller doesn't inject one.

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_controller.py`, after `test_resume_relaunches_with_same_params` (~line 165):

```python
def test_resume_relaunches_download_only_run_as_download_not_full(tmp_path, monkeypatch):
    """A paused download-only run's resume() must pick `_spawn_download` (resolved from the
    manifest's own stored mode) when the caller doesn't inject a test fake -- production's real
    call shape (`server.py` never passes `spawn=`) -- not silently fall back to launching a full
    `app.build_corpus` run."""
    calls = []

    def spy_download(data_dir, target, parse_workers, events_path, log_path):
        calls.append("download")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    def spy_full(data_dir, target, parse_workers, events_path, log_path):
        calls.append("full")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    manifest = controller_mod.start(
        tmp_path, target=30000, parse_workers=1, mode="download", spawn=_fake_spawn,
    )
    try:
        controller_mod.pause(tmp_path)
        monkeypatch.setattr(controller_mod, "_spawn_download", spy_download)
        monkeypatch.setattr(controller_mod, "_spawn", spy_full)
        resumed = controller_mod.resume(tmp_path)  # no spawn injected -- production default path
        assert resumed["mode"] == "download"
        assert calls == ["download"]
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))


def test_resume_relaunches_full_run_as_full_when_no_spawn_injected(tmp_path, monkeypatch):
    """The mode="full" (default) mirror of the test above -- resume()'s own default must still
    pick the real `_spawn` (app.build_corpus), today's exact behavior, for a manifest with no
    stored mode or `mode="full"`."""
    calls = []

    def spy_download(data_dir, target, parse_workers, events_path, log_path):
        calls.append("download")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    def spy_full(data_dir, target, parse_workers, events_path, log_path):
        calls.append("full")
        return subprocess.Popen(["sleep", "100"], start_new_session=True).pid

    manifest = controller_mod.start(tmp_path, target=100, spawn=_fake_spawn)
    try:
        controller_mod.pause(tmp_path)
        monkeypatch.setattr(controller_mod, "_spawn_download", spy_download)
        monkeypatch.setattr(controller_mod, "_spawn", spy_full)
        resumed = controller_mod.resume(tmp_path)
        assert resumed["mode"] == "full"
        assert calls == ["full"]
    finally:
        _cleanup(controller_mod._read_manifest(tmp_path))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_controller.py -k "resume_relaunches_download_only or resume_relaunches_full_run_as_full" -v`
Expected: FAIL — both currently resume with `_spawn` regardless of stored mode, so `calls` won't match (`test_resume_relaunches_download_only_run_as_download_not_full` fails since `_spawn` — not `_spawn_download` — gets called).

- [ ] **Step 3: Make resume mode-aware**

Find `resume`/`_resume_locked` (~line 842). Replace:

```python
def resume(data_dir: str | Path, *, spawn: SpawnFn | None = None) -> dict:
    """Relaunch the run's spawn command with the SAME params as the existing manifest --
    checkpoints make this safe, it picks up where it left off. Refuses (`DoubleRunError`) if the
    prior run is still `running`, or if a `pausing`/`stopping` run's process hasn't yet been
    confirmed dead -- SIGTERM is a request, not a guarantee, and relaunching before the old
    process actually exits would duplicate the work it's still mid-way through.

    T-DOC78: `spawn`'s default (`None`) is resolved from the manifest's own stored `"mode"` --
    `_spawn_download` for a download-only run, `_spawn` (`app.build_corpus`) otherwise -- so a
    paused download-only run resumes as a downloader, not a full pass1/pass2 run."""
    data_dir = Path(data_dir)
    with _control_lock(data_dir):
        return _resume_locked(data_dir, spawn=spawn)


def _resume_locked(data_dir: Path, *, spawn: SpawnFn | None = None) -> dict:
    manifest = reconcile(data_dir)
    if manifest is None:
        raise NoRunError("no run to resume")

    status = manifest.get("status")
    if status == "running":
        raise DoubleRunError(f"run {manifest['run_id']!r} is already running (pid {manifest['pid']})")
    if status in ("pausing", "stopping"):
        pid = manifest.get("pid")
        if not pid or not _wait_for_death(pid, timeout_s=_DEATH_TIMEOUT_S):
            raise DoubleRunError(
                f"run {manifest['run_id']!r} has not confirmed stopped yet (status={status!r}) "
                "-- refusing to resume until its process exits"
            )
        manifest["status"] = "paused" if status == "pausing" else "done"
        _write_manifest(data_dir, manifest)

    events_path = Path(manifest["events_path"])
    log_path = Path(manifest["log_path"])
    stored_ids_file = manifest.get("paper_ids_file")  # OG-40: keep a cache-first run cache-first
    paper_ids_file = Path(stored_ids_file) if stored_ids_file else None
    stored_run_cwd = manifest.get("run_cwd")
    run_cwd = Path(stored_run_cwd) if stored_run_cwd else data_dir
    if run_cwd != data_dir and not run_cwd.exists():
        _rebuild_missing_run_cwd(data_dir, manifest, run_cwd)
    params = manifest.get("params") or {}
    # T-DOC78: resolved from the manifest's own recorded mode when the caller (production: always)
    # doesn't inject a spawn fake -- see `resume`'s docstring.
    spawn = spawn or (_spawn_download if manifest.get("mode") == "download" else _spawn)
    pid = _call_spawn(
        spawn, run_cwd, manifest["target"], manifest["parse_workers"],
        events_path, log_path, paper_ids_file,
        telemetry_poll_interval=params.get("telemetry_poll_interval"),
        batch_size=params.get("batch_size"),
    )
    starttime, cmdline = _capture_identity(pid)
    manifest["pid"] = pid
    manifest["pid_starttime"] = starttime
    manifest["pid_cmdline"] = cmdline
    manifest["status"] = "running"
    _write_manifest(data_dir, manifest)
    return manifest
```

(`manifest.get("mode")` returns `None` for a manifest written before this change — `None != "download"`, so it falls back to `_spawn`, matching today's exact behavior for pre-existing manifests.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_controller.py -k "resume" -v`
Expected: PASS (both new tests, plus every pre-existing `resume`-related test — they all inject `spawn=` explicitly, unaffected by the default-resolution change).

- [ ] **Step 5: Run the full controller test suite**

Run: `pytest app/dashboard/test_controller.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "T-DOC78: resume() relaunches a download-only run as download-only, not full"
```

---

### Task 3: `server.py` — `POST /api/control {"action": "download"}`

**Files:**
- Modify: `app/dashboard/server.py` (`_validate_control_kwargs` ~line 82-117, `_control_kwargs` ~line 156-193, `_dispatch` ~line 437-456, `_RUN_FIELDS` ~line 128-132)
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `controller.start(data_dir, target, parse_workers, *, mode=..., **kwargs)` (Task 1).
- Produces: `_editable_query_kwargs(body: dict) -> dict` (keywords/remove_keywords/arxiv_categories/arxiv_date_from/arxiv_date_to only) and `_validate_editable_kwargs(kwargs: dict) -> None`, both reused by `_control_kwargs`/`_validate_control_kwargs` (existing `"start"`/`"retarget"` behavior unchanged) and the new `"download"` branch.
- `/api/status`'s `run` object gains a `"mode"` key.

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_server.py`, after `test_control_start_forwards_og45_og46_editable_params` (~line 415, find a nearby anchor and insert in the `# --- OG-45/OG-46 ---` area — exact location doesn't matter, tests are independent):

```python
# --- T-DOC78: POST /api/control {"action": "download"} -----------------------------------------


def test_control_download_dispatches_start_with_mode_and_prefetch_target(running_server):
    url, fake_controller = running_server
    status, body = _post(url, "/api/control", {"action": "download"})
    assert status == 200
    assert body["ok"] is True
    call = fake_controller.calls[-1]
    assert call[0] == "start"
    _, target, parse_workers, kwargs = call
    assert target == server_mod._STATIC_CONFIG.prefetch_target
    assert parse_workers == 1
    assert kwargs["mode"] == "download"


def test_control_download_forwards_keywords_and_arxiv_filters(running_server):
    url, fake_controller = running_server
    body = {
        "action": "download",
        "keywords": ["double machine learning"],
        "arxiv_categories": ["stat.ME"],
        "arxiv_date_from": "2024-01-01",
    }
    status, _ = _post(url, "/api/control", body)
    assert status == 200
    _, _, _, kwargs = fake_controller.calls[-1]
    assert kwargs["keywords"] == ["double machine learning"]
    assert kwargs["arxiv_categories"] == ["stat.ME"]
    assert kwargs["arxiv_date_from"] == "2024-01-01"
    # Full-run-only fields must never reach a download-only start, even if present in the body.
    assert "ordering" not in kwargs
    assert "stranded_policy" not in kwargs
    assert "parse_batch_size" not in kwargs
    assert "batch_size" not in kwargs
    assert "telemetry_poll_interval" not in kwargs


def test_control_download_rejects_a_quote_injection_keyword(running_server):
    url, _ = running_server
    status, body = _post(url, "/api/control", {"action": "download", "keywords": ['bad"keyword']})
    assert status == 400
    assert body["ok"] is False


def test_control_download_rejects_an_invalid_arxiv_category(running_server):
    url, _ = running_server
    status, body = _post(
        url, "/api/control", {"action": "download", "arxiv_categories": ["not a category!"]}
    )
    assert status == 400


def test_control_download_rejects_a_malformed_arxiv_date(running_server):
    url, _ = running_server
    status, body = _post(
        url, "/api/control", {"action": "download", "arxiv_date_from": "not-a-date"}
    )
    assert status == 400


def test_status_route_shape_includes_run_mode(running_server):
    url, _ = running_server
    status, body = _get(url, "/api/status")
    assert status == 200
    assert "mode" in body["run"]
```

Also update the EXISTING `test_status_route_shape_matches_api_contract` (~line 203-218): add `"mode"` to the expected `run` key set:

```python
    assert set(body["run"].keys()) == {
        "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
        "paper_ids_file", "parse_batch_size", "arxiv_categories", "arxiv_date_from",
        "arxiv_date_to", "ordering", "stranded_policy", "mode",
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_server.py -k "download or shape_includes_run_mode or shape_matches_api_contract" -v`
Expected: FAIL — `action == "download"` isn't recognized (`KeyError: "unknown action 'download'"` → the handler's `_dispatch` doesn't have that branch, and `run.mode`/`"mode"` isn't in `_RUN_FIELDS` yet).

- [ ] **Step 3: Refactor `_control_kwargs`/`_validate_control_kwargs`, add the `"download"` action**

In `app/dashboard/server.py`, replace `_validate_control_kwargs` (~line 82-117) with:

```python
def _validate_editable_kwargs(kwargs: dict) -> None:
    """The DOWNLOAD-side query filters shared by every action that can launch a downloader
    (`"start"`/`"retarget"`'s full run, and T-DOC78's `"download"` action) -- pulled out of
    `_validate_control_kwargs` so `"download"` can validate just this subset without a
    target/parse_workers it never has."""
    for keyword in (kwargs.get("keywords") or []) + (kwargs.get("remove_keywords") or []):
        if _UNSAFE_KEYWORD_CHARS_RE.search(keyword):
            raise ControlValidationError(
                f"keyword {keyword!r} contains a '\"' or '\\\\', which would break the arXiv "
                "query it's added to or removed from"
            )
    for category in kwargs.get("arxiv_categories") or []:
        if not _CATEGORY_RE.match(category):
            raise ControlValidationError(
                f"arxiv_categories entry {category!r} is not a valid arXiv subject code "
                "(letters/digits/dot/dash only)"
            )
    for field in ("arxiv_date_from", "arxiv_date_to"):
        value = kwargs.get(field)
        if value is not None and not _DATE_RE.match(value):
            raise ControlValidationError(f"{field} {value!r} is not YYYY-MM-DD or YYYYMMDD")


def _validate_control_kwargs(target: int, parse_workers: int, kwargs: dict) -> None:
    """Raises `ControlValidationError` on the first bad field found in a `start`/`retarget`
    request. Called before `controller.start`/`retarget` -- a bad value 400s the request instead
    of spawning a subprocess that would crash later (OG-49#3/#6)."""
    if target < 1:
        # Otherwise `build_to_target`'s `n_done >= target` is trivially true for any target <= 0
        # (including a negative one) -- a silent, instant, "successful" empty run.
        raise ControlValidationError(f"target must be >= 1, got {target}")
    if parse_workers < _MIN_PARSE_WORKERS:
        raise ControlValidationError(
            f"parse_workers must be >= {_MIN_PARSE_WORKERS}, got {parse_workers}"
        )
    batch_size = kwargs.get("batch_size")
    if batch_size is not None and batch_size < 1:
        raise ControlValidationError(f"batch_size must be >= 1 (or unset), got {batch_size}")
    telemetry_poll_interval = kwargs.get("telemetry_poll_interval")
    if telemetry_poll_interval is not None and telemetry_poll_interval <= 0:
        raise ControlValidationError(
            f"telemetry_poll_interval must be > 0, got {telemetry_poll_interval}"
        )
    _validate_editable_kwargs(kwargs)
```

Replace `_control_kwargs` (~line 156-193) with:

```python
def _editable_query_kwargs(body: dict) -> dict:
    """keywords/remove_keywords/arxiv_categories/arxiv_date_from/arxiv_date_to -- the DOWNLOAD-side
    filters shared by `"start"`/`"retarget"`'s full run and T-DOC78's `"download"` action, omitting
    any field the request didn't set (see `_control_kwargs`'s own docstring for why absence, not an
    explicit `None`/`[]`, matters on `retarget`)."""
    kwargs: dict = {}
    keywords = body.get("keywords")
    if keywords:
        kwargs["keywords"] = [str(k) for k in keywords]
    remove_keywords = body.get("remove_keywords")
    if remove_keywords:
        kwargs["remove_keywords"] = [str(k) for k in remove_keywords]
    categories = body.get("arxiv_categories")
    if categories:
        kwargs["arxiv_categories"] = [str(c) for c in categories]
    if body.get("arxiv_date_from"):
        kwargs["arxiv_date_from"] = str(body["arxiv_date_from"])
    if body.get("arxiv_date_to"):
        kwargs["arxiv_date_to"] = str(body["arxiv_date_to"])
    return kwargs


def _control_kwargs(body: dict) -> dict:
    """Pulls the OG-43 editable params out of a `POST /api/control` body for `start`/`retarget`,
    omitting any field the request didn't set -- `controller.start`'s own kwargs already default
    each of these to "unedited" (`None`/no keywords), so an absent field must stay absent here
    too, not turn into an explicit `None`/`[]` that could shadow a stored value on `retarget`."""
    kwargs = _editable_query_kwargs(body)
    if body.get("telemetry_poll_interval") is not None:
        kwargs["telemetry_poll_interval"] = float(body["telemetry_poll_interval"])
    if body.get("batch_size") is not None:
        kwargs["batch_size"] = int(body["batch_size"])
    if body.get("parse_batch_size") is not None:
        kwargs["parse_batch_size"] = int(body["parse_batch_size"])
    # OG-46: relevance-priority ordering.
    if body.get("ordering"):
        kwargs["ordering"] = str(body["ordering"])
    # How to treat papers left Pass-1-complete by an earlier pause (`Config.stranded_policy`).
    if body.get("stranded_policy"):
        kwargs["stranded_policy"] = str(body["stranded_policy"])
    return kwargs
```

Find `_dispatch` (~line 437-456) and add the new branch:

```python
        def _dispatch(self, action: str | None, body: dict) -> None:
            if action in ("start", "retarget"):
                target = int(body["target"])
                parse_workers = int(body.get("parse_workers", 3))
                kwargs = _control_kwargs(body)
                _validate_control_kwargs(target, parse_workers, kwargs)
                if action == "start":
                    controller_module.start(data_dir, target, parse_workers, **kwargs)
                else:
                    # OG-43: "Apply new settings" while a run is already live -- stop-then-start
                    # with the edited params, instead of making the user pause/stop by hand first.
                    controller_module.retarget(data_dir, target, parse_workers, **kwargs)
            elif action == "download":
                # T-DOC78: download PDFs only -- no GPU, no pass1/pass2. Reuses the same
                # keywords/categories/dates the Apply panel already stages (mode-agnostic
                # override machinery, controller._maybe_build_override); mutual exclusion with a
                # live full run is the SAME double-run guard `"start"` already gets, for free.
                kwargs = _editable_query_kwargs(body)
                _validate_editable_kwargs(kwargs)
                controller_module.start(
                    data_dir, _STATIC_CONFIG.prefetch_target, 1, mode="download", **kwargs,
                )
            elif action == "pause":
                controller_module.pause(data_dir)
            elif action == "resume":
                controller_module.resume(data_dir)
            elif action == "stop":
                controller_module.stop(data_dir)
            else:
                raise KeyError(f"unknown action {action!r}")
```

Find `_RUN_FIELDS` (~line 128-132) and add `"mode"`:

```python
_RUN_FIELDS = (
    "run_id", "status", "target", "parse_workers", "focus_queries", "started_at", "params",
    "paper_ids_file", "arxiv_categories", "arxiv_date_from", "arxiv_date_to", "ordering",
    "stranded_policy", "mode",
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_server.py -k "download or shape_includes_run_mode or shape_matches_api_contract" -v`
Expected: PASS

- [ ] **Step 5: Run the full dashboard test suite**

Run: `pytest app/dashboard/ -v`
Expected: PASS (every existing `"start"`/`"retarget"` validation test still passes unchanged — `_validate_control_kwargs`/`_control_kwargs` behavior is byte-for-byte preserved, just reorganized)

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/server.py app/dashboard/test_server.py
git commit -m "T-DOC78: wire POST /api/control action=download; expose run.mode"
```

---

### Task 4: Frontend — "Download Now" button + mode indicator

**Files:**
- Modify: `app/dashboard/static/index.html` (Control panel buttons ~line 222-226, `render()`'s mode-indicator block ~line 435-443, button wiring ~end of `<script>` before `poll();`)
- Test: `app/dashboard/test_server.py` (HTML substring assertions, matching this repo's existing convention for frontend testing — there is no JS test harness)

**Interfaces:**
- Consumes: `POST /api/control {"action": "download", ...}` (Task 3), `snap.run.mode` (Task 3's `_RUN_FIELDS`).

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_server.py`, near `test_root_html_persists_token_and_distinguishes_auth_errors_from_staleness` (~line 175):

```python
def test_root_html_has_download_now_button_wired_to_the_download_action(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b'id="btnDownloadOnly"' in body
    assert b'"download"' in body


def test_root_html_mode_indicator_branches_on_download_mode(running_server):
    url, _ = running_server
    status, body = _get_raw(url, "/")
    assert status == 200
    assert b"download-only" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/dashboard/test_server.py -k "download_now_button or mode_indicator_branches" -v`
Expected: FAIL — neither string exists in `index.html` yet.

- [ ] **Step 3: Add the button HTML**

In `app/dashboard/static/index.html`, find the Pause/Resume/Stop controls block (~line 222-226):

```html
    <div class="controls">
      <button id="btnPause" class="secondary">Pause</button>
      <button id="btnResume" class="secondary">Resume</button>
      <button id="btnStop" class="danger">Stop</button>
    </div>
```

Add immediately after it:

```html

    <div class="controls" style="margin-top: .5rem;">
      <button id="btnDownloadOnly" class="secondary" type="button">Download Now (no GPU)</button>
      <span class="note" style="margin:0;">Downloads PDFs using the keywords/categories/dates staged below, without running pass1/pass2 -- start the full run later once the GPU is free. Refused while a run is already live (shown below via Control message).</span>
    </div>
```

- [ ] **Step 4: Extend the mode indicator**

In the `<script>` block, find `render()`'s mode-indicator lines (~line 435-443):

```js
  // Cache-first mode indicator (OG-43): every dashboard-launched run goes through
  // app.build_corpus, which is cache-first by construction (OG-40/OG-41) -- note an explicit id
  // list too, when the manifest carries one. OG-46: also surface the processing-order mode
  // (relevance vs freshest) actually in effect for this run.
  const orderingLabel = snap.run.ordering === "relevance" ? "relevance" : "freshest";
  document.getElementById("modeIndicator").textContent = snap.run.run_id
    ? "mode: cache-first" + (snap.run.paper_ids_file ? " (explicit id list)" : "")
      + " · order: " + orderingLabel
    : "";
```

Replace with:

```js
  // Cache-first mode indicator (OG-43): every dashboard-launched full run goes through
  // app.build_corpus, which is cache-first by construction (OG-40/OG-41) -- note an explicit id
  // list too, when the manifest carries one. OG-46: also surface the processing-order mode
  // (relevance vs freshest) actually in effect for this run. T-DOC78: a download-only run has
  // neither pass1/pass2 nor an ordering, so it gets its own label instead.
  const orderingLabel = snap.run.ordering === "relevance" ? "relevance" : "freshest";
  document.getElementById("modeIndicator").textContent = !snap.run.run_id ? "" :
    snap.run.mode === "download"
      ? "mode: download-only (no GPU, no pass1/pass2)"
      : "mode: cache-first" + (snap.run.paper_ids_file ? " (explicit id list)" : "")
        + " · order: " + orderingLabel;
```

- [ ] **Step 5: Wire the button**

Find the end of the `<script>` block, right before `poll();` (~line 776-778, immediately after `btnApply`'s closing `});`):

```js
poll();
setInterval(poll, 4000);
```

Replace with:

```js
function buildDownloadPayload() {
  const body = {};
  if (pendingKeywords.length) body.keywords = pendingKeywords.slice();
  if (pendingRemovals.length) body.remove_keywords = pendingRemovals.slice();
  if (pendingSubjects.length) body.arxiv_categories = pendingSubjects.slice();
  const dateFrom = document.getElementById("newDateFrom").value;
  if (dateFrom) body.arxiv_date_from = dateFrom;
  const dateTo = document.getElementById("newDateTo").value;
  if (dateTo) body.arxiv_date_to = dateTo;
  return body;
}

// T-DOC78: download PDFs now, without committing GPU time to pass1/pass2 -- reuses the same
// staged keywords/categories/dates as Apply, but never target/parse_workers/ordering (not
// meaningful for a bare downloader). Mutual exclusion with a full run is enforced server-side
// (controller.start's existing double-run guard applies regardless of mode) -- a refusal shows up
// in #controlMsg exactly like a rejected "start" does today, no separate client-side guard needed.
document.getElementById("btnDownloadOnly").addEventListener("click", () => {
  control("download", buildDownloadPayload());
  pendingKeywords = [];
  renderPendingKeywords();
  pendingRemovals = [];
  renderFocusQueries();
  pendingSubjects = [];
  renderPendingSubjects();
  document.getElementById("newDateFrom").value = "";
  document.getElementById("newDateTo").value = "";
});

poll();
setInterval(poll, 4000);
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest app/dashboard/test_server.py -k "download_now_button or mode_indicator_branches" -v`
Expected: PASS

- [ ] **Step 7: Run the full dashboard test suite**

Run: `pytest app/dashboard/ -v`
Expected: PASS

- [ ] **Step 8: Manual smoke test**

```bash
python -m app.dashboard.server --data-dir /tmp/dash-smoke --port 8899
```
Open `http://127.0.0.1:8899/` in a browser, confirm: the "Download Now (no GPU)" button renders next to Pause/Resume/Stop, and the mode indicator shows nothing when no run is live. (No real corpus/token needed for this visual check — Ctrl-C to stop.)

- [ ] **Step 9: Commit**

```bash
git add app/dashboard/static/index.html app/dashboard/test_server.py
git commit -m "T-DOC78: dashboard Download Now button + download-only mode indicator"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers "spawn app.prefetch_pdfs directly, mutual exclusion, same log/pid filenames as build_corpus"; Task 2 covers "resume respects stored mode"; Task 3 covers the `POST /api/control` action + `run.mode` in `/api/status`; Task 4 covers the UI button + mode label. All four spec sections ("Architecture", "server.py / API", "UI") have a task. `retarget()` is explicitly left untouched per the spec's "What this deliberately does not do".
- **Placeholder scan:** no TBD/TODO; every step has literal code, not a description of code.
- **Type consistency:** `_spawn_download`'s signature `(data_dir, target, parse_workers, events_path, log_path) -> int` matches `SpawnFn` everywhere it's referenced (Task 1 Step 3, used unchanged in Task 2). `mode` is a plain `str` (`"full"`/`"download"`) consistently across `controller.start`/`_build_manifest`/`server._dispatch`/`index.html`'s `snap.run.mode`. `_editable_query_kwargs`/`_validate_editable_kwargs` names match between their Task 3 definition and Task 3's `_dispatch` usage.
