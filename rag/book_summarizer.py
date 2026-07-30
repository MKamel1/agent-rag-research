"""Map-reduce summarization for doc_type="book" (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

A book's markdown is 10-50x a paper's and cannot go through one `summarize()` call (the real
adapter's num_ctx ceiling truncates it to noise). `_split_chapters` detects chapters by trying
explicit chapter/part/appendix markers first (accepted only if plausible per the count and
word-share guards), falling back to size-based merging at `_TARGET_CHAPTER_WORDS` when markers
aren't plausible, and windowing over fixed-size blocks only when the document parser leaves no
usable heading structure at all. Each chapter is then summarized (map, `kind="book"`), and the
joined chapter summaries are summarized once more (reduce, `kind="book_overview"`) into one
overview + table of contents. Chapter summaries are RETURNED, not discarded -- the orchestrator
persists and embeds them as routing units (ARCHITECTURE §M7 search_papers).

Takes any `Summarizer` as an argument (accept-dependencies principle) -- the GPU lock, eviction
hooks, retry taxonomy all stay the injected summarizer's concern, unchanged.
"""

import re
from typing import NamedTuple

from contracts.document_store import ChapterSummary
from contracts.errors import PermanentError
from contracts.parser import ParsedDoc
from contracts.provenance import Block

# ponytail: fixed thresholds, not adaptive. _MAX_CHAPTER_WORDS stays under the real adapter's
# truncation point (_NUM_CTX_CEILING 16384 tok / 2.2 tok-per-word ~= 7400 words) so a chapter is
# summarized whole, not silently truncated; retune both together if the ceiling moves.
_MAX_CHAPTER_WORDS = 6000
_FALLBACK_WINDOW_BLOCKS = 150  # flat/scanned books with no usable section structure

# T-DOC82: the parser emits real books as a FLAT heading list (measured: 0 blocks with " > "
# across a 2,520-block book, vs 113 on a comparable arXiv paper), so `_top_level` collapses
# nothing and every heading used to become its own "chapter" -- 530 chapters for 535 chunks. Two
# strategies now run in order; see the spec for the measurements behind each threshold.
# `[a-z]\b` (with IGNORECASE) covers letter appendices -- "Appendix A Proofs". It cannot
# over-match a word like "Part of the story": one letter must be followed by a word boundary,
# and "o" in "of" is not.
_CHAPTER_KEYWORD_MARKER = re.compile(
    r"^\s*(?:chapter|part|appendix)\s+"
    r"(?:\d+|[ivxlcdm]+|[a-z]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)
# T-DOC87: the bare "N. Title" alternative used to fire unconditionally on ANY numbered heading.
# The parser's layout model sometimes classifies a numbered list ITEM in body prose as a heading
# (e.g. "1. https://freakonometrics.hypotheses.org/52776" -- a hyperlinked list entry, styled like
# a heading in the source PDF) -- measured against the live corpus: 44/44 of this alternative's
# matches across the two affected books were exactly this, 0/5 books had a single true positive.
#
# Discriminator: a bare "N. Title" heading is trusted as a chapter marker only when EVERY bare-
# numbered heading in the document, taken together in reading order and excluding anything already
# matched by the keyword alternative above, forms the single sequence 1, 2, 3, ..., k with no gaps
# and no repeats -- the numbering a book's own chapters actually have. A numbered list restating
# steps in body prose resets to 1 for each separate list (measured, Econ/Social/Health: the bare
# matches read [1,2, 1,2,...,10, 1,2,...,10, ...] -- two independent 10-step algorithm walk-
# throughs, never one running count across the book) or starts mid-sequence (Discovery in Python's
# sole bare match starts at 3, with nothing numbered 1 or 2 anywhere near it). Position/block-type
# were considered and rejected: the parser adapter already collapses the "is this a heading"
# decision to a single flag before this module ever sees the block (rag/parser.py's `text_level`),
# so nothing about a Block's `type` or position distinguishes a mis-tagged list item from a real
# heading -- only the numbering pattern across the WHOLE document does.
#
# Known ceiling: a book whose ONLY marker-worthy heading anywhere is a single, coincidentally
# 1..N sequential body-prose list (no other bare-number or keyword heading in the entire book)
# would still slip through this check alone -- not observed in this 5-book corpus. In practice the
# word-share and duplicate-title guards below catch most such cases anyway, because the rest of
# the book then piles into one lopsided front-matter unit around the "chapters" a fluke list
# produced.
_BARE_NUMBER_MARKER = re.compile(r"^\s*(\d+)\.\s+\S")
# ponytail: fixed thresholds tuned against one measured 144k-word book, not adaptive. The guard
# band is what stops a book that merely *mentions* "Chapter 3" from producing 2 lopsided units.
_TARGET_CHAPTER_WORDS = 5000
_MIN_MARKER_UNITS = 3
_MAX_MARKER_UNITS = 60
_MAX_UNIT_WORD_SHARE = 0.5

# T-DOC85: `_merge_to_target` used to title each unit by its FIRST heading group, which is
# arbitrary with respect to the unit's content -- the verified re-ingest of a 144k-word book
# produced "Assign", "See Also", "F", and "\* and : Operators" as chapter titles, and those
# strings are what `search_papers` returns as the routing label an agent picks a chapter by. A
# merged unit contains ~10 heading groups, so the fix is to rank them, not to invent a title.
# Deliberately structural, with no word blocklist: the T-DOC82 spec rejected a front-matter
# blocklist because heading names vary per publisher and the list would be endless. Scoring by
# total content characters (not word count) is what ranks "Regularized Regression" over
# "See Also" -- both are two words.
_MIN_TITLE_SCORE = 8  # "See Also" scores 7 and is rejected outright when nothing better exists
_MAX_TITLE_CHARS = 80  # longer than this is a misparsed paragraph, not a heading
_MAX_TITLE_PUNCT_SHARE = 0.15
_TITLE_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")


def _title_score(heading: str) -> int:
    """Total content characters in a heading, or 0 if it is unusable as a routing label.

    0 means "do not use this" -- callers treat it as a hard reject, not a low rank.
    """
    text = heading.strip()
    if not text or len(text) > _MAX_TITLE_CHARS:
        return 0
    punct = sum(1 for c in text if not c.isalnum() and not c.isspace())
    if punct / len(text) > _MAX_TITLE_PUNCT_SHARE:
        return 0
    score = sum(len(m.group()) for m in _TITLE_WORD.finditer(text))
    return score if score >= _MIN_TITLE_SCORE else 0


def _best_heading(headings: list[str]) -> str:
    """The highest-scoring usable heading, earliest on a tie; "" when none is usable."""
    best, best_score = "", 0
    for heading in headings:
        score = _title_score(heading)
        if score > best_score:
            best, best_score = heading.strip(), score
    return best


def _top_level(section_path: str) -> str:
    return section_path.split(" > ", 1)[0]  # separator per rag/parser.py's section-stack join


def _words(blocks: list[Block]) -> int:
    return sum(len(b.text.split()) for b in blocks)


def _heading_groups(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    """Consecutive blocks sharing a top-level section_path, in reading order."""
    groups: list[tuple[str, list[Block]]] = []
    for block in parsed.blocks:
        top = _top_level(block.section_path)
        if groups and groups[-1][0] == top:
            groups[-1][1].append(block)
        else:
            groups.append((top, [block]))
    return groups


def _bare_numbers_are_sequential(groups: list[tuple[str, list[Block]]]) -> bool:
    """True iff every bare "N. Title" heading not already claimed by the keyword alternative,
    taken in reading order, forms exactly 1, 2, 3, ..., k -- see `_BARE_NUMBER_MARKER`'s comment
    above for why this is what separates real bare-numbered chapters from numbered list items."""
    numbers = [
        int(match.group(1))
        for title, _ in groups
        if not _CHAPTER_KEYWORD_MARKER.match(title) and (match := _BARE_NUMBER_MARKER.match(title))
    ]
    return bool(numbers) and numbers == list(range(1, len(numbers) + 1))


def _split_by_markers(
    groups: list[tuple[str, list[Block]]],
) -> list[tuple[str, list[Block]]] | None:
    """Strategy A. Returns None when the split isn't plausible, so the caller falls back."""
    bare_numbers_ok = _bare_numbers_are_sequential(groups)
    units: list[tuple[str, list[Block]]] = []
    for title, blocks in groups:
        is_marker = bool(_CHAPTER_KEYWORD_MARKER.match(title)) or (
            bare_numbers_ok and bool(_BARE_NUMBER_MARKER.match(title))
        )
        if is_marker:
            units.append((title, list(blocks)))
        elif units:
            units[-1][1].extend(blocks)
        else:
            units.append(("", list(blocks)))  # front matter, before the first marker
    titled = [title for title, _ in units if title]
    if len(titled) < _MIN_MARKER_UNITS:
        return None
    if len(units) > _MAX_MARKER_UNITS:
        return None
    total = sum(_words(blocks) for _, blocks in units)
    if total and max(_words(blocks) for _, blocks in units) / total > _MAX_UNIT_WORD_SHARE:
        return None
    if len(titled) != len(set(titled)):
        # T-DOC87: two matched markers sharing a title (e.g. a book's own table of contents
        # repeating "Part 2: Causal Inference" as a heading ahead of the real divider) aren't
        # distinct, addressable chapters -- an agent selecting by label can't tell them apart, so
        # this split is no more trustworthy than the word-share/count guards above and gets the
        # same treatment: reject the whole strategy, let the caller fall back to size-merging.
        return None
    return units


def _merge_to_target(groups: list[tuple[str, list[Block]]]) -> list[tuple[str, list[Block]]]:
    """Strategy B: accumulate consecutive heading groups until ~_TARGET_CHAPTER_WORDS.

    T-DOC85: the unit's title is the best-scoring of ALL headings merged into it (`_best_heading`),
    not the first one -- see that function. Still independent of any particular book's formatting,
    which is why B remains the safe general path.
    """
    units: list[list[Block]] = []
    headings: list[list[str]] = []
    for title, blocks in groups:
        if units and _words(units[-1]) < _TARGET_CHAPTER_WORDS:
            units[-1].extend(blocks)
            headings[-1].append(title)
        else:
            units.append(list(blocks))
            headings.append([title])
    if len(units) > 1 and _words(units[-1]) < _TARGET_CHAPTER_WORDS // 2:
        tail = units.pop()
        tail_headings = headings.pop()
        units[-1].extend(tail)
        headings[-1].extend(tail_headings)
    return [(_best_heading(h), blocks) for h, blocks in zip(headings, units)]


def _split_chapters(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    groups = _heading_groups(parsed)
    if len(groups) <= 1:
        # No usable heading structure (flat/scanned). Window it, but keep the single group's
        # title rather than dropping it to "" (T-DOC82 deferred-minor fix) -- gated through
        # `_best_heading` same as every other strategy, so a junk single heading (e.g. a scanned
        # book's one OCR-garbled heading) becomes "" and reaches the `summarize_book` LLM
        # fallback instead of labelling every window with the junk (latent-only: no Task-8 book
        # takes this path).
        title = _best_heading([groups[0][0]]) if groups else ""
        blocks = parsed.blocks
        return [
            (title, list(blocks[i : i + _FALLBACK_WINDOW_BLOCKS]))
            for i in range(0, len(blocks), _FALLBACK_WINDOW_BLOCKS)
        ]
    return _split_by_markers(groups) or _merge_to_target(groups)


# ------------------------------------------------------------------------------------------------
# Outline-based splitter (Experiment 1, docs/PLAN-book-rag-experiments.md; gate result:
# docs/eval-reports/2026-07-29-outline-join-feasibility.md).
#
# A SIBLING strategy to `_split_chapters()` above, never a replacement -- the gate doc's own risk
# note is that an outline helps only 4 of the corpus's 5 books (the 5th, and any future
# scanned/no-outline book, has no `pypdfium2.get_toc()` entries at all), so the size-merge path
# stays the only option for those books permanently. Deliberately has NO `pypdfium2` import and no
# `paper_id`/PDF-path argument -- it takes already-extracted outline entries, the same
# decoupling `outline_join_probe.py`'s split between "read the PDF" and "compute the join"
# already established, and keeps `pypdfium2` out of this module (CONVENTIONS.md §1 confines a
# vendor import to the one module that owns it -- here, whichever caller reads the PDF).
#
# `summarize_book()` is NOT changed to call this -- it still only ever calls `_split_chapters()`.
# The experiment script that drives this (app/exp1_outline_split.py) instead substitutes this
# module's `_split_chapters` NAME for the duration of one `summarize_book()` call (`unittest.mock.
# patch`), so `summarize_book()`'s own source is untouched and its only variable is *which
# function* `_split_chapters` resolves to at call time -- see that script's own docstring for why.
# ------------------------------------------------------------------------------------------------


class OutlineEntry(NamedTuple):
    """One `pypdfium2.get_toc()` bookmark, already resolved to a title and a 0-based page index
    (`get_dest().get_index()`) by the caller -- entries `get_dest()` couldn't resolve (`None` for
    0 of 1,035 entries across the gate doc's 4 books) are the caller's to drop before construction,
    not this module's problem."""

    level: int
    title: str
    page_index: int


# Same keyword family `_split_by_markers` uses above (deliberately excludes the bare "N. Title"
# alternative -- an outline entry's own numbering isn't corroborated by document position the way
# `_bare_numbers_are_sequential` corroborates a heading's, so this stays keyword-only) -- verified
# in the gate doc (Q5) against all 4 outline-bearing books' actual outlines, not reused unchecked.
_OUTLINE_MARKER = _CHAPTER_KEYWORD_MARKER

# ponytail: front matter (Cover/Half Title/Copyright/Dedication) is detected structurally -- by
# word count, not a label blocklist -- same "no word blocklist" reasoning as `_title_score`'s
# comment above: publishers phrase these differently and a name list would be endless and still
# incomplete. A cover/title/copyright/dedication page carries a handful of words; a real opening
# chapter carries thousands. Ceiling: a front-matter page with unusually dense boilerplate (a
# copyright page listing a long disclaimer, say) could cross this and end up as its own tiny
# routing unit instead of being folded into the front-matter bucket -- harmless (one extra small
# chapter, not a wrong boundary), not silently corrected further; retune this constant if a book
# is found where it matters.
_FRONT_MATTER_MAX_WORDS = 500


def pick_outline_level(entries: list[OutlineEntry]) -> int:
    """Q5 rule (gate doc): the outline level with the most Chapter/Part/Appendix-marker titles,
    else level 0. One rule for all 4 outline-bearing books, even though the level it lands on
    differs per book (some nest chapters under parts, some don't print the word "chapter" at
    all) -- see the gate doc's Q5 section for the per-book reasoning this rule was checked against.
    """
    counts: dict[int, int] = {}
    for e in entries:
        if _OUTLINE_MARKER.match(e.title):
            counts[e.level] = counts.get(e.level, 0) + 1
    return max(counts, key=lambda lv: counts[lv]) if counts else 0


def _split_chapters_outline(
    parsed: ParsedDoc, entries: list[OutlineEntry]
) -> list[tuple[str, list[Block]]] | None:
    """Cuts `parsed.blocks` at the chosen outline level's page boundaries. Returns `None` when
    there's no usable outline (fewer than 2 boundaries at the picked level) -- same "return None,
    caller decides the fallback" contract `_split_by_markers` already uses above, so a caller can
    write `_split_chapters_outline(parsed, entries) or _split_chapters(parsed)` symmetrically.

    Offset is applied as exactly 0 -- the gate doc measured this as a CONSTANT offset (94-100% of
    matched entries land at offset 0 for all 4 books, the small remainder being 1-2 isolated
    single-entry outliers, never a spread), so this cuts directly at `page_index` with no
    per-entry fuzzy re-verification at split time; that fuzzy title-word matching lives only in
    `app/outline_join_probe.py`, where it was needed to PROVE the offset at gate time, not to be
    repeated on every split.

    Front matter (leading Cover/Half Title/Copyright/Dedication-type units, see
    `_FRONT_MATTER_MAX_WORDS`) is merged into one leading `("", blocks)` unit -- the same
    convention `_split_by_markers` already uses for its own pre-first-marker content -- rather
    than left as several near-empty routing units. This only merges a LEADING run: a small unit
    later in the book (e.g. a bare "Part II" divider page, which some outlines put at the same
    level as real chapters -- see the gate doc's Q5 note on `dfe850b3281a`) is left as its own
    unit, unchanged; that is an existing property of the outline's own structure, not something
    this experiment was asked to fix.
    """
    if not entries:
        return None
    level = pick_outline_level(entries)
    level_entries = [e for e in entries if e.level == level]
    boundaries = sorted({e.page_index for e in level_entries})
    if len(boundaries) < 2:
        return None

    # Earliest entry at a given page_index wins the title (matches how a reader would read a
    # boundary page with two outline entries pointing at it -- the outermost/first-listed one).
    title_by_boundary: dict[int, str] = {}
    for e in sorted(level_entries, key=lambda e: e.page_index):
        title_by_boundary.setdefault(e.page_index, e.title.strip())

    units: list[list[Block]] = [[] for _ in boundaries]
    for block in parsed.blocks:
        u = 0
        for i, start in enumerate(boundaries):
            if block.page >= start:
                u = i
        units[u].append(block)

    cut = 0
    while cut < len(units) - 1 and _words(units[cut]) < _FRONT_MATTER_MAX_WORDS:
        cut += 1
    front = [blk for u in units[:cut] for blk in u]

    result: list[tuple[str, list[Block]]] = []
    if front:
        result.append(("", front))
    for i in range(cut, len(units)):
        if units[i]:  # a boundary page with no blocks that landed in its range -- skip, not ""
            result.append((title_by_boundary[boundaries[i]], units[i]))
    return result


def _doc_from_text(parsed: ParsedDoc, text: str) -> ParsedDoc:
    # Both real and fake Summarizer read only `parsed.markdown` (rag/summarizer.py's
    # `summarize()`, rag/fakes/fake_summarizer.py's `FakeSummarizer.summarize()`); blocks/
    # figures/tables ride along untouched for shape-validity.
    return parsed.model_copy(update={"markdown": text})


def _summarize_text(parsed: ParsedDoc, summarizer, text: str, kind: str) -> str:
    words = text.split()
    if len(words) <= _MAX_CHAPTER_WORDS:
        return summarizer.summarize(_doc_from_text(parsed, text), kind=kind)
    # Bounded depth-2 windowing (spec): summarize fixed word-windows, then combine those.
    windows = [
        " ".join(words[i : i + _MAX_CHAPTER_WORDS])
        for i in range(0, len(words), _MAX_CHAPTER_WORDS)
    ]
    partials = [summarizer.summarize(_doc_from_text(parsed, w), kind=kind) for w in windows]
    return summarizer.summarize(_doc_from_text(parsed, "\n\n".join(partials)), kind=kind)


def summarize_book(parsed: ParsedDoc, summarizer) -> tuple[str, list[ChapterSummary]]:
    chapters: list[ChapterSummary] = []
    for n, (title, blocks) in enumerate(_split_chapters(parsed)):
        chapter_text = "\n\n".join(b.text for b in blocks)
        text = _summarize_text(parsed, summarizer, chapter_text, "book")
        if not title and text:
            # T-DOC85: no heading in this unit was usable as a routing label. Title from the
            # summary we just computed -- short input, one call, and it inherits that summary's
            # grounding rather than the raw chapter's noise. Whitespace-collapsed because the
            # model occasionally returns a trailing newline.
            #
            # Guarded by `text` (skip the call entirely when the chapter summary came back empty):
            # the real Summarizer adapter's `summarize` raises `PermanentError` on empty prose, which would
            # quarantine the WHOLE BOOK for a single chapter's degraded title -- before this
            # fallback existed that chapter simply carried "".
            #
            # Gated through `_title_score`, same as every other title source in this module: an
            # unvalidated model response (e.g. "Sure, here's a title: ...") would otherwise be
            # persisted verbatim as a routing label.
            candidate = " ".join(
                summarizer.summarize(_doc_from_text(parsed, text), kind="book_title").split()
            )
            title = candidate if _title_score(candidate) else ""
        chapters.append(
            ChapterSummary(summary_id=f"{parsed.paper_id}:summary:ch{n}", title=title, text=text)
        )
    if not chapters:
        # T-DOC82 deferred-minor fix: an empty/figures-only parse previously produced an empty
        # summary_text that nothing quarantined. Same taxonomy the real Summarizer uses for the
        # same condition, so IngestionOrchestrator's existing retry/quarantine path handles it.
        raise PermanentError(
            f"{parsed.paper_id}: no usable blocks to summarize (empty or figures-only parse)"
        )
    joined = "\n\n".join(f"{c.title}: {c.text}" if c.title else c.text for c in chapters)
    overview = _summarize_text(parsed, summarizer, joined, "book_overview")
    toc = "\n".join(f"{n + 1}. {c.title}" for n, c in enumerate(chapters) if c.title)
    summary_text = overview + ("\n\nContents:\n" + toc if toc else "")
    return summary_text, chapters
