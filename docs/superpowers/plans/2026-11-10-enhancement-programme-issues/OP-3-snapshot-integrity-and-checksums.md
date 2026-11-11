Title: OP-3: Add integrity check and checksums to snapshot manifests
Labels: wave:1-no-gpu, area:ops, size:S

## OP-3 -- Add integrity check and checksums to snapshot manifests

**Review cross-reference:** S-01. **Wave:** W1 do now, no GPU.

**Why.** `app/snapshot.py::backup_sqlite` is correct (read-only source plus VACUUM INTO) but never runs an integrity check and the manifest records no checksum per artifact (RV-6 F-A1, F-A7; review S-01), so a corrupt snapshot looks identical to a good one until the day it is restored.

**Scope.**
- In:
  - Run `PRAGMA quick_check` on the produced SQLite copy and fail the snapshot (non-zero exit, snapshot marked incomplete) if it is not `ok`.
  - Write sha256 per artifact into the manifest; add a verify mode (or reuse an existing one) that recomputes them and compares `count(*)` with the manifest.
- Out (explicitly):
  - The guard against a nonexistent data dir (OP-6). Taking a snapshot (OP-4). Off-device copy (F1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/snapshot.py`
- `app/test_snapshot.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the manifest fields (`quick_check`, `sha256` per artifact) and the failure rule
② failing tests: corrupt copy fails; manifest has sha256; verify detects a flipped byte
③ implementation to green
④ docstring and `--help` text brought up to date

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/snapshot.py app/test_snapshot.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_snapshot.py -o addopts="--disable-socket"`
- Mutation proof (CONVENTIONS section 14): revert the quick_check call and watch the corruption test fail

**Acceptance / falsification criterion.** A deliberately corrupted SQLite copy makes the snapshot exit non-zero and not write a complete manifest; a flipped byte in an artifact fails verify; existing snapshot tests stay green. Falsified if either test passes with the check removed.

**Gates / depends on.** Depends on: none. Gates: EP-7, EP-3, OP-6.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A verify mode changes the manifest shape: old manifests lack checksums. Mitigation: verify treats a missing checksum as 'unverifiable', not 'ok'. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 entry-point row for any new flag (via EP-3); RUNBOOK via EP-7. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
