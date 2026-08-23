# Rivalling OpenEvidence locally — gap analysis, re-parse decision, and benchmark plan

Written 2026-08-22. Every number here was measured or verified against source, not estimated;
where something is unverified it says so.

---

## 1. What OpenEvidence actually is, and where the gap really lies

**Their moat is the corpus, not the architecture.** OpenEvidence has licensed 300+ peer-reviewed
medical journals — NEJM's full archive since 1990, JAMA's eleven-journal network, Cochrane, NCCN —
and indexes ~35 million papers, generating answers only from that licensed set. No independent
technical audit of their stack has been published; the architecture details that are public are
thin. They describe a graph-based retrieval layer over a medical knowledge graph, traversing
disease/drug/pathway relations to assemble evidence spanning documents.

**This matters for the goal.** "As good as OpenEvidence" splits into two very different questions:

- **Corpus parity: not achievable, and not the right target.** You cannot license NEJM. But you do
  not need to — this system is scoped to causal-methods and AV-safety literature, where the
  authoritative sources are open (arXiv, published PDFs). Within its domain the corpus can be
  *complete* in a way a general medical index cannot.
- **Architecture parity: already close, and closable the rest of the way.**

### Architecture: measured against the 2026 production standard

The current published consensus for production RAG is: metadata filter → parallel hybrid search
(dense ANN + sparse) → RRF fusion → cross-encoder rerank → grounded generation with citations.

This system already implements **all of it**:

| stage | SOTA default | this system |
|---|---|---|
| hybrid dense + sparse | required | yes, with server-side IDF weighting |
| RRF fusion | k = 60 | `RRF_K = 60` (`contracts/fusion.py:18`) |
| cross-encoder rerank | 10-25% precision gain | yes, over a 32-deep pool |
| grounded citations | required | yes, verbatim passages with anchors |
| runs locally at ~0 API cost | — | yes |

So the honest answer to "how far are we": **on retrieval architecture, essentially at parity with
the published state of the art.** The gap to OpenEvidence is corpus scale and licensing, plus three
capabilities below.

### The three real architectural gaps

1. **Late interaction (ColBERT-style) as a third pillar.** Per-token representations give
   fine-grained matching that dense-vector similarity flattens. `PRD.md:657` already anticipates
   this for the V2+/VLM phase (ColPali for figure/equation pages). This is the single highest-value
   retrieval upgrade available.
2. **Multi-hop / iterative retrieval.** A question needing two papers combined is answered today
   only if one passage happens to contain both halves. Iterative follow-up retrieval is the
   published fix, and the GT sets being built now include multi-paper synthesis items specifically
   to measure whether this is a real weakness here.
3. **Knowledge-graph traversal** — OpenEvidence's stated differentiator. Highest cost, least
   certain payoff at this corpus size, and it should not be attempted before 1 and 2.

**Ordering:** do not build any of these before the benchmark exists. The instruments from wave 4
(sparse-arm ablation, score-distribution census, groundedness harness) plus the ground-truth sets
being built now are what turn "SOTA-shaped" into "measured". Building ColBERT without a baseline
means never knowing whether it helped.

---

## 2. Re-parse: measured, decided

**Question:** does the corpus need re-parsing, and does it fit under 100 hours?

**Measured** (`.phase0-data/100-paper-run-stats.md`, real runs, not projections):

| operation | rate | 12,390 papers |
|---|---|---|
| Pass 1 (parse only) | 8.05 s/paper | **27.7 h** single-stream |
| Full end-to-end re-ingest | 26.1 s/paper | 89.8 h |

With 2-4 parse workers Pass 1 projects to roughly 9-17 h. PDFs are already cached (31 GB), so no
re-download.

**Decision: run a Pass-1-only FIGURES BACKFILL, not a re-ingest.**

Both fit under 100 h, but full re-ingest is the wrong instrument: it costs 3x and rewrites
`papers`, `blocks`, `chunks` and every vector — risking a corpus that currently works, to gain data
that lives in two new tables. The backfill parses the cached PDF and inserts only figure/table rows.

**Verified state before deciding:**
- causal corpus: 12,390 papers, **0 figure rows** — the `figures` table exists, nothing populated
- Waymo corpus: 1,738 papers, migration not yet applied (it self-applies on next open)
- **RI-3's chunk-payload drift never bit this data**: rechunk ran 2026-07-28, author-org tagging
  landed 2026-08-08, and the causal corpus has 0 papers with `author_orgs` populated. Nothing to
  repair.

**Safety property (RI-32's whole point):** the backfill must be structurally incapable of touching
`papers`/`blocks`/`chunks`/`summaries`/vectors. `DocumentStore.put()` deletes and reinserts all of
those, so calling it is exactly what the tool must not do. Proven by a test asserting those tables
are byte-identical (content hashes, not just row counts) after a backfill run.

**Not required for anything else.** Migrations self-apply and are idempotent; every other fix in the
31-ticket programme was in code paths, not stored data.

---

## 3. Ground truth: two independent authors, then mutual verification

Two agents are building evaluation sets from the Waymo corpus **without seeing each other's work** —
one on ox-alpha, one on Claude. Neither is told what the other produced. Where they disagree, that
disagreement is the signal.

**Both sets must test both directions of error**, which is the part most eval sets skip:

- **False negatives** — the answer IS present, but the question deliberately avoids the paper's own
  vocabulary (paraphrase, synonym the authors never used, a different subfield's framing). Catches a
  system that only matches surface wording.
- **False positives** — plausibly in-domain, reads answerable, but the corpus genuinely lacks the
  answer, with absence *verified* rather than assumed. Catches a system that always returns top-k
  and lets the reader assume relevance — the exact failure the RI-10 absence-honesty work documented
  but could not measure.

**Dimensions covered:** single-passage lookup, multi-paper synthesis, numeric/quantitative claims,
methodology, negation and scope, temporal/versioned claims.

**Vision is in scope and both models have it.** ox-alpha accepts image and video input (verified via
the provider's model metadata); Claude reads images. `pypdfium2` renders PDF pages. Where an answer
genuinely depends on a chart, ODD map, or comparison table that the text layer represents poorly,
the page is rendered and read, and the item is marked `vision_derived` with its page number. Neither
author may guess at a figure it cannot read confidently.

**Grounding rule:** every answerable item cites a real `paper_id` and a `passage_excerpt` verified
programmatically to occur in that paper's stored text. No passage from memory — the same standard
that caught RI-M5's fixture and let it be independently re-verified.

**Then: cross-verification.** Each author checks the other's set — excerpt fidelity, absence claims,
whether "answerable" items really are, whether the dimension labels hold. Items that survive both
become the benchmark; items that don't are the interesting ones.

---

## 4. Benchmark

Only once the ground truth exists:

1. Run the existing wave-4 instruments against the real corpus — sparse-arm ablation (RI-M3),
   score-distribution census (RI-M7), truncation census (RI-M4), groundedness harness (RI-M6).
2. Score retrieval against both GT sets, reporting false-negative and false-positive rates
   **separately** — a single accuracy number hides exactly the asymmetry this set was built to expose.
3. RI-M7 settles the relevance-floor question that has been deferred twice. Its verdict already
   carries its own upper-bound caveat.

Only after that is there a baseline against which ColBERT, multi-hop, or a knowledge graph can be
judged. Until then any such work is unfalsifiable.
