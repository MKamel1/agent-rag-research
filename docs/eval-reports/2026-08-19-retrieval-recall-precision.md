# Making enumeration questions answerable — measurements

*2026-08-19. Five changes aimed at "which papers did X" questions, and the measurement that killed
one of them.*

## The problem

An audit of the Waymo corpus asked "which papers used bootstrap or resampling?" Semantic retrieval
found **3 of 4** qualifying papers. The miss (`2312.12675`) was not an index failure — the paper is
retrievable, and a later query returned it at k=10. It was a *structural* failure: top-k answers
"what are the best k passages", and an enumeration asks "which papers satisfy a predicate". Three
measured mechanisms make the first unable to answer the second.

| mechanism | evidence | effect |
|---|---|---|
| `_RERANK_POOL_SIZE = 32`, clamped in `app/assembly.py` because `TeiReranker` truncated oversized batches | `--k 60` returned **32** passages | at most 32 papers can appear in any one answer |
| `_cap_per_paper` applied only in `retrieve_papers()`, never in `retrieve()` | one paper took **13 of 30** slots | a verbose paper starves the result set |
| ranking is per-passage relevance | `2312.12675` states its bootstrap use in one plain sentence | a brief real USE ranks below a lengthy discussion |

## What shipped

1. **`TeiReranker.rerank()` chunks instead of truncating.** Cross-encoder scores are absolute
   per-(query, document) values, not normalised per request, so scores from separate batches are
   comparable and a global sort reproduces what one oversized call would have returned. Previously
   any batch over 32 was silently cut, which is why `k > 32` never worked.
2. **The `app/assembly.py` clamp is gone**, so `Config.rerank_depth` is a real lever rather than a
   value the composition root quietly overrode.
3. **`SearchFilters.max_hits_per_paper`** — opt-in per-paper diversity on the passage path.
4. **`scan_corpus` MCP tool** — exhaustive lexical enumeration, recall 1.0 by construction. With
   `paper_id` set it is also the full-text lookup that retrieval cannot do (see §"Definitions").
5. **Drop-in data quality** — junk titles 35 → 0, empty abstracts 259 → 79.

## The measurement that changed the plan

Removing the clamp let `rerank_depth: 50` (what the configs already said) actually take effect. That
looked like a straight recall win. It was not.

| 210-question eval, causal corpus | Recall@10 | MRR |
|---|---|---|
| pool 32 (what the clamp had silently enforced) | **0.976** | **0.919** |
| pool 50 (what the config claimed) | 0.967 | 0.911 |

**2 questions lost, 0 gained.** `Q-122` fell from rank 10 and `Q-184` from rank 8 — both marginal
hits, displaced out of the top 10 by candidates the larger pool newly admitted and the cross-encoder
scored above them.

**More candidates is not more recall.** The reranker's scores are not sharp enough to order 50
candidates correctly; near the top-k boundary the extra ones are noise, and noise costs the passages
that were only just inside. `rerank_depth` is therefore set to **32** — now an explicit measured
value rather than an accidental vendor artifact — in `config.example.yaml` and both live corpus
configs.

### Confirmed behaviour-preserving

Re-run after setting `rerank_depth: 32`, against the same 210 questions:

| run | Recall@10 | MRR |
|---|---|---|
| baseline (before any change) | 0.9762 | 0.9192 |
| **confirmation (all five changes shipped)** | **0.9762** | **0.9192** |

Not merely equal in aggregate — **bit-identical per question**: 0 lost, 0 gained, and not one
question's rank changed. That is the stronger claim, and it is the one worth making, because equal
averages can hide offsetting wins and losses. At a pool of 32 the reranker sends exactly one batch,
so the new chunking path reduces to the old single-call path, and the measurement confirms it rather
than assuming it.

The batching change is kept regardless, because it fixes a real defect independently of the default:
a caller passing `k > 32` previously got a silently truncated result set. It also makes the knob
honest — a value above 32 now does what it says, for a workload that wants it.

**Raising the pool is still right for an enumeration workload**, where seeing more distinct papers
matters more than the ordering of the first ten. That is a different objective from what this eval
scores, which is why the tool for enumeration is `scan_corpus`, not a bigger `k`.

## Enumeration, measured

Against the bootstrap audit's ground truth (4 papers that genuinely used resampling):

| method | recall | precision burden |
|---|---|---|
| semantic retrieval, as the audit used it | 3/4 | 0 false positives |
| `scan_corpus` / `DocumentStore.scan_blocks` | **4/4** | 23 candidates to reject |

The two fail in opposite directions: a regex cannot tell a bootstrap *particle filter* from a
bootstrap *confidence interval*, and retrieval cannot prove it surfaced everything. Recall is the
half that cannot be repaired after the fact, so the scan owns stage 1 and adjudication owns stage 2.

`section_path` is what makes stage 2 cheap: a hit under "Related Work" is a citation, one under
"Methods" is a use. It is present for **95.0%** of blocks in the Waymo corpus (836 of 16,801
missing) — and absent for **61.7%** of `2604.03827`, the single most methodologically important
paper for that audit. It is a hint, never an automatic exclusion.

## Definitions are a lookup problem, not a retrieval problem

Six differently-phrased queries failed to establish that "EB" in `2604.03827` meant *exponential
bootstrap* and not *empirical Bayes* — a misreading that would have produced a false headline
finding. Both defining sentences sit in the abstract and the methods section. They never ranked,
because a definitional aside is topically dominated by the mathematics around it.

`scan_corpus(pattern="exponential bootstrap", paper_id="2604.03827")` returns them as the first
result. No amount of query rephrasing was going to fix this; it is the wrong tool applied to the
question.

## Known, not fixed

`reranker server returned 413` on `Q-158` in both runs. That is a payload-**bytes** limit, distinct
from the batch-**count** limit fixed here, and it predates these changes. It silently drops a
question from every eval run. Worth fixing separately.
