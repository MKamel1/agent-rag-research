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
- **Groundedness/faithfulness parity: unmeasured, not unknown-but-fine.** §1.5.

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

### 1.4 Published evaluations of OpenEvidence's accuracy, and what benchmark this system lacks

Three independent evaluations of OpenEvidence's accuracy were found, and they disagree with each
other sharply enough that the disagreement itself is the finding:

- **NYU Langone / *Nature Medicine*, June 2026** ("General-purpose large language models outperform
  specialized clinical AI tools on medical benchmarks," `nature.com/articles/s41591-026-04431-5` —
  peer-reviewed journal publication, the strongest-form source found here, though the full text sat
  behind a login wall and this summary is built from search-result/abstract-level reporting, not a
  full read of the paper). Methodology: OpenEvidence and UpToDate Expert AI vs. three frontier
  models (GPT-5.2, Gemini 3.1 Pro, Claude Opus 4.6) across 500 MedQA licensing-exam questions, 500
  HealthBench items (clinician-alignment), and 100 real clinical queries graded by 12 blinded
  clinicians. **Finding: frontier general-purpose models beat OpenEvidence on all three stages** —
  Gemini scored 97.4% on MedQA vs. OpenEvidence's 89.6%, and the paper characterizes OpenEvidence's
  specific weakness as "clarity of communication rather than knowledge." The authors themselves flag
  a contamination risk: MedQA and HealthBench are public benchmarks the frontier models may have
  seen during training.
- **medRxiv pilot study, posted 2025-12-04** ("The accuracy and repeatability of OpenEvidence on
  complex medical subspecialty scenarios," `medrxiv.org/content/10.64898/2025.11.29.25341091` — a
  preprint, not peer-reviewed). Methodology: 100 hard subspecialty questions from MedXpertQA
  (materially harder than MedQA), manually run through OpenEvidence's two modes, two raters. **OE
  (quick) scored 31% average accuracy, Deep Consult scored 39.5%** — a very different picture from
  the MedQA number above, on a harder benchmark. The authors note this pilot is "underpowered for
  subgroup analyses" and had no API access (manual testing only).
- **"Real-POCQi" preprint** (found only via secondary reporting — the primary preprint itself was
  not located directly, so this entry carries an extra layer of unverified indirection; treat it as
  the weakest-sourced of the three). Reported methodology: 620 real point-of-care queries actually
  submitted to OpenEvidence, 149 specialty-matched physicians grading OpenEvidence against three
  frontier models blind. **Finding: OpenEvidence scored highest on all five measured dimensions**
  (accuracy, clinical utility, source quality, verifiability, completeness) — the opposite
  conclusion from the *Nature Medicine* study.

A secondary source comparing the two contradictory studies
([iatrox.com, *OpenEvidence vs ChatGPT and the Frontier Models: Why Two 2026 Studies Reached
Opposite Conclusions*](https://www.iatrox.com/blog/openevidence-vs-chatgpt-why-2026-studies-disagree))
attributes the disagreement to question type (exam-style vs. real point-of-care queries), query
provenance (each study's "real queries" originated from the *other* product's user base), grader
pool size/expertise, and different, already-superseded model versions between the two studies.

**What this means for benchmarking this system:** OpenEvidence is scored, however inconsistently,
against named external benchmarks (MedQA, HealthBench, MedXpertQA, and now a real-query-based
methodology) by researchers outside the company. This system has **no analogous external
benchmark** — every number in this document is measured against ground truth authored for this
system's own corpus, by this project's own contributors. That is a legitimate and necessary first
step (you cannot borrow MedQA for an AV-safety corpus — no such benchmark exists), but it is not the
same claim as "externally validated." The closest available analogue to what NYU Langone or
Real-POCQi did — independent graders, real user-style queries, a methodology this project did not
design itself — does not exist for this system and is named explicitly as unmeasured in §6.

**Scale and business context, for calibration, not for the architecture question.** OpenEvidence
raised $250M in a Series D at a $12B valuation in January 2026, doubling its prior valuation
([CNBC](https://www.cnbc.com/2026/01/21/openevidence-chatgpt-for-doctors-doubles-valuation-to-12-billion.html);
[STAT News](https://www.statnews.com/2026/01/21/health-ai-starutup-openevidence-raises-250-million/)
— both independent journalism, company-sourced figures within the reporting). By July 2026 the
company was reportedly weighing a further $200M raise at a $20B valuation, with ~$300M ARR (roughly
double the figure from seven months earlier) and reported acquisition interest from a large tech
company ([PYMNTS](https://www.pymnts.com/news/artificial-intelligence/2026/medical-ai-startup-openevidence-weighs-200-million-funding-round/)).
Company-stated adoption (~40% of US physicians) and query volume (18M/month as of Dec 2025) were not
independently verified by any source found here — the Pebblous report explicitly flags this class of
number as "company-stated or third-party estimates," advising readers to "read the structure rather
than the numbers." This context does not bear on the architecture questions in §1.1-1.3; it is
included because it is directly relevant to how large a target OpenEvidence is and how much
independent scrutiny it has actually attracted (comparatively little, on the architecture; more, and
contested, on accuracy).

### 1.5 Groundedness: measured 2026-08-23, provisionally, and it measures something narrower than it looks

**Superseded.** This section previously read "unmeasured, not merely unverified" — correct when
written. JUDGE-1 has since filled the empty `Judge` seam (`app/judge_llm.py::LlmJudge`, a local
model behind the existing Protocol) and produced the first run.

| | |
|---|---|
| auditable | 64 of 68 answerable items (the 4 vision-derived carry no text passage) |
| scored | 63 (1 judge-JSON error) |
| claims | **210**: 128 supported (0.610), 81 unsupported (0.386), 1 contradicted (0.005) |
| known-absent arm | **0 of 16 auditable** |

**Three qualifications, all of which matter more than the headline rate:**

1. **This measures the fixture, not the system.** `load_items()` builds its audit items from the
   ground-truth *file*, so the answers judged are the gold answers, not anything the system
   generated. The number says how traceable those answers are to their own cited excerpts. It is
   **not** a fabrication rate for this system, and should not be quoted as one.
2. **The unsupported rate is largely the rubric working as designed.** Spot-checks split two ways:
   `Q-GTA-003`'s answer cites "19,002 million VMT", genuinely absent from its cited excerpt though
   present elsewhere in the same paper — a real citation-scope defect of the class GT-X flagged on
   `Q-GTA-024`/`Q-GTA-031`; `Q-GTA-004`'s excerpt is one sentence and the answer adds a Poisson
   model and CRSS standard errors that are not in it — defensible strictness, not judge error.
3. **The one `contradicted` verdict is a judge error.** On `Q-GTA-021` the judge compared against
   the wrong one of two supplied passages; 798 + 202 reconciles to the 1,000 the claim asserts.
   Measured contradiction is effectively **0 of 210**. The judge is hand-audited at n=9 with 8
   agreements — thin, and stated as thin.

**The known-absent arm returning 0/16 is the structural finding, not a low score.** Those records
carry no `answer_text` because this repository serves *retrieval only* — no downstream generation
has ever been captured for them. **A real fabrication measurement requires a generation run first.**
That is the concrete next step on this axis, and it is named in §6.

The rubric remains **PROVISIONAL and unsigned**; the report stamps `rubric_sha256_12` so runs under
different wordings cannot be silently compared. Sign-off is an operator decision.

---

## 1.6 The scorecard: how far are we, answered as precisely as the evidence allows

The operator's question is "how far are we from a RAG as good as OpenEvidence." **A percentage
answer would be fabricated**, and it is worth being exact about why rather than just asserting it:
the two systems are not measured on the same corpus, the same questions, *or the same metric class*.
OpenEvidence's published numbers are QA accuracy on medical benchmarks; this system's are retrieval
recall and groundedness on a bespoke AV-safety set. There is no shared denominator, and inventing
one would produce a number that looks rigorous and means nothing.

What the evidence does support is a capability-by-capability scorecard, with the empty cells left
visibly empty:

| capability | this system, measured | OpenEvidence, published | comparable? |
|---|---|---|---|
| corpus scale | 1,738 papers (Waymo), 12,390 (causal) | ~35M papers, 300+ licensed journals | **no** — different targets; domain-scoped completeness is not general coverage |
| corpus access | open sources, fully self-hosted | licensed (NEJM, JAMA network, Cochrane, NCCN) | **no** — not replicable at any effort |
| retrieval recall on own corpus | **0.969** R@10 dense-only, 0.892 fused (n=65; 0.9706/0.8971 on the 84-item v2, n=68) | no published figure found | **no** — they publish no retrieval metric |
| retrieval *precision* on own corpus | **P@1 0.794** (verified-84) / **0.914** (priority set); **block-level P@1 0.375 / 0.727** | no published figure found | **no** |
| QA accuracy on a public benchmark | **none — no external benchmark exists for this corpus** | 31–39.5% MedXpertQA hard subspecialty; wins on point-of-care queries | **no** — this system has no comparable number at all |
| abstention on known-unanswerable | **0 of 8 detected**; score distributions overlap (`distributions_separate: false`) | product claim is answer-only-from-evidence; no published abstention rate found | **partially** — their claim is qualitative, this system's failure is quantified |
| groundedness | 0.610 supported / 210 claims, provisional rubric, **measures fixture answers not system output** | no published groundedness rate found | **no** — neither side has a comparable figure |
| fabrication rate | **no number** — requires a generation run that has never been captured | no published figure found | **no** |
| figure/table understanding | page-level retrieval 4/4 at n=4; **no VLM in the pipeline**; `vlm_description` populated on 0 of 24,708 figure rows | not described in any source found | **no** |
| operating cost | ~0, fully local | commercial service | — |

### 1.6b "How far are we" — answered against the bar the operator actually set

The OpenEvidence comparison has no shared denominator (above). But the operator set a *second*
target, and that one is fully measurable: **recall and precision ≥ 95% on the Waymo corpus**
(`docs/eval-reports/2026-08-23-waymo-priority-benchmark-protocol.md`, frozen before any item was
authored). "How far are we" against **that** bar is a real number, per capability:

| metric | fixture / mode | measured | target | distance |
|---|---|---|---|---|
| Recall@10 | GT-WMR priority, fused | **0.9857** | 0.95 | **+3.6 pp — PASS** |
| Recall@10 | verified-84, dense-only | **0.9706** | 0.95 | **+2.1 pp — PASS** |
| Recall@10 | verified-84, fused (shipped) | 0.8971 | 0.95 | **−5.3 pp — FAIL** |
| P@1 | GT-WMR priority, dense-only | 0.9286 | 0.95 | −2.1 pp — FAIL |
| P@1 | verified-84, fused | 0.7941 | 0.95 | **−15.6 pp — FAIL** |
| block-level P@1 | GT-WMR priority | 0.7273 | 0.95 | −22.7 pp — FAIL |
| block-level P@1 | verified-84 | **0.3750** | 0.95 | **−57.5 pp — FAIL** |
| abstention on known-absent | both fixtures, n=24 | **0 detected** | — (no target set) | cannot abstain at all |
| wrong-side answers on unanswerable | n=16, with refusal affordance | 1 (0.0625) | — (no target set) | 5 of 6 were prompt artifact |

**Read down that column and the answer to "how far are we" is unambiguous, and it is not the answer
the recall headline suggests:**

- **Recall is essentially there.** Two of three configurations already clear 95%, and the third
  clears it the moment the fusion weight is fixed. This is not where the work is.
- **Precision is far away, and the gap widens as the unit gets smaller.** Paper-level P@1 misses by
  2–16 points. **Block-level P@1 — did rank 1 point at the right *passage* — misses by up to 57
  points.** The system finds the right document and then does not find the right paragraph inside
  it. Every retrieval number reported before block-level precision was measured overstated how close
  the system is.
- **Abstention is not near the bar; there is no bar and no capability.** 0 of 24 known-unanswerable
  questions were detected as unanswerable by score.
- **Generation-side fabrication is closer than it looked** — 1 wrong-side answer in 16 once the
  prompt permits refusal, versus 6 without.

So: **for finding the right paper, close. For finding the right passage, roughly half way. For
knowing when to say nothing, not started.** That is the honest "how far are we", and it is
measurable precisely because the target is one the operator set against this corpus — not a
cross-system percentage that no shared benchmark supports.

**The three honest conclusions this supports:**

1. **On retrieval *recall* into its own corpus, this system is strong** — 0.969 paper-level recall
   needs no apologising for. But **precision is where the operator's ≥95% bar is actually missed**:
   best P@1 is 0.929, and block-level P@1 — did rank 1 point at the right *passage*, not merely the
   right paper — is **0.375** on the verified-84 set. That is a reranking and pool-depth problem,
   not a recall problem, and recall alone was hiding it.

   **On the fusion penalty, one correction to this document's earlier phrasing:** it is
   fixture-dependent, not universal. On the verified-84 set the direction is strictly one-way
   (dense-hit/fused-miss = 5, the reverse = 0, reproduced independently on the v2 fixture). On the
   82-item GT-WMR priority set it reverses (fused-hit/dense-miss = 2, the reverse = 0, fused 0.9857
   vs dense 0.9571). So "fusion is a net negative" is true of the corpus slice measured, not of the
   configuration in general — retune it against both sets, do not disable it on one result.
2. **On the capability OpenEvidence is actually sold on — answer only from evidence, refuse
   otherwise — this system scores zero, and that is measured, not assumed** (§1.3). No retrieval
   improvement addresses it, because the score distributions carry no signal to threshold on.
3. **The largest gap is not architecture, it is that most of the scorecard is empty on both sides.**
   Three of nine rows have no published figure from OpenEvidence at all, and two have no figure
   from this system. Anyone claiming a percentage between these two systems is filling those cells
   with invention.

**What would make a real comparison possible**, in the order it becomes possible: capture a
generation run so fabrication can be measured at all → build or adopt an external benchmark for
this corpus's domain → only then is there a shared axis, and even then only against whichever
OpenEvidence numbers exist for the same metric class.

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

**Update, post-benchmark:** the set this section describes grew from 73 to 84 items in a later
verified-set v2 pass (`docs/eval-reports/2026-08-22-waymo-groundtruth-second-pass.md`); the
retrieval numbers in §1.2-1.3 above were measured against the 73-item set (65 answerable / 8
known-absent), not the current 84-item one. On vision: only **1** of the 73 items measured
(`Q-WAYB-027`) is `vision_derived`, verified directly against `fixtures/eval/waymo_gt_verified.json`
— the current 84-item file has grown to 4 vision-derived items, but the other 3
(`Q-GTA-042/043/044`) were added by the v2 pass and are not part of any number reported in §1.
Vision was used only to *build* these ground-truth items (rendering a PDF page and reading a chart,
ODD map, or table the text layer represents poorly); it has never been used to *evaluate* retrieval
itself — see §6.

---

## 4. Benchmark: run 2026-08-22, and what it says

The plan below (as written before the benchmark ran) called for the wave-4 instruments to be run
once ground truth existed and to report false-negative/false-positive rates separately rather than
blending them into one accuracy number. That run happened
(`docs/eval-reports/2026-08-22-waymo-baseline.md`, worktree `BENCH-1-waymo-baseline`) and its
numbers are what §1.2-1.3 above are built from. Restated here as the completed instrument run this
section originally specified:

1. **Sparse-arm ablation (RI-M3)** — `app/retrieval_eval.py` run three times (`fused`, `dense_only`,
   `sparse_only`) against `waymo_gt_verified.json`'s 65 answerable items. Result: §1.2.
2. **Score-distribution census (RI-M7)** — run against the real 8-item known-absent arm, not the
   instrument's fabricated-entity default. Result: §1.3 — `distributions_separate: false`, settling
   the relevance-floor question this document had deferred twice, with **no** upper-bound caveat
   (that caveat only attaches to the fabricated-entity default arm, which was deliberately not used
   here).
3. **Truncation census (RI-M4)** — `scripts.truncation_census` scanned all 1,738 papers
   (`docs/eval-reports/2026-08-22-waymo-baseline-truncation-census.txt`). Reranker item ceiling
   binds on 1/46,155 chunks (0.0%, 2,486 tokens — one `REFERENCES` section). Reranker batch-budget
   pressure binds on 33,958/46,155 chunks (73.6%) but drops nothing by construction — it only forces
   an extra HTTP call. The **summarizer's whole-document ceiling binds on 1,669/1,738 papers
   (96.0%)**, truncating each to its first 7,356 words and dropping ~7.98M words in total (worst
   single paper: over 100,000 words dropped). This sits in the paper-summary pipeline, not in
   `Retriever.retrieve()` — it does not explain the recall numbers in §1.2, and it is a real,
   previously-unmeasured cost of the current summarization design, independent of retrieval quality.
   The token-count-per-word calibration behind these figures is itself unmeasured (`_TOKENS_PER_WORD_ESTIMATE`
   is never checked against the generation server's real per-response token count) — the bind rates
   above are measured against an estimate, stated as such in the instrument's own output.
4. **Groundedness harness (RI-M6)** — could not run at all. §1.5.

Only after this baseline is there evidence against which ColBERT, multi-hop, or a knowledge graph
can be judged — that condition is now satisfied, and §5 uses it.

---

## 5. Re-ranked roadmap, defended against the measurements

The 2026-08-22 draft ranked three architectural upgrades — late interaction, multi-hop, knowledge
graph — and did not include abstention or groundedness measurement at all. Re-ranked here against
what was actually measured:

1. **Retune or disable the shipped fusion weight (`hybrid_dense_weight: 0.5`).** Not a build — an
   operator config change, near-zero cost, and the only item on this list with a *negative* number
   currently attached to leaving it alone: fusion loses 5-0 to dense-only with no counterexample
   (§1.2). Ranked first because it is the cheapest and most directly evidenced change available;
   nothing else on this list should be prioritized ahead of stopping a config from actively costing
   recall. (This is not the same claim as "sparse is useless" — sparse alone found 0.631 of answers
   the dense arm didn't need it for; the finding is specifically that RRF at k=60, weight=0.5 is not
   currently combining the two well on this corpus.)
2. **Abstention / a relevance floor that isn't a raw score threshold.** Placed first among genuine
   build items, ahead of any retrieval-architecture upgrade, because §1.3 measured that this system
   currently cannot distinguish an answerable question from an unanswerable one at all — every
   known-absent question returns a confident top-10 result, and the score distributions overlap
   almost completely. This is not a retrieval-quality gap that a better retriever fixes; RI-10's
   standing conclusion (reaffirmed, not just left unchallenged, by this run) is that abstention has
   to be a presentation/prompting-layer decision, informed by something other than the retrieval
   score — plausibly a groundedness check against retrieved passages (which is item 3), an explicit
   query-answerability classifier, or corpus-coverage metadata the retriever doesn't currently
   expose. Ranked above the architecture gaps because OpenEvidence's product claim is specifically
   "answer only from evidence, refuse otherwise," and this system currently cannot do the "refuse"
   half regardless of how good the "answer" half is.
3. **Build a real groundedness/fabrication judge and get the rubric signed off.** §1.5 — this is
   currently a total blank, on the exact axis (grounded-or-refuse) OpenEvidence is judged on in the
   evaluations found in §1.4. Ranked third, not last, for two reasons: it is comparatively cheap (an
   LLM-judge harness against an already-drafted rubric, not a new retrieval subsystem), and it is a
   *prerequisite* for evaluating whether any future architecture change (item 4 onward) actually
   improves what a user reads, as opposed to only what the retriever returns. Building ColBERT or a
   knowledge graph without a working groundedness check means being unable to tell whether a
   retrieval upgrade made real answers better or merely reshuffled which passages get cited.
4. **Late interaction (ColBERT-style) as a third retrieval pillar.** Now backed by a concrete reason
   rather than a general architecture-checklist entry: §1.2 shows sparse alone recovers real signal
   (0.631 recall) that dense doesn't fully cover, but the current coarse RRF fusion is not
   extracting the best of both — it's currently worse than dense alone. A fine-grained, per-token
   matching layer is the kind of upgrade that could combine both signals without the current
   fusion's cost, and `PRD.md:657` already anticipates it for the V2+/VLM phase (ColPali for
   figure/equation pages). Ranked fourth: it is real, evidenced work, but everything above it is
   cheaper, more directly measured, or a prerequisite for judging whether this helps.
5. **Multi-hop / iterative retrieval.** Unchanged from the 2026-08-22 draft's reasoning — a question
   needing two papers combined is answered today only if one passage happens to contain both halves
   — but still genuinely unmeasured: this baseline did not isolate multi-hop failure specifically
   (the GT sets carry multi-paper synthesis items via `additional_gold_paper_ids`/multi-gold
   scoring, which is a generous measurement, not a targeted one). Ranked fifth: plausible, not yet
   evidenced as a distinct failure mode the way abstention and the fusion weight are.
6. **Knowledge-graph traversal.** Last, and more clearly deprioritized than the 2026-08-22 draft
   argued. That draft called it "OpenEvidence's stated differentiator" and ranked it third on cost
   grounds alone. §1.4's research adds a second reason to deprioritize it further: OpenEvidence's
   own graph-RAG claim is unverified by any independent technical audit found in this research pass,
   and the one independent accuracy measurement on the kind of complex, multi-system reasoning a
   knowledge graph is supposed to help with (the medRxiv MedXpertQA pilot, §1.4) found OpenEvidence
   itself scoring only 31-39.5% on exactly that question class. Building the most expensive item on
   this list to match a competitor's stated differentiator is weaker justification when that
   differentiator's own real-world payoff is itself unverified and, on the one measurement found, not
   obviously working well even for the company making the claim.

---

## 6. What remains unmeasured

Stated explicitly, not left implicit:

- **Fabrication rate — still zero data, for a structural reason.** Groundedness itself is no longer
  unmeasured: JUDGE-1 built the missing judge and ran it (§1.5). But that run scores the ground-truth
  fixture's own answers against their cited excerpts, and the known-absent arm returned **0 of 16
  auditable** because those records carry no `answer_text` at all — this repository serves retrieval
  only, so **no generated answer has ever been captured to audit**. Whether *generated* answers are
  faithful to retrieved passages remains entirely unknown. Capturing a generation run is the
  prerequisite, and is the single cheapest unblocking step left on this list. §1.5, §5 item 3.
- **The rubric's sign-off.** Every groundedness number is produced under a rubric whose own header
  says approval "belongs to a human." Until that happens, no groundedness figure can serve as a
  baseline or a regression gate, by the rubric's own terms.
- **Any external, independently-designed benchmark.** Every number in this document is measured
  against ground truth this project authored for its own corpus. No analogue exists to what NYU
  Langone or the Real-POCQi methodology did for OpenEvidence — independent graders, a benchmark this
  project didn't design, ideally real user-style queries rather than authored ones. §1.4.
- **A VLM inside the pipeline** — no longer "VLM-based retrieval evaluation," which has now been
  done. The vision arm was measured 2026-08-23: **4/4 paper-level recall@10 at ranks 1, 2, 1, 1**,
  and every one of the four returned a gold-paper chunk within one page of the answer's page (two
  exactly on it). So text-chunk retrieval *can* reach the right page for a question whose answer
  exists only in an image — **page-level retrieval is not the blocker**. What is missing is the step
  after: nothing in the pipeline reads that page. `figures` carries `page` and `bbox_json` for all
  24,708 rows but `vlm_description` is populated on **zero** of them, so there is no figure content
  for a query embedding to match and no VLM re-reading a retrieved page at answer time. n=4 — a
  direction, not a rate. `PRD.md:657`'s ColPali-based figure retrieval (§5 item 4) remains unbuilt.
- **The magnitude of the fusion-weight cost**, beyond direction. §1.2's 5-0 asymmetry is solid
  evidence of direction on this one corpus; it does not establish how much recall a re-tuned weight
  would recover, or whether the same direction holds on the causal-methods corpus, which has not
  been benchmarked with this instrument at all.
- **Causal-corpus retrieval, entirely.** Every measurement in this document is Waymo-only, per the
  operator's stated priority (§2). The causal-methods corpus (12,390 papers) has not been re-parsed,
  backfilled, or run through any of the wave-4 instruments.
