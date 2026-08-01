# Backlog — open work queue

Working queue for `research-system-rag`. Close an item by deleting its row and recording the
outcome in the relevant design/closeout doc — this file tracks what is *open*, not what happened.

Status: **OPEN** (not started) · **IN PROGRESS** (branch/PR exists) · **BLOCKED** (needs a decision)
· **READY** (green PR awaiting operator merge).

---

## Dashboard + telemetry programme (2026-07-30/31) — COMPLETE

Spec: `docs/superpowers/specs/2026-07-30-dashboard-dropin-and-usage-design.md`

| id | item | status | notes |
|---|---|---|---|
| D-0 | `/api/status` config-discovery fix | **DONE** | PR #206. `_static_config(data_dir)`. |
| D-1 | Drop-in as a first-class run type | **DONE** | PR #208. Live: 7 staged / 7 processed. |
| D-2a | MCP usage store + `app/serve.py` instrumentation | **DONE** | PR #207. Tool schemas verified intact after decoration. |
| D-2b | Dashboard `usage` panel | **DONE** | PR #209. |
| D-3 | Per-doc_type funnel (book counters) | **DONE** | PR #210. Live: `book done=5`, `paper done=12328`. Combined funnel deliberately unchanged. |
| D-4 | Test staleness audit | **DONE** | `docs/TEST-AUDIT-2026-07-31.md`. 78 files, ~1,440 test functions, 2 stale tests, 6 coverage gaps. T-1/T-2/T-3 fixed in PR #212. |
| D-5 | Counter clarity + persistent tag pool | **DONE** | PRs #214 (counters, tag pool), #215 (drag-and-drop, purge). |
| D-6 | Downloader tracking + restart control | **DONE** | PR #217. Live: `/proc` is the authority, orphan detection, Restart button, tag-staleness warning. |
| D-7 | Archive per-run `prefetch.log` + config before cleanup | **DONE — not yet exercised** | PRs #218/#219. No run has ended since merging, so the archive path has never actually fired. |
| D-8 | Bound retries for repeatedly-failing quarantined papers | **OPEN — lower priority since O-2** | O-2's fix removed the cause. Now a guard against future misclassification, not a live problem. See below. |
| D-9 | Land the orphaned unexpected-exception safety net | **OPEN — real unmerged work** | `T-SEED-combined-fixes`, the only genuinely unmerged branch in the repo. The pipeline has **no catch-all for unforeseen exceptions today**. See below. |

---

## D-9 — land the orphaned unexpected-exception safety net

**Found 2026-08-01 during branch cleanup.** `T-SEED-combined-fixes` is the **only genuinely
unmerged branch** left in the repo after 147 stale ones were deleted. Everything else was either
already in `main` under a different SHA (rebase-merge rewrites them) or throwaway integration
scratch. This one is real work that never landed.

### What it contains

```
e4e15aa  Add a per-paper unexpected-exception safety net with a circuit breaker
         rag/orchestrator.py  +123    rag/test_orchestrator.py  +152
885dd1a  Exclude ContractError from the unexpected-exception safety net
         rag/orchestrator.py   +15    rag/test_orchestrator.py   +23
fe450f0  Document the UNEXPECTED: quarantine-reason prefix in the M9 quarantine() contract
         DATA-CONTRACTS.md      +7
```

Authored 2026-07-14. A fourth commit on the branch (`T-DOC13: bound-retry-then-quarantine
TransientError in finish_phase()`) **is** already in `main` — only these three are missing.

### Why it matters

`main` has no such guard. Verified 2026-08-01 against `origin/main`:

```
rag/orchestrator.py  -- grep 'except Exception|BaseException|safety net|consecutive|breaker'  -> 0 matches
DATA-CONTRACTS.md    -- grep 'UNEXPECTED'                                                      -> 0 matches
```

So an exception from a path nobody anticipated still propagates and can end a whole run, rather
than quarantining the one paper that caused it. That is not hypothetical for this pipeline — in a
single session (2026-07-31/08-01) it hit a MinerU crash mid-parse, GROBID 500s on blank citations,
and a `build_corpus` supervisor that died leaving an orphaned child process. Those particular cases
are caught because each is wrapped explicitly; the *next* unanticipated one would not be.

Excluding `ContractError` from the net (commit `885dd1a`) is the part worth preserving carefully:
a contract violation is a bug that must surface loudly, not be swallowed into a quarantine row.

### Before implementing

- The branch is ~3 weeks stale and `rag/orchestrator.py` has moved since. **Expect a real rebase,
  not a fast-forward** — treat it as "re-apply the design", not "merge the branch".
- `DATA-CONTRACTS.md` is foundation-adjacent: the `UNEXPECTED:` prefix is a contract change and
  needs the usual sign-off.
- A circuit breaker needs a threshold. The branch picked one three weeks ago; check it still makes
  sense against current batch sizes before adopting it unexamined.

### Recovery

Both cleanup bundles live in the data dir (outside the repo, so `git clean` cannot reach them):

```
research-system-rag-data/stale-branches-2026-08-01.bundle   37 MB   (the 12 local-only branches)
research-system-rag-data/final9-branches-2026-08-01.bundle  21 MB   (the last 9 remote branches)
```

`T-SEED-combined-fixes` is in the second bundle **and** still on the remote — it was deliberately
not deleted.

---

## D-8 — bound retries for repeatedly-failing quarantined papers

**A correction first.** This was initially framed as "`cached_not_done` doesn't consult the
quarantine table." **That is wrong** — `app/build_corpus.py::cached_not_done` already subtracts
`_permanently_failed_ids(db_path)`, and its exclusions are deliberate and documented:

- `PermanentError` → **excluded** (a 404'd/withdrawn PDF; re-running cannot fix it). This exact bug
  was already found and fixed once: *"measured on the live corpus: 22 of 33 quarantined papers had
  a cached PDF and were being re-attempted every single run."*
- `TransientError` → **deliberately retried** — "a network blip should be retried."
- undiagnosed → **deliberately retried** — "unknown, not known-permanent."

So the retry behaviour is by design, not an oversight. Do not "fix" it by excluding those
categories; that would revert a considered decision.

### The actual problem

The design assumes `TransientError` means *transient*. For the GROBID failures it does not:

```
POST http://localhost:8070/api/processCitationList -> HTTP 500
```

These fail **identically on every run** against the same documents, but are recorded as
`TransientError`, so they are retried forever. Measured 2026-08-01 on the live corpus:

```
quarantine by error_type:   PermanentError 9 | TransientError 17 | undiagnosed 53
cached PDFs with no ingest_state row at all: 36   (24 of them quarantined)
```

Observed cost: a stopped run had been cycling batches of 16 and 28 of these, MinerU at **89% GPU
util / 6.5 GB VRAM**, with the `done` counter frozen at 12,333 across the whole run
(`build_corpus: batch of 16 ran but made zero net progress ... idle pass 1/12`).

### Proposed shape (not yet designed)

Bound the retries by **attempt count**, not by category — a `TransientError` that has failed N
times in a row is not transient, whatever it is labelled. That preserves the dead-letter design's
intent (retry genuine blips) while stopping the GPU burn on papers that fail every time.

Needs: an attempt counter per paper_id (the `quarantine` table is append-only, so repeat rows may
already be countable — check before adding schema, since `migrations/` is foundation-frozen), a
threshold, and a way for the operator to reset it after fixing the underlying service.

**Fix O-2 first.** If the GROBID 500s are a local service problem, fixing them may return ~24
papers to the corpus and shrink this problem rather than papering over it. Bounding retries is the
right guard either way, but it is a guard, not the cure.

---

## D-6 — downloader tracking, restart control, and tag-staleness warning

**Operator decisions (2026-08-01): fix tracking + add a Restart button; detect staleness by
comparing `tag_pool.json` mtime against the running downloader's start time.**

### The bug, measured 2026-08-01

Three PID sources, none pointing at the live downloader:

```
prefetch.pid  -> 3757989   DEAD
manifest pid  -> 196059    DEAD   (a finished full run)
actual runner -> 3012944   ALIVE  <- tracked by NEITHER
```

The orphan had been running ~20 hours. **Consequence:** the natural workflow — stop, change tags,
start — fails silently. `stop` acts on the manifest PID (dead, so it kills nothing), then
`download` spawns a *second* prefetcher alongside the orphan: two processes harvesting arXiv with
different query sets. The operator was told this workflow would work; it would not have.

Resolved by hand this session (orphan killed by PID; a tracked replacement started —
`run-30000-20260801_012157`, pid 655538). **`prefetch.pid` is still stale even after that
restart** — `_spawn_download` writes it, but nothing reconciles it against the manifest. That is
the same class of bug and is in scope here.

### Scope

1. **One source of truth for the downloader's PID.** Reconcile `prefetch.pid` and the run manifest,
   or drop `prefetch.pid` in favour of the manifest alone. `status.read_downloader` and
   `controller.stop` must agree on which process is the downloader. Whatever is chosen, `stop` must
   reach a live downloader in every case where one exists.
2. **Orphan detection.** If a `app.prefetch_pdfs` process is alive but matches neither source,
   surface it — the dashboard currently cannot see it at all, which is how one ran unnoticed for
   20 hours.
3. **"Restart downloader" button** = stop + start, as one operation, only enabled when tracking is
   sound. This is the workflow the operator asked for; the point of items 1–2 is making it safe
   rather than silently spawning duplicates.
4. **Tag-staleness warning.** `app/prefetch_pdfs.py:433` calls `load_config()` **once**, before its
   forever-loop, and never re-reads. A running downloader therefore keeps its launch-time queries
   no matter what the Tags panel says. When `tag_pool.json`'s mtime is newer than the running
   downloader's start time, show: *"Tag changes pending — restart the downloader to apply."*
   Comparing mtimes needs no new state and catches edits made outside the dashboard too.

### Non-goals

- Do **not** make `prefetch_pdfs` reload config mid-loop. Changing query sets underneath a
  running harvest is a bigger behavioural change than this fixes, and a restart is cheap.
- Do not auto-restart the downloader on a tag change. The operator decides when harvesting
  changes.

---

## Test-audit fix list — T-1..T-3 DONE (PR #212); T-4..T-8 deferred by the operator

From `docs/TEST-AUDIT-2026-07-31.md`. **T-1, T-2 and T-3 shipped in PR #212** (struck through below).
T-4..T-8 remain open and were explicitly deferred by the operator as lower value.

| # | item | kind | why |
|---|---|---|---|
| ~~T-1~~ | Funnel → telemetry end-to-end test | gap | `server.py` reads `corpus["funnel"].get("done")` — a `.get`. If that key is renamed/nested/dropped, ETA and papers/hour silently zero out and **no test fails**. Only ever protected by hand-diffing. |
| ~~T-2~~ | `ingest_local --drop-dir` CLI test | gap | The path production uses. A regression makes a drop-in run scan the wrong directory, stage nothing, and **exit 0**. |
| ~~T-3~~ | `promote_pending_drop_in` concurrency test | gap | Its docstring names the exact race it defends against; both existing tests are single-threaded. The right pattern already exists at `test_controller.py:1495`. |
| T-4 | `_pr_labels` payload-shape tests | gap | Neither the raise-on-missing-`labels` nor the fallback-on-missing-`number` path is exercised. |
| T-5 | Check (a)/(d) comment-matching tests | gap | Both regex raw added lines, so a comment-only mention trips them — a known, previously-hit failure mode with no test in either direction. |
| T-6 | `test_start_tei_containers_poll_timeout_s_overrides_the_module_default` | stale | Asserts nothing about elapsed time; if `poll_timeout_s` were dropped the test would still pass, just take ~30s. No `pytest-timeout` configured. |
| T-7 | `_crashed_before_target` drop-in-mode test | gap (minor) | Download mode has a regression test; drop-in mode relies on the same `target=0` guarantee untested. |
| T-8 | Vacuous `assert server is not None` (`rag/test_mcp_server.py:351`) | stale (cosmetic) | Delete the assert **line** only — the test still guards `McpServer.__init__` growing a required arg. |

Maintenance note (not a fix): 8 files under `rag/` carry stale `M1A-DORMANT (re-enable in M1b)`
header comments. Wrong prose, not wrong behavior — a docs pass, not a code change.

---

## Carried over from the book-RAG programme

Recorded in `docs/BOOK-INTEGRATION-CLOSEOUT.md`; repeated here so they stay visible.

| id | item | status | notes |
|---|---|---|---|
| B-1 | TOC pages mis-classified as headings | **OPEN** | Inflates chapter unit counts. |
| B-2 | Strategy-B junk chapter titles | **OPEN** | Some chapter titles are page furniture, not headings. |
| B-3 | T-DOC87 boundary re-ingest | **OPEN / will not ship as-is** | The marker-regex *correctness* fix shipped (PR #204); the boundary change regressed routing 2.8–3.5× past the floor and does not ship. |
| B-4 | Remove the unused outline splitter | **OPEN** | Review date 2026-08-29. Operator: "merge now, remove later if still unused in a month." |
| B-5 | Flip `reindex_idf` default to `--use-clone-swap` | **OPEN** | Non-destructive migration path exists (PR #203); the default is still the destructive one. |

---

## Operational / infrastructure

| id | item | status | notes |
|---|---|---|---|
| O-1 | Corpus is at its harvest ceiling | **BLOCKED — needs operator decision** | 12,333 done vs `target` 20,000. The downloader last reported `11556/30000 cached, only 6 new available`: arXiv is near-exhausted **for the current query filters**. Cannot reach 20k without changing `focus_area_queries` / `arxiv_categories` / the date window. Restarting runs will not move it. |
| O-2a | GROBID HTTP 500s (10 papers) | **FIXED — not yet verified on real data** | PR #221. Root cause: one blank citation makes GROBID 500 the whole batch (reproduced: `3 good + 1 empty` -> 500, `3 good` -> 200). Blanks now dropped and counted. **~10 papers should recover on the next ordinary run — that run has not happened yet.** |
| O-2b | GROBID `unparseable TEI` (6 papers) | **OPEN** | A *different* failure: GROBID returns 200 with malformed XML. Deliberately out of scope for #221. Worth checking whether it is also deterministic-but-labelled-transient — that pattern cost real GPU time. |
| O-3 | Stale `git stash` entry | **OPEN — do not touch without the owner** | `stash@{0}: On main: lessons-learned wip`. Provenance unknown; predates this session. |
| O-4 | Dashboard is unsupervised by design | **WORKING AS INTENDED** | `scripts/dashboard.sh`: "no process supervisor, no systemd unit, no --restart policy". Needed manual restarts several times this session (stale process, agent live-checks). Revisit only if it becomes a real irritation. |

### Investigated and closed — do not re-open

- **"Funnel stuck at 12333."** Not a defect. Every row in `ingest_state` is at stage `done`; no run
  was active. See O-1 for why the number cannot grow.
- **"Crashed run reported `done` instead of `failed`."** Not a defect. The operator stopped that
  run; `stopping → done` is correct and `_crashed_before_target` behaved as designed.
- **"TEI left down with nothing surfacing it."** Wrong on both halves. `status.read_tei_status()`
  live-probes both endpoints every poll and `index.html` renders it; `controller.load_for_mcp`
  restarts them, exposed as the **"Load for MCP"** button (`server.py:558`, `index.html:938`). An
  `ensure_tei_running` self-heal also exists in the query path.
- **"The test suite is probably stale."** Largely not. See `docs/TEST-AUDIT-2026-07-31.md`: every
  constant the 2026-07 experiments moved was already reflected in its tests. The real issue is
  thinness in specific places, not staleness.

---

## Standing constraints for any agent picking these up

- Never write `research-system-rag-data/papers.db`; read-only via `file:…?mode=ro`.
- Never modify `contracts/`, `rag/config.py`, `migrations/`, `rag/fakes/`, `fixtures/`, `ci/`,
  `.github/` — CODEOWNERS foundation-freeze.
- Never `git stash`; never merge a PR; never pass `--admin` or a branch-protection bypass.
- Never add AI-attribution trailers to a commit message or PR body.
- Branch from `origin/main` after an explicit `git fetch` — a stale local `main` previously made CI
  check (e) flag foundation files the branch never touched.
- **Never `git reset --hard origin/main` with unpushed local commits.** That silently discarded two
  committed docs on 2026-07-31 (recovered via `git reflog`). Commit docs on a branch and open a PR.
- Do not write pytest output to a shared `/tmp` path and poll it for a summary string. A killed run
  never writes the summary line, so the poll never terminates — this deadlocked an agent on
  2026-07-31. Run pytest in the foreground and read its exit code.
- Local enforcement needs a **synthesized event payload**, not just the env var:

  ```bash
  EV=$(mktemp) && printf '{"number":0,"labels":[],"pull_request":{"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  ```

  Supplying both fields is correct. Precisely (verified 2026-07-31): the reader is
  `ci/run_enforcement.py::_pr_labels`, **not** `changed_files.py::compute_diff_base`. `labels` is
  required — read without `.get`, so a missing key raises `KeyError`. `number` is optional by
  design and falls back to cached-payload mode.
- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`.
  Never add a label or weaken a test to make a check go green.
