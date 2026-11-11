Title: EV-7: Require --collection, stamp the fixture hash, preflight gold ids
Labels: wave:1-no-gpu, area:eval, size:M

## EV-7 -- Require --collection, stamp the fixture hash, preflight gold ids

**Review cross-reference:** S-02. **Wave:** W1 do now, no GPU.

**Why.** `--collection` still defaults to None in `app/retrieval_eval.py:780`, `app/escalation_eval.py:153` and `app/score_distribution_census.py:209`, which `build_mcp_server` turns into the main `papers` collection, so a mispointed run yields a plausible low number with `n_errors = 0` (RV-3 F-1.2). Reports stamp no hash of the ground-truth file (contrast `judge_eval`'s `rubric_sha256_12`). EV-5 already fixed the run scripts (fixture hash check, point-count guard, no fixture rewrite, run from the worktree under test); the Python entry points themselves were not touched.

**Scope.**
- In:
  - `--collection` `required=True` in the three entry points (precedent: `app/generation_capture.py`).
  - `ground_truth_sha256_12` in `build_report`, same pattern as `judge_eval`.
  - Preflight before scoring: every `gold_paper_id` of the loaded questions resolves in the document store, else exit 2 naming the unresolved ids.
- Out (explicitly):
  - The run scripts, protocols and addenda (EV-5, done). The collection point-count check (stays in the run scripts' `check-points`). Lock-timeout validity (EV-10). Excerpt metric (EV-8).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `app/retrieval_eval.py`
- `app/test_retrieval_eval.py`
- `app/escalation_eval.py`
- `app/test_escalation_eval.py`
- `app/score_distribution_census.py`
- `app/test_score_distribution_census.py`

**Commits** (① is a stub, committed before any real work):
① stub: docstrings stating the three behaviours (required flag, hash stamp, preflight exit 2)
② failing tests for each
③ implementation to green
④ docstring/`--help` text updated

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check app/retrieval_eval.py app/test_retrieval_eval.py app/escalation_eval.py app/test_escalation_eval.py app/score_distribution_census.py app/test_score_distribution_census.py`
- `conda run -n agent-rag-research python -m app.retrieval_eval --help` shows `--collection` as required
- Unit test: report hash equals `sha256sum` of the fixture file (first 12 hex)

**Acceptance / falsification criterion.** Running any of the three without `--collection` exits non-zero; the report's `ground_truth_sha256_12` equals the first 12 hex of `sha256sum` of the file; a fixture with an unresolvable gold paper id exits 2 naming it. Falsified if a run without `--collection` still starts.

**Gates / depends on.** Depends on: none. Gates: EP-3, EV-8, EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Existing wrapper scripts that relied on the default break loudly. Mitigation: that is the point; EV-5's run scripts already pass `--collection`. Rollback: revert.

**Docs to update in the same PR.** PROJECT-STATUS section 2 (flag now required) via EP-3. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-3 carries those entries from this ticket's merged SHA.
