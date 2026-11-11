Title: RQ-2: Add an opt-in, default-off relevance demotion to the Retriever
Labels: wave:1-no-gpu, area:retrieval, size:M

## RQ-2 -- Add an opt-in, default-off relevance demotion to the Retriever

**Review cross-reference:** S-21. **Wave:** W1 do now, no GPU.

**Why.** 37.4% of main-corpus papers (4,630 of 12,385) are off-topic against the audited labels and nothing in the pipeline can keep them out of an answer; `papers.relevance_score` separates on from off topic at AUROC 0.923 (RV-1 F-1.4, `docs/eval-reports/2026-11-10-topic-labels-audit.md`), the Retriever already loads the paper record for every reranked hit, and `Config.relevance_filter` is dead. The operator keeps the off-topic papers; the lever is measurement first, demotion only.

**Scope.**
- In:
  - `Retriever` keyword arguments (floor value, demote mode) that, when set, move results whose paper `relevance_score` is below the floor after those at or above it, preserving relative order and never removing any result; default off so output is byte-identical to today.
  - A `--demote-relevance <floor>` flag in `app/retrieval_eval.py`, the same pattern CQ-3 used for `--drop-stub-chunks`, so the arm can be run.
- Out (explicitly):
  - A hard drop or a filter (excluded by the frozen topic-focus protocol, section 6). A `Config` field or `SearchFilters.min_relevance` (RIDER-1 item 1 if adopted). The payload-index route (only if RQ-3 observes pool starvation). Choosing the floor: RQ-3's pre-registered arms.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/retriever.py`
- `rag/test_retriever.py`
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstring stating demote semantics, the default-off identity guarantee, and the flag name that RQ-3's addendum will cite
② failing tests: below-floor results follow in-floor ones in original relative order; none removed; `Coverage` unchanged; default off equals baseline on the fake
③ implementation to green
④ `--demote-relevance` flag wired and tested

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/retriever.py rag/test_retriever.py app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_retriever.py app/test_retrieval_eval.py -o addopts="--disable-socket"`
- Identity check: with the flag absent, the per-question rows of a fake-backed run are equal before and after

**Acceptance / falsification criterion.** Default-off output is identical to the pre-change commit on the fake (byte-equal result lists); with a floor set, no result is removed and order within each side of the floor is preserved. The retrieval-quality ADOPT/REJECT rule is not applied here: it is frozen in the topic-focus protocol section 6 and applied by RQ-3. Falsified if the default-off identity test fails.

**Gates / depends on.** Depends on: RQ-1, EV-10. Gates: EP-3, RQ-3.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Demotion acts on the already-truncated pool and can starve it (a pool 40% off-topic still leaves about 19 of 32; RV-1 F-1.4). Mitigation: default off; RQ-3 reports `Coverage` pool sizes. Rollback: revert; nothing depends on it until RIDER-1.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (flag) via EP-3; no contract or Config change here. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
