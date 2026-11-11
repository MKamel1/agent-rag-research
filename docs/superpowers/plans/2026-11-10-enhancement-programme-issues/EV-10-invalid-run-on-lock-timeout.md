Title: EV-10: Mark an eval run invalid when any error is a GPU lock timeout
Labels: wave:1-no-gpu, area:eval, size:S

## EV-10 -- Mark an eval run invalid when any error is a GPU lock timeout

**Review cross-reference:** S-06. **Wave:** W1 do now, no GPU.

**Why.** Lock-timeout errors are scored as ordinary misses by `app/retrieval_eval.py`'s per-hit resilience: in SB-1 two eval jobs sat more than 20 minutes behind a long GPU job and some questions timed out and were counted as misses (RV-6 F-A8, `docs/eval-reports/2026-08-28-sb1-chunk-boundary.md`). Wave 2 is exactly the concurrent-GPU scenario.

**Scope.**
- In:
  - Count questions whose error is a lock timeout; if any, write `run_valid: false` and the count in the report header and exit non-zero instead of scoring them as misses.
- Out (explicitly):
  - The lock holder identity (OP-5). Retrying timed-out questions.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating the invalid-run rule
② failing test: a stubbed lock-timeout error yields `run_valid: false` and a non-zero exit
③ implementation to green
④ report header field documented

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q app/test_retrieval_eval.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** A stubbed lock timeout on one question makes the whole report invalid and the process exit non-zero; a run with no timeouts is unchanged. Falsified if the timeout question is still counted as a miss.

**Gates / depends on.** Depends on: EV-9. Gates: EP-3, RQ-2, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A transient timeout on one question invalidates a long run. Mitigation: intended (a partially starved run is not a baseline); the run is repeatable. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
