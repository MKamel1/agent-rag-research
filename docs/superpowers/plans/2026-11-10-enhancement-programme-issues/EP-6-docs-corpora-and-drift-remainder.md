Title: EP-6: Add CORPORA.md and fix drift rows outside EP-1's files
Labels: wave:1-no-gpu, area:docs, size:M

## EP-6 -- Add CORPORA.md and fix drift rows outside EP-1's files

**Review cross-reference:** S-13. **Wave:** W1 do now, no GPU.

**Why.** Agents follow stale docs exactly (CONVENTIONS section 0.6). The review's 23-row drift punch list (RV-6 B.1) splits by file: PROJECT-STATUS, README and AGENTS belong to EP-1 (in progress); the rest has no owner. Which chunker built each corpus is written nowhere (RV-2 F-2.2), the IDF question in DECISIONS-PENDING Decision 1 is stale (the on-disk config of all five collections already carries the IDF modifier; review item 1 'Decision 1'), and the review's rule 'no ingest into a live collection from this branch' has no home.

**Scope.**
- In:
  - New `docs/CORPORA.md`: one row per corpus (five), data-dir role, collection name, document/chunk counts re-derived read-only, and which chunker built it (standards: bounded chunker; main and Waymo: legacy chunker), reusing the five-corpus registry EP-1 added to PROJECT-STATUS instead of restating it differently.
  - State the rule: no ingest into a live collection from this branch until the verdicts of EV-22 (sparse recompute) and CQ-11 (bounded re-chunk) are in, because it would mix chunkers and sparse versions (review S-13; item h residual risk 1).
  - Close Decision 1 in `docs/DECISIONS-PENDING-operator.md` with the evidence (IDF modifier present in the on-disk config of all five collections); punch-list rows 8 and 16 (that file and `docs/HANDOFF-2026-08-24.md`); tick the status of each ticket in `docs/superpowers/plans/2026-08-25-precision95-programme.md` per RV-6 B.2 (row 7).
  - HISTORICAL banner, in this PR, on any doc this PR supersedes (AGENT-PROCEDURES section B).
- Out (explicitly):
  - PROJECT-STATUS.md, README.md, AGENTS.md (EP-1). BACKLOG.md rows (EP-3). RUNBOOK.md (EP-7).
  - Any code change; any measurement that needs a service (counts are read-only SQLite).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/CORPORA.md`
- `docs/DECISIONS-PENDING-operator.md`
- `docs/HANDOFF-2026-08-24.md`
- `docs/superpowers/plans/2026-08-25-precision95-programme.md`

**Commits** (① is a stub, committed before any real work):
① stub: `docs/CORPORA.md` skeleton with the five rows and column headings, empty cells marked TODO
② corpora table filled from read-only queries; counts stamped with the query date
③ no-ingest rule + chunker provenance column
④ Decision 1 closure + HANDOFF + precision-95 plan status rows (each row cites the git evidence)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `grep -c 'IN PROGRESS' docs/BACKLOG.md` is NOT this ticket's check (EP-3). Instead: `grep -n 'Decision 1' docs/DECISIONS-PENDING-operator.md` shows the closure with the config evidence
- Every count in CORPORA.md reproduces with the read-only query printed under the table (`sqlite3 "file:<db>?mode=ro" 'select count(*) from chunks'`)

**Acceptance / falsification criterion.** `docs/CORPORA.md` lists five corpora with path role, collection, counts and chunker; each count was re-derived on the day and the query is shown; the no-ingest rule is present; Decision 1 reads 'closed' with evidence; someone who did not write it can re-run every shown query and match. Falsified if any count differs from a fresh read-only query by more than the ingest drift stated in the doc.

**Gates / depends on.** Depends on: none. Gates: EP-7, EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. Docs only. A wrong count misleads an agent; mitigation is the printed query beside each number. Rollback: revert the commit.

**Docs to update in the same PR.** New doc: PROJECT-STATUS section 7 (doc map) row is carried by EP-3. Superseded-doc banners are done in this PR. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
