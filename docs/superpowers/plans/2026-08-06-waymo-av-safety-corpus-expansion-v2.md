# Waymo AV-Safety Corpus Expansion — v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. (Per this
> user's standing preference, always subagent-driven for this project — don't re-ask.)

> **Status: plan only, nothing executed.** No ingest command was run, no PDF downloaded, and
> `waymo/data/` was not modified while writing this. Every number below was re-derived on
> 2026-08-06 against live source, git, or a read-only SQLite query, per
> `docs/AGENT-PROCEDURES.md` §A.2/§A.3 — each claim carries the check that produced it.

> **Reviewed 2026-08-06 (second dispatch), against live source rather than against this doc's own
> citations.** Four sections changed as a result, each marked **[REVIEW]** where it appears:
> §1 (resume — confirmed, and the post-mortem's open code-parity question closed), §2 (the
> harvester fix — **the proposed one-expression fix is correct at the parse site but unsafe
> downstream; corrected here**), §3.5 (`tag_pool.json` — **a live sidecar the config edit in Task 3
> would silently bypass**), and a new §8 + rewritten Task 5 for the operator's 449-PDF drop-in
> delivery. §4 (affiliation tagging) was independently re-grepped and stands as written.

> **Extended 2026-08-06 (third dispatch)** with four operator-requested items, each verified
> read-only against source/git/a live query before writing, per `docs/AGENT-PROCEDURES.md` §A.2:
> new §10 (2015 arXiv cutoff — config field + per-source filters + the 827→825 resume-target
> adjustment, folded into Task 4), §11 (separate-corpus decision, recorded and reasoned), §12 (MCP
> registration — no code changes needed; documents an already-fixed stale-env-var bug elsewhere),
> and §13 (confirms the plan's Pass-1/Pass-2/GPU/dashboard settings are the existing tuned values,
> not re-invented — no changes needed there).

**Goal:** rebuild the Waymo AV-safety corpus (`waymo/data/`, Qdrant collection `waymo_av_safety`)
against a **broadened 11-area scope**, resuming the existing partial corpus rather than restarting,
using only mechanisms this repo already supports. Supersedes
`docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md`, whose execution stalled at 17/1437
(post-mortem: `docs/WAYMO-CORPUS-STATUS.md`).

**Scope (verbatim from the operator):** AV safety · AV simulation · traffic modelling for AV
simulation · Waymo tech stack · Waymo research · research *using* Waymo data · AV-safety-evaluation
methodology · AV simulation assessment · simulation validation/realism (distributional fidelity,
sim-to-real, scenario generation) · motion forecasting **only where evaluation- or safety-framed,
explicitly not pure architecture papers** · broader AV safety-case/standards literature (UL 4600,
RSS, Safety Force Field, SOTIF, PEGASUS-adjacent scenario-based testing).

**Tech stack:** unchanged. `app.init_config`, `app.doctor`, `app.build_corpus`, `app.ingest`,
`app.ingest_local`, `app.dashboard.server`, `scripts/dashboard.sh`. No new dependencies, and — with
one exception argued in §3 — no new pipeline code.

---

## Global constraints

- **`waymo/data/` is gitignored** (`.gitignore:19`) and stays that way. Only tracked artifacts:
  docs, `fixtures/waymo/*`, and (Task 1) the scout script.
- **One physical GPU lock.** `waymo/data/config.yaml`'s `gpu_lock_path` already points at
  `/home/omar/ai-projects/research-system-rag/.gpu.lock`, the same file the main corpus uses
  (verified in the live config). Do not give this corpus its own lock — this machine has prior OOM
  history (`docs/RUNBOOK.md`).
- **arXiv rate limit:** 1 request / 3 s (`rag/harvester.py::_RATE_LIMIT_SECONDS`), descriptive
  `User-Agent` via `rag.harvester.arxiv_http_client`. Every path in this plan already honours it.
- **Never touch `ArxivSource._build_query`'s quote/boolean rejection** (`_UNSAFE_QUERY_CHARS_RE`,
  an OG-49#6/M7 injection-safety fix for dashboard-editable input). Rich boolean queries stay in
  the standalone scout, where the strings are operator-fixed literals.
- **Run everything from this repo's own checked-out tree.** The prior attempt executed every run
  from `.claude/worktrees/waymo-corpus-expansion` via a hardcoded `PYTHONPATH`
  (`docs/WAYMO-CORPUS-STATUS.md` §4, second finding). Do not reintroduce that.
- **Ingest-side tools have no `--data-dir`** — cwd is the data dir (`docs/PROJECT-STATUS.md` §2
  trap (a)). Every command below `cd`s first.

---

## Decisions this plan settles

### 1. The existing partial corpus — **RESUME, do not start fresh**

Measured 2026-08-06, read-only, against `waymo/data/papers.db`:

```
select stage,count(*) from ingest_state group by stage  ->  chunked=810, done=17
select count(*) from papers   -> 17
select count(*) from chunks   -> 388
select count(*) from quarantine -> 1
ls waymo/data/pdf_cache/*.pdf | wc -l  -> 1062
```

Resume, for four reasons that all cut the same way:

1. **The 810 stranded papers cost nothing to finish.** They completed Pass 1; their parsed/chunked
   artifacts live in `ingest_state`'s checkpoint blob (`rag/orchestrator.py:456-477`), so
   summarize/embed/store runs at Pass-2 speed with **no re-parse**. `app/build_corpus.py`'s
   `stranded_policy` (live config: `finish_first`) makes a batch drain them *first*, and
   `_apply_stranded_policy`'s docstring states the batch then "skips Pass 1 outright ... no parser-
   model load and no TEI eviction." Starting fresh throws away ~810 papers of GPU parse work.
2. **1,062 PDFs are already cached** (5.2 GB). `_PdfDownloadParser`'s `cache_dir` hit path
   (`app/assembly.py`) short-circuits the HTTP GET for every one of them.
3. **The broadened scope is a strict superset of the narrow one.** Nothing already ingested becomes
   out-of-scope; the change only adds ids. There is no contamination to purge.
4. **The schema is unaffected** by anything in this plan (no migration — see §4), so the existing
   rows stay valid.

**[REVIEW 2026-08-06] Resume re-assessed independently, and confirmed — including after the corpus
scope grew (114 previously-excluded Waymo ids + 449 drop-in PDFs).** Two things were re-measured
rather than taken from the text above:

1. **Every stranded paper is actually batchable.** `build_corpus` can only batch what
   `cached_not_done` sees, and that is `pdf_cache/*.pdf` minus `done` minus permanently-quarantined
   (`app/build_corpus.py:203-211`) — a stranded paper with no cached PDF would never drain. Measured:
   **810 of 810** stranded ids have a `pdf_cache/<id>.pdf`; 0 do not. 1,062 cached PDFs total, of
   which 235 are not tracked in `ingest_state` at all (fresh work `build_corpus` will pick up for
   free). So `--target 827` genuinely drains (see §10 for the 827 → 825 adjustment once the 2
   pre-2015 stranded papers are excluded), and restarting would discard 810 papers of GPU parse
   work plus 5.2 GB of already-downloaded PDFs for zero benefit. The new material is purely
   additive — it does not make anything already ingested out-of-scope.
2. **`docs/WAYMO-CORPUS-STATUS.md` §4's second finding is now closed, not just noted.** That
   post-mortem says every v1 run executed pipeline code from the unmerged
   `worktree-waymo-corpus-expansion` worktree and that "any *behavior* differences … were in effect
   for all four runs — worth checking before resuming, not just assuming code parity." Checked:
   `git diff --stat main...worktree-waymo-corpus-expansion` touches only `.gitignore`, `docs/`,
   `scripts/waymo_arxiv_scout*.py`, and `app/dashboard/controller.py` — and that last one is commit
   `8da1817`, the D-11 dashboard run-log change already on `main` as `4e07eb4`. **Zero delta in
   `rag/parser.py`, `rag/chunker.py`, `rag/orchestrator.py`, `app/ingest.py` or `app/assembly.py`.**
   The 810 checkpoints were produced by pipeline code byte-identical to this branch's, so they are
   safe to resume against rather than merely assumed to be.

One caveat, found while checking and worth stating because it will look like a bug otherwise:
`waymo/data/pdf_cache/` holds **1,062 `.pdf` files and 0 `.json` sidecars**. `harvest_refs`'s
cache-first `_cached_ref` needs *both* files, so a resumed run re-fetches metadata for every id via
`fetch_by_ids` — 50 ids per request, 3 s apart, so ~30 requests / ~90 s for a 1,437-id list. Cheap;
not a reason to restart. (The absent sidecars also confirm `app.prefetch_pdfs` was never run in this
data dir — it writes both files. There is no `prefetch.pid`/`prefetch.log` there either.)

### 2. The pre-2007 arXiv-ID bug — **fix `rag/harvester.py` (separate PR), and filter as belt-and-braces**

Confirmed in current source, not inferred — `rag/harvester.py:418`:

```python
versioned_id = raw_id.rsplit("/", 1)[-1]  # e.g. "2504.09999v2"
```

Against an Atom entry id like `http://arxiv.org/abs/hep-th/9304006v1`, `rsplit("/", 1)[-1]` yields
`9304006v1` → `9304006`, silently dropping the required `hep-th/` archive prefix. Sending that back
to `id_list` 400s the **entire 50-id batch** (`_fetch_by_id_list`, `_ID_LIST_CHUNK_SIZE = 50`),
which is exactly the Run-1 crash in `docs/WAYMO-CORPUS-STATUS.md` §4.

**Decision: fix it in `rag/harvester.py`.** Justification:

- It is a **general harvester defect, not a scout defect.** `_entry_to_ref` is on the return path of
  *both* `fetch()` (query harvest) and `fetch_by_ids()`. Any pre-2007 paper matching the main
  causal-methods corpus's queries produces the same poisoned `PaperRef`. Filtering ids in one
  consumer leaves every other caller broken — including `app.prefetch_pdfs`, `app.build_corpus`'s
  `_relevance_rank`, and the main corpus's production harvest.
- **It is cheap and unblocked.** `rag/harvester.py` is **not** a foundation-protected path — the
  CODEOWNERS list is `contracts/`, `rag/config.py`, `config.example.yaml`, `migrations/`,
  `rag/fakes/`, `fixtures/`, `ci/`, `.github/` (GIT-WORKFLOW.md "Foundation freeze"). Ordinary PR,
  no human sign-off gate, no migration.
- ~~**The fix is one expression.** Split on the URL path segment that actually delimits the id rather
  than on the last `/`: `raw_id.split("/abs/", 1)[-1]` keeps `hep-th/9304006v1` intact and is
  byte-identical for modern ids. Needs a test asserting both a modern and a legacy id round-trip.~~

> **[REVIEW 2026-08-06] The struck-out fix above is wrong to ship as written.** `raw_id.split("/abs/",
> 1)[-1]` is correct *at the parse site* — it does yield `hep-th/9304006v1`, and it is byte-identical
> for modern ids. But `PaperRef.paper_id` is used verbatim as a **single filesystem path component**
> everywhere downstream, and `contracts/harvester.py:20` declares it as a bare `paper_id: str` with
> no pattern validation to catch a `/`. Checked every consumer:
>
> | site | code | what a `hep-th/9304006` id does |
> |---|---|---|
> | PDF cache write | `app/assembly.py:401` `self._cache_dir / f"{ref.paper_id}.pdf"`, written by `_write_cache` via `tmp_path.write_bytes(...)` with **no `mkdir(parents=True)`** | `FileNotFoundError` — `pdf_cache/hep-th/` does not exist |
> | prefetch cache | `app/prefetch_pdfs.py:131/146/162` (`.pdf`, `.json`, `.pdf.skip`) | same |
> | blob store | `rag/document_store.py:138-139`, `:273` `self._blob_dir / f"{paper_id}.md"` | same — `blobs/hep-th/` does not exist |
> | supervisor's to-do list | `app/build_corpus.py:208` `{p.stem for p in cache_dir.glob("*.pdf")}` — **non-recursive** | even if the directories were created, a nested cache entry is invisible, so the paper is re-downloaded on every single loop iteration, forever |
>
> Nothing currently depends on the buggy behaviour — verified: the main corpus's 12,390 papers
> contain **7** non-`YYMM.NNNNN` ids and all 7 are `local:<sha256>` (a `:`, which is a legal filename
> character on Linux); zero contain a `/`, and the Waymo corpus's 17 are all modern-format. So the
> fix breaks nothing that works today. But it also **converts a loud, contained failure (a 400 that
> aborts one 50-id batch) into a set of quiet ones** (a crash mid-write, or an unbounded re-download
> loop) — which is strictly worse than the bug.
>
> **Corrected recommendation — still a root-cause fix at `_entry_to_ref`, still one PR, but it must
> make the id filesystem-safe or refuse it, not merely preserve it.** Pick one, in this order of
> laziness:
>
> 1. **Reject, don't mangle** (recommended). Keep `_entry_to_ref` from ever emitting a silently
>    wrong id: detect the legacy shape and skip the entry in `_parse_entries` with a WARNING, rather
>    than returning a `PaperRef` whose `paper_id` cannot round-trip through `id_list`. This is the
>    smallest correct diff, it fixes both `fetch()` and `fetch_by_ids()` for every caller, and it
>    matches what this corpus actually wants (its earliest genuinely relevant paper is from 2016 —
>    the 7 known legacy ids `0405089 0505496 0606226 9304006 9606006 9701008 9810047` are not
>    AV-safety papers). Cost: pre-2007 arXiv is permanently out of reach for this repo, stated
>    openly rather than as an accident.
> 2. **Preserve *and* make it path-safe.** `raw_id.split("/abs/", 1)[-1]` at the parse site, plus a
>    single shared `paper_id → filename` encoding (e.g. `/` → `__`) applied at the four path sites in
>    the table above. This is a real change to `app/assembly.py`, `app/prefetch_pdfs.py`,
>    `rag/document_store.py` and `app/build_corpus.py`, with a migration question for existing rows —
>    a genuine feature, not a one-liner. Only worth it if pre-2007 arXiv coverage is ever actually
>    wanted.
>
> Either way the test must assert more than "the id round-trips": it must assert that whatever
> `_entry_to_ref` emits is usable as a path component, since that is the invariant the four call
> sites silently rely on.

**This dispatch does not implement it** (docs/plan-only). It is a recommended follow-up ticket, and
Task 0 below gates the corpus build on it.

**Also filter, and keep filtering afterwards.** The scout writes `paper_ids.txt`; that file gets a
`^\d{4}\.\d{4,5}$` guard regardless of whether the harvester fix has landed. Rationale: the filter
costs one line and one test, it protects against *any* future malformed id (not just the legacy
form), and it makes the ingest run independent of another PR's merge timing. The known cost — legacy
pre-2007 papers get dropped — is negligible for a corpus whose earliest genuinely relevant paper is
from 2016; the 7 ids this already bit (`0405089 0505496 0606226 9304006 9606006 9701008 9810047`)
are not AV-safety papers.

### 3. The scout script — **reuse and extend it; cherry-pick, do not merge the branch**

`scripts/waymo_arxiv_scout.py` (207 lines) + `scripts/test_waymo_arxiv_scout.py` (155 lines) exist
only on `worktree-waymo-corpus-expansion` (read read-only via `git show`; the branch was **not**
checked out or merged). It is mature: three iterative fixes, and its `4430cf5` rewrite made it reuse
`ArxivSource._fetch_page` + `Harvester._backoff` — the retry machinery already proven by the
30,000-paper causal harvest. Rewriting it would be pure waste.

**Deliberate, reviewed decision (stated here because the brief requires it to be explicit):** bring
the two script files onto a working branch by *file*, not by merging the branch:

```bash
git checkout worktree-waymo-corpus-expansion -- scripts/waymo_arxiv_scout.py scripts/test_waymo_arxiv_scout.py
```

Merging the whole branch is rejected: it also carries `636eeb0` (a `.gitignore` change already
present) and `9f11bde` (the v1 plan doc this document supersedes), plus a base-branch D-11 duplicate
(`8da1817`, already on `main` as `4e07eb4`) — three commits of pure conflict for zero value.

Required edits to the script (Task 1):

- `_TOPIC_QUERIES` ← `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §2b.2's 36 queries.
- `_AUTHOR_QUERIES` ← §2b.2's 13 author queries.
- `_KEYWORD_WEIGHTS` ← §2b.3's extended table.
- **`ALREADY_CAPTURED_IDS` → empty.** This is the single most important change; see §5 below.
- Add the `^\d{4}\.\d{4,5}$` id filter from §2, with its own test.
- Bump `_MAX_RESULTS_PER_QUERY` from 300 → 600 (36 queries × 600 at 25/page = up to 864 requests ×
  3 s ≈ 43 min; acceptable for a one-shot scouting run, and the queries are now narrower so a
  300-cap would truncate the broad ones).

### 4. Affiliation tagging — **experiment-only today; this corpus does NOT wire it in**

**The wiring answer, with evidence.** Author-org tagging is **not** in the default ingest pipeline.
It is experiment-only:

| claim | evidence |
|---|---|
| The tagger is called from exactly one non-test place, a throwaway experiment script | `app/exp_author_org_tagging.py:19` imports `extract_affiliations_rule_based`/`match_known_orgs`; used at `:106-107` and `:114-115`. Its own module docstring: *"A throwaway validation script (app/exp_* convention …), not a permanent module; its output is a decision, not a library."* |
| Nothing in the pipeline calls it | `grep -rn "author_org\|raw_affiliations\|match_known_orgs\|extract_affiliations\|KNOWN_ORGS" --include=*.py app rag contracts migrations` returns hits only in: `app/exp_author_org_tagging.py`, `contracts/author_orgs.py`, `rag/summarizer.py` (the method's own definition), and test files. **No hit in `rag/orchestrator.py`, `app/ingest.py`, `app/assembly.py`, or `app/parse_phase.py`.** |
| The orchestrator does not import it | `rag/orchestrator.py`'s import block (lines 49-63) has no `author_org_tagger`. |
| There is nowhere to store a result | `grep -rn "affil\|org" migrations/*.sql contracts/document_store.py` returns **nothing**. Four migrations exist (`0001_init` … `0004_doc_type_and_chapter_titles`); none adds an affiliation or org column. |
| `docs/PROJECT-STATUS.md` §3 says the same | *"Not yet backfilled onto the existing 12,390-paper corpus by design"* — and, correctly read, not wired forward either. |

**What this corpus does about it: nothing to the pipeline.** The Waymo-vs-other distinction is
obtained for free, exactly and without any extraction step, from
`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §2 — the 114 arXiv IDs enumerated directly off Waymo's own
two research index pages. That is *ground truth by publication*, strictly better than any extractor's
precision/recall, and it costs one tracked text file.

Wiring the tagger in properly would require, at minimum: a new `paper_orgs` table (a migration —
`migrations/` **is** foundation-protected, so a CODEOWNER sign-off gate), an orchestrator stage, a
`DocumentStore` method, a retrieval-side filter to make the tag usable, and either a regex pass or
one extra Ollama call per paper. That is a real feature with a real design; it is not a side effect
of building a corpus, and the corpus does not need it. **Recommended as a separate backlog item**
(suggested id `T-ORG1`), explicitly out of scope here.

Concretely, this plan ships instead:

- `fixtures/waymo/waymo_authored_ids.txt` — the 114 ids, tracked in git, one per line. (Note:
  `fixtures/` is foundation-protected, so this one file needs the `foundation-change` label and
  operator approval on its PR. It is a data file with no code impact — cheap review.)
- Those ids are seeded into the ingest target list ahead of everything else, so the corpus contains
  Waymo's own body of work *first*, not as a leftover.

### 5. The exclusion-list defect that explains the whole failure mode

`docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §3's 173-ID list was written as *"exclude these before
downloading"*, referring to PDFs in an external folder. Verified 2026-08-06:

- That folder does not exist on this machine (`find /home/omar -maxdepth 3 -iname "*Waymo*Senior*"`
  → no output).
- **All 114** arXiv IDs from Waymo's two research pages are inside that 173-ID list.
- **0** of those 114 appear in `fixtures/waymo/paper_ids.txt` (1,437 ids).
- **0** of those 114 appear in `waymo/data/papers.db`'s `ingest_state` (any stage).

So the corpus built so far contains **none of Waymo's own published papers** — the tier
`docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §1 itself calls priority #1. The scout inherited this
because it honours the list as `ALREADY_CAPTURED_IDS`.

The list is repurposed (that doc's §3 now carries the banner) as a seed/priority list. Deduplication
belongs to the pipeline, not to a hand-maintained doc: `app/build_corpus.py::cached_not_done`
already subtracts `stage='done'` and permanently-quarantined ids on **every loop iteration**.

### 6. Why the keyword strategy extends the existing doc rather than forking

`docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` was extended in place (new §2b, §3 re-banner) rather than
replaced by a new file. The scout hardcodes `_TOPIC_QUERIES`/`_KEYWORD_WEIGHTS`/
`ALREADY_CAPTURED_IDS` as copies of that doc's tables; a second doc with the same three tables gives
the scout two upstreams and guarantees they drift — the exact class of problem
`docs/AGENT-PROCEDURES.md` exists to prevent. §2 is retained verbatim for provenance with §2b
declared authoritative on conflict.

### 7. `build_corpus` vs. a fixed ID list — the thing the v1 plan got structurally wrong

The post-mortem's headline lesson is "use `app.build_corpus`, not a hand-rolled shell loop," and
that is right. But `build_corpus` only works *as designed* under a condition the v1 plan never met,
and this is why the prior attempt ended up hand-rolling anything at all. Verified:

- `app/build_corpus.py::cached_not_done` builds each batch from **`cache_dir/*.pdf` minus `done` minus
  permanently-quarantined** — the cache is its only source of work.
- `build_to_target` unconditionally calls `ensure_prefetch(data_dir)`, which spawns
  `app.prefetch_pdfs`. There is no flag to suppress it.
- `app/prefetch_pdfs.py` harvests from **`cfg.focus_area_queries`** (`refs = list(harvester.harvest(
  cfg.focus_area_queries, harvest_cap, cfg.ordering))`) and downloads to `prefetch_target`. `grep -n
  ingest_paper_ids app/prefetch_pdfs.py` → **no hits**: the downloader cannot see an ID list at all.

So: with a fixed ID list and no useful `focus_area_queries`, `build_corpus`'s downloader has nothing
correct to fetch — which is precisely why the prior attempt set `prefetch_target: 1` to neuter it.
That was a workaround for a real structural mismatch, not carelessness; the honest fix is to stop
mismatching.

**Resolution — split the build by what each mechanism is actually good at:**

| phase | work | mechanism | why this one |
|---|---|---|---|
| A | drain the 808 in-scope stranded (810 minus the 2 pre-2015 exclusions, §10) + the rest of the 1,062 cached | `app.build_corpus --target 825` | Cache already populated; downloader has nothing to do; `stranded_policy: finish_first` drains at Pass-2 speed. `build_corpus` in its element. |
| B | the 114 Waymo-authored ids + drop-in PDFs | `app.ingest --paper-ids-file` (one batch) and `app.ingest_local` | 114 papers is one batch; a supervisor loop adds nothing. `app.ingest` downloads and caches its own PDFs via `_PdfDownloadParser._write_cache`. |
| C | the broad discovery bulk | real `focus_area_queries` + `arxiv_categories` + real `prefetch_target`, then `app.build_corpus --target N --batch-size 300` | Query-driven downloader + cache-first supervisor is exactly the design `app/build_corpus.py`'s docstring describes, and what the 12,390-paper main corpus runs in production. |
| D (optional) | precision top-up | scout → filtered `paper_ids.txt` → `app.ingest --paper-ids-file` in ≤500-id chunks | Boolean/author queries `_build_query` can't express. Supplements C, doesn't replace it. |

`prefetch_target: 1` is then not "worked around" — it is simply wrong for phase C and gets set to a
real value, and phases A/B don't care what it is.

---

### 8. [REVIEW 2026-08-06] `tag_pool.json` — the sidecar that would silently eat Task 3's config edit

`waymo/data/tag_pool.json` **already exists**, seeded `2026-08-06T03:41:15Z` with the three
placeholder queries (`autonomous vehicle safety evaluation`, `rare event extreme value safety`,
`Waymo AV safety`) — `docs/WAYMO-CORPUS-STATUS.md` §7 lists its creation as one of the things v1 got
*right*, which is exactly why it is easy to miss here.

`app/dashboard/tag_pool.py` seeds that file from `cfg.focus_area_queries` **on first touch only**
and never reads `config.yaml` again (`_read_or_seed`, `:68-95`; module docstring: *"a sidecar the
dashboard owns, seeded from `config.yaml` on first touch and never written back to it — `config.yaml`
stays the operator's own file, seed and fallback only"*). A dashboard-launched run composes its
`focus_area_queries` from `tag_pool.active_queries(...)`, not from the config
(`app/dashboard/controller.py:756-791`).

So, as the plan stood: the CLI path (`app.build_corpus` / `app.prefetch_pdfs`, which read
`cfg.focus_area_queries` directly — `app/prefetch_pdfs.py:297`) would use the new 20-query list,
while **any run started from the dashboard's control panel would still use the three stale
placeholders.** Two upstreams, silently disagreeing — the same failure class §6 exists to prevent.

**Fix, using the existing mechanism rather than a new one:** delete `waymo/data/tag_pool.json` right
after editing `config.yaml`, so the next `load`/`active_queries` re-seeds it from the new queries.
Nothing is lost — `held` is empty. Added as Task 3 Step 2b below.

### 9. [REVIEW 2026-08-06] The operator's 449-PDF drop-in library — a scope change, not an addendum

A manually-curated PDF library was placed at
`drop_in/waymo downloaded research/`. Everything below was measured read-only on 2026-08-06 —
filenames, `md5sum`, the delivery's own `manifest.json`, and `app.ingest_local.detect_arxiv_id` run
over every file. **No file was moved, renamed, ingested, or deleted.**

#### 9.1 What is actually there

| folder | PDFs | provenance | what it is |
|---|---|---|---|
| `Research Papers/` (6 numbered subfolders) | **52** | hand-named `Author_Topic_Year.pdf` | curated top tier. `01_Safety_Statistics_Evaluation` alone holds **35** — effectively the whole Waymo safety-research index (Kusano/Scanlon/Campolettano/Favaro/Victor/DiLillo/Schnelle/Engström crash-rate, benchmark, injury-risk and safety-case line of work). The other five: `02_Simulation` (6), `03_RareEvent_Robustness_LongTail` (3), `04_Behavior_Modeling` (4), `05_Foundational_Datasets` (1, the WOD paper), `06_Perception_Planning_Reference` (3) |
| `Research Papers (Extended - Lower Priority 53-200)/` (9 lettered subfolders) | **150** | hand-named, numbered `053_`…`201_` | second tier. `E_Waymo_Perception_Reference` (48) and `F_External_AV_Safety_Methodology_Broader` (32) dominate; then `D_Waymo_BehaviorPrediction_MotionForecasting` (19), `C_Waymo_Stats_Simulation_GeneralML` (14), `G_Government_Industry_Safety_Frameworks` (12 — NHTSA policy documents, RAND RR1478, UL 4600 voting version, Mobileye RSS, NVIDIA SFF, PEGASUS method overview, Waymo's safety-case whitepaper), `B_External_RareEvent_AV_Safety_Academic` (9), `H_External_ScenarioBased_Testing_Additional` (8), `A_Waymo_Safety_Additional` (6), `I_ThirdParty_WaymoDataset_Applications` (2) |
| `Total Research Library/` (flat) | **247** | machine-harvested; `s2_<hash>_` / `openalex_W<id>_` names + a 243-entry `manifest.json` carrying title/authors/year/venue/`sha256`/`pdf_url`/`query`/`score` | an **automated OpenAlex (199) + Semantic Scholar (44) sweep**, driven by 14 queries derived from `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §2's strategy (top three by yield: *automated driving system crash rate benchmark human driver* 45, *autonomous vehicle safety evaluation statistical methodology* 44, *importance sampling autonomous vehicle safety validation* 35). Years 2002-2026. This is the **non-arXiv analogue of the scout script** — general AV-safety/traffic-engineering literature, mostly not Waymo-authored |

The folder also contains two non-PDF files inside `Total Research Library/`: `manifest.json` and a
copy of `ONBOARDING_AND_ARXIV_KEYWORDS.md` (which differs from `docs/`'s current copy — it predates
the §2b broadening; `docs/` is authoritative). Neither is a PDF, so neither is staged by
`app.ingest_local`.

#### 9.2 The three folders are NOT the same set — measured, not assumed

`Total Research Library` is **not** a flat superset or merge of the other two. Measured by content
hash over all 449 files (`md5sum`, then cross-tier set intersection):

- `Research Papers` ∩ `Extended` = **0** byte-identical files.
- `Research Papers` ∩ `Total Research Library` = **3**.
- `Extended` ∩ `Total Research Library` = **4**.
- One intra-`Extended` duplicate (`058_Favaro_BuildingCredibleCaseForSafety_2023.pdf` ≡
  `192_Waymo_SafetyCaseApproach_Whitepaper.pdf`).
- **449 files → 441 distinct documents.** Total cross-tier redundancy: 7 papers, **1.6%**.

Title-level fuzzy matching (filename token sets against `manifest.json` titles) surfaces the same 7
pairs plus one borderline near-match, so the byte-identical count is not hiding a pile of
same-paper-different-copy duplicates. The two hand-curated tiers and the machine sweep are
**complementary sets with different provenance**, which is why they are organised separately.

#### 9.3 What this delivers against the target list

`detect_arxiv_id` (filename, then first-page text) run read-only over all 449:

- **188 files resolve to an arXiv id** (182 distinct) — 24 curated, 115 extended, 49 from the sweep.
  These stage under their **real arXiv paper_id**, with real fetched arXiv metadata, not a `local:` id.
- The remaining **261 mint a content-addressed `local:<sha256>` id**.
- **97 of the 114 Group-A Waymo-authored arXiv ids are already present as PDFs here.** (0 of the 114
  are currently in `waymo/data/pdf_cache/`; 13 of the 188 detected ids are already tracked in
  `waymo/data/ingest_state`.)
- **11 of the 15 Group-B direct-PDF papers**, and **14 of the 23 Group-C manual-sourcing papers**,
  are satisfied — see `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`, whose §1/§3/§4 now carry per-item status.
- **4 files are unreadable by `pypdfium2`** (`PDFium: Data format error`) and will be quarantined to
  `drop_in/failed/` by `stage_file` rather than failing the scan — all four are in
  `Total Research Library/` (`openalex_W1970332306`, `W4213147678`, `W4225349279`, `W4309618441`).

**Scope consequence, stated honestly:** this is not gap-filling for 23 missing papers. It roughly
doubles the corpus's near-term size on its own (441 distinct documents vs. the 827 currently
tracked), and it shifts the corpus's centre of gravity — `Total Research Library` is general
AV-safety / traffic-engineering / surrogate-safety literature from academic databases, most of it
neither Waymo-authored nor arXiv-hosted, i.e. **material the arXiv-only pipeline could never have
reached**. Phase C's `--target 3000` estimate should be read as *arXiv discovery on top of a ~441-document
manually-curated base*, not as the total.

#### 9.4 The mechanism constraint that decides how it gets ingested

**`app.ingest_local` cannot be pointed at this tree as it stands.** Read from the actual scanner,
not the module docstring:

```python
# app/ingest_local.py:311-320  (scan_drop_dir)
for sub in ("papers", "books", "done", "failed"):
    (drop_dir / sub).mkdir(parents=True, exist_ok=True)
for sub, doc_type in (("papers", "paper"), ("books", "book")):
    for pdf_path in sorted((drop_dir / sub).glob("*.pdf")):
```

- `glob("*.pdf")`, **not** `rglob` — the scan is **flat, one level deep**. A PDF in
  `papers/01_Safety_Statistics_Evaluation/x.pdf` is invisible. `_report_dry_run` (`:371-375`) uses
  the identical non-recursive glob, so `--dry-run` would also report "no PDFs" and give false
  reassurance.
- Only `papers/` and `books/` are scanned. A PDF loose at the top of `drop_in_dir` is invisible too.
- `--drop-dir PATH` overrides `cfg.drop_in_dir` but **does not** change the `papers/`+`books/`
  convention — it cannot be aimed at a subfolder directly.
- `stage_file` **moves** the source file (`path.rename(_unique_dest(done_dir, path.name))`,
  `:295`). Pointing the tool at the operator's library in place would flatten and relocate all 449
  curated files into one `done/` directory. **Copy in, never move in.**

Two facts that make the reorganisation cheap: all **449 basenames are unique** (no collision when
flattened into one directory), and the library sits under the *main* corpus's `drop_in/` while the
Waymo corpus's `drop_in_dir` is `waymo/data/drop_in` — a different directory entirely, so nothing
is at risk of being picked up by an unrelated main-corpus run today.

---

### 10. [2026-08-06] The 2015 arXiv cutoff — a query-side config field AND a separate filter at every fixed-id source

Verified directly against `waymo/data/papers.db` (read-only), 2026-08-06:

- **All 17 `done` papers are 2017-07-16 or later.** `select paper_id, published from papers order
  by published` returns a clean run from `1707.04896` (2017-07-16) to `2607.16156` (2026-07-17),
  zero pre-2015. **No action needed on the existing 17.**
- **Of the 810 `chunked`-stage papers** (no `papers` row yet — `published` is only written at
  `stored`/`done`, so year has to come from the arXiv id's own `YYMM.NNNNN` prefix), all 810 ids
  match the modern format (zero malformed/legacy-style ids), and exactly **2 are pre-2015**:
  `1009.1191` (2010-09, "Universality of Cluster Dynamics" — condensed-matter physics, confirmed
  off-topic by reading its parsed markdown in `ingest_checkpoint.artifacts_json`) and `1203.5986`
  (2012-03, "Bayesian Network Enhanced with Structural Reliability Methods: Methodology" —
  borderline-relevant risk/reliability methodology, but still pre-cutoff). The other 808 are all
  post-2015.

**Config change:** `arxiv_date_from: "2015-01-01"` in the "Authorized config edits" table below.
`rag/harvester.py:232` folds `arxiv_date_from`/`arxiv_date_to` into every `search_query` at the
download layer — zero code needed, covers Phase C/D's future query-driven harvest.

**This does NOT retroactively filter the plan's other three paper sources — they're id lists, not
queries, so a query-side date filter never touches them:**

1. **The 114 Waymo-authored arXiv ids (`fixtures/waymo/waymo_authored_ids.txt`, Task 2) and the
   scout's `candidates.json` (Task 7 Phase D).** Both are plain `YYMM.NNNNN` arXiv ids — filter by
   the id's own year prefix (`YY < 15` → drop) before writing `paper_ids.txt`/`--paper-ids-file`,
   same method used above for the 810. Add this check alongside Task 7 Step 3's existing
   `re.fullmatch(r'\d{4}\.\d{4,5}', ...)` id-format filter — same pass, one extra comparison.
2. **The drop-in library (449 PDFs, §9).** `app.ingest_local.detect_arxiv_id` run read-only over
   all 449 (same pass §9.3 already used) splits it into three sub-populations, each with its own
   filter:
   - **188 files resolve to a real arXiv id** (24 curated + 115 extended + 49 sweep): filter by the
     arXiv-ID year prefix, identical to method 1.
   - **194 of the remaining 261** — every `Total Research Library/` file that isn't in the 4-file
     unreadable set (243 manifest entries − 49 arXiv-resolving = 194) — has a usable
     **`manifest.json`'s `year` field** (int, present on all 243 entries, keyed by `local_file`
     basename; confirmed by direct read, e.g. `{"year": 2011, "local_file":
     "openalex_W1492596192_...pdf", ...}`). Filter on `year < 2015` before staging. Measured:
     **11 of 243** manifest entries are pre-2015 (`W1828553022` 2002 through `W2344569186` 2011);
     none overlap the 49 arXiv-resolving files already accounted for by method 1.
   - **The remaining 63 files** (`Research Papers/` + `Extended/`, hand-named, no manifest, no
     arXiv id) are the genuinely gap-prone tier — investigated rather than left unresolved, by
     testing two candidate signals against all 63, read-only, reusing `app.ingest_local`'s own
     `detect_arxiv_id`/`_first_page_text` (zero new code):
     - **First-page year regex** (`_YEAR`, the same one `mint_local_ref` already uses as its
       `published` fallback for `local:` ids) is **unreliable here**: it produced 3 apparent
       pre-2015 hits (`2000`, `2006`, `1938`), and all 3 are false positives — the filenames
       self-report 2025/2026 (`Chen_DynamicBenchmarks_SpatialTemporalAlignment_2025.pdf`,
       `FraadeBlanar_BeingGoodAtDriving_2026.pdf`, `Johnson_FieldOfSafeMotion_2026.pdf`); the
       regex is matching a citation year inside body text, not the paper's own date.
     - **The filename's own trailing year token** (the tier's naming convention,
       `Author_Topic_Year.pdf` / `NNN_Topic_Year.pdf`) is reliable: **58 of 63** files carry one,
       and **zero of the 58 are pre-2015**.
     - **The remaining 5** carry no year in filename or first-page regex:
       `182_RAND_RR1478_DrivingToSafety_Official.pdf`, `189_Mobileye_SDS_SafetyArchitecture.pdf`,
       `190_Mobileye_RSS_FactSheet.pdf`, `192_Waymo_SafetyCaseApproach_Whitepaper.pdf`,
       `193_PEGASUS_MethodOverview.pdf`. Checked individually by reading each one's extracted
       page-1 text: RAND RR-1478 "Driving to Safety" (Kalra & Paddock, RAND Corporation, 2016);
       Mobileye's safety-architecture paper (page 1 states "Mobileye, 2024"); Waymo's safety-case
       whitepaper (page 1 states "March 2023"); Mobileye's RSS fact sheet (RSS itself launched
       2017, this is a marketing sheet describing it, necessarily later); PEGASUS's method overview
       (title-page-only PDF, no extractable body text — the PEGASUS project ran 2016-2019). All
       five confirmed post-2015 by direct inspection; none need exclusion.

     **Decision: accept this 63-file tier without an automated hard date filter.** The reliable
     signal (filename year) already clears all 58 it covers; the remaining 5 were resolved by a
     one-off manual check on a fixed, bounded set. Building a general first-page-date extractor
     here would spend real code fixing a signal already shown unreliable, for a population that
     needed zero exclusions in the end. Stated as a deliberate, bounded gap: if a *future*
     curated-tier delivery arrives with more files and no filename year, this manual-check approach
     does not scale and would need revisiting then, not now.

**Resume target changes from 827 to 825.** `app.build_corpus` has no id-list input for Phase A —
its batch is `cache_dir.glob("*.pdf")` minus `done` minus permanently-quarantined
(`cached_not_done`, `app/build_corpus.py:203-211`), so there is no `--exclude-ids` lever. Both
`1009.1191.pdf` and `1203.5986.pdf` are confirmed present in `waymo/data/pdf_cache/` (still
`chunked`-stage, not `done`, not quarantined), so they would otherwise be swept into Phase A's
drain. **Concrete step, folded into Task 4 below:** move (not delete — keep the already-downloaded
bytes) both files out of `pdf_cache/` before running `build_corpus`, then run `--target 825`
(17 done + 808 in-scope stranded) instead of `--target 827`. This keeps `cached_not_done`'s glob
from ever seeing them, zero code change, and no risk of the supervisor re-downloading them later —
their `ingest_state` row stays at `chunked` indefinitely, excluded from `cached_not_done` for as
long as their PDF sits outside the glob path.

### 11. [2026-08-06] Waymo stays a separate corpus, not merged into the main one — reversible, not permanent

The operator asked whether Waymo should live in its own corpus or share the main causal-methods
one. Recorded here as an explicit, reasoned decision rather than left as an unwritten assumption:

**Keep it separate.** Verified before writing:

- `contracts/vector_index.py`'s `SearchFilters`/`VectorPayload` (read in full) have no
  "domain"/"corpus" field today — `SearchFilters` filters on `categories`, `published_after/before`,
  `kind`, `doc_type`, `paper_id` only; `VectorPayload` carries `paper_id`/`kind`/`section_path`/
  `text`/`categories`/`published`/`embedding_version`/`doc_type`, nothing corpus-scoped. The only
  isolation mechanism between domains today is structural, not a filter: each `app.serve` process
  is bound to exactly one `DocumentStore`/`VectorIndex`/Qdrant collection via its own `config.yaml`
  (`docs/PROJECT-STATUS.md` §2, "second corpus = second directory").
- Merging into one corpus would mean adding a new field to a **foundation-protected contract** —
  `.github/CODEOWNERS` lists `/contracts/` under `@MKamel1` sign-off, confirmed by reading the file
  — plus a schema migration (`migrations/` is separately foundation-protected too), just to keep two
  topically-disjoint domains (causal-inference methods vs. AV safety) from polluting each other's
  retrieval relevance in a shared Qdrant collection.
- Staying separate costs zero new schema/contract work and matches how this corpus has been
  described throughout this effort — experimental, disposable, still under development
  (`docs/WAYMO-CORPUS-STATUS.md`; `docs/PROJECT-STATUS.md` §1: "much smaller and mid-build, not
  production-grade").
- **This is reversible, not permanent.** Revisit merging only if a genuine cross-domain retrieval
  need shows up later — e.g. rare-event/extreme-value risk-estimation statistics methods that turn
  out to be genuinely shared between both domains — not as a default to drift back toward.

### 12. [2026-08-06] MCP server registration — no code changes; a real bug found and fixed along the way

While investigating whether Waymo needs its own MCP-side changes, a live bug was found in the
operator's global Claude Code config (`~/.claude.json`, outside this repo) and already fixed there.
Recorded here as a finding, not a to-do — verified independently before writing:

- `app/serve.py`'s own module docstring (read in full) states `--data-dir` was added specifically
  because the composition root used to read `RAG_DB_PATH`/`RAG_BLOB_DIR`/`RAG_COLLECTION`
  environment variables directly, "a CONVENTIONS.md §3 violation (only `rag/config.py` may read
  env vars)" — fixed, and those three env vars are no longer read anywhere in `app/serve.py`.
  Confirmed by reading the module: `_parse_args` only recognizes `--data-dir`; when given,
  `load_config(_data_dir / "config.yaml")` resolves `db_path`/`blob_dir` absolute against that
  directory, and `collection` comes from the loaded `Config` — never a separate override
  (`app/serve.py:47-58`).
- The existing `research-system-rag` MCP entry in `~/.claude.json` was setting those same three
  now-dead env vars. They were being silently ignored — the server was actually resolving the main
  corpus by cwd-walkup coincidence through the repo-root `config.yaml` symlink, not by the env vars
  doing anything. **Already fixed** (outside this repo, spot-checked read-only, 2026-08-06): the
  entry's `args` now end `..., "-m", "app.serve", "--data-dir",
  "/home/omar/ai-projects/research-system-rag-data"`, with no `env` block naming any of the three
  stale vars.

**What this means for Waymo:**

1. **No `rag/mcp_server.py` or `app/serve.py` code changes are needed** for a second corpus — the
   existing `--data-dir` flag is the correct, already-supported mechanism, and it already does the
   right thing (verified above).
2. **Lesson for any future second MCP registration:** always use `--data-dir` in `args`; never the
   env-var pattern — it is not read, and silently falls back to cwd-walkup instead of erroring,
   which is exactly the "confident fake result against the wrong corpus" failure `app/serve.py`'s
   own `--data-dir` existence check was built to prevent for the flag path (there is no equivalent
   protection for the env-var path, because that path no longer exists at all).
3. **Documented but not yet applied** — a second MCP entry for Waymo, gated on the corpus build
   from this plan actually completing (not stood up against a mid-build, still-being-filtered
   corpus):
   ```json
   "research-system-rag-waymo": {
     "type": "stdio",
     "command": "conda",
     "args": [
       "run", "-n", "agent-rag-research", "--no-capture-output",
       "python", "-m", "app.serve",
       "--data-dir", "/home/omar/ai-projects/research-system-rag/waymo/data"
     ],
     "env": { "PYTHONPATH": "/home/omar/ai-projects/research-system-rag" }
   }
   ```
   Do not register this until Task 8 (documentation obligations) confirms the build is done —
   registering it now would expose an MCP client to the pre-filter, pre-resume, partially-stranded
   corpus this whole plan exists to fix.

### 13. [2026-08-06] Reused, not re-tuned — Pass-1/Pass-2/GPU/dashboard settings

Every setting below was checked against this plan's actual command examples (not assumed) and
against its own source of truth. All five are already correct in this plan as written — nothing
below required a change to the plan itself:

| setting | plan's current value | where it's used | source of truth |
|---|---|---|---|
| `--parse-workers` | `3` | Task 4 Step 3, Task 5 Step 5, Task 6 Step 2 | `WORK-BREAKDOWN.md:548` (T-DOC51): +63% Pass-1 throughput (171.9 → 280.7 pages/min), N>1 confirmed safe by anchor round-trip verification across all 25,387 real anchors (OG-19, RESOLVED). |
| `--batch-size` (on `app.build_corpus`) | `300` | Task 4 Step 3, Task 6 Step 2 | matches the 12,390-paper main corpus's own production pattern (§7 table above: "what the 12,390-paper main corpus runs in production"). |
| `gpu_lock_path` | shared repo-root `.gpu.lock` | Global constraints; "Authorized config edits" table | confirmed still correctly stated (unchanged, "already correct") — both corpora serialize on one physical GPU rather than contending, per this machine's prior OOM history. |
| `parse_batch_size` (Config field) | **not overridden anywhere in this plan** | absent from "Authorized config edits" and every command example — confirmed by grep, zero mentions in this doc | leaving it at Config's default (`4`, `contracts/config.py:63`) lets `app/adaptive_batch_sizer.py`'s AIMD self-tuning (T-DOC21) apply to Waymo exactly as it does to the main corpus, instead of hand-picking a fixed value that would disable that self-tuning. |
| `scripts/dashboard.sh` via `DASHBOARD_DATA_DIR`/`DASHBOARD_PORT=8701` | Task 4 Step 2 | same pattern the v1 Waymo attempt already proved working — `docs/WAYMO-CORPUS-STATUS.md` §7 confirms `dashboard.pid` was alive and correctly configured at this exact port/data-dir combination. |

No discrepancy found between the operator's brief and the plan's actual text — all five values are
already the tuned/reused ones, not re-invented.

---

## Authorized `waymo/data/config.yaml` edits

`app.init_config --data-dir` wrote every other field; **leave all of them alone**. Exactly these
keys may be hand-edited, and no others:

| key | current live value | target | why |
|---|---|---|---|
| `collection` | `waymo_av_safety` | unchanged | already correct |
| `gpu_lock_path` | shared repo-root `.gpu.lock` | unchanged | already correct |
| `ingest_paper_ids` | 1,437 inline ids | **`null`** | v1's unauthorized edit; `--paper-ids-file` already does this per-invocation (`app/ingest.py:327-332`) and `build_corpus` writes its own batch files |
| `prefetch_target` | `1` | `30000` (template default, `config.example.yaml:104`) | v1's workaround; phase C needs a real downloader |
| `focus_area_queries` | 3 placeholder strings | flat keyword list (Task 3) | phase C's discovery lever; also feeds `ordering: relevance` |
| `arxiv_categories` | `null` | `["cs.RO","stat.AP","stat.ME","cs.LG","eess.SY","cs.CV"]` | download-side subject filter (OG-45), `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §2b.1 |
| `ordering` | `freshest_first` | `relevance` | precision-sensitive corpus; `build_corpus` reorders each batch by arXiv's own ranking (`_order_by_relevance`) |
| `arxiv_date_from` | `null` | **`"2015-01-01"`** | §10: download-side lower bound, folded into every `search_query` (`rag/harvester.py:232`) — covers Phase C/D's future query-driven harvest only, does **not** retroactively filter the fixed-id sources (§10 has the per-source filter for those) |

---

## File structure

```
research-system-rag/
  docs/
    WAYMO-RESEARCH-PAPERS-NEEDED.md                       # NEW (this dispatch) — the 152-paper split
    ONBOARDING_AND_ARXIV_KEYWORDS.md                      # MODIFIED (this dispatch) — §2b, §3 re-banner
    superpowers/plans/
      2026-08-06-waymo-av-safety-corpus-expansion-v2.md   # NEW (this dispatch) — this file
      2026-08-05-waymo-corpus-expansion.md                # to be marked HISTORICAL (Task 0)
  scripts/
    waymo_arxiv_scout.py                                  # from worktree branch, then extended (Task 1)
    test_waymo_arxiv_scout.py                             # ditto
  fixtures/waymo/
    waymo_authored_ids.txt                                # NEW (Task 2) — 114 ids; foundation-protected path
    candidates.json, paper_ids.txt                        # existing, preserved
  rag/harvester.py                                        # follow-up PR only (§2) — NOT this plan's diff
  drop_in/
    waymo downloaded research/                            # operator's 449-PDF master library (§9);
                                                          #   READ-ONLY — copied from, never moved
  waymo/data/                                             # gitignored; config edits per the table above
    tag_pool.json                                         # DELETE after the config edit (§8)
    drop_in/papers/                                       # flat copy of the 449 + Group B/C top-ups
```

---

### Task 0: Preconditions (no corpus work yet)

- [ ] **Step 1: land the harvester fix as its own PR — option 1 in §2, not the struck-out
      one-liner.** `rag/harvester.py`: make `_parse_entries`/`_entry_to_ref` refuse a legacy
      (archive-prefixed) arXiv id with a WARNING instead of silently emitting a mangled, unusable
      one. Add tests to `rag/test_harvester_arxiv_source.py`: a modern id
      (`http://arxiv.org/abs/2504.09999v2` → `2504.09999`, `v2`) still round-trips unchanged, and a
      legacy id (`http://arxiv.org/abs/hep-th/9304006v1`) is dropped rather than returned as
      `9304006`. Assert the emitted `paper_id` is a single path component — that is the invariant
      `app/assembly.py:401`, `app/prefetch_pdfs.py:131`, `rag/document_store.py:138` and
      `app/build_corpus.py:208` all silently rely on. Not foundation-protected; ordinary PR.
- [ ] **Step 2: run the real enforcement check before pushing** (`docs/AGENT-PROCEDURES.md` §B):
      ```bash
      echo '{}' > /tmp/fake_push_event.json
      GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH=/tmp/fake_push_event.json python -m ci.run_enforcement
      ```
      then watch CI to conclusion (`gh pr checks <n> --watch`) against the SHA you actually pushed.
- [x] **Step 3: mark the v1 plan HISTORICAL** — add to the top of
      `docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md`:
      `> **HISTORICAL** — superseded by 2026-08-06-waymo-av-safety-corpus-expansion-v2.md; its
      execution is post-mortemed in docs/WAYMO-CORPUS-STATUS.md. Current state:
      [PROJECT-STATUS.md](../../PROJECT-STATUS.md).`
- [x] **Step 4: confirm services.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.doctor
      ```
      Expected: `doctor: OK`, logging `db_path`/`blob_dir` under `waymo/data/` and
      `collection=waymo_av_safety` — never `papers`.

### Task 1: Bring the scout onto this branch and extend it to the broadened scope

**Files:** `scripts/waymo_arxiv_scout.py`, `scripts/test_waymo_arxiv_scout.py` (both from the
worktree branch, by file — see §3).

- [x] **Step 1: fetch the two files by path (never merge/checkout the branch).**
      ```bash
      cd /home/omar/ai-projects/research-system-rag
      git checkout worktree-waymo-corpus-expansion -- \
        scripts/waymo_arxiv_scout.py scripts/test_waymo_arxiv_scout.py
      ```
- [x] **Step 2: write the failing tests first** (TDD, CONVENTIONS §0.7). Add to
      `scripts/test_waymo_arxiv_scout.py`:
      - `test_already_captured_ids_is_empty()` — asserts `len(ALREADY_CAPTURED_IDS) == 0`
        (replaces the existing `== 173` assertion, which now encodes the §5 defect).
      - `test_is_modern_arxiv_id_rejects_legacy_ids()` — `9304006`, `hep-th/9304006` → False;
        `2504.09999`, `2011.00038` → True.
      - `test_score_text_scores_new_scope_keywords()` — e.g. `"waymax sim agents sotif"` →
        `5 + 4 + 4`.
      - `test_topic_queries_cover_every_scope_area()` — asserts the count and that each of
        `sotif`, `ul 4600`, `pegasus`, `scenario generation`, `sim-to-real`, `traffic simulation`,
        `waymax` appears in at least one query string.
- [x] **Step 3: implement** — replace `_TOPIC_QUERIES`, `_AUTHOR_QUERIES`, `_KEYWORD_WEIGHTS` with
      `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §2b.2/§2b.3; empty `ALREADY_CAPTURED_IDS`; add
      `_is_modern_arxiv_id` and apply it in `scout()` before scoring; bump
      `_MAX_RESULTS_PER_QUERY` to 600. Keep the `_fetch_page`/`_backoff` reuse untouched.
- [x] **Step 4: green.** `python -m pytest scripts/test_waymo_arxiv_scout.py -v` — offline, no
      network, no GPU (CI-enforced, GIT-WORKFLOW.md).
- [x] **Step 5: commit** (`git add` by explicit path, never `-A`).

### Task 2: Seed the Waymo-authored ground-truth list

**Files:** `fixtures/waymo/waymo_authored_ids.txt` (NEW — **foundation-protected path**, so this
PR needs the `foundation-change` label and operator approval; agents never merge it).

- [x] **Step 1: write the file** — the 114 ids from `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §2, one
      per line, sorted. **Apply the §10 year filter first**: drop any id whose `YYMM` prefix's `YY`
      is `< 15` (pre-2015) before writing. (Expected to be a no-op here — Waymo's own published
      research starts well after 2015 — but the check costs one line and keeps this file consistent
      with the same rule applied to every other id source in §10.)
- [x] **Step 2: verify it against the doc**, don't eyeball it:
      ```bash
      python3 - <<'PY'
      import re, pathlib
      doc = pathlib.Path("docs/WAYMO-RESEARCH-PAPERS-NEEDED.md").read_text()
      ids = set(re.findall(r"\b\d{4}\.\d{4,5}\b", doc.split("## 2. Group A")[1].split("## 3.")[0]))
      fx  = {l.strip() for l in open("fixtures/waymo/waymo_authored_ids.txt") if l.strip()}
      assert ids == fx, (len(ids), len(fx), ids ^ fx)
      assert len(fx) == 114, len(fx)
      print("OK", len(fx))
      PY
      ```
- [x] **Step 3: commit and open the PR with the `foundation-change` label.** Leave the merge to the
      operator (GIT-WORKFLOW.md "Agent git-action authorization").

### Task 3: Reconfigure `waymo/data/config.yaml`

**Files:** `waymo/data/config.yaml` (gitignored; no commit).

- [x] **Step 1: back the current file up** into `waymo/data/config.yaml.pre-v2` before editing —
      it holds the 1,437-id `ingest_paper_ids` block, which is the only copy outside
      `fixtures/waymo/paper_ids.txt`.
- [x] **Step 2: apply exactly the edits in the "Authorized config edits" table above.** Set
      `focus_area_queries` to a flat keyword list (`ArxivSource._build_query` wraps each as
      `all:"<term>"` and rejects `"`/`\` — plain phrases only, no booleans):
      ```yaml
      focus_area_queries:
        - "autonomous vehicle safety"
        - "automated driving system safety evaluation"
        - "autonomous driving simulation"
        - "traffic simulation realism"
        - "scenario-based testing automated driving"
        - "safety-critical scenario generation"
        - "rare event risk estimation autonomous vehicle"
        - "crash rate benchmark automated driving"
        - "surrogate safety measures traffic conflict"
        - "sim-to-real gap autonomous driving"
        - "driving behavior model calibration"
        - "motion forecasting evaluation autonomous driving"
        - "safety case automated driving"
        - "operational design domain safety"
        - "responsibility sensitive safety"
        - "safety of the intended functionality"
        - "Waymo Open Dataset"
        - "Waymo Open Motion Dataset"
        - "autonomous vehicle runtime monitoring"
        - "reachability analysis vehicle safety"
      ```
- [x] **Step 2b: delete the stale `tag_pool.json` so the dashboard re-seeds from the new queries**
      (§8 — without this, dashboard-launched runs keep using the 3 placeholder queries while CLI
      runs use the new 20):
      ```bash
      rm /home/omar/ai-projects/research-system-rag/waymo/data/tag_pool.json
      ```
      Safe: its `held` list is empty, so nothing an operator chose is discarded. Verify the reseed
      after Step 3 — `GET /api/status` on port 8701 should report the new `active` list.
- [x] **Step 3: verify it loads and points where expected.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.doctor
      ```
      Expected: `doctor: OK`, `collection=waymo_av_safety`, paths under `waymo/data/`.
- [x] **Step 4: create the drop-in tree** the config already names
      (`drop_in_dir: .../waymo/data/drop_in`, verified in the live config):
      `mkdir -p /home/omar/ai-projects/research-system-rag/waymo/data/drop_in/papers`.
      (`app/ingest_local.py::scan_drop_dir` creates `papers/`, `books/`, `done/`, `failed/` itself
      on first run, so this is belt-and-braces, not required.)

### Task 4: Phase A — drain the existing 825 (excludes the 2 pre-2015 stranded papers, §10)

**Files:** none. Runtime only.

- [x] **Step 1: exclude the 2 pre-2015 stranded papers before starting** (§10) — `build_corpus` has
      no id-list input, so the only lever is keeping their PDFs out of `cached_not_done`'s glob:
      ```bash
      mkdir -p /home/omar/ai-projects/research-system-rag/waymo/data/pdf_cache/excluded-pre2015
      mv /home/omar/ai-projects/research-system-rag/waymo/data/pdf_cache/{1009.1191,1203.5986}.pdf \
        /home/omar/ai-projects/research-system-rag/waymo/data/pdf_cache/excluded-pre2015/
      ```
      Moves, not deletes — the already-downloaded bytes are kept, just out of the glob path. Their
      `ingest_state` rows stay at `chunked` (never reached, never re-downloaded) unless the files
      are moved back later.
- [x] **Step 2: start the second dashboard** (own port, own data dir):
      ```bash
      cd /home/omar/ai-projects/research-system-rag
      DASHBOARD_DATA_DIR="$PWD/waymo/data" DASHBOARD_PORT=8701 scripts/dashboard.sh start
      ```
- [x] **Step 3: run the supervisor** — this is the mechanism the post-mortem says to use, and the
      one place it fits without qualification (the cache is already full):
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.build_corpus \
        --target 825 --parse-workers 3 --batch-size 300
      ```
      `--target 825` = `done (17) + chunked (808 in-scope, after excluding the 2 pre-2015 papers in
      Step 1)`. With `stranded_policy: finish_first`, the first batches are stranded-only and skip
      Pass 1 entirely; the run log says so explicitly (`"draining N stranded (Pass-1-complete)
      paper(s), Pass 1 is a no-op for this batch"`). **Do not** write a shell wrapper around this —
      `build_corpus` recomputes remaining work every iteration (`cached_not_done` →
      `_write_batch_ids`) and stops on a real nonzero exit (`subprocess.run(..., check=True)`), the
      two things `run_batches.sh` got wrong (`docs/WAYMO-CORPUS-STATUS.md` §5).
- [ ] **Step 4: verify** — `funnel.done` ≈ 825 on `http://127.0.0.1:8701/api/status`
      (`X-Dashboard-Token` from `waymo/data/.dashboard_token`), `consistency.consistent: true`.
      Compare against a direct read-only `select stage,count(*) from ingest_state group by stage`;
      the dashboard is a reader, not the authority.

### Task 5: Phase B — the 449-PDF drop-in library first, then the arXiv top-up

**Files:** none tracked. Runtime only. **Reordered 2026-08-06 (§9):** the drop-in library now comes
*before* the arXiv id-file run, because 97 of the 114 Waymo-authored ids are already in it as PDFs.
Staging first puts those PDFs in `pdf_cache/` under their real arXiv ids, so Step 5's id-file run
finds them cached (`app/assembly.py`'s `_cached_ref` hit path) and downloads only the ~17 remainder.
Running the id-file first would re-download 97 PDFs the machine already has.

- [x] **Step 1: re-fetch both Waymo research index pages and diff against the existing 152-paper
      enumeration before anything else in this task runs.** `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`'s
      count is a single `WebFetch` snapshot from 2026-08-06 (Self-review §4(c) flagged this as
      unverified, not complete) — confirm it's still current, don't just trust it silently:
      1. `WebFetch` `https://waymo.com/research/` and `https://waymo.com/safety/research/` again.
      2. Enumerate every paper/publication listed on each page the same way the original pass did
         (title, authors if listed, venue/year if listed, arXiv id if resolvable).
      3. Diff the fresh list against `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`'s existing Group A/B/C
         entries by title. Two outcomes:
         - **No new papers, no structural change (pagination, a redesigned listing, etc.)**: note the
           re-fetch date in `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`'s header as confirmed-current, and
           proceed to Step 2.
         - **New papers found, or evidence either page paginates/loads more beyond what a single
           fetch captured**: update `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`'s Group A/B/C split and
           `fixtures/waymo/waymo_authored_ids.txt` (Task 2) with the additions *before* continuing —
           do not proceed to Step 2 on a list known to be incomplete.
      One-time check, matching this plan's one-shot build style — not a recurring/scheduled re-fetch.
- [x] **Step 2: flatten the library into the drop tray by COPY, never by move.** `scan_drop_dir`
      is a flat `glob("*.pdf")` over `papers/`/`books/` only (§9.4) — nested folders are invisible —
      and `stage_file` *moves* what it stages, so a move here would destroy the operator's curated
      folder structure. All 449 basenames are unique, so a flat copy is collision-free:
      ```bash
      cd /home/omar/ai-projects/research-system-rag
      mkdir -p waymo/data/drop_in/papers
      find "drop_in/waymo downloaded research" -name '*.pdf' \
        -exec cp -n {} waymo/data/drop_in/papers/ \;
      ls waymo/data/drop_in/papers/*.pdf | wc -l   # expect 449
      ```
      `cp -n` (no-clobber) makes a re-run idempotent. Everything goes to `papers/` — the delivery
      contains no books, and a book mis-filed as a paper costs GPU-hours (`_report_dry_run`'s own
      docstring). The source library under `drop_in/waymo downloaded research/` is left untouched
      and remains the operator's master copy.
- [x] **Step 3: dry-run and read the output before staging anything.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest_local --dry-run
      ```
      Expect **449** previews, of which ~188 report a detected arXiv id and ~261 fall back to a
      `local:` id (§9.3). A report of "no PDFs in …" means Step 2's copy landed in the wrong place —
      that is the exact failure the non-recursive glob produces silently.
- [ ] **Step 4: stage only — do NOT let `ingest_local` invoke a single 449-paper `app.ingest`.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest_local --stage-only
      ```
      `--stage-only` writes `<paper_id>.pdf` + `.json` sidecars into `pdf_cache/` and the
      `drop_in/manifest-<UTC>.txt`, then stops. Phase A/C's `app.build_corpus` picks them up from
      the cache in `--batch-size` batches like any other cached PDF (`cached_not_done`,
      `app/build_corpus.py:203-211`) — resumable, stall-detecting, and stopping on a real nonzero
      exit. A bare `app.ingest_local` would instead fire **one** `app.ingest --paper-ids-file` over
      all 449 ids: a monolithic, unsupervised run, which is precisely the shape that got killed
      mid-flight three times in v1 (`docs/WAYMO-CORPUS-STATUS.md` §3, Runs 2-4).
      **Budget the staging run's wall-clock honestly:** `stage_file` calls `fetch_by_ids([id])`
      **once per file** (`app/ingest_local.py:263`), so ~188 separate arXiv metadata requests
      back-to-back with no inter-file delay. `_fetch_by_ids_with_backoff` rides out a 429 with
      30s/60s/120s retries (`app/assembly.py:142-167`), so this is safe but can be slow; a file
      whose metadata fetch exhausts the retry budget falls back to a `local:` id rather than failing.
- [ ] **Step 5: verify the staging, then top up the remaining Waymo-authored ids.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      ls drop_in/failed/ | wc -l          # expect ~4 (§9.3's unreadable PDFs), each with a .err
      ls pdf_cache/*.pdf | wc -l          # expect ~1062 + ~445
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest \
        --paper-ids-file /home/omar/ai-projects/research-system-rag/fixtures/waymo/waymo_authored_ids.txt \
        --parse-workers 3
      ```
      One batch is fine for 114. The ~97 already staged are cache hits (no download); only the
      remainder is fetched.
- [ ] **Step 6: fetch the 4 outstanding Group-B PDFs** — **B1, B2, B7, B8** only; the other 11 are
      already in the library (`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §3). Public URLs, no auth,
      into `waymo/data/drop_in/papers/`, then re-run Step 4. Name each with a
      `title--<short title>.pdf` marker — T-DOC88 lets an explicit filename title outrank fetched
      metadata, which matters for the non-arXiv ones that mint a `local:<sha256>` id.
- [ ] **Step 7: add whatever of the 9 outstanding Group-C papers the operator sources**
      (C2, C8, C10, C17, C18, C20, C21, C22, C23) to the same folder and re-run Step 4.
      `mint_local_ref` is content-addressed, so re-dropping an identical file is a no-op.
- [ ] **Step 8: sanity-check** that a `local:`-id paper is retrievable via the dashboard's
      `/api/search`, and review `drop_in/failed/` — anything beyond §9.3's four known-corrupt files
      is a real problem, not expected noise.

> **[EXECUTION 2026-08-07, superseded same day] The run is now dashboard-driven, and the chainer
> drives the dashboard's control API rather than launching processes itself.** The operator asked to
> be able to pause/resume the build, which only works for runs the *controller* started — a
> hand-launched CLI run writes no `run_manifest.json`, so the UI's Pause/Resume cannot see it. Phase A
> was therefore restarted via `POST /api/control {"action":"start"}` (verified: `running → paused →
> running`, build process stops and returns), and `waymo/data/chain_phases.sh` now advances the
> phases by posting `start_drop_in` and `start` to the same API, so every phase stays pausable.
>
> **`controller.stop()` marks a run `status: "done"` — the same terminal status as a natural finish.**
> Reading "done" alone as "phase complete, start the next one" would mean the operator pressing Stop
> silently launches the next phase. The chainer tells them apart by transition path
> (`stopping → done` = operator stop, abort; `running → done` = natural, advance; `pausing → paused`
> = hold, never auto-resume), polling at 10s to shrink the miss window. All three paths were
> unit-tested against a scripted status sequence before the chainer was launched.
>
> **[EXECUTION 2026-08-07] Original deviation: the phases are chained rather than run by hand.**
> The operator was AFK for the build, so stopping at each phase boundary to wait for a human (or an
> agent session) would have idled the GPU for hours between phases. `waymo/data/run_phases.sh`
> (gitignored, lives with the corpus data) waits for the already-running Phase A pid, then runs
> Phase B1 → B2 → C in order.
>
> **This is not the thing `docs/WAYMO-CORPUS-STATUS.md` §5 warns against.** v1's `run_batches.sh`
> reimplemented `build_corpus`'s *batching* in shell — static `batch_*.txt` splits that never
> recomputed remaining work — and could not detect a failed batch. The driver reimplements nothing:
> each phase is one supported command, `build_corpus` still owns all batching, remaining-work
> recomputation, and stall detection. The two specific v1 defects are fixed and were verified by
> running the driver's own `run_phase` helper against a deliberately failing command before use:
> `set -e` is on (v1 had only `set -uo pipefail`, so a failed batch never stopped the loop), and the
> exit status is captured on the line immediately after the command, before anything else runs (v1
> wrote `echo "... exit $?"` with an intervening `$(date)` that had already reset `$?`, so it
> printed `0` for every crashed run). Verified behaviour: a failing phase reports its true non-zero
> code, aborts the chain, and later phases do not run.

### Task 6: Phase C — the broad build

**Files:** none. Runtime only.

- [ ] **Step 1: pick a target honestly.** `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §1's own framing
      stands: this topic yields "a few hundred to low thousands," and padding is a failure, not a
      success. **[REVIEW 2026-08-06]** `--target` is a *cumulative* `done`-count, so it must now be
      read on top of Phase A's 825 (§10) **and** Phase B's ~441 distinct drop-in documents (§9.3) —
      the arXiv-discovery increment `--target 3000` actually asks for is roughly 1,700, not 3,000.
      Set the target after Phase B's real `done` count is known rather than guessing now.
      Start `--target 3000` and let the supervisor tell you the truth — O-1's
      supply-exhaustion handling means an unreachable target now finishes **completed**, not failed,
      with the log line *"arXiv has no new papers for the configured queries … Finishing as
      COMPLETED, not failed."*
- [ ] **Step 2: run it.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.build_corpus \
        --target 3000 --parse-workers 3 --batch-size 300 --run-id waymo-v2-phase-c
      ```
      `--run-id` is what lets a supply-exhausted finish be **persisted** as such
      (`_write_run_outcome`) instead of only logged. `build_corpus` launches
      `app.prefetch_pdfs` itself (`ensure_prefetch_running`) — do not start a second one by hand.
- [ ] **Step 3: watch the dashboard, not the log** — port 8701. `prefetch.log` is the downloader's
      own dedicated file; the run log is the ingest batches'.
- [ ] **Step 4: on completion, record the honest yield** — `funnel` counts, quarantine reasons,
      and whether the run ended `done` or supply-exhausted.

### Task 7: Phase D (optional) — precision top-up via the scout

**Files:** `waymo/data/candidates.json`, `waymo/data/paper_ids_v2.txt` (both gitignored).

- [ ] **Step 1: run the scout** (~45 min of rate-limited requests):
      ```bash
      cd /home/omar/ai-projects/research-system-rag
      /home/omar/miniconda3/envs/agent-rag-research/bin/python scripts/waymo_arxiv_scout.py \
        --out waymo/data/candidates.json
      ```
- [ ] **Step 2: human review checkpoint** — the top-20-by-score list must read as genuinely
      on-topic. Specifically check the §2b.4 carve-out: query 9 (`trajectory prediction`, inherited
      from §2) has no evaluation guard, so pure-architecture forecasting papers can slip through
      it. Hand-trim them here; that is what this checkpoint is for.
- [ ] **Step 3: write the filtered id list** — ids already `done` are excluded by the pipeline, so
      only the format filter is needed here:
      ```bash
      python3 -c "
      import json, re
      ids = [c['id'] for c in json.load(open('waymo/data/candidates.json'))
             if re.fullmatch(r'\d{4}\.\d{4,5}', c['id'])]
      open('waymo/data/paper_ids_v2.txt','w').write('\n'.join(ids)+'\n')
      print(len(ids), 'ids')
      "
      ```
- [ ] **Step 4: ingest in ≤500-id chunks** with `app.ingest --paper-ids-file`, or simply let
      Phase C's `build_corpus` pick them up after a one-off `app.ingest` pass caches their PDFs.
      Do **not** hand-roll a batch loop.

### Task 8: Documentation obligations (`docs/AGENT-PROCEDURES.md` §B)

- [ ] **Step 1:** `docs/PROJECT-STATUS.md` §1 — replace the Waymo corpus table with the post-build
      measured numbers, each carrying the query that produced it.
- [ ] **Step 2:** `docs/WAYMO-CORPUS-STATUS.md` — add a closing section recording that the v2 build
      ran, what it yielded, and whether §9's recovery runbook was followed or superseded.
- [ ] **Step 3:** `docs/PROJECT-STATUS.md` §3 — one shipped-work entry for the harvester fix (Task
      0) with its SHA, and one for the corpus build.
- [ ] **Step 4:** `docs/BACKLOG.md` — open `T-ORG1` (wire author-org tagging into ingest: migration
      + orchestrator stage + store method + retrieval filter) as the deferred half of §4.
- [ ] **Step 5:** self-check — does this work make any existing doc claim false? Fix it in the same
      PR.

---

## Self-review

**1. Spec coverage** — all 11 operator-named topic areas map to at least one query in
`docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §2b.2 (the table's `topic area` column is the map). Category
priority: §2b.1. Motion-forecasting carve-out: §2b.4 rule 1, encoded in queries 27/28 and enforced at
Task 7 Step 2's checkpoint. Standards pointers (UL 4600 / RSS / SFF / SOTIF / PEGASUS): queries
13, 29, 30, 31, 32. Waymo-authored vs. Waymo-adjacent: §4 + §2b.5 + `fixtures/waymo/
waymo_authored_ids.txt`. Drop-in routing: Task 5, through `app/ingest_local.py` only. Waymo's own
research enumerated and split: `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`.

**2. Post-mortem items, each answered rather than repeated** —
supervisor loop: Tasks 4/6 use `app.build_corpus`, and §7 explains the one structural reason the
prior attempt couldn't (query-driven downloader vs. fixed id list) so it isn't rediscovered.
Config edits: the "Authorized config edits" table is exhaustive, and both unauthorized v1 edits are
explicitly reverted rather than inherited. Legacy-id bug: §2 picks the harvester fix *and* the
filter, with the reason for each. Existing corpus: §1 resumes, with the measurement behind it.

**3. Placeholder scan** — no "TBD"/"similar to Task N". Every command is runnable as written; every
number carries the query that produced it. Two things are deliberately *not* fixed here and say so:
the harvester one-liner (Task 0, its own PR) and author-org wiring (§4, backlog item `T-ORG1`).

**3b. [REVIEW 2026-08-06] Reuse-of-existing-code audit, section by section.** Every proposed action
was checked against the real code for "does a supported mechanism already do this," and the answer
was *yes, use it* in every case — no reinvention found, three integration gaps found:

| plan action | existing mechanism | verdict |
|---|---|---|
| drain the stranded 810 | `app.build_corpus` + `stranded_policy: finish_first` | uses it; measured that all 810 are actually batchable (§1) |
| batch the work | `--batch-size` → `cached_not_done` → `_write_batch_ids` | uses them directly; explicitly forbids a shell wrapper (Task 4 Step 3). No duplication |
| ingest operator PDFs | `app.ingest_local` | only route named. **Gap found:** the scan is non-recursive and moves files (§9.4) — Task 5 rewritten around a copy-then-flatten step |
| supervise the drop-in batches | `app.build_corpus` | **Gap found:** original Task 5 let `ingest_local` fire one 449-id `app.ingest`. Now `--stage-only` + let the supervisor batch it (Task 5 Step 4) |
| edit the harvest queries | `config.yaml` + `app/dashboard/tag_pool.py` | **Gap found:** `tag_pool.json` is already seeded and never re-reads the config (§8) — Task 3 Step 2b added |
| Waymo-authored vs. adjacent | enumerated id list, not the tagger | confirmed correct; author-org tagging independently re-grepped and is experiment-only (§4) |
| dashboard drop-in tray (D-1, PR #208) | `controller.start_drop_in` | not duplicated — the plan drives `app.ingest_local` from the CLI, which is the same module the tray spawns (`controller._spawn_drop_in`, `:156-171`) |
| fix the legacy-id bug | `rag/harvester.py::_entry_to_ref` | right place, **wrong fix** — corrected in §2 |

**4. Things that could still go wrong, named rather than hidden** —
(a) Phase C's flat `focus_area_queries` cannot express the boolean precision of the scout's queries;
expect lower precision than Phase D's output, which is why the review checkpoint and `ordering:
relevance` exist. (b) `build_corpus`'s `_relevance_rank` ignores `arxiv_categories` by design (its
own docstring), so the ranking signal is broader than the download filter — an ordering weakness,
never a scope leak. (c) **[OPERATOR 2026-08-06, closed]** The two Waymo index pages may paginate
beyond one fetch and `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md`'s count was a single dated snapshot —
Task 5 Step 1 now re-fetches both pages and diffs against that snapshot immediately before the rest
of the task runs, gated on confirming no material change (or absorbing one) before continuing; not
left as a standing risk. **[REVIEW 2026-08-06]** (d) The drop-in library's 261 `local:<sha256>` documents carry
whatever title `mint_local_ref` derives from PDF metadata / first line / filename stem — for the
machine-harvested `Total Research Library` files the stem embeds the real title, but for the
hand-named tier it does not (`Kusano_CrashRates56.7MillionMiles_2025` is not a title). Consider a
`title--` rename pass over the curated tier's copies before Task 5 Step 4 if retrieval-by-title
matters; the delivery's own `manifest.json` already carries clean titles for the 243 sweep files.
(e) `stage_file` issues one arXiv metadata request per detected-arXiv file — ~188 back-to-back with
no inter-file rate limit; retry-safe but slow, and a 429 storm degrades affected files to `local:`
ids rather than failing loudly.
