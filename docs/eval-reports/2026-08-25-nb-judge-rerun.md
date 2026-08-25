# Fabrication-audit judge re-run under the amended signed rubric (NB-JUDGE-RERUN)

> **STUB — work in progress.** Committed before any run work per the next-build programme's
> Global Constraint #1 (commit 1 is a stub committed before any real work; a dead dispatch must
> be resumable from committed state with zero loss). Numbers below are placeholders until the
> runs land; every number in the final version will come from the committed raw JSONs beside it.

## What this run is

The re-run owed by Decision B (programme plan §1) and recorded in the amended rubric's SIGNED OFF
header: the 2026-08-23 fabrication audit ran under rubric hash `d82bbfa36155` (48-line wording);
the rubric was then amended (F-A1 split rule, F-A2 subject-binding, F-A3 several-passages — see
`docs/eval-rubrics/2026-08-24-fabrication-rubric-review.md`) and signed off 2026-08-25. By the
reports' own rule, amending the text changes `rubric_sha256_12`, so **one re-run is owed under the
new wording before any fabrication-audit number is treated as a trend. This ticket is that re-run.**

## Setup — mirrored from the provisional run for procedural comparability

| | |
|---|---|
| audited population | the SAME captured generation run: `fixtures/eval/runs/2026-08-23-waymo-generation-run.{answerable,absent}.json` (68 answerable / 16 known-absent records with their captured `answer_text` + retrieved `supporting_passages`) — no new generation |
| generation model / prompt | unchanged from 2026-08-23 (`qwen3:14b`, no-refusal-affordance prompt, verbatim in the provisional report) — only the JUDGE side re-runs |
| judge model | `qwen3-14b-16k:latest` via local Ollama (`--judge-factory app.judge_llm:factory`, unmodified) |
| rubric | `docs/eval-rubrics/fabrication-audit-rubric.md` as committed on this branch — expected hash `4add354fe464`, verified ≠ `d82bbfa36155` |
| harness | `python -m app.judge_eval --ground-truth <arm JSON> --rubric docs/eval-rubrics/fabrication-audit-rubric.md --judge-factory app.judge_llm:factory` |
| GPU lock | shared cross-process lock honored (sibling lanes may queue ahead) |

## Raw artifacts (this directory's data/)

- `data/2026-08-25-nb-judge-rerun/2026-08-25-waymo-fabrication-audit.absent.json`
- `data/2026-08-25-nb-judge-rerun/2026-08-25-waymo-fabrication-audit.answerable.json`

## Questions this report must answer when complete

1. Headline rates under the new wording, both arms separately with denominators, explicitly marked
   **NON-COMPARABLE-BY-HASH** against the 2026-08-23 numbers (same population ≠ same instrument).
2. The named question of record: does F-A2's subject-binding now surface the Q-GTA-037 /
   Q-GTA-040-class wrong-side answers in `unsupported_claims`? Checked item-by-item.
3. F-A1 compound-split and F-A3 multi-passage attribution: verdict changes vs the old run on items
   those rules touch.
4. Judge-behavior caveats per the review's "What this review could not assess" section — wording is
   not compliance; measured, not assumed.

## Status

- [ ] Stub committed (this commit)
- [ ] Absent arm run + hash verified
- [ ] Answerable arm run + hash verified
- [ ] Analysis written
- [ ] Final report committed
