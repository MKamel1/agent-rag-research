# Backlog — open work queue

Working queue for `research-system-rag`. Close an item by deleting its row and recording the
outcome in the relevant design/closeout doc — this file tracks what is *open*, not what happened.

Status: **OPEN** (not started) · **IN PROGRESS** (branch/PR exists) · **BLOCKED** (needs a decision)
· **READY** (green PR awaiting operator merge).

---

## Code-grounded review programme (RI-19+, 2026-08-22) — COMPLETE

A second review campaign, run after the first was found to have anchored on documentation rather
than source. The rule this time: a finding whose evidence is a docstring, comment, or `.md` file is
not a finding. Five reviewers, one per code area, read-only, each required to cite `file:line`, the
caller path found by grep, a concrete trigger, and a falsification attempt.

The change in method paid for itself. The first campaign's FD-1 read a docstring, reported "figure
images go to a temp directory", and missed that figures were never persisted at all — no table,
`figures=[]` hard-coded on read. And the single most valuable finding below was found by querying
GitHub Actions, which no amount of source reading would have surfaced.

| id | item | status | notes |
|---|---|---|---|
| RI-19 | `restart_downloader` SIGKILLs another corpus's downloader | **DONE** -- `bc147bc` | A bare callable reference, called zero-arg, defaulted `data_dir=None` and skipped RI-8's qualification. |
| RI-20 | Unlocked `reconcile()` can orphan a live run | **DONE** -- `def1cdc` | Compare-and-swap at the write site; the lock's poll latency was rejected. |
| RI-21 | Eight temp-write sites, four not pid-qualified | **DONE** -- `fccc316` | One shared helper, modelled on RI-6's `_write_private_file`. |
| RI-22 | Sharded Pass 1 can double-assign papers | **DONE** -- `4991a72` | Positional slicing over independently-harvested lists; hash-partition on `paper_id`. |
| RI-23 | The enforcement gate is RED on `main` | **DONE** -- `4511f74` | Two merges failing a required check. See below. |
| RI-24 | `migrate()` races on first init | **DONE** -- `1967ef4` | Reproduced with 4 threads. RI-5 widened this. See below. |
| RI-25 | Injected process-scan callables have no mechanical guard | **DONE** -- `5f98144` | RI-19's fix is correct but nothing stops the next injection site repeating it. |
| RI-26 | `search_papers` silently drops `min_distinct_papers` | **DONE** -- `86f36b3` | Honor it, reusing `_top_up_distinct_papers`. Resolved: it IS meaningful there. |
| RI-31 | One decode-or-classify helper for four adapter seams | **DONE** -- `889cfae` | `rag/decode_classify.decode_or_classify` covers the two remaining seams (summarizer ×2 methods, contextual_header). Design call: transient degrades to skip-chunk at `reembed_experiment` (spike script, no retry loop by design); reranker/embedder keep their inline RI-28/29 mapping. |
| RI-27 | Six further LOW/MED findings | **DONE** -- `5f98144` | Reranker 413 on a huge query; wrong log path behind a displayed verdict; filtered-target reconciliation; error-taxonomy escape; broken-config connection drop. |

### RI-23 — the required `enforcement` check has been failing on `main`

**This was missed because "CI checks pass" was claimed on the wrong evidence.** Running
`pytest ci/checks/` exercises the checks' own unit tests; it does not run the checks against a
diff, which is what the enforcement job does. Nothing ran the real gate locally, and the actual
run results were never read after pushing.

Live: run `32591144469` (the RI-18 merge) failed with 6 `[a]` violations — `httpx.MockTransport`
test fixtures in `app/test_assembly.py`, a file never added to that rule's allow-list. Run
`32579939693` (the RI-M3/M7 merge) failed with 2 `[f]` violations — `_FixedVectorEmbedder` and
`_IdentityReranker`, pure in-memory doubles caught by a class-name-suffix heuristic meant for real
GPU adapters. Both are the check being wrong, not the code.

Three further tripwires will fire on the next unrelated diff that touches their file:
`contracts/_base.py` has no sibling test (check g); `app/mcp_verify_client.py`'s
`env=dict(os.environ)` passes the environment through to a child rather than reading config from it
(check d); `contracts/config.py`'s module docstring contains the literal `os.getenv` and check (d)
scans prose.

The durable fix is the fourth part: a way to run the real checks against a diff locally, reusing
`ci/run_enforcement.py`'s composition rather than duplicating it.

### RI-24 — `migrate()` is not concurrency-safe on a brand-new database

Reproduced: 4 threads calling `migrate()` on one fresh path — the winner completes, the losers die
with `OperationalError('duplicate column name: doc_type')` inside 0004's `executescript`. The
T-DOC81 transaction wrapper does its job (losers roll back and stay unrecorded), but the exception
still propagates out of `__init__` and kills the caller's startup.

**RI-5 made this more likely**: it added `SqliteIngestState.__init__` as a second unconditional
`migrate()` caller alongside `DocumentStore.__init__`. The realistic shape is starting the
dashboard or MCP server while an ingest bootstraps a brand-new corpus directory.

Fix reuses a pattern already in this repo: `rag/vector_index.py` handles the identical
concurrent-creator race by catching the already-exists error and re-checking whether the artifact
is now present.

---

## Review implementation programme (RI series, 2026-08-22) — COMPLETE

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

| GT-WMR | Waymo-priority ≥95% benchmark: protocol frozen, GT built, baseline measured | **BASELINE MEASURED** -- see `docs/eval-reports/2026-08-23-waymo-priority-baseline.md` | Protocol `4e14d7b`; GT-WMR fixture + invariants; verified-set v2 (84 items, dedup); RI-32 full backfill complete and corpus verified byte-identical. Gates A-D results in the baseline report; any gate miss becomes ranked work judged against those frozen numbers. |

| MCP-E1 | Find-similar papers over MCP ("more like this paper": embed summary, nearest neighbours) | **OPEN** | Deferred from the 2026-08-23 MCP capability review (rank 3). Exa-style find-similar; cheap with the existing embedder; high literature-discovery value. |
| MCP-E2 | Citation-graph traversal over MCP (what does X build on / who builds on it) | **OPEN -- feasibility check first** | Deferred (rank 4). GROBID resolved references at parse time -- first verify what references data the store actually holds; OpenEvidence-style differentiator if present. |
| MCP-E3 | Token-lean search mode (snippet + highlighted span by default; full text via get_span) | **OPEN** | Deferred (rank 5). Aligns with best practice (Apple RAG MCP's token economy); GroundedResult currently carries full chunk text every call. |
| MCP-E4 | Method taxonomy table + argument layer (per-method rationale & pro/anti quotes with anchors) | **OPEN -- T-F7 gated** | Deferred (rank 7 = plan options D+E). New migration + contracts shapes; eval set (rationale/stance items) must be frozen first per the review plan; V0 boundary: anchored quotes, never verdicts. |
| MCP-E5 | Abstention / relevance floor | **OPEN -- blocked on RI-M7** | Deferred (rank 8). 2026-08-23 baseline reconfirmed answerable/absent score distributions do not separate on both fixtures; any threshold is a guess. Revisit only with a mechanism that separates them. |
| RI-M7 | Score-distribution census | G | **DONE** -- `033565b`, `19afe05` | Settles whether a relevance floor is choosable. Verdict carries its own upper-bound caveat. |
| RI-17 | Prefetch logs carry no timestamps | - | **DONE** -- `adc101e` | Starts the clock; the existing archive stays unmeasurable. |

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

### RI-31 — one decode-or-classify helper for the four adapter seams

Filed 2026-08-22 from RI-29's investigation, which was asked to report rather than fix.

Four sites parse a response body without guarding the decode. RI-28 and RI-29 fixed two
(`rag/reranker.py`, `rag/embedder.py`) with a settled rationale: won't-decode-at-all is transient
(the service returned 2xx, so most plausibly transit corruption); decodes-but-wrong-shape stays
permanent (deterministic for that request). Two remain: `rag/contextual_header.py` (~:150) and
`rag/summarizer.py` (~:241, ~:289).

**RI-29's read, which changes the shape of this ticket:**

- `contextual_header` is the **same defect** — its sole caller catches only `PermanentError`, so a
  raw decode escape aborts an entire re-embed run before any upsert.
- `summarizer` is **masked, not handled** — a caller wraps it in a broad log-and-continue that
  RI-29 characterised as "experiment-script posture, not a designed absorption".

**Two constraints for whoever takes this:**

1. The shared piece must be **decode-or-classify** (raise the taxonomy error), **not
   decode-or-retry**. The summarizer and contextual-header have no internal retry loop *by design*
   — they raise classified errors and the caller owns retry policy. For the summarizer a
   `TransientError` then flows into the orchestrator's existing retry-then-quarantine for free.
2. **A real design question, not mechanical porting:** `contextual_header`'s only caller handles
   `PermanentError` (skip-chunk) but not `TransientError`. This ticket must decide whether transient
   gets retry semantics there or also maps to skip-chunk. Do not let a helper smuggle that decision
   in implicitly.

Also worth settling here: the summarizer draws its wrong-shape line (`KeyError`) in a *second* try
block after the HTTP one, which sits awkwardly against the classify-at-one-seam principle the other
two now follow.

**Operator decisions outstanding** (not agent work) -- see the plan's final section. The
time-sensitive one is **FD-1**: figure images from the 12,390-paper parse went to an OS temp
directory and are gone; redirecting `output_dir` to persistent storage is cheap *before* the next
large Waymo parse and a full re-parse after it.
**Update 2026-11-10:** resolved for new parses by `f92bd8f` (RI-18 persists figures and tables); not backfilled on the main corpus.

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
| B-4 | Remove the unused outline splitter | **OPEN** | Review date 2026-08-29. Operator: "merge now, remove later if still unused in a month." The review date 2026-08-29 has passed (checked 2026-11-10); operator: remove or extend. |
| B-5 | Flip `reindex_idf` default to `--use-clone-swap` | **OPEN** | Non-destructive migration path exists (PR #203); the default is still the destructive one. Moot for the IDF modifier: it is applied on all five collections (on-disk collection configs, checked 2026-11-10); the destructive default of `reindex_idf` remains but is a no-op everywhere. |

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

## Landed: NB-C1 refusal-affordance detector falsification (2026-08-25)

A-series C1 stage 1 (mandate: A-1 abstention design doc §C1), branch `NB-C1-refusal-detector`.
One frozen blind classification rule committed before any classification
(`app/exp_nb_c1_refusal_classifier.py` v1.0); applied mechanically to the ver84 affordance-arm
captures and to one fresh gt_wmr capture (82 items, 0 errors, GPU-lock serialized). **verdict:
DROPPED** — ver84 fails both halves of the pre-committed criterion (10/16 absent covered, bar ≥12;
7/68 false refusals, bar ≤5) while gt_wmr passes clean (11/12, 0/70); the criterion is disjunctive.
What died: mechanical extractability of the refusal signal by a fixed lead-region rule — not the
generation-layer behavioural separation itself. Successor reading recorded in the report
(`docs/eval-reports/2026-08-25-nb-c1-refusal-detector.md`): the affordable generation-layer
abstention win remains A-1 §3's unconditional-affordance fallback; C1 stages and detector-family
attempts are closed.

## Landed: next-build programme Wave 0–2 (2026-08-25)

All lanes verified by the orchestrator before merge; full ledger with SHAs:
`docs/PROJECT-STATUS.md` "Next-build programme" section. Summary: C1 closed already-satisfied;
D1 pool-depth, D2 block-adjacency, D3 abstention census (no separation found), D4 dual-fixture
runner — merged; R0 fix ranking reviewed+revised — merged; A-1 abstention signal-source design doc
— merged; X-F fusion shape (eviction gone at production depth) and X-P deep-pool tables (depth =
serving win, ordering hazard; X-O unblocked) — merged. In flight at write time: X-O ordering
quality, NB-6 VLM scoping (Decision C gate). Decisions A–D recorded in PROJECT-STATUS.

## NB-JUDGE-CTX — judge prompts are silently truncated at num_ctx; amended rubric undelivered on 46/84 items

**RESOLVED 2026-08-25** by NB-NUMCTX (branch `NB-NUMCTX-fix`, commits through `96dc650`): window
raised to the served model artifact's declared 40,960 (after the interim 16384 was itself caught
truncating Q-WAYB-010, true count 17,452 tok), loud pre-send estimate-vs-window guard +
per-call `prompt_eval_count` delivery telemetry added in `app/judge_llm.py` (the one choke point;
`rag/contextual_header.py` deliberately untouched — its input is chunker-bounded), stale
"max 228 words" comment corrected. Clean-delivery re-run delivered and verified 84/84; report:
`docs/eval-reports/2026-08-25-nb-numctx-clean-delivery.md`. Outcome adverse: amended-rubric
unsupported rates collapsed vs both priors and F-A2 surfaced neither target item on its clean
tests — follow-up (seeded/repeated judge sampling) noted there, not ticketed here.

Original finding, kept for the record:

**Found 2026-08-25 closing NB-JUDGE-RERUN** (`docs/eval-reports/2026-08-25-nb-judge-rerun.md` §3;
probe + per-item census committed beside it).

`app/judge_llm.py` requests `num_ctx=8192`. Measured against Ollama v0.31.2 / `qwen3-14b-16k`: the
window is honored as capacity (≤8,192 true tokens evaluate whole), but past it Ollama **silently
keeps only the final 4,098 tokens** of the prompt — no error, no metadata flag. `_JUDGE_PROMPT`
puts the rubric FIRST, so every oversized item was judged with zero rubric text delivered. The
fabrication re-run's real prompts run 15–53K chars (k=5 full retrieved passages from the captured
generation run — not the short GT-fixture excerpts behind `judge_llm.py`'s stale "max 228 words"
comment): **46/84 items truncated**, including Q-GTA-040 — one of the two items F-A2 was amended to
catch. Consequence: no fabrication-audit number under the amended signed rubric exists yet.

### Proposed fix

1. Per-item context sizing (mirror `rag/summarizer.py`'s estimate-and-clamp pattern) or raise
   `_NUM_CTX` toward the Modelfile's own `num_ctx 16384` default.
2. Add a loud estimated-tokens-vs-window assertion (fail or log a measured warning per item) so
   silent truncation can never again masquerade as a completed judgment.
3. Correct `app/judge_llm.py`'s safety comment — its 228-word measurement does not transfer from
   GT-fixture excerpts to generation-run passages.
4. Re-run both arms under the fixed harness; only then amend the NON-COMPARABLE-BY-DELIVERY
   headline in `2026-08-25-nb-judge-rerun.md`.

### Severity

High for any judge-side measurement: the failure mode is invisible in artifacts (parseable JSON,
valid verdict literals, plausible rates) and silently converts a signed instrument into
instructions-only judging.

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

## Landed: Precision-95 lane outcomes (2026-08-28)

GPU freeze lifted 2026-08-27; lanes dispatched immediately. Primary work landed 2026-08-28.

| id | item | status | notes |
|---|---|---|---|
| QW-2 | MiniCheck-FT5 confidence surface v0 | **LANDED** | Support score separates answerable/absent ~500× wider than retrieval score, but heavy overlap blocks thresholding. Viable as one candidate signal for IN-2, not alone; sentence-level scoring recommended over per-answer means. Branch `NB-QW2-confidence-v0`, merge `fd05dbf`; report `docs/eval-reports/2026-08-28-confidence-v0.md` |
| QW-3 | Qwen3-Reranker-0.6B seat A/B | **VERDICT: REJECT** | Block-P@1 collapses 24× (gt_wmr) and 11× (ver84); ver84 falls below no-rerank floor. All three hypotheses tested before measurement trusted. Not attempted: 4B/8B variants, tuned task instruction, PyLate/GTE-ModernColBERT. Branch `P95-QW3-reranker-seat`, merge `825c57b`; report `docs/eval-reports/2026-08-28-qw3-reranker-seat.md` |
| W-A4 | SB-2 partial-absent ground truth authoring | **LANDED** | 31 usable items across 22 papers. Two blind authors + cross-verification (Stages B/C/D). Falsified 2 absence claims via lexical re-probe; corrected 3 hit-count stale entries. Incidental finding: 12/12 Author B citations sat 1–5 blocks downstream of anchor — supports X-C Variant A. Branches `P95-SB2-WA4-authorA` (7191f8e), `P95-SB2-WA4-authorB` (336d78c), `P95-SB2-WA4-crossverify` (259b007); data `docs/eval-reports/data/2026-08-28-wa4-gt/`; report `docs/eval-reports/data/2026-08-28-wa4-gt/crossverify/cross-verification-report.md` |
| SB-1 | Chunk-boundary impact measurement | **REJECT (both arms) — `7b679f7`** | Report `docs/eval-reports/2026-08-28-sb1-chunk-boundary.md`: neighbour smoothing a flat null, section-context embedding trades fixtures with zero boundary-class conversions. Measurement instrument finding kept: **ver84 MRR noise floor ~0.0074** (one tied-pair flip = 0.5/68 MRR gap). R@10 and block-P@1 are stable metrics on this corpus. |
| SB-3 | Agentic loop prototype v0 | **LANDED** | Arm (a) CRAG-style evaluator ADOPT-as-candidate (not wired), arm (b) decomposition REJECT. Commits `8d7c478`..`901a108`; report `docs/eval-reports/2026-08-28-sb3-agentic-loop.md`. |
| P0-2 | Metric-ratification sign-off | **BLOCKED** — on operator | `docs/eval-reports/2026-08-26-precision95-metric-ratification.md` remains unsigned DRAFT. Gates IN-1. Still pending 2026-11-10. |
| T-F7 | X-C member-block citation adoption sign-off | **BLOCKED** — on operator | Batched rider PR for Variant A wiring. Measured effect: gt_wmr 93.9%→95.5%, monotone, zero-risk. Supported by SB-2/W-A4's 12/12 anchor-offset finding. Design note `docs/design-notes/2026-08-28-xc-member-citation-adoption.md`. Still pending 2026-11-10. |

## Enhancement programme (2026-11-10)

Plan: `docs/superpowers/plans/2026-11-10-enhancement-programme.md` (instruments first, GPU measurements second, gated changes last). After the operator-approved minimizer verdicts (`docs/eval-reports/2026-11-10-ticket-set-minimizer.md`, applied by EP-2b) the set is 22 ACTIVE tickets and 21 PARKED tickets (51 originally: 7 merged away, 2 cut, EV-6b added); one issue file each in `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/` (parked ones in `parked/`), list in `INDEX.md`, not yet posted to GitHub. Source: `docs/eval-reports/2026-11-10-system-review.md`. Every ticket edits this file and PROJECT-STATUS.md in its own PR (AGENT-PROCEDURES section B); there are no batch tickets. Status BLOCKED means an operator answer (F1-F8) or an upstream gate, named in the notes. PARKED means do not start: the trigger is a checkable condition on a baseline result or a named decision.

| id | item | status | notes |
|---|---|---|---|
| EP-0 | Programme branch; three ground-truth sets (standards 128 items, causal books 74, paper passages 61); chunk-quality census; corpus audits (off-topic, ligature, embed truncation) | **DONE — `0021de1`** | commits `173fe4e` (standards GT), `f119f30` (books GT), `0c9483e` (papers GT), `09cb847` (audits), `368ce55` (census), `17b48ec`, `0021de1` |
| EV-1 | Topic labels for all 12,385 main-corpus papers | **DONE — `5f54fb4`** | `docs/eval-reports/data/2026-11-10-topic-labels/` |
| EV-2 | Label audit (weighted kappa 0.90, same model family as the labeller) | **DONE — `eb4d993`** | `docs/eval-reports/2026-11-10-topic-labels-audit.md` |
| EV-3 | relevance_score against labels (AUROC 0.923) | **DONE — `eb4d993`** | same merge as EV-2; report above |
| EV-5 | Three frozen protocols, run scripts that verify fixture hashes, fixture hashes, GPU-day runbook | **DONE — `b9be4c8`** | `docs/eval-reports/2026-11-10-*-benchmark-protocol.md`, `2026-11-10-GPU-DAY-RUNBOOK.md`, `data/2026-11-10-FIXTURE-HASHES.json` |
| EV-6 | Per-stratum evaluation report script | **DONE — `c06b411`** | `scripts/eval_strata_report.py` |
| CQ-1 | Ligature repair in the sparse arm (merged, applied to no index) | **DONE — `56d24d0`** | `docs/eval-reports/data/2026-11-10-ligature-census/repair-map-report.md` |
| CQ-2 | `VectorIndex.resparse` / `set_payload` and their CLIs | **DONE — `655b384`** | `docs/eval-reports/2026-11-10-cq2-index-maintenance.md` |
| CQ-3 | Stub filter (default off) and pre-registered A/B | **DONE — `720f77d`** | `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`; A/B (EV-21) KILLED 2026-11-11 before any arm ran (stub-at-rank-1 max 1; ceiling 0); filter stays default off; `docs/eval-reports/2026-11-11-stub-filter-result.md` |
| CQ-6 | Duplicate-document and reference-list census | **DONE — `23fc2d2`** | `docs/eval-reports/data/2026-11-10-dup-ref-census/` |
| CQ-4 | Truncation re-chunk plan: about 177k-212k embeddings, 48 ground-truth items to re-ground; names a server token-limit change as the unassessed alternative | **DONE — `bb6520a`** | `docs/eval-reports/data/2026-11-10-truncation-rechunk/report.md` |
| CQ-5 | Standards metadata: reviewed table, validator/tag emitter, acquisitions list; specifies the authority/edition follow-up authoring (CQ-19, CQ-20) | **DONE — `3df5c8b`** | `docs/eval-reports/2026-11-10-cq5-standards-metadata.md` |
| EP-1 | Documentation drift pass over PROJECT-STATUS, README, AGENTS, RUNBOOK | **DONE — `dc70a73`** | commits `2f25a68`..`dc70a73` on the integration branch |
| OP-1 | `doctor --cpu-only` and fail-fast degraded mode | **DONE — `564582a`** | `app/doctor.py` |
| RV-1..RV-6 | Six review lanes | **DONE — `b4c2b43`, `e796cc9`** | `docs/eval-reports/data/2026-11-10-system-review/` |
| RV-S | Adjudicated system review (the primary input of this plan) | **DONE — `364aa13`** | `docs/eval-reports/2026-11-10-system-review.md` |
| EV-4 | Topic-focus ground truth | **DONE — `cf65a32`** | merged; superseded in content by EV-4b (`5973770`); retrieval baseline in `docs/eval-reports/2026-11-11-topic-focus-baseline.md`; earlier notes: branch `EP-EV4-focus-gt`; independent cross-verification found 18 of 26 collision questions did not contain their collision term and 6 of 10 absent items weak; repaired by EV-4b. Anything that depends on the focus set's frozen hash depends on EV-4b, not EV-4 |
| EV-4b | Repair the topic-focus ground truth (collision questions, weak absent items) and re-freeze its hash | **DONE — `5973770`** | focus ground truth repaired; hash frozen by EV-11 (`626fac3`); 49 items after the EV-11 re-check; earlier notes: branch `EP-EV4b-focus-fixes`; gates EV-17 (focus hash) and shares the hash file with EV-11 |
| EP-2 | Enhancement programme plan, issue files, BACKLOG section | **DONE — `9550d80`** | merged into the integration branch; earlier notes: branch `EP-EP2-ticket-set` |
| EP-2b | Apply the operator-approved minimizer verdicts to the ticket set | **DONE — `ff9e693`** | merged into the integration branch; earlier notes: branch `EP-EP2b-apply-minimizer`; this section, the plan and the issue files as rebuilt |
| OP-4 | Take and verify a fresh main-corpus snapshot | **DONE — 2026-11-10** | SQLite snapshot `backups/papers.db.snapshot-20261110` with `.sha256` (re-verified 2026-11-11: `sha256sum -c` OK) and a Qdrant storage copy `backups/qdrant-storage-20261110` (five production collections, 7.2 GB, taken with the container stopped; the ~24 GB of experiment collections are not included; its README states verify and restore). Marked done on the orchestrator's instruction; off-device copy and deletions remain F1 and are not done. The earlier row text said "not DONE" until the vector-store copy existed; it exists; was: W1; S-01; executed by the orchestrator now, outside the queue; consistent SQLite backup of the main corpus into its `backups/` directory with integrity check, row-count comparison and SHA-256; **the vector store's on-disk data was NOT copied** (service stopped, about 31 GB, operator decision pending), so this is not DONE; F1 blocks only the off-device copy and deletions; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-4-take-verify-main-snapshot.md` |
| OP-3 | Add integrity check and checksums to snapshot manifests | **DONE — `3c257c4`** | merged with OP-5 and OP-6 (commits `1d4aa02`, `b7a17ec`, `5a86e45`); earlier notes: W1; S-01; needs none; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-3-snapshot-integrity-and-checksums.md` |
| OP-6 | Guard every corpus tool against a missing or mismatched database | **DONE — `3c257c4`** | merged with OP-3 and OP-5 (commit `799a199`, `1d4aa02`); earlier notes: W1; S-07; needs OP-3; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-6-wrong-corpus-guards.md` |
| OP-5 | Name the GPU lock holder and list foreign GPU processes in doctor | **DONE — `3c257c4`** | merged with OP-3 and OP-6 (commit `799a199`; gpu-lock holder record, doctor GPU-contention check); earlier notes: W1; S-06; needs OP-6; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-5-gpu-lock-holder-and-fast-fail.md` |
| OP-7 | Track the four container definitions in ops/docker-compose.yml | **DONE — `066185b`** | merged with EP-6 (commit `9babfbc`); earlier notes: W1; S-12; needs OP-5; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/OP-7-tracked-container-definitions.md` |
| EP-6 | Add CORPORA.md and fix drift rows outside EP-1's files | **DONE — `066185b`** | merged with OP-7 (commit `d75ceb9`, `docs/CORPORA.md`); earlier notes: W1; S-13; needs none; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EP-6-docs-corpora-and-drift-remainder.md` |
| MC-1 | Raise an error for an unknown paper_id filter instead of returning empty | **DONE — `8c657a0`** | merged with MC-2 and MC-3 (commit `3949ed4`); earlier notes: W1; S-08; needs none; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-1-unknown-paper-id-raises.md` |
| MC-2 | Make the MCP server describe its corpus, filters and limits | **DONE — `8c657a0`** | merged with MC-1 and MC-3 (commit `19b5f64`); earlier notes: W1; S-10; needs MC-1; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-2-self-describing-mcp-server.md` |
| MC-3 | Record arguments and errors for scan and get tools in the usage log | **DONE — `8c657a0`** | merged with MC-1 and MC-2 (commit `1ee26e7`); earlier notes: W1; S-11; needs MC-2; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/MC-3-scan-tool-telemetry.md` |
| EV-14 | Measure filtered-search overlap with exact search on the live collection (read-only) | **DONE — 2026-11-11: CQ-9 TRIGGER MET (F1 0.988 < 0.99)** | measured read-only at `03cfd18`; `papers` F1 0.988, F2 0.993, F3/F4/F6 1.000; 0 short result lists, so the kill clause "no query returned fewer than k hits" is also literally met (rule conflict, not resolved; CQ-9 not started); report `docs/eval-reports/2026-11-11-filtered-search-result.md`; run `docs/eval-reports/data/2026-11-11-session2/runs/filtered-20261111T121957`; was: BLOCKED — on F2 (vector store up); earlier notes: W1; S-15; needs F2; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-14-payload-index-overlap-measurement.md` |
| EV-7 | Require --collection, stamp the fixture hash, preflight gold ids | **DONE — `f0643c9`** | merged with EV-8 to EV-10 (commits `083c696`, `a24261a`); earlier notes: W1; S-02; needs none; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-7-eval-entrypoints-explicit-collection.md` |
| EV-8 | Add an excerpt-containment passage metric that honours alternative gold chunks | **DONE — `f0643c9`** | commits `2e61427`, `70f4139`; earlier notes: W1; S-03; needs EV-7; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-8-passage-excerpt-hit-metric.md` |
| EV-9 | Record retrieved chunk ids in eval rows | **DONE — `f0643c9`** | commit `0b46386`; earlier notes: W1; S-05; needs EV-8; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-9-chunk-ids-in-eval-rows.md` |
| EV-10 | Mark an eval run invalid when any error is a GPU lock timeout | **DONE — `f0643c9`** | commits `db3fc5e`, `7c5b45d`; earlier notes: W1; S-06; needs EV-9; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-10-invalid-run-on-lock-timeout.md` |
| EV-11 | Record note-only duplicates as alternatives and re-freeze fixture hashes | **DONE — `626fac3`** | three alternatives recorded, focus set re-checked and frozen, hashes re-frozen (commits `82bffac`, `b4f5a09`, `7830ce5`); dated addenda in the three protocols; earlier notes: W1; S-03; needs EV-8, EV-4b; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-11-record-alternatives-refreeze-hashes.md` |
| EV-15 | Add the plain BM25 floor script named EV-5b in the protocols | **DONE — `84261a2`** | `scripts/bm25_floor.py`; report `docs/eval-reports/2026-11-10-bm25-floor.md`; earlier notes: W1; S-02; needs none; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-15-bm25-floor-script.md` |
| EV-6b | Dry-run and independently review the strata report script before the first baseline | **OPEN** | W1; review section 2 ('EV-6 not reviewed by any lane'); needs EV-9; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-6b-review-strata-report-script.md` |
| EV-16 | Run the frozen main-corpus baselines (papers, books, legacy) | **DONE — 2026-11-11 (run at `626fac3`)** | main-corpus baseline measured; report `docs/eval-reports/2026-11-11-main-corpus-baseline.md`; run `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/20261111T004734` (untracked); unblocks EV-17 and EV-18 ordering only; earlier notes: W2; S-16; needs EV-7, EV-8, EV-9, EV-10, EV-11, EV-15, EV-6b, F3; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-16-baseline-main-corpus.md` |
| EV-17 | Run the frozen topic-focus baseline | **DONE — 2026-11-11 (run at `626fac3`)** | topic-focus baseline measured; report `docs/eval-reports/2026-11-11-topic-focus-baseline.md`; run `.../runs/20261111T012931` (untracked); earlier notes: W2; S-16; needs EV-16, EV-4b, F3; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-17-baseline-topic-focus.md` |
| EV-18 | Run the frozen standards baseline and evaluate the structure gate | **PARTLY DONE — 2026-11-11 (run at `626fac3`)** | standards baseline run and D-1 (keep 128) / S-1 (unresolved) evaluated in `docs/eval-reports/2026-11-11-standards-baseline.md`; run `.../2026-11-10-standards-gt/runs/20261111T013215` (untracked). **The structure-gate count (qualifying CQ-12 misses) has NOT been produced**, so the parked CQ-8/12/13/14/16 triggers are not evaluated; earlier notes: W2; S-16; needs EV-16, EV-9, EV-11, EV-15, F3; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-18-baseline-standards.md` |
| EV-20 | Run the depth grid (32 versus 128) on papers and books, only if headroom allows | **DONE — 2026-11-11: papers no change (G-1 not met), books G-1 met; OPEN operator decision; no default changed** | depth 128 vs 32: papers 52 -> 54 (+2, 2:0), books 54 -> 57 (+3, 4:1); both lean 128 by the >= 2 rule; report `docs/eval-reports/2026-11-11-rerank-depth-result.md`; run `docs/eval-reports/data/2026-11-11-session2/runs/depth-20261111T095413`; was: BLOCKED — scripts merged `cc1ad6c`; earlier notes: session-2 run scripts and launch sheet (commits `a45c4ff`, `b025226`) are merged and unrun. EV-16 and EV-18 baselines now exist; the 6-item headroom gate has not been evaluated here; F3 as before; was: W2; S-19; needs EV-16, EV-18, F3; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/EV-20-depth-weight-grid.md` |
| RIDER-1 | Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step) | **BLOCKED** — on EV-18 (post-baseline) and F4 | W4; review (D), RV-5 F-5.6, RV-3 F-1.11, RV-6 F-A5, RV; needs EV-11, EV-18, F4; `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/RIDER-1-foundation-signoff-rider.md` |
| CQ-19 | Author 38 more standards ground-truth items for the weak stratum (authority or edition) | **PARKED** | trigger: start only if EV-18 shows authority-stratum hit@10 clearly below the other standards strata (at least 2 of the 4 current authority items missing at hit@10 while the other strata are strong); author only the stratum that is weak (the edition half, absorbed from CQ-20, is started only if the edition stratum is the weak one). Kill: killed if no standards stratum is visibly weak in EV-18. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-19-standards-authority-items.md` |
| CQ-7 | Build a ligature-repaired clone of the main collection on CPU | **DONE — 2026-11-11 (clone built; not deleted)** | `papers__ligrepair_20261111`, 412,167 points = live, 138,484 sparse vectors changed, post-check 0/200 stale, 741 s clone + 273 s resparse; live untouched; report `docs/eval-reports/2026-11-11-ligature-repair-result.md`; run `docs/eval-reports/data/2026-11-11-session2/runs/ligclone-20261111T115922`; was: PARKED; earlier notes: trigger: start only if EV-16's per-stratum rows show damaged-gold passage hit@10 at least 10 points below clean-gold passage hit@10, or at least 5 damaged-gold misses (computable from EV-16 rows, no extra GPU); and operator answer F2 (vector store up) and OP-4 done. Kill: none listed by the minimizer; the trigger is the gate. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-7-ligature-resparse-clone-cpu.md` |
| CQ-8 | Make rechunk re-embed only chunks whose text changed | **PARKED** | trigger: start only if EV-18's structure-gate count is 5 or more (its sole consumer is CQ-16). Kill: killed if EV-18's count is below 5. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-8-rechunk-reuse-vectors-by-text-hash.md` |
| EV-12 | Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect) | **PARKED** (pre-registration merged `cc1ad6c`) | session-2 A/B pre-registration and CQ-3 stub-A/B addendum (commit `5321150`) are merged; trigger below unchanged; was: trigger: only after the decision to commission EV-21 (it is a pure prerequisite of EV-21). Kill: killed with EV-21. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-12-cq3-preregistration-addendum.md` |
| EV-13 | Capture cross-encoder scores and build the absence census tool | **PARKED** (code merged `1763006`) | tool and opt-in score capture (`--record-rerank-scores`) are merged and unrun; the PARKED trigger below is unchanged; was: trigger: only after an abstention feature is commissioned by the operator and at least 60 distinct absent items exist (the sets hold 9-24). Kill: killed if no abstention feature is commissioned. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-13-rerank-score-capture-and-census.md` |
| OP-2 | Construct the vector index lazily so the server starts without it | **PARKED** | trigger: only after the operator needs the MCP server to start with the services down. Kill: none. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/OP-2-lazy-vector-index-construction.md` |
| RQ-1 | Fix three one-line retrieval defects (payload, partial rerank, cap) | **PARKED** | trigger: only after EV-16, EV-17 and EV-18 are merged (the baseline commit is then released); it is the first post-baseline change and must be verified byte-identical against the real-index baseline rows. Kill: none; if the byte-identical check fails it is not merged. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-1-three-retrieval-one-liners.md` |
| RQ-2 | Add an opt-in, default-off relevance demotion to the Retriever | **PARKED** (code merged `03cfd18`; RQ-3 A/B run: REJECT) | the lever stays default off; RQ-3 measured 2026-11-11, all three arms REJECT, see `docs/eval-reports/2026-11-11-relevance-demotion-result.md`; was: PARKED (code merged `03cfd18`); earlier notes: opt-in demotion (`tail` / `penalty`) is in the Retriever, default off, together with RQ-3 pre-registration and run script; nothing has been run; the PARKED trigger below is unchanged; was: trigger: start only if EV-17's off-topic top-10 share exceeds the operator's F6 bar (the share and a first demotion estimate are computable offline from EV-17 rows plus `relevance_score`). Kill: killed if EV-17's share is below the bar. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-2-opt-in-relevance-demotion.md` |
| RQ-5 | Extract one shared sparse_tokens() used by the index | **PARKED** | trigger: only after the CQ-18 trigger holds (the sparse arm is shown to matter, see CQ-18). Kill: killed with CQ-18. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-5-shared-sparse-tokens.md` |
| EV-19 | Run the reranker-score census on the absent arms | **DONE — 2026-11-11: CANDIDATE (pre-registered rule)** | rerank_top1 AUROC focus 0.942, standards 0.801 pass; legacy fails the question-length control (0.874 vs 0.974); authorises only a larger pre-registered calibration study, no threshold or exposure; report `docs/eval-reports/2026-11-11-rerank-score-census-result.md`; run `docs/eval-reports/data/2026-11-11-rerank-score-census/runs/20261111T104113`; was: PARKED; earlier notes: trigger: only together with EV-13 (same condition: abstention commissioned and 60+ distinct absent items). Kill: the census closes the RQ-4 gate: RQ-4 dies if the census CI contains 0.5 on two of three sets. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-19-rerank-score-absence-census.md` |
| EV-21 | Run the amended CQ-3 stub-filter A/B | **DONE — 2026-11-11: KILLED by its own ceiling rule, no arm run** | stub-at-rank-1 max 1 answerable item per set (need 3), ceiling 0 on all three sets; `--drop-stub-chunks` stays default off; report `docs/eval-reports/2026-11-11-stub-filter-result.md`; was: PARKED (helper scripts merged `cc1ad6c`); earlier notes: offline arithmetic helper and read-only filtered-search script (commit `e057aae`) are merged; the A/B itself has not run; was: trigger: start only if baseline rows (with chunk ids) show a stub at rank 1 on at least 3 answerable items on some set; needs EV-12 and operator answer F3. Kill: killed if the stub-at-rank-1 count is below 3 on every set. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-21-stub-filter-ab.md` |
| EV-22 | Run the ligature-repair A/B on the repaired clone | **DONE — 2026-11-11: REJECT (CQ-2 clause (a) fails)** | papers `sparse_only` paper Recall@10 22 vs 22; fused papers 52/52, books 54 -> 53; standards not run; nothing reverted or adopted; report `docs/eval-reports/2026-11-11-ligature-repair-result.md`; run `docs/eval-reports/data/2026-11-11-session2/runs/ligab-20261111T122952`; also records an OPEN finding that system `sparse_only` is far below the BM25 floor; was: PARKED; earlier notes: trigger: start only if the damaged-gold stratum shows a gap (CQ-7's trigger holds and CQ-7 is done); needs F3. Kill: killed with CQ-7. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/EV-22-ligature-resparse-ab.md` |
| CQ-12 | Add golden tests and rules to the section tracker (standards) | **PARKED** | trigger: start only if EV-18's structure-attributable miss count is 5 or more. Kill: killed if the count is below 5 or standards passage hit@10 leaves under 5 items of headroom. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-12-section-tracker-rules-and-golden-tests.md` |
| CQ-13 | Add the running-furniture pre-pass (standards) | **PARKED** | trigger: start only after CQ-12 has run and its in-memory re-derive leaves furniture roots among the qualifying-miss questions. Kill: killed if zero furniture roots remain among the qualifying-miss questions. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-13-furniture-prepass-and-table-spans.md` |
| CQ-14 | Fold heading-only chunks into the next group and guard normalisation regexes | **PARKED — kill criterion as written is met (not closed here)** | EV-21 was KILLED and standards stub-at-rank-1 is 1 (< 3), so "killed if ... stub-at-rank-1 occurs on fewer than 3 answerable standards items" holds; see `docs/eval-reports/2026-11-11-stub-filter-result.md`; was: PARKED; earlier notes: trigger: only after the EV-21 verdict; the regex guard only if CQ-16 proceeds. Kill: killed if EV-21 is REJECT, or stub-at-rank-1 occurs on fewer than 3 answerable standards items, or fewer than 3 qualifying misses have a stub in the top 10. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-14-stub-folding-and-regex-guard.md` |
| CQ-16 | Rebuild the standards clone from re-derived paths and measure it against baseline (absorbs CQ-15) | **PARKED** | trigger: start only if EV-18's structure-attributable miss count is 5 or more (net +3 must be reachable); the CQ-15 half (clone rebuild) also needs F2, F3 and F7. Kill: killed if the EV-18 count is below 5 or the rebuilt clone shows fewer than 3 flipped questions; the CQ-15 half is killed if CQ-12, CQ-13 and CQ-14 are all killed, or F7 says keep stored paths and the operator will not pay the 35k re-embed. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-16-standards-rechunk-verdict.md` |
| CQ-18 | Add BM25 weighting behind a flag and run the A/B on a repaired clone (absorbs CQ-17) | **PARKED** | trigger: start only if on some set fused minus dense-only passage hit@10 is 3 items or more AND sparse-only passage hit@10 is more than 3 items from the plain-BM25 floor on that set (the sparse arm matters and is not merely BM25); needs F2 and F3, and a repaired base if EV-22 ran. Kill: killed if on every set fused minus dense-only passage hit@10 is 2 items or fewer, or sparse-only is within 3 items of the BM25 floor on every set, or EV-22 shows ligature repair itself changed the sparse arm so that attribution is muddied and no gain remains. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-18-bm25-weighting-ab.md` |
| CQ-9 | Add idempotent payload indexes and verify them on a clone | **PARKED — trigger MET by EV-14 (F1 0.988), not started** | trigger text is met on `papers` F1 only; the kill clause "no query returned fewer than k hits" is also literally met (0 short lists); the operator has not decided between them; see `docs/eval-reports/2026-11-11-filtered-search-result.md` section 4; was: PARKED; earlier notes: trigger: start only if EV-14 reports overlap below 0.99 on at least one of the three filters. Kill: killed if EV-14 overlap is at least 0.99 on all three filters, or no baseline query returned fewer than k hits. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/CQ-9-payload-indexes-on-clone.md` |
| MC-4 | Slim the MCP wire by projecting duplicated envelope fields away | **PARKED** | trigger: start only if F5 = yes AND MC-3 telemetry shows agents lowering the default k. Kill: killed if F5 = no, or MC-3 telemetry shows default-k calls are not lowered, or a standards k=10 response (about 4.2k tokens) is acceptable to the operator. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/MC-4-mcp-wire-projection.md` |
| RQ-3 | Run the relevance-demotion arms on the focus and passage sets | **DONE — 2026-11-11: REJECT (all three arms)** | baseline focus contamination 0.100; tail-0.25 0.112, tail-0.30 0.154, penalty-0.30-p5 0.112 (none <= 0.050); legit off-topic recall 14 -> 8, 8, 14; default stays off; report `docs/eval-reports/2026-11-11-relevance-demotion-result.md`; run `docs/eval-reports/data/2026-11-10-focus-gt/runs-rq3/20261111T111549`; was: PARKED; earlier notes: trigger: start only if EV-17's off-topic top-10 share exceeds the operator's F6 bar; needs RQ-2 built and F3. Kill: killed if EV-17's share is below the bar, or an offline demotion on EV-17 rows (using `relevance_score`) removes under 50% of off-topic top-10 slots or drops any gold on papers-passage or books. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-3-focus-lever-ab.md` |
| RQ-4 | Expose the cross-encoder score in result metadata | **PARKED** | EV-19 census returned CANDIDATE (not NO SIGNAL); the kill criterion "CI contains 0.5 on two of three sets" is NOT met (it contains 0.5 on none); the other gates (abstention commissioned, 60+ distinct absent items, RIDER-1) are unchanged; see `docs/eval-reports/2026-11-11-rerank-score-census-result.md`; was: PARKED; earlier notes: trigger: only after an abstention feature is commissioned, the EV-19 census gate can open (60+ distinct absent items) and RIDER-1 has landed. Kill: killed if the EV-19 census CI contains 0.5 on two of three sets. `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-4-expose-rerank-score-metadata.md` |
