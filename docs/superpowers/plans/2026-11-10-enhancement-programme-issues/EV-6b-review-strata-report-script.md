Title: EV-6b: Dry-run and independently review the strata report script before the first baseline
Labels: wave:1-no-gpu, area:eval, size:S

## EV-6b -- Dry-run and independently review the strata report script before the first baseline

**Review cross-reference:** review section 2 ('EV-6 not reviewed by any lane'); minimizer section 2 (critical-path gap). **Wave:** W1 do now, no GPU.

**Why.** `scripts/eval_strata_report.py` (EV-6, done) produces every per-stratum and member-passage number of EV-16, EV-17 and EV-18, yet no lane or reviewer has examined it, and its own docstring states known over-estimate cases (3.1% of sampled standards chunks have a member block missing from the chunk text; chunks sharing one anchor are merged). A wrong table would be read as a baseline. The minimizer proposed folding a dry run into EV-8's acceptance; the operator asked for a separate small ticket so that the review is done by an agent other than the author of the row-format changes (EV-8, EV-9, EV-10) and after the row format is final.

**Scope.**
- In:
  - A hand-computed example: a six-question fake rows file and a tiny ground-truth file (built in the test, no real corpus) in which every printed number (paper recall@k and P@1, anchor and member-passage hit, stub share, authority/edition ranking, cross-document, absent arm, focus contamination) is computed by hand and written into the test as a literal; the script's output must equal it.
  - A dry run of the script on the rows produced by the merged EV-7..EV-10 bundle's fake-backed tests (so rows carry `passage_excerpt_hit`, `retrieved_chunk_ids`, `scoring_rule`, `ground_truth_sha256_12`, `run_valid`): the script must not fail on the new fields and the review note states whether it ignores or uses each.
  - A written review note: each metric definition read against the frozen protocols, the known over-estimate cases listed with their bound, and any defect fixed minimally (or reported if the fix is larger than a few lines). The reviewer is a fresh agent, not the author of EV-8, EV-9 or EV-10.
- Out (explicitly):
  - New metrics. Using `passage_excerpt_hit` inside the strata tables (only if the review shows the member rule disagrees materially). Reading any real corpus database, any GPU or service.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `scripts/eval_strata_report.py`
- `scripts/test_eval_strata_report.py`
- `docs/eval-reports/<run-date>-eval-strata-report-review.md`

**Commits** (① is a stub, committed before any real work):
① stub: review-note skeleton listing every metric and the hand-computed expected table, committed before the script is run against it
② hand-computed example test (red where the script disagrees, green where it agrees) and the dry run on the bundle's fake rows
③ fixes for any defect found (omitted if none), each with its own test
④ review note final: per metric 'matches protocol' or 'deviates: how and by how much'

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research ruff check scripts/eval_strata_report.py scripts/test_eval_strata_report.py`
- `conda run -n agent-rag-research python scripts/eval_strata_report.py --help` still works
- Mutation proof: change one hand-computed literal and watch the test fail

**Acceptance / falsification criterion.** The script's output equals the hand-computed value for every metric of the example; the dry run on rows with the new fields succeeds; the review note gives each metric a verdict. Falsified if any hand-computed value differs from the script's output and the difference is not an explicitly documented rule of the script.

**Gates / depends on.** Depends on: EV-9. Gates: EV-16.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic work; no Opus-level design adjudication is needed.

**Risk and rollback.** A defect found late changes the reporting rule after rows exist. Mitigation: the review is a prerequisite of EV-16, before any real row exists. Rollback: revert; the script is post-processing only.

**Docs to update in the same PR.** The review note is a new doc (section 7 doc-map row, REFERENCE). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
