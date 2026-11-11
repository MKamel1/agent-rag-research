Title: RQ-3: Run the relevance-demotion arms on the focus and passage sets
Labels: wave:3-gated-change, area:retrieval, area:eval, needs-gpu, needs-services, size:M

## RQ-3 -- Run the relevance-demotion arms on the focus and passage sets

**Review cross-reference:** S-21. **Wave:** W3 gated changes after baselines.

**Why.** Off-topic papers cannot be kept out of an answer today. RQ-2 built a default-off demotion lever; the frozen topic-focus protocol (section 6) pre-registers its adoption rule. Whether the lever is needed at all depends on how material the baseline off-topic share is (operator question F6) (review S-21).

**Scope.**
- In:
  - Runbook step 6 (document-store route, no index change; the payload route only if pool starvation is observed): arms baseline, demote at 0.25, demote at 0.30 on the focus set and the papers-passage set, back to back (about 111 queries x 3, estimate 15 min). Record the exact flag in a dated addendum to the focus protocol before reading any number.
  - Starts only if EV-17's off-topic share exceeds the bar the operator sets (F6); if it does not, close as 'not material'.
- Out (explicitly):
  - A hard drop or filter (never, per protocol). A Config field or SearchFilters field (RIDER-1 item 1 if adopted). Writing `relevance_score` into the vector payload (follow-on only if starvation is observed).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-focus-lever-ab.md`
- `docs/eval-reports/data/<run-date>-focus-lever-ab/`
- `docs/eval-reports/2026-11-10-topic-focus-benchmark-protocol.md`

**Commits** (① is a stub, committed before any real work):
① stub: dated addendum to the focus protocol naming the exact flag and arms, committed before any arm runs
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ three arms run; MANIFEST per arm; `Coverage` pool sizes recorded
④ paired tables: off-topic share in top 10 and gold losses per set
⑤ report: ADOPT or REJECT against protocol section 6

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Both the focus set and the papers-passage set are reported separately; causal-books is the held-out control
- Every command names `--collection`, `--db-path`, `--blob-dir`

**Acceptance / falsification criterion.** ADOPT only if the protocol's rule holds: at least 50% relative drop in off-topic top-10 share with zero gold losses on papers-passage and causal-books and the legitimate-off-topic guards intact; otherwise REJECT. Ceiling: the achievable drop is bounded by the share of off-topic papers whose `relevance_score` falls below the floor (printed from the 0.923-AUROC operating points). Falsified if the baseline arm differs from EV-16/EV-17 beyond the jitter envelope.

**Gates / depends on.** Depends on: RQ-2, EV-16, EV-17, EV-22. Operator answers: F3, F6. Gates: CQ-10, RIDER-1, EP-5.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3, F6 · re-embed: n. Also: GPU free (F3); operator-set materiality bar (F6); about 15 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Demotion starves a pool that is already 40% off-topic. Mitigation: pool sizes are recorded and a starved pool is a REJECT reason. Rollback: n/a (flag only).

**Docs to update in the same PR.** Report and protocol addendum; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
