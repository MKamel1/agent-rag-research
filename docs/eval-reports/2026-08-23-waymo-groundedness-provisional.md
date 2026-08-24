# Waymo groundedness audit — provisional, first run (JUDGE-1)

> **PROVISIONAL. NOT A BASELINE.** This is one fallible judge model's reading of one
> **unapproved, unsigned-off rubric** (`docs/eval-rubrics/groundedness-rubric.md`) applied once to
> `fixtures/eval/waymo_gt_verified.json`. That rubric's own header states plainly that sign-off
> "belongs to a human, not to whoever last edited this file" — this run does not change that, and
> nothing below should be read as a target, a regression gate, or a number future work is expected
> to beat. Treat every rate in this document the way you would treat a single noisy measurement:
> informative about where the risk sits today, not a ground truth about the system's quality.

## What this is

The first-ever run of `app/judge_eval.py` (RI-M6, groundedness) against a real judge model,
following JUDGE-1's brief: build the missing `Judge` implementation and measure the axis this
system has never had a number for.

## The judge

**Adapter:** `app/judge_llm.py::LlmJudge`, wired in via `--judge-factory app.judge_llm:factory`.
Same construction as `rag/summarizer.py`/`rag/contextual_header.py` (injected `httpx.Client` +
`GpuLock` + model name); tested offline in `app/test_judge_llm.py` against a mocked transport, no
live model in the test suite.

**Model: `qwen3-14b-16k:latest`**, served locally. Chosen over the two other available options
(`qwen38:160k`; `hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M`) for a measured, not guessed, reason:

- Before picking a context budget, the 64 auditable items in this fixture were measured directly
  — the largest single item (question + all passages + answer combined) is **228 words** (≈500
  tokens at this repo's own measured ~2.2 tokens/word, `rag/summarizer.py`). Adding the rubric text
  (~490 words, ≈700 tokens) and prompt scaffolding, the real input ceiling for this task is well
  under 2,000 tokens for every item in this fixture — nowhere near even a plain 4k-context model,
  let alone 16k.
- Given that, the deciding factor was *not* context size (all three models have plenty) but
  latency: this run needed to make ~84 sequential calls to a single-GPU-serialized model. The
  14B model completed the answerable arm (64 calls) in a few minutes; the 27B quantized option
  would cost meaningfully more wall-clock per call with no prior evidence in this repo that it
  judges groundedness any better, and `qwen38:160k`'s larger context is pure unused headroom for
  inputs this small. `qwen3-14b-16k:latest`'s explicit context tag was picked as generous,
  measured insurance (not a guess) against a verbose multi-claim JSON response, while staying the
  cheapest of the three to run 84 times.
- The adapter itself configures a **fixed `num_ctx=8192`** (not the model's full 16k) — a fixed
  ceiling generous enough for the measured 500-token maximum plus rubric and prompt overhead,
  same reasoning `rag/contextual_header.py` already uses for its own fixed ceiling rather than
  per-item dynamic sizing (this task's inputs don't vary enough to earn that complexity).
- `think: False`, matching `rag/summarizer.py`/`rag/contextual_header.py`'s existing convention:
  this Ollama-based v1 stack shares one token budget between reasoning and the answer with no way
  to protect the answer's share, a documented failure mode in this repo already (a thinking-enabled
  call can spend its whole budget "thinking" and return no answer at all) — a worse failure mode
  for a *measurement* than losing the reasoning trace. Worth revisiting once ADR-09's planned vLLM
  migration ships a real `thinking_token_budget`.

## Exact commands run

```
python -m app.judge_eval \
  --ground-truth fixtures/eval/waymo_gt_verified.json \
  --rubric docs/eval-rubrics/groundedness-rubric.md \
  --judge-factory app.judge_llm:factory \
  --report-path docs/eval-reports/2026-08-23-waymo-groundedness-provisional.json
```

Rubric stamp: `sha256:ab502229362f` (see `rubric_sha256_12` in the JSON report — any future run
under edited rubric wording will carry a different stamp and must not be compared to this one
without noting that).

## 1. Groundedness on the answerable arm

`fixtures/eval/waymo_gt_verified.json` has **68 answerable records**. `load_items()` (the
harness's existing loader, unmodified) could only build an `AuditItem` for **64 of the 68** —
4 (`Q-WAYB-027`, `Q-GTA-042`, `Q-GTA-043`, `Q-GTA-044`) are `vision_derived: true`: their gold
answer was extracted by a human reading a rendered PDF page (a figure or table), so the record
carries `answer_text` but no `passage_excerpt` at all — there is no text passage for a text-only
judge to compare the answer against, and `load_items()` correctly skips them (a warning names each
one) rather than fabricating a passage. This is a real gap in what this harness can audit, not a
bug in this run: a vision-derived groundedness judge is a different, unbuilt instrument.

Of the 64 items the judge actually ran on, **1 errored** (`Q-WAYB-019`): the model's raw response
was JSON with a genuine syntax bug — a missing comma between two claim objects in the array — so
`json.loads` correctly rejected it and `run_audit` recorded the item as an error rather than
guessing at a repair. This is a **judge reliability finding in its own right** (see §3) and is
excluded from the claim counts below, exactly as `build_report`'s existing "omit errored items"
behavior (already unit-tested in `app/test_judge_eval.py`) requires.

**63 items scored, 210 claims extracted.**

| Verdict | Count | Rate (of 210 claims) |
|---|---:|---:|
| supported | 128 | 0.610 |
| unsupported | 81 | 0.386 |
| contradicted | 1 | 0.005 |

Read this claim-level, not item-level: an item with 4 fully-supported claims and an item with 1
supported claim out of 4 both count as "1 auditable item" but pull the claim-level rate in very
different directions — the item-level summary (63/64 = 98.4% of attempted items produced at least
one claim) says nothing about how grounded any one answer actually was, which is why the harness
retains claim text, not just item counts.

**Read the "unsupported" number as noisy in both directions**, not as a clean fabrication rate —
and this run's own spot-check (§3) shows a concrete instance of why. Two things are folded into
it that a text-only claim can't separate:
- A gold reference answer in this fixture is sometimes richer than the single `passage_excerpt`
  chosen to ground it (that excerpt is *a* supporting passage, not necessarily *the entire*
  textual basis for every clause in the answer) — several spot-checked "unsupported" claims were
  specific numbers genuinely absent from the supplied excerpt even though the excerpt correctly
  supports the surrounding claim (§3 has examples). That matches the rubric's own stated
  calibration (`groundedness-rubric.md`'s "unsupported... even if the claim happens to be true in
  general") — a real, correctly-flagged gap between "what this passage grounds" and "what the full
  answer asserts," the rubric working as designed, not the judge inventing a problem.
- At least one case (§3) shows the judge attributing a claim to the wrong one of several supplied
  passages, which produced a false negative in the other direction. The 0.386 unsupported rate is
  this instrument's reading, not ground truth about how grounded these answers are.

## 2. The known-absent arm (n=16) — could not be run, and here is exactly why

The fixture's 16 known-absent records (`tests: "absent"`) assert that a fact is **not** in the
corpus. Every one of them carries `question_text` and `absence_note`, but **none of them carries
`answer_text` at all** — verified directly (`answer_text is None` for all 16, not merely missing
`passage_excerpt`). `load_items()`'s existing skip logic (already unit-tested in
`app/test_judge_eval.py::test_load_items_skips_known_absent_records_that_have_no_answer_to_audit`)
fires on every single one, logging `no answer_text to audit` — confirmed in this run's own log,
all 16 IDs present.

**This is not a fixable gap in the harness or a bug to patch around — it reflects what this
ground-truth file actually contains.** `load_items()`'s own docstring is explicit about what
`answer_text` stands in for: "the text a real generation run produced." No real generation run
has ever been captured for these 16 questions in this fixture, because **this repository's own
system is a retrieval-only MCP server** (`app/serve.py`: `search_papers`/`semantic_search`/
`get_paper`/`get_span`) — the final natural-language answer to a question is written by whatever
downstream agent calls this server, not by anything in this repo. For the 68 answerable records,
this fixture's `answer_text`/`passage_excerpt` fields stand in for that downstream output on
already-known-good ground truth (per `load_items()`'s own docstring, this is "instruments only,"
not a claim about real generation quality). For the 16 known-absent records, the natural downstream
output would be a claim that the fact is absent — but nobody has actually run a downstream agent
against these 16 questions and recorded what it said, positive or fabricated.

**What it would take to measure this arm, and why this run does not do it:** producing a real
fabrication measurement here requires an actual candidate answer to judge — running the system's
real downstream generation step against these 16 known-absent questions and capturing what it
says (including, most importantly, whether it fabricates a specific-sounding number when the
correct answer is "the corpus does not say this"). That is a materially larger, separate piece of
work — a real generation run, not an eval-harness change — and JUDGE-1's brief is explicit that
fabricating a run is worse than reporting nothing. So: **0 of 16 known-absent items were audited,
by construction of the ground-truth file, not by a limitation introduced in this run.** The
closest true fabrication measurement this system could produce is real but does not exist yet;
this run does not manufacture a substitute for it.

## 3. The judge's own reliability — my own audit

Nine claim-level verdicts were spot-checked by hand against the cited passages (exceeds the
brief's 8-minimum), read-only against `waymo/data/papers.db` where a claim's authenticity itself
was in question. Selection: the run's only `contradicted` verdict (1 exists; checked it), six
`unsupported` verdicts spanning six different questions (not six claims off one item), and two
`supported` verdicts from the very first item run (`Q-GTA-001`).

**8 of 9 agreed. 1 disagreement, and it is the interesting one:**

### Disagreement: `Q-GTA-021`, verdict `contradicted` — should be `supported`

Question: *"Between the original release paper of the 3D-detection dataset and a later sparse-
window transformer paper in this corpus, the published scene split changed. State the split as
each paper reports it."* The answer has two sentences, one per paper. This item supplies two
passages:

- `[1]` (from the *later* SWFormer paper, `2210.07372`): *"The dataset contains 1150 scenes, split
  into 798 training, 202 validation, and 150 test."*
- `[2]` (from the *original* dataset paper, `1912.04838`, via `supporting_sources`): *"Our dataset
  currently consists of 1000 scenes for training and validation, and 150 scenes for testing."*
  (Confirmed read-only against `papers.db`: `chunks.chunk_id = '1912.04838:c2'` exists and its
  text opens with this paper's own title and introduction.)

The judge's flagged claim: *"The original dataset paper reports 1000 scenes for training and
validation plus 150 test scenes (1150 total)."* Its rationale quotes only passage `[1]`'s 798/202
split and calls the claim contradicted. But the claim is explicitly about **the original paper**,
which is passage `[2]` — and passage `[2]` states the 1000/150 split **verbatim**, matching the
claim exactly (1000 + 150 = 1150, consistent with the claim's own parenthetical). The judge
compared the claim against the wrong one of the two supplied passages rather than the one that
actually corresponds to it. Correct verdict: `supported`.

This is the run's *only* contradicted verdict (1/210, 0.5%), and on inspection it is wrong in the
specific way "compares a multi-passage claim against the wrong passage" — worth treating as a real,
observed failure mode of this judge/prompt combination on multi-passage items, not a one-off. The
groundedness rubric's own "not a second fabrication audit" section anticipates the judge being
imperfect; this is a concrete instance, found by hand, not inferred.

### The eight agreements (brief)

- `Q-GTA-002` (unsupported): claim reasons from a wide confidence interval to "not statistically
  significant... low mileage" — neither the phrase nor that specific reasoning appears in the
  passage. Agreed unsupported under the rubric's stricter-than-fabrication-audit calibration.
- `Q-GTA-003` (unsupported): the specific figure "19,002 million VMT" is nowhere in the passage.
  Agreed.
- `Q-GTA-004` (unsupported): passage confirms the Nelson (1970) method is more conservative than a
  bootstrap alternative, but never says it is "based on a Poisson model" — that added detail isn't
  grounded. Agreed (borderline: the "method was used" half of the claim is arguably supported, but
  the compound claim as extracted includes an ungrounded detail, and the rubric doesn't ask the
  judge to split a claim mid-sentence).
- `Q-GTA-005` (unsupported): the cited passages describe the *earlier* 7.1M-mile study's numbers
  only; the claimed 56.7M-mile follow-up's 65% figure appears in neither passage. Agreed.
- `Q-GTA-006` (unsupported): passage confirms the *direction* (a significant increase in Phoenix)
  but not the specific magnitude (+117%, CI 11–281%) the claim states. Agreed under the rubric's
  "specific numbers... must match" bar.
- `Q-GTA-007` (unsupported): passage supports the three pre-crash movement category *definitions*
  verbatim but says nothing about the 100%/76%/24% distribution the claim adds. Agreed — though
  this also shows the judge extracting one compound claim covering both a grounded and an
  ungrounded half, the same granularity issue as `Q-GTA-004`.
- `Q-GTA-001` claims 1–2 (supported): "0.6 incidents per million miles for the ADS" and "2.80 IPMM
  for the human benchmark... all locations together" both appear near-verbatim in the passage.
  Agreed, trivially.

**What this audit does and does not establish about the judge:** 8/9 agreement on a small hand
sample is not a calibration study, and the one disagreement found is specifically the
multi-passage-attribution failure mode — items with exactly one supplied passage were not observed
to have this problem in this sample. An operator relying on this judge for anything beyond a
provisional read should not assume the 0.5% contradicted rate is trustworthy at face value; this
sample shows it can be too low (a real contradiction reported as none) as much as it can be too
high.

## What this run does and does not establish

**Does:**
- Proves the `Judge` seam now has a real, tested implementation (`app/judge_llm.py`) that a
  fabrication-audit run (`docs/eval-rubrics/fabrication-audit-rubric.md`) can reuse unchanged —
  the harness is rubric-parameterized by design.
- Produces this system's first-ever groundedness numbers, with denominators, on the 64 of 68
  answerable items this text-only harness can reach.
- Surfaces two concrete, unfakeable gaps: 4 answerable items this judge structurally cannot reach
  (vision-derived, no text passage) and 16 known-absent items this fixture never captured an
  answer for (no downstream generation run exists to judge).
- Finds, by hand, a real judge failure mode (multi-passage misattribution) worth carrying into any
  future prompt iteration — once that iteration is itself an approved change, not a quiet
  "improve the number" edit (explicitly out of scope for this run).

**Does not:**
- Does not establish a baseline. The rubric that produced these numbers is unsigned-off by design;
  see this document's own header and `docs/eval-rubrics/groundedness-rubric.md`'s.
- Does not measure fabrication on questions the corpus cannot answer — the known-absent arm is
  0/16, not a low number, and §2 explains why that gap is structural to this fixture, not a defect
  in this run.
- Does not tell you whether 0.386 "unsupported" is bad. Some of that is the rubric correctly
  penalizing an answer that's richer than its cited excerpt (§1); some of it may be judge error in
  the other direction not caught by this run's 9-item spot-check. Reading it as "39% of claims are
  fabricated" would be wrong on this evidence.

## Verification

- `PYTHONPATH=. python -m ci.run_enforcement --local main` → PASS (no violations in checks
  (a)-(d), (f)-(h), testpaths; check (e) not run locally, needs PR labels).
- `python -m pytest -p no:cacheprovider` → `2139 passed, 39 deselected in 102.81s (0:01:42)`
  (baseline 2121 + the 15 new `app/test_judge_llm.py` tests + a small number of tests added by
  other work already on `main` ahead of this branch's fork point; zero failures either way).
