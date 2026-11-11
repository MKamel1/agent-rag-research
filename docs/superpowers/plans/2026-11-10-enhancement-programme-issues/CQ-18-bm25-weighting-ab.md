Title: CQ-18: Run the BM25-weighting A/B on a repaired clone
Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:M

## CQ-18 -- Run the BM25-weighting A/B on a repaired clone

**Review cross-reference:** S-25. **Wave:** W3 gated changes after baselines.

**Why.** Whether length normalisation and saturation help the sparse arm is unmeasured; a separate A/B keeps attribution clean after the ligature A/B (review S-25).

**Scope.**
- In:
  - On a fresh clone: resparse with the option on (CPU), run the standards, causal-books and papers-passage sets and the lexical strata (standards clause lookups, books terminology) against the live baseline, paired flips.
- Out (explicitly):
  - Live application (follow-on on ADOPT only). Combining with any other change.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-bm25-weighting-ab.md`
- `docs/eval-reports/data/<run-date>-bm25-weighting-ab/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 items on at least one set, no set losing more than 1, and a gain on the lexical strata, else REJECT
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ clone built and resparsed; counts recorded
④ arms run; MANIFEST
⑤ report; clone deleted

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection`; the live collection is never an apply target

**Acceptance / falsification criterion.** Verdict applies the stated rule per set (never averaged); the ceiling is stated per stratum (BM25 floor from EV-15 shows where lexical headroom exists). Falsified if the baseline arm differs from EV-16/EV-18 beyond the jitter envelope.

**Gates / depends on.** Depends on: CQ-17, EV-22, EV-16, EV-18, CQ-16. Operator answers: F2, F3. Gates: RIDER-1, EP-5.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F2, F3 · re-embed: n. Also: GPU free (F3); vector store (F2); 6-8 GB for a clone.

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Disk or contention; mitigations as CQ-7. Rollback: delete the clone.

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
