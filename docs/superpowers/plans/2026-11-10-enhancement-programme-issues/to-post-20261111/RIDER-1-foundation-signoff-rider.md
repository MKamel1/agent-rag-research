Title: RIDER-1: Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step)
Labels: wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M

## RIDER-1 -- Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step)

**Review cross-reference:** review (D), RV-5 F-5.6, RV-3 F-1.11, RV-6 F-A5, RV-1 F-1.10. **Wave:** W4 rider and what it unblocks.

**Status update, 2026-11-11.** The baselines (EV-11, EV-16, EV-17, EV-18) and the follow-on measurements are done, so the pre-baseline rule no longer blocks this PR. Results are in `docs/eval-reports/EXPERIMENT-REGISTER.md`; nothing below was adopted by a measurement. This file is the request for operator sign-off on the protected-path edits only.

**Why.** Several changes can only land on protected paths (`contracts/`, `rag/config.py`, `config.example.yaml`, `rag/fakes/`, `fixtures/`, `.github/`), and every unrelated protected-path PR pays the same sign-off toll; batching them into one PR pays it once (`docs/AGENT-OPERATIONS-LESSONS.md` section 6.3).

**Scope.**
- In:
  - (5) Promote the frozen ground-truth sets to `fixtures/eval/` with one parametrised invariants test (unique ids, strata vocabulary, no gold on absent items, 6-word rule, excerpt verbatim in the live database with a skip when absent) and the SHA-256 in each set's metadata (RV-3 F-1.11). The hash file `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json` now freezes four sets: standards (128 items, 94 scored), books (74, 69 answerable), papers (61) and the repaired topic-focus set (49 items after the EV-11 re-check). All four were used by the 2026-11-11 runs. Promotion must keep the hashes and the `check-hash` script working (the script reads paths from that file).
  - (2) Reject the dead lever: `relevance_filter="embedding"` fails validation until a gate exists (RV-5 F-5.6). The measurement that would have given the lever a gate is now in: the relevance-demotion A/B (RQ-3, `docs/eval-reports/2026-11-11-relevance-demotion-result.md`) returned REJECT on all three arms (baseline focus contamination 0.100; arms 0.112, 0.154, 0.112; legitimate off-topic recall 14 -> 8, 8, 14), so there is no evidence-based way to enable it. The opt-in demotion code from RQ-2 stays default off; whether to remove it is a separate operator decision and is not part of this PR.
  - (6) `.github/`: a `ruff` step in CI and the nightly real-adapter workflow labelled manual-only (RV-6 F-A5).
  - (7) Conditional, only if the operator confirms it: `config.example.yaml` still shows `rerank_depth: 32`. The operator moved the main corpus to 128 on 2026-11-11 in the per-corpus config (not a tracked file); the example file is protected, so aligning it rides this PR. The standards corpus already runs at 128 and Waymo, Motional and Waabi stay at 32, so the example value is an operator choice about what a new corpus should start with.
- Out (explicitly):
  - Items 1, 3, 4 (their sources are parked, cut or rejected). The `chunker_id` migration (not doing). Any logic change beyond the listed edits. Reverting or deleting anything in response to the ligature-repair result (see the open question below). Pushing to the default branch or merging (human only).

**Open question the operator should answer in this PR's review (no file change here).** The ligature A/B (`docs/eval-reports/2026-11-11-ligature-repair-result.md`) is recorded as REJECT because clause (a) failed (`sparse_only` paper Recall@10 22 versus 22). The pre-registered consequence text also says to revert the query-side repair in `_sparse_vector`, but that A/B measured only the index-side repair; the query-side repair was in both arms and was a verified no-op on the fixture questions. So the rejection wording also covers a change that was not measured. `rag/vector_index.py` is not a protected path, so no rider edit is involved; the decision is recorded here so it is not lost.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `contracts/config.py`
- `rag/config.py`
- `config.example.yaml` (item 7 only, if confirmed)
- `fixtures/eval/`
- `.github/workflows/ci.yml`
- `.github/workflows/nightly-real-adapters.yml`

**Commits** (① is a stub, committed before any real work):
① stub: PR description draft listing each item, its source and the operator decision it needs; empty diff
② item (5) (promotion and invariants test)
③ item (2) (validation of the dead lever)
④ item (6)
⑤ item (7), only if confirmed
⑥ local enforcement transcript with the `foundation-change` label noted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check contracts/config.py rag/config.py`
- `check-hash` (`scripts/eval_protocol_tools.py`) still passes after promotion
- Mutation proof for the invariants test: edit one question in a copy and watch it fail

**Acceptance / falsification criterion.** One PR only; every protected-path edit is traceable to a listed item; the invariants test passes on the promoted sets and fails when one question is altered; the PR carries the `foundation-change` label and waits for the operator's merge. Falsified if the PR touches any protected path not listed, or if any frozen fixture hash changes.

**Gates / depends on.** Depends on: EV-11 (done), EV-18 (partly done; the baseline is taken), operator answer F4 (push so CI can judge the PR). Gates: RQ-4 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: y: this ticket IS the sign-off request; the operator merges (never an agent) · re-embed: n.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Item 2 changes config validation (a start-up behaviour), so it must not precede any measurement that needs the old behaviour; none is pending. Promotion moves frozen files, so the hash check is the guard. Rollback: revert the merge (single PR).

**Docs to update in the same PR.** Per `docs/AGENT-PROCEDURES.md` section B: flip this ticket's row in `docs/BACKLOG.md` to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 ledger; add a row to `docs/eval-reports/EXPERIMENT-REGISTER.md` for any new result; add a section 7 doc-map row for every new `docs/*.md`. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns.
