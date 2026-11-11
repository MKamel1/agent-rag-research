Title: EV-13: Capture cross-encoder scores and build the absence census tool
Labels: wave:1-no-gpu, area:eval, area:retrieval, size:M, parked
Parked-until: only after an abstention feature is commissioned by the operator and at least 60 distinct absent items exist (the sets hold 9-24). Kill criterion: killed if no abstention feature is commissioned.

## EV-13 -- Capture cross-encoder scores and build the absence census tool

**Review cross-reference:** S-04. **Wave:** W1 do now, no GPU.

**Parked, do not start.** Parked-until: only after an abstention feature is commissioned by the operator and at least 60 distinct absent items exist (the sets hold 9-24). Kill criterion: killed if no abstention feature is commissioned.

**Why.** Callers get the fusion (RRF) score and the reranker's score is discarded (`rag/retriever.py:249`, `rag/reranker.py:231`), so the earlier 'no score floor' verdict tested rank arithmetic only; the cross-encoder score is the one cheap absence signal nobody has censused (review item a; RV-1 F-1.1, RV-4 F-4.1). A CRAG instrument (AUROC 0.94 and 0.80) and MiniCheck are independent of this and stay as they are.

**Scope.**
- In:
  - Experiment-only `rerank_scored()` on `TeiReranker` returning `(candidate, score)` pairs, no contract change, `rerank()` untouched.
  - `app/exp_rerank_score_census.py`: answerable top-1 reranker score versus the absent arms (standards absent 9 and partial-absent 13 reported separately; main known-absent 24; books partial-absent 5; Waymo 12 and 14), AUROC with Hanley-McNeil interval, reusing `auroc_pos_higher` from `exp_agentic_loop_v0` and `_iqr_separates` from the score census; explicit `--collection`, `--db-path`, `--blob-dir`. Definition frozen in the standards protocol section 7 (iii).
- Out (explicitly):
  - Exposing the score to callers (RQ-4, gated). Running it (EV-19, GPU). Any threshold or wiring decision (needs 60 or more distinct absent items; RV-3 F-1.10).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `rag/reranker.py`
- `rag/test_reranker.py`
- `app/exp_rerank_score_census.py`
- `app/test_exp_rerank_score_census.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings of `rerank_scored` and the census CLI; the frozen definition cited by section number
② failing tests: scores returned are monotone in the order `rerank()` returns; census on a fake reranker computes the expected AUROC and CI
③ implementation to green
④ census CLI with required collection flags

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check rag/reranker.py rag/test_reranker.py app/exp_rerank_score_census.py app/test_exp_rerank_score_census.py`
- `conda run -n agent-rag-research python -m pytest -q rag/test_reranker.py app/test_exp_rerank_score_census.py -o addopts="--disable-socket"`
- Reuse stated: `auroc_pos_higher`, `_iqr_separates`, Hanley-McNeil helper (no new statistics code)

**Acceptance / falsification criterion.** Unit test: `rerank_scored` scores are monotone with `rerank()` order; the census reproduces a hand-computed AUROC on a fixture of 6 items. Falsified if `rerank()` output changes by even one id on the existing reranker tests.

**Gates / depends on.** Depends on: RQ-1. Gates: EV-19 (parked).

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Adding a method to a real adapter widens its surface. Mitigation: documented experiment-only; fakes are untouched (protected). Rollback: revert.

**Docs to update in the same PR.** Section 2: new `app/` entry point. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
