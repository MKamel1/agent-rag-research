Title: EV-23: Measure rerank depth 32 versus 128 on the Waymo, Motional and Waabi corpora where a ground-truth set exists
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S

## EV-23 -- Measure rerank depth 32 versus 128 on the Waymo, Motional and Waabi corpora where a ground-truth set exists

**Wave:** W2 first GPU session, measurements only.

**Why.** The operator decided on 2026-11-11 to use whatever depth gives the best results per corpus type. The main corpus moved from 32 to 128 (papers +2 at 2:0, books +3 at 4:1, about 1.9x wall-clock; `docs/eval-reports/2026-11-11-rerank-depth-result.md` section 8) and standards stays at 128 (rule D-1). Waymo, Motional and Waabi stay at 32 because depth was never measured on them with the current fixtures.

**What exists to measure with (checked in `docs/CORPORA.md` and `fixtures/eval/`).**
- Waymo: yes. A verified set of 82 questions (68 answerable, 14 known absent) with paper-level gold, `fixtures/eval/waymo_gt_verified.json`, plus related sets (`gt_wmr.json`, `waymo_gt_a.json`, `waymo_gt_b.json`). There is no passage-level gold, so the metric is paper Recall@10, not member-passage hit@10. Earlier evidence (2026-08, `docs/eval-reports/2026-08-24-*`, cited in `docs/CORPORA.md`): pool 32/64/128 gave Recall@10 65/64/61 of 68, i.e. 128 was worse there, at the then weight 0.5 (Waymo now runs at 0.7). Headroom at depth 32 is therefore about 3, below the 6 the pre-registered precondition requires.
- Motional (65 papers) and Waabi (29 papers): no ground-truth set in the repository. They cannot be measured by this ticket. Authoring a set is out of scope and probably not worth it for corpora of this size; they stay at 32.

**Scope.**
- In:
  - Step 1 (CPU, no services): compute Waymo's headroom (answerable minus baseline hits at depth 32 under the current Waymo config, metric paper Recall@10) from the recorded baseline outputs under `docs/eval-reports/data/2026-08-23-waymo-priority/`, or from one depth-32 run if none is current. If headroom is below 6, record `skipped: ceiling` with the arithmetic and stop. Waymo stays at 32.
  - Step 2 (only if headroom is 6 or more): run depth 32 and depth 128 back to back on Waymo with the current Waymo config (weight 0.7), reusing the session-2 rule unchanged (`docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` section 1): prefer 32 unless 128 gains at least 2 net questions with no gating stratum (n of at least 10) losing more than one; rule G-1 (net at least +3, wins to losses at least 3:1, no gating stratum losing more than one, same sign on a title-ablated arm if one exists for the set) recommends a change only if both hold; the depth-32 arm doubles as the validity gate (|net| of at most 1 against the recorded baseline). The only deviation is the metric (paper Recall@10), written into the report skeleton before the run.
  - Record Motional and Waabi as "no ground truth, not measured" in the report and in `docs/CORPORA.md`.
- Out (explicitly): changing any depth (a verdict is a recommendation; the operator applies it in the per-corpus config); the 0.7 or 1.0 weight arms; authoring new ground truth; any retrieval run on the main or standards collections.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-rerank-depth-other-corpora-result.md`
- `docs/eval-reports/data/<run-date>-rerank-depth-other-corpora/`
- `docs/eval-reports/EXPERIMENT-REGISTER.md` (one row)
- `docs/CORPORA.md` (the depth status cells for these three corpora)

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the rule and the metric deviation quoted before any run
② headroom arithmetic (step 1); stop here if below 6
③ MANIFEST committed at launch, raw reports and validity (step 2)
④ verdict and report

**Verification:**
**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Fixture hash check passes before any service call (`scripts/eval_protocol_tools.py check-hash`; the Waymo set may need its hash recorded first if it is not in `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json`: record it by a dated addendum, do not edit silently)
- Errors 0 and `run_valid` true on every arm

**Acceptance / falsification criterion.** The report states, per corpus, either a verdict by the stated rule or the reason it was not measured (ceiling, or no ground truth). Falsified (run not read) if the depth-32 re-run differs from the recorded baseline by more than one question or any arm has errors. The rule cannot show effects below about 6 net questions at this fixture size; the report says so next to the verdict.

**Gates / depends on.** Depends on: none in the repository; operator answer F3 (GPU session) for step 2 only. Gates: none.

**Needs.** GPU: y (step 2 only, estimated well under an hour for 68 questions per arm) · services up: embedder and reranker containers, vector store, the corpus's own data directory (read-only) · operator sign-off: n · re-embed: n.

**Model tier and size.** Sonnet; S.

**Risk and rollback.** Waymo's data directory is outside git, so the config for the run must be a copy with only `rerank_depth` differing; the live config is not edited. Rollback: discard.

**Docs to update in the same PR.** Per `docs/AGENT-PROCEDURES.md` section B: flip this ticket's row in `docs/BACKLOG.md` to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 ledger; add a row to `docs/eval-reports/EXPERIMENT-REGISTER.md` for any new result; add a section 7 doc-map row for every new `docs/*.md`. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns.
