# Affiliation retrieval accuracy, measured against AI-labelled ground truth — 2026-08-07

**Two findings, the second larger than the first:**

1. **The authorship signal is not usable: precision 0.043** (2 true positives against 44 false
   positives). It cannot tell "written by Waymo" from "mentions Waymo".
2. **For 53% of papers the affiliation evidence was never extracted at all** — no institution name
   and no email in the front matter the parser captured. That caps what *any* affiliation method can
   achieve, including the fix recommended below, and is a parser problem rather than a matching one.

The v2 plan's decision to source the Waymo-vs-other split from the enumerated
`fixtures/waymo/waymo_authored_ids.txt` instead of the tagger is therefore correct, and now rests on
measurement rather than argument.

> **Supersedes the earlier draft of this report.** That version scored against the 114-id list, of
> which **0 papers had been ingested**, so it could report precision only — recall and false
> negatives were unmeasurable, and its "false positives" really meant "not on the list". This
> version builds ground truth from each paper's own source text, so FP *and* FN are both measured.

## Method

Ground truth is per-paper, built by three independent AI labellers reading **only the paper's own
front-matter affiliation region** — with the abstract removed, since the abstract is precisely what
contaminates the tagger and must not be allowed to contaminate the reference labels either. Labellers
were **not shown the tagger's prediction**, so labels cannot be anchored to the thing being measured.

The instruction they scored against: a paper counts as Waymo-affiliated only if Waymo appears as an
author's *employer* or an author has an `@waymo.com` address. "Waymo Open Dataset", "we compare
against Waymo", or Waymo in an index-terms line are explicitly **not** affiliations.

Sampling was stratified over the **370 papers at `stage='done'`**:

| tier | what | n | purpose |
|---|---|---|---|
| 1 | every paper the tagger predicted Waymo-authored | 80 (all labelled) | exact TP / FP |
| 2 | tagger said no, but "waymo" in the affiliation region | 0 | empty *by construction* — the tagger reads a superset of this region, so it cannot miss a mention it can see |
| 3 | random sample of the unflagged remainder | 40 of 290 | bounds false negatives in the silent majority |

Labels of `unclear` are **excluded from the metrics** rather than being forced into a bucket — the
conservative choice, and the reason the denominators below are smaller than the tier sizes.

## Results

```
CONFUSION MATRIX (predicted-positive side exhaustive)
  TRUE POSITIVES  :  2
  FALSE POSITIVES : 44
  unclear         : 34      excluded

NEGATIVE SAMPLE (40 of 290)
  TRUE NEGATIVES  : 24
  FALSE NEGATIVES :  0
  unclear         : 16      excluded

PRECISION = 2/46 = 0.043
FN rate   = 0/24 = 0.000
```

**Precision 0.043.** Of 46 decided predictions, 44 are wrong.

**No false negatives found**, but this is a weaker result than it looks and should not be quoted as
"recall ≈ 1.0": it rests on **24 decided negatives**, because 16 of the 40 sampled were `unclear`.
It does establish that the tagger is not silently missing large numbers of Waymo papers — its
failure mode is over-firing, not under-firing.

### Why the 44 false positives fired

| cause | n |
|---|---|
| no "waymo" anywhere in the affiliation region — the keyword can only have come from the **abstract** | 27 |
| "waymo" present in region but not as an affiliation (e.g. "Waymo Open Dataset" in an index-terms line) | 17 |

Traced end-to-end on `2505.00972` (authors: Tongji University, Hong Kong Polytechnic). Its 7
candidate blocks:

```
[0]..[4]  waymo_in_block=False   title, authors, the real Tongji / HK-Poly affiliations
[5]       waymo_in_block=True    len=1091   <- the ABSTRACT
          "...Evaluations using the Waymo Open Motion Dataset demonstrate that our model
           reduces the mean minimum time-to-collision from 1.62 to 1.08 s..."
[6]       waymo_in_block=False
```

`_is_candidate_affiliation_block` (`rag/author_org_tagger.py:21`) accepts any page-0 block that is
front matter (`section_path == ""`) or contains `@`. On a real parse that includes the abstract.
`match_known_orgs` then joins every candidate into one string and substring-matches, so a paper that
merely *benchmarks on* a Waymo dataset is indistinguishable from one Waymo wrote.

### The two true positives

| paper | evidence |
|---|---|
| `2604.03827` | affiliation line reads "Waymo LLC"; all five authors carry `@waymo.com` emails |
| `2605.22997` | "1Waymo LLC 2UC San Diego", emails `{ylzou, ywli}@waymo.com` |

Both carry a `waymo.com` email. Across all 370 done papers, exactly **2** have one.

## The larger finding: the evidence is usually missing

Measured over the 120 labelled records:

| | n | share |
|---|---|---|
| no institution-like word in the affiliation region | 65 | **54%** |
| no email address in the region | 97 | **81%** |
| **neither institution nor email** | **64** | **53%** |

This is what drove 50 of 120 labels to `unclear`: the labellers repeatedly found author names with
superscript markers (`Yao¹, Bouzidi¹, Goehring¹, Reichardt²`) and **no affiliation list captured at
all**. For those papers no matching rule can succeed, because the text it would match against was
never extracted. This is an extraction/parser gap, and it bounds every option below.

## Recommended fixes, cheapest first

1. **Match on email domain, not keyword substring.** On this sample a domain-only rule flags exactly
   2 papers: **2 correct, 0 wrong, 0 missed** — precision 1.000 where the current rule scores 0.043.
   The obvious caveat is recall: 81% of regions carry no email, so domain-only would be
   high-precision and unknown-recall on the wider corpus.
2. **Exclude the abstract from the candidate window.** Removes the dominant false-positive source
   (27 of 44) at near-zero cost. The abstract is identifiable — it is already stored separately in
   `papers.abstract`.
3. **Fix the extraction gap before trusting any recall number** (the 53% above). Until affiliation
   text is reliably captured, a high-precision rule will simply be silent on half the corpus.
4. **Do not wire any of this into ingest until precision *and* recall are re-measured** — backlog
   `T-ORG1`, now blocked by `T-ORG2`. Persisting a 0.043-precision tag would bake a wrong answer into
   the schema.

## Threats to validity, stated plainly

- **Recall is an estimate, not a measurement.** 24 decided negatives out of a 290-paper population.
- **Labeller inconsistency on empty regions.** Batch A treated "no affiliation text at all" as
  `unclear`; batch B called some of the same shape `false` at low confidence. Because `unclear` is
  excluded and those records contain no Waymo text either way, this cannot manufacture a false
  positive or hide a false negative — but it does mean the `unclear`/`false` split is softer than
  the TP/FP split.
- **The done set is not the target corpus.** These 370 papers come from v1's broad harvest, not from
  the 114 Waymo-authored ids (still uningested at the time of the run — they arrive in Phase B2).
  Precision measured here should hold, but recall must be re-measured once the known-positive
  population is actually in the corpus.

## Reproducing

Ground-truth labels and the scoring harness are throwaway job-scratch artifacts, not committed. The
method is: rebuild the stratified test set from `ingest_state` + `blocks` with the abstract removed,
label tiers 1 and 3 blind, then score with `unclear` excluded. The two true positives
(`2604.03827`, `2605.22997`) and the 2-of-370 `waymo.com`-email count are the anchors any re-run
should reproduce.

---

# ADDENDUM 2026-08-08 — the ground truth was the problem, not (only) the classifier

Everything above measured against `fixtures/waymo/waymo_authored_ids.txt` when it held **114 ids**.
That file was Group A only — the Waymo papers with an *arXiv link*. Groups B (15) and C (23) are
equally Waymo's own published research, listed on waymo.com by DOI or direct PDF, and they entered
the corpus through the operator's drop-in delivery under `local:<sha256>` ids. **They were never
added to the ground truth, so a classifier that correctly identified them was scored as wrong.**

The tell: 14 of GROBID's 24 "false positives" carried an author `@waymo.com` email in the parsed
header. A paper written by someone with a Waymo email is a Waymo paper. That is a broken
measurement, not a broken classifier.

## Correcting it, in two evidence-based steps

1. **Group B/C title-matched to corpus ids** (+16). Fuzzy title match against `papers.title`, then
   every borderline case adjudicated by reading the actual titles. Three were **rejected**: `B7`
   (an IWAI poster fuzzy-matching a different arXiv paper), `C6` ("56.7 Million Miles" vs the
   corpus's "7.1 Million Miles" — different papers), and `B13`, which matched a paper whose title
   is literally `"9"` — a failed PDF parse that my containment heuristic accepted because `"9"` is
   a substring of almost anything. That was a bug in the matcher, fixed by requiring real length on
   both sides before allowing a containment boost.
2. **+8 more on conclusive evidence**: papers where GROBID parsed an author `@waymo.com` email out
   of the header. Includes `2604.03827` ("Waymo LLC", five `@waymo.com` addresses) and `2605.22997`,
   both hand-verified earlier in this report as true positives that the 114-id list did not contain.

Ground truth: **114 → 138**.

## What that did to the numbers — with no classifier change at all

| rule | GT=114 | GT=130 | GT=138 |
|---|---|---|---|
| block-regex (what T-ORG1 ships) | 0.569 / 0.763 | 0.654 / 0.769 | **0.706 / 0.783** (F1 0.742) |
| GROBID alone | 0.652 / 0.395 | 0.797 / 0.423 | 0.913 / 0.457 |
| GROBID email-domain only | 0.720 / 0.316 | 0.840 / 0.323 | — |

Precision rose **0.569 → 0.706** purely by fixing what we were measuring against.

**Circularity warning, stated plainly:** the +8 were identified *by* GROBID's email signal, so
GROBID's own 0.913 at GT=138 is partly self-referential and must not be quoted as an independent
result. The regex figure is not contaminated that way — regex and GROBID are independent signals,
and regex never saw the evidence used to extend the ground truth.

## GROBID does not help — recommendation withdrawn

An earlier draft of this work recommended a GROBID cascade on the strength of a 314-paper sample
where it produced **zero false positives** (precision 1.000). Run over the full 1,741 papers it
produced 24, and precision fell to 0.652. The sample had a 36% positive rate against the corpus's
real 6.5% — precision depends on class balance, and the small sample was flattering. Measured at
the real base rate:

| rule | prec | rec | F1 |
|---|---|---|---|
| regex alone | 0.706 | 0.783 | **0.742** |
| GROBID alone | 0.913* | 0.457 | 0.609 |
| union | 0.704 | 0.812 | 0.754 |
| cascade (GROBID vetoes when it has data) | 0.649 | 0.649 | 0.649 |

`*` circular, see above. **The cascade scores worse than what already ships.** T-ORG1 keeps the
regex signal. GROBID's value here was diagnostic — it found the ground-truth gap — not predictive.

## Near-perfect was not reached, and here is what stands in the way

Best honest F1 is **0.742**. The residue after all corrections: **45 false positives** with no Waymo
email evidence, and **30 false negatives**.

- The FN floor is an **extraction** problem, not a matching one: 53% of papers yield no institution
  name and no email at all from the parser, so no rule can match what was never extracted.
- The remaining FPs need per-paper adjudication to know whether they are genuine errors or *further*
  ground-truth gaps. Every round of this so far has found more gaps, so the current 0.706 should
  still be read as a **lower bound**.

Reaching near-perfect means fixing extraction (GROBID `processFulltextDocument`, or the already-
shipped-but-never-compared `OllamaSummarizer.extract_affiliations`) and completing the ground truth
— not tuning the matcher, which is now the best-performing part of the system.

---

# ADDENDUM 2 — 2026-08-08, corrected measurement harness

## A parser bug in my own tooling, and its real size

GROBID HTML-escapes some addresses as `&lt;user@waymo.com&gt;`. The sweep did
`email.split("@")[-1]`, producing `waymo.com&gt;`, which failed `endswith("waymo.com")` — so valid
Waymo hits were silently discarded. Caught on EMMA (`2410.23262`), where GROBID *had* extracted
`tanmingxing@waymo.com` and the harness reported "no Waymo".

Re-ran the full 1,741-paper sweep with entity-aware parsing. **Honest impact: small.** Exactly three
papers changed verdict (`2410.23262`, `2510.26125` → `domain`; `2605.20390` `org` → `domain`).
GROBID moved from TP=63/FP=6 to TP=64/FP=7. The bug was real and worth fixing, but it was not
distorting the conclusions — stated plainly here rather than left as "understated by an unknown
amount".

## A scope hole in the completeness check (V2)

The first V2 run checked only `domain` evidence and reported "0 missing". Re-run over `domain` **or**
`org` evidence, **7** papers with GROBID Waymo evidence were absent from the curated list. Two carried
an author `@waymo.com` address — conclusive — and were added: `2510.26125` (WOD-E2E) and `2605.20390`
(STELLAR). **Ground truth 138 → 140.**

The other five were **not** added. An `org`-only hit is not conclusive: GROBID can lift
"Waymo Open Motion Dataset" out of a title into an `orgName` field, which would make a paper *about*
Waymo's dataset look Waymo-authored — the exact confusion this whole effort exists to prevent. All
five are queued in the operator labeling sheet (`affiliation-labeling/`) for a human verdict instead.

**V2 is amended: the completeness check must consider every evidence channel, not just the
strongest one.** A check with a narrower scope than the thing it audits will report a clean bill of
health it has not earned.

## Current honest numbers

Corrected harness, corrected 140-id ground truth, all 1,741 done papers:

| signal | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|
| block-regex (shipped in T-ORG1) | 109 | 44 | 31 | **0.712** | **0.779** | **0.744** |
| GROBID header | 66 | 5 | 74 | 0.930\* | 0.471 | 0.626 |

`*` **circular** — 10 of the 140 ground-truth ids were added on GROBID's own email evidence. Not an
independent result and must not be quoted as one.

The regex figure is the trustworthy one: it never sees GROBID's output, so no ground-truth id was
added on evidence it produced.

## What is still unresolved

- **54 curated ids remain unverifiable** — no extractor can read their affiliations, so the
  authoritative list rests partly on unaudited curation. This is P1 of the labeling sheet.
- **Precision is still a lower bound.** Three successive rounds of ground-truth correction
  (114 → 130 → 138 → 140) each raised it with no classifier change. There is no reason to believe
  the fourth round would find nothing.
- **526 papers (30%) yield no affiliation text at all.** Until that is fixed, recall has a hard
  ceiling no matching rule can lift — Track B of
  `docs/superpowers/plans/2026-08-08-affiliation-accuracy-to-near-perfect.md`.
