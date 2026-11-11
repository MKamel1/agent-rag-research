Title: EV-24: Pre-registered calibration study for the reranker-score "not in corpus" signal
Labels: wave:2-gpu-measure, area:eval, area:retrieval, needs-gpu, needs-services, size:M

## EV-24 -- Pre-registered calibration study for the reranker-score "not in corpus" signal

**Wave:** W2 first GPU session, measurements only (authoring and pre-registration first, CPU).

**Why.** The EV-19 census (`docs/eval-reports/2026-11-11-rerank-score-census-result.md`) returned CANDIDATE: the best cross-encoder score among returned passages separates absent from answerable queries, AUROC (absent as positive) with 95 percent bootstrap interval: focus 0.942 [0.861, 0.994] with 9 absent items against 40 answerable; standards 0.801 [0.715, 0.879] with 22 absent (9 absent plus 13 partial-absent) against 106; legacy 0.874 [0.819, 0.922] but it fails the question-length control (question length alone gives 0.974, because the fabricated-entity questions are shorter). The verdict authorises only a larger, separately pre-registered calibration study; no threshold, wiring or exposure of the score is authorised. In-sample best thresholds had large false-abstain rates on answerable items (standards 48 of 106, legacy 92 of 250, focus 3 of 40), and a threshold decision needs at least 60 distinct absent items (RV-3 F-1.10); each set holds 9 to 24.

**Relation to RQ-4.** Parked RQ-4 (expose the score in result metadata, a protected-path change) needs: an abstention feature commissioned, 60 or more distinct absent items, and RIDER-1 landed. This study is what would supply the second condition and a threshold-free answer to "is the signal usable at all". It needs no contract change: the score is captured with the opt-in `--record-rerank-scores` option (EV-13) and analysed with `scripts/rerank_score_census.py`. If the study fails, RQ-4 is killed.

**Scope.**
- In:
  - Step 1 (authoring, no services): write the new absent-question set. At least 60 distinct absent items per corpus type studied (at minimum the main corpus; standards if it can reach the same size), of the kind users actually ask: real topics that the corpus does not cover, not fabricated entities. Match the answerable items on question length by construction, and include the partial-absent class separately labelled so it is not silently pooled (the standards pass depended on pooling).
  - Step 2 (pre-registration, committed before any score is seen): the fixture and its hash; the primary feature (`rerank_top1`) and the controls (question length, fusion top score); the pass rule (AUROC lower confidence bound above 0.70 and above both controls on every qualifying set, with the length control computed on the new matched set); thresholds fixed before measurement, as one operating point per corpus chosen by a stated criterion (for example a maximum false-abstain rate on answerable items) on a development half and evaluated once on a held-out half; the sample-size arithmetic showing the study can detect the effect it claims; and the rule for a null result.
  - Step 3 (GPU): run the retrieval with score capture at the shipped config of each corpus (record the rerank depth: the main corpus now runs at 128, the 2026-11-11 census ran it at 32, and scores are model- and pool-relative, so the study is a new measurement, not a continuation) and apply the pre-registered analysis.
- Out (explicitly): exposing the score in any result (RQ-4); wiring any abstention behaviour; generated-answer abstention (separate measurements); changing the reranker or its flags; using the census sets as the held-out half.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/data/<run-date>-rerank-calibration/` (fixture, MANIFEST, run outputs)
- `docs/eval-reports/<run-date>-rerank-calibration-prereg.md`
- `docs/eval-reports/<run-date>-rerank-calibration-result.md`
- `docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json` (one added entry, by dated addendum)

**Commits** (① is a stub, committed before any real work):
① stub: pre-registration skeleton with the pass rule, controls and threshold procedure
② fixture authored, hash frozen, pre-registration committed (no score seen yet)
③ MANIFEST committed at launch
④ raw outputs and validity
⑤ result report with the verdict applied literally

**Verification:**
**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Fixture invariants: unique ids, no gold on absent items, question-length distributions of absent and answerable items reported side by side
- Errors 0 and `run_valid` true on every arm; a repeat arm agrees within the jitter envelope

**Acceptance / falsification criterion.** The pre-registered rule is applied as written and the report states PASS, FAIL or INCONCLUSIVE with intervals. Falsified (signal not usable) if the AUROC lower bound does not exceed the length control on the new matched set, or does not exceed 0.70 on the main-corpus set. A PASS authorises only the next step (commissioning the abstention feature and un-parking RQ-4), not any threshold in production.

**Gates / depends on.** Depends on: EV-19 (done). Operator answers: F3 (GPU session); a decision that an abstention feature is wanted at all (otherwise this study is not worth its authoring cost). Gates: RQ-4 (parked).

**Needs.** GPU: y (about 35 GPU minutes for the census; scale by the new set size) · services up: embedder and reranker containers, vector store, corpus databases read-only · operator sign-off: n for the study itself · re-embed: n.

**Model tier and size.** Sonnet for authoring and running; the pre-registration (step 2) is statistical design and should be reviewed by an independent reviewer before step 3. M.

**Risk and rollback.** Items authored by a model from the same family as the labeller share blind spots (the census items were LLM-authored); the pre-registration must say how this is controlled (for example human spot-check of a sample). Rollback: discard the run directory; nothing is shipped.

**Docs to update in the same PR.** Per `docs/AGENT-PROCEDURES.md` section B: flip this ticket's row in `docs/BACKLOG.md` to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 ledger; add a row to `docs/eval-reports/EXPERIMENT-REGISTER.md` for any new result; add a section 7 doc-map row for every new `docs/*.md`. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns.
