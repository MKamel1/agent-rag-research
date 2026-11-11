Title: CQ-10: Assess raising the embedding server's token limit for truncated chunks
Labels: wave:3-gated-change, area:corpus, area:ops, needs-gpu, needs-services, size:M

## CQ-10 -- Assess raising the embedding server's token limit for truncated chunks

**Review cross-reference:** S-23. **Wave:** W3 gated changes after baselines.

**Why.** 3,138 main chunks exceed the embedder's 4,096-token limit and are silently truncated (0.79% of main chunks; 0 in standards). CQ-4's plan (`docs/eval-reports/data/2026-11-10-truncation-rechunk/report.md`) shows the re-chunk fix costs about 177k-212k embeddings (against 64,770 chunks held today by the affected papers), re-grounding of 48 ground-truth items, and mixed chunk granularity inside one index; it names raising the embedding server's `--max-batch-tokens` as the alternative it did not assess. The review's rule (d)(2) permits a targeted re-chunk only for information destroyed at embed time, and CQ-4 shows the targeted form is not cheap, so the cheap alternative is assessed first (review S-23, re-scoped).

**Scope.**
- In:
  - Feasibility measurement on a scratch embedder setting, after the operator restarts the embedder container with a higher limit (agents never restart containers): VRAM use, out-of-memory events and p50/p95 latency at the larger limit; then embed the exact truncated chunk list (`truncated_chunk_ids_main.txt`, about 3,136 chunks, minutes of GPU) and report the cosine between each full-length embedding and its stored truncated embedding. Nothing is written to any index.
  - Ceiling statement: none of the 48 affected ground-truth items has a truncated gold chunk (CQ-4), so a retrieval gain on the current fixtures is bounded at 0 by construction; the verdict is feasibility and vector shift, not retrieval quality.
- Out (explicitly):
  - Any re-chunk (see CQ-11: only inside a planned full re-chunk). Writing or replacing vectors in any collection. Restarting containers (operator action).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-embedder-token-limit.md`
- `docs/eval-reports/data/<run-date>-embedder-token-limit/`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton with the feasibility rule written before any run: FEASIBLE if no out-of-memory event and p95 embedding latency for normal chunks stays within 1.5x of today's; INFEASIBLE otherwise
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ limit change requested from the operator; baseline latency and VRAM recorded first
④ truncated-chunk embeddings and cosine table
⑤ report and verdict

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Each embedding call is wrapped by the existing GPU lock; no collection name appears in any write command
- Count of chunks embedded equals the length of the truncated-id list

**Acceptance / falsification criterion.** Report states, for the larger limit: out-of-memory events (0 or not), latency ratio against baseline, and the distribution of cosine shift on the truncated chunks; verdict FEASIBLE or INFEASIBLE by the pre-stated rule. Falsified (INFEASIBLE) if any out-of-memory event occurs or latency exceeds 1.5x.

**Gates / depends on.** Depends on: EV-16, RQ-3. Operator answers: F3. Gates: CQ-11.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F3 · re-embed: n. Also: operator restarts the embedder with a higher limit and restores it afterwards; GPU free (F3); minutes of GPU (estimate).

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** A larger batch-token limit can exhaust VRAM next to the reranker and starve other work. Mitigation: operator-run restart, restore step in the record, one job at a time. Rollback: restore the previous container setting.

**Docs to update in the same PR.** Report; PROJECT-STATUS via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
