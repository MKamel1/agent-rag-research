Title: EV-16: Run the frozen main-corpus baselines (papers, books, legacy)
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M

## EV-16 -- Run the frozen main-corpus baselines (papers, books, legacy)

**Review cross-reference:** S-16. **Wave:** W2 first GPU session, measurements only.

**Baseline commit freeze (step of this ticket, not a separate ticket).** Before launch the orchestrator records the integration-branch head as `baseline_commit`; all code used by EV-16, EV-17 and EV-18 is that exact commit (run worktree checked out at it); the SHA is written into the stub and into every run's MANIFEST and output directory; nothing in the pre-baseline rule's list (plan section 4, rule 16) merges into the integration branch until the EV-18 report is merged.

**Why.** No baseline exists for the new papers-passage and causal-books sets, and every later A/B needs a measured reference on the same code and index; the first run is also the only moment the TEI truncation limit can be confirmed with one `/info` request (review S-16). Plain BM25 already reaches 0.96-0.98 paper recall on these sets, so only passage level and the title-ablated arm can show headroom (RV-3 F-1.3).

**Scope.**
- In:
  - Freeze the baseline commit (see above) and verify the strata-report instrument was reviewed (EV-6b merged) before any number is read.
  - Run `run_baseline_main.sh papers books legacy` exactly as the GPU-day runbook step 1a specifies (about 654 queries, estimated 20-40 min), as a detached process (LESSONS section 7.3); then the BM25 floor (EV-15) beside it, the title-ablated arm and the strata report (EV-6, reviewed by EV-6b).
  - One `/info` request to the embedder to confirm its truncation limit; record the value.
  - Report unmodified as a dated baseline document: passage-level headline (member-passage hit@10 and P@1, plus `passage_excerpt_hit`), paper recall as tripwire only, per-stratum Wilson intervals, `authority`/`edition`-style small strata labelled descriptive.
- Out (explicitly):
  - Any A/B or config change (later tickets). The focus set (EV-17) and standards (EV-18). Re-grounding or editing a fixture. Quoting a precision-95 headline number (operator question F8).
  - Baselines for the Motional, Waabi and Waymo corpora: none is planned (plan section 9).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-main-baseline.md`
- `docs/eval-reports/data/<run-date>-main-baseline/`
- `docs/eval-reports/data/2026-11-10-papers-passage-gt/runs/ (own stamp only)`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton citing the frozen main-corpus protocol and the stop conditions; hash file revision recorded; `baseline_commit` frozen (integration head SHA), recorded here, and the run worktree checked out at exactly that SHA
② detached run launched; MANIFEST committed when it starts (start time, collection, db, `baseline_commit`, fixture hashes)
③ raw reports copied into the data dir with `n_errors` and `run_valid` shown
④ BM25 floor and title-ablated arm
⑤ report written; every number carries {metric, fixture, arm, pool depth, config}

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- `conda run -n agent-rag-research python -m app.doctor --no-auto-start` exits 0 before and after
- Run scripts print `check-hash` and `check-points` passes; the report's `ground_truth_sha256_12` equals the hash file's entry
- `n_errors` is 0 and `run_valid` is true in every report (else the arm is invalid and is not read)
- `git rev-parse HEAD` in the run worktree equals the recorded `baseline_commit` before and after the run, and the SHA appears in every output directory

**Acceptance / falsification criterion.** Per set (never averaged): passage-level hit@10 and P@1 with Wilson intervals, the BM25 floor beside it, the title-ablated paper recall, and stratum tables; the report hash equals the frozen hash; zero errors. The ceiling for each metric is printed with it (member hit@10 ceiling 1.00; paper recall tripwire headroom at most 2 items on the legacy 210-set). Every output carries the `baseline_commit` SHA. Falsified (run discarded) if a hash or point-count check fails, the recorded SHA differs from the code that ran, or any error is a lock timeout.

**Gates / depends on.** Depends on: EV-7, EV-8, EV-9, EV-10, EV-11, EV-15, EV-6b. Operator answers: F3. Gates: CQ-7 (parked), EV-17, EV-18, EV-20, EV-19 (parked), EV-21 (parked), EV-22 (parked), CQ-18 (parked), RQ-3 (parked).

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free of the foreign model process (operator question F3); about 20-40 min GPU (estimate, not measured).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A foreign GPU holder or a held lock starves the run. Mitigation: EV-10 invalidates a starved run (and `app.doctor`, if OP-5 has merged, names the holder); one GPU job at a time. The run only reads. Rollback: discard the run directory.

**Docs to update in the same PR.** The dated baseline report is the doc (section 7 doc-map row); section 3 ledger entry carries the `baseline_commit` SHA. Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
