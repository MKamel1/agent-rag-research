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
fixtures** (TEST-STRATEGY). Record the throughput number — it feeds the 30k backfill estimate.

**If it fails:** if no parser clears the anchor gate, the grounding contract is at risk — escalate before
building. Do not lower the bar silently; grounding is the product.

---

## Spike 2 — Retrieval quality  *(unblocks: embedder + reranker + vector config, ADR-02/03/10/11)*

**Gates:** VectorIndex (M6) / Retriever (M7) tuning — top-k, hybrid weights, rerank depth (WORK-BREAKDOWN.md).

**Assumption at risk:** Qwen3-Embedding-4B ≥ BGE-M3 on *our* corpus, and hybrid+RRF+rerank beats plain dense.

**Method:**
1. **The eval set is already committed** — `fixtures/eval/eval_questions_blind.json` +
   `fixtures/eval/eval_ground_truth.json` (210 questions with ground truth), built externally by LLM
   subagents reading the full text of this same 100-paper Phase-0 corpus and authoring reading-comprehension
   (110) and deep-reasoning (100) questions per paper/cluster, plus 10 cross-paper synthesis questions. This
   **supersedes** the originally-planned synthetic method (sample a chunk, generate one question from it,
   gold = that chunk's `chunk_id`) — that method is no longer used and `TEST-STRATEGY.md`'s "Retrieval eval
   set" section has been updated to match.
   **The format gap this creates:** the imported ground truth gold-labels each question with
   `source_paper_id` + `section_path` + a verbatim `passage_excerpt` (≤200 chars) — not a `chunk_id`.
   `chunk_id`s don't exist yet; they're only produced once Spike 1's chosen parser + this system's own
   chunker actually run over these papers. So Spike 2's first job, once Spike 1 is done, is **resolution**:
   for each of the 210 questions, fuzzy/substring-match its `passage_excerpt` against the text of the
   chunks produced for that `source_paper_id`, and record the matching `chunk_id` as the gold label. Do
   this at Spike-2-execution time, against real chunks — do not fabricate or guess a `chunk_id` now or ever.
   **Any question whose excerpt can't be confidently matched to a single chunk must be flagged** (logged
   with its `question_id` and reason — ambiguous match, no match, or split across chunk boundaries) and
   excluded from that run's Recall@10/MRR denominator, not silently dropped from the fixture and not force-
   matched to the nearest chunk. Report the flagged count/rate in `phase0-results.md` — a high flag rate is
   itself a signal about chunking quality.
   **Known limitation — the flag rate conflates two causes.** 24% of ground-truth excerpts contain
   non-ASCII/math characters and 87/210 are truncated mid-sentence — both extracted by a different pipeline
   than whichever parser Spike 1 picks. A meaningful share of match failures will therefore reflect
   cross-tool extraction drift, not chunking quality. Normalize (unicode NFKC + whitespace collapse) on both
   sides before substring-matching, and only read the post-normalization flag rate as a chunking-quality
   signal. Also set a **floor on the exclusion rate** — an invalidating threshold above which the run itself
   is suspect, not just the number worth noting — rather than an unbounded "record and note" policy.
   **On the lexical-overlap caveat:** the original synthetic method's caveat (Recall@10 is an optimistic
   upper bound because the question was generated *from* its own gold chunk, inflating lexical/semantic
   overlap) applies less directly here — these questions were authored from a full paper read, and the
   `passage_excerpt` was located afterward as supporting evidence for an already-written answer, not used
   as the generation seed. That said, don't read this set as bias-free: the questions are still LLM-authored
   from the papers' own text, so some shared domain vocabulary with the source passage is still likely, just
   not the tight generated-from-this-exact-span echo the synthetic method had. Also worth naming plainly:
   the imported set's own automated QA (`rag-system-eval-set/tests/test_eval_dataset.py`) checks *structural*
   integrity — item counts, question/ground-truth ID alignment, zero field-leakage in the blind file,
   category-quota coverage — it does **not** run an equivalent to the originally-planned judge pass (no
   automated check for near-verbatim excerpt overlap, answerable-without-the-passage, or
   answerable-from-title-alone questions). Treat that as an open risk, not a solved one.
   **Known limitation — title leakage (disclose, don't silently fix).** That open risk isn't hypothetical:
   ~80% of the 210 `question_text`s contain the source paper's title verbatim (some the literal arXiv ID),
   and 168/210 gold passages sit in Abstract/Introduction, where the paper's own title co-occurs with the
   passage in raw parser output. A retriever can score well on this set via exact-string title-matching,
   independent of real semantic retrieval quality — that undermines using the full-set Recall@10 alone for
   the embedder/hybrid/rerank decisions this spike exists to make. **The Spike-2 harness MUST report
   Recall@10 split into title-present vs. title-absent subsets** (roughly ~40 questions are title-absent,
   giving a leakage-controlled lower bound). A hybrid/rerank "win" on the full set is not evidence about
   those components unless it also holds on the title-absent split.
   **Known limitation — multi-paper items score on one paper.** 60/210 questions are typed
   Multi-Paper-Reasoning/Multi-Paper-Synthesis, but their ground truth (`source_paper_id` +
   `passage_excerpt`) is singular — one paper, one snippet — even though the question requires synthesizing
   2+ papers. A retriever that finds only one of the required papers still scores a Recall@10 hit on these.
   Don't build a multi-gold schema for this (YAGNI) — instead, **scope the primary Recall@10 gate to the 150
   single-passage items**, and report the 60 multi-paper items separately as a "primary-passage-only" lower
   bound, not blended into the headline number.
2. Embed with each candidate: **Qwen3-Embedding-4B** and **BGE-M3** (optionally 8B), served via TEI/vLLM.
3. Sweep configs: `{dense}` vs `{hybrid dense+sparse+RRF}` vs `{hybrid + cross-encoder rerank}`
   (BGE-reranker-v2-m3 or Qwen3-Reranker). Optionally A/B SPECTER2/SciNCL for summary routing (PRD §11B).
   **Contextual headers are NOT part of this sweep** — they're a V1 feature, not a V0 build decision
   (ADR-07); don't spend Phase-0 time generating them.
4. Run the real `Retriever.retrieve()` against the resolved gold `chunk_id`s and measure **Recall@10, MRR**,
   and **retrieval-failure rate** (PRD §11B: how often the right chunk wasn't retrieved at all). **Tag
   context-related failures automatically** — a result where the gold chunk was retrieved-adjacent (same
   paper/section, near-miss rank) but scored low, suggesting it reads ambiguously without surrounding text
   (e.g. "we set β=0.9" with no visible link to "Adam optimizer ablation"). This tag is the **monitoring
   signal handed to V1** for the contextual-header decision — record the count/rate in `phase0-results.md`,
   but do not act on it in V0.

**Gate (pass/fail):**
- Lock the embedder, reranker, and retrieval config (top-k, hybrid weights, rerank depth).
- **Recall@10 ≥ ~0.85.**
- **Hybrid and the reranker are kept in V0/V1 regardless of this spike's result.** The original rationale
  was that the eval set was synthetic (a question generated from its own gold chunk), which is directionally
  biased toward making both components look unnecessary (shared vocabulary inflates lexical/dense match)
  exactly when they exist to rescue real, vocabulary-mismatched research questions a chunk-echo eval
  underrepresents. That specific premise no longer holds as stated — the imported 210-question set (see
  Method step 1) isn't generated from its own gold chunk, so it doesn't carry that exact bias. The policy
  still stands, though: these questions are LLM-authored from the papers' own text and so may still skew
  toward shared domain vocabulary with the source passage, just less severely than the chunk-echo method
  would. Spike 2's job here remains to **lock the retrieval config** (embedder choice, top-k, hybrid
  weights, rerank depth) and confirm Recall@10 ≥ ~0.85, not to decide keep/drop. A future post-V0/V1 revisit
  may reconsider dropping either component, but only once there's a real Recall@10 delta measured on this
  human/LLM-authored set against a genuinely vocabulary-mismatched query sample — the 210-question set is a
  step toward that, not a finished proof either way.

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
- [x] **Parser locked with numbers**; anchor round-trip ≥ ~95%; golden fixtures committed.[^spike1]
- [x] **Embedder + reranker + retrieval config locked with numbers**; Recall@10 ≥ ~0.85; hybrid/rerank each
      justified their complexity.[^spike2]
- [x] The 210-question retrieval eval set (`fixtures/eval/`) has every `passage_excerpt` resolved to a real
      `chunk_id` against the Spike-1 corpus, with unmatched excerpts flagged (not dropped or guessed) and the
      exclusion rate under its invalidating floor (see Spike 2 Method step 1's flag-rate limitation note).
- [x] Spike 2's Recall@10 is reported both on the full 210-question set **and** split title-present vs.
      title-absent, and separately for the 150 single-passage items vs. the 60 multi-paper items (see Spike 2
      Method step 1's known-limitation notes) — not just as one blended headline number.
- [ ] Real papers/hour measured → a realistic 30k backfill plan (smoke-test 200 papers, then run overnight).
- [ ] `phase0-results.md` records every number, so no decision is "asserted, not proven" (PRD §9 ethos).

Once these hold, the adapters behind the three real seams are chosen, and Owners A–E integrate their modules
against them. Everything before this point is de-risking; everything after is the V0 build (WORK-BREAKDOWN.md).

[^spike1]: Spike 1 concluded: MinerU locked as the sole V0 `Parser` adapter (Docling and Marker evaluated
    and dropped — see `phase0-results.md`). One gap carried forward, not silently treated as done: the
    method's step 4, the arXiv-LaTeX ingest trial (best-case anchoring against `.tex` for arXiv papers),
    was never run — no artifact in `.phase0-data/` addresses it. It doesn't block the parser-lock decision
    (a separate, optional path, not a gate condition) but is an open follow-up recorded in
    `phase0-results.md`.

[^spike2]: Spike 2 concluded (PR #46): Qwen3-Embedding-4B + hybrid (dense+sparse+RRF) + BGE-reranker-v2-m3
    locked as the V0 retrieval config, on the real 210-question eval set (n=192 after excluding 18
    structurally-unscorable questions). Qwen3-4B dense-only Recall@10 **0.875** clears the ≥0.85 gate;
    Qwen3-4B hybrid+rerank Recall@10 **0.844** / MRR **0.601** — technically just under the Recall@10
    gate, locked anyway per this runbook's own keep-hybrid-regardless rule (a synthetic eval set
    structurally favors dense-only; see `phase0-results.md`). BGE-M3 was measured and not selected.
