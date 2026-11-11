Title: OP-4: Take and verify a fresh main-corpus snapshot
Labels: wave:1-no-gpu, area:ops, size:S

## OP-4 -- Take and verify a fresh main-corpus snapshot

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Status (2026-11-10): IN PROGRESS**, executed by the orchestrator outside the programme queue (do not wait for F1; only the off-device copy and deletions need it). It is a consistent SQLite backup of the main corpus database into that corpus's `backups/` directory with an integrity check, a row-count comparison against the manifest and a SHA-256. **The vector store's on-disk data was NOT copied** (service stopped; about 31 GB; operator decision pending). Do not mark this ticket DONE until the operator has decided that copy.

**Why.** The newest main snapshot is from 2026-07-30 (manifest records 11,026 papers; the live database has 12,390) and every backup sits on the same device as the live data, which is 98% full with 91 GB free (review item g, `df -h`). The next write, re-embed or bad migration on that device has no recent restore point. This is the only finding whose downside is unrecoverable.

**Scope.**
- In:
  - Run the existing `python -m app.snapshot` for the main corpus from its data directory, once.
  - Verify the new snapshot read-only: `PRAGMA quick_check` on the snapshot copy opened with `mode=ro`, and `count(*)` of papers and chunks equal to the manifest. Record sizes, timings and `df` before/after in a dated record under `docs/eval-reports/data/`.
- Out (explicitly):
  - Deleting any old snapshot, `.bak` or `.partial` file, and copying to another device (operator question F1; no target exists).
  - Any code change (OP-3 adds the checks to the tool). Any write to `papers.db`.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<run-date>-main-snapshot-record/`

**Commits** (① is a stub, committed before any real work):
① stub: record file with the four acceptance checks as an unchecked list and the abort rule (stop if under 20 GB free)
② snapshot taken; manifest copied into the record
③ verification results: quick_check, counts vs manifest, age
④ free-space and next-step notes (off-device copy is F1)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `sqlite3 "file:<snapshot-db>?mode=ro" "PRAGMA quick_check"` prints `ok`
- `sqlite3 "file:<snapshot-db>?mode=ro" "select count(*) from papers"` equals the manifest `papers`
- `df -h /` before and after is quoted

**Acceptance / falsification criterion.** Newest main snapshot is under 24 hours old at verification time, quick_check is ok, restored paper count equals the manifest, and free space after is still at least 20 GB. Falsified if any of the four fails; then the snapshot is deleted and the failure reported (nothing else is touched).

**Gates / depends on.** Depends on: none. Gates: CQ-7 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched); operator answers: F1 · re-embed: n. Also: operator go-ahead to write about 9 GB (estimate, RV-6) into the main data dir's backups folder on a 98%-full device.

**Model tier and size.** Haiku; S (up to 2 h of agent work). Mechanical work, no judgement calls.

**Risk and rollback.** Disk fills mid-write on a 98%-full device. Mitigation: abort rule before starting; the tool reads the source read-only and writes only the new snapshot. Rollback: delete the new snapshot directory.

**Docs to update in the same PR.** The dated snapshot record is the doc (section 7 doc-map row if a new `docs/*.md` is added); ledger entry only after the operator decides the vector-store data copy. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
