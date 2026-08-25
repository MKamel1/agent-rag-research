# NB-6 — VLM/vision project scoping: does unique figure information justify the project?

**Status: SCOPING IN PROGRESS** (stub — sections filling in numbered commits; this header flips to
COMPLETE when all four land). Ticket NB-6, standing independent lane of the next-build programme
(`docs/superpowers/plans/2026-08-24-next-build-programme.md` §4, gated only on operator decision C,
answered conditional 2026-08-25 in that programme's §1). Branch `NB-6-vlm-scoping`. This document
scopes; it builds nothing — no model downloads, no config changes, no service changes, no foundation
paths (programme §2 constraints 9; ticket brief).

Every number cites its source file. Where something is estimated rather than measured, the word
ESTIMATE appears next to it; where a number is extrapolated beyond its measured denominator, the
extrapolation is labeled inline.

## Inputs this scoping stands on

| fact | value | source |
|---|---|---|
| Measured floor: items absent from EVERY pool size | 5 scored items = ver84 Q-GTA-042/043/044 + Q-WAYB-027, GT-WMR Q-WMR-094 | `docs/eval-reports/2026-08-25-nb-d1-pool-depth.md` (population detail + depth histogram) |
| Extraction-gap caveat | Q-GTA-044's nine inset values ARE selectable via `fitz.get_text()`; dropped by this corpus's block/chunk extractor — an extraction-pipeline gap, not a true vision requirement; two independent reviewers | `docs/superpowers/plans/2026-08-23-openevidence-programme.md` §3 |
| Opportunity size | figures 24,708 rows / tables 8,266; `vlm_description` populated on 0 | `docs/PROJECT-STATUS.md` Waymo-priority section; `migrations/0006_figures_tables.sql`; `DATA-CONTRACTS.md` figures/tables schema |
| VRAM co-residency trap | MinerU footprint not flat: ~13GB routine peak, observed ~23.7GB/24GB (96.4%); TEI embedder+reranker ~9.4GB resident | `docs/PROJECT-STATUS.md` §4 T-DOC15 |
| Vision arm shape | all 4 ver84 vision items right paper at rank 1, gold block unreachable by text; page-level retrieval 4/4 at n=4 | programme plan §0 (handoff §5.3); `docs/superpowers/plans/2026-08-22-openevidence-gap-and-benchmark.md` |

## §1 Unique-information-yield analysis (the Decision C gate)

Operator decision C (`docs/superpowers/plans/2026-08-24-next-build-programme.md` §1): proceed only
if VLM earns its cost by information *only it* can reach. This section measures that population and
prices what is honestly known about it.

### The measured floor: 5 items no text path can reach, proven exhausted

NB-D1 asked, for every right-paper-wrong-block item across both fixtures, whether the gold block
appears anywhere in the reranked candidate pool at K ∈ {32, 64, 128} (on top of the shipped K=10
path). The items absent from every pool size are exactly the vision-derived ones
(`docs/eval-reports/2026-08-25-nb-d1-pool-depth.md`):

| fixture | scored n | near-miss population | unreachable by ANY text fix | identities |
|---|---|---|---|---|
| verified-84 | 64 | 27 (C1∪C2) | **4** = 14.8% of the population; 6.25% of scored | Q-GTA-042, Q-GTA-043, Q-GTA-044, Q-WAYB-027 |
| GT-WMR | 66 | 12 (C1∪C2) | **1** = 8.3% of the population; 1.52% of scored | Q-WMR-094 |
| both | 130 | 39 | **5** = 12.8% of populations; 3.85% of scored | — |

Structurally means: their answers live in figure/chart content that no text chunk carries, so no
retrieval-side or reranking-side fix (X-P/X-O/X-F classes) can rank them — D1's own reading ("their
answers live in figures no text retrieval can rank"). The programme's shorthand "the 15% unreachable
slice" (programme plan §4 NB-6) maps to the 4/27 ver84 population fraction above; this doc cites the
exact fractions everywhere.

### The discount: Q-GTA-044 is not a true vision requirement

Q-GTA-044's nine inset values *are* selectable in the raw PDF via `fitz.get_text()`; only this
corpus's block/chunk extractor drops them (`docs/superpowers/plans/2026-08-23-openevidence-programme.md`
§3; two independent reviewers). It measures an extraction-pipeline gap — potentially closable
text-side by a parser/chunker fix — not a requirement that pixels be read.

**Discounted floor: 4 true-vision items** (ver84 Q-GTA-042/043 + Q-WAYB-027; GT-WMR Q-WMR-094,
which carries no such caveat in any source reviewed). The pilot's Stage 0 (§3) re-audits all five
per-item rather than trusting this discount statically.

### Honest denominators

Vision ground truth is **n = 4 (verified-84) + 1 (GT-WMR) = 5 items ever authored**, against 68+70 =
138 authored answerable items (`docs/superpowers/plans/2026-08-23-openevidence-programme.md` §3;
`docs/PROJECT-STATUS.md` Waymo-priority section). Every number below inherits that caveat:

- Unreachable share of *scored* items: 5/130 = 3.85% measured; after discount 4/130 = 3.08%.
- Unreachable share of *authored answerable* items: 5/138 = 3.6%; after discount 4/138 = 2.9%.
- Fixture authoring rates for context: vision = 4/68 answerable on verified-84 (4.8%, openevidence
  §4), 1/70 on GT-WMR (1.4%).

**EXTRAPOLATION, labeled:** these rates measure what fixture *authors chose to ask*, not what the
operator actually asks. No organic query log exists in this repo. Extrapolating "≈3–5% of
operator-relevant questions need figure-only content" from hand-authored fixtures assumes the
fixture mix resembles the operator's real question mix — an assumption with zero measurement behind
it. §3's pilot is partly designed to produce the first demand-side evidence; until then the honest
statement is: *the prevalence of figure-only questions in real usage is unmeasured.*

### Opportunity size vs. yield

The corpus holds figures 24,708 rows / tables 8,266 with `vlm_description` populated on 0
(`docs/PROJECT-STATUS.md` Waymo-priority section; `migrations/0006_figures_tables.sql`; location
ready via `image_path` + caption + page + `bbox_json`, content empty — `DATA-CONTRACTS.md`). This is
opportunity size, NOT yield: 24,708 unpopulated descriptions say nothing about how many operator
questions need them. Conflating the two would be the same error as MinerU's flat-footprint estimate
(T-DOC15): arithmetic optimism standing in for a measurement. Page-level anchors already work —
page-level retrieval went 4/4 at n=4 (`2026-08-22-openevidence-gap-and-benchmark.md`) while block-
level stayed unreachable — so the missing piece is genuinely content, not location.

### What a VLM would and would not buy, against the frozen target

The operator target is recall and precision ≥ 95% on the Waymo corpus (frozen before implementation;
`docs/PROJECT-STATUS.md` Waymo-priority section). Current ceilings (D1, bottomless-at-K=128 under a
perfect reranker): ver84 all-arm 56/64 = 0.8750, text-arm 56/60 = 0.9333; the four vision items are
exactly the residual between those two readings. Serving all four vision items perfectly would lift
the all-arm cap only to 60/64 = 0.9375 — **still below 0.95** (the 2026-08-23 openevidence programme's §8 records the same cap
under today's text-only accounting). So a VLM closes the *structural* gap (items no text path can
touch) but does not by itself rescue the ≥0.95 passage target on verified-84; the remaining miss is
ordering quality, a separate workstream (programme X-O lane). How vision items would be counted
post-VLM — scoped-out arm, own arm, or served-in-place — is an operator protocol decision among the three options that programme's §8 already
lists.

### Verdict line

Bar used (stated before verdict): a VLM project is worth starting iff BOTH hold —

- **B1 structural exclusivity, measured:** a non-zero ground-truth set requires figure/table content
  no text path reaches, with text remedies *proven exhausted* (not merely failing today).
- **B2 prevalence, evidenced:** such questions plausibly occur often enough in the operator's real
  usage to justify GPU co-residency risk plus build cost.

B1: **clears decisively** — n=5 measured (floor 4 after the Q-GTA-044 discount), absent from every
pool size through K=128, on both fixtures, with the page-level path already proven at 4/4. B2:
**unmeasured** — no query log exists; fixture authoring rates are proxies for author choice, not
operator demand.

**Verdict: CONDITIONAL CLEAR.** The unique-information case clears the bar's measured half and
fails its evidence half for lack of any measurement — which is exactly the shape decision C's
"conditional" anticipated. It justifies a bounded falsification pilot (§3) whose explicit secondary
deliverable is the first demand-side evidence; it does NOT justify a project-scale build commitment.
If the pilot passes its pre-committed criteria, B2 returns to the operator with numbers instead of
proxies.

## §2 Candidate architecture sketch

Only relevant because §1 cleared conditionally; every choice below is a candidate to be *measured*
in the pilot, not a commitment. Model-size and latency figures are ESTIMATEs — nothing has been
downloaded or run for this scoping (ticket constraint).

### Candidate local VLMs

| option | shape | why it fits this machine | risks |
|---|---|---|---|
| **Ollama-hosted qwen2.5-VL-class** (~7B instruct, 4-bit GGUF + mmproj vision encoder) | single host daemon; the machine already runs Ollama for summarization (`README.md`; convention: never auto-started) | smallest ops surface; quantized weights ≈ 5–7GB ESTIMATE → the only candidate plausibly co-resident with both TEI services | Ollama's vision stack is less batch-oriented; throughput for a backfill unproven here |
| **vLLM-hosted Qwen2.5-VL-7B-Instruct** (bf16 or AWQ) | dedicated inference server | real batching for the 24.7k-figure backfill path; first-class Qwen2.5-VL support | bf16 weights ≈ ~16GB ESTIMATE → co-residency dead on arrival; AWQ ≈ ~7GB but vLLM's allocator pre-reserves aggressively (`gpu_memory_utilization`), so effective headroom must be measured, not configured blind |

Either way the model class is "Qwen2.5-VL-7B-or-equivalent local" per the ticket brief; exact
quantization gets pinned at pilot Stage 0 by measurement. Zero paid API anywhere (house constraint).

### Page-render pipeline

Anchors already exist: every figure row carries `image_path` (MinerU-extracted PNG at parse time),
caption, page, and `bbox_json [x0,y0,x1,y1]` (`migrations/0006_figures_tables.sql`; `DATA-CONTRACTS.md`
figures schema). Two render modes for the VLM's input:

1. **Stored PNG directly** — zero render cost; risk: chart-only crops can lose axis labels and
   surrounding context.
2. **Full-page render via pymupdf at page+bbox** — one `Page.get_pixmap(clip=bbox-padded)` call per
   item at ~150–200 DPI ESTIMATE. Preferred default, because the Q-GTA-044 lesson cuts both ways:
   values that look "visual" are sometimes textual insets near the figure, and a page image lets
   the VLM see caption + axis + legend together.

pymupdf is verified importable in `agent-rag-research` (v1.28.2; note: import surfaces as deprecated
`fitz`; it is not an explicit `environment.yml` line today — the pilot should pin it explicitly
rather than ride a transitive dependency).

### VRAM co-residency plan — the T-DOC15 arithmetic, done pessimistically

Resident baseline: TEI embedder + reranker ≈ **~9.4GB combined**
(`docs/PROJECT-STATUS.md` §4 T-DOC15). Card: 24GB.

| scenario | naive arithmetic | reading |
|---|---|---|
| Quantized ~7B VLM + full TEI pair | 9.4 + ~5–8 ≈ **15–17GB** → 7–9GB headroom | plausible on paper; T-DOC15's whole lesson is that this class of arithmetic already failed once (flat "~6.6GB MinerU" claim vs measured ~13GB routine / ~23.7GB observed peak). Treat as hypothesis; Stage 0 measures it with sampled `nvidia-smi` before any batch runs. |
| Serialized (VLM excludes TEI) | VLM alone ≈ ≤17GB worst case | safe by construction; reuse existing machinery instead of new scheduling code (below). Costs TEI downtime during batches — acceptable offline, needs the self-healing reload for serving. |
| Anything overlapping MinerU ingest | 9.4 + ~13 routine = 22.4GB; MinerU *alone* has been observed at 23.7GB (96.4% of card) | **never**. This exact overlap arithmetic is T-DOC15's recorded trap; the pilot schedules against it explicitly. |

Serialization machinery already exists and is dashboard-proven (T-DOC78): `FileGpuLock`
(`rag/gpu_lock.py`) to exclude, and `free_gpu()` / `load_for_mcp()` +
`app.tei_lifecycle.ensure_tei_running` (`app/dashboard/controller.py`, `app/tei_lifecycle.py`) to
evict/reload TEI around a batch with the query path self-healing afterwards. The pilot's default
posture: **serialize for backfill arms; measure co-residency only as a serving-time question**, and
only after Stage 0's measured profile says headroom is real.

### Latency

ESTIMATE, unmeasured: a quantized ~7B VLM describing one page image (~300 output tokens) on this
card should land ~2–10 s/page. At the pilot scale (§3: ~150–250 page-describes) that is minutes of
GPU time either way; the number matters only for the backfill projection in §4, which is therefore
labeled an extrapolation twice over. Stage 0 measures real s/page before §4's projection is treated
as anything better than a bracket.

### Where descriptions land

The designed seam exists and is contract-pinned: `figures.vlm_description TEXT` nullable, always
NULL in V0, written by nobody today ("filled by the V3 VLM enricher" — `contracts/parser.py`;
`migrations/0006_figures_tables.sql`; `DATA-CONTRACTS.md`; `rag/document_store.py`'s put path
already carries the column positionally). A pilot enricher writes through the existing document-store
figure path behind `ParsedDoc` — exactly ARCHITECTURE.md M2's stated V3 extension point.

Two honest scope notes:

- **Tables need no VLM.** `tables.markdown` already persists table content as text
  (`migrations/0006_figures_tables.sql` header) — the unique-information gap §1 measured is
  figure-*shaped* (chart pixels), and any table-content gap would be an indexing decision, not a
  vision one.
- **Serving integration is out of scope here.** Indexing descriptions into retrieval touches
  chunker/embedder paths and re-opens the scoring-protocol question from §1 (which arm do
  vision-served items live in). That is a post-pilot operator decision, not part of this project's
  gate.

## §3 Falsification-style build criteria (pre-committed)

House rule: success/failure thresholds are fixed HERE, before any model is downloaded or any prompt
is written. Post-hoc threshold movement, prompt re-rolling after seeing results, or metric
redefinition kills the pilot's evidentiary value — so this section is written to be quotable against
the eventual outcome.

**Pilot population (fixed):**
- All **5** unreachable items from D1: ver84 Q-GTA-042/043/044 + Q-WAYB-027; GT-WMR Q-WMR-094.
  These are the only ground-truth items in the repo whose answers are *proven* figure-locked.
- **N = 100** additional figure-bearing pages, sampled from `figures` rows stratified chart-vs-
  diagram vs caption-only (exact strata weights recorded in the pilot report when drawn), to get
  off-gold-ground-truth and measure description fidelity on pages nobody authored questions for.

**Stage 0 — gates that must pass before inference counts (each measured, not modeled, per T-DOC15):**

| gate | criterion | fail action |
|---|---|---|
| G0.1 VRAM profile | one of §2's two postures holds under sampled measurement: co-resident with full TEI pair within headroom, or serialized round-trip (evict → batch → reload) completes with serving restored | neither works on this card → project closed without Stage 1 |
| G0.2 per-page latency | measured ≤ 30 s/page across the N=100 sample | above it, even a priority-subset backfill leaves feasibility (§4) → closed |
| G0.3 true-vision audit | re-audit all 5 items fitz-first (`get_text()` over the gold page region), Q-GTA-044-style | denominators shrink to the surviving count; if < 3 survive, the unique-information case falls below any interesting bar → operator review before continuing |

**Stage 1 — description fidelity (per-value scoring, n = every asked value across the 5 items' figure
sets + sampled-page spot checks):**
The VLM describes each rendered page blind to the gold excerpt; an independent judge session checks
each stated value/fact against the PDF (same layered-verification discipline the GT sets used:
openevidence-programme §3).
- **Success: ≥ 80% of asked values verified correct.**
- **Failure: < 80%.** One pre-registered retry is allowed ONLY for infrastructure failure (model
  fails to load, OOM, render error) — never for score disappointment.

**Stage 2 — end-to-end rescue of the unreachable items (n = 5, or G0.3's surviving count):**
Descriptions are injected into a **pilot-local copy** of the index (never production Qdrant/SQLite),
and the original questions rerun through the existing scoring path
(`app/retrieval_eval.py::load_questions` / `score_question`, the D1 harness pattern).
- **Success: ≥ 4/5 items surface their figure-derived answer at rank 1 with a correct extractable
  answer** — i.e., the items D1 proved structurally unreachable become reachable.
- **Failure: ≤ 3/5 → project closed.** Consequences then execute as written: vision items move to
  their own arm or the target gets rescoped (operator picks among the three accounting options in
  openevidence-programme §8), and Q-GTA-044-class extraction gaps route to a parser/chunker-fix
  ticket instead — text-side work, correctly reassigned.

**Anti-goodhart constraints:** both fixtures reported separately, never averaged (programme
constraint 10); one variable changed per arm; thresholds and populations frozen by THIS document;
any deviation is recorded in the pilot report's disagreement register with rationale, and the result
is reported as deviated rather than clean.

## §4 Cost summary

**Pilot GPU-hours (the only spend this ticket asks to authorize):**

| item | estimate | basis |
|---|---|---|
| Page rendering (CPU) | minutes | pymupdf pixmap over ≤ ~250 pages |
| VLM inference | ≈ 150–250 page-describes × ESTIMATE 2–10 s/page ≈ **0.1–0.7 GPU-h** | §3 populations (5 gold items' pages + N=100 sample + Stage-2 reruns) |
| VRAM profiling + TEI evict/reload cycles | adds < 1 GPU-h wall | T-DOC78 machinery does the moving |
| **Pilot total** | **≤ 2 GPU-hours** (budget cap) | sum of the above; serialize on `.gpu.lock` per house rules |

**If-success backfill projection — EXTRAPOLATION, labeled twice:** scaling the unmeasured 2–10 s/page
bracket to all 24,708 figure rows gives ≈ **14–69 GPU-hours**, which is why the projection is staged:
priority papers first (`fixtures/eval/waymo_safety_research_55.json` resolution — the 53-ingested
waymo.com/safety/research set, `docs/PROJECT-STATUS.md` Waymo-priority section), remainder only if
the priority slice demonstrates retrieval value. Both the s/page bracket AND the "all figures are
worth describing" premise are assumptions; neither is measured until the pilot runs.

**Storage impact (arithmetic on an assumed description length):** ~500 chars average per description
× 24,708 rows ≈ **~12MB SQLite growth** (call it tens of MB worst case; tables excluded per §2).
Rendered page caches are discardable intermediates (~100–500KB/page, pilot-scale only).

**Existing machinery reused (named):**

| layer | files/modules |
|---|---|
| Landing seam | `migrations/0006_figures_tables.sql` columns; `contracts/parser.py` `Figure.vlm_description`; `rag/document_store.py` put/get figure paths |
| GPU discipline | `rag/gpu_lock.py` `FileGpuLock`; `app/dashboard/controller.py::free_gpu` / `load_for_mcp`; `app/tei_lifecycle.py::ensure_tei_running` (all T-DOC78) |
| Figure artifacts | MinerU parse-time extraction → `figures.image_path` populated by the RI-32 backfill (no re-parse needed — PRD frames the VLM exactly as this bolt-on, `PRD.md` figure/table-capture ADR) |
| Measurement harness | `app/retrieval_eval.py::load_questions` / `score_question`; `scripts/nb_d1_pool_depth.py` as the detached-measurement template; `scripts/nb_eval_runner.py` dual-fixture pattern |
| Host service | Ollama (already running for summarization; never-auto-started convention respected) |

**New code the pilot would add:** one throwaway enricher script under the `app/exp_*.py`
convention + its report and JSON data under `docs/eval-reports/` and `docs/eval-reports/data/`
(programme constraint 9's non-foundation homes). No foundation paths touched; no config changes; no
service definitions changed. If a future tables-description column is ever wanted, that IS a
`migrations/` diff → foundation-gated, operator sign-off, batched rider (constraint 9) — noted here
so it can't be smuggled later.

## Method notes & disagreement register

Framing accepted as briefed; no disagreement required deviation. Refinements discovered while
scoping, recorded so the delta from the brief is visible:

1. **"The 15% unreachable slice" resolved to exact fractions.** Programme plan §4's shorthand maps
   to 4/27 of verified-84's near-miss population (14.8%) and 5/39 across both fixtures (12.8%);
   this doc cites fractions with denominators throughout rather than the rounded headline.
2. **Tables dropped out of the vision case mid-scoping.** `tables.markdown` already persists table
   content as text (`migrations/0006_figures_tables.sql`) — the unique-information gap is
   figure-shaped only. This *sharpens* the case (a smaller, truer target) rather than weakening it;
   §1's opportunity numbers still cite both row counts for completeness.
3. **Q-GTA-044 discount applied but not statically trusted.** Applied as instructed (floor 5→4),
   then converted into Stage-0 gate G0.3: the pilot re-audits all five items fitz-first, because
   today's true-vision labels are one reviewer's judgment, not a measured invariant.
4. **The load-bearing unknown is named, not smoothed.** Operator-demand prevalence (§1 B2) has zero
   measurement behind it in this repo — no query log exists. Every proxy number is labeled; the
   pilot is partly designed to produce the first demand-side evidence, which is why CONDITIONAL
   CLEAR stops at a bounded pilot instead of a build.
5. **Dependency note for whoever writes the pilot brief:** pymupdf is importable in
   `agent-rag-research` (v1.28.2, deprecated `fitz` alias) but is not an explicit
   `environment.yml` line today; pin it explicitly rather than ride a transitive dependency.

*(Docs obligations — BACKLOG row + PROJECT-STATUS ledger entry per AGENT-PROCEDURES §B — are
deliberately deferred to PR time, same pattern as the NB-D1 report, to keep concurrent lanes'
shared-file ownership conflict-free: programme constraint 6.)*
