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

## Diversity: additive beats subtractive, measured

`max_hits_per_paper` caps hits per paper. It is SUBTRACTIVE -- it deletes passages to make room --
so a gold passage ranked 5th inside its own paper is gone under a cap of 3, and nothing in the
response says so. `min_distinct_papers` reaches the same goal by ADDING: it keeps the top `k` exactly
as ranked and appends the best not-yet-seen passage from further papers.

60 real eval questions, k=10, against the causal corpus:

| mode | gold found | distinct papers | result size | **passages lost vs plain** |
|---|---|---|---|---|
| plain (uncapped) | 60/60 | 3.92 | 10.00 | 0 |
| capped, `max_hits_per_paper=2` | 60/60 | 8.58 | 10.00 | **298** |
| additive, `min_distinct_papers=8` | 60/60 | 8.00 | 14.08 | **0** |

**The cap destroyed 298 passages** across 60 questions -- about 5 per question -- that the plain
query had returned. The additive form destroyed none, which is a guarantee of its construction
rather than a property of this sample.

### What this does NOT show

**Paper-level gold recall was 60/60 for all three.** The cap's 298 deletions did not cost a single
gold *paper* here, and it would be dishonest to claim otherwise. The reason is granularity: this
ground truth scores whether any passage from the right paper was returned, so deleting a paper's
2nd-best passage is invisible as long as its best one survives. The cap's danger lives at
passage level (`gold_block_id`), which the 210-question set does not carry -- see this runner's own
docstring on that gap.

So the finding is: **the cap demonstrably destroys evidence, and this fixture cannot see the cost.**
That is a reason to prefer the form that cannot destroy evidence at all, not a reason to believe the
cost is zero.

### The honest trade

The additive form is not free and not superior on every axis:

| dimension | vs. the cap |
|---|---|
| passages lost | **strictly better** -- zero, by construction |
| distinct papers | comparable (8.00 vs 8.58; the additive target is exact and configurable) |
| response size | **worse** -- 14.08 vs 10.00, a 41% larger result set |

It converts a silent loss into a visible cost. A caller on a fixed context budget is now spending
tokens deliberately instead of having a cap discard evidence on its behalf without telling it. Both
fields remain available; `min_distinct_papers` is the one to reach for by default.

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

## The 413, and why batching by item count was only a third of the fix

`reranker server returned 413` on `Q-158` in every run, including the first two here. It predated
these changes, and the first instinct -- "a payload-size edge case, worth doing separately" -- was
wrong on both counts. It is neither an edge case nor separate.

TEI enforces **three** limits, read live from the deployed container (`GET /info`):

| limit | value |
|---|---|
| `max_client_batch_size` | 32 items |
| `max_input_length` | 8192 tokens per (query, document) pair |
| **`max_batch_tokens`** | **16384 for the whole request** |

Batching by item count respects only the first. 32 items sharing a 16384-token budget is ~512 tokens
each -- and measured over 20k chunks, the **causal corpus's median chunk is ~566 estimated tokens**,
so a full batch runs ~18,100 against the ceiling. **The median case exceeded the limit.** The Waymo
corpus (median ~400) merely sits under it more often, which is why this never surfaced during the
Waymo work. 413 is correctly non-retryable -- resending an identical oversized batch fails
identically -- so the affected question was dropped outright on every run.

The fix packs against the token budget, counting the query **once per candidate** (each pair
re-tokenises it; forgetting that is how a batch that looks under budget still 413s) and truncating
any single document at the model's own `max_input_length`, which is lossless because TEI truncates
there server-side regardless.

Verified against live TEI: 32 real corpus chunks estimated at **54,411 tokens, 3.3x the limit**,
now pack into 5 requests and return all 32 candidates.

### It was a recall bug, not a plumbing bug

| run | Recall@10 | MRR | errors |
|---|---|---|---|
| baseline | 0.9762 | 0.9192 | 2 |
| **with token-budget packing** | **0.9857** | **0.9264** | **0** |

**0 questions lost, 2 gained** (`Q-116`, `Q-158`), and `Q-158` now returns its gold paper at
**rank 1** -- it was always a strong match, it just never got scored because the batch died before
reaching it. A silent infrastructure limit was costing real answers, and it looked like a corpus gap
rather than a bug, which is the reason to chase 413s rather than route around them.
