# Dashboard `/api/status` Config-Discovery Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `GET /api/status` return 200 when the dashboard's working directory contains no `config.yaml`, by loading the config from the `--data-dir` the server was already started with.

**Architecture:** `app/dashboard/server.py::_static_config()` calls a bare `load_config()`, which since T-DOC89 discovers via `RAG_CONFIG` → cwd → walk-up. `scripts/dashboard.sh` `cd`s to the repo root, which has no deployed `config.yaml`, so every status poll raises `ContractError`. The fix mirrors the pattern `app/dashboard/controller.py::_load_base_config` already uses: prefer `<data_dir>/config.yaml`, fall back to discovery. `data_dir` is threaded from the existing `--data-dir` flag into `_static_config` and `_search_display`.

**Tech Stack:** Python 3.12, stdlib `http.server`, `functools.lru_cache`, pytest, pytest-socket.

## Global Constraints

- Deliverable 0 of `docs/superpowers/specs/2026-07-30-dashboard-dropin-and-usage-design.md` §1.
- **Do not modify** `contracts/`, `rag/config.py`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, or `.github/` — CODEOWNERS foundation-freeze. This fix needs none of them.
- **Never** write to `/home/omar/ai-projects/research-system-rag-data/papers.db`, and never run ingest, rechunk, delete, or snapshot.
- Never run `git stash` (the stash stack is shared across worktrees in this repo).
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit message or PR body.
- Do not merge the PR, and never pass `--admin` or any branch-protection bypass. Open it and stop.
- Environment: activate conda env `agent-rag-research`, chained in ONE shell call, e.g.
  `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && python -m pytest ...`
- Report real exit codes: put `rc=$?` on the line **immediately** after the command, never after an `echo` or through a pipe.
- `lru_cache` behavior must be preserved: config is read once per process, not once per request.

---

### Task 1: Thread `data_dir` into `_static_config` and `_search_display`

**Files:**
- Modify: `app/dashboard/server.py:161-180` (`_static_config`, `_search_display`)
- Modify: `app/dashboard/server.py:224-252` (`_status_dict` — three `_static_config()` call sites)
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `rag.config.load_config(path: Path | None = None) -> Config`; `contracts.config.Config` with fields `top_k`, `rerank_depth`, `parse_batch_size`, `hybrid_dense_weight`.
- Produces: `_static_config(data_dir: Path) -> Config` and `_search_display(data_dir: Path) -> dict`. Nothing outside `server.py` calls either.

- [ ] **Step 1: Write the failing test**

Add to `app/dashboard/test_server.py`. The `monkeypatch.chdir` is the load-bearing part — without it the test passes against the buggy code, because pytest's own cwd is the repo root only sometimes.

```python
def test_status_route_reads_config_from_data_dir_not_cwd(tmp_path, monkeypatch):
    """T-DOC90 regression: `_static_config` used a bare `load_config()`, so after T-DOC89 changed
    discovery to RAG_CONFIG -> cwd -> walk-up, a dashboard started by `scripts/dashboard.sh` (which
    cd's to the repo root, where no deployed config.yaml exists) raised ContractError on EVERY
    `GET /api/status`. Serving from a cwd with no config.yaml is the exact shape that broke."""
    import json
    import shutil
    import urllib.request
    from pathlib import Path

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    shutil.copy(Path(__file__).resolve().parents[2] / "config.example.yaml",
                data_dir / "config.yaml")

    empty_cwd = tmp_path / "no_config_here"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    monkeypatch.delenv("RAG_CONFIG", raising=False)

    server = server_mod.build_server(data_dir, "tok", 0, host="127.0.0.1")
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/status",
            headers={"X-Dashboard-Token": "tok"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
    finally:
        server.shutdown()
        server.server_close()

    # Proves the config came from data_dir, not from a default or a stray discovery hit.
    expected = controller_mod.load_config(data_dir / "config.yaml")
    assert body["search"]["top_k_default"] == expected.top_k
    assert body["search"]["hybrid_dense_weight"] == expected.hybrid_dense_weight
```

If `test_server.py` already has a helper that starts a server on an ephemeral port (check the `running_server` fixture at roughly line 214), reuse it instead of the inline `build_server`/thread block — but you must still apply `monkeypatch.chdir(empty_cwd)` and point `--data-dir` at a `tmp_path` holding a real `config.yaml`. Do not weaken either condition.

- [ ] **Step 2: Run the test to verify it fails**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_server.py::test_status_route_reads_config_from_data_dir_not_cwd -v
rc=$?
```

Expected: FAIL. The response is a 500, or the request raises, with `ContractError: no config.yaml found` in the server's stderr.

- [ ] **Step 3: Change `_static_config` and `_search_display` to take `data_dir`**

Replace `app/dashboard/server.py:161-180`. Keep the existing module docstring/comment block above `_static_config` and extend it with the sentence shown.

```python
# T-DOC90: `data_dir`-first, discovery-fallback -- the same two-branch shape
# `controller.py::_load_base_config` already uses. A bare `load_config()` here meant every
# `GET /api/status` raised ContractError whenever the process's cwd had no config.yaml, which is
# exactly how `scripts/dashboard.sh` launches it (it cd's to the repo root). `lru_cache` is keyed
# on `data_dir` so the "read once per process" behavior is unchanged.
@lru_cache(maxsize=1)
def _static_config(data_dir: Path) -> Config:
    data_dir_config = data_dir / "config.yaml"
    if data_dir_config.exists():
        return load_config(data_dir_config)
    return load_config()


def _search_display(data_dir: Path) -> dict:
    return {
        "top_k_default": _static_config(data_dir).top_k,
        "rerank_pool_size": min(_static_config(data_dir).rerank_depth, _RERANKER_MAX_BATCH_SIZE),
    }
```

- [ ] **Step 4: Update the three call sites in `_status_dict`**

In `app/dashboard/server.py::_status_dict`, `_static_config` is called three times. All three take `data_dir`, which is already that function's first parameter:

```python
            "parse_batch_size": (
                manifest_parse_batch_size if manifest_parse_batch_size is not None
                else _static_config(data_dir).parse_batch_size
            ),
```

```python
        "search": {
            **_search_display(data_dir),
            "hybrid_dense_weight": _static_config(data_dir).hybrid_dense_weight,
        },
```

- [ ] **Step 5: Find and fix any remaining callers**

```bash
grep -n "_static_config()\|_search_display()" app/dashboard/*.py
rc=$?
```

Expected: no output (`rc=1` from grep means no matches, which is success here). If `_LazyMcpServer` or any other site still calls `_static_config()` with no argument, give it the `data_dir` it already holds. Do not add a module-level default value for `data_dir` — a default would silently reintroduce the bug.

- [ ] **Step 6: Run the new test and the full dashboard suite**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/ -q
rc=$?
```

Expected: PASS, `rc=0`. `test_server.py` has existing status-route tests (`test_status_route_with_valid_token_is_200`, `test_status_route_shape_matches_api_contract`, `test_status_route_includes_tei_block`, `test_status_route_shape_includes_run_mode`) — all must still pass. If any of them broke, you changed a call site wrong; do not edit those tests to accommodate the change.

- [ ] **Step 7: Run the full suite and the CI enforcement checks**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest -q
rc=$?
```

Expected: `rc=0`.

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  GITHUB_EVENT_NAME=pull_request python -m ci.run_enforcement
rc=$?
```

Expected: `rc=0`, "enforcement: PASS". Use `GITHUB_EVENT_NAME=pull_request`, **not** `push` — the two scan different diffs, and a local `push`-scoped pass has previously coexisted with a CI `pull_request`-scoped failure on the same branch.

- [ ] **Step 8: Commit**

```bash
git add app/dashboard/server.py app/dashboard/test_server.py
git commit -m "T-DOC90: load dashboard config from --data-dir, not cwd

_static_config used a bare load_config(), so after T-DOC89 changed discovery
to RAG_CONFIG -> cwd -> walk-up, every GET /api/status raised ContractError
when the process cwd held no config.yaml -- which is how scripts/dashboard.sh
launches it. Mirrors controller.py::_load_base_config's data-dir-first shape.
lru_cache is now keyed on data_dir, preserving read-once-per-process."
```

- [ ] **Step 9: Verify against the live dashboard**

The operator's dashboard is running on port 8700 against `/home/omar/ai-projects/research-system-rag-data`. Restart it on the fixed code and confirm the route returns 200:

```bash
cd /home/omar/ai-projects/research-system-rag && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

```bash
D=/home/omar/ai-projects/research-system-rag-data
curl -s -o /dev/null -m 60 -w "%{http_code}\n" \
  -H "X-Dashboard-Token: $(cat $D/.dashboard_token)" http://127.0.0.1:8700/api/status
rc=$?
```

Expected: `200`. This is read-only (`GET`), touches no corpus data, and starting/stopping the dashboard is explicitly authorized for this task. Report the actual HTTP code you observed — do not report success without this number.

- [ ] **Step 10: Open the PR**

```bash
git push -u origin HEAD
gh pr create --title "T-DOC90: load dashboard config from --data-dir, not cwd" --body "$(cat <<'EOF'
## Problem

`GET /api/status` returned 500 on every poll, leaving the dashboard showing
"run - unknown / stale / reconnecting". `app/dashboard/server.py::_static_config`
called a bare `load_config()`; T-DOC89 changed discovery to `RAG_CONFIG` -> cwd ->
walk-up, and `scripts/dashboard.sh` cd's to the repo root, which has no deployed
`config.yaml`.

The previously-running dashboard process started 2026-07-25, three days before
T-DOC89 landed, so the regression stayed invisible until the process was restarted.

## Fix

Prefer `<data_dir>/config.yaml`, fall back to discovery -- the same two-branch shape
`controller.py::_load_base_config` already uses. `lru_cache` keyed on `data_dir`
preserves read-once-per-process.

## Verification

- New regression test serves `/api/status` from a cwd with no `config.yaml` and a
  `--data-dir` that has one. It fails against the old code.
- Full suite green; `ci.run_enforcement` PASS under `GITHUB_EVENT_NAME=pull_request`.
- Live check against the operator's dashboard on :8700 returns 200.
EOF
)"
```

Do **not** merge. Report the PR number and stop.

---

## Report contract

Write your full report to the report file path given in your dispatch. Return only:
- status (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`)
- the commit SHA and PR number
- one line of test summary with the real `rc` values
- the HTTP code from Step 9
- any concerns
