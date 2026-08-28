# QW-3 — reranker-seat A/B: shipped BGE vs. Qwen3-Reranker-0.6B

Precision-95 programme. Measure-before-adopt experiment, branch `P95-QW3-reranker-seat`. No
config was flipped in the shipped system — every number below comes from a throwaway harness
(`app/exp_nb_rr_qwen_reranker.py`) driving the existing dual-fixture reuse seam
(`scripts/nb_eval_runner.py` → `app/retrieval_eval.py`), unmodified.

**Verdict: REJECT**, on both fixtures, without averaging. See §8.

Every number in this report is a field of one of the committed JSONs under
`docs/eval-reports/data/2026-08-28-qw3/` — none is typed by hand. File map at the end.

## 0. Hosting decision

Qwen3-Reranker-0.6B is a `Qwen3ForCausalLM` (scores a query/document pair via the softmax-
normalized logit of a `yes` vs. `no` token after a chat-formatted judge prompt), a structurally
different serving shape than the classification-head cross-encoder (BGE-reranker-v2-m3) the
shared `rag-tei-reranker` TEI container already runs. Retrofitting TEI for it would mean a second
TEI container (new deployment artifact + port, reconfiguring shared infra other lanes depend on)
or fighting TEI's `/rerank` route for a scoring scheme it wasn't built to serve. At 0.6B params it
fits beside the resident TEI pair on the shared card with room to spare (~13.4GB free; this model
needs on the order of 1-2GB in bfloat16), so it runs **locally in-process via `transformers`**
(already installed in the `agent-rag-research` env) and never touches the `rag-tei-reranker`
container. The shared `rag-tei-embed`/`rag-tei-reranker` containers were never restarted or
reconfigured.

The swap itself uses no new mechanism: `app/exp_nb_rr_qwen_reranker.py` monkeypatches the
module-global `app.assembly.TeiReranker` name to `Qwen3Reranker` in-memory, immediately before
calling the unmodified `app.retrieval_eval.main()` — `app/assembly.py` and `app/retrieval_eval.py`
are never edited on disk. See that module's own docstring for the full mechanism.

## 1. BGE baseline reproduction (commit `f3b73a9`)

Reproduces the committed NB-D4 dual-fixture SAMPLE baseline to four decimals on every headline
number — the harness is trustworthy before any candidate number is trusted.

| metric | fixture | arm | pool depth | config | value |
|---|---|---|---|---|---|
| R@10 (answerable) | gt_wmr | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 68/70 = 0.9714 |
| R@10 (answerable) | waymo_gt_verified | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 65/68 = 0.9559 |
| MRR | gt_wmr | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.9393 |
| MRR | waymo_gt_verified | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.8335 |
| block-P@1 | gt_wmr | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 48/65 = 0.7385 |
| block-P@1 | waymo_gt_verified | BGE (baseline) | rerank_depth=32, k=10 | fused, waymo_av_safety | 22/60 = 0.3667 |

Source: `data/2026-08-28-nb-d4-dual-fixture-bge-baseline.json`. Exact match to
`data/2026-08-25-nb-d4-dual-fixture-SAMPLE.json` on every field above.

## 2. Candidate arm: Qwen3-Reranker-0.6B (commit `4eb9315`)

Identical harness, config, fixtures, `--collection waymo_av_safety` — only the reranker adapter
swapped.

| metric | fixture | arm | pool depth | config | value |
|---|---|---|---|---|---|
| R@10 (answerable) | gt_wmr | Qwen3-Reranker-0.6B | rerank_depth=32, k=10 | fused, waymo_av_safety | 66/70 = 0.9429 |
| R@10 (answerable) | waymo_gt_verified | Qwen3-Reranker-0.6B | rerank_depth=32, k=10 | fused, waymo_av_safety | 61/68 = 0.8971 |
| MRR | gt_wmr | Qwen3-Reranker-0.6B | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.5968 |
| MRR | waymo_gt_verified | Qwen3-Reranker-0.6B | rerank_depth=32, k=10 | fused, waymo_av_safety | 0.5429 |
| block-P@1 | gt_wmr | Qwen3-Reranker-0.6B | rerank_depth=32, k=10 | fused, waymo_av_safety | 2/65 = 0.0308 |
| block-P@1 | waymo_gt_verified | Qwen3-Reranker-0.6B | rerank_depth=32, k=10 | fused, waymo_av_safety | 2/60 = 0.0333 |

Source: `data/2026-08-28-nb-d4-dual-fixture-qwen3-0pt6b.json`.

### Before/after side by side

| fixture | R@10: BGE → Qwen | MRR: BGE → Qwen | block-P@1: BGE → Qwen |
|---|---|---|---|
| gt_wmr | 0.9714 → 0.9429 (−2.9 pts) | 0.9393 → 0.5968 (−34.2 pts) | **0.7385 → 0.0308 (−70.8 pts)** |
| waymo_gt_verified | 0.9559 → 0.8971 (−5.9 pts) | 0.8335 → 0.5429 (−29.1 pts) | **0.3667 → 0.0333 (−33.3 pts)** |

**Paper-level recall degrades modestly on both fixtures; block-level precision collapses on both.**
This is the "right document, wrong passage" signature at the aggregate level — but §4 below shows
the mechanism is more mixed than that phrase implies.

### Known-absent arms (reported separately — never blended)

| fixture | n | with a top result | top-score median | range |
|---|---|---|---|---|
| gt_wmr | 12 | 12 | 0.0100 | [0.0084, 0.0148] |
| waymo_gt_verified | 14 | 14 | 0.0097 | [0.0082, 0.0144] |

Unchanged in shape from the BGE arm's absent-item behavior (both rerankers see an empty gold set
and correctly return low top scores); absent-arm behavior is not part of this verdict.

## 3. Ceilings, printed next to the results (pre-committed, not from vibes)

| ceiling | ver84 (waymo_gt_verified) | gt_wmr |
|---|---|---|
| Perfect-ordering ceiling over top-10 | **0.7812** | **0.9394** |
| Depth bound @K=128, all-arm | **0.8750** | — |
| Depth bound @K=128, text-arm | **0.9333** | — |

BGE's block-P@1 (0.3667 ver84 / 0.7385 gt_wmr) sits well below both ceilings — known headroom
before this ticket started. Qwen's block-P@1 (0.0333 ver84 / 0.0308 gt_wmr) sits far below BGE,
not closer to either ceiling; the candidate does not close any of the headroom the ceilings
describe, on either fixture.

Reranking-load-bearing reference point: with reranking OFF, ver84 block-P@1 collapses to
**0.1667** [pre-committed]. Qwen's measured 0.0333 sits *below* the no-rerank floor — the
candidate's block-level ordering on ver84 is worse than doing no cross-encoder reranking at all
on this fixture. (No no-rerank arm was re-run this ticket; 0.1667 is quoted from the pre-committed
ceiling set, not re-measured here.)

## 4. Rank histograms and the F1 (rank-2 near-miss) target

Source: `data/2026-08-28-rank-histograms-and-f1.json`. `miss` = gold block not in the returned
top-10.

### gt_wmr (n=65 text-answerable, block-scored)

| rank | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | miss |
|---|---|---|---|---|---|---|---|---|---|---|
| BGE | 48 | 11 | 2 | — | — | — | 1 | — | — | 3 |
| Qwen | 2 | 6 | 9 | 5 | 3 | 1 | 2 | — | 2 | 35 |

### waymo_gt_verified (n=60 text-answerable, block-scored)

| rank | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | miss |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BGE | 22 | 11 | 7 | 2 | 1 | — | 3 | 3 | — | — | 11 |
| Qwen | 2 | 5 | 2 | 1 | 3 | 2 | 2 | 3 | 3 | 2 | 35 |

Qwen's distribution is not piled at the bottom (a sign-inversion signature) — it is genuinely
spread across ranks 1–10, with the largest single bucket being **miss** (35/65 gt_wmr, 35/60
ver84): more than half the time, the gold block is not merely reordered, it drops out of the
returned top-10 entirely.

### F1 target: BGE's own rank-2 near-misses (11 per fixture, this reproduction's own population)

The ticket's cited F1 counts (7/18 ver84, 8/12 gt_wmr) come from a **different** prior baseline
arm (`docs/eval-reports/2026-08-24-passage-precision-diagnosis.md`, ver84-dense-only/gt_wmr-fused,
denominators 64/66) — not directly comparable to this reproduction's fused/fused, 65/60
denominators. The operative F1 population reported here is this run's own: BGE's 11 rank-2 items
per fixture, which is the exact population a "better cross-encoder should convert."

- **gt_wmr: 0/11 converted to rank 1.** 5 stayed hits (ranks 2–9), 6 fell out of the top-10 entirely.
- **waymo_gt_verified: 1/11 converted to rank 1** (`Q-WAYB-004`). 3 stayed hits, 7 fell out of the top-10.

Full per-item detail (question_id, bge_rank, qwen_rank, converted flag) in
`data/2026-08-28-rank-histograms-and-f1.json`. **The candidate does not convert the F1 population
it was meant to target — it mostly makes those items worse, including outright misses on items
BGE had at rank 2.**

## 5. Diagnostic trail — three hypotheses tested and refined/falsified before trusting the numbers

Reproducing a known baseline first, then re-measuring per-item, is what caught every step below;
none of it was visible from the aggregate numbers alone.

**Hypothesis 1 — dtype (fp16 vs. bfloat16).** A synthetic 2-sentence pair ("Paris is the capital
of France" vs. "bananas are a fruit") collapsed to near-symmetric, wrong-direction yes/no logits
under `torch_dtype=float16`; Qwen3-Reranker-0.6B is calibrated in bfloat16 (`config.json`). Fixed
the adapter to load `dtype=torch.bfloat16`. **Ruled out as the explanation for the corpus-level
result**: a controlled A/B on the identical `--limit 5` subset moved block-P@1 by exactly 0/5 →
0/5 on both fixtures (MRR moved <0.002). bfloat16 was kept anyway — it is the model's documented
native precision and a real, reproducible trap on short/simple inputs — but it explains nothing
about this corpus's measured behavior. Regression-pinned in `app/test_exp_nb_rr_qwen_reranker.py`.

**Hypothesis 2 — wrong prompt template (raised by the orchestrator).** Hypothesis: the adapter
was feeding a bare `query [SEP] document` pair in the BGE convention rather than the model's
`<Instruct>/<Query>/<Document>` chat-template format, which would produce well-distributed but
meaningless scores. **Falsified by decoding the actual token sequence** the adapter's own
`_score_batch` sends to the model (not a description of the code — the literal
`tokenizer.decode()` output), which is byte-for-byte the model card's documented format:
```
<|im_start|>system
Judge whether the Document meets the requirements based on the Query and the Instruct provided...
<|im_start|>user
<Instruct>: Given a web search query, retrieve relevant passages that answer the query
<Query>: {question}
<Document>: {chunk text}<|im_end|>
<|im_start|>assistant
<think>

</think>
```
Also independently reconfirmed: `true_id`/`false_id` used by the adapter (9693/2152) match
`config.json`'s `true_token_id`/`false_token_id` exactly, and the manual last-hidden-state → LM-head
projection `_score_batch` uses (for memory reasons — see the module docstring's OOM note) is
numerically **identical** to the reference `model(**inputs).logits[:, -1, :]` computation on a
real left-padded batch, to 5 decimal places.

**Hypothesis 3 — reranker systematically prefers abstract/summary blocks over the specific body
passage (raised by the orchestrator, from two spot-checked items).** Quantified over every item
in the full run where Qwen's passage rank is worse than BGE's ("demotions" — 59/65 gt_wmr, 44/60
ver84 scored items). For each, classified the block Qwen actually promoted to its own rank 1:

| fixture | n demotions | promoted block same paper as gold | promoted block summary-ish (abstract/intro/conclusion, or index ≤ 2) | same paper AND summary-ish | promoted a **different paper** entirely |
|---|---|---|---|---|---|
| gt_wmr | 59 | 23/59 = 39.0% | 14/59 = 23.7% | 7/59 = 11.9% | 36/59 = 61.0% |
| waymo_gt_verified | 44 | 16/44 = 36.4% | 6/44 = 13.6% | 5/44 = 11.4% | 28/44 = 63.6% |

Source: `data/2026-08-28-demotion-analysis.json` (per-item detail included).
**Falsified as the dominant mechanism.** The two spot-checked items (§ below) were real examples
of the pattern, but they are not representative: a majority of demotions (61–64%) promote a chunk
from a **different paper** than gold, not a same-paper summary block. "Right document, wrong
passage" is not the right description of most of this collapse — it is closer to "wrong document
much of the time, and even when it's the right document, usually not the abstract." The two spot
checks that suggested the abstract-preference story remain in the record as concrete, real
examples (`Q-WMR-001`, `Q-WMR-003` — see prior commit `2e25b66`'s message and this report's git
history) — real but a minority pattern (~12%), not the explanation.

**Sanity check — is the adapter fundamentally separating relevant from irrelevant at all?**
Before trusting the full-run numbers as a model-quality finding rather than an adapter defect: for
two questions, scored the verbatim gold block against 3 blocks from other, topically distinct
papers, on the exact `Qwen3Reranker._compute_scores` code path (bfloat16). Source:
`data/2026-08-28-sanity-check.json`.

| trial | question | gold score | closest unrelated score | margin | gold ranked 1st? |
|---|---|---|---|---|---|
| 1 | Q-WMR-001 | 0.6367 | 0.5859 | 0.0508 | yes |
| 2 | Q-WMR-003 | 0.8672 | 0.7891 | 0.0781 | yes |

**2/2 pass** (gold ranks first both times) — the adapter is not broken; it correctly separates a
verbatim relevant passage from unrelated ones. But the margins (0.05, 0.08 on the model's own
[0,1] yes-probability scale) are narrow next to the wide margin on an easy, generic out-of-domain
pair tested in Hypothesis 1 (0.996 vs. 0.0000275, the same dtype and code path). **Conclusion: the
adapter has real signal, and much weaker resolving power on this specialized safety-research
corpus than the shipped BGE cross-encoder** — consistent with, not contradicted by, the aggregate
collapse in §2 and the histogram spread in §4.

## 6. Vendor claim vs. local measurement

**[V]** Qwen3-Reranker-0.6B ≥ +8.8 MTEB-R points over BGE-reranker-v2-m3 at equal parameter count
on an identical top-100 candidate pool from Qwen3-Embedding-0.6B (MTEB-R 65.80 vs. 57.03).
Source: `docs/research/2026-08-25-agentic-rag-sota.md` §3.2, citing arXiv:2506.05176 and
github.com/QwenLM/Qwen3-Embedding (Table 4). Vendor-published, no independent replication behind
that number.

**Locally measured** (this ticket, `waymo_av_safety` collection, fused hybrid retrieval,
rerank_depth=32): Qwen3-Reranker-0.6B block-P@1 is **24.0× worse on gt_wmr** (0.0308 vs. 0.7385)
and **11.0× worse on waymo_gt_verified** (0.0333 vs. 0.3667) than BGE-reranker-v2-m3 on this
corpus, and R@10/MRR are also lower on both fixtures.

A published pooled-benchmark gain not reproducing — and inverting sharply — on a specific
domain corpus's block-level retrieval task is itself the finding worth stating plainly: MTEB-R is
a general IR benchmark measuring whether *a* relevant passage is found; this ticket's block-P@1
measures whether the *specific, citation-grounded* passage is found, on a narrow-domain (AV
safety, ~120-paper) corpus neither benchmark's training/eval mix necessarily resembles. The vendor
number and the local number are not measuring the same thing closely enough to expect one to
predict the other, and this ticket is the evidence for that gap on this corpus.

## 7. Related finding from another lane (noted, not re-verified here)

The W-A4 ground-truth authoring lane independently found (today, same repo) that **12/12** cited
passages sat 1–5 blocks downstream of their chunk's anchor block — anchor blocks trend toward
headings and opening text, while the substantive sentence lives further in. That is a different
mechanism (chunk/anchor boundary placement, not reranker scoring) but the same shape of problem:
summary-ish/opening text sits where the specific evidence is not. Worth one line connecting the
two findings for whoever works this area next; it does not change this ticket's verdict, which
rests on the reranker-arm measurement in §2–§5, not on the demotion mechanism.

## 8. Verdict: REJECT (both fixtures, not averaged)

**Reject Qwen3-Reranker-0.6B for the shipped reranker seat, on this corpus, in this harness.**

- gt_wmr: block-P@1 0.7385 → 0.0308 (−70.8 pts), R@10 0.9714 → 0.9429 (−2.9 pts), MRR 0.9393 →
  0.5968 (−34.2 pts). F1 rank-2 population: 0/11 converted, 6/11 became outright misses.
- waymo_gt_verified: block-P@1 0.3667 → 0.0333 (−33.3 pts, and *below* the no-rerank floor of
  0.1667), R@10 0.9559 → 0.8971 (−5.9 pts), MRR 0.8335 → 0.5429 (−29.1 pts). F1 rank-2 population:
  1/11 converted, 7/11 became outright misses.

The candidate loses on **both** fixtures, on every headline metric, by a wide and consistent
margin — this is not a case of winning on one fixture and losing on the other, so there is no
per-fixture split to report separately beyond what's already itemized above. The adapter is
verified functioning (§5's decode + sanity check), so this is a genuine candidate-model finding on
this corpus, not a measurement artifact.

**Not done in this ticket, left for an operator to pick up if this direction is revisited**:
Qwen3-Reranker-4B/8B (larger, likely stronger resolving power, but no longer "fits trivially
beside everything" on the shared card — a real GPU-budget tradeoff to work out first); a custom
task instruction tuned for this corpus's block-level, citation-grounded retrieval task rather than
the model's generic default instruction (worth trying before writing off the whole Qwen3-Reranker
family, but out of scope for a measure-before-adopt ticket — instruction tuning is itself a design
decision, not a straight A/B); PyLate/GTE-ModernColBERT, the fallback candidate named alongside
Qwen3-Reranker-0.6B in the same research doc.

## File map (every number above traces here)

- `data/2026-08-28-nb-d4-dual-fixture-bge-baseline.json` / `.md` / `bge-baseline/{gt_wmr,waymo_gt_verified}.json` — commit `f3b73a9`
- `data/2026-08-28-nb-d4-dual-fixture-qwen3-0pt6b.json` / `.md` / `qwen3-0pt6b/{gt_wmr,waymo_gt_verified}.json` — commit `4eb9315`
- `data/2026-08-28-rank-histograms-and-f1.json` — §4
- `data/2026-08-28-demotion-analysis.json` — §5 Hypothesis 3
- `data/2026-08-28-sanity-check.json` — §5 sanity check
- `app/exp_nb_rr_qwen_reranker.py`, `app/test_exp_nb_rr_qwen_reranker.py` — harness + dtype regression pin
