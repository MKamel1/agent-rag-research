# Waymo AV-safety baseline — 2026-08-22

Branch `BENCH-1-waymo-baseline`, worktree `/home/omar/ai-projects/research-system-rag/.worktrees/BENCH-1`.
This is a **measurement report**, not a design doc: three instruments run against the real, live
Waymo corpus, numbers recorded as they came back, unflattering ones included. A fourth instrument
(`app/judge_eval.py`) cannot run at all — reported as such, not worked around.

## Environment and collection spot-check

- Qdrant collection `waymo_av_safety`: `status: green`, `points_count: 47893` — matches the
  established count exactly (verified again here, not re-derived).
- `waymo/data/papers.db` (the real corpus, referenced by `waymo/data/config.yaml`'s absolute
  `db_path`/`blob_dir`): `SELECT COUNT(*) FROM papers` → 1738, `SELECT COUNT(*) FROM chunks` →
  46155 — matches the established 1,738 papers / 46,155 chunks.
- Spot-checked a real retrieval hit: question `Q-GTA-001`'s gold `paper_id` `2312.12675` resolves in
  `papers.db` to *"Comparison of Waymo Rider-Only Crash Data to Human Benchmarks at 7.1 Million
  Miles"* — a genuine Waymo safety paper, not a causal-inference paper. Every command below passes
  `--collection waymo_av_safety` explicitly; none relies on `build_mcp_server`'s `papers` default.
- **Operational trap found and worked around, noted for whoever runs this next**: this worktree's
  own `waymo/data/` is empty (`.gitignore`d, 0 papers/0 blobs) — it is a stub, not the corpus. The
  real corpus lives only at the main checkout's absolute path,
  `/home/omar/ai-projects/research-system-rag/waymo/data/`, which is what `waymo/data/config.yaml`
  points at via its absolute `db_path`/`blob_dir`. All commands below pass that absolute
  `--config` path and, for `truncation_census`, an absolute `--data-dir` — a bare relative
  `waymo/data` from inside the worktree silently scans 0 papers.

## Methodology note stated openly

`af8d979` folds every `supporting_passages`/`supporting_sources` paper id into a question's gold
set, so retrieving **any one** co-source on a multi-paper synthesis item counts as a hit. This is
the same multi-gold methodology the 210-question causal eval already uses (`additional_gold_paper_ids`),
not something invented for this run — but it does move the recall number, so it is named here rather
than left for a reader to infer from the JSON.

The two arms are reported **separately, never blended**: `waymo_gt_verified.json`'s 8 known-absent
items have an empty gold set by construction and can never register a hit. An unpartitioned
`overall` exists in every report below for backward compatibility but is not the headline — e.g. for
the fused run, unpartitioned `overall` recall@10 is 0.795 (n=73) vs. the answerable arm's 0.892
(n=65): blending in 8 guaranteed misses costs ~9.7 points that have nothing to do with retrieval
quality.

---

## 1. Retrieval eval + sparse-arm ablation (`app/retrieval_eval.py`)

```
python -m app.retrieval_eval \
  --ground-truth fixtures/eval/waymo_gt_verified.json \
  --config /home/omar/ai-projects/research-system-rag/waymo/data/config.yaml \
  --collection waymo_av_safety \
  --sparse-mode {fused|dense_only|sparse_only} \
  --report-path docs/eval-reports/2026-08-22-waymo-baseline-retrieval-{name}.json
```
(`fused` uses the config's own `hybrid_dense_weight: 0.5`; `dense_only`/`sparse_only` pin it to
1.0/0.0.) Run from the worktree root so `app.retrieval_eval` resolves to this branch's code (the
`af8d979`/`dd2d9bd` fixes) rather than an unpatched copy elsewhere on the machine.

Full JSON: `docs/eval-reports/2026-08-22-waymo-baseline-retrieval-{fused,dense-only,sparse-only}.json`.

### False negatives — answerable arm (n=65), paper-level

| sparse mode | Recall@10 | MRR |
|---|---|---|
| fused (config default, weight=0.5) | **0.892** | 0.828 |
| dense_only (weight=1.0) | **0.969** | 0.841 |
| sparse_only (weight=0.0) | **0.631** | 0.594 |

Passage-level (n=61 of 73 questions carry a `gold_block_id` — the specific chunk, not just the
right paper):

| sparse mode | Recall@10 | MRR |
|---|---|---|
| fused | 0.705 | 0.491 |
| dense_only | 0.820 | 0.529 |
| sparse_only | 0.230 | 0.199 |

**Unflattering finding, reported as measured, not tuned away**: `dense_only` beats `fused` at both
granularities on this corpus and question set. Sparse alone is a real but meaningfully weaker
retriever here (0.631 paper-level recall on its own — not nothing, it's finding roughly two-thirds
of answers through lexical/IDF matching alone), but fusing it in at the config's current 0.5 weight
currently *costs* recall rather than adding to dense's own ceiling, on this fixture. This is exactly
the measurement `--sparse-mode` exists to make possible and it says the current weight is not free
on this corpus — that's an operator decision this report does not make, only surfaces.

Title-leak diagnostic (verbatim-substring floor, not deducted from the metrics above): 51/58 fused
paper-level hits, 56/63 dense-only hits, 36/41 sparse-only hits embed the gold paper's own title.
High across all three modes — a meaningful fraction of "hits" may be riding on title/short-form
lexical overlap rather than passage semantics; this is a floor (paraphrase leaks go uncounted), not
a ceiling.

### False positives — known-absent arm (n=8)

Recall/MRR are undefined here by construction (empty gold set) and are withheld by `build_report`
rather than reported as a misleading zero. What's measured instead: does the retriever return a
top result, and at what score, for a question about something genuinely absent from the corpus.

| sparse mode | n with a top result | top_score median | top_score range |
|---|---|---|---|
| fused | 8/8 | 0.0105 | [0.0072, 0.0146] |
| dense_only | 8/8 | 0.0129 | [0.0109, 0.0159] |
| sparse_only | 8/8 | 0.0138 | [0.0109, 0.0147] |

Every one of the 8 known-absent questions gets a confident-looking top-10 result under every sparse
mode — this is RI-10's absence-honesty behavior working exactly as designed (the system always
returns its best-available top-k) and exactly why a downstream reader needs a way to tell these
apart from real hits, which is what instrument 2 below measures directly.

---

## 2. Score-distribution census (`app/score_distribution_census.py`, RI-M7)

```
python -m app.score_distribution_census \
  --config /home/omar/ai-projects/research-system-rag/waymo/data/config.yaml \
  --collection waymo_av_safety \
  --answerable-ground-truth fixtures/eval/waymo_gt_verified_answerable_split.json \
  --known-absent-path fixtures/eval/waymo_gt_verified_known_absent_split.json \
  --report-path docs/eval-reports/2026-08-22-waymo-baseline-score-census.json
```

The module's *default* known-absent arm (`fixtures/eval/eval_known_absent.json`) names fabricated
causal-inference entities — a construction that hands the lexical/sparse arm a guaranteed
zero-match, which the module's own docstring names as an **upper-bound** caveat on any "separates"
verdict measured against it. **That default arm was not used here.** The two files passed above are
a straight split of `waymo_gt_verified.json`'s own 65 answerable and 8 known-absent items — the
same 8 real questions about real absent facts from instrument 1's known-absent arm, not fabricated
entities. **This run is a direct measurement, not an upper bound**, and it is the more honest of the
two arms this instrument can measure, because it doesn't hand the lexical arm a freebie.

Result:

| arm | n | mean | median | IQR (p25–p75) | range |
|---|---|---|---|---|---|
| known-answerable | 65 | 0.0113 | 0.0113 | [0.0085, 0.0141] | [0.0069, 0.0160] |
| known-absent | 8 | 0.0110 | 0.0105 | [0.0082, 0.0145] | [0.0072, 0.0146] |

**Verdict: the distributions do NOT separate.** The known-absent IQR sits almost entirely inside the
answerable IQR. **No relevance floor is choosable from this measurement** — the standing RI-10
rejection (proposed and rejected during the RI review; see
`docs/superpowers/plans/2026-08-22-review-implementation.md`, RI-10) is reaffirmed, not merely left
unchallenged. Because this was measured against the *real*, non-fabricated known-absent arm, this
"does not separate" verdict carries **none** of the instrument's own upper-bound caveat — a real
uncovered topic was exactly what was measured, and it still overlaps the answerable distribution.
(Had the result instead been "separates," it would have needed reading through that caveat; it did
not separate, so the caveat doesn't apply in either direction here.)

---

## 3. Truncation census (`scripts/truncation_census.py`, RI-M4)

```
python -m scripts.truncation_census \
  --data-dir /home/omar/ai-projects/research-system-rag/waymo/data
```

Full output (includes one log line per truncated paper): `docs/eval-reports/2026-08-22-waymo-baseline-truncation-census.txt`.
1,738 papers scanned — matches the corpus count.

| ceiling | bound | bind rate | dropped |
|---|---|---|---|
| reranker item ceiling (`_MAX_ITEM_TOKENS`) | 1 / 46,155 chunks | 0.0% | 2,486 tokens (one chunk, its `REFERENCES` section) |
| reranker batch-budget pressure (`_MAX_BATCH_TOKENS`, drops nothing — forces an extra HTTP call) | 33,958 / 46,155 chunks | 73.6% | 0 (by definition) |
| summarizer whole-document ceiling (`_NUM_CTX_CEILING`) | 1,669 / 1,738 papers | **96.0%** | **7,982,230 words total** |

**Where truncation actually binds**: not the reranker — its per-chunk item ceiling almost never
fires (0.0%), and its batch-budget pressure, while frequent, drops nothing (it only splits an HTTP
call). The real binding ceiling is the **summarizer**: 96% of papers in this corpus exceed the
summarizer's safe-token ceiling and get truncated to the first 7,356 words before summarization,
with the worst single paper losing over 100,000 words. This is a whole-document paper-summary
pipeline stage, separate from the chunk-level retrieval path instrument 1 measures — it affects
paper-level summaries, not what `Retriever.retrieve()` returns for a question.

`_TOKENS_PER_WORD_ESTIMATE` calibration: **not measured** — this system never captures the
generation server's own real per-unit token count anywhere (the response field that carries it is
read and discarded, `rag/summarizer.py`'s `summarize()`), and no `--real-tokens-json` was supplied.
Every bind-rate number above is measured against an *estimate*, not a verified token count; the
instrument says this plainly rather than letting the numbers imply more precision than they have.

---

## 4. Judge/groundedness harness — cannot run

`app/judge_eval.py`'s `--judge-factory` argument is `required=True` (`app/judge_eval.py:247`), and
`Judge` is only a `Protocol` (`app/judge_eval.py:87`) — **no concrete implementation exists anywhere
in the repo**. The only thing satisfying that protocol is `FakeJudge`, a test double with canned
verdicts (`app/test_judge_eval.py:22`), used exclusively by the unit suite. Confirmed by actually
invoking it:

```
$ python -m app.judge_eval --rubric docs/eval-rubrics/groundedness-rubric.md
usage: judge_eval.py [-h] [--ground-truth GROUND_TRUTH] --rubric RUBRIC
                     --judge-factory JUDGE_FACTORY [--limit LIMIT]
                     [--report-path REPORT_PATH]
judge_eval.py: error: the following arguments are required: --judge-factory
```

Separately, even if a judge existed: the rubric it would score against
(`docs/eval-rubrics/groundedness-rubric.md:3`) is explicitly marked **"PROVISIONAL — not a
baseline. Nobody has signed off on this rubric yet"**, and `docs/BACKLOG.md:107` records the same
status for RI-M6. Building a throwaway `Judge` to force a number out of this would produce a score
against an unsigned rubric — worth less than no score, per this ticket's own scope. **Not built.**
Reported as unrunnable, which is the honest output here.

---

## What this says about the gap to a state-of-the-art RAG

Per `docs/superpowers/plans/2026-08-22-openevidence-gap-and-benchmark.md` §4, this is the "only
after the ground truth exists" benchmark step, feeding the relevance-floor question (§4.3) and the
false-negative/false-positive split (§4.2) the plan calls for.

- **§4.3, relevance floor — settled, not deferred a third time.** The plan expected RI-M7 to "settle
  the relevance-floor question that has been deferred twice." It does: measured against the real
  (non-fabricated) known-absent arm, the score distributions do not separate. This is a direct
  measurement, stronger than what the plan anticipated (it expected only an upper-bound read from
  the fabricated default arm). The architectural conclusion is unchanged from RI-10: this system
  cannot honestly refuse a question by score threshold alone; absence-honesty has to keep being a
  presentation/prompting concern, not a retrieval-layer gate.
- **§4.2, false-negative / false-positive split — done, and it's asymmetric in an informative way.**
  The false-negative side (answerable-arm recall) is respectable at fused (0.892) and better at
  dense-only (0.969). The false-positive side shows the retriever is *confidently* wrong on
  known-absent questions — full top-10 results, scores overlapping the answerable distribution — so
  a downstream consumer cannot lean on "did it return something" as a proxy for "is this real."
  Whatever surfaces answers to users has to carry that asymmetry forward (grounded citations,
  verbatim passages) rather than papering over it with a confidence number this corpus doesn't
  support.
- **§1's architecture-parity claim gets a data point, not just an audit.** The gap-analysis section
  claims retrieval architecture is "essentially at parity" with SOTA (hybrid dense+sparse, RRF
  fusion, cross-encoder rerank) and names late-interaction retrieval as the single highest-value
  upgrade available. This run's sparse-arm ablation is a concrete reason to believe that upgrade
  path, not just the architecture checklist: sparse alone recovers real signal (0.631 paper-level
  recall on its own) that dense doesn't fully cover, but the current RRF fusion weight (0.5) is
  *not* extracting the best of both — dense_only beats fused outright here. A fine-grained,
  per-token matching layer (ColBERT-style, `PRD.md:657`) is the kind of upgrade that could resolve
  this without giving up what sparse contributes; right now the fusion weight is leaving recall on
  the table in a way this baseline makes visible and future work can be judged against.
- **Truncation is real but off the critical retrieval path.** 96% of papers hit the summarizer's
  document-level ceiling — a substantial, previously-unmeasured cost — but it sits in the
  paper-summary pipeline, not in what `Retriever.retrieve()` returns for a question. It doesn't
  explain today's recall gap; it's a separate, now-quantified cost of the current summarization
  design worth its own ticket.
- **The groundedness/fabrication axis remains completely unmeasured.** `app/judge_eval.py` has no
  runnable judge and an unsigned rubric — so nothing in this report speaks to whether the *answers*
  this system would generate over these retrieved passages are faithful to them. Retrieval quality
  and answer faithfulness are different gaps; this baseline only closes the first one.

---

## Verification

- `python -m ci.run_enforcement --local main` (from repo root, `PYTHONPATH` set): 
  `enforcement: PASS -- no violations in checks (a)-(d), (f)-(h), testpaths`
- `python -m pytest -p no:cacheprovider`: `2021 passed, 39 deselected in 102.25s (0:01:42)`

## Commits

- `c030509` — RI-M7 score-distribution census result for waymo_av_safety
- `a9c5e98` — truncation census result for waymo_av_safety corpus
- `ae07238` — full retrieval_eval + sparse-arm ablation results for waymo_av_safety

All on `BENCH-1-waymo-baseline`, not pushed, no PR opened.
