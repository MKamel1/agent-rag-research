Title: EP-6: Add CORPORA.md and fix drift rows outside EP-1's files
Labels: wave:1-no-gpu, area:docs, size:S

## EP-6 -- Add CORPORA.md and fix drift rows outside EP-1's files

**Review cross-reference:** S-13. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** the HANDOFF-2026-08-24 and precision-95 plan status-tick rows are archaeology and are cut; CORPORA.md, the no-ingest rule and the closure of Decision 1 stay (a stale doc misleads agents). Not on the baseline path.

**Why.** Agents follow stale docs exactly (CONVENTIONS section 0.6). The review's 23-row drift punch list (RV-6 B.1) splits by file: PROJECT-STATUS, README and AGENTS belong to EP-1 (in progress); the rest has no owner. Which chunker built each corpus is written nowhere (RV-2 F-2.2), the IDF question in DECISIONS-PENDING Decision 1 is stale (the on-disk config of all five collections already carries the IDF modifier; review item 1 'Decision 1'), and the review's rule 'no ingest into a live collection from this branch' has no home.

**Scope.**
- In:
  - New `docs/CORPORA.md`: one row per corpus (five), data-dir role, collection name, document/chunk counts re-derived read-only, and which chunker built it (standards: bounded chunker; main and Waymo: legacy chunker), reusing the five-corpus registry EP-1 added to PROJECT-STATUS instead of restating it differently. State that only the main, standards-GT and focus sets have baselines in this programme; the Motional, Waabi and Waymo corpora get none (plan section 9).
  - State the rule: no ingest into a live collection from this branch until the operator has decided the parked sparse-recompute (CQ-7/EV-22) and re-chunk (CQ-16) questions, because it would mix chunkers and sparse versions (review S-13; item h residual risk 1).
  - Close Decision 1 in `docs/DECISIONS-PENDING-operator.md` with the evidence (IDF modifier present in the on-disk config of all five collections).
  - HISTORICAL banner, in this PR, on any doc this PR supersedes (AGENT-PROCEDURES section B).
- Out (explicitly):
  - `docs/HANDOFF-2026-08-24.md` and the precision-95 plan tick rows (cut).
  - PROJECT-STATUS section rows other than this ticket's own ledger and doc-map entries, README.md, AGENTS.md (EP-1, done). RUNBOOK.md (OP-3, OP-5, OP-7). Any code change; any measurement that needs a service (counts are read-only SQLite).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/CORPORA.md`
- `docs/DECISIONS-PENDING-operator.md`

**Commits** (① is a stub, committed before any real work):
① stub: `docs/CORPORA.md` skeleton with the five rows and column headings, empty cells marked TODO
② corpora table filled from read-only queries; counts stamped with the query date
③ no-ingest rule + chunker provenance column
④ Decision 1 closure with the git evidence

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `grep -n 'Decision 1' docs/DECISIONS-PENDING-operator.md` shows the closure with the config evidence
- Every count in CORPORA.md reproduces with the read-only query printed under the table (`sqlite3 "file:<db>?mode=ro" 'select count(*) from chunks'`)

**Acceptance / falsification criterion.** `docs/CORPORA.md` lists five corpora with path role, collection, counts and chunker; each count was re-derived on the day and the query is shown; the no-ingest rule is present; Decision 1 reads 'closed' with evidence; someone who did not write it can re-run every shown query and match. Falsified if any count differs from a fresh read-only query by more than the ingest drift stated in the doc.

**Gates / depends on.** Depends on: none. Gates: none.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. Docs only. A wrong count misleads an agent; mitigation is the printed query beside each number. Rollback: revert the commit.

**Docs to update in the same PR.** New `docs/CORPORA.md` gets a section 7 doc-map row (AUTHORITATIVE) and a ledger entry. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
