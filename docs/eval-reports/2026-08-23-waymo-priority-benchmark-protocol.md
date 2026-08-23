# FROZEN benchmark protocol — Waymo-priority recall/precision target (≥95%)

Written 2026-08-23 **before** any GT-WMR item was authored and before any retrieval-side change.
This document is the target; the measurement that follows it is not free to move. If a definition
here turns out to be wrong or unmeasurable, the fix is a dated addendum that says what changed and
why — never a silent redefinition after seeing numbers.

## Motivation and honesty constraint

The operator set the goal: recall and precision ≥ 95% on the Waymo corpus, with the
[waymo.com/safety/research](https://waymo.com/safety/research/) papers (55 publications, 53
ingested — see `fixtures/eval/waymo_safety_research_55_resolution.json`) as top priority. The
target must exist before implementation work so the system cannot be tuned toward the specific
questions it will be judged on ("hacking our way there"). Therefore:

1. Item-authoring rules are fixed here (§5) and were written without inspecting any retrieval
   output for those items.
2. The first measurement against this protocol is the baseline, published regardless of how
   unflattering it is. Improvements afterwards are new tickets judged against these numbers.

## Ground-truth fixtures

| fixture | role | n | note |
|---|---|---|---|
| `waymo_gt_verified.json` | full-corpus arm | 84 (82 scored) | pass-2 verified union of GT-A + GT-B |
| `fixtures/eval/gt_wmr.json` *(to be built)* | priority arm | ≥55 | answerable items drawn from the 53 ingested priority papers |

Duplicate handling: records carrying `duplicate_of` are excluded from all aggregate denominators
by default (`load_questions(include_duplicates=False)`, the default). Each duplicate_of group is
counted once.

## Metric definitions (frozen)

All metrics are computed by `app/retrieval_eval.py` in its shipped state at freeze time
(commit of this commit), modes: `fused` (shipped config), `dense` (dense-only ablation),
`sparse` (sparse-only diagnostic). k = 10 primary; R@5 recorded alongside.

- **Recall@k (paper-level)** — over ANSWERABLE items only (gold paper set nonempty): a query
  scores a hit at rank r when any retrieved result's `paper_id` ∈ gold set (source ∪ additional ∪
  supporting), gold-ranked by best (lowest) such r. Headline: fraction of answerable queries with
  a hit in the top-k.
- **Precision@k (paper-level)** — over ANSWERABLE items only: |top-k results ∩ gold papers| / k,
  macro-averaged over queries. This measures purity of what the system serves for questions it
  can answer.
- **Known-absent arm (reported, never blended)** — absent items have ∅ gold by construction, so
  they are excluded from recall/precision denominators *by design, not to inflate them*: with no
  abstention mechanism every return is irrelevant-by-definition and precision would be structurally
  capped near (N−N_absent)/N regardless of retrieval quality (RI-M7 pass-1 measured exactly this:
  answerable vs known-absent score distributions do not separate, so no honest threshold exists).
  For each absent item we report: top score, mean score, whether a top-10 was returned (always,
  today). The abstention gap is thus measured and displayed next to the headline, not hidden.
- **MRR@10** recorded as diagnostic, not gated.
- **Chunk-level P@10** where `gold_chunk_id` exists: fraction of the top-10 whose chunk_id or
  block_id matches the item's gold chunk/block. Diagnostic only (gold chunks are one of several
  supporting passages in some items).

## Targets (the number the operator set)

| gate | metric | subset | target |
|---|---|---|---|
| A | Recall@10, fused | GT-WMR priority answerable | ≥ 0.95 |
| B | Precision@10, fused | GT-WMR priority answerable | ≥ 0.95 |
| C | Recall@10, fused | verified-84 answerable (82-scored minus its own absent) | ≥ 0.95 |
| D | Precision@10, fused | verified-84 answerable | ≥ 0.95 |

Dense-only and sparse-only arms are reported for the same subsets as ablations. Failure of any
gate is an acceptable outcome of the protocol — it becomes the ranked-work list for closing the
gap, judged against these exact numbers.

## Known ceiling facts at freeze time (from the merged BENCH-1 baseline)

Recorded here so the first WMR measurement has context, not as excuses: on the verified-73 v1
set, dense-only beat shipped fusion 0.969 → 0.892 R@10 (5 losses, 0 wins, per-question); the
sparse arm contributed nothing dense didn't already have on this corpus; no relevance floor is
separable (abstention impossible today); judge_eval remains unrunnable-by-design (no Judge
implementation; rubric PROVISIONAL/unsigned).

## Item-authoring rules (fixed before authoring)

1. Every ingested priority paper (53) gets ≥ 1 item where its content supports one (papers with
   too little extracted text get their summary-based item instead; a paper skipped entirely must
   be listed with the reason).
2. Answerable single-passage items: `question_text` asks for a fact stated in one chunk;
   `passage_excerpt` MUST be produced by substring extraction from that chunk's stored text (the
   programmatic-resolver pattern), never retyped. Gold ids come from the same row.
3. Numeric preference: where a paper reports numbers, prefer items whose answer is a figure/table
   value or a quantified result, over generic method questions.
4. Absent items (12–18): plausible-in-domain confusables — facts a reasonable reader might expect
   Waymo safety papers to contain but no corpus paper states. Each carries `absence_note` plus an
   `absence_search` log of live-run queries with hit counts, produced during authoring.
5. Vision items (3–6): derived from figures/tables of priority papers (now persisted post-RI-32),
   each with leak checks against both `blocks.text` and `chunks.text` recorded at authoring time,
   and a `vision_scope` classification (`document-image-only` vs `corpus-extraction-gap`).
6. Multi-paper synthesis (≥4): answers requiring ≥2 priority papers, grounded via
   `supporting_passages`.
7. Dimension labels reuse the shared vocabulary; difficulty mix roughly 1:2:1 easy:medium:hard.
8. No item may be authored, edited, or dropped after its author has seen any retrieval result for
   it. Corrections for verifiable factual errors are allowed and logged in the fixture's
   `_metadata.corrections`.

## Measurement procedure

One run, after `gt_wmr.json` passes its invariant suite:

```
python -m app.retrieval_eval --ground-truth fixtures/eval/gt_wmr.json \
    --config waymo/data/config.yaml --collection waymo_av_safety [--mode dense] [--mode sparse]
python -m app.retrieval_eval --ground-truth fixtures/eval/waymo_gt_verified.json ... (same)
```

Results land in `docs/eval-reports/2026-08-23-waymo-priority-baseline.md` with gates A–D
pass/fail and the absent-arm display, committed unmodified.
