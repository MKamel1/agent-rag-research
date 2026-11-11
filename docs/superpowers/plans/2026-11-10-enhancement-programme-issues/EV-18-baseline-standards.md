Title: EV-18: Run the frozen standards baseline and evaluate the structure gate
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M

## EV-18 -- Run the frozen standards baseline and evaluate the structure gate

**Review cross-reference:** S-16, S-24 gate. **Wave:** W2 first GPU session, measurements only.

**Why.** The standards corpus (119 documents, 35,714 chunks, built with the new bounded chunker) has never been measured by any fixture; the standards protocol freezes a depth decision rule (D-1) and a falsifier (S-1) to be evaluated from this one run, and the review gates the whole standards structure bundle (CQ-12 to CQ-16) on a count taken from it (review S-24).

**Scope.**
- In:
  - Run `run_baseline.sh` exactly as GPU-day runbook step 1c specifies (about 1,198 queries across depth 128/32/64 and fused/dense/sparse arms plus ablations and controls; estimated 1-2 h), detached; BM25 floor and per-stratum tables beside it; evaluate D-1 and S-1 as written.
  - Gate evaluation for CQ-12: count answerable misses whose gold chunk or top-10 chunk has a furniture, numeric or NOTE root, or a split table (mechanical rules from `scripts/chunk_quality_census.py` and RV-2 F-2.5), and state whether the count reaches 5.
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

**Acceptance / falsification criterion.** Verdicts for D-1 and S-1 are mechanical and quoted from the protocol; the structure-gate count is a number with the list of qualifying questions; per-stratum intervals shown with edition/authority marked descriptive; no fixture averaged. Falsified (run not read) if the repeat arm disagrees beyond the envelope or any error occurs.

**Gates / depends on.** Depends on: EV-16, EV-11, EV-15. Operator answers: F3. Gates: EV-19, EV-20, EV-21, EV-22, EP-4, CQ-12, CQ-13, CQ-14, CQ-16, CQ-18, RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 1-2 h GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Longest read-only job of the session; a mid-run foreign GPU grab invalidates it. Mitigation: detached, validity arm, `run_valid`. Rollback: discard.

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.
