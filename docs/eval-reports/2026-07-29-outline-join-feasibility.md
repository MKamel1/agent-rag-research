# Outline-to-block join feasibility — Experiment 1 gate step

*2026-07-29. Read-only, no-GPU, no-ingestion investigation per
`docs/PLAN-book-rag-experiments.md` Experiment 1's "prove the join on one book's front matter
first" prerequisite, and §5 item 1 ("Outline→block page join plausibility"). This is the cheapest
possible negative result in that plan — it either clears the way for Experiment 1's real cost
(re-summarizing ~90 chapters and embedding them into a throwaway collection) or stops it here.*

**Reproduce with:** `app/outline_join_probe.py` (read-only probe, throwaway script — see its
docstring). No GPU, no summarizer/embedder calls, connects to `papers.db` with `?mode=ro` only.

```
RAG_CONFIG=/home/omar/ai-projects/research-system-rag-data/config.yaml \
    python -m app.outline_join_probe
```

Full output: every number below was produced by this exact command, not hand-recorded.

---

## Headline result

**The join works, on all 4 outline-bearing books, including front matter.** Title-match rate is
96.8%–98.3% overall per book. Where a title matches at all, the page offset between the outline's
`page_index` and the block that actually carries the title text is **0 for 94–100% of matches**,
with the small remainder being 1–2 isolated single-entry outliers per book (never a spread across
many entries) — this is a **constant offset**, not a variable one. The falsification criterion
("a variable, unpredictable page offset") does not trigger for any of the 4 books.

This is a stronger result than the plan's cautious framing anticipated going in. It does not mean
"no caveats" — see the front-matter section below for the real, but different, failure mode found
there.

---

## Q1 — Does `get_toc()` return usable page indices?

Verified against the actual `pypdfium2` API (not assumed):

- `pdf.get_toc()` yields `PdfBookmark` objects with `.level` (int, 0 = outermost) and a
  `.get_title()` **method** (not a `.title` attribute — this errored on first try).
- The page index is **not** a direct attribute either. It requires resolving a destination
  object: `bookmark.get_dest()` returns a `PdfDest | None` (`None` for a small number of entries
  with no destination — 0 of them in these 4 books), and `dest.get_index()` returns the page
  index. `PdfDest.get_view()` also exists (returns a `(zoom_mode, view_params)` tuple) but is not
  the page index and was not needed.
- **The index is 0-based**, confirmed two ways: (a) the first entry of every book with a "Cover"
  or title-page-shaped first entry resolves to `page_index=0`; (b) `blocks.page`'s own observed
  range starts at 0 and its max equals `len(pdf) - 1` for 3 of 4 books exactly (CI Python: max
  block page 408, `len(pdf)-1=408`; CI Discovery: 455/455; CI ML Econ: 838/838; Elements: max
  block page 283 vs. `len(pdf)-1=288` — the last few pages have no parsed blocks, consistent with
  a blank/near-blank tail, not a different indexing base). `blocks.page` and `get_toc()`'s
  `page_index` are the same 0-based unit.

## Q2 — Do outline page indices line up with `blocks.page`? Constant or variable offset?

Method: for every outline entry, take its significant title words (regex tokens, len≥3, minus a
small stopword list) and search `blocks.page ∈ [page_index−8, page_index+8]` for the page whose
combined block text has the highest word-overlap with the title; accept a match at ≥60% overlap,
record the offset (matched page − outline `page_index`). This is **not** a sample — every outline
entry in every book was checked (223 + 84 + 350 + 378 = 1,035 entries total).

| book | entries | match rate | offset histogram (matched only) | unmatched |
|---|---|---|---|---|
| CI in Python (`f0929288d4f3`) | 223 | 218/223 = 0.978 | `{0: 213, -1: 1, 1: 1, 2: 1, 5: 1, 8: 1}` | 5 |
| Elements of CI (`f6c64e1e8c7d`) | 84 | 82/84 = 0.976 | `{0: 82}` | 2 |
| CI and Discovery in Python (`dfe850b3281a`) | 350 | 344/350 = 0.983 | `{0: 343, 7: 1}` | 6 |
| CI and ML in Econ/Social/Health (`54d6ca71dda9`) | 378 | 366/378 = 0.968 | `{0: 366}` | 12 |

**This is a constant offset (0), not a variable one.** For 2 of 4 books every single matched entry
lands at offset 0. For the other 2, 213/218 and 343/344 matches land at offset 0, with exactly one
outlier entry each landing 5, 7, or 8 pages away (plus one CI-Python entry each at −1, +1, +2 —
plausibly a heading rendered one page either side of a page break, not drift). No book shows
offsets spread across a meaningful fraction of its entries. A 70%-ish match rate with scattered
offsets would have been the "close but not real" case the plan warns against rationalizing past;
that is not what these numbers show.

**A match-rate caveat, stated precisely per CONVENTIONS §14:** the 96.8–98.3% figure is a *lower
bound* on join correctness, not a precise error rate, because the title-word matcher itself has
false negatives. Manually inspected: CI-Python's "Index" entry (`page_index=388`) is flagged
unmatched (0% overlap) — but `blocks` on page 388 *is* the correct index page (block text: `"A"`,
`"“A/B Testing Intuition Busters..."`, alphabetical entries), it simply never contains the literal
word "index" as extractable text, because MinerU didn't emit an "Index" heading block for that
page. Same pattern confirmed for CI-ML-Econ's "Cover"/"Half Title"/"Title Page"/"Copyright
Page"/"Dedication" (all unmatched, all overlap 0.00–0.50) — spot-checked pages 0–5 directly: they
contain the book's title/author/publisher text, not the literal bookmark label. **The page is
right in every spot-checked case; the title-matching heuristic just can't confirm it via exact
words for a subset of decorative front-matter pages.** This means the true join-correctness rate
is higher than the reported match rate, not lower — but this claim is spot-checked on the specific
entries shown above, not proven for all 43 unmatched entries across the corpus, so it is stated as
an observation with its supporting check, not asserted as "always."

## Q3 — Front matter specifically

Front matter (defined per-book as entries before the first `Chapter`/`Part`-marker page, where
one exists) does show a **lower title-match rate** than body content — but the *offset itself*
does not drift; the gap is entirely explained by the false-negative pattern above.

| book | front matter n | front-matter match rate | body match rate | front-matter offsets found |
|---|---|---|---|---|
| CI in Python | 11 | 10/11 = 0.909 | 208/212 = 0.981 | `{0, 5}` (one outlier) |
| CI and Discovery in Python | 9 | 5/9 = 0.556 | 339/341 = 0.994 | `{0, 7}` (one outlier) |
| CI and ML in Econ/Social/Health (manual, no `Chapter`-literal cutoff)† | 8 | 2/8 = 0.25 | matches book-wide rate on remaining entries | `{0}` only — no outliers |
| Elements of CI (manual)† | 3 | 3/3 = 1.0 | matches book-wide rate | `{0}` |

† These two books never print the literal word "chapter"/"part" (CI-ML-Econ uses bare `"N. Title"`
headings; Elements uses topic titles with no numbering), so the script's automatic cutoff
(`_CHAPTER_OR_PART` regex) returns `None` for them — the front-matter boundary shown here was
identified manually from the full outline dump (before "About the Authors"/first numbered chapter
for CI-ML-Econ; before "Statistical and Causal Models" for Elements), not by the reproducible
script. Flagged as manual, not script-reproduced, per the deliverable's reproducibility bar.

**The research doc's specific warning — "page-offset drift concentrates in front
matter/preface pagination" — did not materialize as an offset problem here.** What did
materialize, confirmed by direct block inspection: front matter has more pages whose block text
doesn't literally restate the bookmark's label (Cover, Title Page, Copyright, Dedication, Index —
pages that are typographically distinct rather than textually headed), which lowers the
*title-match* rate without indicating the *page number* is wrong. This is a real, book-specific
weak spot (worst case 25% on CI-ML-Econ) but a different failure mode than the one flagged as the
falsification risk, and it does not touch chapter boundaries (front matter is never itself the
"chapter" unit in the level picked per Q5).

## Q4 — Would the resulting boundaries be plausible?

Chapter units were built by cutting `blocks` at each outline entry's `page_index` for a candidate
level, entirely from data already read (no GPU, no LLM). Word share = unit's word count / book's
total word count.

| book | outline level | unit count | word-share min / median / max | today's size-merge count |
|---|---|---|---|---|
| CI in Python | 0 (Part) | 11 | 0.002 / 0.045 / 0.239 | 26 |
| CI in Python | **1 (Chapter)** | **17** | **0.001 / 0.070 / 0.124** | 26 |
| CI in Python | 2 | 92 | 0.002 / 0.007 / 0.049 | 26 |
| CI in Python | 3 | 88 | 0.001 / 0.006 / 0.074 | 26 |
| Elements of CI | **0** | **18** | **0.001 / 0.042 / 0.262** | 8 |
| Elements of CI | 1 | 58 | 0.002 / 0.013 / 0.079 | 8 |
| CI and Discovery in Python | **0** | **29** | **0.000 / 0.027 / 0.136** | 7 |
| CI and Discovery in Python | 1 | 93 | 0.000 / 0.007 / 0.051 | 7 |
| CI and Discovery in Python | 2 | 166 | 0.000 / 0.004 / 0.055 | 7 |
| CI and ML in Econ/Social/Health | **0** | **42** | **0.000 / 0.023 / 0.080** | 44 |
| CI and ML in Econ/Social/Health | 1 | 153 | 0.001 / 0.005 / 0.047 | 44 |
| CI and ML in Econ/Social/Health | 2 | 164 | 0.000 / 0.002 / 0.061 | 44 |

(Today's size-merge counts reverified live from `summaries` — `WHERE summary_id LIKE
'%:summary:chN'`: 26 / 8 / 7 / 44, matching the task's stated 26/9/7-8/44-45 within the "reverify"
tolerance already flagged there.)

**No candidate unit at any level, for any book, swallows an implausible share of the book.** The
largest single unit anywhere is 26.2% (Elements of CI, level 0 — plausibly its longest chapter,
"Multivariate Causal Models", pages 97–151, not investigated further since it's well under a
"swallows most of the book" threshold). Every other level's max share is ≤24%. This clears Q4's
falsification bar (no "chapter that swallows most of the book") for all 4 books at their
Q5-selected level.

**Bolded rows are the level picked by the Q5 rule below.** Comparing to today's counts: CI-ML-Econ
lands very close (42 vs. 44 — essentially the same granularity). CI-in-Python is coarser (17 vs.
26 — larger, fewer chapters). Elements and CI-Discovery are markedly finer (18 vs. 8, 29 vs. 7 —
roughly 2–4× more, smaller units). This is a real, book-dependent shift in granularity, not a
defect — the outline-derived counts reflect each publisher's actual chapter count, while
size-merge's `_TARGET_CHAPTER_WORDS=5000` heuristic was merging multiple real chapters into one
unit for the shorter-chapter books (Elements, CI-Discovery) and splitting within a chapter for
none of them.

## Q5 — Which outline level is "chapter"?

**A single rule works for all 4 books:** pick the outline level with the most entries matching a
`Chapter|Part|Appendix + <number>` marker (same marker family as
`book_summarizer._CHAPTER_MARKER`); if no level has any such entry, use level 0.

Verified by running this exact rule (`pick_chapter_level()` in the probe script) against all 4
books:

- **CI in Python → level 1.** This book nests `"Chapter 1. ..."` one level under `"Part I. ..."`
  headings, so level 0 is Parts (11 units) and level 1 is the real chapters (17 units,
  including a handful of tiny front-matter subsections like "Prerequisites"/"Acknowledgments" that
  share level 1 with the chapters — harmless, each is <1% word share).
- **Elements of CI → level 0** (no book prints the word "chapter" anywhere in its outline, so the
  rule falls back to level 0 — which manual inspection confirms is correct: level 0 entries are
  literally one per chapter/appendix/bibliography/index, e.g. `"Statistical and Causal Models"`,
  `"Cause-Effect Models"`).
- **CI and Discovery in Python → level 0** (prints `"Chapter N: ..."` at level 0, alongside `"Part
  N: ..."` divider entries at the same level — both correctly picked up as level 0 by the rule).
- **CI and ML in Econ/Social/Health → level 0** (prints bare `"N. Title"`, no literal "chapter"
  word, so the rule falls back to level 0 — manually confirmed correct: level 0 is exactly one
  entry per numbered chapter, 32 numbered chapters + 10 front/back-matter entries = 42).

**One rule, not four book-specific hacks** — but it does have to be book-adaptive in its *output*
(different books pick different levels), because the four books structure their outlines
differently: one nests chapters under parts, the other three don't nest chapters at all but two of
those three never spell out the word "chapter." The fallback-to-level-0 branch does the real work
for 3 of 4 books.

---

## Go/no-go, per book

| book | join works? | offset behaviour | boundaries plausible? | go/no-go for Experiment 1's expensive step |
|---|---|---|---|---|
| CI in Python (`f0929288d4f3`) | Yes, 97.8% match | Constant (0), 1–2 isolated outliers | Yes (17 units, max share 12.4%) | **Go** |
| Elements of CI (`f6c64e1e8c7d`) | Yes, 97.6% match | Constant (0), no outliers | Yes (18 units, max share 26.2%) | **Go** |
| CI and Discovery in Python (`dfe850b3281a`) | Yes, 98.3% match | Constant (0), 1 isolated outlier | Yes (29 units, max share 13.6%) | **Go** |
| CI and ML in Econ/Social/Health (`54d6ca71dda9`) | Yes, 96.8% match | Constant (0), no outliers | Yes (42 units, max share 8.0%) | **Go** |
| Trustworthy OCE (`14b7e283bdcd`) | N/A — 0 outline entries (control, confirmed by `get_toc()`) | N/A | N/A | **Untouched, as designed** — stays on size-merge |

**None of the 4 outline-bearing books hit the falsification criterion.** No variable offset, no
implausible boundary, on any book. The gate does not stop Experiment 1 for any book.

## Recommendation

**Proceed to Experiment 1's real cost** (re-summarize the outline-derived chapters for all 4
outline-bearing books at the Q5-picked level, embed into a throwaway collection, re-score against
the 5-book eval set) — the join-feasibility prerequisite is cleared for all 4, not a subset. This
was the cheap-negative-result step the plan sequenced first specifically so a bad join wouldn't
cost any GPU time to discover; it came back positive instead, so it doesn't change Experiment 1's
scope, only confirms it's safe to spend the budget the plan already sized (order 85–95 chapters to
re-summarize, ~90 vectors to re-embed into a throwaway collection — see the plan's §2 cost
estimate). One thing worth carrying into that step, not re-litigated here: the shift in unit count and
granularity is real and book-specific, not uniform — CI-in-Python goes from 26 to 17 units (fewer,
larger chapters); Elements and CI-Discovery go from 8→18 and 7→29 (markedly more, smaller
chapters); CI-ML-Econ is nearly unchanged, 44→42. That's a real change in what `search_papers`
will return per book, in different directions for different books, and should be visible in
Experiment 1's own report, not just inferred from this gate step.
