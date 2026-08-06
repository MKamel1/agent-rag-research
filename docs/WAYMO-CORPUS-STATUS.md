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
