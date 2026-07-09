# Technical Design & Annotated Survey: An Advanced RAG System for Applied-Science Academic Literature (Causal Inference, EconML, Causal ML, LLM Applications)

## TL;DR
- Build a **multimodal, hybrid, hierarchical RAG system** with a layout-aware parsing front end (MinerU/Docling + Mathpix for math), section-aware parent-child chunking, contextual retrieval, hybrid dense+BM25 search with cross-encoder reranking, and a citation-graph/GraphRAG reasoning layer — recommended core stack: **Qdrant** (15K MVP → tens of millions) with a **Milvus/DiskANN** migration path at billions, **SPECTER2 + E5-Mistral/Voyage** dual embeddings, and a **ColBERT/ColPali** late-interaction layer (served at scale via MUVERA) for math-heavy and figure pages.
- The single biggest lever for "let the smart agent be smart AND save tokens" is **retrieval precision + context compression**: contextual retrieval cuts the top-20 retrieval-failure rate from 5.7% to 1.9% (a 67% reduction) with reranking, cross-encoder reranking shrinks the context passed to the LLM, LLMLingua compresses context 2–20×, and semantic caching eliminates 30–70% of LLM calls entirely.
- **Math is the domain's hardest unsolved problem**: general embeddings fail at mathematical equivalence, so preserve LaTeX end-to-end, store equations as first-class typed nodes, and add a symbolic (SymPy/CAS) representation to make derivations checkable rather than trusting text embeddings or next-token prediction alone.

## Key Findings
1. **PDF parsing is the make-or-break stage** — garbage-in, garbage-out. For born-digital applied-science PDFs, MinerU 2.5 leads on layout (97.5 mAP) and preserves LaTeX equations and tables; Docling is faster (~8.2s vs 14.7s on a 12-page paper) and Apache-2.0 (commercial-friendly); olmOCR and other VLM approaches win on scanned/legacy documents. No single tool wins everything — route by document type.
2. **Chunking must be section-aware and hierarchical** — parent-child (retrieve small, generate on large) plus Anthropic's contextual retrieval is the production default; equations/tables must be kept intact as atomic units.
3. **Domain embeddings matter but don't win alone** — SPECTER2/SciNCL beat general models on scientific document similarity, but general leaders (E5-Mistral, Voyage, Qwen3-Embedding) are stronger for QA; use a two-model approach and add a late-interaction (ColBERT/ColPali) layer for precision and math/figure pages.
4. **Advanced RAG (GraphRAG, RAPTOR, HippoRAG) enables cross-paper reasoning** — but at real cost (3–10× tokens, 2–5× latency); use adaptive routing so cheap queries never hit the expensive graph path.
5. **Provenance and math are the credibility backbone** — citation graphs (OpenAlex/Semantic Scholar), inline span-level attribution, and contradiction handling reduce but do not eliminate hallucination, which persists even with retrieval.

## Details

### 1. PDF Parsing & Document Understanding
The literature partitions PDF parsers into **pipeline-based systems** (chained ML components: layout detection → table/formula/section parsing) and **end-to-end VLM models** (page image → text). For scientific papers specifically:

- **MinerU (2.5)** — OpenDataLab. Integrates DocLayout-YOLO; reported SOTA on layout detection (~97.5 mAP), full table preservation, LaTeX equation extraction. AGPL-3.0 (source-release obligation if distributed), ~2× slower than Docling. Best structural fidelity for research papers. (arXiv:2409.18839; MinerU2.5 arXiv:2509.22186)
- **Docling** — IBM/Deep Search. Apache-2.0, faster (~8.2s vs 14.7s on a 12-page academic paper), simpler setup, aligns well with downstream AI pipelines; weaker table internal structure in some tests. (arXiv:2408.09869)
- **olmOCR** — Ai2. Fine-tuned Qwen2-VL-based VLM with "document anchoring"; excels on complex visual layouts, multi-column, and scanned/legacy archives; ~1/35th the cost of frontier APIs; released olmOCR-mix-0225 (260K pages) + olmOCR-Bench. (arXiv:2502.18443)
- **Nougat** — Meta. End-to-end transformer, page image → Markdown+LaTeX; strong on math but prone to repetition/hallucination loops and slow.
- **GROBID** — the long-standing scientific-document workhorse; best-in-class for metadata + bibliographic reference parsing (used by S2ORC/peS2o). Weak on equations/tables.
- **Marker** — datalab-to. Fast pipeline PDF→Markdown; strong general performance, good balance.
- **Mathpix** — commercial, best-in-class math OCR (LaTeX/MathML).
- **PyMuPDF4LLM / pypdf** — fast rule-based text-layer extraction for born-digital PDFs only; cannot handle images/scans.
- **Others benchmarked in 2025:** GOT-OCR 2.0, MonkeyOCR, Nanonets-OCR-s, PaddleOCR-VL, Mistral OCR ($1/1,000 pages), Dolphin, LlamaParse, Unstructured.

**Benchmarks to evaluate against:** OmniDocBench (CVPR 2025; 1,651 pages, 10 doc types, arXiv:2412.07626), READoc (arXiv:2409.05137), olmOCR-Bench (unit-test-driven), and a dedicated 2025 formula-extraction benchmark (arXiv:2512.09874) covering inline+display formulas.

**Recommendation:** Route by document class. Born-digital modern papers → MinerU (structure) or Docling (speed/license); math-dense pages → add Mathpix; scanned/legacy → olmOCR. Keep GROBID for reference/metadata extraction regardless. Preserve LaTeX for all equations.

### 2. Chunking Strategies
- **Parent-child / hierarchical chunking** is the production default: index small child chunks for precise retrieval, return larger parent sections for generation. Practitioners commonly start at 512-token children with 10–20% overlap.
- **Section-aware / layout-aware chunking** respects the paper's logical structure (abstract, methods, results) rather than fixed character counts. Treat tables/figures/equations as first-class atomic retrieval nodes (HiKEY, structural chunking).
- **Late chunking (Jina AI, 2024)** — embed the full document through a long-context model first, then split, so each chunk's embedding carries whole-document context.
- **Contextual retrieval (Anthropic, Sept 19, 2024)** — prepend an LLM-generated context blurb to each chunk before embedding/indexing. Anthropic's reported results: Contextual Embeddings reduced the top-20-chunk retrieval failure rate by 35% (5.7% → 3.7%); adding Contextual BM25 by 49% (5.7% → 2.9%); adding reranking by 67% (5.7% → 1.9%).
- **Proposition / "Dense X" chunking** — decompose to atomic propositions; higher precision but weaker context continuity.
- **Semantic / LumberChunker / Meta-Chunker** — LLM- or perplexity-driven boundary detection.

**Recommendation:** Section-aware parent-child + contextual retrieval, with equations/tables kept intact. Chunk boundaries must never split an equation from its defining context.

### 3. Embedding & Representation
- **Scientific-specialized:** SPECTER2 (adapter-based, trained on citation signal across 23 fields, EMNLP 2023; SciRepEval avg ~65.5), SciNCL (citation-neighborhood contrastive, arXiv:2202.06671), SciBERT. These win on scientific document similarity/proximity/clustering.
- **General SOTA (strong for QA):** E5 / E5-Mistral, BGE (M3 for hybrid), Nomic (8K context), Voyage (voyage-3), OpenAI text-embedding-3 (Matryoshka support), Cohere, Gemini Embedding, Qwen3-Embedding-8B (MTEB v2 ~70.6), Jina v3.
- **Matryoshka Representation Learning (Kusupati et al., NeurIPS 2022)** — nested embeddings; truncate to 256/512/1024 dims to cut storage with minimal quality loss.
- **Multi-vector / late interaction:** ColBERTv2 (token-level MaxSim; compresses to ~20–36 bytes/vector, arXiv:2112.01488), ColPali/ColQwen (patch-level embeddings for document images — critical for figures, charts, equation-heavy pages, arXiv:2407.01449), Jina-ColBERT-v2 (multilingual, Matryoshka).
- **Math embeddings caveat:** general embedding models fail to capture mathematical equivalence (MathNet benchmark shows models match on surface keywords, not structure). MathBERT and formula-structure (leaf-root path / operator-tree) approaches help but remain immature.

**Recommendation:** Dual-embedding — a scientific model (SPECTER2/SciNCL) for paper-level similarity/recommendation + a strong general/instruction model (E5-Mistral or Voyage) for chunk-level QA, plus a ColBERT/ColPali late-interaction layer for high-precision reranking and figure/equation pages. Use Matryoshka truncation to control storage at scale.

### 4. Retrieval Architecture
- **Hybrid dense + sparse (BM25)** is essential — dense embeddings miss exact matches (equation symbols, theorem names, citation keys, identifiers) that BM25 catches. Native hybrid supported by Weaviate (BlockMax WAND), Milvus 2.5+ (Sparse-BM25), Qdrant (named vectors, server-side IDF). Chroma and plain pgvector do not.
- **Reranking (cross-encoders):** Cohere Rerank, BGE reranker, ColBERT MaxSim. Rerank a small candidate set to control latency/cost.
- **Query transformation:**
  - **HyDE (Gao et al., ACL 2023, arXiv:2212.10496)** — prompt an LLM to write a hypothetical answer/document, embed *that* for retrieval; strong zero-shot gains, "significantly outperforms the state-of-the-art unsupervised dense retriever Contriever." (Note: third-party sources report 25–60% latency overhead — validate on your own stack.)
  - **Query Rewriting / Rewrite-Retrieve-Read (Ma et al., EMNLP 2023, arXiv:2305.14283)** — a small trainable rewriter (RL-tuned) closes the query↔knowledge gap for a frozen black-box reader.
  - **Query decomposition (multi-hop):** Self-Ask (arXiv:2210.03350), Least-to-Most (arXiv:2205.10625), IRCoT (arXiv:2212.10509), Decomposed Prompting (arXiv:2210.02406). Benchmarks: HotpotQA, 2WikiMultiHopQA, MuSiQue, MultiHop-RAG.
- **Vector DB scaling comparison:**

| DB | Sweet spot | Notes |
|---|---|---|
| **pgvector** | ≤ ~50M vectors, existing Postgres | ACID, SQL; no native hybrid; simplest ops |
| **Qdrant** | perf + filtering + hybrid, tens of millions | Rust, latency edge, late-interaction support, quantization |
| **Weaviate** | hybrid-search-heavy | strongest hybrid story (BlockMax WAND) |
| **Milvus/Zilliz** | 100M–billions | routinely billion-scale in production |
| **LanceDB** | embedded/multimodal/edge | Lance columnar, newer/less mature |
| **Chroma** | prototyping | no native hybrid |

**Recommendation:** Start on **Qdrant** (hybrid + late interaction + filtering + quantization) for the 15K→tens-of-millions range; plan a **Milvus** migration path for billions. Use pgvector only if already Postgres-committed and under ~50M. Hybrid + rerank + HyDE/decomposition as standard.

### 5. Advanced RAG Architectures
- **RAPTOR (Sarthi et al., ICLR 2024)** — recursive clustering + summarization into a tree; retrieve at multiple abstraction levels; excellent for "synthesize across many papers" queries.
- **GraphRAG (Microsoft, Edge et al., 2024, "From Local to Global," arXiv:2404.16130)** — LLM-extracted entity/relation graph + community summaries; strong on global sensemaking; Microsoft's own tests report ~70–80% win rates on comprehensiveness/diversity vs naive RAG. (The often-cited "86% vs 32%" figure traces specifically to Writer's RobustQA benchmark (2024), where a knowledge-graph approach scored 86.31% versus 59–75% for other RAG methods — attribute it to Writer RobustQA, not Microsoft's own evaluation.) Expensive due to many LLM calls.
- **HippoRAG / HippoRAG 2 (Gutiérrez et al., 2024/2025, arXiv:2405.14831 / 2502.14802)** — Personalized PageRank over an LLM-built KG; neurobiologically inspired; strong multi-hop associative retrieval, markedly cheaper multi-hop than iterative approaches.
- **LightRAG (Guo et al., 2024)** — dual-level (low-level entity + high-level thematic) graph retrieval; cheaper than GraphRAG.
- **Contextual Retrieval (Anthropic)** — see §2; the highest ROI-per-effort technique.
- **Self-RAG (arXiv:2310.11511), CRAG (arXiv:2401.15884), Adaptive-RAG (arXiv:2403.14403)** — reflection tokens / retrieval evaluator with corrective routing / difficulty-based routing. Adaptive-RAG's classifier costs ~5–15 ms and lets easy queries skip the agent loop entirely.
- **PathRAG, ToG-2, GFM-RAG, KET-RAG, MiniRAG** — recent graph efficiency variants.

**Recommendation:** Layered — contextual retrieval + hybrid + rerank as the always-on base; RAPTOR tree for synthesis queries; a citation/concept GraphRAG or HippoRAG layer for multi-hop reasoning; adaptive routing (a small classifier) to decide retrieval depth per query.

### 6. Knowledge Graphs & Structure
- **External scholarly graphs:** OpenAlex (works/authors/venues/concepts; metadata CC0, arXiv:2205.01833), Semantic Scholar Academic Graph (S2AG: 225M+ papers, 100M+ authors, 2.8B+ citation edges), DBLP, ORKG, Crossref. Use their APIs to bootstrap citation edges, venue, author, and citation-count metadata.
- **Internal KG construction:** LLM entity/relation extraction (papers, methods, metrics, datasets, claims) into a Neo4j-style schema; resolve intra-corpus citations to CITES edges; link chunks via HAS_CHUNK to bridge text index and graph (cf. TechRAG, arXiv:2606.01613).
- **Graph embeddings** (TransE/RotatE) to blend structural + semantic retrieval.

**Recommendation:** Two-tier graph: (a) a bibliographic citation graph seeded from OpenAlex/S2AG for provenance and credibility signals; (b) a concept/method/claim graph extracted from full text for reasoning and cross-paper linking. For the causal-inference/EconML domain specifically, model methods (IV, DiD, double/debiased ML, causal forests, synthetic control), identifying assumptions, estimands, and datasets as first-class nodes so the agent can reason over "which method under which assumptions."

### 7. Credibility, Provenance & Trust
- RAG reduces but does not eliminate hallucination. Legal-domain evaluation (Magesh et al., Stanford RegLab, *Journal of Empirical Legal Studies* 2025, arXiv:2405.20362) found that leading AI legal-research tools "hallucinate between 17% and 33% of the time" (Westlaw AI-Assisted Research at the 33% end).
- **Attribution is architecturally fragile:** Wallat et al., "Correctness is not Faithfulness in RAG Attributions" (arXiv:2412.18004, Dec 2024), found "up to 57% of citations being post-rationalized" (unfaithful). Liu, Zhang & Liang (EMNLP 2023 Findings, "Evaluating Verifiability in Generative Search Engines," arXiv:2304.09848) found "a mere 51.5% of generated sentences are fully supported by citations and only 74.5% of citations support their associated sentence." Inline citation *during* generation (not post-hoc) is a necessary condition for faithfulness; StrictCitations-style prompting turns the LLM into a verifiable extractor.
- **Contradiction handling:** corroborating/refuting evidence retrieval (CIBER, arXiv:2503.07937) for claim verification; NLI-based claim-level entailment checks (DeBERTa) for faithfulness scoring; Vectara HHEM for hallucination detection.
- **Credibility signals:** venue, citation count, retraction status (Retraction Watch/Crossref), preprint vs peer-reviewed flag — attach as metadata and expose to the ranker and the end LLM.

**Recommendation:** Enforce inline, span-level citations generated inline (not post-hoc); store provenance (paper ID, version, section, char offsets) on every chunk; add a claim-verification pass for high-stakes synthesis; surface credibility metadata to both ranker and end LLM.

### 8. Handling Math, Equations & Scientific Reasoning
- Preserve **LaTeX end-to-end** from parsing through storage to prompt.
- Store equations as **first-class typed nodes** with: LaTeX string, surrounding context, a natural-language gloss, and (where parseable) a **SymPy/CAS symbolic form** to make derivations checkable.
- General embeddings fail at mathematical equivalence (MathNet, arXiv:2604.18584); use formula-structure representations (operator/symbol-layout trees, leaf-root paths — Zanibbi et al. lineage; MathBERT) and/or dedicated formula embeddings for math-aware retrieval; retrieve math by both symbolic structure and textual context.
- For derivation checking, route to a CAS (SymPy) via tool use rather than trusting LLM token prediction — this is how "checkable derivations" become real.

### 9. Efficiency & Token Optimization
- **Reranking + retrieval precision** — the primary token saver: pass only the top few high-precision chunks.
- **Prompt compression — LLMLingua / LongLLMLingua / LLMLingua-2 (Microsoft):** 2–20× compression with <2% quality loss on CoQA/HotpotQA/TriviaQA. LongLLMLingua (ACL 2024, arXiv:2310.06839) reports "a performance boost of 21.4% on NaturalQuestions with the ground-truth document at the 10th position" using ~1/4 of tokens (4× compression), and a 94.0% cost reduction on the LooGLE benchmark — directly mitigating "lost-in-the-middle."
- **Semantic caching (GPTCache, Redis vector cache):** 30–70% of requests served from cache; GPTCache reports 61.6–68.8% hit rates with 97%+ positive-hit accuracy; set cosine threshold ≥0.92 for factual workloads; watch embedding drift and use TTL.
- **Provider prompt/prefix caching:** Anthropic up to 90% cost / 85% latency reduction on cache reads; OpenAI automatic (~50%). Stack semantic + prefix caching for 60–80% total reduction.
- **Adaptive retrieval:** a small classifier (~5–15 ms) decides no-retrieval / single-hop / multi-hop, so easy queries skip the expensive path.
- **RAPTOR/summarization layers** provide compressed abstraction levels to avoid dumping full papers into context.

**Recommendation:** Precision-first retrieval + rerank → LLMLingua compression on the surviving context → multi-tier caching (semantic → prefix → inference) → adaptive routing. This chain is the core of "smart RAG that lets the smart agent be smart AND saves tokens."

### 10. Evaluation
- **Frameworks:** RAGAS (reference-free: faithfulness, answer relevancy, context precision/recall — most adopted), TruLens (groundedness via claim decomposition; production tracing), ARES (trained LLM judges + synthetic data + confidence intervals, arXiv:2311.09476), DeepEval (CI/CD enforcement).
- **Critical caveat:** these measure faithfulness *to retrieved context*, NOT whether that context is correct/current — a system can score 0.95 faithfulness and still be wrong if the index is stale. Add a "context trustworthiness" dimension (ownership, freshness, lineage).
- **Scientific benchmarks:** SciFact (claim verification), BEIR (SciFact/NFCorpus subsets), plus a hand-curated causal-inference/EconML gold set. (Illustrative RAGAS numbers on SciFact 5K docs: context precision ~0.32, faithfulness ~0.71 — domain sensitivity is real.)
- **Retrieval metrics:** recall@k, nDCG@k, context precision/recall; retrieval-failure rate (Anthropic's headline metric).

**Recommendation:** RAGAS in CI with explicit per-metric thresholds; TruLens/Phoenix for production tracing; a curated domain gold set; track retrieval-failure rate and faithfulness as headline KPIs.

### 11. Scaling & Infrastructure
- **Ingestion:** distributed processing with Ray (parallel parse + embed across GPUs) or Spark; a common AWS pattern uses Ray → OpenSearch/pgvector. Orchestrate with Airflow/Dagster/Prefect.
- **Incremental indexing:** manifest-tracked, idempotent MERGE for the graph, append-only for vector/BM25 indices; compute embeddings only for new PDFs.
- **ANN index types:** Flat (exact, small), HNSW (fast, high recall, memory-heavy), IVF (cheaper memory), IVF+PQ (compressed), **DiskANN** (billion-point NN from SSD with low RAM, NeurIPS 2019). **Product Quantization** (Jégou et al., 2011) compresses vectors ~32×.
- **MUVERA (Google, NeurIPS 2024, arXiv:2405.19504):** maps multi-vector (ColBERT/ColPali) sets to single **Fixed Dimensional Encodings (FDEs)** so standard MIPS/DiskANN can serve late-interaction retrieval, replacing the complex four-stage PLAID pipeline. Reported: ~10% higher recall with ~90% lower latency vs PLAID across 6 BEIR datasets (up to 56% higher recall, up to 5.7× lower latency), retrieving 2–5× fewer candidates; PQ compresses the 10,240-dim FDEs to 1,280 bytes (32× reduction). Critical for scaling the late-interaction layer to millions+.
- **Storage/compute:** decouple compute from storage; self-hosting embeddings beats API cost only above ~10–15M embeddings/month.

**Recommendation:** Ray-based ingestion; HNSW at 15K–tens-of-millions; migrate to DiskANN/IVF-PQ + MUVERA for the multi-vector layer at hundreds of millions to billions; incremental idempotent indexing from day one.

### 12. Risks & Pitfalls
- **Parsing errors propagate** — bad LaTeX/table extraction poisons everything downstream (GIGO). Mitigate with parser routing + validation + spot QA.
- **Chunk-boundary problems** — splitting equations/proofs from context; mitigate with section-aware atomic chunking.
- **Embedding drift** — model updates change vectors, breaking caches and forcing re-indexing.
- **Stale indexes** — versioned papers, retractions; needs incremental refresh + versioning.
- **Hallucination despite retrieval** — 17–33% in the legal domain; needs inline attribution + claim verification.
- **Cost blowup** — agentic loops 3–10× tokens; mitigate with adaptive routing + caching + compression.
- **Math mishandling** — general embeddings fail at equivalence; needs a symbolic layer.
- **Prompt injection via documents (indirect / corpus poisoning)** — OWASP LLM01:2025. PoisonedRAG (Zou et al., USENIX Security 2025, arXiv:2402.07867) achieved "a 90% attack success rate when injecting five malicious texts for each target question into a knowledge database with millions of texts." Agentic iteration compounds the risk. Mitigate with ingestion-time scanning, retrieved-chunk validation, injection classifiers (~80–85% on known patterns), instruction-pattern scanning, and treating the KB as untrusted.
- **Evaluation blind spots** — faithfulness ≠ correctness; a trustworthy-index dimension is needed.
- **Licensing/copyright** — see §13.

### 13. Design Considerations They May Not Have Thought Of
- **Metadata schema (critical):** paper ID, arXiv ID + version, DOI, venue, year, authors, citation count, retraction flag, preprint/peer-reviewed flag, license, section, char offsets, equation IDs, figure/table IDs. This powers filtered hybrid search, provenance, and credibility ranking.
- **Deduplication:** MinHash/LSH (Broder 1997) + exact-substring for byte-level (Lee et al., "Deduplicating Training Data Makes LMs Better," ACL 2022, arXiv:2107.06499 — dedup makes models emit memorized text ~10× less often); **SemDeDup (Meta, arXiv:2303.09540)** for semantic near-dups ("can remove 50% of the data [from LAION] with minimal performance loss, effectively halving training time").
- **Versioning:** collapse arXiv v1/v2/… on the base ID, keep the canonical/latest version; note different arXiv versions can carry different licenses; cluster preprint↔published via DOI + title/author + MinHash overlap.
- **Licensing/copyright at scale:** the arXiv default license is **non-exclusive** — arXiv (and by extension you) cannot redistribute full text; article *metadata* is CC0; per-article license is exposed via OAI-PMH; a minority of submissions are CC-BY/CC0. Publisher versions-of-record generally require a TDM (text-and-data-mining) license. Safest large-scale corpora: **S2ORC** (ODC-By, ~8–12M full-text papers, arXiv:1911.02782) and **peS2o** (ODC-By, ~40M open-access papers). If indexing arXiv full text, link back to arXiv for downloads.
- **Human-in-the-loop & feedback loops:** capture user corrections as retrieval-improvement signals — treat every correction as an index-quality signal.
- **Multi-tenancy & governance:** cache isolation (e.g., vLLM `cache_salt`), access controls, data lineage.
- **Observability:** monitor vector index size, search latency, retrieval-failure rate, cache hit rate, and embedding-drift histograms.
- **Cross-lingual:** multilingual embeddings (BGE-M3, Jina-ColBERT-v2) if the corpus spans languages.

## Annotated Survey — Quick-Reference Table
| Area | Key papers/tools (with IDs) | One-line contribution |
|---|---|---|
| PDF parsing | MinerU (2409.18839; 2509.22186), Docling (2408.09869), olmOCR (2502.18443), Nougat, GROBID, Marker, Mathpix | Structure/formula/table extraction; route by doc type |
| Parsing benchmarks | OmniDocBench (2412.07626), READoc (2409.05137), olmOCR-Bench, formula bench (2512.09874) | Standardized parsing/formula eval |
| Chunking | Contextual Retrieval (Anthropic 2024), Late Chunking (Jina), RAPTOR (ICLR 2024), Dense X | Section-aware, context-preserving chunking |
| Embeddings | SPECTER2 (EMNLP 2023), SciNCL (2202.06671), E5-Mistral, Voyage, BGE-M3, Matryoshka (NeurIPS 2022) | Scientific + general dual embeddings |
| Late interaction | ColBERTv2 (2112.01488), ColPali (2407.01449), MUVERA (2405.19504) | Token/patch-level precision; FDE for scale |
| Query transform | HyDE (2212.10496), RRR (2305.14283), Self-Ask (2210.03350), IRCoT (2212.10509) | Rewrite/decompose for better retrieval |
| Advanced RAG | GraphRAG (2404.16130), HippoRAG/2 (2405.14831/2502.14802), LightRAG, Self-RAG (2310.11511), CRAG (2401.15884), Adaptive-RAG (2403.14403) | Reasoning, multi-hop, self-correction, routing |
| Scholarly graphs | OpenAlex (2205.01833), S2AG (2301.10140), S2ORC (1911.02782) | Citation/provenance backbone |
| Trust/faithfulness | Magesh (2405.20362), Wallat (2412.18004), Liu (2304.09848), CIBER (2503.07937), RAGAS/ARES (2311.09476) | Hallucination/attribution measurement |
| Efficiency | LLMLingua/LongLLMLingua (2310.06839), GPTCache (2411.05276) | Compression + caching token savings |
| Corpus hygiene | Dedup (2107.06499), SemDeDup (2303.09540), DiskANN (NeurIPS 2019), PQ (TPAMI 2011) | Dedup + billion-scale ANN |
| Security | PoisonedRAG (2402.07867), Agentic RAG survey (2501.09136) | Corpus poisoning / injection defense |

## Recommendations (Phased)

**Phase 0 — 15K-PDF MVP (weeks):**
- **Parse:** MinerU (structure) or Docling (license/speed) + GROBID (references) + Mathpix (math pages); preserve LaTeX.
- **Chunk:** section-aware parent-child + Anthropic contextual retrieval; equations/tables atomic.
- **Embed:** E5-Mistral or Voyage (chunk QA) + SPECTER2 (paper similarity); Matryoshka truncation.
- **Retrieve:** Qdrant hybrid (dense+BM25) + Cohere/BGE reranker + HyDE for hard queries.
- **Generate:** inline span-level citations; RAGAS eval harness in CI; provider prompt caching on.
- Metadata schema + OpenAlex/S2AG enrichment + dedup (MinHash + SemDeDup) from day one.
- **Benchmark to advance:** retrieval-failure rate < 3%, faithfulness > 0.9 on domain gold set.

**Phase 1 — Reasoning & efficiency (months):**
- Add RAPTOR summarization tree (synthesis) + citation/concept GraphRAG or HippoRAG (multi-hop).
- Add ColBERT/ColPali late-interaction layer for math/figure precision.
- Add LLMLingua compression + semantic caching + adaptive-retrieval router.
- Add claim-verification/contradiction pass + credibility ranking; symbolic (SymPy) equation layer.
- **Benchmark to advance:** ≥60% token reduction vs naive RAG at equal answer quality; measurable multi-hop accuracy gain on the domain set.

**Phase 2 — Millions-scale (quarters):**
- Ray-based distributed ingestion; incremental idempotent indexing.
- Migrate hot path to Milvus/DiskANN; IVF-PQ quantization; MUVERA for the multi-vector layer.
- Full observability (drift, latency, failure-rate dashboards); prompt-injection scanning at ingestion; governance/licensing enforcement (prefer ODC-By corpora S2ORC/peS2o; arXiv link-back).
- **Threshold to revisit DB choice:** > ~50M vectors (leave pgvector), > ~100M (Milvus/DiskANN mandatory).

## Caveats
- Many 2026-dated sources here are vendor blogs and secondary write-ups; the headline benchmark numbers (MinerU 97.5 mAP; Anthropic 35/49/67%; MUVERA ~90% latency / ~10% recall vs PLAID; LLMLingua up to 20×; LongLLMLingua +21.4%) should be re-validated on your own data — generic benchmarks rarely transfer directly to a causal-inference/EconML corpus.
- The "86% vs 32%" GraphRAG figure is from Writer's RobustQA benchmark, not Microsoft's own evaluation, which reports ~70–80% win rates; treat GraphRAG's advantage as query-distribution-dependent.
- The math-retrieval frontier is genuinely unsolved: no embedding model reliably captures mathematical equivalence today; the symbolic-layer recommendation is a mitigation, not a solved capability.
- GraphRAG/agentic gains come with 3–10× token cost and 2–5× latency; they are justified only for genuinely complex/multi-hop queries — measure your query distribution before over-investing.
- A few arXiv IDs for query-decomposition and HippoRAG papers were confirmed via cross-references rather than direct abstract-page reads; double-check the exact digits before publication if citation precision is critical.