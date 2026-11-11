Title: EV-21: Run the amended CQ-3 stub-filter A/B
Labels: wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M

## EV-21 -- Run the amended CQ-3 stub-filter A/B

**Review cross-reference:** S-18. **Wave:** W2 first GPU session, measurements only.

**Why.** 7-10% of chunks in every corpus are heading-only stubs (main 36,364 of 399,676; standards 2,483 of 35,714) and whether they cost any results is unmeasured; CQ-3 shipped a reversible default-off filter and a pre-registered A/B, amended by EV-12 (review S-18, `docs/eval-reports/2026-11-10-cq3-stub-chunks.md`).

**Scope.**
- In:
  - GPU-day runbook step 4 as amended by EV-12: baseline and `--drop-stub-chunks` back to back per fixture (standards, causal-books, papers-passage), baseline re-run rather than reused, per-question rows kept, stubs matched by chunk id (about 588 queries x 2 arms, estimate 40-80 min); `scripts/list_stub_chunks.py --ab`.
- Out (explicitly):
  - Turning the filter on (adoption rides RIDER-1 item 1). Changing the pre-registration.

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-stub-filter-ab.md`
- `docs/eval-reports/data/<run-date>-stub-filter-ab/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton quoting the EV-12 addendum rule verbatim
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ baseline and drop arms with MANIFEST per arm
④ paired flip table by fixture and stratum
⑤ report: ADOPT or REJECT

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Per-question rows present (no `--no-per-question`)
- Both arms ran on the same collection and code revision (manifest lines compared)

**Acceptance / falsification criterion.** ADOPT only if the EV-12 rule holds (net +3 items on at least one set, no stratum losing more than 1, stub-at-rank-1 share above 0 at baseline); otherwise REJECT and the default stays off. Both sets' tables are shown; none averaged. Ceiling: a gain is bounded by the stub-at-rank-1 and top-10 stub shares printed from `--report`. Falsified if the baseline arm differs from EV-16/EV-18's beyond the jitter envelope.

**Gates / depends on.** Depends on: EV-12, EV-9, EV-16, EV-18, EV-20. Operator answers: F3. Gates: EV-22, EP-4, RIDER-1.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: GPU free (F3); about 40-80 min GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A noise flip adopting a filter: prevented by the amended minimum effect. Rollback: n/a (flag only).

**Docs to update in the same PR.** Report via EP-4. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-4 carries those entries from this ticket's merged SHA.
