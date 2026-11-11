Title: CQ-11: Decide the truncation fix: limit change or only inside a planned full re-chunk
Labels: wave:3-gated-change, area:corpus, area:eval, size:S

## CQ-11 -- Decide the truncation fix: limit change or only inside a planned full re-chunk

**Review cross-reference:** S-23. **Wave:** W3 gated changes after baselines.

**Why.** With CQ-4's costs on record, a re-chunk of only the truncated chunks is not justified on its own (about 177k-212k embeddings, 48 ground-truth items to re-ground, mixed granularity). The only remaining routes are a server limit change (CQ-10) or folding the truncation fix into a full re-chunk that passes the review's paired chunker test, rule (d)(3) (66 papers, two scratch collections, about 45k embeds, at least +5 net excerpt hits, flips at least 3:1, 2x disk headroom).

**Scope.**
- In:
  - A short decision note: if CQ-10 is FEASIBLE, recommend the limit change to the operator and list which stored vectors would be recomputed (only the truncated chunks, about 3,136 for main; a bounded job, specified but not run); if INFEASIBLE, record that the truncation defect waits for a full re-chunk decision and is not re-proposed separately. No GPU.
- Out (explicitly):
  - Running any re-chunk or re-embed. Re-grounding fixtures. A full re-chunk test (not part of this programme).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-truncation-fix-decision.md`

**Commits** (① is a stub, committed before any real work):
① stub: note skeleton with the two branches and the facts each cites (CQ-4 report, CQ-10 verdict)
② decision text
③ cross-check that every cited number resolves to a file

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every number in the note appears in CQ-4's report or CQ-10's report (grep list in the PR)

**Acceptance / falsification criterion.** Note states one recommendation, derived mechanically from CQ-10's verdict, with costs from CQ-4 quoted exactly; someone who did not write it can trace each figure. Falsified if a quoted figure is absent from its source report.

**Gates / depends on.** Depends on: CQ-10. Gates: CQ-15, EP-5.

**Needs.** GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; S (up to 2 h of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Low. Docs only. Rollback: revert.

**Docs to update in the same PR.** Note is the doc; PROJECT-STATUS section 5/6 via EP-5. Programme batching rule (plan section 4, rule 13): this ticket does not edit PROJECT-STATUS.md or BACKLOG.md; EP-5 carries those entries from this ticket's merged SHA.
