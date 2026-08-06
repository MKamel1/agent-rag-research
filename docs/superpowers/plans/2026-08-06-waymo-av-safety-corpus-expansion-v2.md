# Waymo AV-Safety Corpus Expansion — v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. (Per this
> user's standing preference, always subagent-driven for this project — don't re-ask.)

> **Status: plan only, nothing executed.** No ingest command was run, no PDF downloaded, and
> `waymo/data/` was not modified while writing this. Every number below was re-derived on
> 2026-08-06 against live source, git, or a read-only SQLite query, per
> `docs/AGENT-PROCEDURES.md` §A.2/§A.3 — each claim carries the check that produced it.

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
- **The fix is one expression.** Split on the URL path segment that actually delimits the id rather
  than on the last `/`: `raw_id.split("/abs/", 1)[-1]` keeps `hep-th/9304006v1` intact and is
  byte-identical for modern ids. Needs a test asserting both a modern and a legacy id round-trip.

**This dispatch does not implement it** (docs/plan-only). It is a recommended follow-up ticket,
sized at one function + two tests, and Task 0 below gates the corpus build on it.

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
| A | drain the 810 stranded + the rest of the 1,062 cached | `app.build_corpus --target 827` | Cache already populated; downloader has nothing to do; `stranded_policy: finish_first` drains at Pass-2 speed. `build_corpus` in its element. |
| B | the 114 Waymo-authored ids + drop-in PDFs | `app.ingest --paper-ids-file` (one batch) and `app.ingest_local` | 114 papers is one batch; a supervisor loop adds nothing. `app.ingest` downloads and caches its own PDFs via `_PdfDownloadParser._write_cache`. |
| C | the broad discovery bulk | real `focus_area_queries` + `arxiv_categories` + real `prefetch_target`, then `app.build_corpus --target N --batch-size 300` | Query-driven downloader + cache-first supervisor is exactly the design `app/build_corpus.py`'s docstring describes, and what the 12,390-paper main corpus runs in production. |
| D (optional) | precision top-up | scout → filtered `paper_ids.txt` → `app.ingest --paper-ids-file` in ≤500-id chunks | Boolean/author queries `_build_query` can't express. Supplements C, doesn't replace it. |

`prefetch_target: 1` is then not "worked around" — it is simply wrong for phase C and gets set to a
real value, and phases A/B don't care what it is.

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
  waymo/data/                                             # gitignored; config edits per the table above
    drop_in/papers/                                       # NEW dir — Group B/C PDFs land here
```

---

### Task 0: Preconditions (no corpus work yet)

- [ ] **Step 1: land the harvester fix as its own PR.**
      `rag/harvester.py::_entry_to_ref` — replace `raw_id.rsplit("/", 1)[-1]` with
      `raw_id.split("/abs/", 1)[-1]`. Add two tests to `rag/test_harvester_arxiv_source.py`:
      a modern id (`http://arxiv.org/abs/2504.09999v2` → `2504.09999`, `v2`) and a legacy id
      (`http://arxiv.org/abs/hep-th/9304006v1` → `hep-th/9304006`, `v1`). Not foundation-protected;
      ordinary PR.
- [ ] **Step 2: run the real enforcement check before pushing** (`docs/AGENT-PROCEDURES.md` §B):
      ```bash
      echo '{}' > /tmp/fake_push_event.json
      GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH=/tmp/fake_push_event.json python -m ci.run_enforcement
      ```
      then watch CI to conclusion (`gh pr checks <n> --watch`) against the SHA you actually pushed.
- [ ] **Step 3: mark the v1 plan HISTORICAL** — add to the top of
      `docs/superpowers/plans/2026-08-05-waymo-corpus-expansion.md`:
      `> **HISTORICAL** — superseded by 2026-08-06-waymo-av-safety-corpus-expansion-v2.md; its
      execution is post-mortemed in docs/WAYMO-CORPUS-STATUS.md. Current state:
      [PROJECT-STATUS.md](../../PROJECT-STATUS.md).`
- [ ] **Step 4: confirm services.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.doctor
      ```
      Expected: `doctor: OK`, logging `db_path`/`blob_dir` under `waymo/data/` and
      `collection=waymo_av_safety` — never `papers`.

### Task 1: Bring the scout onto this branch and extend it to the broadened scope

**Files:** `scripts/waymo_arxiv_scout.py`, `scripts/test_waymo_arxiv_scout.py` (both from the
worktree branch, by file — see §3).

- [ ] **Step 1: fetch the two files by path (never merge/checkout the branch).**
      ```bash
      cd /home/omar/ai-projects/research-system-rag
      git checkout worktree-waymo-corpus-expansion -- \
        scripts/waymo_arxiv_scout.py scripts/test_waymo_arxiv_scout.py
      ```
- [ ] **Step 2: write the failing tests first** (TDD, CONVENTIONS §0.7). Add to
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
- [ ] **Step 3: implement** — replace `_TOPIC_QUERIES`, `_AUTHOR_QUERIES`, `_KEYWORD_WEIGHTS` with
      `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §2b.2/§2b.3; empty `ALREADY_CAPTURED_IDS`; add
      `_is_modern_arxiv_id` and apply it in `scout()` before scoring; bump
      `_MAX_RESULTS_PER_QUERY` to 600. Keep the `_fetch_page`/`_backoff` reuse untouched.
- [ ] **Step 4: green.** `python -m pytest scripts/test_waymo_arxiv_scout.py -v` — offline, no
      network, no GPU (CI-enforced, GIT-WORKFLOW.md).
- [ ] **Step 5: commit** (`git add` by explicit path, never `-A`).

### Task 2: Seed the Waymo-authored ground-truth list

**Files:** `fixtures/waymo/waymo_authored_ids.txt` (NEW — **foundation-protected path**, so this
PR needs the `foundation-change` label and operator approval; agents never merge it).

- [ ] **Step 1: write the file** — the 114 ids from `docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §2, one
      per line, sorted.
- [ ] **Step 2: verify it against the doc**, don't eyeball it:
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
- [ ] **Step 3: commit and open the PR with the `foundation-change` label.** Leave the merge to the
      operator (GIT-WORKFLOW.md "Agent git-action authorization").

### Task 3: Reconfigure `waymo/data/config.yaml`

**Files:** `waymo/data/config.yaml` (gitignored; no commit).

- [ ] **Step 1: back the current file up** into `waymo/data/config.yaml.pre-v2` before editing —
      it holds the 1,437-id `ingest_paper_ids` block, which is the only copy outside
      `fixtures/waymo/paper_ids.txt`.
- [ ] **Step 2: apply exactly the edits in the "Authorized config edits" table above.** Set
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
- [ ] **Step 3: verify it loads and points where expected.**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.doctor
      ```
      Expected: `doctor: OK`, `collection=waymo_av_safety`, paths under `waymo/data/`.
- [ ] **Step 4: create the drop-in tree** the config already names
      (`drop_in_dir: .../waymo/data/drop_in`, verified in the live config):
      `mkdir -p /home/omar/ai-projects/research-system-rag/waymo/data/drop_in/papers`.
      (`app/ingest_local.py::scan_drop_dir` creates `papers/`, `books/`, `done/`, `failed/` itself
      on first run, so this is belt-and-braces, not required.)

### Task 4: Phase A — drain the existing 827

**Files:** none. Runtime only.

- [ ] **Step 1: start the second dashboard** (own port, own data dir):
      ```bash
      cd /home/omar/ai-projects/research-system-rag
      DASHBOARD_DATA_DIR="$PWD/waymo/data" DASHBOARD_PORT=8701 scripts/dashboard.sh start
      ```
- [ ] **Step 2: run the supervisor** — this is the mechanism the post-mortem says to use, and the
      one place it fits without qualification (the cache is already full):
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.build_corpus \
        --target 827 --parse-workers 3 --batch-size 300
      ```
      `--target 827` = `done (17) + chunked (810)`. With `stranded_policy: finish_first`, the first
      batches are stranded-only and skip Pass 1 entirely; the run log says so explicitly
      (`"draining N stranded (Pass-1-complete) paper(s), Pass 1 is a no-op for this batch"`).
      **Do not** write a shell wrapper around this — `build_corpus` recomputes remaining work every
      iteration (`cached_not_done` → `_write_batch_ids`) and stops on a real nonzero exit
      (`subprocess.run(..., check=True)`), the two things `run_batches.sh` got wrong
      (`docs/WAYMO-CORPUS-STATUS.md` §5).
- [ ] **Step 3: verify** — `funnel.done` ≈ 827 on `http://127.0.0.1:8701/api/status`
      (`X-Dashboard-Token` from `waymo/data/.dashboard_token`), `consistency.consistent: true`.
      Compare against a direct read-only `select stage,count(*) from ingest_state group by stage`;
      the dashboard is a reader, not the authority.

### Task 5: Phase B — Waymo's own papers, and the drop-ins

**Files:** none tracked. Runtime only.

- [ ] **Step 1: ingest the 114 Waymo-authored ids** (one batch — no supervisor needed for 114):
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest \
        --paper-ids-file /home/omar/ai-projects/research-system-rag/fixtures/waymo/waymo_authored_ids.txt \
        --parse-workers 3
      ```
      Expected exit 0; `app.ingest` fetches metadata by id, downloads each PDF, and caches it
      (`_PdfDownloadParser`'s `_write_cache`), so these also become `build_corpus` fodder later.
- [ ] **Step 2: fetch the 15 Group-B PDFs** (`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §3) into
      `waymo/data/drop_in/papers/`. Public URLs, no auth. Name each file with a
      `title--<short title>.pdf` marker where useful — `app/ingest_local.py` (T-DOC88) lets an
      explicit filename title outrank fetched metadata, which matters for the non-arXiv ones that
      mint a `local:<sha256>` id.
- [ ] **Step 3: add whatever Group-C PDFs the operator has sourced** to the same folder.
- [ ] **Step 4: dry-run first, then stage and ingest:**
      ```bash
      cd /home/omar/ai-projects/research-system-rag/waymo/data
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest_local --dry-run
      /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest_local
      ```
      `--dry-run` prints the detected id/title/preview per file without staging (T-DOC86) — cheap
      insurance against a mis-detected arXiv id. The real run stages into `pdf_cache`, writes
      `drop_in/manifest-<UTC>.txt`, and invokes `app.ingest --paper-ids-file <manifest>` itself.
      **This is the only supported route for operator-supplied PDFs — do not invent another.**
- [ ] **Step 5: sanity-check** that a `local:`-id paper is retrievable via the dashboard's
      `/api/search`, and that no Group-B file landed in `drop_in/failed/`.

### Task 6: Phase C — the broad build

**Files:** none. Runtime only.

- [ ] **Step 1: pick a target honestly.** `docs/ONBOARDING_AND_ARXIV_KEYWORDS.md` §1's own framing
      stands: this topic yields "a few hundred to low thousands," and padding is a failure, not a
      success. Start `--target 3000` and let the supervisor tell you the truth — O-1's
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

**4. Things that could still go wrong, named rather than hidden** —
(a) Phase C's flat `focus_area_queries` cannot express the boolean precision of the scout's queries;
expect lower precision than Phase D's output, which is why the review checkpoint and `ordering:
relevance` exist. (b) `build_corpus`'s `_relevance_rank` ignores `arxiv_categories` by design (its
own docstring), so the ranking signal is broader than the download filter — an ordering weakness,
never a scope leak. (c) The two Waymo index pages may paginate beyond one fetch; both counts in
`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` are dated and should be re-fetched before being treated as
complete.
