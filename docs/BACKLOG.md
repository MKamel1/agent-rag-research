# Backlog — open work queue

Working queue for `research-system-rag`. Close an item by deleting its row and recording the
outcome in the relevant design/closeout doc — this file tracks what is *open*, not what happened.

Status: **OPEN** (not started) · **IN PROGRESS** (branch/PR exists) · **BLOCKED** (needs a decision)
· **READY** (green PR awaiting operator merge).

---

## Review implementation programme (RI series, 2026-08-22) — IN PROGRESS

Plan: `docs/superpowers/plans/2026-08-22-review-implementation.md`. Provenance: three independent
review campaigns run 2026-08-21 (code-defect rounds 1-2 and a five-lens methodology review), with
findings verified against live source and two competing implementation plans adjudicated into one.
Verbatim reviewer transcripts are in the untracked `reviews/` directory, backed up to
`~/ai-projects/backups/research-system-rag/`.

Tickets are grouped into workstreams by file ownership so concurrent work cannot collide.

| id | item | ws | status | notes |
|---|---|---|---|---|
| RI-1 | `DocumentStore` connection is single-thread-bound | A | **DONE** -- `b9be4c3` | `check_same_thread=False`, no lock -- `threadsafety==3` and the threaded consumer performs no writes, both verified. |
| RI-5 | `SqliteIngestState` requires a migration it does not perform | A | **DONE** -- `4695cd5` | Mirror `DocumentStore`: call `migrate()` in `__init__`, drop the unenforceable prose precondition. |
| RI-2 | Dashboard auth does not fail closed on `--token ""` | B | **DONE** -- `7adcd83` | Empty token matches a request sending no header at all. Refuse to start. |
| RI-6 | Token sidecar: crash window, no pid qualification, no corrupt tolerance | B | **DONE** -- `103edc5`, `8855db6` | `touch`/`write_text` can leave an empty token file, feeding RI-2 from a second direction. |
| RI-3 | Chunk payload has two definitions that have already drifted | C | **DONE** -- `112f6bb` | `rechunk`'s copy omits `author_orgs` -- a rechunked paper silently loses affiliation facets. |
| RI-4 | Resume path assumes the `papers` row exists | C | **DONE** -- `e5899f6` | Ships standalone, deliberately not folded into D-9: D-9's net is for *unknown* exceptions. |
| RI-8 | Downloader scan counts another corpus's downloader | D | **DONE** -- `5b3f968` | Qualify by `/proc/<pid>/cwd`; the config/db-path alternative is not observable at scan time. |
| RI-9 | `DATA-CONTRACTS.md` out of sync with shipped shapes | D | **DONE** -- `89aba70` | Per-field decision, not a blanket rewrite either way. |
| RI-11 | Compiled bytecode is tracked | D | **DONE** -- `799fb06` | Two `.pyc` files predate the ignore rule, which does not apply to tracked files. |
| RI-10 | Stale docstrings + absence honesty | E | **DONE** -- `189ac33` | *k* results are best-available, not *k* endorsements. No relevance floor -- see RI-M7. |
| RI-12 | Delete the CI exit-5 carve-out | F | **DONE** -- `1e928e4` | With 1,774 tests collected, exit 5 now means collection broke, and CI goes green on it. |
| RI-13 | `testpaths` fails open; add the mechanical guard | F | **DONE** -- `969233c` | The list is currently complete (85/86, one deliberate exclusion) -- the defect is structural. |
| RI-14 | `CODEOWNERS` does not cover `pyproject.toml` | F | **DONE** -- `5de07c7` | It carries `--disable-socket`, the zero-network test guarantee, ungated. |
| RI-15 | The eval reports a number whose rule it does not record | F | **DONE** -- `155a3e8` | New `title_leak` diagnostic + `scoring_rule` stamp. Reported alongside metrics, never subtracted. |
| RI-16 | Dashboard under-reports `rerank_pool_size` above 32 | - | **DONE** -- `88fd689` | Was latent, not live: rerank_depth was 32, so the clamp was a no-op. |
| RI-M1 | Archived run-log census | H | **DONE** -- `01de25e` | Its findings about what is NOT recoverable drove RI-17. |
| RI-M2 | Fabrication audit | I | **DONE** -- `637b60c` | Shares one harness with RI-M6. |
| RI-M3 | Sparse-arm ablation | G | **DONE** -- `060f2a5` | |
| RI-M4 | Truncation census | H | **DONE** -- `ce05f46` | Reports estimate-vs-real token calibration, not just bind rate. |
| RI-M5 | Waymo eval fixture | I | **DONE** -- `c1f0254` | 15-item grounded seed set; every excerpt re-verified against the live corpus DB. |
| RI-M6 | Groundedness harness | I | **DONE** -- `637b60c` | Rubric is PROVISIONAL -- needs operator sign-off before any output is treated as a baseline. |
| RI-M7 | Score-distribution census | G | **IN PROGRESS** | Settles whether a relevance floor is even choosable. |
| RI-17 | Prefetch logs carry no timestamps | - | **OPEN** | One-line fix, large payoff -- see below. |

### RI-16 — the dashboard's displayed rerank pool size still carries a clamp the pipeline dropped

Found 2026-08-22 while closing RI-10's stale-docstring sweep; the same staleness had already
crossed from a comment into live code.

`app/assembly.py:633` passes `rerank_pool_size = config.rerank_depth` **unclamped** into the
`Retriever` — the clamp to `rag/reranker.py`'s 32-item vendor batch limit was deliberately removed
once the reranker learned to pack an oversized pool into several batches and merge their scores
instead of truncating. But `app/dashboard/server.py:201` still displays
`min(rerank_depth, _RERANKER_MAX_BATCH_SIZE)`, and the comment above it still explains that as
mirroring a clamp `build_mcp_server` no longer applies.

**Latent, not live.** Both `config.example.yaml:104` and the operator's
`../research-system-rag-data/config.yaml:43` set `rerank_depth: 32`, so `min(32, 32)` is currently
the right answer and the dashboard is not misreporting anything today.

It is worth fixing anyway, and the reason is the trap: removing the clamp is precisely what made a
`rerank_depth` above 32 usable. The first operator to raise it gets a dashboard that silently
under-reports the pool the retrieval path actually uses — while the panel exists to be trusted about
exactly that kind of number (cf. D-10, dashboard number accuracy). Fix is to drop the `min(...)` and
correct the comment.

Deferred rather than folded into RI-2/RI-6: those were mid-flight in `app/dashboard/server.py` when
this was found, and two agents editing one file is the collision this programme's workstream split
exists to prevent.

### RI-17 — prefetch logging emits no timestamps, so its own history is unmeasurable

Found 2026-08-22 by RI-M1, which set out to mine the archived run logs and discovered that the
most valuable questions cannot be answered from them at all.

`app/prefetch_pdfs.py:431` calls `logging.basicConfig(level=logging.INFO)` with no `format=` or
`datefmt=`, so **no archived log line carries a timestamp**. Every number RI-M1's census can
recover is therefore a line-occurrence count or a configured constant echoed back — never a
measured duration. Stall duration, real download throughput, and whether the stall/retry
parameters in use are anywhere near the observed distribution are all unanswerable, for every run
already archived and every run until this changes.

A second, smaller gap: the log is opened in append mode (`app/dashboard/controller.py`, three
sites) across pause/resume with no separator line, so a paused-then-resumed run's segments cannot
be told apart.

**Fix:** pass a `format=` with `%(asctime)s` to that `basicConfig` call. One line. It cannot
recover the existing archive, which is exactly why it is worth doing now rather than after the
next long run — every day it waits is another day of history that stays unmeasurable.

Optionally, write a separator line on resume so segments are distinguishable.

**Operator decisions outstanding** (not agent work) -- see the plan's final section. The
time-sensitive one is **FD-1**: figure images from the 12,390-paper parse went to an OS temp
directory and are gone; redirecting `output_dir` to persistent storage is cheap *before* the next
large Waymo parse and a full re-parse after it.

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
| D-7 | Archive per-run `prefetch.log` + config before cleanup | **DONE — exercised** | PRs #218/#219. Per D-11's own investigation below, `run-13000-20260801_072158` (failed) had its logs archived once a later run's cleanup ran; the mechanism is confirmed working on real data, though a run ending `done` specifically hasn't been observed. |
| D-8 | Bound retries for repeatedly-failing quarantined papers | **OPEN — lower priority since O-2** | O-2's fix removed the cause. Now a guard against future misclassification, not a live problem. See below. |
| D-9 | Land the orphaned unexpected-exception safety net | **OPEN — real unmerged work** | `T-SEED-combined-fixes` is real unmerged work, but is no longer "the only genuinely unmerged branch in the repo" — `worktree-waymo-corpus-expansion` also has real unmerged commits (see `docs/WAYMO-CORPUS-STATUS.md`). The pipeline has **no catch-all for unforeseen exceptions today**. See below. |
| D-10 | Dashboard number accuracy: cross-check + dynamic tests | **DONE** | PR #227. `verify_numbers` reports `OK -- every field matches ground truth`. Caught and fixed a live orphan false positive. |
| D-11 | D-7 does not archive logs for a **failed** run | **DONE — `4e07eb4`** | Archives on the `failed` transition too, not only on `done`. |
| D-12 | `_live_prefetch_pids` counts observer processes as downloaders | **DONE — `f351a27`** | Matches the downloader by argv, not substring; the cross-check is now independent. |

---

## D-12 — the downloader scan counts its own observers

**Found 2026-08-01 while testing the #230 orphan fix on the live system.**

`status._live_prefetch_pids` scans `/proc/*/cmdline` for the substring `app.prefetch_pdfs`. Any
process whose command line *mentions* that string matches — including a diagnostic
`pgrep -af "app.prefetch_pdfs"`, a `grep`, or a shell one-liner. Each such transient process is
counted as a live downloader, and because it is not the manifest PID nor a descendant of it, it
trips **`orphan=True`**.

Observed: `live_pids=[2187579, 2188865]` where `2188865` was the observing command itself; a scan
that avoided naming the pattern in its own cmdline found **exactly one** real downloader.

### This bug is already documented — elsewhere

`scripts/dashboard.sh` carries the identical warning about its own PID lookup:

> a naive `pgrep -f "dashboard"` ALSO matches this very wrapper's own invocation, since its own
> path contains that substring too

and solves it by anchoring on `-m app\.dashboard\.server`. D-6's `_live_prefetch_pids`
reintroduced the flaw the wrapper had already fixed.

### Why `verify_numbers` did not catch it

`app/dashboard/verify_numbers.py` recomputes `downloader.live_pids` **the same way** the dashboard
does, so both agree on the same wrong answer and the cross-check reports `OK`. This is a real gap
in its independence guarantee — the property that makes it worth having. Any ground truth that
shares an implementation with the thing it checks is not ground truth.

### Proposed fix

1. Match the *executable invocation*, not a loose substring: require the cmdline to contain the
   `-m app.prefetch_pdfs` argument pair (argv-aware), the way `scripts/dashboard.sh` anchors on
   `-m app\.dashboard\.server`. A `pgrep` naming the module in a search pattern does not have
   `-m` as its own argv.
2. Exclude the scanning process itself and its own ancestors as a belt-and-braces guard.
3. **In `verify_numbers`, compute the ground truth differently from the reader** — e.g. resolve
   `/proc/<pid>/exe` and check argv structurally — so a shared bug cannot hide again.

### Severity

Cosmetic in practice today (a spurious orphan warning, no wrong action taken), but it undermines
two things that are supposed to be trustworthy: the orphan alarm, and the cross-check's claim of
independence. Item 3 matters more than items 1–2.

---

## D-11 — D-7 does not archive logs when a run ends as `failed`

**Found 2026-08-01 while verifying D-7 on a real run.**

`controller.reconcile()` calls `_cleanup_run_cwd` — which is where D-7's archiving lives — **only
when the reconciled status becomes `done`**:

```python
if manifest["status"] == "done":
    _cleanup_run_cwd(data_dir, manifest)
```

A run that gives up (`build_corpus: stalled ... giving up`) reconciles to **`failed`**, not `done`,
because `_crashed_before_target` sees `done_count < target`. Failed runs deliberately keep their
`run_cwd` so a later `resume()` can reuse it — that part is correct and documented.

**The consequence:** the archive never fires on the `failed` transition. Observed live —
`run-13000-20260801_072158` ended `failed` at 12,374/13,000, and no
`prefetch_run-*.log` / `config_*.yaml` appeared until the *next* run's `_start_locked` cleaned up
the abandoned manifest and archived it on the way out.

So the logs survived **only because another run followed**. A failed run that is never followed by
another keeps its diagnostics in `.run_overrides/<run_id>/` indefinitely — which is safe, but they
are then deleted un-archived the moment any later run starts... except that later cleanup *does*
archive them. The real exposure is narrower than it first looks:

- failed run, then another run starts → archived (verified working)
- failed run, then `resume()` → dir reused, nothing lost
- failed run, then the operator deletes `.run_overrides/` by hand → lost

**A failed run is exactly the one whose harvest diagnostics matter most**, so relying on a
follow-up run to trigger the archive is the wrong dependency.

### Proposed fix

Archive at the point the status becomes terminal, independently of whether the directory is then
deleted. Concretely: call `_archive_run_artifacts` on the `failed` transition in `reconcile()` too,
**without** calling `_cleanup_run_cwd` (which must keep its current resume-preserving behaviour).
Archiving is idempotent (`shutil.copy2` over the same names), so a later cleanup re-archiving the
same files is harmless.

### Test

A run reconciled `running -> failed` must produce `prefetch_<run_id>.log` and `config_<run_id>.yaml`
in the data dir **while `run_cwd` still exists**, proving the archive does not depend on deletion.

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
| O-1 | Corpus is at its harvest ceiling | **CLOSED — automated, not manual (commits `70940dc`/`f8a7f69`/`013f7cf`)** | 12,333 done vs `target` 20,000. The downloader last reported `11556/30000 cached, only 6 new available`: arXiv is near-exhausted **for the current query filters**. Rather than requiring the operator to widen queries by hand, `build_corpus` now finishes as `completed` (reconciled `done`, not `failed`) when supply is exhausted, and the run panel surfaces the supply-exhausted outcome directly. Cannot reach 20k without changing `focus_area_queries` / `arxiv_categories` / the date window — that part still needs an operator decision — but the completion path itself is automatic. |
| O-2a | GROBID HTTP 500s (10 papers) | **FIXED — PR #221's blank-citation fix was superseded, not merely followed up** | PR #221's `.strip()` blank-citation filter only caught empty/whitespace citations; `25543f1` (2026-08-01) widened it to drop any citation with no alphanumeric character. Neither was the real fix: `fa70acd` (2026-08-01, later same day) found the actual culprit is MinerU leaking raw C0 control bytes into ordinary alphanumeric-rich citation text, which neither prior filter ever caught, and **replaced** the alphanumeric-drop filter with an in-place sanitize step that strips C0 bytes and drops nothing. Validated against all 7 sampled real failing batches: every one flips 500→200 with zero references lost. |
| O-2b | GROBID `unparseable TEI` (6 papers) | **OPEN** | A *different* failure: GROBID returns 200 with malformed XML. Deliberately out of scope for #221. Worth checking whether it is also deterministic-but-labelled-transient — that pattern cost real GPU time. |
| O-3 | Stale `git stash` entry | **OPEN — do not touch without the owner** | `stash@{0}: On main: lessons-learned wip`. Provenance unknown; predates this session. |
| O-4 | Dashboard is unsupervised by design | **WORKING AS INTENDED** | `scripts/dashboard.sh`: "no process supervisor, no systemd unit, no --restart policy". Needed manual restarts several times this session (stale process, agent live-checks). Revisit only if it becomes a real irritation. |

---

## Other

| id | item | status | notes |
|---|---|---|---|
| W-1 | Waymo second-corpus resume | **IN PROGRESS — v2 build running since 2026-08-07** | Superseded by the v2 plan (`docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md`), merged in PR #238 along with the scout, the 114-id ground-truth list, and the reconfigured `waymo/data/config.yaml`. The scout is no longer stranded on an unmerged branch. Phase A (drain the 825) is executing; Phases B/C follow. Post-mortem of the *v1* attempt stays at `docs/WAYMO-CORPUS-STATUS.md`. |
| T-ORG1 | Wire author-org tagging into the ingest pipeline | **DONE — `01e2aed`** | Migration `migrations/0005_author_orgs.sql` adds nullable `papers.raw_affiliations`/`papers.author_orgs` (JSON); `PaperRecord` (`contracts/document_store.py`) and `VectorPayload`/`SearchFilters` (`contracts/vector_index.py`) carry the evidence and the new `author_org` filter; `rag/orchestrator.py::_finish` computes both (cheap, pure, no new I/O) via a new `rag/author_org_tagger.py::match_known_orgs_with_method`, which returns `AuthorOrgMatch(name, method)` — `method` is `"email_domain"` or `"keyword"`, `email_domain` winning when both fire — instead of a bare boolean, because the underlying signal is far from exact (see T-ORG2 below). `rag/document_store.py::put`/`get` round-trip both fields; `rag/vector_index.py`/`rag/fakes/fake_vector_store.py` implement the `author_org` filter identically to the existing `doc_type` filter (a legacy point with no `author_orgs` key matches nothing, unlike `doc_type`'s "absent means paper" default — there is no safe default for "was this ever checked"). `rag/mcp_server.py`'s `semantic_search`/`search_papers` docstrings state the precision/recall plainly so a caller doesn't treat a hit as confirmed authorship. **Not authoritative — never treat `author_orgs`/the `author_org` filter as ground truth**; the enumerated id list (`fixtures/waymo/waymo_authored_ids.txt`) remains the exact source for the Waymo-authored-vs-adjacent split on this corpus. |
| T-ORG2 | Affiliation authorship signal: precision 0.043, and the evidence is missing for half the corpus | **DONE — `d3e79c3`** | Root cause: `_is_candidate_affiliation_block` accepted page-0 front matter including the **abstract**, so any paper benchmarking on a Waymo dataset keyword-matched as Waymo-**authored**. Fixed by capping candidate blocks at 40 words (with an email-address override so a genuine affiliation merged into a longer block isn't dropped) — front-matter blocks containing "waymo" run a median of 6 words in genuinely Waymo-authored papers vs. 166 in the rest. Measured live over the 1,741 done papers against the 114 enumerated Waymo-authored ids: **precision 0.569, recall 0.763** (up from an honest pre-fix 0.311/0.851 — the 0.043 figure this row previously reported was measured before the 114 known-positive papers were ingested, so it undercounted true positives it hadn't seen yet). Email-domain-only matching, floated as a higher-precision alternative, scores precision 0.700 but recall only 0.123 (81% of extracted affiliation regions carry no email at all) — which is why T-ORG1 stores *which* signal fired (`AuthorOrgMatch.method`) rather than picking one matching strategy and discarding the other. At 0.569 precision, close to half of keyword-derived tags are still wrong — this signal is not authoritative for any downstream use. |
| D-14 | A one-sided arXiv date filter emitted a wildcard the API rejects with HTTP 500 | **DONE — `49b966a`** | `_build_query` emitted `submittedDate:[<from> TO *]` when only `arxiv_date_from` was set. arXiv answers that with 500; 500 is retryable, so each harvest burned its retries and logged `truncated early -- got 0 distinct paper(s)`, which `prefetch_pdfs` reports as "0 new available" before sleeping an hour. An ordinary "papers newer than 2015" cutoff therefore disabled the downloader completely while presenting as arXiv supply exhaustion. Isolated against the live API (`TO *` → 500, `TO 209912312359` → 200). Both open ends now emit concrete bounds. The pre-existing test asserted the broken `TO *` form and passed, which is what kept it invisible. After the fix the same harvest found **596 candidates / 306 to download** where it had found 0. |
| D-13 | Dashboard consistency panel counted the wrong corpus's vectors when idle | **DONE — `4cc164f`** | Found live bringing up the Waymo dashboard. `_status_dict` passed `live.get("collection")` to `read_consistency`, but the manifest only carries `collection` once a run *starts* — so an idle dashboard fell through to `read_consistency`'s hardcoded `"papers"` default and counted the **main** corpus. Waymo's dashboard reported `vector_points: 412167` (main corpus) beside its own `sqlite_done: 17` and called it `consistent: True` — a false pass on the very OG-16/T-DOC35 "done rows, zero vectors" check the field exists to make. Now falls back to the data dir's own configured collection. `verify_numbers.py` does not cross-check `consistency` at all, which is why nothing caught it; regression tests added for both the idle and running cases. |
| A-1 | Author-org tagging | **DONE — shipped on `origin/main` 2026-08-05, retroactively documented here** | Landed with zero backlog/tracking entry until now. Two-step extraction+matching pipeline (`rag/author_org_tagger.py`) identifying which papers were actually written by a known org's own team (currently: Waymo). See `docs/PROJECT-STATUS.md` §3 for the full writeup. |
| T-ORG3 | Curated tier — an authoritative "papers Waymo actually wrote" signal, alongside the heuristic | **DONE — `0498e82`** | T-ORG1's heuristic (precision 0.706, recall 0.783 at the corrected 138-id ground truth — see T-ORG2's row above, and its own numbers there are now stale relative to `docs/eval-reports/2026-08-07-affiliation-retrieval-first-batch.md`'s 2026-08-08 addendum) is fine for open-ended discovery, but the operator's real use case — understanding Waymo's technical stack from Waymo's own papers — needs zero false positives, and a keyword matcher can never get there against "1st Place Solution for Waymo Open Dataset Challenge"-style papers. `fixtures/waymo/waymo_authored_ids.txt` (138 ids, Waymo's own two research-index pages) already gives 0 FP / 0 FN by construction; this wires it in as a third `AuthorOrgMatch.method` value, `"curated"` (`contracts/author_orgs.py`), instead of tuning the matcher. `AuthorOrgTag.curated_ids_path` (optional, resolved relative to the repo root, `None` by default — no behavior change for an org that doesn't opt in) points Waymo's `KNOWN_ORGS` entry at that file; `rag/author_org_tagger.py::curated_orgs_for(paper_id)` is a pure id lookup against it (no affiliation text involved at all), reading the file once per run and caching it (not once per paper — ingest calls this 1,741 times). `rag/orchestrator.py::_finish` merges `curated_orgs_for()` with the existing heuristic, `curated` winning ties by org name. `contracts/vector_index.py` adds `SearchFilters.author_org_curated_only` (only takes effect combined with `author_org`) and `VectorPayload.curated_author_orgs` (the `method=="curated"` subset) so "papers Waymo actually wrote" is queryable, not just stored; `rag/vector_index.py`/`rag/fakes/fake_vector_store.py` filter on the right key identically. `rag/mcp_server.py` docstrings state plainly that `curated` is exact and the heuristic tiers are ~0.71 precision. No migration — `author_orgs` was already a JSON TEXT column (`migrations/0005_author_orgs.sql`); `"curated"` is a `Literal`-only change, confirmed by a round-trip test rather than assumed. Sanity-checked read-only against the live fixture: all 138 curated ids resolve, and the real challenge-paper false positive `2006.15505` gets no curated match. |

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
  EV=$(mktemp) && printf '{"pull_request":{"number":0,"labels":[],"base":{"sha":"%s"},"head":{"sha":"%s"}}}' \
    "$(git merge-base origin/main HEAD)" "$(git rev-parse HEAD)" > "$EV"
  GITHUB_EVENT_NAME=pull_request GITHUB_EVENT_PATH="$EV" python -m ci.run_enforcement
  ```

  **`number` and `labels` go INSIDE `pull_request`, not at the top level** — corrected 2026-08-01
  after the top-level form raised `KeyError: 'labels'`. The reader is
  `ci/run_enforcement.py::_pr_labels` (**not** `changed_files.py::compute_diff_base`, which reads
  only the `base`/`head` SHAs). `labels` is read without `.get`, so a missing key raises;
  `number` is optional and falls back to cached-payload mode.
- A PR is not done until `gh pr checks <n>` shows **both** `enforcement` and `unit-tests` as `pass`.
  Never add a label or weaken a test to make a check go green.
