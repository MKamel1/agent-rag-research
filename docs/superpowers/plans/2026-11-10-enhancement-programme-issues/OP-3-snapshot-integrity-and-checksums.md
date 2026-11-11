Title: OP-3: Add integrity check and checksums to snapshot manifests
Labels: wave:1-no-gpu, area:ops, size:S

## OP-3 -- Add integrity check and checksums to snapshot manifests

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Absorbs EP-7** (part: the backup and restore RUNBOOK section). EP-7's GPU-contention section goes to OP-5 and its containers pointer to OP-7.

**Why.** `app/snapshot.py::backup_sqlite` is correct (read-only source plus VACUUM INTO) but never runs an integrity check and the manifest records no checksum per artifact (RV-6 F-A1, F-A7; review S-01), so a corrupt snapshot looks identical to a good one until the day it is restored.

**Scope.**
- In:
  - Run `PRAGMA quick_check` on the produced SQLite copy and fail the snapshot (non-zero exit, snapshot marked incomplete) if it is not `ok`.
  - Write sha256 per artifact into the manifest; add a verify mode (or reuse an existing one) that recomputes them and compares `count(*)` with the manifest.
  - `docs/RUNBOOK.md`: backup and restore section (what `app.snapshot` writes, how to verify with `quick_check` and the manifest checksums, a restore drill on a scratch copy, retention, the off-device gap named as open question F1). Commands run or `--help`-checked and quoted, not guessed.
- Out (explicitly):
  - The guard against a nonexistent data dir (OP-6). Taking a snapshot (OP-4). Off-device copy (F1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/snapshot.py`
- `app/test_snapshot.py`
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the manifest fields (`quick_check`, `sha256` per artifact) and the failure rule
② failing tests: corrupt copy fails; manifest has sha256; verify detects a flipped byte
③ implementation to green
④ docstring and `--help` text brought up to date
⑤ RUNBOOK backup and restore section

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/snapshot.py app/test_snapshot.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_snapshot.py -o addopts="--disable-socket"`
- Mutation proof (CONVENTIONS section 14): revert the quick_check call and watch the corruption test fail
- `grep -n 'quick_check' docs/RUNBOOK.md` shows the verification step; every command in the section was run or `--help`-checked and quoted in the PR

**Acceptance / falsification criterion.** A deliberately corrupted SQLite copy makes the snapshot exit non-zero and not write a complete manifest; a flipped byte in an artifact fails verify; existing snapshot tests stay green. Falsified if either test passes with the check removed.

**Gates / depends on.** Depends on: none. Gates: OP-6.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A verify mode changes the manifest shape: old manifests lack checksums. Mitigation: verify treats a missing checksum as 'unverifiable', not 'ok'. Rollback: revert.

**Docs to update in the same PR.** Section 2: entry-point row for any new snapshot flag; `docs/RUNBOOK.md` backup and restore section is part of this PR. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
