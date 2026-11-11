Title: EV-18: Run the frozen standards baseline and evaluate the structure gate
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M

## EV-18 -- Run the frozen standards baseline and evaluate the structure gate

**Review cross-reference:** S-16, S-24 gate. **Wave:** W2 first GPU session, measurements only.

**Minimizer note.** The gate count here is the single trigger for parked CQ-8, CQ-12, CQ-13, CQ-14 and CQ-16 (count of 5 or more); the authority-stratum result is the trigger for parked CQ-19. Report both explicitly.

**Why.** The standards corpus (119 documents, 35,714 chunks, built with the new bounded chunker) has never been measured by any fixture; the standards protocol freezes a depth decision rule (D-1) and a falsifier (S-1) to be evaluated from this one run, and the review gates the whole standards structure bundle (CQ-12 to CQ-16) on a count taken from it (review S-24).

**Scope.**
- In:
  - Run `run_baseline.sh` exactly as GPU-day runbook step 1c specifies (about 1,198 queries across depth 128/32/64 and fused/dense/sparse arms plus ablations and controls; estimated 1-2 h), detached; BM25 floor and per-stratum tables beside it; evaluate D-1 and S-1 as written.
  - Gate evaluation for CQ-12: count answerable misses whose gold chunk or top-10 chunk has a furniture, numeric or NOTE root, or a split table (mechanical rules from `scripts/chunk_quality_census.py` and RV-2 F-2.5), and state whether the count reaches 5.
  - Run at EV-16's `baseline_commit` (recorded in the MANIFEST). Every per-question row must carry `retrieved_chunk_ids` (EV-9); the gate count is printed together with the list of qualifying questions.
- Out (explicitly):
  - Changing the standards depth default (that is rule D-1's verdict, a sign-off, not an edit here). Any structure fix (CQ-12 to CQ-16).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-standards-baseline.md`
- `docs/eval-reports/data/<run-date>-standards-baseline/`
- `docs/eval-reports/data/2026-11-10-standards-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with rules D-1 and S-1 quoted verbatim and the gate definition for CQ-12
② MANIFEST committed at launch
③ raw reports + validity (the `depth128-fused-repeat` arm is the validity gate)
④ D-1 / S-1 verdicts and the structure-gate count
⑤ report

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Run script prints `check-hash` and `check-points` passes
- `depth128-fused-repeat` agrees with `depth128-fused` within the protocol's jitter envelope
- `n_errors` 0, `run_valid` true

**Acceptance / falsification criterion.** Verdicts for D-1 and S-1 are mechanical and quoted from the protocol; the structure-gate count is a number with the list of qualifying questions and the per-row chunk ids they rest on; the MANIFEST `baseline_commit` equals EV-16's; per-stratum intervals shown with edition/authority marked descriptive; no fixture averaged. Falsified (run not read) if the repeat arm disagrees beyond the envelope or any error occurs.

**Gates / depends on.** Depends on: EV-16 (GPU-serial order and the shared baseline commit), EV-9 (chunk ids in rows), EV-11, EV-15. Operator answers: F3. Gates: CQ-19 (parked), CQ-8 (parked), RQ-1 (parked), EV-20, EV-19 (parked), EV-21 (parked), EV-22 (parked), CQ-12 (parked), CQ-13 (parked), CQ-14 (parked), CQ-16 (parked), CQ-18 (parked), RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 1-2 h GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Longest read-only job of the session; a mid-run foreign GPU grab invalidates it. Mitigation: detached, validity arm, `run_valid`. Rollback: discard.

**Docs to update in the same PR.** The dated standards baseline report is the doc (section 7 doc-map row); the D-1 and S-1 verdicts go to section 5 or 6. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
