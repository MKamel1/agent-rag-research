# NB-R1 — agentic RAG state of the art (2025–2026), mapped to this system

Web-research ticket (NB programme). Written 2026-08-25 on branch `NB-R1-agentic-sota`.
**Status: STUB — commit 1 of N. Research in progress; every `[TODO]` below gets replaced before the
final commit. No pipeline code is touched by this ticket.**

## 0. Scope, method, and citation policy

- Deliverable: one cited report. Every non-obvious claim carries a URL (arXiv abs pages preferred).
- Each technique card flags whether its headline gains were measured on **passage/block-level metrics**
  (nDCG@k, recall@k, precision@k over passages — OUR target regime) or **answer-level QA metrics**
  (EM/F1 over generated answers — a different instrument; gains there do not automatically transfer,
  see §4).
- Claims whose sources were paywalled/unfetchable are marked per-claim rather than guessed.
- "State of the art" (published measured results) is distinguished from "state of the practice"
  (widely used, thin or vendor-published evaluation) throughout §2–§3.

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

## 2. Agentic / iterative RAG families (mechanism · measured gains · infra cost · failure modes)

[TODO: cards for Self-RAG; CRAG; adaptive-retrieval routers; IRCoT/Self-Ask/FLARE/subquestion
planners; iterative RL search loops (Search-R1 class); HyDE; GraphRAG-class; agentic memory]

## 3. Retrieval-quality adjacent levers

[TODO: cards for late interaction (ColBERTv2/PLAID class) on a 24GB budget; LLM-as-reranker /
listwise (RankGPT lineage, open-weight successors); contextual retrieval post-Anthropic-2024;
section/neighborhood-aware scoring]

## 4. Evidence-quality audit: passage-level vs answer-level claims

[TODO: where the literature measures answers not passages; divergence evidence; what transfers]

## 5. Ranked top-5 adoptable techniques for THIS system

[TODO: per item — expected yield mapped to F1–F7; implementation cost class (scripts /
app-level / contracts-gated); the benchmark that would prove it worked]

## 6. Source register

[TODO: consolidated numbered source list]
