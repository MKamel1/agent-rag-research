# Review implementation plan — RI series

**Provenance.** Three independent review campaigns run 2026-08-21 by an external reviewer model
(code-defect review rounds 1-2, plus a five-lens methodology review; verbatim transcripts in the
untracked `reviews/` directory, backed up to
`~/ai-projects/backups/research-system-rag/reviews-*.tar.gz`). Findings were verified against live
source before entering this plan; several reviewer claims were rejected or corrected in that pass
and do not appear here. Two independent planners (the reviewer model and a separate Opus planner)
produced competing implementation plans; the adjudicated merge is what follows.

**Scope boundary.** This plan covers the *code* tickets (waves 1-3) and the *instruments* for the
wave-4 measurement campaigns. Running those campaigns against the live corpus is operator work and
is not a completion condition for the RI series.

**Ticket id.** `RI-n`. Distinct from the reviewer's own finding ids (`FD-n`, `R-n`, `M-n`), which
are cited in the ticket bodies as provenance only.

---

## Workstream assignment

Tickets are grouped so that no two concurrently-running workstreams touch the same file. This is
the scheduling constraint, not a design statement: within a workstream tickets are sequential and
each lands as its own commit.

| ws | files owned | tickets |
|---|---|---|
| **A** | `rag/document_store.py`, `rag/ingest_state_sqlite.py` | RI-1, RI-5 |
| **B** | `app/dashboard/server.py` | RI-2, RI-6 |
| **C** | `rag/orchestrator.py`, `app/rechunk.py` | RI-3, RI-4 |
| **D** | `app/dashboard/status.py`, `DATA-CONTRACTS.md`, `.gitignore` | RI-8, RI-9, RI-11 |
| **E** | docstrings across `rag/`, `app/` (no logic) | RI-10 |

---

## Wave 1 — correctness

### RI-1 — `DocumentStore` connection is single-thread-bound
**File:** `rag/document_store.py:102`

`sqlite3.connect(db_path)` defaults `check_same_thread=True`. The dashboard reads corpus records
from a `ThreadingHTTPServer` handler thread, so any read through a `DocumentStore` built on another
thread raises `ProgrammingError` rather than returning data.

**Fix (adjudicated):** pass `check_same_thread=False`. **No lock.** Two facts carry the decision and
both were verified, not assumed:
- `sqlite3.threadsafety == 3` on this build (serialized) — the driver itself serializes access.
- Zero writes reach `DocumentStore` from anywhere in the `app/dashboard/` package; the ingest
  writer is a separate single-threaded process.

A lock would be dead weight against today's call graph. The hedge is explicit: this holds *because*
the threaded consumer performs no writes. Record that in the comment so a future writer-side change
is forced to revisit it rather than inheriting a silent assumption.

**Done when:** a test constructs a `DocumentStore` on one thread and reads it from another without
raising; the comment names the threadsafety level and the read-only-consumer premise.

### RI-2 — dashboard auth does not fail closed on an empty token
**File:** `app/dashboard/server.py:706`

`token = args.token if args.token is not None else _load_or_create_token(data_dir)`. Passing
`--token ""` is not `None`, so it wins over the generated token, and the comparison at `:447`
(`hmac.compare_digest(self.headers.get("X-Dashboard-Token", ""), token)`) then succeeds against a
request that sends **no token header at all** — the missing-header default `""` equals the
configured `""`. `POST /api/control` becomes unauthenticated.

**Fix:** refuse to start on an empty effective token. The guard belongs at the effective-token
resolution point (`main`), not inside `_load_or_create_token` — the file path can never produce an
empty token, only the flag can, and a guard placed where the value is *resolved* also covers any
future third source. Refuse-to-start over silently regenerating: an operator who typed `--token ""`
has a broken invocation and needs to be told, not quietly overridden.

**Done when:** starting with `--token ""` exits non-zero with a message naming the flag; a test
asserts a no-header request is rejected under every startup path.

### RI-3 — chunk payload has two definitions that have already drifted
**Files:** `app/rechunk.py:125` (`_chunk_payload`), `rag/orchestrator.py:792`

The two builders construct the same vector payload independently. They have already diverged:
`rechunk`'s omits `author_orgs` and `curated_author_orgs`, so a rechunked paper loses its
affiliation facets and drops out of org-filtered retrieval — silently, with no error anywhere.

**Fix (adjudicated):** one definition, as a **module-level function in `rag/orchestrator.py`**;
`app/rechunk.py` imports it. No new module — a separate file buys no dependency-direction or
testing advantage here, and the anti-drift property comes from single-definition plus a parity
test, not from file location.

**Done when:** `app/rechunk.py` has no payload-construction logic of its own; a test asserts a
rechunked paper's payload equals the ingest-time payload field-for-field.

### RI-4 — resume path assumes the `papers` row exists
**File:** `rag/orchestrator.py:557`

`record = self._document_store.get(paper_id)` is unguarded on the resume branch. If the row is
absent (the delete-ordering window at `:270-272` can produce this), the run dies on an
uncaught exception mid-corpus.

**Fix:** guard for `None` and quarantine the paper with a named reason, matching how the
surrounding branch already handles embed/upsert exhaustion.

**Ships standalone, not folded into D-9.** D-9's catch-all exists for *unknown* exceptions and
deliberately excludes known-bug classes. This is a diagnosed, reproduced condition with an
identified cause; routing it through the generic net would consume circuit-breaker budget for a
shape we understand and blur the diagnosis. D-9 also sits on `T-SEED-combined-fixes`, which the
backlog flags as needing a real rebase — a ten-line fix for a multi-day-run wedge should not queue
behind that.

**Done when:** a test drives the resume branch with the `papers` row deleted and asserts the paper
is quarantined with the named reason and the run continues.

### RI-5 — `SqliteIngestState` requires a migration it does not perform
**File:** `rag/ingest_state_sqlite.py:71`

The `__init__` docstring states as a precondition that `migrate()` has already been applied. Nothing
enforces it. `DocumentStore.__init__` already calls `migrate(db_path)` at `rag/document_store.py:100`
before connecting — the same class of object, the opposite policy.

**Fix:** call `migrate()` in `SqliteIngestState.__init__`, mirroring `DocumentStore`. Migration is
idempotent, so making it unconditional costs nothing and removes an unenforceable prose
precondition. Delete the precondition sentence from the docstring — a claim CI cannot check is
exactly what CONVENTIONS.md §0 warns about.

**Done when:** constructing `SqliteIngestState` against an unmigrated database succeeds.

### RI-6 — dashboard token sidecar: crash window, no pid qualification, no corrupt tolerance
**File:** `app/dashboard/server.py:659-676` and the run-overrides sidecar

Three defects in one file, one ticket to avoid two agents colliding:
- **Crash window:** `token_path.touch()` … `chmod` … `write_text()`. A crash between `touch` and
  `write_text` leaves an empty token file, which the next start reads as `""` — feeding RI-2's
  auth hole from a second direction. Write to a temp file in the same directory, `chmod`, then
  `os.replace` — atomic, so the file either has the full token or does not exist.
- **Pid qualification:** the sidecar does not record which process wrote it, so a stale sidecar
  from a dead run is indistinguishable from a live one.
- **Corrupt tolerance:** a truncated or malformed sidecar currently propagates an exception instead
  of being treated as absent.

**Done when:** a test asserts an empty/short-write token file is not accepted as a valid token; a
malformed sidecar is tolerated as absent; the sidecar carries and is validated against a pid.

### RI-8 — the downloader scan counts *another corpus's* downloader
**File:** `app/dashboard/status.py:568` (`_is_prefetch_argv`), `:616` (`_live_prefetch_pids`)

D-12 fixed argv anchoring: a match now requires `-m app.prefetch_pdfs` as adjacent argv elements.
It does not distinguish *which corpus* the matched process is downloading for. With the Waymo
corpus and the causal corpus both live, each dashboard counts the other's downloader as its own —
inflating `live_pids` and tripping `orphan=True` on a perfectly healthy pair of runs.

**Fix:** qualify the match by the process's working directory, read from `/proc/<pid>/cwd`, against
the dashboard's own `data_dir`. Note the rejected alternative and why: discriminating on "the
resolved config/db path the child loaded" is not observable from outside the process —
`load_config()` closes the file and `SqliteIngestState` opens per-operation, so neither shows up in
`/proc/<pid>/fd` at scan time. `cwd` is stable for the process lifetime and is a real symlink.

Handle the unreadable-`cwd` case (permissions, race, process exit) the way `_read_cmdline_argv`
already handles its own: treat as not-a-match rather than raising.

**Done when:** a test with a fake `/proc` root asserts a prefetch process under a different
`data_dir` is excluded, one under the dashboard's own `data_dir` is included, and an unreadable
`cwd` excludes without raising.

---

## Wave 2 — honesty and hygiene

### RI-9 — `DATA-CONTRACTS.md` out of sync with the shipped shapes
Reconcile the documented shapes against live source. `DATA-CONTRACTS.md` wins shape conflicts by
AGENTS.md, so where the doc and the code disagree the resolution is a deliberate decision per field,
not a blanket rewrite in either direction — record which way each went and why.

### RI-10 — docstrings that describe code that no longer exists, plus absence honesty
Two parts, no logic changes:
- Sweep stale docstrings flagged in review.
- Add the absence-honesty sentences where the system reports results: *k* results are the
  best-available passages, not *k* endorsements of relevance. The system has no relevance floor and
  returns its top *k* regardless of whether anything in the corpus answers the question; the
  docstrings currently let a reader assume otherwise.

A relevance floor was **proposed and rejected** — see RI-M7. Do not add one here.

### RI-11 — compiled bytecode is tracked
`migrations/__pycache__/migrate.cpython-313.pyc` and
`migrations/__pycache__/test_migrate.cpython-313-pytest-9.1.1.pyc` are tracked despite `.gitignore`
listing `__pycache__/` and `*.pyc` — they predate the ignore rule, which does not apply to already
tracked files. `git rm --cached` both. `migrations/.gitkeep` is already staged locally for the
directory-presence case; keep it if the directory must exist, drop it if not.

---

## Wave 3 — frozen paths, one PR, one sign-off

`contracts/` and the CODEOWNERS-gated paths need operator sign-off (T-F7). Four riders travel in a
single PR to pay one gate toll rather than four:
- `CODEOWNERS` += `pyproject.toml`
- delete the exit-5 carve-out
- score-semantics sentence
- `testpaths` fix

Plus, outside the frozen set: eval instrument restoration in `app/retrieval_eval.py`, carrying the
**verbatim** `title_leak` predicate and a `scoring_rule` stamp on every emitted result, so a future
reader can tell which rule produced a number. The hit rule at `:141` is currently a bare
`r.paper_id in question.gold_paper_ids` with no record of the scoring convention in the output.

**Known limitation, to be stated in the report rather than silently carried:** a verbatim predicate
leaves paraphrase-level leaks in the "absent" bucket. That is a measurement floor, not a bug.

---

## Wave 4 — measurement instruments

Build the instruments; running the campaigns is operator work.

| id | instrument |
|---|---|
| RI-M1 | log mining over archived run logs |
| RI-M2 | fabrication audit harness |
| RI-M3 | sparse-retrieval ablation |
| RI-M4 | truncation census |
| RI-M5 | Waymo fixture |
| RI-M6 | groundedness harness — **judge rubric needs operator review before it hardens into a baseline** |
| RI-M7 | score-distribution census |

**RI-M7 exists to settle a rejected proposal.** A relevance floor stays rejected until a census
shows the score distribution over known-answerable vs known-absent queries actually separates. If
it does not separate, no threshold can be chosen honestly, and the absence-honesty sentences of
RI-10 remain the whole answer.

---

## Operator decisions — not agent work

1. **FD-1 figures — time-sensitive.** Figure images from the 12,390-paper parse were written to an
   OS temp directory and are gone. Redirecting `output_dir` to persistent storage is roughly a
   quarter-day, reversible, no schema change. The cheap moment is *before* the next large Waymo
   parse; after that it is a full re-parse.
2. Self-hosted runner + cron.
3. Corpus target conflict: 15k / 30k / 12.4k are all documented as the target in different places.
4. Ruling on reviewer findings R4 and R5.
5. Confirm refuse-to-start as the empty-token policy (RI-2 assumes it).
6. RI-M6 judge rubric sign-off.
