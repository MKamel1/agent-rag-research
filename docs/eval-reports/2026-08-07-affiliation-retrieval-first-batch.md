# Affiliation retrieval, measured on the Waymo corpus's first batch — 2026-08-07

**Verdict: the rule-based authorship signal does not work as an authorship signal. Precision 0.000
on the evaluated subset (36 flagged Waymo-authored, 0 actually Waymo-authored).** It is structurally
unable to tell "written by Waymo" from "mentions Waymo", which is the one distinction this corpus
needs it for. The v2 plan's decision to source the Waymo-vs-other split from the enumerated
`fixtures/waymo/waymo_authored_ids.txt` instead of the tagger is therefore correct, and now has
evidence behind it rather than only an argument.

## What was measured

`rag/author_org_tagger.py` deliberately exposes two different signals, and its own docstring says
they must not be conflated:

| function | intended meaning |
|---|---|
| `match_known_orgs(extract_affiliations_rule_based(blocks))` | **authorship** — a Waymo employee wrote this |
| `mentions_orgs(title, abstract)` | **topical** — this paper uses Waymo data |

Both were run read-only over the **134 papers at `stage='done'`** in `waymo/data/papers.db` at the
time of the run, and scored against the 114 enumerated Waymo-authored ids in
`fixtures/waymo/waymo_authored_ids.txt`.

## Results

```
done papers evaluated : 134
ground-truth Waymo ids: 114   (of which already done: 0)

AUTHORSHIP signal : 36
TOPICAL   signal  : 60

authored-by AND mentions : 35
mentions but NOT authored: 25
authored but no mention  :  1     <- the whole "independent signal" claim rests on this one paper

authorship vs ground truth:
  true positives : 0
  false positives: 36
  precision      : 0.000
```

Recall is **not** measurable yet: 0 of the 114 ground-truth papers had been ingested at this point
(Phase A drains v1's broad harvest; the 114 arrive in Phase B2). Precision alone is already
conclusive, and the false positives were confirmed by reading the actual author lists:

| paper | flagged as | actual authors |
|---|---|---|
| `2505.00972` | Waymo | Tongji University, Hong Kong Polytechnic |
| `2404.18464` | Waymo | Baotian He, Yibing Li |
| `2508.00384` | Waymo | Purdue, Toyota |

## Root cause — the extractor's candidate window includes the abstract

`_is_candidate_affiliation_block` (`rag/author_org_tagger.py:21`) accepts any page-0 block that is
front matter (`section_path == ""`) or contains an `@`. On a real parse, front matter is not just
the affiliation lines — it includes the **abstract**. `match_known_orgs` then joins every candidate
block into one string and substring-matches org keywords across the lot.

Traced directly on `2505.00972` — 7 candidate blocks were extracted:

```
[0]..[4]  waymo_in_block=False   (title, authors, the real Tongji/HK-Poly affiliations)
[5]       waymo_in_block=True    len=1091   <- the ABSTRACT
          "...Evaluations using the Waymo Open Motion Dataset demonstrate that our model
           reduces the mean minimum time-to-collision from 1.62 to 1.08 s..."
[6]       waymo_in_block=False
```

The keyword hit comes from the abstract's *use* of the Waymo Open Motion Dataset, not from any
affiliation. So the "authorship" signal is largely re-deriving the topical one: **35 of its 36 hits
also fire `mentions_orgs`**.

## What this does and does not condemn

- **`extract_affiliations_rule_based` + `match_known_orgs` as an authorship classifier: not usable.**
  Any AV paper benchmarking on a Waymo dataset — which is most of this corpus — is a false positive.
- **`mentions_orgs` is fine** at what it claims (a topical signal), and correctly labelled as weaker.
- **The `KNOWN_ORGS` roster and the email-domain path are not the problem.** No false positive here
  matched by email domain; every one came through the keyword-substring path reading abstract text.
  A domain-only match would likely be high-precision, just low-recall.

## Recommended fixes, cheapest first

1. **Exclude the abstract from the candidate window.** The abstract is typically the longest page-0
   front-matter block; affiliation lines are short. A length ceiling, or dropping the block that the
   parser also stored as the paper's `abstract`, would remove the dominant false-positive source at
   near-zero cost. Needs re-measuring against ground truth once Phase B2 has ingested the 114.
2. **Prefer the email-domain signal, treat keyword matches as weak.** Return a confidence rather
   than a bare list, so a downstream filter can require domain-level evidence.
3. **Do not wire this into ingest until precision is re-measured** (backlog `T-ORG1`). Persisting a
   0.000-precision tag into the schema would bake a wrong answer into the corpus.

Until then the Waymo-authored set comes from `fixtures/waymo/waymo_authored_ids.txt` — enumerated
from Waymo's own research index pages, exact by construction, and re-verified current on 2026-08-07.
