Title: EP-7: Add backup, container and GPU-contention sections to RUNBOOK
Labels: wave:1-no-gpu, area:docs, area:ops, size:S

## EP-7 -- Add backup, container and GPU-contention sections to RUNBOOK

**Review cross-reference:** S-13, S-01, S-06, S-12. **Wave:** W1 do now, no GPU.

**Why.** `docs/RUNBOOK.md` has no backup or restore section, no container definitions and no GPU-contention section (RV-6 punch row 22), yet the system has no backup newer than 2026-07-30 and a foreign process holds the GPU today (review items g, S-06). A second-corpus recipe also omits that `app.init_config` writes a private `gpu_lock_path` that must be edited to the shared lock.

**Scope.**
- In:
  - Three sections: (1) backup and restore (what `app.snapshot` writes, how to verify with `quick_check` and the manifest checksums, restore drill, retention, the off-device gap), (2) containers (point to `ops/docker-compose.yml`, the pinned Qdrant version, the rule that nothing is restarted without a snapshot), (3) GPU contention (holder file, doctor's foreign-process listing, the 20 s query-path timeout, cheapest-first ordering rule from LESSONS section 9.1).
  - Punch row 22: the shared-lock note in 'Running a second corpus'. Add a pointer to `docs/CORPORA.md` and the no-ingest rule.
- Out (explicitly):
  - Writing the code those sections describe (OP-3, OP-5, OP-7 own it). Deleting any backup (operator question F1).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/RUNBOOK.md`

**Commits** (① is a stub, committed before any real work):
① stub: three empty section headings with one-line intent each
② backup/restore section, commands copied from the merged OP-3/OP-4 output, not guessed
③ container + GPU-contention sections, commands verified against merged OP-5/OP-7
④ punch row 22 + CORPORA pointer

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command in the new sections was run (or `--help`-checked) in the worktree and the output is quoted in the PR description
- `grep -n 'gpu_lock_path' docs/RUNBOOK.md` shows the second-corpus warning

**Acceptance / falsification criterion.** A cold agent can, from RUNBOOK alone, (a) take and verify a snapshot, (b) name who holds the GPU, (c) recreate the four containers from the tracked compose file. Checked by a reviewer who did not write it following each section once on a read-only or dry-run basis. Falsified if any quoted command fails or prints different flags.

**Gates / depends on.** Depends on: OP-3, OP-4, OP-5, OP-7, EP-6. Gates: EP-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. A documented command that has since changed misleads; mitigation: commands verified at merge time. Rollback: revert.

**Docs to update in the same PR.** RUNBOOK is itself the doc; PROJECT-STATUS doc-map row carried by EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
