# PHASE0-RUNBOOK — de-risking before the build (V0)

Phase 0 answers the questions V0 cannot start without: **which parser, which embedder, which vector store**,
and **is retrieval good enough**. V0 needs only a *light* Phase 0 (PRD §9 scope note): **S0 bring-up + Spike 1
(parse) + Spike 2 (retrieval)**. Spike 3 (reconciliation) and Spike 5 (consumption) gate V1+, not V0 — do not
run them now.

A spike that cannot fail isn't a spike. Each one below has a **measurable gate** and a **decision it unblocks**.
Record the numbers in `phase0-results.md` — they become the baselines and regression gates for the whole build.

Owner F + the parser owner (B) and retrieval owners (C/D/E) run Phase 0. The other owners start the shared
foundation (DATA-CONTRACTS types, Config, schema, fakes) in parallel — they don't need Phase 0 to begin,
because the interfaces are fixed even though the adapters aren't.

---

## S0 — Bring-up (prerequisite; ~1 day)

Goal: the box is healthy and the pipeline runs end-to-end on **one** paper.

1. **Fix the GPU driver.** Resolve the `nvidia-smi` NVML driver/library mismatch (reboot or reload the kernel
   module). Verify `python -c "import torch; print(torch.cuda.is_available())"` prints `True` and sees the 3090.
2. **Stand up services (Docker):** Qdrant (persistent volume); the embedding server (TEI or vLLM — ADR-03,
   *not* Ollama/GGUF for embeddings); and **the summarization LLM service** (Qwen tier per ADR-08, served
   via Ollama per ADR-09) — a **separate** service from the embedding server. This is not optional bring-up:
   `DocumentStore.put(PaperRecord)` requires non-nullable `summary_text` (DATA-CONTRACTS §M5), so the S0
   exit gate below cannot complete without it. (No LLM service is needed for *chunking* in V0 — contextual
   headers are a V1 feature, ADR-07 — but summarization is a distinct V0-scoped decision; see ARCHITECTURE
   M3B.)
3. **Assemble the representative set:** 30–50 papers from the causal-methods `focus_area` — deliberately
   include math-heavy, code-heavy, multi-column, table-heavy, and **one broken/scanned PDF**.
4. **Exit gate:** one paper flows harvest → parse → {chunk, summarize} → embed → store → a retrievable
   result, by hand. If this doesn't work, nothing downstream will — do not proceed.

---

## Spike 1 — Parse + provenance fidelity  *(unblocks: Parser adapter choice, ADR-06)*

**Gates:** Parser (M2), Chunker (M3), and any ticket consuming `Anchor` (WORK-BREAKDOWN.md) — `Anchor`'s
shape is the frozen-contract bet this spike settles. M1/Harvester is unaffected and proceeds regardless.

**Assumption at risk:** a parser recovers equations/code/tables **and** its blocks anchor back to the source
(the grounding contract). Char offsets are already known not to survive PDF→markdown — the contract is
**block-bbox + snippet** (CONTEXT.md).

**Method:**
1. Run **MinerU**, **Marker**, and **Docling** (PRD §11B promoted Docling) over the S0 set.
2. Rubric-score each on: equations preserved as LaTeX, code intact, tables usable, reading order correct,
   section paths sane, GROBID references parsed.
3. **Round-trip test the anchor:** take a block's `(page, bbox, snippet)`, and confirm it highlights the
   correct region of the source PDF. This is the grounding guarantee — measure the success rate.
4. Trial the **arXiv-LaTeX ingest path** on a couple of papers (best-case anchoring against `.tex`).

**Gate (pass/fail):**
- Pick one parser (MinerU or Marker; add Docling if tables are load-bearing or its speed wins).
- **Block-anchor round-trip ≥ ~95%** on the set.
- GROBID references look sane.

**Output:** the chosen `parser_id` becomes the V0 `Parser` adapter. The scored PDFs become the **golden
fixtures** (TEST-STRATEGY). Record the throughput number — it feeds the 15k backfill estimate.

**If it fails:** if no parser clears the anchor gate, the grounding contract is at risk — escalate before
building. Do not lower the bar silently; grounding is the product.

---

## Spike 2 — Retrieval quality  *(unblocks: embedder + reranker + vector config, ADR-02/03/10/11)*

**Gates:** VectorIndex (M6) / Retriever (M7) tuning — top-k, hybrid weights, rerank depth (WORK-BREAKDOWN.md).

**Assumption at risk:** Qwen3-Embedding-4B ≥ BGE-M3 on *our* corpus, and hybrid+RRF+rerank beats plain dense.

**Method:**
1. Parse + chunk the S0/representative papers (using the Spike-1 parser). Build the **~200-question eval
   set** on the resulting chunks — **agent-generated, no human labeler** (PRD §11 Q6, RESOLVED; full
   mechanism in TEST-STRATEGY.md "Retrieval eval set"): sample chunks stratified across the 6 causal
   sub-topics (CONTEXT.md), generate one natural question per sampled chunk with the local generation LLM
   (gold label = that chunk's `chunk_id`), then run an automated judge pass to discard degenerate
   questions (near-verbatim question/chunk overlap, answerable without the passage, under-specified,
   answerable from the title/section prefix alone). Over-generate ~300, commit ~200 survivors to
   `fixtures/eval/eval_set.jsonl`. **Caveat to carry forward:** synthetic questions have more
   lexical/semantic overlap with their source chunk than a real user's phrasing would, so Recall@10 on
   this set is an optimistic upper bound — still a valid permanent regression gate, just not a
   real-world-query guarantee.
2. Embed with each candidate: **Qwen3-Embedding-4B** and **BGE-M3** (optionally 8B), served via TEI/vLLM.
3. Sweep configs: `{dense}` vs `{hybrid dense+sparse+RRF}` vs `{hybrid + cross-encoder rerank}`
   (BGE-reranker-v2-m3 or Qwen3-Reranker). Optionally A/B SPECTER2/SciNCL for summary routing (PRD §11B).
   **Contextual headers are NOT part of this sweep** — they're a V1 feature, not a V0 build decision
   (ADR-07); don't spend Phase-0 time generating them.
4. Measure **Recall@10, MRR**, and **retrieval-failure rate** (PRD §11B: how often the right chunk wasn't
   retrieved at all). **Tag context-related failures automatically** — a result where the gold chunk was
   retrieved-adjacent (same paper/section, near-miss rank) but scored low, suggesting it reads
   ambiguously without surrounding text (e.g. "we set β=0.9" with no visible link to "Adam optimizer
   ablation"). This tag is the **monitoring signal handed to V1** for the contextual-header decision —
   record the count/rate in `phase0-results.md`, but do not act on it in V0.

**Gate (pass/fail):**
- Lock the embedder, reranker, and retrieval config (top-k, hybrid weights, rerank depth).
- **Recall@10 ≥ ~0.85.**
- **Hybrid and the reranker are kept in V0/V1 regardless of this spike's result** — the eval set is
  synthetic (a question generated from its own gold chunk), which is directionally biased toward making
  both components look unnecessary (shared vocabulary inflates lexical/dense match) exactly when they
  exist to rescue real, vocabulary-mismatched research questions the synthetic eval underrepresents. The
  synthetic eval's shared-vocabulary bias cannot be trusted to justify dropping either. Spike 2's job here
  is to **lock the retrieval config** (embedder choice, top-k, hybrid weights, rerank depth) and confirm
  Recall@10 ≥ ~0.85, not to decide keep/drop. A future post-V0/V1 revisit may reconsider dropping either
  component, but only against a human-phrased (not synthetic) eval set.

**Output:** locked `Embedder` model + `EmbedderInfo.version`, reranker choice, and the `Config` retrieval
knobs. The eval set becomes the **permanent regression gate** for any future model/DB swap (TEST-STRATEGY).

**If it fails:** if neither embedder clears 0.85, do not ship V0 on it — retrieval quality *is* the V0 north
star (token-saving cache is worthless if it retrieves the wrong passage). Investigate chunking first (a common
cause), then try the 8B model, then escalate.

---

## Vector store note (already decided — verify, don't re-litigate)

ADR-01 selects **Qdrant** for V0 (native local dense+sparse hybrid + RRF; Chroma OSS lacks native hybrid —
verified). In Spike 2, **verify** Qdrant's hybrid + payload filtering behave as expected on the real config —
specifically, confirm whether Qdrant's native fusion can express the **weighted-RRF formula** frozen in
DATA-CONTRACTS §M6 (`RRF_K=60` + `hybrid_dense_weight`); if not, the `VectorStore` adapter must compute the
fusion itself from separate dense/sparse result lists so the fake and real adapter provably agree (see the
contract-test note there). Also verify `SearchFilters` fields (categories/date-range/kind) map cleanly onto
Qdrant payload filtering. Only evaluate LanceDB if avoiding a Docker service turns out to matter. Don't reopen
the DB question without a new fact — the decision is fact-driven and cheap to reverse later anyway (vectors
rebuild, ADR-04).

---

## Phase 0 exit criteria (all must hold before the parallel build integrates)

- [ ] GPU healthy; Qdrant + embedding server + summarization LLM service up; pipeline runs end-to-end
      (including summarize) on the representative set.
- [ ] **Parser locked with numbers**; anchor round-trip ≥ ~95%; golden fixtures committed.
- [ ] **Embedder + reranker + retrieval config locked with numbers**; Recall@10 ≥ ~0.85; hybrid/rerank each
      justified their complexity.
- [ ] The ~200-question, agent-generated retrieval eval set exists and is committed as a regression gate.
- [ ] Real papers/hour measured → a realistic 15k backfill plan (smoke-test 200 papers, then run overnight).
- [ ] `phase0-results.md` records every number, so no decision is "asserted, not proven" (PRD §9 ethos).

Once these hold, the adapters behind the three real seams are chosen, and Owners A–E integrate their modules
against them. Everything before this point is de-risking; everything after is the V0 build (WORK-BREAKDOWN.md).
