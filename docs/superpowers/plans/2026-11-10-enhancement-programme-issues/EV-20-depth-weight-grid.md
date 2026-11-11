Title: EV-20: Run the depth grid (32 versus 128) on papers and books, only if headroom allows
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S

## EV-20 -- Run the depth grid (32 versus 128) on papers and books, only if headroom allows

**Review cross-reference:** S-19. **Wave:** W2 first GPU session, measurements only.

**Cut by minimizer:** 1,200 queries and 40-90 min of GPU against weak, sign-flipping prior evidence is cut to depth 32 versus 128 at weight 0.5 on the papers and books sets only; standards (depth already decided by D-1 from EV-18's depth arms) and Waymo drop; the weight arms wait. It runs only if that set's passage hit@10 in EV-16 leaves at least 6 items of headroom. The EV-19 -> EV-20 edge is cut (EV-19 is parked).

**Why.** Rerank depth and dense weight differ per corpus (standards depth 128; Waymo weight 0.7; others 32 and 0.5) with no recorded reason, and the existing measurements are single-question effects with the sign flipping between fixtures (RV-1 F-1.5, review S-19). The evidence that the settings matter is weak; the evidence that they differ for a reason is absent.

**Scope.**
- In:
  - Precondition (stated in commit 1, checked from EV-16's report): a set is run only if its passage hit@10 leaves at least 6 items of headroom (answerable items minus member-passage hits at 10); if neither set does, close the ticket by that gate with the numbers.
  - Arms: depth 32 versus depth 128 at dense weight 0.5 on the papers-passage and causal-books sets, each on its own fixture; arms already measured in the baselines are not repeated; paired flips via `scripts/nb_xp_deeppool_tables.py` with its jitter envelope.
  - Rule G-1 as already frozen in the runbook: a candidate arm is believed only with net member-passage hit@10 of at least +3 on that corpus's own fixture, wins:losses at least 3:1, no gating stratum (n at least 10) losing more than 1, and the same sign on the title-ablated arm.
- Out (explicitly):
  - Standards and Waymo grids; dense-weight arms 0.7 and 1.0 (they wait for a reason to run them). Reopening the standards depth question (D-1 decides it).
  - Changing any default (a verdict here is a recommendation; a default change needs sign-off and goes through RIDER-1 or a config edit the operator approves). The review's fallback 'otherwise set everything to 32/0.5' is NOT part of G-1: see risk.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-depth-weight-grid.md`
- `docs/eval-reports/data/<run-date>-depth-weight-grid/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton quoting rule G-1, the 6-item headroom precondition with the numbers from EV-16, and the unresolved difference with the review (see risk); pre-registered, no metric, threshold or fixture changes afterwards (dated addendum only)
② arms run one at a time (cheapest first); MANIFEST per arm, each recording the baseline commit SHA
③ flip tables per set with the jitter envelope
④ report: verdict per set (or closed by the headroom gate)

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Each arm names `--collection`, `--db-path`, `--blob-dir` explicitly
- Both fixtures (or all of a corpus's fixtures) are reported separately, never averaged

**Acceptance / falsification criterion.** Per set (papers, books): the flip table and the G-1 verdict (or the headroom gate that closed it); no default changes unless G-1 holds; the ceiling for 'net +3' is shown per fixture (n answerable). Falsified if the baseline arm repeated here differs from the EV-16/EV-18 arm beyond the jitter envelope (then the grid is not interpretable).

**Gates / depends on.** Depends on: EV-16, EV-18. Operator answers: F3. Gates: none.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); GPU time is not estimated here (a fraction of the original 40-90 min grid; the first run replaces any estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The review (S-19) says that if no arm wins, reset all corpora to 32/0.5; the runbook's frozen rule G-1 says defaults stay. The EV-20 stub commit must state which applies; default is G-1 as frozen, because resetting is a config change needing sign-off and a frozen rule changes only by dated addendum. Rollback: n/a (read-only).

**Docs to update in the same PR.** The grid report is the doc (section 7 doc-map row); a verdict goes to section 5 (tried) or 6 (open). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
