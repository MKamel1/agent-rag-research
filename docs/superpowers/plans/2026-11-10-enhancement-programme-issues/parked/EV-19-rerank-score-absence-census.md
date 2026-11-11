Title: EV-19: Run the reranker-score census on the absent arms
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S, parked
Parked-until: only together with EV-13 (same condition: abstention commissioned and 60+ distinct absent items). Kill criterion: the census closes the RQ-4 gate: RQ-4 dies if the census CI contains 0.5 on two of three sets.

## EV-19 -- Run the reranker-score census on the absent arms

**Review cross-reference:** S-16, S-04. **Wave:** W2 first GPU session, measurements only.

**Parked, do not start.** Parked-until: only together with EV-13 (same condition: abstention commissioned and 60+ distinct absent items). Kill criterion: the census closes the RQ-4 gate: RQ-4 dies if the census CI contains 0.5 on two of three sets.

**Why.** Whether the cross-encoder score can tell 'answerable' from 'absent' was never tested; the earlier 'no floor' verdict measured RRF rank arithmetic (review item a). This is the cheapest read-only job after the baselines and decides whether exposing the score (RQ-4) is worth a contract change.

**Scope.**
- In:
  - Run the EV-13 census tool on: standards absent 9 and partial-absent 13 (separately), main known-absent 24, books partial-absent 5, and the Waymo absent items, each against the answerable top-1 score, about 500 queries (estimate 15-30 min); AUROC with Hanley-McNeil interval and the IQR separation test; explicit `--collection`, `--db-path`, `--blob-dir` for every corpus.
- Out (explicitly):
  - Any threshold or wiring decision (needs 60 or more distinct real absent items; RV-3 F-1.10). Exposing the score (RQ-4).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-rerank-score-census.md`
- `docs/eval-reports/data/<run-date>-rerank-score-census/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule written before the run: gate OPEN for RQ-4 only if the lower CI bound exceeds 0.65 on at least two of three sets; question CLOSED if the interval includes 0.5 on two of three; a floor is 'viable' only at AUROC 0.85 or more
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ raw census output saved
④ report with per-set AUROC, CI and the verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every census command names `--collection` explicitly (a missing flag fails after EV-7)
- Counts of items per arm printed beside each AUROC

**Acceptance / falsification criterion.** Verdict is the pre-registered rule applied mechanically on per-set (not pooled) results, with each set's n printed; partial-absent is reported as its own class. Ceiling note: with 9-24 absent items per set the interval half-width is about 0.1 or more, so 'open' needs a clearly separated signal. Falsified (gate closed) if the interval includes 0.5 on two of the three sets.

**Gates / depends on.** Depends on: EV-13, EV-16, EV-18. Operator answers: F3. Gates: RQ-4 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 15-30 min GPU (estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Small n yields an inconclusive verdict. Mitigation: the rule treats inconclusive as 'gate closed, no change'. Rollback: n/a (read-only).

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
