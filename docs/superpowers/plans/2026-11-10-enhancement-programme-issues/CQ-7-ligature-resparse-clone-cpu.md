Title: CQ-7: Build a ligature-repaired clone of the main collection on CPU
Labels: wave:1-no-gpu, area:corpus, needs-services, size:M

## CQ-7 -- Build a ligature-repaired clone of the main collection on CPU

**Review cross-reference:** S-17. **Wave:** W1 do now, no GPU.

**Why.** CQ-1 repairs ligature damage in the sparse arm but is deliberately not applied to any index, and CQ-2 added `app.resparse` to recompute sparse vectors without re-embedding. The A/B (EV-22) needs a repaired clone to exist, and the whole preparation is CPU-only, so it can run while the GPU is held by another process (GPU-day runbook step 5.1). About 35% of main-corpus chunks change; resparse time is unmeasured.

**Scope.**
- In:
  - Clone the main collection with `VectorIndex.clone_points_into` into a new scratch collection, then `app.resparse --collection <scratch> --target-is-clone --clone-of <live> --apply` after a dry run, following `docs/eval-reports/2026-11-10-cq2-index-maintenance.md`. Record measured resparse time and the sparse-staleness sample before and after.
- Out (explicitly):
  - Touching the live collection (read-only source only). The A/B (EV-22). Any BM25 weighting (CQ-17). Deleting the clone: EV-22 does that when done.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<run-date>-ligature-clone/`

**Commits** (① is a stub, committed before any real work):
① stub: record skeleton with the dry-run and apply checklists and the abort rule (under 20 GB free)
② dry run output saved
③ apply on the clone; times and counts recorded; staleness sample before/after
④ handover note for EV-22 (collection name, git revision of the resparse code)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `df -h /` before the clone
- `conda run -n agent-rag-research python -m app.resparse --help` shows `--collection` required and `--target-is-clone`
- Post-apply sparse-staleness sample reports the stale share near zero on the clone and unchanged on the live collection

**Acceptance / falsification criterion.** Scratch collection holds the same point count as the live one; resparse applied only to the scratch collection; staleness sample on the scratch shows the repaired vectors, on the live shows unchanged. Falsified if the live collection's point count or sampled sparse vectors changed at all.

**Gates / depends on.** Depends on: OP-4. Operator answers: F2. Gates: EP-3, EV-22.

**Needs.** GPU: n · services up: vector store (CPU container) up; no GPU services · operator sign-off: n (no protected path is touched); operator answers: F2 · re-embed: n. Also: vector store start approved (F2); 6-8 GB free for the clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Applying resparse to the live collection by mistake (the documented CQ-1 deployment hazard). Mitigation: `--target-is-clone` guard, explicit `--collection` on every command, live collection read-only. Rollback: delete the scratch collection.

**Docs to update in the same PR.** CQ-2 operating note is the reference; record is the doc; PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
