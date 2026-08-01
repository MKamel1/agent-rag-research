# D-10: Dashboard number accuracy — cross-check + dynamic tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every number the dashboard shows is provably equal to an independently-computed ground truth, and provably *tracks* that truth when it changes.

**Architecture:** Two deliverables. (1) `app/dashboard/verify_numbers.py` — a runnable cross-check that recomputes each `/api/status` field from an independent source and reports agreement or drift. (2) Dynamic tests that mutate a scratch fixture and assert each number *moves correctly*, rather than asserting a frozen constant.

**Tech Stack:** Python 3.12, stdlib `sqlite3`/`json`/`urllib`, pytest.

---

## Why this exists — a live false positive, found in 5 minutes

While enumerating the fields on 2026-08-01, `/api/status` reported:

```
downloader.orphan      = True
downloader.tracked_pid = None
```

Ground truth at that moment:

```
prefetch pid=1181468  parent=1181456     <- legitimate child of the running build_corpus
manifest pid          = 1181456
```

`server.py` passes the manifest PID into the orphan check **only when `mode == "download"`**. This run is `mode == "full"`, and `app/build_corpus.py` legitimately spawns `app.prefetch_pdfs` as a child — so during every full run, that child is flagged as an orphan.

**D-6's unit tests pass. CI is green. The number is still wrong in production.** That is the gap this ticket closes: correctness of a *value against reality*, which no amount of fake-injected unit testing reaches.

**Fix that specific bug as part of this work** (Task 3), not just detect it.

## The two failure modes being targeted

1. **Wrong value** — the field disagrees with reality (the orphan bug).
2. **Frozen value** — the field is right today by accident and would not move if reality changed. A test asserting `done == 12333` proves nothing; a test asserting *"insert one `stage='done'` row ⇒ `funnel.done` increases by exactly 1"* proves the wiring.

Every check below must be of the second kind wherever it can be.

## Ground-truth sources (independent of the dashboard's own readers)

| dashboard field | independent ground truth |
|---|---|
| `funnel.<stage>` | `SELECT COUNT(*) FROM ingest_state WHERE stage=?`, summed cumulatively over `_STAGES` from that stage onward |
| `funnel.quarantined` | `SELECT COUNT(*) FROM quarantine q WHERE NOT EXISTS (…stage='done'…)` |
| `by_doc_type.<t>.<stage>` | same, joined to `papers.doc_type` |
| `downloads.staged_pdfs` | count of `pdf_cache/*.pdf` |
| `downloads.sidecars` | count of `pdf_cache/*.json` |
| `downloads.prefetch_target` | `Config.prefetch_target` from the data-dir `config.yaml` |
| `downloads.stalled` / `new_last_pass` | newest matching line in `prefetch.log` |
| `downloader.live_pids` | `pgrep -f app.prefetch_pdfs` |
| `downloader.orphan` | a live prefetch PID that is **neither** the manifest PID **nor** a descendant of it |
| `downloader.tags_pending` | `tag_pool.json` mtime vs the live downloader's `/proc/<pid>` start time |
| `tags.active_count` / `held_count` | `len()` of each list in `tag_pool.json` |
| `drop_in.pending_*` / `staged` / `failed` / `excluded` | counts of `*.pdf` in each drop subfolder |
| `drop_in.processed` | manifest paper_ids ∩ `ingest_state.stage='done'` |
| `usage.*` | direct queries against `mcp_usage.db` |
| `tei.*` | direct `GET` to each health endpoint |
| `disk.free_gb` | `shutil.disk_usage` |
| `run.*` | the raw `run_manifest.json` |

**Independence is the point.** Do not import the dashboard's own reader and compare it to itself — recompute from the underlying source. If the check merely calls `status.read_corpus` twice it proves nothing.

---

## Global Constraints

- Backlog **D-10**.
- **Do not modify** `contracts/`, `rag/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`, `app/build_corpus.py`, `app/prefetch_pdfs.py`, or `rag/parser.py` (another agent owns `parser.py` right now).
- **Never** write `<data_dir>/config.yaml`, `tag_pool.json`, or `papers.db`. All DB access read-only via `file:…?mode=ro`. No ingest, rechunk, delete, snapshot, or corpus run.
- **A corpus build may be running.** Do not stop, pause, or signal it. Do not restart the dashboard while a run is in progress — the verify script is read-only and needs no restart.
- Never `git stash`; never merge a PR; never `--admin`.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b dashboard-number-accuracy origin/main`.
- Run pytest in the **foreground**; read its exit code. Do NOT write output to a shared `/tmp` path and poll it for a summary string.
- Enforcement — **`number`/`labels` go INSIDE `pull_request`**; the top-level form raises `KeyError: 'labels'`:

  ```bash
  EV=$(mktemp) && printf '{"pull_request":{"number":0,"labels":[],"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`.

---

### Task 1: `app/dashboard/verify_numbers.py` — the cross-check

**Files:** Create `app/dashboard/verify_numbers.py`. Test: create `app/dashboard/test_verify_numbers.py`.

**Interfaces:**

```python
def verify(data_dir: Path, status: dict) -> list[Discrepancy]   # pure; no HTTP, no I/O beyond ground truth
def main(argv: list[str] | None = None) -> int                  # CLI: fetch /api/status, verify, print, exit 1 on any discrepancy
```

`Discrepancy` is a frozen dataclass: `field: str`, `dashboard: object`, `ground_truth: object`, `note: str`.

- [ ] **Step 1: Write the failing tests** — every one uses a `tmp_path` scratch data dir, never the real one.

```python
def test_verify_reports_no_discrepancies_when_dashboard_matches_ground_truth(tmp_path):
    _make_scratch_corpus(tmp_path, done=5, chunked=2)          # helper you write
    status = {"funnel": {"harvested": 7, "parsed": 7, "chunked": 7,
                         "summarized": 5, "embedded": 5, "stored": 5, "done": 5,
                         "quarantined": 0}, ...}
    assert verify_numbers.verify(tmp_path, status) == []


def test_verify_catches_a_wrong_funnel_number(tmp_path):
    _make_scratch_corpus(tmp_path, done=5, chunked=2)
    status = {...}; status["funnel"]["done"] = 999
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "funnel.done" and x.ground_truth == 5 for x in d)


def test_verify_catches_a_stale_number_that_did_not_track_a_change(tmp_path):
    """The frozen-value failure mode: the dashboard reported a number that WAS right
    before the corpus changed and is wrong now."""
    _make_scratch_corpus(tmp_path, done=5)
    status = _status_for(done=5)
    assert verify_numbers.verify(tmp_path, status) == []
    _add_done_rows(tmp_path, 3)                                 # corpus moves; status does not
    d = verify_numbers.verify(tmp_path, status)
    assert any(x.field == "funnel.done" and x.ground_truth == 8 for x in d)


def test_verify_flags_an_orphan_only_when_the_pid_is_not_a_descendant_of_the_run(tmp_path):
    """The live 2026-08-01 false positive: build_corpus legitimately spawns prefetch_pdfs
    as a child during a `full` run, and it was reported as an orphan."""
    status = {"downloader": {"live_pids": [222], "orphan": True}, ...}
    d = verify_numbers.verify(tmp_path, status, _pid_parent=lambda p: 111 if p == 222 else None,
                              _manifest_pid=111)
    assert any(x.field == "downloader.orphan" for x in d)
```

Inject process-tree lookups (`_pid_parent`) rather than reading `/proc` directly in tests, so no test depends on live processes.

- [ ] **Step 2: Run to verify failure**, then **Step 3: implement.**

`verify()` is **pure given its inputs** — it takes the already-fetched `status` dict and a data dir, and returns discrepancies. All I/O for ground truth is read-only. Missing sources (no `mcp_usage.db`, no `tag_pool.json`) yield a `note` and **no** discrepancy — absent is not disagreement.

Numeric comparison is exact for counts. `disk.free_gb` and telemetry floats compare with a tolerance (disk changes between the two reads); state the tolerance in the code.

**Fields that are legitimately allowed to differ** because they are sampled at different instants — `telemetry.*`, `disk.free_gb`, and any count while a run is actively writing — must be marked `note="racy"` and reported separately, not as hard failures. Say so in the output rather than pretending the check is exact.

- [ ] **Step 4: CLI + commit**

`main()` fetches `/api/status` with the token from `<data_dir>/.dashboard_token`, runs `verify`, prints a table, and exits `1` if any non-racy discrepancy exists — so it is usable as a health gate.

```bash
git add app/dashboard/verify_numbers.py app/dashboard/test_verify_numbers.py
git commit -m "Add verify_numbers: cross-check every dashboard field against ground truth

Recomputes each /api/status number from an independent source -- the DB, the
filesystem, the process table -- rather than from the dashboard's own readers,
so a shared bug cannot hide. Found by hand on 2026-08-01: downloader.orphan
read True for a prefetch process that was a legitimate child of the running
build_corpus supervisor."
```

### Task 2: Dynamic tests — numbers must *track*, not just match

**Files:** `app/dashboard/test_status.py` (extend). No new module.

For each reader, assert the number **moves correctly under a mutation** rather than equalling a constant:

- [ ] `read_corpus`: insert N rows at a stage ⇒ that stage and every earlier stage increase by N; later stages unchanged.
- [ ] `read_corpus`: move a row `chunked → done` ⇒ `done` +1, `chunked` cumulative unchanged (it is cumulative, so this is the subtle one).
- [ ] `by_doc_type`: insert a `book` row ⇒ only the `book` funnel moves; `paper` untouched.
- [ ] `read_downloads`: add a `.pdf` to the cache ⇒ `staged_pdfs` +1; add a `.json` ⇒ `sidecars` +1, `staged_pdfs` unchanged.
- [ ] `read_drop_in`: add a file to `papers/` ⇒ `pending_papers` +1; move it to `done/` ⇒ `pending_papers` −1, `staged` +1, `processed` **unchanged** (staging is not processing — the distinction the whole feature exists for).
- [ ] `tag_pool`: hold a tag ⇒ `active_count` −1, `held_count` +1, sum constant.
- [ ] `read_downloads`: append a stall line to `prefetch.log` ⇒ `stalled` flips True; append a newer pace line ⇒ flips back False.

Each is one mutation and one assertion about the *delta*. A test that hardcodes an absolute expected count is a regression waiting to happen and must not be written here.

- [ ] Commit: `Add dynamic dashboard-number tests: assert deltas, not constants`

### Task 3: Fix the orphan false positive

**Files:** `app/dashboard/server.py`, `app/dashboard/status.py` (whichever holds the decision). Test: `app/dashboard/test_server.py`.

**The bug:** the manifest PID is passed to the orphan check only for `mode == "download"`, so during a `full` run every prefetch child of `build_corpus` is reported as an orphan.

**The fix:** a live prefetch PID is an orphan only if it is neither the manifest PID **nor a descendant of it**. Walk `/proc/<pid>/stat`'s PPID chain up to the manifest PID (bounded — stop at PID 1 or after a small depth cap, so a cycle or a reparented process cannot loop forever). Pass the manifest PID regardless of `mode`.

- [ ] Test: a prefetch PID whose parent is the manifest PID ⇒ `orphan is False`, even when `mode == "full"`.
- [ ] Test: a prefetch PID with an unrelated parent ⇒ `orphan is True` (the real 20-hour case D-6 was built for must still be caught).
- [ ] Commit: `Do not report a run's own prefetch child as an orphan`

### Task 4: Verify against the live system, then PR

- [ ] **Step 1: Full suite + enforcement** — both `rc=0`.

- [ ] **Step 2: Run the cross-check against the real dashboard** (read-only):

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m app.dashboard.verify_numbers --data-dir /home/omar/ai-projects/research-system-rag-data
rc=$?
```

Report the full output verbatim. `rc=0` means every non-racy field agrees. **If it reports a discrepancy, that is a finding, not a test failure — investigate and report it; do not silence it.**

- [ ] **Step 3: PR** titled `D-10: dashboard number accuracy — cross-check, dynamic tests, orphan fix`. Do not merge. Poll `gh pr checks <n>` until final; both must `pass`.

---

## Report contract

Return only: status, commit SHAs, PR number, real `rc` for pytest and enforcement, the Step 2 verify output verbatim, confirmation that the orphan fix distinguishes a run's own child from a true orphan, whether any live discrepancy remains, and the final CI conclusion for each check by name.
