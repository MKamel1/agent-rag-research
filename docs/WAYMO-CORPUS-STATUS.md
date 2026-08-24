# Waymo AV-safety corpus — status and post-mortem

*2026-08-05. What this attempt shipped, what went wrong, and the supported path to resume it — or
consciously abandon it.*

## 1. What this is

An attempt to stand up a second, isolated corpus — Waymo/autonomous-vehicle-safety arXiv papers —
alongside the existing causal-methods corpus this repo already serves, by reusing the repo's
existing multi-corpus mechanisms (`app.init_config --data-dir`, `app.ingest --paper-ids-file`, a
second dashboard instance on its own port) rather than building anything new. The plan is
`docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md`; the source list of what to harvest
is `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md`. As of today the corpus sits stalled at **17 of 1437**
target papers fully ingested, with 810 more parsed-and-chunked but not summarized/embedded/stored.

## 2. Planned vs. executed

The plan's four tasks, and what actually happened against each:

| Task | Plan | What happened |
|---|---|---|
| **1 — isolated data dir + config** | `app.init_config --data-dir`, then hand-edit exactly 3 keys: `collection`, `focus_area_queries`, `gpu_lock_path` | Done as planned, **plus two more hand-edits the plan never authorized**: `ingest_paper_ids` (populated with all 1437 target ids) and `prefetch_target` (set to `1`, down from the template's `30000`). See §5. |
| **2 — scout script** | `scripts/waymo_arxiv_scout.py`, TDD, committed | Built on the unmerged branch `worktree-waymo-corpus-expansion`, iterated 4 times (§8), never merged to this branch. |
| **3 — human review + `paper_ids.txt`** | Scout output reviewed, approved ids written to `paper_ids.txt` | Done — `candidates.json` (1444 entries) and `paper_ids.txt` (1437 entries, 7 legacy-format ids manually dropped after they caused a crash — see §4) both exist in `waymo/data/` and are preserved in `fixtures/waymo/`. |
| **4 — ingest via `app.ingest --paper-ids-file`** | One blocking `app.ingest --paper-ids-file paper_ids.txt --parse-workers 1` invocation | **Never run as planned.** Instead: a bare `app.ingest` crashed (Run 1, §3), was retried by hand twice more with different worker counts and both times killed mid-run (Runs 2–3), then a hand-rolled `waymo/data/run_batches.sh` was written and run once, itself killed partway through its first batch (Run 4). The plan's Task 4 doesn't mention `app/build_corpus.py` at all — the module that already exists in this repo specifically to supervise multi-batch, resumable ingest runs (OG-40/OG-41, `app/build_corpus.py`'s own docstring). Nobody used it. |

## 3. Run table

Reconstructed from `waymo/data/ingest_events.jsonl` (`RUN_START`/`RUN_END`/`STAGE_*` events) and the
four log files under `waymo/data/`. All times PDT, 2026-08-05.

| # | run_id | log file | started | paper_count | ended | outcome |
|---|---|---|---|---|---|---|
| 1 | `95321b6142fe` | `ingest_full_run_attempt1_crashed.log` | 20:15:31 | 1444 | 20:16:42 (`RUN_END`, 70.99s) | **Crashed**, `EXIT_CODE:1`. `n_done: 0, n_quarantined: 0`. |
| 2 | `27f44516a8cd` | `ingest_full_run_1worker_partial.log` | 20:18:02 | 1437 | last log line 20:41:29 | **Killed**, `EXIT_CODE:143` (SIGTERM). No `RUN_END` event was ever written. |
| 3 | `db1ec6430d01` | `ingest_full_run_3worker_monolithic_partial.log` | 20:41:50 | 1437 | last log line 21:14:04 | **Killed**, no exit code printed at all (the script's own trailer never ran — consistent with a signal, not a clean exit), no `RUN_END` event. |
| 4 | `a9a631a552f9` | `ingest_batched.log` (via `run_batches.sh`, batch_00.txt = 300 ids) | 21:14:22 | 300 | last log line 21:18:57 | **Stopped mid-batch.** `STAGE_END parse` logged at 21:14:42, `STAGE_START finish` logged immediately after — then the log just stops, ~4.5 min later, with no crash traceback, no `EXIT_CODE`, no `=== finished batch_00.txt ...` trailer (which `run_batches.sh` prints unconditionally after every invocation, confirming the underlying `app.ingest` process was killed before returning, not that it exited and the script logged the result). Only 4 of the 5 pre-split batch files were ever touched — `batch_01.txt`–`batch_04.txt` never started. |

No `app.ingest`, `app.parse_phase`, or `run_batches.sh` process is running now (`ps aux` confirms).
Only the second dashboard server (pid from `waymo/data/dashboard.pid`) is still alive — see §7.

## 4. Root cause of the crash (Run 1)

Run 1's traceback, in full:

```
INFO:httpx:HTTP Request: GET https://export.arxiv.org/api/query?id_list=...%2C2008.11672%2C0606226%2C2606.07016%2C1202.0582%2C9304006%2C2309.15417%2C2401.06439%2C0903.4089&max_results=50 "HTTP/1.1 400 Bad Request"
Traceback (most recent call last):
  File ".../rag/harvester.py", line 369, in _fetch_by_id_list
    response.raise_for_status()
  ...
httpx.HTTPStatusError: Client error '400 Bad Request' for url '...'
...
  File ".../rag/harvester.py", line 383, in _fetch_by_id_list
    raise PermanentError(f"ArxivSource: arXiv API returned {status}") from error
contracts.errors.PermanentError: ArxivSource: arXiv API returned 400
...
subprocess.CalledProcessError: Command '[...python, -m, app.parse_phase]' returned non-zero exit status 1.
```

**Offending ids, named directly in that request URL:** `0606226` and `9304006` — pre-2007 arXiv
identifiers with their category-archive prefix stripped (the real ids are something like
`hep-th/9304006`; arXiv's `id_list` endpoint 400s the *entire batch* of 50 ids when even one entry
in it is malformed like this, so 48 good ids failed alongside these 2). Diffing `candidates.json`
(1444 entries, scout output) against `paper_ids.txt` (1437 entries, the file actually fed to
ingest) surfaces **7** such ids total, not just the 2 caught in Run 1's specific 50-id chunk:

```
0405089  0505496  0606226  9304006  9606006  9701008  9810047
```

These 7 were manually removed from `paper_ids.txt` between Run 1 (paper_count 1444) and Run 2
(paper_count 1437) — a symptom fix (strip the ids that already broke a run) rather than a root-cause
fix (the scout script that produced them still has this defect unrepaired — see §8).

**A second finding from the same traceback, independent of the id-format bug:** every frame in
Run 1's stack trace points into `/home/omar/ai-projects/research-system-rag/.claude/worktrees/waymo-corpus-expansion/...`,
not this repo's own tree. `run_batches.sh` (§5) makes this explicit and permanent by hardcoding
`PYTHONPATH=.../.claude/worktrees/waymo-corpus-expansion`. Every ingest run in this whole episode
executed the pipeline code (`app.ingest`, `app.parse_phase`, `rag.harvester`, ...) from the
**unmerged worktree branch**, not from `main`/this branch. Data written to `waymo/data/papers.db`
and the `waymo_av_safety` Qdrant collection is real and reusable regardless (the schema is
unaffected), but any *behavior* differences between that worktree's code and this branch's code
were in effect for all four runs — worth checking before resuming, not just assuming code parity.

## 5. Where execution drifted from supported mechanisms

| ad-hoc artifact | existing mechanism it reinvents | why the existing mechanism is better |
|---|---|---|
| `waymo/data/run_batches.sh` — a hand-rolled `for f in batch_00.txt ... batch_04.txt` shell loop | `python -m app.build_corpus --target N --parse-workers N --batch-size N` (`app/build_corpus.py`) | `build_corpus` is this repo's actual supervisor for exactly this problem (OG-40/OG-41, module docstring lines 1–37): it drives `app.ingest` in a loop, tracks a `--target` done-count, detects processing stalls (`_DEFAULT_MAX_IDLE`) and supply exhaustion, and is what the *causal-inference* corpus already runs in production. It was never invoked here. |
| Static `batch_00.txt`…`batch_04.txt` — `paper_ids.txt` pre-split into 5 fixed files once, before any ingest ran | `cached_not_done()` (`app/build_corpus.py:203-211`) — recomputed **every loop iteration** from `{cache_dir}/*.pdf` minus ids already `stage='done'` minus permanently-quarantined ids, then written fresh via `_write_batch_ids()` (`app/build_corpus.py:339-343`) | The static files never shrink. Rerunning `run_batches.sh` after Run 4's partial batch would resubmit ids already at `done` (wasted re-harvest/re-parse work) and would keep resubmitting the same 7 malformed legacy ids forever, since nothing filters them out between runs — the exact failure mode Run 1 already hit once. `build_corpus`'s dynamic recomputation makes every iteration naturally exclude both categories automatically. |
| The exit-code check in `run_batches.sh`: `echo "=== finished $f at $(date), exit $?" ===` | `subprocess.run(cmd, cwd=str(data_dir), check=True)` (`app/build_corpus.py:370`) | **Confirmed by direct reproduction** (`bash -c 'set -uo pipefail; false; echo "exit $?"'` → prints `exit 0`): the `$(date)` command substitution inside the same `echo` argument runs *before* `$?` is expanded, so `$?` reports the date subshell's exit status (0), never `app.ingest`'s real one. Combined with `set -uo pipefail` and no `-e`, the loop has **no way to detect or stop on a failed batch** — it always logs "exit 0" and silently continues to the next file. `build_corpus`'s `check=True` raises `CalledProcessError` on a real nonzero exit and stops the loop immediately (`app/build_corpus.py:352-356`, by design — "matches that module's own 'let it raise' style"). |
| `run_batches.sh`'s hardcoded `PYTHONPATH=.../.claude/worktrees/waymo-corpus-expansion` | Running from this repo's own checked-out tree | Every run in this episode executed pipeline code from an unmerged worktree branch, not this branch — see §4's second finding. |

## 6. Current state (measured today, 2026-08-05)

**`waymo/data/papers.db`** (`ingest_state`, read-only query):

```
stage    count
-------  -----
chunked  810
done     17
```

827 total tracked ids (of 1437 in `paper_ids.txt`); 610 never harvested at all.

**`papers` table:** 17 rows, all `doc_type='paper'`. (The 810 `chunked`-stage papers have their
parsed/chunked artifacts held only in `ingest_state`'s checkpoint blob — `rag/orchestrator.py:456-477`
— not yet written to `papers`/`blocks`/`chunks`, which only happen at `_finish`/`put()`, i.e. once a
paper reaches `stored`/`done`. This is expected, and it's exactly what lets a resumed run skip
re-parsing them.)

**`blocks`:** 2,407 rows (17 papers). **`chunks`:** 388 rows (17 papers). **`summaries`:** 17 rows.
**`quarantine`:** 1 row —

```
2601.05653 | parsed | failed to download PDF from https://arxiv.org/pdf/2601.05653v2: Client error '404 Not Found' ...
```

Confirmed identical via the live dashboard's `/api/status` (port 8701):

```json
"funnel": {"harvested": 827, "parsed": 827, "chunked": 827,
           "summarized": 17, "embedded": 17, "stored": 17, "done": 17, "quarantined": 1}
```

**Qdrant** (`curl -s localhost:6333/collections/waymo_av_safety`, reachable): `points_count: 405`,
`status: green`, sparse IDF modifier already on (created fresh, so it got IDF at creation — same
mechanism `docs/BOOK-INTEGRATION-CLOSEOUT.md` §2 documents for the main corpus). 405 points for 17
done papers is consistent with `child_parent_expansion: true` roughly doubling stored points per
paper (parent + child chunks) plus a small remainder.

**Disk:** `waymo/data/` is 5.4G total — `pdf_cache/` 5.2G (1,062 staged PDFs), `papers.db` 178M,
`blobs/` 1.3M.

## 7. What was done right

The plan's foundation held up; only Task 4's execution went off the rails.

- **`app.init_config --data-dir`** was used correctly to bootstrap `waymo/data/config.yaml` — every
  field `app.init_config` writes (paths, defaults) matches `config.example.yaml`'s shape, resolved
  absolute under `waymo/data/`.
- **`gpu_lock_path`** correctly points at the shared repo-root `/home/omar/ai-projects/research-system-rag/.gpu.lock`
  — the same file the main corpus's `config.yaml` uses — not a separate waymo-local lock. This was
  the one deliberate piece of shared state the plan called for (Task 1 Step 2), so that this
  corpus's GPU-heavy work and the main corpus's never run concurrently, and it's set correctly.
- **A second dashboard instance is up and correctly configured.** `waymo/data/dashboard.pid` →
  `2620755`; `ps -p 2620755 -o args=` confirms:
  `python -m app.dashboard.server --data-dir /home/omar/ai-projects/research-system-rag/waymo/data --port 8701 --host 0.0.0.0`
  — exactly the plan's Task 4 Step 2 command shape, still alive and reachable at
  `http://127.0.0.1:8701/api/status`.
- **`tag_pool.json`** exists and correctly mirrors `config.yaml`'s `focus_area_queries` (`active`
  list matches the 3 planned queries verbatim, `seeded_from: "config.yaml"`).
- **`collection: waymo_av_safety`** and **`focus_area_queries`** (the plan's other two authorized
  edits) are both set correctly and match the plan's Task 1 Step 2 exactly.

## 8. The scout script

`scripts/waymo_arxiv_scout.py` lives **only** on the unmerged branch `worktree-waymo-corpus-expansion`
(`git show worktree-waymo-corpus-expansion:scripts/waymo_arxiv_scout.py`) and was **not merged** by
this documentation effort. It queries `https://export.arxiv.org/api/query` directly with
`docs/ONBOARDING_AND_ARXIV_KEYWORDS.md`'s real boolean/author query strings (deliberately bypassing
`ArxivSource._build_query`'s quote/boolean rejection — see the plan's "Why not `focus_area_queries`"
section), scores hits by keyword weight, dedups, excludes 173 already-captured ids, and writes
`candidates.json`.

**Fix history** (`git log worktree-waymo-corpus-expansion --oneline -- scripts/waymo_arxiv_scout.py`,
4 commits after the initial version):

1. `ad761b9` — "Fix arXiv scout timeouts: smaller page size + retry with backoff" — the original
   hand-rolled HTTP loop was timing out at 100-results-per-page.
2. `8f700d6` — "Give arXiv scout longer backoff on 429 rate-limits" — a real run hit HTTP 429 on
   every 1s/2s retry attempt ~9 queries deep; switched to a dedicated 10s/30s/90s curve for 429s
   and bumped the inter-request gap from 3s to 5s.
3. `4430cf5` — "Rewrite arXiv scout to reuse ArxivSource/Harvester's proven fetch and retry
   machinery instead of a hand-rolled version" — rather than tune a third bespoke retry variant,
   switched to reusing `ArxivSource._fetch_page` and `Harvester._backoff` directly (the same code
   the 30,000-paper causal-inference harvest already validated).
4. `acf97e2` — "Fix scout output field name and cross-query rate limiting" — a post-rewrite
   follow-up: `scout()` was emitting `PaperRef.paper_id` instead of the `id` field Task 3's
   `candidates.json` consumer expects, and the rate-limit sleep flag was resetting between queries
   instead of persisting across the whole run.

**Still-open bug, confirmed in the code (not just inferred):** `rag/harvester.py`'s
`ArxivSource._entry_to_ref` (line ~415) does

```python
versioned_id = raw_id.rsplit("/", 1)[-1]  # e.g. "2504.09999v2"
```

against an Atom entry id like `http://arxiv.org/abs/hep-th/9304006v1`. `rsplit("/", 1)[-1]` keeps
only the text after the *last* `/`, silently dropping the `hep-th/`-style category-archive prefix
that pre-2007 arXiv ids require — producing the bare `9304006` that then 400s the whole `id_list`
batch (§4). Because the scout's rewrite (`4430cf5`) made it reuse this exact method, **the scout
inherits this bug** and will keep emitting archive-less legacy ids for any future run against pre-
2007 papers, until this is fixed in `rag/harvester.py` itself (it's a harvester bug, not a
scout-only one — a fix there would also protect any other id-list-based fetch in this repo).

## 9. Recovery runbook

The supported path to resume — concrete steps someone could run; **none of these were executed as
part of writing this document.**

1. **Undo the two config hand-edits the plan never authorized**, in `waymo/data/config.yaml`:
   - Set `ingest_paper_ids: null` (currently populated with all 1437 ids inline — the plan's Task 4
     Step 3 says to pass the id list via `--paper-ids-file paper_ids.txt` on the command line, not
     bake it into the config).
   - Restore `prefetch_target` to a real value (currently `1`; the template default is `30000` —
     `config.example.yaml` line 104). A `1` effectively disables the PDF-prefetch downloader that
     `app.build_corpus` depends on to stay ahead of the parser (`app/build_corpus.py`'s own
     docstring, "Why this exists").
2. **Resume via the supported supervisor, not `run_batches.sh`.** From `waymo/data/`:

   ```bash
   cd /home/omar/ai-projects/research-system-rag/waymo/data
   /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.build_corpus \
     --target 827 --parse-workers 3 --batch-size 300
   ```

   `--target 827` first, because that's exactly `done (17) + chunked (810)` — the 810 stranded
   papers can reach `done` through summarize/embed/store **without re-parsing** (their parsed/
   chunked artifacts are already checkpointed, `rag/orchestrator.py:456-461`). Once that completes,
   re-run with `--target 1437` (the full `paper_ids.txt` count) to harvest and process the remaining
   ~610 never-touched ids; `build_corpus` will keep going until either the target is hit, the
   downloader reports supply exhaustion, or it stalls. Confirm `python -m app.doctor` from
   `waymo/data/` reports OK first, and run this from this repo's own checked-out code (not the
   `worktree-waymo-corpus-expansion` worktree — §4's second finding).
3. **The scout's legacy-ID bug (§8) must be worked around before any future scout re-run** adds more
   candidates: filter `candidates.json`/any new id list for ids that don't match new-style
   `YYMM.NNNNN` (e.g. `re.match(r"^\d{4}\.\d{4,5}$", id)`) before writing `--paper-ids-file`, until
   `rag/harvester.py::ArxivSource._entry_to_ref` is fixed to preserve the archive prefix for
   pre-2007 ids. The 7 ids already known to trip this (§4) are excluded from the current
   `paper_ids.txt`, so this only matters for a *future* scout run, not resuming with the existing
   list.

## 10. Reusable assets

- `fixtures/waymo/candidates.json` and `fixtures/waymo/paper_ids.txt` — the scout's full output and
  the human-approved id list, preserved and tracked in git (identical to the working copies under
  the gitignored `waymo/data/`).
- `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` — the handoff spec: arXiv search queries, category filter,
  keyword-weight table, and the 173 already-captured ids the scout excludes.
- `docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md` — the original plan this status
  report is measured against.

---

## 11. Closeout — how v2 actually resolved this (2026-08-07)

**§9's recovery runbook was followed in substance and superseded in form.** The substance held: the
partial corpus was resumed rather than rebuilt, `app.build_corpus` did the batching, and v1's two
unauthorized config edits were reverted. What changed is that the run is now driven by the
**dashboard controller** rather than a CLI invocation, because the operator wanted Pause/Resume —
and those only work for runs the controller started (a CLI run writes no `run_manifest.json`, so the
UI cannot see it). Plan Task 4's exact command was therefore issued as
`POST /api/control {"action":"start","target":825,"parse_workers":3,"batch_size":300}` instead.

**Resume, not rebuild — vindicated.** All 810 stranded papers had their Pass-1 work banked in
`ingest_state`, so the drain skipped parsing entirely (`"draining 810 stranded (Pass-1-complete)
paper(s), Pass 1 is a no-op for this batch"`). Measured throughput once warm: **~72 papers/hour**.

**The 2 pre-2015 papers** (`1009.1191`, `1203.5986`) were excluded exactly as §10 of the plan
specifies — their PDFs moved to `pdf_cache/excluded-pre2015/`, not deleted — dropping the target
from 827 to 825.

### A power outage mid-build, and what it proved

The workstation lost power at ~16:30 with Phase A at `done=103`. Nothing was lost, and the recovery
is worth recording because it validates the design:

- `pragma integrity_check` → `ok` (SQLite's WAL did its job).
- Both Qdrant collections came back `green`; the main corpus was untouched.
- Cross-store consistency held: every paper marked `done` — including the one written *seconds*
  before power was cut — had `qdrant_points == chunks + 1` (its summary vector).
- The lock files were 0-byte advisory `filelock` files, released automatically with their processes;
  no stale-lock cleanup was needed.

The build resumed from `done=103` with no manual repair. Per-phase completion markers were added to
the chainer afterwards so a future hard shutdown skips finished phases rather than restarting them,
and an adopted phase that ends *below* target is deliberately not marked complete — otherwise a
power cut could make a resume silently skip the rest of the drain.

### Three defects the v1 post-mortem could not have found

v1 never got far enough to hit these; all three were found by running v2 and are fixed with tests
(detail in `docs/PROJECT-STATUS.md` §3/§4):

1. **`49b966a`** — a one-sided `arxiv_date_from` emitted `submittedDate:[<from> TO *]`, which arXiv
   answers with HTTP 500. The operator's own 2015 cutoff was therefore **silently disabling the
   downloader**, presenting as "0 new available" supply exhaustion. This is also the true origin of
   v1's `prefetch_target: 1` symptom being so easy to rationalize: a broken downloader looks
   identical to an exhausted one.
2. **`4cc164f`** — the dashboard's consistency panel reported the *main* corpus's vector count for
   this corpus and called it consistent.
3. **`c3765c9`** — the scout's 12 tests were never collected by CI.

### Still open

- Phases B (449-PDF drop-in + the 114-id top-up) and C (broad build) had not run at the time of
  writing; the chainer advances into them when Phase A finishes naturally, and deliberately aborts
  instead of advancing if the operator presses Stop.
- `T-ORG2` — affiliation retrieval measured at precision 0.000 and blocking `T-ORG1`
  (`docs/eval-reports/2026-08-07-affiliation-retrieval-first-batch.md`). It does not affect this
  build, which never calls the tagger.

---

## 12. Current state — 2026-08-18

*Re-measured today against the live DB, Qdrant, and Waymo's two index pages. §1's "17 of 1437" and
§6's tables are the v1 snapshot and are **long superseded** — read this section instead.*

The v2 chainer ran to completion on 2026-08-08 (`chain.log`: `### ALL PHASES COMPLETE (done=1726)`).
Phases B and C, listed as "still open" in §11, both finished. Nothing has run since; the corpus was
idle for 10 days until today.

| metric | value |
|---|---|
| `ingest_state` | **1,745 done**, 2 chunked, 1 quarantined |
| `papers` | 1,745 (1,490 arXiv + 255 `local:` drop-in) |
| `chunks` / `blocks` | 46,215 / — |
| Qdrant `waymo_av_safety` | **48,024 points**, status green |
| `app.corpus_integrity` | **OK** — every `done` paper has ≥1 chunk and ≥1 block |
| `app.doctor` | **OK** — all services healthy (had to be started; all 6 containers were down) |
| repo test suite | **1,755 tests, all pass** (`pytest` exit 0) |

### Waymo-authorship was unqueryable until today

`papers.author_orgs` and `papers.raw_affiliations` were **NULL for all 1,741 rows**, and no Qdrant
point carried the `author_orgs`/`curated_author_orgs` payload keys. The corpus held every Waymo
paper but could not answer *"is this a Waymo paper?"* at all — `SearchFilters.author_org` and
`author_org_curated_only` (`rag/vector_index.py:161`) filter on payload keys that simply were not
there, so any org-filtered query returned nothing.

Cause: the corpus was built before T-ORG1/T-ORG3 wired `curated_orgs_for()` into
`rag/orchestrator.py::_finish`. The tagging code, `KNOWN_ORGS`, and the MCP filters were all
correct and tested — they had just never run over this data.

Fixed by `scripts/backfill_curated_author_orgs.py` (+ tests), which writes what `_finish` would
have written, in both stores, without re-ingesting:

```
curated ids: 147
sqlite papers rows updated: 147
qdrant points now tagged curated=Waymo: 3529
```

Only the `curated` tier is backfilled — an enumerated fact from Waymo's own index pages, exact by
construction. The `email_domain`/`keyword` heuristics (precision 0.706) are deliberately **not**
backfilled: they would need the parsed Blocks re-scanned, and at ~3-in-10 wrong they cannot support
the "100% tell if it is Waymo research" requirement this corpus exists to serve. **Operator ruling
2026-08-18: anything named on Waymo's two index pages is Waymo research** — which is precisely what
the curated tier encodes.

Note the backfill *replaces* `author_orgs` rather than merging. Harmless today (Waymo is the only
entry in `KNOWN_ORGS`); if a second org is ever added, merge instead.

### Verified working over a real MCP client

`python -m app.serve --data-dir waymo/data` was driven over stdio by an actual MCP client (not an
in-process call). All four tools respond: `semantic_search`, `search_papers`, `get_paper`,
`get_span`.

**`author_org_curated_only=True` was then verified by assertion, not by eye.** Five queries chosen
to surface mostly non-Waymo work (RL training, pedestrian detection, driver behavior, lidar
segmentation, safety cases), `k=25` each:

| | hits | of which NOT on the curated list |
|---|---|---|
| unfiltered | 125 | **107** |
| `author_org_curated_only=True` | 125 | **0** |

Zero leaks, while the unfiltered control proves the corpus really is dominated by non-Waymo papers
for these queries — so the filter is doing work, not passing everything through. `search_papers`
behaves the same (32 papers returned, all curated; the unfiltered run returns 31 non-Waymo).

An earlier draft of this section claimed the filter was proven by two `local:` ids vanishing from a
filtered query. That was wrong: both (`local:3633ca3a8efb`, `local:6b9ccd0431f6`) ARE curated Waymo
papers, and their absence was a ranking artefact, not exclusion. The table above replaces it.

Citations resolve to verbatim evidence. Asking *"bootstrap resampling confidence intervals"*
restricted to curated-Waymo returns, with `anchor = {paper_id, block_id, page, bbox}` on every hit:

- `2410.08903` *Dynamic Benchmarks* p6 — "…estimated using Poisson bootstrap method (28) with 90%
  confidence level. For each of the bootstrap iterations (N=1000)…"
- `2604.03827` *Confidence Intervals for Rate Estimation…* p0/p6/p12 — "…a novel exponential
  bootstrap (EB) method for CI construction based on a fiducial argument…"
- `2312.12675` *Comparison…at 7.1 Million Miles* p6 — "…confidence intervals using a parametric
  bootstrap using the standard error for the benchmark crash counts…"

### Two known defects, neither blocking

1. **Duplicate papers — 19 pairs, corpus-wide.** *(An earlier draft of this section said "two",
   from an ad-hoc title-token scan. That was a large undercount; `scripts/find_duplicate_papers.py`
   is the real measurement and supersedes it.)*

   The pipeline's only dedup is `mint_local_ref`'s **sha256 over PDF bytes** (identical file, any
   filename → idempotent) and `detect_arxiv_id` (drop-in copy folded onto its arXiv id when that id
   is in the filename or page-1 text). **Nothing compares titles or body text.** So the same paper
   arriving as two differently-encoded PDFs, with no detectable arXiv id, is ingested twice — which
   is what happened 19 times. 16 of the 19 score a 5-gram-shingle Jaccard of **1.000** (identical
   extracted text under two ids).

   `papers.abstract` cannot detect this: **all 259 `local:` rows have an empty abstract.** The
   detector compares chunk text for that reason.

   | class | pairs | why it matters |
   |---|---|---|
   | both ids curated | **3** | a curated-only query can cite the same work twice (`2410.08903`/`local:3633ca3a8efb`, `2505.14842`/`local:3d17a9f42374`, `2210.08375`/`local:4addea530fb0`) |
   | one id curated | **11** | **the provenance hole** — a second copy of a Waymo paper sits in the corpus answering "not Waymo" to a curated query (e.g. `2212.08148`/`local:a46ca5506b1f`, `2011.00038`/`local:8f3f207a6c38`) |
   | neither curated | 5 | third-party papers, cosmetic only |

   The 11 "one curated" pairs qualify the exactness claim above: the curated tier is exact **for the
   ids on the list**, but a duplicate copy of a listed paper under a different id is not on the list
   and therefore reads as non-Waymo. Recall against *papers* is 100%; recall against *stored copies*
   is not.

   Fix is `python -m app.delete_docs <local-id> --yes` on the redundant twin, then re-run the
   backfill and `scripts/verify_curated_filter.py`. **Not done here — it destroys data and is the
   operator's call.** Deleting the `local:` side is usually right (the arXiv id is the citable one),
   but check first where the drop-in copy is the published version and the arXiv one a preprint.
2. **Poor titles on some drop-in PDFs** — `local:ebf093becfa1` is "PowerPoint Presentation",
   `local:03e2dfdfa816` is "1". Content, chunks and retrieval are unaffected; only the display
   title is wrong.

### Coverage of Waymo's own research

**143 of 153 (93.5%)** — all 114 arXiv-available and all 15 direct-PDF works are in. The 10 gaps are
all paywalled journal articles needing a human with access; see
`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §5–6 for the enumerated list and the re-fetch method.

---

## 13. Duplicate cleanup — executed 2026-08-18

Defect 1 in §12 is now resolved. **16 of the 19 duplicate pairs were collapsed; 3 were deliberately
left alone.**

### The rule, not a hand-curated list

`scripts/propose_duplicate_resolution.py` decides each pair mechanically, so this is re-runnable
after every ingest rather than a one-off:

1. **Directional containment over FULL text.** `find_duplicate_papers.py` scores a truncated prefix
   (first 40 chunks / 8,000 words) for speed — enough to *find* candidates, **not** enough to delete
   on, since two documents can share an introduction and diverge after. The proposer rebuilds
   shingles over every chunk with no cap and asks what fraction of the loser's text the survivor
   already contains. Deletion requires ≥ 0.995. **When neither side contains the other, both are
   kept** — that is the no-information-loss guarantee, and it is a hard gate, not a heuristic.
2. **The source PDF is never touched.** `delete_paper` clears SQLite rows, vectors and ingest state
   only. The proposer verifies the loser's PDF is on disk *before* proposing, so every deletion is
   reversible by re-ingesting one file. Confirmed after the fact: **16/16 PDFs still in
   `pdf_cache/`.**
3. **Tie-break** when both contain each other: keep the arXiv id. Borne out by the data — every
   survivor had authors + abstract, every deleted `local:` twin had `authors=0, abstract=N`.

All 16 deletions scored containment **1.0000 both ways with identical character counts** — the same
document stored twice, not two versions.

### What it fixed

| | before | after |
|---|---|---|
| duplicate pairs | 19 | **3** |
| …both ids curated (double-citation risk) | 3 | **0** |
| …one id curated (**copy of a Waymo paper reading "not Waymo"**) | 11 | **0** |
| papers / chunks / vectors | 1,745 / 46,279 / 48,024 | 1,729 / 45,899 / 47,628 |
| curated ids | 147 | 144 |

The three curated ids removed (`local:3d17a9f42374`, `local:3633ca3a8efb`, `local:4addea530fb0`)
were each the redundant twin of an **already-curated** arXiv survivor (`2505.14842`, `2410.08903`,
`2210.08375`), so no work lost its Waymo tag.

### Deliberately not touched

| pair | containment | why |
|---|---|---|
| `2205.02911` / `local:fa85983cd3c7` | 0.927 / 0.916 | each holds text the other lacks (15 vs 20 chunks) |
| `2312.06371` / `local:9e227ca73ba3` | 0.891 / 0.743 | same shape — looks like v1 vs v2 |
| `2207.10035` / `2301.02562` | 0.319 / 0.602 | **not duplicates** — a false positive the prefix scan flagged at 0.320 and full containment rejected |

None involve Waymo-authored work. The third is the containment gate paying for itself.

### Verification after the fact

- `pragma integrity_check` → **ok**; `app.corpus_integrity` → **OK**; Qdrant **green**.
- `scripts/verify_curated_filter.py` → **0 leaks** (125 curated-only hits, all on the list).
- `find_duplicate_papers.py` → 3 pairs remaining, **0 curated**.
- All **112** arXiv ids on Waymo's two index pages still at `stage='done'`; all **144** curated ids
  still resolve to a stored paper.

### Rollback

`app.snapshot` was taken first and covers all three stores together —
`waymo/data/backups/snapshot-20260819T024659Z` (1.2G: `papers.db` 297MB, blobs 124MB, Qdrant
snapshot 808MB), plus a separate verified `papers.db.pre-dedupe-20260818T194653.bak`
(`integrity_check: ok`, 1,745 papers). Either restores the pre-cleanup state.

---

## 14. Group C closed but one — 2026-08-18 (later same day)

The operator sourced the outstanding paywalled papers; **9 ingested, 1 still out.**

| metric | §12/§13 | now |
|---|---|---|
| `ingest_state` done | 1,729 | **1,738** |
| curated ids | 144 | **153** |
| Qdrant points tagged `curated=Waymo` | 3,466 | **3,731** |
| coverage of Waymo's own research | 143/153 | **152/153 (99.3%)** |

Re-verified after ingest: `app.corpus_integrity` **OK**; `verify_curated_filter.py` **0 leaks**;
`find_duplicate_papers.py` still **3 pairs, 0 curated** — the nine additions introduced no duplicate.

The single remaining gap is **C10**, *Representative cyclist collision injury risk distributions*
(SAE 2024-01-2645), behind the SAE paywall with no free copy published anywhere by Waymo — see
`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §7.

**Coverage was verified per-entry against all 55 safety-page entries**, replacing the earlier
figure that was inherited from the group tables rather than checked. The method matters and is
recorded there: match a page title against a paper's **opening ~3,500 characters**, never its full
text (which matches bibliographies) and never its stored title alone (drop-in titles include
"February 2021", "PowerPoint Presentation" and "9"). Both shortcuts produced wrong answers first.

---

## 15. Curated labeling closed out for the safety page — 2026-08-23

A fresh per-entry recheck of all **55 `waymo.com/safety/research/` entries** against the live stores
surfaced four Group-B drop-ins whose `local:` ids had never been added to
`fixtures/waymo/waymo_authored_ids.txt` — ingested and present, but answering "not Waymo" to every
curated-only query despite being named on the index page (the same failure class §5's backfill fixed
for arXiv ids, surviving on the drop-in side):

| site entry | corpus id | stored title (why per-title matching alone misses it) |
|---|---|---|
| #42 *Framework for a conflict typology…* (B12) | `local:1023e9edcb19` | "Conflict Typology and Causal Mechanisms Paper - ESV 2023" |
| #44 *Challenges for the evaluation of ADS…* (B13) | `local:341648b7a22a` | "Challenges in Evaluating ADS using Current Active Safety…" |
| #45 *Safety performance of the Waymo rider-only ADS at one million miles* (B14) | `local:4c3912bd5507` | "Safety Performance of Waymo RO at 1M miles" |
| #53 *Waymo safety report* (B15) | `local:2b0e7fb59b39` | — (this one's title is fine) |

All four ids are now on the curated list via `9466ae1` (that commit's message names only three;
B12's line rode along from a concurrent session's in-progress edit to the same checkout), and the
full-list backfill was re-run over all **157** ids: every id resolves to a stored paper, and Qdrant
holds **3,888** points tagged `curated=Waymo`.

Post-fix verification, all measured live:

- **54 / 55 safety-page entries are present in the corpus and carry the curated Waymo tag** in both
  stores (SQLite `papers.author_orgs` + Qdrant payload keys). Four entries match only under variant
  titles and need head-text or word-overlap matching to find: #46 → `2303.15201` ("An active
  inference model of car following…" = *"Learning An Active Inference Model of Driver Perception and
  Control…"*), #30 → `local:5fa216c3425a` ("…Waymo One service" vs stored "…Waymo Driver"), #31 →
  `2208.08651` ("…traffic conflicts" vs preprint "…naturalistic settings"), #16 →
  `local:4087ccce4c01` ("…studies of Automated Driving Systems" vs stored "…Retrospective Safety
  Studies…").
- The single absence is unchanged: **C10**, the accepted gap (§9). Confirmed negatively — zero chunks
  contain its SAE number `2024-01-2645`, and the near-identically-titled *pedestrian* sibling
  (`local:aa069e80dac9`) is the only close match in the corpus.
- `scripts/verify_curated_filter.py` → **PASS, 0 leaks** (125/125 curated-only hits on-list;
  unfiltered control shows 104 non-Waymo hits, so the filter does real work).
- Corpus-wide: **157 papers** carry the curated tag; no untagged paper matches any of the 55 page
  entries.

Method note for future re-checks (learned by producing two wrong answers first): match each page
title against stored titles **or** opening ~3,500 characters **or** ≥5 shared content words with the
stored title — then hand-check every fallback hit against its nearest sibling, because word-overlap
matching confidently pairs C10 with its pedestrian twin.

