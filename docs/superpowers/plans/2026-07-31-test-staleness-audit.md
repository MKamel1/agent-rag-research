# Test Staleness Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reviewed inventory of stale, vacuous, or superseded tests across the suite — as a report the operator approves before any test is changed.

**Architecture:** Read-only. Four parallel shards, one per area of the codebase, each writing a findings file. The coordinator merges them into one report. **No test file is modified by this plan.**

**Tech Stack:** Python 3.12, pytest, ripgrep.

## Global Constraints

- Backlog item **D-4** (`docs/BACKLOG.md`); deliverable 3 of `docs/superpowers/specs/2026-07-30-dashboard-dropin-and-usage-design.md` §4.
- **READ-ONLY. Do not modify, delete, or add any test.** The output is a report. A test that looks redundant may be the only thing catching a real regression; deciding that is the operator's call, and this plan exists to give them the evidence.
- Do not modify any source file either. The only file an agent writes is its own findings file under `/home/omar/.claude/jobs/f0255e85/tmp/`.
- **Never** write to `/home/omar/ai-projects/research-system-rag-data/papers.db`. No ingest, rechunk, delete, snapshot, or corpus run.
- Never `git stash`, never commit, never open a PR, never merge.
- Environment for any pytest invocation: `source ~/miniconda3/etc/profile.d/conda.sh && conda activate agent-rag-research && <cmd>` — chained in ONE shell call.
- Report real exit codes: `rc=$?` on the line **immediately** after the command, never after `echo`, never through a pipe.
- Do not spawn subagents.

## Scale (measured 2026-07-31)

**123 test files, 1,432 test functions.** Too large for one agent's context, which is why this shards. Exclude `.worktrees/` and `.claude/worktrees/` — those are stale copies of other branches, not the live suite.

## Finding categories

Every finding is exactly one of these:

| category | means |
|---|---|
| `asserts-nothing` | runs code but makes no meaningful assertion (no `assert`, or only `assert True` / `assert x is not None` on something that cannot be None) |
| `superseded` | asserts behavior a later change intentionally replaced — the test passes but encodes the old contract |
| `stale-constant` | pinned to a value the 2026-07 experiments moved (see below) |
| `dead` | exercises a code path, flag, or module that no longer exists |
| `over-mocked` | fakes so much of the system under test that a real regression could not fail it |

**Known moved constants** — flag any test still pinned to the superseded side:

- `_MAX_HITS_PER_PAPER` — was a flat `3`; now `3` unscoped and `_MAX_HITS_PER_PAPER_SCOPED = 50` when `filters.doc_type` is set (`rag/retriever.py`).
- **Sparse IDF** — the production collection was created without the IDF modifier and now has it. Tests asserting IDF-off scoring behavior are stale.
- **Book eval set** — `fixtures/eval/eval_book_questions.json` went from 40 questions to **115** (23 per book × 5). A test pinned to 40 is stale.
- **`SearchFilters`** — gained `paper_id` (PR #205). Tests asserting the old field list are stale.
- **Dashboard** — `_static_config` now takes `data_dir` (PR #206); `run_manifest.json` gained `mode="drop_in"` and `pending_drop_in` (PR #208); `/api/status` gained `drop_in`, `usage`, and `by_doc_type` blocks (PRs #208/#209/#210).

## Finding format

Each finding is one row. Do not editorialize beyond the risk note.

```
| file:line | test_name | category | what it does now | proposed action | risk if changed |
```

`risk if changed` is the important column and must never be "none": state what would stop being caught if the test were altered or deleted. If you genuinely cannot identify a risk, that itself is the finding — say so.

---

### Shard assignments

Each shard is one dispatched agent, run in parallel. All four are read-only, touch disjoint files, and write to their own output path.

| shard | scope | output file |
|---|---|---|
| **A** | `rag/` — retriever, orchestrator, vector_index, embedder, reranker, summarizer, parser, harvester, chunker, book_summarizer, contextual_header, ingest_state, fakes' own tests | `/home/omar/.claude/jobs/f0255e85/tmp/audit-A-rag.md` |
| **B** | `app/` top level only, NOT `app/dashboard/` — assembly, build_corpus, ingest, ingest_local, serve, usage_log, snapshot, rechunk, telemetry, prefetch_pdfs, retrieval_eval, and the experiment scripts | `/home/omar/.claude/jobs/f0255e85/tmp/audit-B-app.md` |
| **C** | `app/dashboard/` — controller, server, status, conftest | `/home/omar/.claude/jobs/f0255e85/tmp/audit-C-dashboard.md` |
| **D** | `contracts/`, `fixtures/`, `ci/`, plus repo-root and `migrations/` tests | `/home/omar/.claude/jobs/f0255e85/tmp/audit-D-foundation.md` |

Shard C is the highest-yield: `app/dashboard/` was rewritten across four PRs in two days, so it has the most opportunity for tests that were extended rather than re-thought.

### Per-shard steps

- [ ] **Step 1: Enumerate the shard's test files**

```bash
find <shard paths> -name "test_*.py" -not -path "*/.worktrees/*" -not -path "*/worktrees/*" | sort
rc=$?
```

- [ ] **Step 2: Mechanical first pass**

Cheap greps that find candidates without reading every line. These are leads, not findings — confirm each by reading the test.

```bash
# tests with no assert at all
for f in <files>; do
  awk '/^def test_|^    def test_/{name=$2; body=""} {body=body$0"\n"}
       /^def |^    def /{if(name && body !~ /assert|pytest.raises|self\.assert/) print FILENAME": "name; name=""}' "$f"
done
rc=$?
```

```bash
# vacuous assertions
rg -n "assert True|assert 1|assert .* is not None$|assert len\(.*\) >= 0" --glob "test_*.py" <shard paths>
rc=$?
```

```bash
# stale constants
rg -n "_MAX_HITS_PER_PAPER|== 40\b|questions.*40|idf|IDF|doc_type|paper_id" --glob "test_*.py" <shard paths>
rc=$?
```

- [ ] **Step 3: Read and confirm**

Read each candidate in context. A test with no `assert` may still be a valid smoke test that asserts by not raising — say so and do **not** flag it. A test using a fake is not automatically `over-mocked`; it qualifies only when the fake is so complete that the real code under test could break without failing it.

- [ ] **Step 4: Write the findings file**

Use the table format above, ordered by category then file. Head the file with: the shard letter, the number of test files and test functions examined, and a one-paragraph summary of the overall health of that area.

**If a shard finds nothing, say so explicitly.** An empty findings file is a legitimate and useful result; do not invent findings to appear productive.

- [ ] **Step 5: Report**

Return only: shard letter, files examined, test functions examined, finding count by category, and the output file path. Do not paste the findings into the reply — they are in the file.

---

### Coordinator: merge and hand off

- [ ] **Step 1:** Read all four findings files.
- [ ] **Step 2:** Merge into `docs/TEST-AUDIT-2026-07-31.md`: an executive summary (total examined, total findings by category), then one section per shard, then a **proposed fix list ranked by risk** — lowest-risk mechanical fixes first, anything touching a regression guard last and explicitly flagged.
- [ ] **Step 3:** Commit the report to `main`. It is a document, not a code change.
- [ ] **Step 4:** Present the fix list to the operator. **Do not dispatch any fix until they approve it.** That approval gate is the entire point of splitting audit from fix.

## Report contract

The coordinator reports: total files and test functions examined, finding counts by category, the report path, and the top five findings by risk — with an explicit note on any finding where changing the test would reduce real regression coverage.
