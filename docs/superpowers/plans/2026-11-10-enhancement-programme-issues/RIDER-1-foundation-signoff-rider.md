Title: RIDER-1: Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step)
Labels: wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M

## RIDER-1 -- Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step)

**Review cross-reference:** review (D), RV-5 F-5.6, RV-3 F-1.11, RV-6 F-A5, RV-1 F-1.10. **Wave:** W4 rider and what it unblocks.

**Cut by minimizer:** items 3 (`rerank_score` note) and 4 (fake imports `sparse_tokens`) die with parked RQ-4 and RQ-5; item 1 and conditional item 7 exist only if an adopted result needs them. Kept: item 5 (promote the ground-truth sets to `fixtures/eval/` with the invariants test, the drift guard), item 2 (reject the dead `relevance_filter`) and item 6 (ruff step, after F4). Items for adopted results are added by a plan amendment when the result exists.

**Why.** Several adopted changes can only land on protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `rag/fakes/`, `fixtures/`, `.github/`), and every unrelated protected-path PR pays the same sign-off toll; batching them into one PR pays it once (`docs/AGENT-OPERATIONS-LESSONS.md` section 6.3). It is raised only after the baselines so no start-up or validation change precedes the frozen baseline commit; items whose source tickets are parked are absent.

**Scope.**
- In:
  - (2) `relevance_filter="embedding"` fails validation until a gate exists (dead lever, RV-5 F-5.6).
  - (5) Promote the three ground-truth sets to `fixtures/eval/` with one parametrised invariants test (unique ids, strata vocabulary, no gold on absent items, 6-word rule, excerpt verbatim in the live database with a skip when absent) and the SHA-256 in each set's metadata (RV-3 F-1.11), after the hash lock.
  - (6) `.github/`: a `ruff` step in CI and the nightly real-adapter workflow labelled manual-only (RV-6 F-A5).
- Out (explicitly):
  - Items 1, 3, 4 and conditional item 7 (their sources are parked or cut; each returns only by a plan amendment citing an ADOPT verdict). The `chunker_id` migration (not doing). Any logic change beyond the listed edits. Pushing to the default branch or merging (human only).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `contracts/config.py`
- `rag/config.py`
- `fixtures/eval/`
- `.github/workflows/ci.yml`
- `.github/workflows/nightly-real-adapters.yml`

**Commits** (① is a stub, committed before any real work):
① stub: PR description draft listing each item, its source and the operator decision it needs; empty diff
② item (5) (promotion and invariants test)
③ item (2) (validation of the dead lever)
④ item (6)
⑤ local enforcement transcript with the `foundation-change` label noted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check contracts/config.py rag/config.py`
- Mutation proof for the invariants test: edit one question in a copy and watch it fail

**Acceptance / falsification criterion.** One PR only; every protected-path edit is traceable to a listed item; the invariants test passes on the three promoted sets and fails when one question is altered; the PR carries the `foundation-change` label and waits for the operator's merge. Falsified if the PR touches any protected path not listed.

**Gates / depends on.** Depends on: EV-11 (hash lock before promotion), EV-18 (pre-baseline rule: no validation change before the last baseline). Operator answers: F4. Gates: RQ-4 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: y: this ticket IS the sign-off request; the operator merges (never an agent); operator answers: F4, F7 · re-embed: n. Also: operator sign-off and merge; push of the local commits so CI can judge them (F4).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Item 2 changes config validation (a start-up behaviour), so the ticket is sequenced after the last baseline (pre-baseline rule, plan section 4). A broad rider is slow to review; this one is small. Rollback: revert the merge (single PR).

**Docs to update in the same PR.** DATA-CONTRACTS is untouched by the kept items; the PR description is the record. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
