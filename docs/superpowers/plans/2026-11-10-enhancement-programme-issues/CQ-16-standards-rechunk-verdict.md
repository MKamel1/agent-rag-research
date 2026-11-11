Title: CQ-16: Measure the standards re-chunk against baseline and decide
Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:S

## CQ-16 -- Measure the standards re-chunk against baseline and decide

**Review cross-reference:** S-24. **Wave:** W3 gated changes after baselines.

**Why.** Structure fixes are only worth a live re-embed if answers improve: the gate (EV-18) is a count of structure-attributable misses, and the standards fixture is scored by the chunker-independent excerpt metric so old and new chunkers are comparable (review S-24).

**Scope.**
- In:
  - Run the standards GT on live and on the CPU-rebuilt clone, same code, excerpt metric, paired flips by stratum; plus the structural checks (furniture roots 0, stub rate under 2%, bare-number stubs 0).
- Out (explicitly):
  - Applying to the live collection (follow-on ticket on ADOPT only; needs F7).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-standards-rechunk-verdict.md`
- `docs/eval-reports/data/<run-date>-standards-rechunk-verdict/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 excerpt hits on the standards set, flips at least 3:1, no stratum losing more than 1, and the structural checks pass
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ live and clone arms; MANIFEST
④ report

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection` (live and clone separately)
- Gold chunk ids of re-chunked documents are not used for scoring

**Acceptance / falsification criterion.** Verdict applies the stated rule; edition and authority strata (n=4 each) are shown as descriptive only. Ceiling: gain bounded by the EV-18 structure-attributable miss count. Falsified if the live arm differs from EV-18's beyond the jitter envelope.

**Gates / depends on.** Depends on: CQ-15, EV-18. Operator answers: F3. Gates: CQ-18, EP-5.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 20-30 min GPU (estimate).

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Gain unobservable at n=94. Mitigation: UNDERPOWERED is a verdict. Rollback: delete the clone.

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
