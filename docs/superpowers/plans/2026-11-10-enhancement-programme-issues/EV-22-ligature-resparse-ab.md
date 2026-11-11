Title: EV-22: Run the ligature-repair A/B on the repaired clone
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M

## EV-22 -- Run the ligature-repair A/B on the repaired clone

**Review cross-reference:** S-17. **Wave:** W2 first GPU session, measurements only.

**Why.** CQ-1's sparse-arm ligature repair is merged but unmeasured: 32.42% of main chunks (129,566) carry damaged ligatures and 57% of the papers-set gold chunks (35 of 61) and 39% of books (27 of 69) are damaged, so the effect can be stratified (RV-3 F-1.14, review S-17). Review item h shows the merged query-side repair changes none of 1,217 stored queries.

**Scope.**
- In:
  - Runbook step 5: arm A is the live collection at the baseline revision; arm B is the repaired clone from CQ-7 (about 345 queries, estimate 12-25 min GPU); stratify every set by damaged versus clean gold (census regexes in `docs/eval-reports/data/2026-11-10-ligature-census/results.json`); delete the clone afterwards.
  - First, on CPU, recheck item h for the three new sets' questions: if repair changes any of their query strings, arm A must instead run from the pre-CQ-1 checkout.
- Out (explicitly):
  - Dense-side repair and any 129k re-embed (explicitly not doing; reopened only if this A/B shows a sparse gain and dense-only misses on damaged gold). Applying resparse to the live collection.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-ligature-ab.md`
- `docs/eval-reports/data/<run-date>-ligature-ab/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule: net gain on damaged-gold items and no loss of more than 1 on any set, both strata reported
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ CPU recheck of query-string changes; arm choice recorded
④ arms A and B run; MANIFEST per arm
⑤ stratified flip tables and verdict; clone deleted and recorded

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection` (live for arm A, clone for arm B)
- Point counts of live and clone are equal before the run

**Acceptance / falsification criterion.** Verdict applies the pre-registered rule per set, with damaged and clean strata separate (35/26 on papers, 27/42 on books); the ceiling is stated (a gain can only occur on damaged-gold items; with about 60 damaged items only an effect of about 10 net items is detectable per RV-3). Falsified if arm A differs from the EV-16 run beyond the jitter envelope.

**Gates / depends on.** Depends on: CQ-7, EV-16, EV-18, EV-21. Operator answers: F3. Gates: EP-4, RQ-3, CQ-17, CQ-18.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); the repaired clone exists (CQ-7); about 12-25 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Serving from the clone with the wrong code revision. Mitigation: manifest records revisions; arm B uses the CQ-1 code by design. Rollback: delete the clone.

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.
