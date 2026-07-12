# Phase 0 Results

Per PHASE0-RUNBOOK.md's ethos ("record the numbers... so no decision is asserted, not proven," PRD §9),
every number below is sourced from a specific artifact under `.phase0-data/` (not committed — see
`.gitignore` — but referenced by path for anyone who wants to re-verify).

## Spike 1 — Parse + provenance fidelity

**Status: done. Spike 2 (retrieval quality) has not run yet and is not covered by this document.**

**Decision authority:** made under explicit delegation while the project owner was away; flagged for
their review, not silently merged.

**Sources:** `.phase0-data/spike1-scoring/phase0-results-draft.md` (full reasoning),
`.phase0-data/spike1-scoring/rubric_scorecard.md` (per-dimension data), `round_trip_results.json`,
`grobid_check.md` (same directory), plus direct inspection of `.phase0-data/parser-eval/*/full-batch/`
output.

### Headline numbers — three candidates

| Metric | Docling | MinerU | Marker |
|---|---|---|---|
| Block-anchor round-trip | **100%** (90/90) | 94.4% raw, **100%** after manual audit (90/90) | **100%** (90/90, zero failures) |
| Clears ≥95% gate? | Yes | Yes | Yes |
| Throughput | 1.48 s/page | **0.34 s/page** | 2.54 s/page |
| 15,000-paper backfill (corrected) | ~9.5 days | **~2.2 days** | ~16.4 days |
| Equation blocks (101 papers) | 8,729 | 8,743 | 8,683 |
| Code/algorithm blocks, Code-Heavy papers (20) | 1 | 8 | 3 (unreliable typing, see below) |
| Code/algorithm blocks, corpus-wide (101) | 65 | **123** | 82 |
| Table blocks (101 papers) | 661 | 658 | 647 |
| Table representation | Cell-addressable JSON | HTML parse needed | HTML parse needed |
| OCR fallback | Handled (batch success) | Handled (batch success) | Handled, confirmed at scale: 41.2% of all pages (1,550/3,762) triggered Surya OCR corpus-wide, including correct LaTeX recovery |
| GROBID references | Pass (parser-independent) | same | same |

Round-trip sample: 3 papers x 5 structural categories (Code-Heavy, Math-Heavy, Multi-Column,
Table-Heavy, Scanned-OCR) x ~6 blocks = 90 blocks/parser, equal across all three candidates.

**Gate 1 result: all three parsers clear the >=95% round-trip bar.** Round-trip is therefore not a
discriminator between them — the decision turns on throughput and content-fidelity instead.

**Throughput correction (load-bearing for this decision):** an earlier draft mistakenly reported a
"15k-**page**" backfill estimate (`15,000 x sec/page`). The PRD's `corpus_cap` (§6A/§11) is 15,000
**papers**, and this corpus averages ~37.2 pages/paper (3,762 pages / 101 papers), so the real backfill
is ~37x longer than that earlier number implied. Scaling each parser's measured total-sec by
`15000/101` papers gives the corrected estimates above. PRD line 536 wants the full 15K backfill done
"overnight/over a few days" — **only MinerU's ~2.2 days fits that window**; Docling's ~9.5 days and
Marker's ~16.4 days both miss it by a wide margin.

### Round-trip methodology

- **Ground truth:** `pypdfium2` native text extraction (`get_text_bounded`) over each block's own
  `(page, bbox)` rectangle in the original source PDF — independent of the parser being scored.
- **Comparison:** `rapidfuzz.fuzz.token_set_ratio` on normalized (lowercased, HTML/LaTeX-command-stripped)
  text; success threshold 65/100 (a correctly-anchored block still varies from raw glyph extraction —
  e.g. `\beta` vs. the rendered glyph — while a wrong-region crop reliably scores near 0).
- **Coordinate systems:** Docling ships bottom-left PDF-point bboxes; MinerU ships 0-1000-normalized
  top-left bboxes needing a page-size rescale + y-flip; Marker's origin was empirically determined to be
  top-left (40-block A/B test: 99.9 avg similarity with the y-flip applied vs. 27.8 without) then
  hardcoded and reused.
- **Manual audit (MinerU):** 5 of 90 raw scores fell just under 65 (54.5-62.1), all on
  `equation`/`table` blocks where the parser's LaTeX legitimately diverges token-wise from a raw glyph
  extraction. Manual review of those 5 crops confirmed the bbox correctly points at the right region in
  every case — hence "94.4% raw / 100% after audit."
- **Marker's 90/90:** zero blocks fell below threshold, no manual audit needed.

### New finding: Marker's code/algorithm block-type classifier is unreliable

Beyond low recall (82 `Code` blocks corpus-wide vs. MinerU's 123), direct inspection across the 20
Code-Heavy papers found the same kind of construct classified two different ways by Marker: some
"Algorithm N" constructs decompose cleanly into a `ListGroup` of numbered `ListItem`s (structure
preserved), while others collapse into a single monolithic `Code` block (the whole algorithm body as
one HTML blob, per-step structure lost). Only 3 of Marker's 82 corpus-wide `Code` blocks fall inside the
Code-Heavy category's own 20 papers — most Code-Heavy papers have zero `Code` blocks despite containing
visible algorithm boxes. This is a correctness-shape risk, not just a recall gap: a chunker that keys
off `block_type` would treat the same kind of content differently paper to paper, silently. This corpus
is causal-inference/econometrics with frequent algorithm/pseudocode boxes (not literal source code), so
this dimension is directly relevant.

### Does "tables load-bearing" apply to V0? No.

The runbook's gate language is conditional: pick MinerU or Marker, "add Docling if tables are
load-bearing or its speed wins." Both conditions were checked against the actual V0/V1 design:

- **Docling's speed does not win** — it's 4.3x slower than MinerU (1.48 vs. 0.34 s/page) and ~4.3x
  longer on the corrected 15k-paper backfill.
- **Tables are not load-bearing at the cell-structure level in V0/V1.** Per PRD ADR-13, tables are
  stored as PNG + caption + section context + bbox artifacts, with captions indexed in v1 — table cell
  content is not chunked or embedded in V0. Docling's cell-addressable `table_cells` JSON is real,
  verified quality, but nothing in V0's chunker/retriever path currently consumes cell-level structure.
  All three parsers detect tables at essentially tied volume (647-661), so the caption-indexing path V0
  actually uses is a wash across parsers too.

Neither "add Docling" condition holds for V0. This is a "revisit if" condition for a later phase (v3 VLM
bolt-on, or a decision to chunk table cells directly), not a V0 requirement.

### Replaceability

`Parser` is one of ARCHITECTURE.md's three explicitly-designed real seams (swappable adapter,
principle 4), same tier as `Embedder`/`VectorStore`. ADR-06 names the re-run cost directly: parsing is
idempotent + resumable + cached, so re-runs are cheap. Picking MinerU now does not foreclose adding
Docling or Marker later if a concrete future need materializes (e.g. a v3 VLM wanting Docling's
structured tables) — DocumentStore/VectorIndex are derived+rebuildable from the parse output, so a later
parser change re-runs a batch job, not a redesign. This argues for optimizing the V0 pick for V0's actual,
present constraint (15k-paper backfill throughput) rather than over-weighting a hypothetical V3 need the
architecture already makes cheap to satisfy later.

### Decision: lock MinerU as the sole V0 `Parser` adapter. Do not add Docling or Marker.

1. **Round-trip** clears the gate (94.4% raw / 100% audited, 90/90) — statistically tied with Docling and
   Marker's 100%, not a discriminator.
2. **Throughput is the deciding factor.** MinerU is the only parser whose corrected 15,000-paper backfill
   estimate (~2.2 days) fits PRD line 536's explicit "overnight/over a few days" target. Docling (~9.5
   days) and Marker (~16.4 days) both miss it by roughly a week or more.
3. **Code/algorithm-block recall is best-in-class and this corpus needs it** — 123 corpus-wide vs.
   Docling's 65 and Marker's 82, without Marker's same-construct-classified-two-ways reliability problem.
4. **Equations, tables, reading order, OCR fallback are all a wash** across all three parsers (within ~1%
   of each other on detection counts; all handled the synthetic zero-text-layer stress test).
5. **GROBID references pass regardless** (parser-independent) — doesn't affect the choice.

**Docling: drop, do not keep as secondary/table-fallback.** Neither "add Docling" condition holds for
V0 (see above). Carrying a second parser adapter into V0 for a table-structure advantage the pipeline
doesn't yet use would be speculative complexity the runbook doesn't ask for. Revisit if a future phase
makes structured table JSON load-bearing — Docling is the pre-benchmarked, ready-to-reattach option at
that point, and the `Parser` seam is already built for that swap.

**Marker: drop entirely, not selected as primary or secondary.** It does not win any dimension outright
against MinerU, is the slowest of all three parsers, and introduces a genuinely new risk — the
code/algorithm-block classification inconsistency above — that neither of the other two candidates has.

**Net result: single parser, MinerU, no fallback adapter in V0.** This resolves the runbook's default
instruction ("Pick one parser (MinerU or Marker)") cleanly to MinerU without tripping either of the "add
Docling" conditions. The seam's designed replaceability means this isn't a one-way door if a future
phase's needs change.

### Open item carried forward — NOT done in this pass

The runbook's Spike 1 method step 4 — "Trial the arXiv-LaTeX ingest path on a couple of papers
(best-case anchoring against `.tex`)" — **has not been run.** No artifact in `.phase0-data/` addresses
it. This does not block the parser-lock decision above (it's a separate, optional best-case ingest path
for arXiv papers specifically, not a gate condition), but it is not to be treated as done. Recommended
follow-up before/alongside V0 build start: pick 2-3 arXiv papers with available `.tex` source, confirm
reading order/equations/section anchoring against the `.tex` spans, and record whether it's worth
preferring over MinerU's PDF path for arXiv-sourced papers specifically (per ADR-06's "prefer the
arXiv-LaTeX path for arXiv papers" language).

### Golden fixtures committed

11 papers committed under `fixtures/golden/` (manifest at `fixtures/golden/manifest.json`), reusing the
papers already hand-scored in the round-trip pass — no reason to hand-pick a fresh set:

| Category | Paper IDs |
|---|---|
| Math-Heavy | `2409.02332`, `2410.00903` |
| Code-Heavy | `2604.23107`, `2605.05993` |
| Multi-Column | `2409.01266`, `2504.08836` |
| Table-Heavy | `2506.14329`, `2601.12120` |
| Scanned-OCR (real text layer, visually noisy) | `2602.15916`, `2605.07029` |
| Broken/scanned (quarantine test) | `synthetic_scan_2605.07029` |

Each fixture directory holds the source `paper.pdf` plus `mineru_content_list.json` — MinerU's raw
per-block output (`type`, `text`, `bbox`, `page_idx`, etc.) for that paper, copied from
`.phase0-data/parser-eval/mineru/full-batch/<paper_id>/auto/<paper_id>_content_list.json`. This is
reference data for whoever implements T-B1 (Parser adapter): it's the "ground truth" MinerU produced
during Spike 1's scoring pass, to check a real T-B1 implementation's output against (block count in
range, equations present as LaTeX, every block has page+bbox, etc. — TEST-STRATEGY.md's invariants, not
full-string equality). It is not a `ParsedDoc` fixture — `ParsedDoc` doesn't exist as code yet (T-B1
hasn't started) — so no `ParsedDoc`-shaped file is invented here; T-B1's own test suite writes the actual
assertions once the type exists.

`synthetic_scan_2605.07029.pdf` has zero native PDF text layer on every page (confirmed via
`pypdfium2`'s `get_text_range()` returning `""` for all pages) — the one true image-only scan in the
corpus, meant to exercise the Parser's `PermanentError` -> quarantine path, not the round-trip/anchor
gate.

### Summary for the record

| Gate | Result |
|---|---|
| Block-anchor round-trip >= 95% | **Pass, all three parsers** (Docling 100%, MinerU 100% audited, Marker 100%) |
| GROBID references sane | **Pass** (parser-independent) |
| Pick one parser | **MinerU** |
| Add Docling (tables load-bearing or speed wins)? | **No** — neither condition holds for V0 |
| Add/keep Marker? | **No** — slowest of the three, plus a new code-block classification reliability risk |
| Throughput recorded for 15k backfill | MinerU ~2.2 days corrected estimate — feeds the backfill plan |
| Golden fixtures committed | 11 papers, `fixtures/golden/`, listed above |
| arXiv-LaTeX ingest trial | **Not done** — open follow-up, does not block this decision |

## Spike 2 — Retrieval quality

Not run yet. Not covered by this document.
