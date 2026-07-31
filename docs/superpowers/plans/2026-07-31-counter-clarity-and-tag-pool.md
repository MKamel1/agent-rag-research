# Counter Clarity + Tag Pool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard's counters honest (Part 1), and replace per-run throwaway keyword edits with one persistent tag pool that supports hold-and-restore (Part 2).

**Architecture:** Part 1 corrects a wrong denominator and parses a stall line the prefetcher already logs. Part 2 introduces `<data_dir>/tag_pool.json`, a dashboard-owned sidecar with `active` and `held` lists, seeded from `config.yaml` and composed into each run's override. No foundation-frozen file is touched and `config.yaml` is never rewritten.

**Tech Stack:** Python 3.12, stdlib `json`/`re`/`http.server`, `filelock`, pytest, pytest-socket.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-31-dashboard-counter-clarity-design.md`. Backlog **D-5**.
- **Do not modify** `contracts/`, `rag/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`, or `app/prefetch_pdfs.py`.
- **The dashboard must never rewrite `<data_dir>/config.yaml`.** It is the operator's file: seed and fallback only. If you find yourself writing to it, stop — the design is a sidecar for exactly this reason.
- **Never** write to `/home/omar/ai-projects/research-system-rag-data/papers.db`. No ingest, rechunk, delete, snapshot, or corpus run.
- **Do not change** `funnel`, `read_telemetry`, ETA, or papers-per-hour. The combined funnel is frozen — `read_telemetry` derives ETA and papers/hour from `funnel["done"]`.
- Never `git stash`; never merge a PR; never pass `--admin` or a branch-protection bypass.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — chained in ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b counter-clarity-and-tag-pool origin/main`.
- Run pytest in the **foreground** and read its exit code. Do NOT write output to a shared `/tmp` path and poll it for a summary string — a killed run never writes the summary line, so the poll never ends.
- Local enforcement needs a synthesized payload (`labels` is read without `.get`; `number` is optional):

  ```bash
  EV=$(mktemp) && printf '{"number":0,"labels":[],"pull_request":{"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`. Never add a label or weaken a test to make a check go green.

## Measured facts this plan depends on (verified 2026-07-31)

```
blobs/*.md        = 12,333   corpus (one per processed paper)
pdf_cache/*.pdf   = 11,612   staged ahead of processing
done but NOT cached =  745   ingested via live arXiv fetch; papers.pdf_path is a URL
cached but NOT done =   24
config prefetch_target = 30,000      run manifest target = 20,000
len(focus_area_queries) = 33
```

Nothing deletes cached PDFs — grepped `unlink|rmtree|remove|prune|evict` against `pdf_cache` across `app/` and `rag/`, zero hits.

---

# Part 1 — Counter clarity

### Task 1: `read_downloads` — right denominator, stall state

**Files:** Modify `app/dashboard/status.py` (`read_downloads` ~line 415, `_DOWNLOAD_PACE_RE` ~line 440). Test: `app/dashboard/test_status.py`.

**Interfaces:** Produces `read_downloads(data_dir, prefetch_target: int | None) -> dict` with keys `staged_pdfs`, `sidecars`, `prefetch_target`, `stalled`, `new_last_pass`.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_downloads_reports_stall_from_the_prefetch_log(tmp_path):
    (tmp_path / "pdf_cache").mkdir()
    (tmp_path / "prefetch.log").write_text(
        "INFO:__main__:prefetch_pdfs: pass complete, +6 this pass, 11556/30000 cached\n"
        "INFO:__main__:prefetch_pdfs: prefetch stalled: 11556/30000 cached, "
        "only 6 new available, next attempt in 3600s\n"
    )
    out = status.read_downloads(tmp_path, 30000)
    assert out["stalled"] is True
    assert out["new_last_pass"] == 6
    assert out["prefetch_target"] == 30000


def test_read_downloads_stall_clears_when_a_newer_pace_line_follows(tmp_path):
    """A stall followed by fresh progress is not a stall -- whichever line appears LATER wins."""
    (tmp_path / "pdf_cache").mkdir()
    (tmp_path / "prefetch.log").write_text(
        "prefetch stalled: 11556/30000 cached, only 6 new available, next attempt in 3600s\n"
        "prefetch_pdfs: downloaded 40 / target 30000\n"
    )
    out = status.read_downloads(tmp_path, 30000)
    assert out["stalled"] is False


def test_read_downloads_absent_log_is_not_a_stall_and_not_a_zero(tmp_path):
    (tmp_path / "pdf_cache").mkdir()
    out = status.read_downloads(tmp_path, 30000)
    assert out["stalled"] is False
    assert out["new_last_pass"] is None      # absent != zero
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -k read_downloads -v
rc=$?
```

- [ ] **Step 3: Implement**

Rename the returned keys (`cached_pdfs` → `staged_pdfs`, `target` → `prefetch_target`), rename the parameter to `prefetch_target`, and add:

```python
# app/prefetch_pdfs.py:417 logs this every stalled pass and nothing has ever read it -- the system
# knew it had exhausted arXiv for the configured queries and never told the operator.
_DOWNLOAD_STALL_RE = re.compile(r"prefetch stalled: (\d+)/(\d+) cached, only (\d+) new available")
```

Scan the same log tail `read_downloader` already reads. Compare the byte offset of the last
`_DOWNLOAD_STALL_RE` match against the last `_DOWNLOAD_PACE_RE` match; the later one wins, so a
stall followed by fresh progress correctly clears. Missing/unreadable log or no match ⇒
`stalled: False`, `new_last_pass: None` — **never a fabricated `0`**.

- [ ] **Step 4: Run the tests, then commit**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -q
rc=$?
```

```bash
git add app/dashboard/status.py app/dashboard/test_status.py
git commit -m "read_downloads: pair with prefetch_target, surface harvest stall

The downloader aims at cfg.prefetch_target (30000), not the run's processing
target -- pairing staged PDFs with the latter showed a denominator nothing was
working toward. prefetch_pdfs has logged 'prefetch stalled: only N new available'
every hour since it started; nothing read it, so an exhausted harvest looked
like a bar stuck at 58%. Absent log yields None, never a fabricated zero."
```

### Task 2: Wire it into `/api/status`

**Files:** Modify `app/dashboard/server.py` (`_status_dict`). Test: `app/dashboard/test_server.py`.

- [ ] **Step 1: Write the failing test**

```python
def test_status_dict_passes_prefetch_target_not_the_run_target(tmp_path, monkeypatch):
    """Regression: server.py passed live.get('target') -- the PROCESSING target -- as the
    denominator for DOWNLOADED pdfs, while the downloader aims at cfg.prefetch_target."""
    seen = {}

    class _Status:
        def read_downloads(self, data_dir, prefetch_target):
            seen["prefetch_target"] = prefetch_target
            return {"staged_pdfs": 0, "sidecars": 0, "prefetch_target": prefetch_target,
                    "stalled": False, "new_last_pass": None}
        # ... remaining methods delegate to the real `status` module

    # run manifest target is 20000; config prefetch_target is 30000
    ...
    assert seen["prefetch_target"] == 30000
```

Build it using whatever `_FakeStatus` / fixture idiom `test_server.py` already establishes rather than the sketch above; the assertion is what matters.

- [ ] **Step 2–4: Run, implement, verify**

In `_status_dict`, change:

```python
"downloads": status_module.read_downloads(data_dir, live.get("target")),
```

to pass `_static_config(data_dir).prefetch_target`. Leave the `run` block's own `target` alone.

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/ -q
rc=$?
```

`test_status_route_shape_matches_api_contract` asserts the full `/api/status` key set and **will fail** on the rename. That is correct — update its expected keys to `staged_pdfs`/`prefetch_target`. This is the one existing test this plan is permitted to modify, and only for the renamed keys.

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/server.py app/dashboard/test_server.py
git commit -m "Pass prefetch_target into read_downloads, not the run's processing target"
```

---

# Part 2 — Tag pool

### Task 3: `app/dashboard/tag_pool.py` — the store

**Files:** Create `app/dashboard/tag_pool.py`. Test: create `app/dashboard/test_tag_pool.py`.

**Interfaces:**

```python
def load(data_dir: Path, seed_queries: list[str]) -> dict          # {"active": [...], "held": [...]}
def add(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict
def hold(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict
def restore(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict
def active_queries(data_dir: Path, seed_queries: list[str]) -> list[str]
```

Every function takes `seed_queries` so a missing pool file can be seeded on first touch without the module importing `rag.config` itself.

- [ ] **Step 1: Write the failing tests**

```python
def test_pool_seeds_from_config_queries_on_first_load(tmp_path):
    pool = tag_pool.load(tmp_path, ["causal inference", "do-calculus causal"])
    assert pool["active"] == ["causal inference", "do-calculus causal"]
    assert pool["held"] == []


def test_hold_moves_a_tag_to_held_without_destroying_it(tmp_path):
    seed = ["a", "b", "c"]
    pool = tag_pool.hold(tmp_path, seed, ["b"])
    assert pool["active"] == ["a", "c"]
    assert [h["query"] for h in pool["held"]] == ["b"]
    assert pool["held"][0]["held_at"]          # timestamped


def test_restore_brings_a_held_tag_back(tmp_path):
    seed = ["a", "b"]
    tag_pool.hold(tmp_path, seed, ["b"])
    pool = tag_pool.restore(tmp_path, seed, ["b"])
    assert "b" in pool["active"]
    assert pool["held"] == []


def test_adding_a_held_tag_reactivates_it_instead_of_duplicating(tmp_path):
    seed = ["a", "b"]
    tag_pool.hold(tmp_path, seed, ["b"])
    pool = tag_pool.add(tmp_path, seed, ["b"])
    assert pool["active"].count("b") == 1
    assert pool["held"] == []


def test_holding_every_tag_is_refused_and_leaves_the_pool_untouched(tmp_path):
    seed = ["a", "b"]
    with pytest.raises(controller.InvalidOverrideError):
        tag_pool.hold(tmp_path, seed, ["a", "b"])
    assert tag_pool.load(tmp_path, seed)["active"] == ["a", "b"]


def test_add_is_idempotent_and_preserves_order(tmp_path):
    seed = ["a"]
    tag_pool.add(tmp_path, seed, ["b"])
    pool = tag_pool.add(tmp_path, seed, ["b"])
    assert pool["active"] == ["a", "b"]
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: implement**.

File shape:

```json
{"active": [...], "held": [{"query": "...", "held_at": "ISO-8601Z"}],
 "seeded_from": "config.yaml", "updated_at": "ISO-8601Z"}
```

Requirements:

- Seed on first load from `seed_queries`; **never** write `config.yaml`.
- All mutations go through the existing `controller._control_lock(data_dir)` so a tag edit cannot interleave with a run-control op. Import it rather than creating a second lock — two locks over the same data dir is a deadlock waiting to happen.
- Holding every active tag raises `controller.InvalidOverrideError` and leaves the file byte-identical. This mirrors the guard `_maybe_build_override` already applies to `remove_keywords`: an empty `focus_area_queries` leaves the downloader with nothing to search.
- A corrupt/unreadable pool file re-seeds rather than raising into a status poll — but log a WARNING, because silently discarding an operator's held tags would be worse than the error.

- [ ] **Step 4: Test, then commit**

```bash
git add app/dashboard/tag_pool.py app/dashboard/test_tag_pool.py
git commit -m "Add tag_pool: one persistent pool of queries with hold/restore

Tag edits were run-scoped: _maybe_build_override wrote them to a scratch
config.yaml that _cleanup_run_cwd later deleted, so the next run reverted to
the base 33 queries. Every edit created its own private pool that died with the
run. tag_pool.json is a dashboard-owned sidecar -- not a contracts/config.py
field, which is foundation-frozen -- seeded from config.yaml and never writing
back to it. Removal is hold, not delete: a held tag stays listed and restores
in one click."
```

### Task 4: Compose the pool into runs

**Files:** Modify `app/dashboard/controller.py` (`_maybe_build_override`). Test: `app/dashboard/test_controller.py`.

- [ ] **Step 1: Write the failing test — this is the regression test for the actual bug**

```python
def test_added_tags_persist_into_a_SECOND_run(tmp_path):
    """The bug the operator hit: keyword edits were written to a run-scoped scratch config that
    _cleanup_run_cwd deleted, so the next run reverted to the base queries and every edit built
    its own private pool. Fails against the old code."""
    base = controller_mod.load_config(controller_mod._REPO_ROOT / "config.example.yaml")

    controller_mod._maybe_build_override(
        base, ["new topic"], None, data_dir=tmp_path, run_id="run-1",
    )
    _, override_dir = controller_mod._maybe_build_override(
        base, None, None, data_dir=tmp_path, run_id="run-2",
    )

    second = controller_mod.load_config(Path(override_dir) / "config.yaml")
    assert "new topic" in second.focus_area_queries
```

- [ ] **Step 2: Run to verify failure**, then **Step 3: implement**.

`_maybe_build_override` composes `focus_area_queries` from `tag_pool.active_queries(data_dir, cfg.focus_area_queries)`. `keywords` writes through `tag_pool.add`; `remove_keywords` writes through `tag_pool.hold` — same add/remove meaning as before, now persistent.

An override dir is still only built when something actually changes relative to the composed pool, so a run that edits nothing launches exactly as before (`cwd=data_dir`, no scratch files) — preserve that.

- [ ] **Step 4: Test, then commit**

```bash
git add app/dashboard/controller.py app/dashboard/test_controller.py
git commit -m "Compose run queries from the tag pool so edits persist across runs"
```

### Task 5: HTTP surface and Tags panel

**Files:** Modify `app/dashboard/server.py`, `app/dashboard/static/index.html`. Test: `app/dashboard/test_server.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_route_includes_tags_block(running_server):
    body = _get_status(running_server)
    assert set(body["tags"]) >= {"active", "held", "active_count", "held_count"}


def test_control_hold_tags_moves_a_tag_to_held(running_server):
    resp = _post_control(running_server, {"action": "hold_tags", "tags": ["causal forest"]})
    assert resp["ok"] is True
    body = _get_status(running_server)
    assert "causal forest" not in body["tags"]["active"]
    assert "causal forest" in [h["query"] for h in body["tags"]["held"]]
```

Use the file's own `running_server` / control-POST helpers rather than the illustrative names.

- [ ] **Step 2–4: Run, implement, verify**

`_status_dict` gains:

```python
"tags": {**tag_pool.load(data_dir, _static_config(data_dir).focus_area_queries),
         "active_count": ..., "held_count": ...},
```

`POST /api/control` gains `add_tags`, `hold_tags`, `restore_tags`, each taking `{"tags": [...]}`. Map `InvalidOverrideError` to the status code the dispatch already uses for it — find it, do not invent one.

**Part 1's exhaustion banner reads its query count from `tags.active_count`**, not from a second read of the config, so the two features cannot drift apart.

Frontend: a "Tags" panel in `index.html` matching the existing panels' idiom — active tags as chips each with a **Hold** control, a collapsed **Held** section each with **Restore**, and an add box. Held tags render visibly but styled inactive, so parked tags can be seen and brought back without retyping.

Also render Part 1's three quantities as **separate labelled rows, never a shared ratio**:
**Corpus** (`funnel.done`), **Staged for processing** (`downloads.staged_pdfs / downloads.prefetch_target`), and the run's processing target where it already lives. When `downloads.stalled`, show the banner:

> **Harvest exhausted** — every arXiv paper matching your **N queries** has been downloaded. **+M new** in the last pass. Widen `focus_area_queries` or `arxiv_categories` to grow further.

- [ ] **Step 5: Full suite and enforcement**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && python -m pytest -q
rc=$?
```

Then enforcement using the Global Constraints form. Both `rc=0`.

- [ ] **Step 6: Live verification**

```bash
cd /home/omar/ai-projects/research-system-rag && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

```bash
D=/home/omar/ai-projects/research-system-rag-data
curl -s -m 90 -H "X-Dashboard-Token: $(cat $D/.dashboard_token)" http://127.0.0.1:8700/api/status \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('downloads:', d['downloads']); print('tags:', d['tags']['active_count'], 'active,', d['tags']['held_count'], 'held')"
rc=$?
```

Expected: `staged_pdfs` 11612, `prefetch_target` 30000, `stalled` **True** (the live log's newest line is a stall), `new_last_pass` a small number, and **33 active / 0 held**. `GET` only — no run is started, no tag is modified. Report the actual output verbatim.

**Leave the repo on `main` with the dashboard running:**

```bash
cd /home/omar/ai-projects/research-system-rag && git checkout main && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

- [ ] **Step 7: Commit, push, PR**

Open one PR titled `Dashboard counter clarity + persistent tag pool`. **Do not merge.** Poll `gh pr checks <n>` at 60-second intervals until every check is final; both must read `pass`.

---

## Report contract

Return only: status, commit SHAs, PR number, real `rc` values for pytest and enforcement, the Step 6 live output verbatim, confirmation that `<data_dir>/config.yaml` was **not** modified (`git status` cannot show it — it is outside the repo; verify with its mtime before and after), the final CI conclusion for each check by name, and confirmation the repo was left on `main` with the dashboard running.
