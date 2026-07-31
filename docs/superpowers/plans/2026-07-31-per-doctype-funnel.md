# Per-doc_type Funnel (Book Counters) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show books and papers as separate pipeline funnels in the dashboard, so a dropped book can be watched moving through harvested → parsed → chunked → summarized → embedded → stored → done instead of only appearing once it is finished.

**Architecture:** One additive `by_doc_type` block on `GET /api/status`, built in `app/dashboard/status.py::read_corpus` from a `ingest_state ⋈ papers` join grouped by `doc_type` and `stage`, reusing the existing `_funnel_from_stage_counts` helper per type. The existing combined `funnel` is **unchanged** — operator decision, because `read_telemetry`'s ETA and papers-per-hour math read `funnel["done"]`.

**Tech Stack:** Python 3.12, stdlib `sqlite3` (read-only URI), stdlib `http.server`, pytest, pytest-socket.

## Global Constraints

- Backlog item **D-3** (`docs/BACKLOG.md`).
- **The combined `funnel` block must not change shape, keys, or values.** It is additive work only. `status.read_telemetry` derives ETA and papers/hour from `funnel["done"]`; a change there silently corrupts both.
- **Do not modify** `contracts/`, `rag/`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`, `.github/`.
- **Never** write to `/home/omar/ai-projects/research-system-rag-data/papers.db`. Reads go through `status._ro_connect` (`file:…?mode=ro`).
- Never `git stash`. There is an unrelated stash on the stack (`stash@{0}`) — leave it alone.
- Never merge a PR; never pass `--admin` or a branch-protection bypass.
- Never add `Co-authored-by: Claude`, `Claude-Session:`, or "Generated with Claude Code" to any commit or PR body.
- Environment: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — chained in ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- **Step zero:** `git fetch origin && git checkout -b per-doctype-funnel origin/main`. A stale local `main` previously made CI check (e) flag foundation files the branch never touched.
- **Local enforcement needs a synthesized event payload** — the env var alone raises `KeyError`, and BOTH `number` and `labels` are required (check (e) reads the label list):

  ```bash
  EV=$(mktemp) && printf '{"number":0,"labels":[],"pull_request":{"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
    GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  rc=$?
  ```

- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`. Never add a label or weaken a test to make a check go green.

---

## Background the implementer needs

The stage lives in `ingest_state`, the document type lives in `papers`. They join on `paper_id`:

```sql
SELECT p.doc_type, i.stage, COUNT(*)
FROM ingest_state i JOIN papers p ON p.paper_id = i.paper_id
GROUP BY p.doc_type, i.stage;
-- verified live 2026-07-31:  book | done | 5      paper | done | 12328
```

`_funnel_from_stage_counts` (`status.py:143`) converts `{stage: count}` into the **cumulative** funnel the dashboard shows: each stage's number is that stage plus every later one, i.e. "reached at least this stage". Reuse it per doc_type rather than reimplementing that semantics.

---

### Task 1: `by_doc_type` in `read_corpus`

**Files:**
- Modify: `app/dashboard/status.py` (`read_corpus` at line 101, plus one new helper)
- Test: `app/dashboard/test_status.py`

**Interfaces:**
- Consumes: `_ro_connect`, `_funnel_from_stage_counts`, `_STAGES` — all already in `status.py`.
- Produces: `read_corpus(data_dir)` gains a `"by_doc_type"` key: `{doc_type: {stage: int, ..., "quarantined": int}}`. Task 2 renders it.

- [ ] **Step 1: Write the failing tests**

Add to `app/dashboard/test_status.py`. Use whatever scratch-DB helper the file already defines for `read_corpus`; if there is none, build the tables inline as below.

```python
def test_read_corpus_splits_the_funnel_by_doc_type(tmp_path):
    import sqlite3
    db = tmp_path / "papers.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ingest_state (paper_id TEXT PRIMARY KEY, stage TEXT NOT NULL, "
                 "updated_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE papers (paper_id TEXT PRIMARY KEY, doc_type TEXT)")
    conn.execute("CREATE TABLE quarantine (paper_id TEXT, stage TEXT)")
    conn.execute("CREATE TABLE quarantine_diagnostics (paper_id TEXT PRIMARY KEY, error_type TEXT)")
    rows = [
        ("b1", "done", "book"), ("b2", "done", "book"),
        ("b3", "parsed", "book"),                        # book still mid-pipeline
        ("p1", "done", "paper"), ("p2", "embedded", "paper"),
    ]
    for pid, stage, dt in rows:
        conn.execute("INSERT INTO ingest_state VALUES (?,?,'2026-07-31T00:00:00Z')", (pid, stage))
        conn.execute("INSERT INTO papers VALUES (?,?)", (pid, dt))
    conn.commit()
    conn.close()

    out = status.read_corpus(tmp_path)

    # The combined funnel is UNCHANGED -- cumulative over all 5 documents.
    assert out["funnel"]["done"] == 3
    assert out["funnel"]["parsed"] == 5

    books = out["by_doc_type"]["book"]
    assert books["done"] == 2
    assert books["parsed"] == 3      # cumulative: 2 done + 1 sitting at parsed
    assert books["harvested"] == 3

    papers = out["by_doc_type"]["paper"]
    assert papers["done"] == 1
    assert papers["embedded"] == 2


def test_read_corpus_by_doc_type_is_empty_when_db_is_unreadable(tmp_path):
    out = status.read_corpus(tmp_path / "no_such_dir")
    assert out["by_doc_type"] == {}
    assert out["funnel"]["done"] is None      # existing null-funnel behavior, unchanged


def test_read_corpus_by_doc_type_counts_quarantine_per_type(tmp_path):
    import sqlite3
    db = tmp_path / "papers.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ingest_state (paper_id TEXT PRIMARY KEY, stage TEXT NOT NULL, "
                 "updated_at TEXT NOT NULL)")
    conn.execute("CREATE TABLE papers (paper_id TEXT PRIMARY KEY, doc_type TEXT)")
    conn.execute("CREATE TABLE quarantine (paper_id TEXT, stage TEXT)")
    conn.execute("CREATE TABLE quarantine_diagnostics (paper_id TEXT PRIMARY KEY, error_type TEXT)")
    conn.execute("INSERT INTO ingest_state VALUES ('b1','parsed','2026-07-31T00:00:00Z')")
    conn.execute("INSERT INTO papers VALUES ('b1','book')")
    conn.execute("INSERT INTO quarantine VALUES ('b1','parsed')")
    # A paper that was quarantined but LATER succeeded must not count (OG-44, same rule
    # quarantine_summary already applies to the combined number).
    conn.execute("INSERT INTO ingest_state VALUES ('p1','done','2026-07-31T00:00:00Z')")
    conn.execute("INSERT INTO papers VALUES ('p1','paper')")
    conn.execute("INSERT INTO quarantine VALUES ('p1','parsed')")
    conn.commit()
    conn.close()

    out = status.read_corpus(tmp_path)

    assert out["by_doc_type"]["book"]["quarantined"] == 1
    assert out["by_doc_type"]["paper"]["quarantined"] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -k by_doc_type -v
rc=$?
```

Expected: FAIL, `KeyError: 'by_doc_type'`.

- [ ] **Step 3: Implement**

In `read_corpus`, add the per-type read alongside the existing queries — inside the **same** `try`/`except sqlite3.Error` and the same connection, so one extra query cannot change the existing failure behavior:

```python
        stage_counts = dict(
            conn.execute("SELECT stage, count(*) FROM ingest_state GROUP BY stage").fetchall()
        )
        quarantine_count, reason_pairs = quarantine_summary(conn)
        by_doc_type = _funnels_by_doc_type(conn)
```

and return it:

```python
    return {
        "funnel": funnel,
        "by_doc_type": by_doc_type,
        "quarantine_reasons": quarantine_reasons,
    }
```

The `_ro_connect(db_path) is None` early return and the `except sqlite3.Error` path must **both** gain `"by_doc_type": {}` — an unreadable DB yields no per-type data, not a fabricated empty funnel per type.

New helper, beside `_funnel_from_stage_counts`:

```python
# Books and papers share one pipeline but are worth watching apart: a dropped book that stalls at
# `parsed` is invisible in the combined funnel, which is dominated by ~12k papers. The stage lives
# in `ingest_state`, the type in `papers`; they join on paper_id. Cumulative semantics come from
# `_funnel_from_stage_counts` -- reused per type rather than reimplemented, so the split can never
# drift from the combined funnel's meaning.
def _funnels_by_doc_type(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    rows = conn.execute(
        "SELECT p.doc_type, i.stage, count(*) FROM ingest_state i "
        "JOIN papers p ON p.paper_id = i.paper_id GROUP BY p.doc_type, i.stage"
    ).fetchall()
    per_type: dict[str, dict[str, int]] = {}
    for doc_type, stage, n in rows:
        per_type.setdefault(str(doc_type), {})[str(stage)] = int(n)

    quarantined = dict(
        conn.execute(
            # Same OG-44 exclusion `quarantine_summary` applies: `quarantine` is an append-only
            # dead-letter log, so a paper that later succeeded must not still read as stuck.
            "SELECT p.doc_type, count(*) FROM quarantine q "
            "JOIN papers p ON p.paper_id = q.paper_id "
            "WHERE NOT EXISTS (SELECT 1 FROM ingest_state s "
            "                  WHERE s.paper_id = q.paper_id AND s.stage = 'done') "
            "GROUP BY p.doc_type"
        ).fetchall()
    )

    out = {}
    for doc_type, stage_counts in per_type.items():
        funnel = _funnel_from_stage_counts(stage_counts)
        funnel["quarantined"] = int(quarantined.get(doc_type, 0))
        out[doc_type] = funnel
    return out
```

Note the shape difference from the combined funnel, and keep it: `funnel["quarantined"]` is `None` when the DB is unreadable, but a per-type `quarantined` is a real `0` when that type simply has none — here the type key only exists because the join produced rows for it.

- [ ] **Step 4: Run the tests**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_status.py -q
rc=$?
```

Expected: PASS, `rc=0`. **Every pre-existing `test_status.py` test must still pass** — if a combined-funnel test broke, you changed the combined funnel, which this plan forbids.

- [ ] **Step 5: Commit**

```bash
git add app/dashboard/status.py app/dashboard/test_status.py
git commit -m "Add per-doc_type funnels to read_corpus

Books are invisible in the combined funnel, which ~12k papers dominate: a dropped
book stalled at 'parsed' looks identical to one that finished. by_doc_type joins
ingest_state to papers and reuses _funnel_from_stage_counts per type, so the split
cannot drift from the combined funnel's cumulative semantics. Per-type quarantine
applies the same OG-44 later-succeeded exclusion. The combined funnel is unchanged
-- read_telemetry's ETA and papers/hour math read funnel['done']."
```

---

### Task 2: Surface it on `/api/status` and in the UI

**Files:**
- Modify: `app/dashboard/server.py` (`_status_dict`)
- Modify: `app/dashboard/static/index.html`
- Test: `app/dashboard/test_server.py`

**Interfaces:**
- Consumes: `read_corpus(data_dir)["by_doc_type"]` from Task 1.

- [ ] **Step 1: Write the failing test**

```python
def test_status_route_includes_by_doc_type_block(running_server):
    body = _get_status(running_server)
    assert "by_doc_type" in body
    # The combined funnel must survive untouched -- it is what ETA/rate math reads.
    assert "funnel" in body
    assert "done" in body["funnel"]
```

Use whatever status-GET helper `test_server.py` already defines rather than the illustrative `_get_status` name.

- [ ] **Step 2: Run to verify failure**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest app/dashboard/test_server.py -k by_doc_type -v
rc=$?
```

Expected: FAIL, `KeyError: 'by_doc_type'`.

- [ ] **Step 3: Add it to `_status_dict`**

`_status_dict` already binds `corpus = status_module.read_corpus(data_dir)`. Add one key to the returned dict, next to `"funnel"`:

```python
        "by_doc_type": corpus["by_doc_type"],
```

Do not touch the existing `"funnel"` entry.

**Read the current `app/dashboard/server.py` before editing.** It changed substantially across PRs #206/#208/#209 — `_status_dict` now also carries `drop_in` and `usage` blocks and calls `controller.promote_pending_drop_in`. Do not assume this plan's line numbers still match.

- [ ] **Step 4: Frontend**

Add a "By document type" panel to `app/dashboard/static/index.html`, matching the existing panels' structure and styling — the `drop_in` panel added by PR #208 is the closest template. Render one compact row per doc_type (`book`, `paper`) showing the seven stages plus `quarantined`, so a book sitting at `parsed` is visible at a glance.

Leave the existing combined-funnel display exactly as it is. If `by_doc_type` is `{}`, render "unavailable" rather than a row of zeros.

- [ ] **Step 5: Full suite and enforcement**

```bash
source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && \
  python -m pytest -q
rc=$?
```

Expected: `rc=0`. Then run enforcement using the synthesized-payload form in Global Constraints.

- [ ] **Step 6: Live verification**

The operator's dashboard runs on port 8700 against `/home/omar/ai-projects/research-system-rag-data`. Restart it on your branch and read the block back:

```bash
cd /home/omar/ai-projects/research-system-rag && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

```bash
D=/home/omar/ai-projects/research-system-rag-data
curl -s -m 90 -H "X-Dashboard-Token: $(cat $D/.dashboard_token)" \
  http://127.0.0.1:8700/api/status | python3 -c "import json,sys; print(json.load(sys.stdin)['by_doc_type'])"
rc=$?
```

Expected: `book` and `paper` entries; against the live corpus as of 2026-07-31 that is `book: done=5` and `paper: done=12328`. `GET` only — nothing is written and no run is started. **Report the actual output.**

**When you are finished, leave the repository on `main` with the dashboard running**, so the operator's dashboard is not left serving an unmerged branch or left down:

```bash
cd /home/omar/ai-projects/research-system-rag && git checkout main && scripts/dashboard.sh stop && scripts/dashboard.sh start
rc=$?
```

- [ ] **Step 7: Commit, push, open the PR**

```bash
git add app/dashboard/server.py app/dashboard/test_server.py app/dashboard/static/index.html
git commit -m "Surface per-doc_type funnels on /api/status and in the dashboard

One additive by_doc_type block plus a panel showing each type's stage funnel and
quarantine count. The combined funnel display is untouched."
git push -u origin HEAD
```

Open the PR. **Do not merge.** Poll `gh pr checks <n>` at 60-second intervals until every check is final; both `enforcement` and `unit-tests` must read `pass`.

---

## Report contract

Write your full report to the report file path given in your dispatch. Return only: status, commit SHAs, PR number, real `rc` values for pytest and enforcement, the Step 6 `by_doc_type` output verbatim, the final CI conclusion for each check by name, confirmation that the repo was left on `main` with the dashboard running, and any concerns.
