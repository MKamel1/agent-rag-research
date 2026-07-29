# Established methods for book-scale RAG — external research

*2026-07-28. Written to pressure-test `DESIGN-book-chapters-and-hierarchy.md` with outside
evidence, per the brief in that effort. Companion to `docs/PLAN-book-rag-experiments.md` (the
resulting experiment plan) and `docs/METHODS-books-and-chunk-quality.md` (the internal methods
log this supplements — see its new "External research" section).*

**Scope discipline (CONVENTIONS.md §14):** every citation below was fetched (arXiv abs page,
official blog, docs page) during this research pass, not recalled from training data. Where a
claim could not be verified against fetched content, it is marked `UNVERIFIED` or dropped
entirely — one candidate reranker-benchmark citation was dropped for exactly this reason (see
"What I could not verify" at the end). Every "measured" claim states dataset, authors, and
whether that dataset resembles ours (5 technical books, 150–670 chunks each, agent consumer,
15-question hand-written eval, k=10).

---

## Two findings before the ranked table, because they change how to read it

**1. Two of the "established methods" a naive literature scan would recommend are already
shipped here.** `rag/retriever.py` runs hybrid dense+sparse search fused by RRF *and* a
cross-encoder reranker (BGE-reranker-v2-m3, ADR-10) on **both** `retrieve()` (passage) and
`retrieve_papers()` (chapter routing) — confirmed by reading the module directly, not inferred.
The 2026-07-28 baseline (chapter routing recall@10 = 0.467) is a baseline **with** hybrid search
and reranking already active. This matters because §5 below (reranking, hybrid search) is
standard advice in almost every RAG methods survey — and it is not available headroom here. The
bottleneck the baseline exposes is downstream of retrieval mechanics: which unit
(`ChapterSummary`) exists to be found, not how well it's found once it exists.

**2. Contextual Retrieval (Anthropic's method, §2 below) already has a real spike in this exact
codebase, on paper data, with a documented HOLD.** `WORK-BREAKDOWN.md` T-DOC41 (2026-07-17): the
header generator (`rag/contextual_header.py`) and A/B tooling (`app/reembed_experiment.py`) are
built and merged; measured on 809 papers; headroom-corrected re-test showed a small positive
signal (Recall@10 +0.025, MRR +0.047) **inside the noise band at n=40 questions**; cost measured
at ~11.7 GPU-hours for 809 papers, extrapolated to ~18.1 GPU-days at the 30k-paper target. Status:
HOLD, not rejected — the blocker was an under-powered eval, not a bad result. This is the single
most important piece of "what we already tried" context an external literature scan would
otherwise miss, because it isn't in `METHODS-books-and-chunk-quality.md` (that log is book-scoped;
T-DOC41 predates the book work and ran against papers). At the 5-book scale (~1,939 chunks total
across all five books, ARCHITECTURE-verified below) the same technique is two to three orders of
magnitude cheaper to test than at 30k-paper scale — cheap enough that the GPU-cost objection to
T-DOC41 mostly disappears for books specifically.

---

## Search coverage

Queries run (WebSearch + WebFetch, this session): RAPTOR and successors/critiques; GraphRAG;
late chunking; Anthropic Contextual Retrieval; Dense X Retrieval (propositions); Chroma's chunking
evaluation report; LlamaIndex parent-document/auto-merging/index-type docs; Lost in the Middle;
Agentic RAG survey; Self-RAG; Docling technical report; GROBID docs; reranker cost/latency;
QuALITY/NarrativeQA/QASPER/SCROLLS long-doc benchmarks; "Long Context vs RAG" (summarization- vs
chunk-based retrieval); statistical power for IR evaluation (Sakai, SIGIR); synthetic vs
hand-written question generation bias; PDF bookmark/outline page-offset reconciliation practice;
hybrid dense+sparse RRF; multi-view content-aware long-document indexing; Self-Route (RAG vs
long-context routing, Google/EMNLP 2024); BGE-reranker-v2-m3 model card (to check against what
this codebase already runs).

**What I could not find or verify:**
- No paper measuring chapter-summary-routing specifically against agent-issued multi-step
  retrieval calls (area 7) on a benchmark resembling ours — the closest is Self-Route (§7), which
  is single-shot-vs-long-context routing, not summary-vs-passage routing for an agent.
- No published benchmark uses "chapter routing recall" as a named metric; every long-doc
  benchmark found (QuALITY, NarrativeQA, QASPER, SCROLLS) scores final-answer QA, not intermediate
  routing accuracy — so no external number exists to compare our 0.467 against directly.
- A Springer Discover Computing article ("Evaluating retriever reranker pairings...") surfaced in
  search with specific MRR numbers; the DOI redirected to an authentication wall I could not pass,
  so those numbers are **dropped**, not cited — see "What I could not verify" below.
- RAPTOR's own successor/critique papers (`arXiv:2410.01736`, a Stanford CS224N *class project*
  writeup) were only read at abstract/summary depth, not the full method — flagged where used.
- The Agentic RAG survey (`arXiv:2501.09136`) abstract was fetched but its body (where any
  index-design guidance would live) was not — flagged where used, contributes taxonomy only.

---

## Ranked summary

| # | Method | Addresses | Evidence strength (this shape) | Cost here | Verdict |
|---|---|---|---|---|---|
| 1 | **PDF outline as chapter boundary/hierarchy (= Q1)** | P1, P2, P3 | Indirect — no retrieval-quality paper found; strong *practitioner* evidence the page-offset join is a known hazard | Cheap: read-only against `blocks`, no re-embed to prototype | **Recommend for testing** (already planned; research below sharpens the risk) |
| 2 | **Contextual Retrieval, book-scoped re-test (T-DOC41 revival)** | P1 (indirectly, chunk quality) | Anthropic: −49%/−67% failure rate, general RAG KBs, not book-shaped; **this repo's own T-DOC41**: inconclusive at n=40, paper-scale | Cheap at 5-book scale (~1,939 chunks vs 809 papers) — order 1-3 GPU-hours | **Worth testing if cheap** — but scope to chunk-level passage recall, not chapter routing, since it doesn't touch chapter boundaries |
| 3 | **Section-aware boost/filter by `section_path` type (= Q4)** | P2/ranking | No external measured citation found for this specific technique | Cheap — existing field, filter/boost logic only | **Worth testing if cheap** (as already planned; ride along with Q1/Q2 harness) |
| 4 | **Multi-view (raw + summary) segment representation** | P2 | Dong et al. 2024: 16–43% recall gain over flat chunking, structure-segmented long docs, 8 retrievers — **domain not confirmed to resemble ours** | Already architecturally present (two-surface `search_papers`/`semantic_search`) | **Worth testing if cheap** — not a new build, a validation that the existing two-surface shape is directionally right; only the *unit* (chapter split) needs fixing |
| 5 | **Self-Route-style agent escalation (retrieved-context-sufficiency check)** | P2, agentic (area 7) | Li et al., EMNLP 2024 (Google): Self-Route matches long-context QA at much lower cost by letting the model decide if retrieved context suffices | Very cheap — prompting/agent-orchestration only, no index change | **Worth testing if cheap** — cheapest agentic-design experiment on this list |
| 6 | **Statistical rigor for the eval set (Sakai 2016; general two-proportion power math)** | P0 | SIGIR/TOIS systematic review: many published IR significance claims are underpowered | Zero — it's a planning constraint, not a build | **Recommend for testing** (i.e., adopt in the eval plan — see `PLAN-book-rag-experiments.md`) |
| 7 | **Hand-written, pre-retrieval question discipline (current practice) vs. synthetic generation** | P0 | Synthetic-data-for-RAG-eval paper: synthetic Qs reliably rank retriever configs but show task-mismatch/stylistic bias for generator comparisons | N/A (methodology, not code) | **Recommend for testing** — i.e., keep current discipline; the literature doesn't contradict it |
| 8 | **RAPTOR (recursive clustering + tree summarization)** | P1, P2, P3 | Sarthi et al., ICLR 2024: QuALITY +20% absolute accuracy w/ GPT-4 — fiction QA, not technical-book chapter routing; documented failure mode (cluster confusion at higher layers) resembles M1/M2's mis-split failures | Expensive: LLM call per cluster per tree level, re-clustering logic, new index shape | **Not worth it here** — solves "no ground-truth structure exists"; we have exact structure (outline) for 4/5 books already |
| 9 | **GraphRAG (entity graph + community summaries)** | P2 (global sensemaking only) | Edge et al. 2024 (Microsoft): built for "what are the themes in this 1M-token corpus" queries, not targeted fact lookup | Expensive: LLM entity/relation extraction per document, community detection, community summarization | **Not worth it here** — wrong query shape (our eval questions are targeted-fact lookups, not corpus-wide sensemaking) and LLM-heavy at index time |
| 10 | **Late chunking (embed-then-pool)** | P1 (chunk quality) | Günther et al. 2024 (Jina): claims contextual coherence gain; no benchmark numbers were surfaced in the fetched content | Unknown/plumbing-heavy — needs the embedder to expose pre-pool token embeddings, which TEI's standard `/embed` endpoint may not | **Not worth it here** — vendor-adapter-level uncertainty, and duplicates the "context-poor chunk" problem contextual retrieval (#2) already addresses more cheaply |
| 11 | **Propositional/atomic chunking (Dense X Retrieval)** | P1 (chunk granularity) | Chen et al. 2023: outperforms passage-level on 5 open-domain QA datasets, 6 retrievers — Wikipedia factoid retrieval, not book-chapter routing | Expensive: LLM extraction per proposition at book scale | **Not worth it here** — targets passage recall, which is already our *better*-performing surface (0.600); the bottleneck is chapter routing (0.467), and finer granularity does nothing for that |
| 12 | **Docling / layout-model PDF parsing** | P3 (structure extraction, general) | IBM technical report (arXiv:2408.09869): DocLayNet + TableFormer, production-grade | High — would mean replacing the ADR/Spike-1-locked MinerU parser | **Not worth it here** — out of scope; parser is locked by ADR, not up for revisit on this ticket |
| 13 | **GROBID** | P3 (structure extraction, general) | Long-standing production tool (Semantic Scholar, CORE) for scholarly-article structure | Same as above | **Not worth it here** — same reason; noted for completeness only |

Verdicts read against **this system specifically** — a single-GPU local deployment, 5 books,
101 existing chapter units, an agent consumer, and a documented HOLD on the closest prior
experiment. A method ranked "not worth it here" may be the right call in a different corpus or
deployment; that's stated per-method below, not implied by the ranking order.

---

## Detailed records

### Area 1 — Long-document / book-scale structuring and indexing

#### RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)

- **Addresses:** P1, P2, P3 — this is the most direct competitor to the whole book_summarizer
  approach: recursively cluster chunks by embedding similarity, summarize each cluster, repeat,
  building a multi-level tree; retrieve by either layer-by-layer traversal or a "collapsed tree"
  that considers all layers at once.
- **Mechanism:** No heading text or publisher structure is used at all — the tree is built purely
  from embedding-space clustering (typically Gaussian Mixture Models) plus LLM summarization at
  each level. This is a genuinely different strategy from every internal M1–M8/Q1 approach: those
  all try to recover the book's *actual* structure (headings, markers, outline); RAPTOR invents a
  structure from semantic similarity instead.
- **Evidence:** Sarthi, Abdullah, Tuli, Khanna, Goldie, Manning, ICLR 2024
  (`arxiv.org/abs/2401.18059`). Headline number: coupling RAPTOR with GPT-4 improves QuALITY
  (long-document multiple-choice QA over short stories/articles, ≤8K tokens, 1,065 items) by 20%
  absolute accuracy over the paper's baselines. QuALITY is fiction/narrative, single-shot QA, and
  does not resemble our corpus (technical books, agent doing multi-step lookup, no multiple-choice
  structure) — the gain is real but on a different task shape.
- **Critique found:** A Stanford CS224N course-project report (not peer-reviewed — flagged as
  lower rigor, `web.stanford.edu/class/cs224n/final-reports/256925521.pdf`) and a follow-up paper
  (`arXiv:2410.01736`, abstract-level only) both describe the same failure mode: RAPTOR's
  clustering can produce higher-layer nodes that mix unrelated content, "confusing" the retriever.
  This is structurally the same failure M1 and M2 hit here (arbitrary/mis-scoped units producing
  unusable labels) — evidence that clustering-without-ground-truth has the same fragility our own
  heuristics did, not a reason to prefer it over them.
- **Fit to this system:** Expensive relative to what's already built. Needs: embedding every
  chunk (already have), a clustering step (new dependency or hand-rolled GMM), an LLM summarize
  call per cluster per tree level (multiplies book_summarizer's existing map-step cost by tree
  depth), and a new multi-level index shape in `summaries` beyond the flat `parent_id`/`level`
  Q3 already proposes. Deterministic? No — clustering + LLM summarization at each level, same
  nondeterminism profile as the existing map-reduce summarizer, but repeated more times.
- **Relation to internal work:** Directly competes with Q1/Q3. The whole reason Q1 is attractive
  (per `DESIGN-book-chapters-and-hierarchy.md`) is that 4 of 5 books ship *exact, deterministic*
  ground-truth structure via `pdf.get_toc()` — RAPTOR exists to solve the case where no such
  ground truth exists, which is not our situation for 4/5 books. For the fifth (Trustworthy OCE,
  no outline), M3+M4 already produces the best-reviewed result in the corpus (`"excellent — every
  title a real section"`) — RAPTOR would have to beat that specific heuristic on the one book it
  could even apply to.
- **Verdict: not worth it here.** The problem RAPTOR solves (no structure to exploit) doesn't
  match 4/5 of our books, and the one book where it might apply already has the best-reviewed
  chapter split in the corpus from a much cheaper heuristic.

#### GraphRAG (Microsoft)

- **Addresses:** P2, but for a different query class than ours — "global sensemaking" questions
  over an entire corpus ("what are the main themes"), not targeted fact lookup.
- **Mechanism:** LLM-driven two-stage index: extract an entity/relationship knowledge graph from
  source documents, then pre-generate hierarchical community summaries (via community detection)
  over that graph. At query time, "global search" map-reduces over community summaries; "local
  search" walks the graph from query-relevant entities.
- **Evidence:** Edge, Trinh, Cheng, Bradley, Chao, Mody, Truitt, Metropolitansky, Ness, Larson,
  Microsoft Research (`arxiv.org/abs/2404.16130`). Reported: "substantial improvements... in both
  comprehensiveness and diversity" over conventional RAG, for a corpus in the **1-million-token**
  range and query class described as query-focused summarization, not fact retrieval. The
  webpage/abstract fetched did not surface a specific numeric win — flagged, not fabricated.
- **Fit to this system:** High cost — LLM entity/relation extraction per document at index time,
  community detection, community-level summarization; multiplies the summarization cost problem
  P1 already describes (a book too large for one summarize() call) rather than solving it. Needs
  an LLM at index time (heavily) and a new graph-store dependency, not just a schema migration.
- **Relation to internal work:** Doesn't compete with Q1–Q4 directly — it's aimed at a query type
  ("what are this book's major themes across all five books") the current eval set doesn't test
  and the MCP consumer (an agent doing targeted lookups) doesn't obviously need. If a genuinely
  "sensemaking" query type is ever added to the eval set, this would be worth revisiting.
- **Verdict: not worth it here.** Wrong query shape for the documented consumer and eval
  questions (all "Book-Chapter-Recall"-style targeted fact lookups, per
  `eval_book_questions.json`), and the most LLM-expensive method surveyed.

### Area 2 — Chunking strategy evidence

#### Anthropic Contextual Retrieval

- **Addresses:** P1 (chunk quality, one level below the chapter-boundary problem) — mostly
  orthogonal to P2/P3, since it doesn't touch chapter units at all, only what text gets embedded
  per chunk.
- **Mechanism:** Before embedding (and before BM25-indexing) a chunk, prepend a short
  (50–100-token) LLM-generated blurb situating the chunk within its source document — "This
  section discusses X in the context of document Y about Z." Both the embedding index and the
  sparse/BM25 index get the prepended context ("Contextual Embeddings" + "Contextual BM25").
- **Evidence:** Anthropic engineering blog, published 2024-09-19
  (`anthropic.com/engineering/contextual-retrieval`). Measured on knowledge bases across "codebases,
  fiction, ArXiv papers, science papers," using 1 − recall@20 as the failure metric, Gemini
  Text 004 embeddings, retrieving top-20: contextual embeddings alone cut failures 35%
  (5.7%→3.7%), + contextual BM25 → 49% (5.7%→2.9%), + reranking → 67% (5.7%→1.9%). Anthropic's own
  stated caveat: benefit is largest for **larger** knowledge bases (under ~200K tokens, just put
  the whole KB in the prompt instead) — our per-book chunk counts (160–671) sit well inside "large
  enough to need retrieval," but each book individually is far smaller than the corpora in
  Anthropic's own test set. The "ArXiv papers" domain in their test set is the closest analogue to
  our corpus, not a book domain specifically.
- **Fit to this system:** **This repo already spiked exactly this method** (T-DOC41,
  `rag/contextual_header.py`, `app/reembed_experiment.py`) against 809 papers, and the result was
  HOLD, not a clean win, at n=40 questions — inside the noise band. The blocker was an
  under-powered eval, not the technique itself; headers were independently judged high quality.
  Cost for a 5-book-only re-run: ~1,939 chunks total (216+357+160+535+671) vs. 809 papers in the
  original spike — roughly 2-3x the chunk count but each summarize call is against a much smaller,
  already-summarized-per-chapter source, so the GPU-hour estimate scales sub-linearly; order
  1-3 GPU-hours, not the ~18 GPU-days quoted for the 30k-paper full-corpus case. Needs an LLM at
  index time (one call per chunk), no schema migration (the `contextual_header` column already
  exists on `chunks`, per DATA-CONTRACTS — currently always `NULL`, V1-reserved per PRD ADR-07).
  Deterministic? No (LLM-generated text).
- **Relation to internal work:** Directly reuses T-DOC41's built tooling. Does **not** touch
  chapter boundaries (P2/P3) — it's a pure passage-recall lever, and passage recall (0.600) is
  already our *better*-performing metric, so this competes for priority with, rather than
  substitutes for, Q1/Q2's chapter-routing work.
- **Verdict: worth testing if cheap.** The tooling exists, the book-scale cost is genuinely
  cheap, and re-running it here would be the first properly-powered test of a method this repo
  already spent real GPU-hours on inconclusively — but it should be sequenced *after* Q1/Q2, since
  it doesn't move the metric (chapter routing) currently identified as the actual bottleneck.

#### Chroma "Evaluating Chunking Strategies for Retrieval"

- **Addresses:** P1 (chunk boundary choice generally).
- **Mechanism:** A token-level evaluation harness (recall/precision/IoU against a
  human-annotated "which tokens are relevant" ground truth, not just chunk-ID hit/miss) comparing
  fixed-size (recursive character, token) splitters against embedding-aware semantic splitters,
  introducing two new strategies: `ClusterSemanticChunker` (embedding-aware, globally optimized
  cluster assignment) and `LLMSemanticChunker` (LLM-prompted boundaries).
- **Evidence:** Smith & Troynikov, Chroma Technical Report, July 2024
  (`research.trychroma.com/evaluating-chunking`). With `text-embedding-3-large`, top-5 retrieval:
  `LLMSemanticChunker` 91.9% recall / 3.9% precision; `ClusterSemanticChunker` (200-token target)
  87.3% recall / 8.0% precision; plain `RecursiveCharacterTextSplitter` (200-token) 88.1% recall /
  7.0% precision — up to a 9-point recall spread across strategies. Domain: general text corpora,
  not specifically technical books; no chapter-routing-equivalent metric measured.
- **Fit to this system:** This measures *chunk*-level splitting (what feeds `chunks`/embeddings),
  not chapter-level splitting (what feeds `summaries`/`ChapterSummary`) — a different unit than the
  one P1–P3 are actually about. M3/M4 (size-merge + structural title scoring) already occupies
  roughly the same design space as `ClusterSemanticChunker`/heading-aware chunking for the
  *chapter* unit; this report is closer evidence for whether `rag/chunker.py`'s own chunk-splitting
  (independent of book work) is well-chosen, which is out of this ticket's scope.
- **Relation to internal work:** Doesn't compete with M1–M8/Q1–Q4 directly (different unit level)
  but is useful negative evidence against one temptation: don't assume a fancier
  embedding-aware/LLM chunker will fix chapter routing — the report's own strategies operate one
  level below the unit our baseline shows is actually broken.
- **Verdict: not worth it here** for the *chapter*-unit problem this research is about (wrong
  granularity); flagged as relevant if `rag/chunker.py`'s own chunk splitting is ever separately
  revisited.

#### Late Chunking (Jina AI)

- **Addresses:** P1 (chunk quality) via a different mechanism than contextual retrieval — no LLM
  call, instead re-ordering the embed/chunk pipeline: embed the *whole* document with a
  long-context model first, chunk the resulting *token-level* embeddings, then mean-pool per
  chunk — so each chunk embedding is computed with full-document context already baked in via
  attention.
- **Evidence:** Günther, Mohr, Williams, Wang, Xiao, Jina AI (`arxiv.org/abs/2409.04701`,
  Sept 2024, updated Jul 2025). The fetched abstract/summary claims "superior results across
  various retrieval tasks" but no comparative numbers were surfaced in what I could fetch —
  **UNVERIFIED at the numeric level**, cited here for mechanism only, not for a specific
  performance claim.
- **Fit to this system:** Uncertain and potentially high-cost. Requires the embedder to expose
  pre-pooling token embeddings rather than a single vector per input — this is an embedder-adapter
  (`rag/embedder.py`, the one module allowed to import the TEI client) capability question, not
  something that can be bolted on above the interface. Whether the deployed TEI server + Qwen3
  Embedding model configuration supports returning token-level output instead of the pooled
  output was not checked (out of scope for a docs-only research task — flagged as an open question
  for whoever picks this up, not answered here). Even if supported, it changes the `Embedder`
  contract's output shape, which is foundation-protected (`contracts/`).
  Deterministic? Yes (no LLM), a genuine advantage over contextual retrieval — but the plumbing
  risk is real and unquantified.
- **Relation to internal work:** Solves roughly the same problem contextual retrieval (already
  spiked, HOLD) solves — context-poor chunks — via a different, deterministic mechanism.
- **Verdict: not worth it here.** Not because the technique is bad, but because contextual
  retrieval already has a working, cheap-at-book-scale implementation in this codebase and late
  chunking would require unverified embedder-adapter and foundation-contract changes to even
  prototype.

#### Dense X Retrieval (propositional/atomic chunking)

- **Addresses:** P1, but at a granularity *finer* than current chunks, not the chapter-unit
  problem.
- **Mechanism:** Break text into "propositions" — atomic, self-contained factual statements —
  via LLM extraction, and index at proposition granularity instead of passage/chunk granularity.
- **Evidence:** Chen, Wang, Chen, Yu, Ma, Zhao, Zhang, Yu (`arxiv.org/abs/2312.06648`, Dec 2023).
  Outperforms passage- and sentence-level retrieval on 5 open-domain QA datasets with 6 dense
  retrievers; built `FACTOIDWIKI` (6M Wikipedia pages → 250M propositions) as the demonstration
  corpus. Wikipedia factoid QA, not book-chapter routing.
- **Fit to this system:** Expensive (LLM call per proposition, at book scale that's plausibly
  thousands of calls per book) and targets the wrong metric for our bottleneck: propositions would
  sharpen `semantic_search`/passage recall, which is already the *better*-performing surface
  (0.600 vs. chapter routing's 0.467) in the baseline. Finer granularity does nothing for chapter
  routing, since `search_papers` returns chapter summaries, not propositions.
- **Relation to internal work:** Unrelated to Q1–Q4; would be a chunk-level change, same
  granularity mismatch as the Chroma report above.
- **Verdict: not worth it here** — solves a problem (passage recall) this system doesn't
  currently have, at real LLM cost.

### Area 3 — Structure extraction from PDFs at scale

- **Addresses:** P3, directly, and specifically the exact "unproven join" risk Q1 already flags:
  "outline entries carry page indices; our blocks carry page anchors... prove it on one book before
  committing."
- **What I found:** No academic paper on the specific outline-page-to-block-page join problem —
  this turns out to be a well-known *practical* PDF-tooling problem, not a research topic. Evidence
  from the PDF-tooling ecosystem (not RAG-specific): PDF viewer/bookmark page numbers commonly
  diverge from a document's own printed/logical page numbers (front matter in roman numerals, a
  preface that isn't numbered, scanned inserts) — common enough that dedicated tools exist purely
  to detect and correct the offset (`tocPDF`, `github.com/aminya/tocPDF` — a small utility built
  around exactly this reconciliation, with a `--missing_pages` flag to auto-recompute offsets when
  outline destination pages don't match expected content). Commercial PDF tools (e.g. PDF-XChange,
  per its own forum documentation) expose an explicit manual "page offset" setting in their
  bookmark-editing UI for the same reason. This is UNVERIFIED as an academic claim — it's
  practitioner/tooling evidence, cited as such, not as a peer-reviewed result.
- **What breaks in practice, per this evidence:** front matter (roman-numeral or unnumbered pages
  before the body starts) is the single most common cause of an outline-to-content page offset —
  which lines up exactly with `DESIGN-book-chapters-and-hierarchy.md`'s own flagged risk ("Cover,
  Copyright, Dedication all appear at level 0" needing deliberate handling).
- **Fit to this system:** `pypdfium2.get_toc()` returns each entry's destination page index; our
  `blocks.page` is a page anchor from the parser (MinerU). The join risk is exactly what the
  outside evidence predicts: **test the join on the front matter of at least one book first**, not
  just a mid-book chapter, since front matter is where offset drift concentrates per the tooling
  evidence above.
- **Also surveyed for completeness, not recommended for adoption here:** Docling (IBM technical
  report, `arxiv.org/abs/2408.09869`, DocLayNet layout model + TableFormer table structure,
  production-grade, MIT-licensed) and GROBID (long-standing TEI-XML scholarly-document structure
  extractor, used by Semantic Scholar/CORE). Both are established production alternatives to
  MinerU for structure extraction generally. **Out of scope here**: MinerU is locked by
  ADR/Spike 1 (per `AGENTS.md`), and switching parsers is not what this ticket is about — mentioned
  only because area 3 explicitly asked how production pipelines solve structure extraction "at
  scale," and both are real, verifiable answers to that question.
- **Verdict on the outline-join risk itself: recommend for testing** — this is Q1's own
  prerequisite step, already correctly sequenced first in the existing plan; the external evidence
  sharpens *what* to test first (front matter/preface pagination specifically) rather than
  changing the plan's structure.

### Area 4 — Multi-granularity / two-stage retrieval

This is the area most directly relevant to the baseline's headline finding (passage recall 0.600
> chapter routing 0.467) and the area with the most disagreement in what I found.

#### Multi-view content-aware indexing (structure-segmented + raw/keyword/summary views)

- **Addresses:** P1, P2 — segments a document by structural boundaries (not fixed length) and
  represents each segment with multiple views (raw text, keywords, summary) rather than one.
- **Mechanism:** Training-free; segment by section/paragraph structure, then build parallel
  raw-text, keyword, and summary representations per segment for retrieval.
- **Evidence:** Dong, Deik, Lee, Zhang, Li, Zhang, Liu (`arxiv.org/abs/2404.15103`, Apr 2024).
  Reported recall gains of 16.3%–42.8% (varying by top-k, k=10→k=1.5) over "state-of-art chunking
  schemes" across 8 retrievers (2 sparse, 6 dense). **Domain not confirmed** — the fetched summary
  did not specify the source corpus, and I could not verify whether it resembles technical books;
  flagged as a real but domain-unconfirmed number.
- **Fit to this system:** Architecturally, this system **already has** the "multiple views per
  unit" shape: `search_papers` returns the summary view, `semantic_search` returns the raw-chunk
  view, over the same underlying content. What's unvalidated isn't the two-view *pattern* — it's
  whether the current chapter unit (the summary view's boundary) is well-chosen, which is exactly
  what Q1/Q2 test.
- **Relation to internal work:** External support for the two-surface architecture's general
  shape, not a new build. Doesn't resolve the open question in `METHODS-books-and-chunk-quality.md`
  ("does chapter-level routing earn its cost at all?") — that paper's own gains are against "flat
  chunking," not against a comparison of *which* structural boundary produces the summary view, so
  it doesn't bear on Q2's specific A1-vs-A2 question.
- **Verdict: worth testing if cheap** — as validation, not new engineering: it's evidence the
  two-surface architecture is a reasonable shape to keep investing in via Q1/Q2, rather than
  evidence for a specific new build.

#### "Long Context vs. RAG for LLMs" (Li, Cao, Ma, Sun, 2024) — the disagreement

- **Addresses:** P2 directly — this paper's own framing is "summarization-based retrieval vs.
  chunk-based retrieval vs. long-context," which sounds like exactly our chapter-vs-passage
  question.
- **Evidence:** `arxiv.org/abs/2501.01880`, Dec 2024. Reported finding, from the fetched
  abstract/summary: "summarization-based retrieval performs comparably to [long context], while
  chunk-based retrieval lags behind." Taken at face value, **this appears to contradict our
  baseline** (chapter/summary routing 0.467 underperforms passage/chunk retrieval 0.600).
- **Where I have to hedge, per the rigor requirement to separate measured from claimed:** I only
  fetched this paper's abstract/summary, not its method section, and could not confirm what
  "summarization-based retrieval" means mechanically in their setup — it may mean summarizing
  *retrieved* chunks post-hoc for the generator's context window (a generation-time compression
  step), not pre-built, embedded chapter/document summaries used as a *routing index* the way
  `ChapterSummary` is used here. Those are different mechanisms that could easily produce opposite
  results without actually disagreeing about anything. Their evaluation domain (the abstract
  mentions "Wikipedia-based questions") also doesn't resemble ours. **I am flagging this as an
  unresolved disagreement, not resolving it by fiat, per the brief's explicit instruction** — if
  this paper's "summarization-based retrieval" does turn out to mean the same thing as our
  chapter-routing surface, it would be real outside evidence against the current chapter-summary
  design; if it means post-hoc compression of retrieved passages, it's unrelated. Whoever
  implements the experiment plan should re-check this paper's method section before treating it as
  either support or contradiction.
- **Verdict: cite as an open disagreement**, not a recommendation either way — the honest
  position given what I could verify.

#### Self-Route (RAG-vs-long-context query routing)

- **Addresses:** area 7 primarily (agentic retrieval design), touches P2.
- **Mechanism:** Give the LLM the query plus top-k retrieved passages; let the model
  self-reflect on whether that's sufficient to answer; if not, escalate to reading the full
  document via long context instead of trusting the retrieval result.
- **Evidence:** Li, Li, Zhang, Mei, Bendersky, EMNLP 2024 industry track
  (`arxiv.org/abs/2407.16833`, Google). Finding: long-context LLMs (Gemini-1.5, GPT-4) outperform
  RAG on average when resourced sufficiently, but Self-Route recovers comparable performance to
  pure long-context at much lower cost by only escalating when needed. Domain: general QA
  benchmarks, not book-chapter routing specifically.
- **Fit to this system:** The mechanism translates cleanly to an agent MCP consumer that already
  has `get_span` as an escalation primitive: after a `search_papers`/`semantic_search` call, the
  agent (not the index) could decide whether to trust the routing or pull broader context. This is
  a **consumer-side behavior change, not an index change** — no re-embedding, no schema migration,
  no LLM call at index time; it's a prompting/orchestration experiment that can be tried against
  the existing MCP surface as-is.
- **Relation to internal work:** New — not covered by M1–M8/Q1–Q4, all of which are index-side.
  Complements Q1/Q2 rather than competing: even a perfectly-boundaried chapter split will
  sometimes route wrong, and a self-assessing agent is a cheap mitigation for the residual error
  rate regardless of which splitter wins.
- **Verdict: worth testing if cheap** — the cheapest experiment on this whole list (no
  ingestion, no migration, pure agent-side prompting), and it's the one method here that actually
  engages area 7's brief ("how does an agent consumer change optimal index design") rather than
  just being a general RAG technique that happens to apply.

### Area 5 — Metadata/section-aware filtering and reranking

Covered in the "two findings" section above: hybrid dense+sparse (RRF) and cross-encoder
reranking are **already implemented and active** in `rag/retriever.py` for both `retrieve()` and
`retrieve_papers()`. I looked for external evidence specifically on the queued Q4 (boost/filter by
`section_path` type, e.g. favor Method/Results over Introduction) and did not find a measured,
citable external paper for that specific technique — general RRF evidence (Cormack, Clarke,
Buettcher, SIGIR 2009, `dl.acm.org/doi/10.1145/1571941.1572114`, the original RRF paper this
system's own fusion is presumably built on) supports rank-fusion generally, and industry
sources (MongoDB, OpenSearch engineering blogs) report RRF consistently beating single-method
retrieval by double-digit percentage points on IR benchmarks — but none of that is specific to
section-type boosting. Q4 remains supported mainly by domain intuition (T-DOC64), not external
measurement; that's a fair characterization to carry into the plan, not a reason to drop it, since
it's cheap and rides along with the Q1/Q2 harness anyway.

**Verdict: RRF and reranking — already shipped, no action.** **Section-type boosting (Q4) —
worth testing if cheap**, exactly as already planned, with the caveat that no external paper
specifically validates it; the evidence for it is internal (owner's stated use case).

### Area 6 — Evaluation methodology for book/long-document retrieval

- **Benchmarks surveyed:** QuALITY (Pang et al. — cited via SCROLLS; long-form fiction/article
  multiple-choice QA, ≤8K tokens, 1,065 items), NarrativeQA (book/movie-script narrative QA,
  answers require synthesizing across the full text), QASPER (scientific-paper QA, ≤8K tokens, 200
  items), all aggregated into the SCROLLS benchmark suite. **None of these use a routing/chapter
  metric** — every one scores final-answer QA accuracy, so there is no external number our
  0.467/0.600/0.667 baseline can be directly compared against; the closest external analogue
  (NarrativeQA) tests full-book comprehension, not intermediate index-routing accuracy.
- **Statistical power:** Tetsuya Sakai, "Statistical Significance, Power, and Sample Sizes: A
  Systematic Review of SIGIR and TOIS, 2006–2015," SIGIR 2016
  (`dl.acm.org/doi/10.1145/2911451.2911492` — abstract/metadata confirmed via search; full text
  was behind an auth wall I could not pass, so the paper's own specific sample-size
  recommendation is **UNVERIFIED** and not quoted here). What is safe to state, and what the
  companion plan uses instead: a back-of-envelope two-proportion power calculation (shown with its
  formula in `PLAN-book-rag-experiments.md`, not asserted from memory) to size how many questions
  a Q1-vs-M3 A/B would actually need to distinguish a plausible effect size — this is arithmetic
  performed for this task, not a literature citation, and is labeled as such there.
- **Synthetic vs. hand-written questions:** "Can we Evaluate RAGs with Synthetic Data?"
  (`arxiv.org/abs/2508.11758`) — synthetic LLM-generated questions reliably rank *retriever
  configurations* against human-labeled baselines, but introduce task-mismatch and stylistic bias
  when comparing *generator* architectures. Our use case (A/B two retrieval-index configurations,
  Q1 vs. M3) is exactly the retriever-configuration comparison the paper says synthetic data
  handles adequately — which means synthetic question generation is a legitimate way to scale the
  eval set past what's hand-writable, **if** the retriever-comparison-only caveat is respected
  (never use it to judge summarization/generation quality). This is genuinely useful: it means the
  "write 40–60 more questions by hand" constraint in the existing plan may not be the only lever
  available for the N needed — see the companion plan for how this is used without abandoning the
  existing "write before retrieval" discipline for the *hand-written* core set.
- **Verdict on our current practice:** the existing discipline (write from book content, before
  any retrieval call, record provenance block IDs) is **more conservative** than what the
  literature says is required for retriever-comparison use cases, not less — nothing found
  contradicts continuing it for the core set.

### Area 7 — Agentic retrieval specifically

- **Addresses:** the framing question underlying P2 — "does an agent consumer change the optimal
  index design?"
- **What I found:** A dedicated survey exists — "Agentic Retrieval-Augmented Generation: A Survey
  on Agentic RAG," Singh, Ehtesham, Kumar, Khoei, Vasilakos, Jan 2025
  (`arxiv.org/abs/2501.09136`) — proposing a taxonomy (agent cardinality, control structure,
  autonomy, knowledge representation) for agentic RAG systems. I fetched only the abstract, not
  the body; the survey's specific guidance on summary-index-vs-passage-index tradeoffs for an
  agent consumer specifically was **not verified** — flagged, not claimed. Self-RAG (Asai, Wu,
  Wang, Sil, Hajishirzi, `arxiv.org/abs/2310.11511`) trains a model to emit reflection tokens that
  decide *when* to retrieve and *whether* a generation is well-grounded, adaptively retrieving
  multiple times or not at all — the clearest evidence found that a genuinely agentic consumer
  changes retrieval behavior (variable number of calls, self-assessed sufficiency) rather than
  just index shape. Self-Route (area 4 above) is the most directly reusable instance of this
  pattern for our system, since it needs no fine-tuned model — plain prompting over an existing
  capable LLM suffices per that paper.
- **The honest gap:** none of the agentic-RAG literature surveyed measures whether a *multi-level
  summary index specifically helps an agent more than a single-shot consumer* — the survey and
  Self-RAG both address *when to retrieve*, not *what granularity of index to offer an agent*.
  This is a real gap in what's published, not a gap in this research pass — worth stating plainly
  per the brief's instruction to say what couldn't be found.
- **Verdict:** no single method to recommend from this area alone; its main contribution to the
  ranked table is Self-Route (already listed under area 4), and the honest conclusion that the
  brief's own framing question ("does an agent consumer change optimal index design") is not
  answered in the literature I could find — it would have to be answered empirically, by this
  system's own eval harness, which is exactly what the companion experiment plan proposes.

---

## References

All fetched directly during this research pass (arXiv abstract pages, official engineering blogs,
docs sites, or search-result metadata cross-checked against at least one primary source).

1. Sarthi, P., Abdullah, S., Tuli, A., Khanna, S., Goldie, A., Manning, C. D. "RAPTOR: Recursive
   Abstractive Processing for Tree-Organized Retrieval." ICLR 2024.
   https://arxiv.org/abs/2401.18059
2. Anthropic. "Contextual Retrieval." Engineering blog, 2024-09-19.
   https://www.anthropic.com/engineering/contextual-retrieval
3. Edge, D., Trinh, H., Cheng, N., Bradley, J., Chao, A., Mody, A., Truitt, S., Metropolitansky,
   D., Ness, R. O., Larson, J. "From Local to Global: A Graph RAG Approach to Query-Focused
   Summarization." Microsoft Research, 2024. https://arxiv.org/abs/2404.16130
4. Günther, M., Mohr, I., Williams, D. J., Wang, B., Xiao, H. "Late Chunking: Contextual Chunk
   Embeddings Using Long-Context Embedding Models." Jina AI, 2024 (updated 2025).
   https://arxiv.org/abs/2409.04701
5. Chen, T., Wang, H., Chen, S., Yu, W., Ma, K., Zhao, X., Zhang, H., Yu, D. "Dense X Retrieval:
   What Retrieval Granularity Should We Use?" 2023. https://arxiv.org/abs/2312.06648
6. Smith, B., Troynikov, A. "Evaluating Chunking Strategies for Retrieval." Chroma Technical
   Report, July 2024. https://research.trychroma.com/evaluating-chunking
7. LlamaIndex. "Auto Merging Retriever" / "How Each Index Works" documentation (parent-document,
   small-to-big retrieval; summary/vector/tree index guide).
   https://docs.llamaindex.ai/en/latest/examples/retrievers/auto_merging_retriever/ ;
   https://developers.llamaindex.ai/python/framework/module_guides/indexing/index_guide/
8. Liu, N. F., Lin, K., Hewitt, J., Paranjape, A., Bevilacqua, M., Petroni, F., Liang, P. "Lost in
   the Middle: How Language Models Use Long Contexts." TACL 2024 (arXiv 2023).
   https://arxiv.org/abs/2307.03172
9. Singh, A., Ehtesham, A., Kumar, S., Khoei, T. T., Vasilakos, A. V. "Agentic
   Retrieval-Augmented Generation: A Survey on Agentic RAG." Jan 2025.
   https://arxiv.org/abs/2501.09136
10. Asai, A., Wu, Z., Wang, Y., Sil, A., Hajishirzi, H. "Self-RAG: Learning to Retrieve, Generate,
    and Critique through Self-Reflection." ICLR 2024 (arXiv 2023).
    https://arxiv.org/abs/2310.11511
11. Docling contributors. "Docling Technical Report." IBM, 2024. https://arxiv.org/abs/2408.09869
12. GROBID documentation. https://grobid.readthedocs.io/en/latest/Introduction/ ;
    https://grobid.readthedocs.io/en/latest/Principles/
13. Stanford CS224N course project. "Expanding Horizons in RAG: Exploring and Extending the
    Limits of RAPTOR." Unpublished class report, not peer-reviewed — cited for its documented
    RAPTOR failure mode only.
    https://web.stanford.edu/class/cs224n/final-reports/256925521.pdf
14. "Recursive Abstractive Processing for Retrieval in Dynamic Datasets." arXiv, abstract-level
    only. https://arxiv.org/abs/2410.01736
15. Cormack, G. V., Clarke, C. L. A., Buettcher, S. "Reciprocal Rank Fusion Outperforms Condorcet
    and Individual Rank Learning Methods." SIGIR 2009.
    https://dl.acm.org/doi/10.1145/1571941.1572114
16. Dong, K., Deik, D. G. X., Lee, Y. Q., Zhang, H., Li, X., Zhang, C., Liu, Y. "Multi-view
    Content-aware Indexing for Long Document Retrieval." 2024. https://arxiv.org/abs/2404.15103
17. Li, X., Cao, Y., Ma, Y., Sun, A. "Long Context vs. RAG for LLMs: An Evaluation and Revisits."
    Dec 2024. https://arxiv.org/abs/2501.01880
18. Li, Z., Li, C., Zhang, M., Mei, Q., Bendersky, M. "Retrieval Augmented Generation or
    Long-Context LLMs? A Comprehensive Study and Hybrid Approach." EMNLP 2024 (industry track),
    Google. https://arxiv.org/abs/2407.16833
19. Sakai, T. "Statistical Significance, Power, and Sample Sizes: A Systematic Review of SIGIR and
    TOIS, 2006-2015." SIGIR 2016. Metadata confirmed via search; full text not accessible.
    https://dl.acm.org/doi/10.1145/2911451.2911492
20. "Can we Evaluate RAGs with Synthetic Data?" 2025. https://arxiv.org/abs/2508.11758
21. aminya. `tocPDF` — PDF bookmark/outline page-offset reconciliation utility (practitioner
    tooling evidence, not academic). https://github.com/aminya/tocPDF
22. BAAI. `bge-reranker-v2-m3` model card (used to confirm this repo's own reranker choice — ADR-10
    — matches the production model this research describes). https://huggingface.co/BAAI/bge-reranker-v2-m3

**Internal sources** (this repository, read directly, not web-fetched): `rag/retriever.py`,
`rag/book_summarizer.py`, `WORK-BREAKDOWN.md` (T-DOC41 entry), `DATA-CONTRACTS.md`,
`docs/METHODS-books-and-chunk-quality.md`, `docs/DESIGN-book-chapters-and-hierarchy.md`,
`app/retrieval_eval.py` and `fixtures/eval/eval_book_questions.json`
(`origin/feat/book-retrieval-eval`).

### What I could not verify (dropped rather than cited)

- A Springer *Discover Computing* article surfaced by search ("Evaluating retriever reranker
  pairings in RAG based on quality and efficiency trade-offs") with specific MRR@5 numbers
  (0.160 → 0.750). The DOI redirected to an authentication wall (`idp.springer.com`) I could not
  pass. **Dropped entirely** — not cited anywhere above, per the brief's instruction that an
  unverifiable claim must be dropped or explicitly marked, and a specific numeric claim I could
  not confirm is exactly the kind of thing not worth marking UNVERIFIED-and-keeping; better
  dropped.
- Detailed body content of the Agentic RAG survey (#9 above) and Self-Route/GraphRAG papers
  (#18, #3) beyond their abstracts — WebFetch on arXiv abstract pages generally returns the
  abstract/metadata, not the full paper body; where a claim needed body-level detail (e.g. exact
  benchmark tables), it's flagged inline as abstract-level-only rather than presented as fully
  verified.
