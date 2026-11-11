Title: EV-17: Run the frozen topic-focus baseline
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S

## EV-17 -- Run the frozen topic-focus baseline

**Review cross-reference:** S-16. **Wave:** W2 first GPU session, measurements only.

**Why.** Whether off-topic papers enter the top ten for realistic questions is unmeasured: 37.4% of main-corpus papers are off-topic (labels audited at weighted kappa 0.90) and nothing has ever measured how often they surface in answers (review section 4 'Unknown'). The frozen topic-focus protocol defines the instrument; its fixture hash is null until authoring ends.

**Scope.**
- In:
  - Run the `focus` mode of the main baseline script (about 50 queries, estimated 2-5 min) once EV-4b (the repair of EV-4's focus fixture, which found 18 of 26 collision questions without their collision term and 6 of 10 weak absent items) has re-frozen the focus fixture hash in the hash file; the run uses the same `baseline_commit` as EV-16 (recorded in its MANIFEST); report off-topic share in the top 10 with its interval, `offtopic-legit` paper recall, and the control arms, per the frozen protocol.
- Out (explicitly):
  - Choosing the materiality bar (operator question F6: the report states the number, the operator sets the bar). Any demotion arm (RQ-3).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-focus-baseline.md`
- `docs/eval-reports/data/<run-date>-focus-baseline/`
- `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton, the frozen metrics and the refusal rule (the script refuses while the hash is null)
② MANIFEST committed at launch
③ raw report copied; errors and validity shown
④ report with off-topic share, interval and the bar left blank for the operator

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `sha256sum` of the focus fixture equals the hash file entry (the script checks it)
- `n_errors` 0, `run_valid` true

**Acceptance / falsification criterion.** Report states off-topic share in the top 10 on the focus set with a Wilson interval, per question dimension, never averaged with the other sets, with the control arms' values beside it; its fixture hash matches EV-4b's frozen hash and its MANIFEST `baseline_commit` equals EV-16's. The ceiling and floor arithmetic of the protocol are printed with each metric. Falsified (not read) if the hash was null at launch or any error occurred.

**Gates / depends on.** Depends on: EV-16 (GPU-serial order and the shared baseline commit). In-progress tickets on other branches (merge order or inputs): EV-4b. Operator answers: F3. Gates: RQ-2 (parked), RQ-3 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); focus fixture authoring finished and hash frozen (EV-4b).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Fixture hash still null: the script refuses to run, which is the intended guard. Rollback: discard run directory.

**Docs to update in the same PR.** The dated focus baseline report is the doc (section 7 doc-map row); the off-topic share goes to section 6 as an open measured number. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
