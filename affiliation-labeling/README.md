# Affiliation labeling — how to fill this in

**File:** `affiliations_to_label.csv` (166 rows). Opens directly in a spreadsheet. Only the three
`*_fill` columns are yours; everything else is context.

The goal is attributing papers to the organization that **wrote** them, so questions like "what is
in Waymo's stack" answer from Waymo's own research and never from someone else's paper that merely
*uses* Waymo's dataset.

## The three columns to fill

| column | what to put |
|---|---|
| `AFFILIATIONS_fill` | Every institution listed for the authors, semicolon-separated. E.g. `Waymo LLC; UC San Diego`. Leave **blank** if the paper does not state any. |
| `IS_WAYMO_fill` | `yes` / `no` / `unknown` — see below. |
| `NOTES_fill` | Anything odd. Optional. |

## `IS_WAYMO_fill` — and please do use `unknown`

- **`yes`** — at least one author's *employer* is Waymo. An `@waymo.com` email counts.
- **`no`** — you can see the affiliations and none is Waymo.
- **`unknown`** — you **cannot tell from the paper**. Use this freely; it is a real answer, not a
  failure. Cases: the PDF states no affiliations at all, the page is a scan with no readable text,
  the author list has superscript markers but the institution list is missing, or it is genuinely
  ambiguous.

`unknown` and blank are both treated as "no label" and are **excluded from scoring** — they never
count as `no`. This matters: silently treating "couldn't tell" as "not Waymo" would fabricate
precision, which is the exact class of error that made earlier numbers here wrong.

## The one distinction that matters most

A paper that **uses, benchmarks on, or cites** Waymo is **`no`** unless a Waymo employee co-wrote it.

- `no` — "1st Place Solution for Waymo Open Dataset Challenge" (another team competing on Waymo's
  public benchmark)
- `no` — "we evaluate on the Waymo Open Motion Dataset" in the abstract
- `no` — "Waymo Open Dataset" in a keywords/index-terms line
- `yes` — the affiliation block says `Waymo LLC`, or an author's email is `@waymo.com`

Most of the P2 rows below are the first kind. That is expected — they are what we are trying to
stop mislabeling.

## Priority — stop wherever you like, earlier bands are worth more

| band | rows | question it answers |
|---|---|---|
| **P1** | 54 | These are on our authoritative Waymo list, but **no extractor could confirm any of them**. If some are wrong, our "exact" list is not exact. **Highest value.** |
| **P2** | 45 | The heuristic flagged these as Waymo but they are not on the list. Each is either a gap in the list or a genuine false positive. |
| **P3** | 7 | On the list, heuristic missed them. Cheap confirmation. |
| **P4** | 60 | No extractor produced anything and they are not on the list. Sampled from 458 — checking whether we **missed** Waymo papers entirely. |

Finishing only P1 is already a meaningful result.

## Opening a paper

`open_this` is an arXiv abstract URL where one exists (fastest — affiliations are usually on the
abstract page), otherwise an absolute path to the cached PDF. `machine_found` tells you what the
automated extractors saw, purely as a hint — **please judge from the paper, not from that column**,
since the whole point is to catch cases where the machines are wrong.

## When you're done

Save as CSV in place (or tell me another path). I will:
1. score the extractors against your labels, excluding `unknown`/blank;
2. correct `fixtures/waymo/waymo_authored_ids.txt` for any list errors your labels expose;
3. commit your labels as a versioned fixture so this becomes a repeatable regression test rather
   than a one-off.
