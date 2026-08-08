# Plan: affiliation attribution to near-perfect, and general across orgs — 2026-08-08

## Why

The operator's use case is **understanding an organization's technical stack from its own papers**
(currently Waymo; the mechanism must generalize). For that, a false positive is worse than a miss:
attributing another team's architecture to Waymo invents capability that does not exist. The
measured false positives are overwhelmingly *"1st Place Solution for Waymo Open Dataset Challenge"*
papers — other teams competing on Waymo's public benchmark. No keyword matcher reaches zero on those.

Current state, measured over all 1,741 done papers against a corrected 138-id ground truth
(`docs/eval-reports/2026-08-07-affiliation-retrieval-first-batch.md`):

| signal | precision | recall | F1 |
|---|---|---|---|
| block-regex (shipped in T-ORG1) | 0.706 | 0.783 | 0.742 |
| GROBID header | 0.913\* | 0.457 | 0.609 |
| curated enumerated list | **1.000** | **1.000** (within corpus) | **1.000** |

`*` partly circular — see the eval report.

**Requirement: near-zero false positives AND near-zero misses, for any org, in any corpus.**

## The core insight

Two different problems are being conflated, and they need different solutions:

1. **Attribution for a known org that publishes a research index** → this is an *enumeration*
   problem, not a classification problem. Solved exactly by a curated id list. No heuristic needed.
2. **Attribution for an org with no index, or a paper absent from one** → this is a *classification*
   problem, and it is bottlenecked on **extraction**, not on matching. 526 of 1,741 papers (30%)
   yield no affiliation text at all from either the block-regex or GROBID. 23 of the 30 missed
   Waymo papers (77%) are exactly this case. No matching rule can match text that was never extracted.

So: Track A buys exactness now; Track B buys generality. They are complementary, not alternatives.

---

## Track A — curated tier (IN PROGRESS, PR #240)

Make the enumerated list the authoritative signal, and demote the heuristic to *discovery*.

- `AuthorOrgMatch.method` gains `"curated"`, which wins over `email_domain`/`keyword`.
- `AuthorOrgTag.curated_ids_path` points an org at its id list; orgs without one are unaffected.
- Retrieval can demand the authoritative tier, so "what does Waymo's own research say" returns
  **only** curated hits.

**Result for the Waymo stack use case: 0 FP / 0 FN within the corpus, verified — all 138 curated ids
are present and `done`.**

**Generality:** any org that publishes a paper index (Google Research, Meta AI, NVIDIA, DeepMind all
do) gets the same exactness for the cost of enumerating it once. That is a real cost, and it is why
Track A alone is not sufficient.

### A2 — keep the curated list honest (small, do next)
- Source the 22 outstanding Group C papers (`docs/WAYMO-RESEARCH-PAPERS-NEEDED.md` §4 — operator
  action) and map them in.
- Re-run the Task-5-Step-1 re-fetch gate periodically; Waymo publishes continuously and a stale list
  silently becomes a recall bug.
- Record *provenance* per curated id (which index page, fetched when), so staleness is visible.

---

## Track B — fix extraction so the heuristic generalizes

This is where the LLM extractor earns its place, and it is the answer to "scalable for other
research papers": `OllamaSummarizer.extract_affiliations(first_page_text) -> list[str]`
(`rag/summarizer.py:253`) is **org-agnostic by construction** — it returns whatever affiliations a
paper states, and the existing cheap `match_known_orgs` step then handles *any* org in `KNOWN_ORGS`.
Improving extraction lifts every org at once, including ones added years from now.

It shipped 2026-08-05 and **has never been compared against the alternatives.** That is the gap.

### B1 — characterise the failures (½ day)
Cluster the 526 `no_data` papers by *why* extraction failed: affiliation in a footnote, two-column
layout, scanned/image-only page, non-standard LaTeX template, affiliation on page 2. Sample ~40 and
read them. **Do not skip this** — if most failures are image-only PDFs, an LLM over extracted text
cannot help either, and the honest answer is "OCR first, or don't".

### B2 — measure the LLM extractor where it matters (1 day)
Run it **only on the 526 `no_data` papers plus the 30 known misses** — not the whole corpus. Targeted
because it is GPU-bound and serialised behind the shared `.gpu.lock`; at ~5s/paper that is ~45 min,
versus ~2.5h for a full sweep that would mostly re-confirm cases GROBID already handles.

Report, against the corrected 138-id ground truth:
- extraction success rate on `no_data` (does it produce affiliation text where nothing else did?)
- downstream precision/recall when its output is fed to `match_known_orgs`
- disagreement analysis vs GROBID where both produced output

### B3 — decision gate (explicit, so this cannot drift)
Adopt the LLM extractor as a **fallback tier** (`method: "llm"`, ranked below `curated` and
`email_domain`, above `keyword`) only if, on the targeted set:
- it lifts recall by **≥10 percentage points**, and
- its own precision is **≥0.85**.

If it fails either bar, record the negative result in an eval report and stop. A shipped-but-unused
extractor with a measured verdict is a better outcome than a third mediocre signal — the GROBID
cascade is precedent: it looked excellent on a small sample and was withdrawn on the full run.

### B4 — cascade, only if B3 passes
`curated` → `email_domain` → `llm` → `keyword`, first hit wins, method recorded. Re-measure the full
stack end to end. **Do not assume the cascade beats its parts** — measured at the real base rate,
the GROBID cascade scored *worse* (F1 0.649) than the plain regex (0.742) it was meant to improve.

---

---

## Track V — validate the ground truth itself (STANDING GATE, not a one-off)

**Added 2026-08-08 after the operator asked whether the perfect score was a test-set artifact. It
was.** The curated tier *reads* `fixtures/waymo/waymo_authored_ids.txt`; the ground truth *is* that
file. Measuring one against the other is a tautology — 1.000/1.000 is arithmetic, not evidence, and
it must never again be quoted as validation of anything.

A curated list is only as good as its curation, so it needs its own independent audit. The audit
must use evidence that did **not** put the paper on the list.

### V1 — the audit, run whenever the list changes
For every curated id, classify the independent evidence:

| bucket | meaning | action |
|---|---|---|
| confirmed | an extractor independently found the org (email domain / org name) | none |
| **contradicted** | an extractor read the affiliations and found no such org | **investigate every one** |
| unverifiable | nothing could extract affiliations at all | count it, never call it confirmed |

Run 2026-08-08 over the 138 Waymo ids: **63 confirmed, 21 contradicted, 54 unverifiable.** All 21
contradicted were investigated and cleared — they are EMMA, Block-NeRF, SceneDiffuser++, StarNet and
similar, i.e. extractor failures, not list errors. **54 unverifiable is the honest residual**, and it
is the same 30% extraction floor Track B attacks. It is not evidence of correctness; it is absence
of evidence.

### V2 — the completeness direction
Assert the converse: **no paper carrying an org's email domain may be absent from that org's curated
list.** Run 2026-08-08: 50 papers had a `@waymo.com` email, 0 were missing. This is the check that
originally caught the list being 114 instead of 138, so it earns a permanent place.

### V3 — trust the tooling last
Two measurement bugs were found in one day, both of which corrupted reported numbers:
- a fuzzy title matcher that accepted a paper titled `"9"` (a failed parse) because `"9"` is a
  substring of almost anything;
- an email parser that dropped `&lt;user@waymo.com&gt;` because GROBID HTML-escapes some addresses,
  so `split("@")[-1]` produced `waymo.com&gt;` and failed the domain test. This understated GROBID
  in every figure quoted before 2026-08-08.

So: before believing any surprising score, re-derive one row of it by hand. A result that looks
excellent is a reason to check the harness, not to ship.

## Non-negotiables (learned the hard way this week)

1. **Always measure at the real base rate.** GROBID showed precision 1.000 on a 36%-positive sample
   and 0.652 on the true 6.5% corpus. Any number from a balanced sample is inadmissible.
2. **Suspect the ground truth before the classifier.** Correcting 114 → 138 ids raised precision
   0.569 → 0.706 with *no code change*. Every residual false positive gets adjudicated as
   "genuinely wrong" vs "another ground-truth gap" before it is called an error.
3. **Never persist a verdict without its method.** Already enforced by `AuthorOrgMatch.method`.
4. **`rag/` stays corpus-agnostic.** Curated paths hang off `KNOWN_ORGS`, never hardcoded in
   pipeline code.

## Sequencing

| step | effort | unblocks |
|---|---|---|
| A (curated tier) | DONE — T-ORG3, PR #240 | the Waymo-stack use case, exactly |
| **V1/V2 (validate the ground truth)** | **done once; now a standing gate** | **the right to trust any score at all** |
| A2 (complete + provenance the list) | small | stops silent recall decay |
| B1 (characterise failures) | ½ day | tells us whether B2 is worth it at all |
| B2 (measure LLM on failures) | 1 day | the decision |
| B3/B4 (adopt + cascade) | 1 day | generality for orgs with no index |

Track A already satisfies the stated requirement for Waymo. Track B is what makes it work for the
next organization without hand-curating a list first — and B1 is deliberately a gate, not a
formality, because the LLM cannot recover affiliations from a page whose text was never extracted.
