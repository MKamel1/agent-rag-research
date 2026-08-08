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
