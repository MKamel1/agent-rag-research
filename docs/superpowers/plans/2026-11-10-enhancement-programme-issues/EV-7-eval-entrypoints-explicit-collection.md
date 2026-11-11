Title: EV-7: Require --collection, stamp the fixture hash, preflight gold ids
Labels: wave:1-no-gpu, area:eval, size:M

## EV-7 -- Require --collection, stamp the fixture hash, preflight gold ids

**Review cross-reference:** S-02. **Wave:** W1 do now, no GPU.

**Cut by minimizer:** `escalation_eval.py` and `score_distribution_census.py` are not run anywhere in the programme and drop out; `app/retrieval_eval.py` (the instrument) and the gold-id preflight stay. The failure is real but already mitigated: EV-5's run scripts pass `--collection` and check the hash.

**Why.** `--collection` still defaults to None in `app/retrieval_eval.py:780` (the same default exists in `app/escalation_eval.py` and `app/score_distribution_census.py`, which this programme does not run), which `build_mcp_server` turns into the main `papers` collection, so a mispointed run yields a plausible low number with `n_errors = 0` (RV-3 F-1.2). Reports stamp no hash of the ground-truth file (contrast `judge_eval`'s `rubric_sha256_12`). EV-5 already fixed the run scripts (fixture hash check, point-count guard, no fixture rewrite, run from the worktree under test); the Python entry points themselves were not touched.

**Scope.**
- In:
  - `--collection` `required=True` in `app/retrieval_eval.py` (precedent: `app/generation_capture.py`).
  - `ground_truth_sha256_12` in `build_report`, same pattern as `judge_eval`.
  - Preflight before scoring: every `gold_paper_id` of the loaded questions resolves in the document store, else exit 2 naming the unresolved ids.
- Out (explicitly):
  - `app/escalation_eval.py` and `app/score_distribution_census.py` (not run in this programme; they keep their default).
  - The run scripts, protocols and addenda (EV-5, done). The collection point-count check (stays in the run scripts' `check-points`). Lock-timeout validity (EV-10). Excerpt metric (EV-8).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the three behaviours (required flag, hash stamp, preflight exit 2)
② failing tests for each
③ implementation to green
④ docstring/`--help` text updated

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py`
- `conda run -n agent-rag-research python -m app.retrieval_eval --help` shows `--collection` as required
- Unit test: report hash equals `sha256sum` of the fixture file (first 12 hex)

**Acceptance / falsification criterion.** Running `app.retrieval_eval` without `--collection` exits non-zero; the report's `ground_truth_sha256_12` equals the first 12 hex of `sha256sum` of the file; a fixture with an unresolvable gold paper id exits 2 naming it. Falsified if a run without `--collection` still starts.

**Gates / depends on.** Depends on: none. Gates: EV-8, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Existing wrapper scripts that relied on the default break loudly. Mitigation: that is the point; EV-5's run scripts already pass `--collection`. Rollback: revert.

**Docs to update in the same PR.** Section 2: `--collection` is now required for `app.retrieval_eval`. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
