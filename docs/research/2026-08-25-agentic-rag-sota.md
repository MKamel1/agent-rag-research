# NB-R1 — agentic RAG state of the art (2025–2026), mapped to this system

Web-research ticket (NB programme). Written 2026-08-25 on branch `NB-R1-agentic-sota`.
**Status: COMPLETE.** Commit 1 was the stub; this commit carries §2–§6. No pipeline code is touched
by this ticket.

## 0. Scope, method, and citation policy

- Deliverable: one cited report. Every non-obvious claim carries a URL (arXiv abs pages preferred).
- Each technique card flags whether its headline gains were measured on **passage/block-level metrics**
  (nDCG@k, recall@k, precision@k over passages — OUR target regime) or **answer-level QA metrics**
  (EM/F1 over generated answers — a different instrument; gains there do not automatically transfer,
  see §4).
- Claims whose sources were paywalled/unfetchable are marked per-claim rather than guessed.
- "State of the art" (published measured results) is distinguished from "state of the practice"
  (widely used, thin or vendor-published evaluation) throughout §2–§3.
- Two evidence tags used in addition to the P/A metric tags: **[V]** vendor/self-reported evaluation,
  **[I]** independent or adversarial re-evaluation. Where neither applies (claim rests on the
  original paper's abstract alone), no tag is given.

## 0a. Method note: what happened to the three research clusters, and what that cost this report

The ticket plan called for three librarian web-research sub-sessions (agentic families /
retrieval-quality levers / metric-divergence evidence). Those sub-runs did not survive: their session
stores contain only the dispatch prompts — no tool calls, no findings. What *was* recoverable from the
parent session's store: ten primary-source captures (arXiv abstract pages + Anthropic's contextual-
retrieval post) made before the session ended. This report is built from those ten captures plus
targeted follow-up searches run during this writing pass.

Consequences, stated plainly rather than papered over:

- **Covered with pinned numbers:** Self-RAG, CRAG (+Self-CRAG), Adaptive-RAG, IRCoT, Self-Ask, FLARE,
  Search-R1, HyDE (+ two negative reassessments), GraphRAG/LightRAG (+ three critiques), ColBERTv2,
  AnswerAI-ColBERT-small-v1, Jina-ColBERT-v2, GTE-ModernColBERT/PyLate/token-pooling, Qwen3-Reranker
  family, Anthropic contextual retrieval (+ one independent confirmation), late chunking, RAPTOR,
  metric-divergence literature (UDCG, facet-tracing, attribution-transfer audit, lost-in-the-middle
  reproduction), agentic-evaluation surveys.
- **Named but NOT pinned this cycle — treated here as unverified leads, not findings:** DRAGIN and
  SEAKR router internals/numbers; RankZephyr/RankLLaMA measured deltas; ZeroSearch, R1-Searcher,
  ReSearch, WebThinker exact results; LoTTE per-split scores; sliding-window listwise latency
  profiles; MemGPT/Letta/Mem0/Zep/A-MEM (no passage-retrieval-bearing result sought and none found);
  mxbai-rerank variants; Vespa late-interaction serving costs.
- Where a number below has no URL-declared source behind it beyond an abstract, the card says so.

## 1. System profile and the measured failure buckets recommendations must map onto

Local-only stack: Ollama-served Qwen generation models (qwen3-14b-16k; Qwen3 27B-class GGUF on disk),
TEI-hosted Qwen3-Embedding-4B + BGE reranker, Qdrant hybrid (dense + sparse IDF), SQLite source of
truth, ONE 24GB GPU shared by all services, MCP tool surface, zero paid APIs. Corpus: PDFs parsed to
page/bbox-anchored blocks, grouped into multi-block chunks anchored at each group's first block.

Measured failure buckets (all numbers cite the local eval reports; nothing here is new measurement):

| # | bucket | evidence | source |
|---|---|---|---|
| F1 | Near-misses at ranks 2–10 (right paper, wrong block, gold in top-10): concentrated at rank 2 | 7/18 ver84 + 8/12 GT-WMR near-miss populations sit at rank 2 | PREC-1 §1 |
| F2 | Gold block absent from top-10 though rank-1 paper correct (C2): recoverable by pool depth | 23/23 non-vision C2 items exposed at K=64; bottomless-pool ceiling 0.8750 all-arm / 0.9333 text-arm @K=128 | NB-D1 via NB-R0 |
| F3 | Chunk-boundary misses (`same_chunk`+`adjacent_chunk`) | 33% of ver84 near-misses, 25% of GT-WMR; plus ~1–2/fixture anchor-exactness artifacts (gold served, cited elsewhere) | NB-D2 |
| F4 | Hard-difficulty collapse + negation/scope strata | block-P@1 0.167 hard vs 0.519 medium (ver84); negation 1/7 | PREC-1 §4 |
| F5 | Multi-paper synthesis items | 5 exposed items ver84, 1/5 — tiny denominator, real class | PREC-1 §4 |
| F6 | Abstention: no retrieval-score feature separates known-absent from answerable | 17 features × 2 fixtures, null | NB-D3 via NB-R0 |
| F7 | Vision-derived items unreachable by any text-side fix | 4+1 items absent from every pool size | NB-D1 |

Proven ceilings any recommendation must respect (NB-R0): perfect re-ordering of today's top-10 caps
at 0.7812 (ver84) / 0.9394 (GT-WMR); depth+ordering together bounded by 0.8750/0.9333 (K=128 bound).
The residual lives upstream (chunking long tail: `same_doc_elsewhere` = 63–75% of near-misses) and in
the vision slice. X-O verdict: no cheap ordering lever cleared the bar with the shipped reranker;
reranking itself is load-bearing.

## 2. Agentic / iterative RAG families

Format per card: mechanism → measured gains (metric-tagged) → infra cost on our stack → failure
modes. Families with no adoptable finding say so explicitly.

### 2.1 Self-RAG — self-reflection tokens [A]

Trains a single LM (7B/13B) to emit special *reflection tokens* deciding on-demand retrieval and
critiquing retrieved passages and its own generations; controllable at inference. Original claims:
outperforms ChatGPT and retrieval-augmented Llama2-chat on open-domain QA, reasoning, fact
verification; gains in factuality/citation accuracy for long-form generation — all answer-level
(https://arxiv.org/abs/2310.11511).

- **No passage/block-level measurement exists** for Self-RAG's headline claims — its retrieval
  component is never scored against gold passages as such. That absence is itself the finding for a
  precision-targeted system.
- Replication/critique status: no study showing Self-RAG-style reflection failing to transfer to
  retrieval metrics surfaced this cycle (the planned librarian sweep for exactly this did not run).
  The closest independent evidence is indirect: the EMNLP-2024 best-practices sweep found
  query-dependent retrieval machinery generally buys answer quality only at heavy latency cost
  (https://arxiv.org/abs/2407.01219), and CRAG's own paper shows large headroom left on top of it:
  coupling CRAG into Self-RAG ("Self-CRAG") added +6.9% PopQA accuracy / +5.0% Biography FactScore
  over Self-RAG when built on SelfRAG-LLaMA2-7b (and +20%/+36.9% respectively on the LLaMA2-hf-7b
  base) [A][I within-paper] (https://arxiv.org/abs/2401.15884v2). Adopting
  Self-RAG would also mean training/fine-tuning a generator — off-limits cost class here.
- Verdict: not adoptable; monitor for replication studies.

### 2.2 CRAG — corrective RAG and its retrieval evaluator [A] (evaluator itself: reusable signal)

Lightweight retrieval evaluator scores overall retrieved-document quality per query and triggers
actions {Correct, Incorrect, Ambiguous}, with decompose-then-recompose filtering; web-search fallback
for the low-confidence arms. Plug-and-play on top of RAG/Self-RAG; four short/long-form datasets,
answer-level gains (https://arxiv.org/abs/2401.15884). Robustness curve: as deliberate retrieval
quality degrades, Self-CRAG degrades more slowly than Self-RAG [A] (same v2 link).

- **Why we care despite answer-level evals:** the evaluator is exactly the *independent correctness/
  confidence signal* our abstention problem (F6) lacks — our NB-C2 probe showed sparse-anchor score
  features carry no signal (AUROC 0.4824/0.3563), i.e. we need a different signal class, and a trained
  relevance evaluator is one. Note honestly: whether CRAG's evaluator separates known-absent queries
  was never published even by them; it is a hypothesis to test locally, not a result to import.
- The web-search fallback arm violates our zero-paid-API constraint and does not apply to a closed
  corpus; only the evaluator + decompose-recompose halves are relevant.
- Verdict: adopt the *pattern* (trained evaluator over retrieved context), not the system. See §5 #4.

### 2.3 Adaptive-retrieval routers (Adaptive-RAG class) [A]

Adaptive-RAG trains a small classifier to route each query to {no retrieval, single-step, iterative}
based on predicted complexity; improves efficiency and accuracy vs always-iterate and never-route
baselines on open-domain QA (https://arxiv.org/abs/2403.14403). Independent corroboration from the
best-practices sweep: a query-classification gate improved average RAG score 0.428→0.443 while
cutting latency 16.41→11.58 s/query, and they recommend selective retrieval as default practice [A]
(https://arxiv.org/abs/2407.01219; https://aclanthology.org/2024.emnlp-main.981.pdf).

- For us the value is inverted relative to the papers: our corpus is closed and every query is
  knowledge-seeking, so "skip retrieval" is rarely right; the interesting routing axis is *how much*
  retrieval (pool depth K, rerank depth, expansion on/off) conditioned on query stratum — directly
  aimed at F4 (hard/negation collapse) without taxing easy queries.
- DRAGIN/SEAKR specifics unpinned this cycle (see §0a) — no numbers claimed here.
- Verdict: adoptable as a light app-layer router; evidence base is answer-level, so treat yield on F4
  as unproven until our fixture A/B runs.

### 2.4 Query decomposition & planning: IRCoT, Self-Ask, FLARE [mixed P/A]

- **IRCoT** interleaves CoT sentence generation with retrieval so each hop conditions the next;
  "up to 21 points" retrieval gain and up to 15 points QA gain on HotpotQA/2WikiMultihopQA/MuSiQue/IIRC
  — the retrieval gains ARE passage-level-flavored (retrieval recall/precision on multi-hop corpora),
  the QA gains answer-level; works training-free with Flan-T5-large (https://arxiv.org/abs/2212.10509).
  Caveat: all four benchmarks are multi-hop Wikipedia QA — nothing pins transfer to single-passage
  scientific lookup.
- **Self-Ask**: model emits follow-up sub-questions then composes; motivation is the compositionality
  gap (models answer sub-facts but fail to compose); search-engine plug-in variant improves accuracy —
  answer-level throughout (https://arxiv.org/abs/2210.03350).
- **FLARE**: active retrieval during long-form generation — when the next-sentence preview contains
  low-confidence tokens, use it as a query and regenerate; superior/competitive on 4 long-form
  knowledge-intensive tasks (https://arxiv.org/abs/2305.06983). Metric regime: task-quality on
  long-form generation; not passage-ranking.
- **Negative evidence, same family:** the best-practices sweep found plain query rewriting and query
  decomposition "did not enhance retrieval performance as effectively" on TREC DL19/20 passage
  ranking [P] (https://arxiv.org/abs/2407.01219), and T2-RAGBench found multi-query expansion gave
  limited benefit for precise numerical queries while adding latency [P]
  (https://arxiv.org/html/2604.01733v1).
- Synthesis: decomposition helps when the query genuinely requires multi-hop composition (our F5
  multi-paper stratum) and can hurt otherwise (our negation/hard strata risk scope drift). Any local
  adoption should be routed (§2.3), not global.

### 2.5 Iterative RL-trained search agents (Search-R1 class) [A]

Search-R1 RL-trains an LLM (PPO/GRPO, outcome reward = EM) to interleave multi-turn search calls with
reasoning; +26%/+21%/+10% average relative EM improvement over SOTA baselines with Qwen2.5-7B/3B and
LLaMA3.2-3B respectively across seven QA datasets (v1 abs numbers; later revision reports 24%/20%
with PPO defaults); E5 retriever, 2018 Wikipedia dump, top-3 passages; PPO > GRPO; 7B learns search
much better than 3B (https://arxiv.org/abs/2503.09516, https://arxiv.org/pdf/2503.09516v1).
Representative table row (Qwen2.5-7B-base, PPO): avg EM 0.431 vs RAG 0.304 vs IRCoT 0.239 [A].

- All gains are answer-EM on Wikipedia QA; the retrieval corpus and metric are both foreign to us.
  Infra cost: RL training loops (rollouts × retrieval × reward) on the order of GPU-days — not
  compatible with ONE shared 24GB GPU that also serves the live system. ZeroSearch/R1-Searcher/
  ReSearch/WebThinker: named, numbers unpinned (§0a).
- Verdict: not adoptable now. The durable idea worth stealing cheaply: *retrieval decisions belong in
  the reasoning loop*, which our MCP agent surface already permits without any training.

### 2.6 HyDE — hypothetical document embeddings [P original; P negative replications]

Zero-shot pivot: instruct an LLM to write a hypothetical answer document, embed *that*, retrieve by
doc-doc similarity; beats unsupervised Contriever across DL19/20 and six BEIR subsets (DL19 nDCG@10
44.5→61.3; SciFact 64.9→69.1) (https://arxiv.org/abs/2212.10496;
https://aclanthology.org/2023.acl-long.99.pdf).

Two independent negatives since:

1. **Knowledge-leakage audit** (fact-verification testbed, 7 LLMs): >40% of claims show leakage
   (generated documents entail gold evidence) for most LLM×dataset combos; performance gains
   concentrate almost entirely on leaked claims, and on non-leaked ("unmatched") claims expansion
   methods often perform *worse* than baseline retrievers
   (https://www.alphaxiv.org/abs/2504.14175). Our corpus (specialist causal-methods PDFs) is close to
   the worst case: little pretraining overlap, high leakage risk of *plausible-but-wrong* content.
2. **T2-RAGBench** (23,088 financial queries, mixed text/table): HyDE underperforms vanilla dense on
   every metric (nDCG@10 0.433 vs 0.466; Recall@5 0.544 vs 0.587); hallucinated plausible-but-wrong
   figures pull embeddings away from true context; authors' explicit recommendation: avoid HyDE where
   factual precision dominates [P] (https://arxiv.org/html/2604.01733v1).

Verdict: do not adopt. Our F4 negation/hard strata are precisely where fabricated pseudo-documents
would be most confidently wrong.

### 2.7 GraphRAG-class (Microsoft GraphRAG, LightRAG) [A, with adverse independent re-evaluations]

Mechanism: LLM-extracted entity/relation graph + community summaries retrieved alongside or instead
of chunks. Original evaluations are answer-level LLM-as-judge win rates on narrative/textbook corpora
(UltraDomain etc.) — confirmed, as suspected in the brief (https://arxiv.org/abs/2404.16130;
LightRAG: https://aclanthology.org/2025.findings-emnlp.568.pdf). LightRAG's own cost analysis:
GraphRAG community traversal ≈ 610 community reports × ~1,000 tokens + hundreds of API calls per
query vs LightRAG <100 tokens/single call; incremental updates force GraphRAG to rebuild community
reports (~1,399 communities × 2 × 5,000 tokens) while LightRAG grafts onto the existing graph.

Three independent critiques pin the reality:

1. **KG incompleteness**: only ~65.8%/65.5% of answer entities exist in the constructed KGs
   (HotpotQA/NQ); Community-GraphRAG global search underperforms plain RAG on detail-oriented QA and
   hallucinates on null queries (https://arxiv.org/html/2502.11371v2).
2. **Evaluation-bias reversal**: under an unbiased protocol (position/length/trial controls),
   LightRAG's reported 72% vs 28% win rate over NaiveRAG flips — NaiveRAG slightly outperforms
   LightRAG; comparing LightRAG to itself still yields 90/10 win rates under the biased protocol
   (https://arxiv.org/pdf/2506.06331).
3. **Honest exchange rate on SEC filings** (40-question GT benchmark): graph mode raised strict
   document recall 82.5%→97.5% but fully-correct answers only 42.5%→45.0%; answer-or-refuse decisions
   got *worse* (85.0%→77.5%); indexing cost 10.97 h GPU; 53% of retrieved entity descriptions fused
   multiple fiscal years undated (https://bestin-it.com/lightrag-benchmark-sec-filings/) [I].

Verdict: not adoptable for a passage-precision goal on a single-GPU personal corpus. The one durable
signal: graph structure paid off specifically on *cross-document event-consequence and restatement
patterns* (2 of 8 dispersion patterns) — the shape of our F5 multi-paper stratum, if F5 ever justifies
authoring dedicated items (NB-B0 §3 sizing).

### 2.8 Agentic memory (MemGPT/Letta, Mem0, Zep/Graphiti, A-MEM)

No published result found bearing on document/passage retrieval quality; these systems target
conversational-memory management. **Does not apply to this problem.** Stated per brief rather than
left implicit.

## 3. Retrieval-quality adjacent levers

This section is the load-bearing one: everything here is measured on passage/block-level metrics —
our regime — except where flagged.

### 3.1 Late interaction (ColBERT lineage) on a 24GB budget [P]

ColBERTv2 established token-level MaxSim late interaction with residual compression, cutting late-
interaction space 6–10× at SOTA quality (https://arxiv.org/abs/2112.01488). The modern open-weight
generation, all runnable CPU/GPU-cheap:

| model | BEIR nDCG@10 avg | params | notes |
|---|---|---|---|
| BM25 | 44.0 | – | reference floor |
| ColBERTv2 | 49.6–50.02 | 110M | English-only, 2019-era backbone |
| Jina-ColBERT-v2 | 53.1 | ~161M | multilingual, 8192 ctx, Matryoshka 128→64 dims ≈ −50% storage, negligible loss (0.599→0.589 on their 14-set avg) |
| AnswerAI-ColBERT-small-v1 | 53.79 | **33M** | beats ColBERTv2 across the board; ms-latency, CPU-capable |
| GTE-ModernColBERT | **54.67** | ~150M | current open late-interaction SOTA; distilled from bge-reranker-v2-gemma scores; trained <2 h on 8×H100 |

Sources: https://huggingface.co/jinaai/jina-colbert-v2 (BEIR table incl. SciFact 67.8 / NFCorpus
34.6 / SCIDOCS 18.6); https://aclanthology.org/2024.mrl-1.11/;
https://www.answer.ai/posts/2024-08-13-small-but-mighty-colbert.html (SciFact 74.77 / NFCorpus 37.30 /
SCIDOCS 18.42 — note subset differences between tables; both [V]);
https://huggingface.co/lightonai/GTE-ModernColBERT-v1 (SciFact 76.34 / NFCorpus 37.93 / SCIDOCS
19.06); PyLate library: https://arxiv.org/html/2508.03555 (PLAID indexing, rerankers-library
integration, loads ColBERTv2/AnswerAI/Jina weights directly). Token pooling cuts any multi-vector
index footprint ~in half without performance degradation (https://arxiv.org/abs/2409.14683, via
PyLate paper description).

Fit notes, honestly drawn: all numbers above are first-stage full-corpus BEIR retrieval, not
second-stage reranking over 32–128 candidates — the deployment mode relevant to us. As a reranker,
MaxSim over ≤128 candidates is computationally trivial for these parameter counts; what is *not*
published anywhere I could pin this cycle is a head-to-head of strong-open-cross-encoder vs modern
late-interaction as second stage at equal compute (the librarian sweep would have hunted this; §0a).
The honest position: late interaction is the strongest *measured* passage-level family in the
literature, it plausibly slots into our reranker seat, and the only proof that matters is our own
fixtures.

Known weak spots (same sources): ArguAna-class long-query tasks and duplicate-detection tasks hurt;
SCIDOCS near-floor for every model (~18–19) — citation-graph adjacency is simply hard for lexical/
dense alike.

### 3.2 LLM-as-reranker / listwise, open-weight [P, mostly V]

RankGPT established listwise LLM permutation ranking: GPT-4 beats supervised SOTA on TREC-DL/BEIR;
permutation-distilled 440M model outperforms a 3B supervised model on BEIR
(https://arxiv.org/abs/2304.09542). RankZephyr/RankLLaMA successors exist; **their specific deltas
are unpinned this cycle** (§0a) — no numbers claimed.

The practically important open-weight data point is the Qwen3 reranker family (0.6B/4B/8B,
instruction-aware, 32k ctx), evaluated identically over the same top-100 candidates from
Qwen3-Embedding-0.6B [V]:

| reranker | MTEB-R (eng) | MMTEB-R (multi) | MLDR (long-doc) |
|---|---|---|---|
| (no rerank: Qwen3-Embedding-0.6B) | 61.82 | 64.64 | 50.26 |
| BGE-reranker-v2-m3 (0.6B) | 57.03 | 58.36 | 59.51 |
| Qwen3-Reranker-0.6B | 65.80 | 66.36 | 67.28 |
| Qwen3-Reranker-4B | **69.76** | 72.74 | 69.97 |
| Qwen3-Reranker-8B | 69.02 | **72.94** | **70.19** |

Source: https://arxiv.org/abs/2506.05176 and https://github.com/QwenLM/Qwen3-Embedding (Table 4).
Reading with care: BGE-v2-m3 scoring below the no-rerank baseline on MTEB-R/MMTEB-R is a property of
that pooled evaluation (its strength was long-doc MLDR), not proof reranking hurts; the actionable
delta is Qwen3-Reranker-0.6B ≥ +8.8 MTEB-R over BGE-v2-m3 at equal parameter count on the identical
candidate pool. These are vendor numbers ([V]) — no independent replication surfaced this cycle.
Sliding-window listwise pitfalls documented in the RankGPT lineage (window boundary effects) were not
re-quantified here; Qwen3 rerankers run pointwise relevance (yes/no logit), sidestepping windowing
entirely.

Serving note (to verify at implementation time, not asserted): TEI added support for Qwen-class
scoring models after mid-2025; if TEI hosting proves awkward, a 0.6B scorer fits beside everything
else on the shared GPU.

### 3.3 Contextual retrieval (post-Anthropic-2024) [P — chunk-level, our regime]

Original announcement, exact figures: prepending LLM-generated chunk-situating context (50–100
tokens) before embedding + BM25 indexing cut top-20-chunk retrieval failure (metric: 1−recall@20)
35% with contextual embeddings alone (5.7%→3.7%), 49% combined with contextual BM25 (→2.9%), and 67%
adding a reranker (→1.9%); $1.02 per million document tokens one-time ingest cost with prompt caching
(800-token chunks, 8k-token docs); generic whole-document-summary injection explicitly tried and
rejected ("very limited gains"), summary-based indexing "low performance"; domains included ArXiv
papers and science papers; top-150 → Cohere rerank → top-20 (https://www.anthropic.com/news/contextual-retrieval)[V].

Independent confirmation exists now: T2-RAGBench (23k queries, financial) shows Contextual Hybrid >
Hybrid RRF (Recall@5 0.717 vs 0.695; nDCG@10 0.571 vs 0.551) with contextual retrieval "yielding
consistent gains" while HyDE/multi-query did not [P][I] (https://arxiv.org/html/2604.01733v1).

Cheaper cousins: **late chunking** embeds the whole long document and applies chunk pooling *after*
the transformer, giving contextualized chunk embeddings with zero extra LLM calls, no training,
generic to long-context embedders (https://arxiv.org/abs/2409.04701 — abstract-level claim; per-task
tables not pinned this cycle, §0a). Our stack is unusually well-suited: Qwen3-Embedding-4B is
32k-context, and our parser already produces section-structured blocks, so a section-scoped variant
(embed per-section token span, pool at block-group boundaries) approximates the mechanism without
any generative call. Full Anthropic-style per-chunk contextualization is also feasible offline via
Ollama qwen3-14b at our corpus scale (≈10⁵ blocks ⇒ order 10⁷–10⁸ doc-tokens ⇒ tens of dollars-
equivalent GPU-hours, one-time).

Direct mapping: F3 boundary misses (33%/25%) are exactly the "chunk lacks situating context" disease
this treats; the same_doc_elsewhere tail (63–75% of near-misses) is partially addressable because
contextualization makes sibling-section chunks lexically findable. It cannot touch F7 vision items.

### 3.4 Section/neighborhood-aware scoring & structure exploitation [mostly A; gap flagged]

- **RAPTOR**: recursive cluster-summarize tree over chunks; +20% absolute accuracy on QuALITY (long-
  fiction QA) coupled with GPT-4 — answer-level on narrative corpora; QASPER is its scientific set
  (numbers not pinned this cycle, §0a) (https://arxiv.org/abs/2401.18059).
- Sentence-window / small-to-big / parent-document patterns: widely practiced (LlamaIndex et al.);
  **no measured primary evidence pinned this cycle** — flagged as state-of-practice, not SOTA.
- Neighbor-chunk score smoothing across adjacent blocks: attractive for our F3 bucket, and **we found
  no published measurement of it** — this absence should push the experiment local (NB-D2 strata give
  the instrument) rather than let the idea ride on vibes.
- Cautionary datapoint against summary-based neighborhood hacks: Anthropic tried generic-summary
  injection and rejected it for near-zero gains (link above); LightRAG's SEC benchmark shows merged
  undated entity summaries actively corrupting temporal grounding (§2.7 critique 3).
- Late-chunking (§3.3) doubles as the principled version of "neighborhood-aware embeddings."

## 4. Evidence-quality audit: passage-level vs answer-level claims

Where the literature measures answers, not passages: essentially the entire agentic-RAG headline
corpus — Self-RAG (accuracy/FactScore), Adaptive-RAG (QA accuracy), Search-R1 (EM), GraphRAG/LightRAG
(LLM-judge win rates), RAPTOR (QuALITY accuracy), FLARE/Self-Ask (task accuracy/EM). Passage-level
evidence lives almost entirely in the IR-lever literature (BEIR/MTEB reranking tables, ColBERT line,
Anthropic's failure-rate metric, T2-RAGBench, IRCoT's retrieval half).

Divergence evidence, both directions — the honest picture is that the two instruments measure
different things, and neither upper-bounds the other:

1. **Passage metrics don't guarantee answers.** UDCG (EACL 2026): traditional IR metrics mispredict
   end-to-end RAG accuracy because (i) LLMs read holistically, not rank-by-rank, and (ii) irrelevant
   passages actively distract rather than merely dilute; utility-aware annotation improves correlation
   with answer accuracy up to 36%, and "achieving perfect traditional IR metrics is insufficient for
   optimal RAG performance" (https://aclanthology.org/2026.eacl-long.391.pdf).
2. **Better retrieval can worsen answer-side behavior.** Facet-level tracing across GPT/Gemini/LLaMA
   on medical QA + HotpotQA: evidence *override* (retrieved but contradicted/ignored) dominates
   evidence *failure* 28.4% vs 7.0% (medical) and 42.3% vs 5.8% (HotpotQA); strict grounding
   underperforms no-retrieval in 30% of cases
   (https://arxiv.org/html/2604.09174v2). A Springer ML faithfulness benchmark finds hybrid-retrieval
   accuracy gains frequently accompanied by *increased hallucination and reduced abstention* in
   reasoning-intensive domains (https://link.springer.com/article/10.1007/s10994-026-07121-y). The
   independent LightRAG SEC benchmark reproduces the abstention side: more evidence in context made
   the system bolder and wronger about refusing (§2.7).
3. **Even within "attribution," metrics don't transfer.** Auditing eight attribution scorers across
   datasets: best-metric rank ordering discordant (Kendall's W = 0.07); an NLI scorer best-in-class
   on one dataset falls to chance (AUROC 0.53) on another (https://arxiv.org/html/2606.23915). This
   is methodological support for our house rule (PREC-1 §5): never average across fixtures, validate
   instruments per fixture.
4. **Position effects contaminate interpretation, and don't replicate cleanly.** Lost-in-the-middle
   (https://arxiv.org/abs/2307.03172) effects interact strongly with retrieval quality and topic
   sampling; idealised-setup conclusions "do not always transfer to real-world RAG pipelines";
   better top-k evidence reduces order sensitivity (https://arxiv.org/html/2605.27105v2). Practical
   echo: reverse repacking (gold nearest the query) won in the best-practices sweep
   (https://arxiv.org/abs/2407.01219).

What transfers to US: our product *is* the grounded passage — the citation anchor is the deliverable,
so answer-level divergence (1)–(2) threatens our summarizer/generation layer, not our block-P@1
target. But two cautions bind anyway: (a) any future answer layer inherits the override/abstention
findings above; (b) UDCG's distraction result warns that raising pool depth K (our F2 fix) imports
more distractors — depth must land *behind* a reranker, not in front of the context window.

Agentic-evaluation gaps (survey-level): the SoK of agentic RAG formalizes the loop as a POMDP and
documents that evaluation remains inherited from static single-pass tasks — final-answer focused,
blind to trajectories, credit assignment, and compounding-error modes
(https://arxiv.org/html/2603.07379v1). A 33-failure-mode taxonomy grades ALL eight agentic failure
modes as lacking dedicated peer-reviewed empirical evidence — an "agentic evidence desert"
(https://aclanthology.org/2026.trustnlp-main.27.pdf). This converges with our own NB-B0 audit: our
fixtures are single-pass/end-state instruments, multi-paper exposure is largely unscored, and no
trajectory layer exists. The outside literature and our inside audit agree: nobody currently measures
what agentic RAG claims to improve.

## 5. Ranked top-5 adoptable techniques for THIS system

Ranked by expected yield against F1–F7 ÷ implementation cost, respecting NB-R0 ceilings. Cost classes:
scripts (offline/experimental), app-level (module code + config, no frozen-shape changes),
contracts-gated (touches `contracts/`, Config, schema — needs foundation sign-off).

### #1 — Reranker-seat upgrade: Qwen3-Reranker-0.6B (fallback candidate: late-interaction second stage via PyLate)

- **Yield**: F1 (rank-2 concentration) primarily; F2 partially via correct down-ranking of pool
  noise. X-O already proved reranking is load-bearing and the shipped BGE reranker exhausted its
  headroom; the same-pool vendor delta is +8.8 nDCG-scale points over BGE-v2-m3 (§3.2) [V].
- **Cost**: app-level. Adapter swap in `rag/reranker.py` + config; 0.6B fits trivially on the shared
  GPU; TEI compatibility to verify first.
- **Proves itself**: block-P@1 + full rank-histogram on ver84/gt_wmr text-arm; must clear the
  pre-committed bar NB-R0 set (perfect-ordering ceiling 0.7812/0.9394 tells us the max any reranker
  can deliver — report against it, not against vibes). Run PyLate/GTE-ModernColBERT as the competing
  candidate in the same harness; keep whichever wins per-fixture.

### #2 — Depth-first reranking: retrieve K=64–128, rerank down to 10

- **Yield**: F2 directly — 23/23 C2 items exposed at K=64; depth+ordering joint bound 0.8750/0.9333
  @K=128 vs today's 0.78-ish effective. Without depth, #1's ceiling is capped by gold-absent-from-top-10.
- **Cost**: scripts → app-level config (pool depth is already a knob; the work is making deep pools +
  reranker throughput fit latency budget on the shared GPU).
- **Proves itself**: NB-D1 protocol re-run at K∈{32,64,128} with the #1 reranker; watch the UDCG
  caution (§4) — depth lands behind the reranker only. Also re-score F6 features post-change (deeper
  pools change score distributions; NB-D3's null may need re-testing, not assuming).

### #3 — Contextual chunk enrichment at ingest (section/document-scoped; late-chunking first, Ollama-contextualization second)

- **Yield**: F3 (boundary misses 33%/25%) plus part of the same_doc_elsewhere tail feeding F1/F2.
  Evidence: −49%/−67% top-20 failure-rate reductions [P, V], independently confirmed direction
  (Contextual Hybrid > Hybrid, 23k-query benchmark [P, I]).
- **Cost**: ingest-time scripts + full re-embed/reindex (app-level; touches embedder inputs and the
  rebuildable Qdrant projection, not SQLite truth or contracts). Late-chunking variant needs zero
  generative calls (32k-ctx embedder already hosted); Anthropic-style per-chunk captions via
  qwen3-14b are the heavier fallback if pooling-based context underdelivers.
- **Proves itself**: NB-D2 boundary-stratum re-run + block-P@1 both fixtures; anchor-exactness
  artifacts (~1–2/fixture) tracked separately since enrichment may shift which block is "gold-adjacent."

### #4 — CRAG-pattern retrieval evaluator as the abstention signal

- **Yield**: F6 — currently zero separating signal (17 features null; NB-C2 AUROC ≈ chance). A small
  trained evaluator scoring retrieved-context sufficiency is a genuinely different feature class
  from anything probed. Honest caveat repeated: CRAG never published absent-query behavior; this is a
  hypothesis with good priors, not an imported result.
- **Cost**: app-level-plus — needs labeled (query, retrieved-set) pairs; our fixtures + GT discipline
  provide seeds; if the evaluator's score becomes an MCP-visible field or enters Config, that edge is
  contracts-gated.
- **Proves itself**: pre-committed criterion à la NB-C2 BEFORE running: AUROC separating known-absent
  from answerable arms on BOTH fixtures, threshold ≥0.75 (the bar NB-C2 used), leakage guards intact.

### #5 — Stratum-routed retrieval (Adaptive-RAG pattern applied to depth/expansion, not skip-retrieval)

- **Yield**: F4 (hard 0.167, negation 1/7) and F5 (multi-paper 1/5) via conditional treatment:
  deeper pools + (only for flagged queries) IRCoT-style decomposition, whose retrieval-side gains
  (+up to 21 points) are the one passage-plausible decomposition result. Weakest published support of
  the five — the same family carries negative passage-level results on non-multi-hop data (§2.4), so
  the router must be proven per-stratum, not assumed.
- **Cost**: scripts → app-level (classifier can start rule-based: negation cues, question-type);
  decomposition path uses existing Ollama models.
- **Proves itself**: stratum-conditioned block-P@1 on the hard/negation slices (PREC-1 §4 defines
  them) and the 5 exposed multi-paper items — with denominators printed, tiny-n flagged.

**Explicitly not recommended, with reasons**: GraphRAG-class (gains reverse under unbiased
evaluation; wrong regime; indexing cost on shared GPU); Search-R1-class RL agents (training infra
impossible here; answer-level only); HyDE (two independent negatives; worst-case domain match);
Self-RAG training (cost class + no passage-level evidence); agentic memory (N/A).

**Residual honesty note**: even if #1–#3 fully land, NB-R0 arithmetic caps text-arm block-P@1 at
0.9333 (@K=128) on ver84; the same_doc_elsewhere upstream tail and F7 vision items remain out of
reach of every technique in this report.

## 6. Source register

1. Self-RAG — https://arxiv.org/abs/2310.11511
2. CRAG (Corrective RAG) — https://arxiv.org/abs/2401.15884 ; v2 details — https://arxiv.org/abs/2401.15884v2
3. Adaptive-RAG — https://arxiv.org/abs/2403.14403
4. IRCoT — https://arxiv.org/abs/2212.10509
5. Self-Ask — https://arxiv.org/abs/2210.03350
6. FLARE — https://arxiv.org/abs/2305.06983
7. Search-R1 — https://arxiv.org/abs/2503.09516 ; v1 — https://arxiv.org/pdf/2503.09516v1
8. HyDE — https://arxiv.org/abs/2212.10496 ; ACL version — https://aclanthology.org/2023.acl-long.99.pdf
9. HyDE knowledge-leakage audit — https://www.alphaxiv.org/abs/2504.14175
10. T2-RAGBench (HyDE-negative, contextual-positive) — https://arxiv.org/html/2604.01733v1
11. Microsoft GraphRAG — https://arxiv.org/abs/2404.16130
12. LightRAG — https://aclanthology.org/2025.findings-emnlp.568.pdf
13. RAG vs. GraphRAG systematic evaluation — https://arxiv.org/html/2502.11371v2
14. Unbiased GraphRAG evaluation (bias reversal) — https://arxiv.org/pdf/2506.06331
15. LightRAG SEC-filings independent benchmark — https://bestin-it.com/lightrag-benchmark-sec-filings/
16. ColBERTv2 — https://arxiv.org/abs/2112.01488
17. Jina-ColBERT-v2 — https://huggingface.co/jinaai/jina-colbert-v2 ; paper — https://aclanthology.org/2024.mrl-1.11/
18. AnswerAI-ColBERT-small-v1 — https://www.answer.ai/posts/2024-08-13-small-but-mighty-colbert.html
19. GTE-ModernColBERT — https://huggingface.co/lightonai/GTE-ModernColBERT-v1
20. PyLate — https://arxiv.org/html/2508.03555 ; token pooling — https://arxiv.org/abs/2409.14683
21. Qwen3 Embedding/Reranker — https://arxiv.org/abs/2506.05176 ; https://github.com/QwenLM/Qwen3-Embedding
22. Anthropic Contextual Retrieval — https://www.anthropic.com/news/contextual-retrieval
23. Late chunking — https://arxiv.org/abs/2409.04701
24. RAPTOR — https://arxiv.org/abs/2401.18059
25. Searching for Best Practices in RAG — https://arxiv.org/abs/2407.01219 ; EMNLP version — https://aclanthology.org/2024.emnlp-main.981.pdf
26. UDCG / Redefining Retrieval Evaluation — https://aclanthology.org/2026.eacl-long.391.pdf
27. Facet-level evidence tracing — https://arxiv.org/html/2604.09174v2
28. Attribution-metric transfer audit — https://arxiv.org/html/2606.23915
29. Faithfulness-hallucination benchmark (Springer ML) — https://link.springer.com/article/10.1007/s10994-026-07121-y
30. Lost in the Middle — https://arxiv.org/abs/2307.03172
31. Position/context-size reproducibility study — https://arxiv.org/html/2605.27105v2
32. SoK: Agentic RAG — https://arxiv.org/html/2603.07379v1
33. Failure-mode taxonomy (TrustNLP) — https://aclanthology.org/2026.trustnlp-main.27.pdf
