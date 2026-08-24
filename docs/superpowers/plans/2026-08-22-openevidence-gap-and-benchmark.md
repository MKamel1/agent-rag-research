# Rivalling OpenEvidence locally — gap analysis, re-parse decision, and benchmark plan

Written 2026-08-22, rewritten 2026-08-23 against `BENCH-1-waymo-baseline`'s measurements. Every
number here was measured or verified against source, not estimated; where something is unverified
it says so. **The 2026-08-22 version of this document claimed retrieval-architecture parity with
the published state of the art. That claim did not survive contact with the benchmark and has been
removed.** See §1 for what replaced it, and `docs/eval-reports/2026-08-22-waymo-baseline.md` (plus
its raw JSON in the same directory) for the instrument runs this rewrite is built on.

---

## 1. What OpenEvidence actually is, and where the gap really lies

### 1.1 Their moat is the corpus, not (verifiably) the architecture

OpenEvidence has licensed 300+ peer-reviewed medical journals — NEJM's full archive since 1990,
JAMA's eleven-journal specialty network, Cochrane reviews, NCCN guidelines — and indexes over 35
million papers, generating answers only from that licensed set
([OpenEvidence × NEJM Group announcement](https://www.openevidence.com/announcements/openevidence-and-nejm);
[OpenEvidence × JAMA Network announcement](https://www.openevidence.com/announcements/openevidence-and-the-jama-network-sign-strategic-content-agreement)
— both primary/company sources, dates not independently confirmable from the page content fetched).

**On architecture, the public record is much thinner than the 2026-08-22 draft of this document
implied.** OpenEvidence describes its retrieval layer internally as "SystemAI," a "graph-based
retrieval-augmented generation architecture" that traverses a medical knowledge graph (disease /
drug / pathway relations) to assemble evidence across documents before generation. **This is the
company's own description, not an independently verified one** — a secondary analysis explicitly
flags it as such: "The graph RAG claim is the company's own description of SystemAI. No published
independent technical audit of the architecture exists." (Ram Paragi,
[*OpenEvidence: A Clinical and Strategic Assessment for Academic Medical Practice*](https://datadrivenmed.github.io/OpenEvidence/),
dated 2026-04-09 — a third-party clinical/strategic assessment, not an audit of the codebase or
infrastructure). A separate third-party report describes the pipeline more plainly as "licensed
literature flows through vector search and semantic mapping to ground answers" and does not repeat
the graph-RAG claim at all
([Pebblous, *The Medical AI Moat Isn't the Model. It's the Licensed Journals.*](https://blog.pebblous.ai/report/openevidence-medical-ai-data-moat/en/),
no publish date visible on the fetched page). **Where these two secondary sources disagree on
architecture, neither is independently confirmed** — this document is not going to adjudicate
between "graph traversal" and "vector search with semantic mapping" as OpenEvidence's real
retrieval mechanism, because nobody outside the company has published enough to settle it.
OpenEvidence's own public-facing About page, by contrast, makes no technical architecture claims at
all — only adoption and partnership marketing ("the leading medical information platform," "over
200 million AI-powered clinical consultations") — so even the graph-RAG claim traces back to
company statements made elsewhere, not to the company's own primary documentation.

**This matters for the goal.** "As good as OpenEvidence" splits into questions with very different
achievability, not one question:

- **Corpus/licensing parity: not achievable, and not the right target.** You cannot license NEJM.
  This system is scoped to causal-methods and AV-safety literature, where the authoritative sources
  are open (arXiv, published PDFs). Within its domain the corpus can be *complete* in a way a
  general medical index cannot — but domain-scoped completeness is a different claim from general
  medical coverage, and this document is careful not to conflate the two going forward.
- **Retrieval-architecture parity: presence of components was confused with benefit from them.**
  The 2026-08-22 draft listed hybrid dense+sparse and RRF fusion as things this system "has," in a
  table headed "this system," and concluded "essentially at parity with the published state of the
  art." Having a component in the pipeline is not the same claim as that component helping — §1.2
  below is what changed the conclusion.
- **Abstention/trustworthiness parity: not attempted, and not previously named as a gap at all.**
  OpenEvidence's entire product claim is answering only from licensed evidence and rejecting
  unsourced answers. §1.3 measures whether this system can tell an answerable question from an
  unanswerable one. It cannot, currently.
- **Groundedness/faithfulness parity: unmeasured, not unknown-but-fine.** §1.4.

### 1.2 Retrieval architecture: measured, not assumed

The current published consensus for production RAG is still: metadata filter → parallel hybrid
search (dense ANN + sparse) → RRF fusion → cross-encoder rerank → grounded generation with
citations, and this system implements all of those stages:

| stage | SOTA default | this system |
|---|---|---|
| hybrid dense + sparse | required | yes, with server-side IDF weighting |
| RRF fusion | k = 60 | `RRF_K = 60` (`contracts/fusion.py:18`) |
| cross-encoder rerank | 10-25% precision gain | yes, over a 32-deep pool |
| grounded citations | required | yes, verbatim passages with anchors |
| runs locally at ~0 API cost | — | yes |

**That checklist is true and it is not the finding.** `BENCH-1-waymo-baseline` ran `app/retrieval_eval.py`
against the real, live Waymo corpus (1,738 papers, 46,155 chunks, `waymo_av_safety` Qdrant
collection, verified `points_count: 47893`) with `--sparse-mode` pinned to `fused` (the shipped
config, `hybrid_dense_weight: 0.5`), `dense_only` (1.0), and `sparse_only` (0.0), against 65
answerable ground-truth questions. Paper-level Recall@10 / MRR
(`docs/eval-reports/2026-08-22-waymo-baseline-retrieval-{fused,dense-only,sparse-only}.json`):

| sparse mode | Recall@10 | MRR |
|---|---|---|
| dense only | **0.969** | 0.841 |
| fused (shipped config) | **0.892** | 0.828 |
| sparse only | 0.631 | 0.594 |

**Fusion at the shipped weight is a net negative against dense alone on this corpus.** Per-question
(comparing `docs/eval-reports/2026-08-22-waymo-baseline-retrieval-fused.json` and
`...-dense-only.json` directly, paper-level hits): five questions the dense arm retrieved that
fusion lost — Q-GTA-010, Q-GTA-011, Q-GTA-020, Q-GTA-022, Q-WAYB-002 — against **zero** questions
in the other direction (nothing fusion retrieved that dense alone missed). Where fusion kept the
gold paper at all, it frequently pushed it down: Q-GTA-007 rank 3 → 10, Q-GTA-015 rank 1 → 7 (two
of seven questions with a rank change; the other five moved by 1-2 positions or improved). Sparse
alone is a real, meaningfully weaker retriever (0.631 recall on its own — genuinely finding roughly
two-thirds of answers through lexical/IDF matching, not nothing) but the current RRF weight (0.5) is
not extracting the best of both signals; it is currently strictly worse than not using sparse at
all, on this fixture.

**This is one corpus, n=65 answerable questions.** The direction of the finding (fused ≤ dense_only
here, 5-0 with no counterexample) is a real, measured asymmetry on the only corpus this has been
run against — solid enough to reject the "essentially at parity" framing and to justify not shipping
`hybrid_dense_weight: 0.5` as if it were free. The *magnitude* (exactly how much recall the current
weight costs, whether a different weight would recover it) is not established beyond this one
fixture and should not be quoted as a general property of hybrid retrieval or of this system on
other corpora.

**What the SOTA checklist actually earns this system, honestly:** a genuinely strong dense-only
retriever (0.969 paper-level recall is a good number by any standard) plus a reranker and citation
layer that are real, working infrastructure — not "architecture parity with OpenEvidence," a claim
this document can no longer make and should not have made on an architecture checklist alone.

### 1.3 Abstention: measured absent from the old gap list, and the retriever cannot do it

The 2026-08-22 draft ranked three architectural gaps (late interaction, multi-hop, knowledge-graph
traversal) and did not mention abstention. `app/score_distribution_census.py` (RI-M7) measured
whether this system's retrieval scores can distinguish an answerable question from a genuinely
unanswerable one — run against the *real* 8 known-absent items from `waymo_gt_verified.json` (not
the module's fabricated-entity default arm, which the module's own docstring flags as an
upper-bound), so this result carries none of that caveat
(`docs/eval-reports/2026-08-22-waymo-baseline-score-census.json`):

| arm | n | mean top score | IQR (p25-p75) |
|---|---|---|---|
| known-answerable | 65 | 0.01129 | [0.00855, 0.01407] |
| known-absent | 8 | 0.01103 | [0.00819, 0.01447] |

`distributions_separate: false`. The known-absent IQR sits almost entirely inside the answerable
IQR — no relevance-score threshold exists that would separate the two arms. And it is not a case of
low-confidence-but-present results: **all 8 known-absent questions return a confident, full top-10
result** under every sparse mode tested (`n_with_top_result: 8/8` in all three arms of
`docs/eval-reports/2026-08-22-waymo-baseline-retrieval-*.json`). The system does not fail
gracefully on an absent topic; it answers as if the topic were present.

**Why this outranks the architecture gaps, not just supplements them:** OpenEvidence's entire
product proposition is answering *only* from evidence it actually has and rejecting what it
doesn't. A system that always returns a confident top-10 result — regardless of whether the corpus
actually contains an answer — cannot rival that proposition regardless of how good its recall is
when an answer does exist. 0.969 recall on real questions is a genuine strength; it says nothing
about the 8/8 rate at which this system also confidently answers questions it has no basis to
answer. This is why abstention is placed first in the re-ranked list in §5, not fourth or absent.

### 1.4 Groundedness: unmeasured, not merely unverified

`app/judge_eval.py` implements the harness both RI-M2 (fabrication audit) and RI-M6 (groundedness)
were meant to run on, but `Judge` is only a `Protocol` (`app/judge_eval.py:87`) — no concrete
implementation exists anywhere in the repo. `--judge-factory` is a required CLI argument
(`app/judge_eval.py:243`), so the module refuses to run at all without one:

```
$ python -m app.judge_eval --rubric docs/eval-rubrics/groundedness-rubric.md
judge_eval.py: error: the following arguments are required: --judge-factory
```

The only thing satisfying the `Judge` protocol anywhere in the repo is `FakeJudge`, a canned-verdict
test double used exclusively by the unit suite (`app/test_judge_eval.py`). Separately, even a
working judge would score against a rubric marked, in its own header,
"**PROVISIONAL — not a baseline.** Nobody has signed off on this rubric yet"
(`docs/eval-rubrics/groundedness-rubric.md:3`). So this is not "we haven't gotten to it yet" —
fabrication rate and citation faithfulness, the two axes OpenEvidence's own product claim is
actually judged on (grounded-or-refuse), have **no number of any kind** for this system. See §6.

---

## 2. Re-parse: measured, decided

**Question:** does the corpus need re-parsing, and does it fit under 100 hours?

**This section originally carried two rounds of estimates, and both were wrong — in opposite
directions.** The 2026-08-22 draft projected 8.05 s/paper → 3.9 h for the 1,738-paper Waymo
backfill, extrapolated from a 250-paper full-ingest run (`.phase0-data/100-paper-run-stats.md`) that
was not the same operation as the actual RI-32 figures-only backfill. A later interim estimate,
derived from a 101-paper parser-eval batch, projected 12.73 s/paper → roughly 6.2 h for the same
job — closer, but still wrong, and wrong the other way. **The real run measured 5.4 s/paper**:
1,738 papers processed in 9,298.8 s = 2.58 h, 1,718 papers backfilled, 0 failures
(`docs/PROJECT-STATUS.md:570-572`, RI-32 completion entry; `9298.8 / 1738 = 5.35` s/paper, `9298.8 /
3600 = 2.58` h — both recomputed here from the raw figures rather than taken on faith). Neither
estimate — the original 8.05 s/paper (44% too slow) nor the interim 12.73 s/paper (over 2x too
slow) — transferred from the corpus/batch it was measured on to this one. **The lesson is not "our
numbers were off by a fixed factor," it's that a parse-rate benchmark measured on a different corpus
or a different operation (full ingest vs. figures-only backfill) does not transfer, and the only
number worth planning against is one measured on the actual job, on the actual corpus.**

**Corpus priority (operator, 2026-08-22): Waymo first, not causal.** It has near-term use and is
7x smaller, so it is both the more valuable and the cheaper target — and it is the corpus both
ground-truth sets are built against, so backfilling it is what makes vision-derived evaluation
items possible at all. This has since been borne out: the Waymo backfill is complete and is what
every measurement in this document's §1 is run against.

| corpus | papers | estimate (2026-08-22, 8.05 s/paper) | interim estimate (12.73 s/paper) | **measured** |
|---|---|---|---|---|
| **Waymo** | 1,738 | 3.9 h | ~6.2 h | **2.58 h (5.4 s/paper, 9,298.8 s)** |
| causal | 12,390 | 27.7 h | ~43.8 h | not yet run |

Causal remains available on the same tool afterwards if wanted; it is not on the critical path, and
now that the actual per-paper rate on this system is known (5.4 s/paper, on Waymo), a causal-corpus
estimate can be built from a measured number rather than another projection — 12,390 × 5.4 s ≈ 18.6
h single-stream, itself still a cross-corpus projection and not a measurement until it is run.

Note the Waymo corpus has not had migration 0006 applied yet — it self-applies on the first
`DocumentStore` open, which the backfill will trigger. Idempotent, no manual step.

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

Two agents are building evaluation sets from the Waymo corpus (the operator's priority corpus) **without seeing each other's work** —
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
