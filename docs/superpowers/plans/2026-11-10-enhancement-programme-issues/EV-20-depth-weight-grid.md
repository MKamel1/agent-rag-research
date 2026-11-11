Title: EV-20: Run the per-corpus depth and dense-weight grid
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M

## EV-20 -- Run the per-corpus depth and dense-weight grid

**Review cross-reference:** S-19. **Wave:** W2 first GPU session, measurements only.

**Why.** Rerank depth and dense weight differ per corpus (standards depth 128; Waymo weight 0.7; others 32 and 0.5) with no recorded reason, and the existing measurements are single-question effects with the sign flipping between fixtures (RV-1 F-1.5, review S-19). The evidence that the settings matter is weak; the evidence that they differ for a reason is absent.

**Scope.**
- In:
  - The GPU-day runbook step 3 grid: depth {32, 128} by dense weight {0.5, 0.7, 1.0} per corpus on its own fixtures, arms already measured in the baselines not repeated (about 1,200 queries, estimate 40-90 min), paired flips via `scripts/nb_xp_deeppool_tables.py` with its jitter envelope.
  - Rule G-1 as already frozen in the runbook: a candidate arm is believed only with net member-passage hit@10 of at least +3 on that corpus's own fixture(s), wins:losses at least 3:1, no gating stratum (n at least 10) losing more than 1, and the same sign on the title-ablated arm. The standards depth question is already decided by D-1 and is not reopened.
- Out (explicitly):
  - Changing any default (a verdict here is a recommendation; a default change needs sign-off and goes through RIDER-1 or a config edit the operator approves). The review's fallback 'otherwise set everything to 32/0.5' is NOT part of G-1: see risk.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-depth-weight-grid.md`
- `docs/eval-reports/data/<run-date>-depth-weight-grid/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton quoting rule G-1 and stating the unresolved difference with the review (see risk)
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ arms run one at a time (cheapest first); MANIFEST per arm
④ flip tables per corpus with the jitter envelope
⑤ report: verdict per corpus

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Each arm names `--collection`, `--db-path`, `--blob-dir` explicitly
- Both fixtures (or all of a corpus's fixtures) are reported separately, never averaged

**Acceptance / falsification criterion.** Per corpus: the flip table and the G-1 verdict; no default changes unless G-1 holds; the ceiling for 'net +3' is shown per fixture (n answerable). Falsified if the baseline arm repeated here differs from the EV-16/EV-18 arm beyond the jitter envelope (then the grid is not interpretable).

**Gates / depends on.** Depends on: EV-16, EV-18, EV-19. Operator answers: F3. Gates: EV-21, EP-4, RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 40-90 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** The review (S-19) says that if no arm wins, reset all corpora to 32/0.5; the runbook's frozen rule G-1 says defaults stay. The EV-20 stub commit must state which applies; default is G-1 as frozen, because resetting is a config change needing sign-off and a frozen rule changes only by dated addendum. Rollback: n/a (read-only).

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.
