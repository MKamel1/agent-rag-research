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
_CHAPTER_MARKER = re.compile(
    r"^\s*(?:chapter|part|appendix)\s+"
    r"(?:\d+|[ivxlcdm]+|[a-z]|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"
    r"|^\s*\d+\.\s+\S",
    re.IGNORECASE,
)
# ponytail: fixed thresholds tuned against one measured 144k-word book, not adaptive. The guard
# band is what stops a book that merely *mentions* "Chapter 3" from producing 2 lopsided units.
_TARGET_CHAPTER_WORDS = 5000
_MIN_MARKER_UNITS = 3
_MAX_MARKER_UNITS = 60
_MAX_UNIT_WORD_SHARE = 0.5


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


def _split_by_markers(
    groups: list[tuple[str, list[Block]]],
) -> list[tuple[str, list[Block]]] | None:
    """Strategy A. Returns None when the split isn't plausible, so the caller falls back."""
    units: list[tuple[str, list[Block]]] = []
    for title, blocks in groups:
        if _CHAPTER_MARKER.match(title):
            units.append((title, list(blocks)))
        elif units:
            units[-1][1].extend(blocks)
        else:
            units.append(("", list(blocks)))  # front matter, before the first marker
    if sum(1 for title, _ in units if title) < _MIN_MARKER_UNITS:
        return None
    if len(units) > _MAX_MARKER_UNITS:
        return None
    total = sum(_words(blocks) for _, blocks in units)
    if total and max(_words(blocks) for _, blocks in units) / total > _MAX_UNIT_WORD_SHARE:
        return None
    return units


def _merge_to_target(groups: list[tuple[str, list[Block]]]) -> list[tuple[str, list[Block]]]:
    """Strategy B: accumulate consecutive heading groups until ~_TARGET_CHAPTER_WORDS.

    Title of a merged unit is its FIRST heading. Independent of heading text entirely, which is
    why it is the safe general path for any book's formatting.
    """
    units: list[tuple[str, list[Block]]] = []
    for title, blocks in groups:
        if units and _words(units[-1][1]) < _TARGET_CHAPTER_WORDS:
            units[-1][1].extend(blocks)
        else:
            units.append((title, list(blocks)))
    if len(units) > 1 and _words(units[-1][1]) < _TARGET_CHAPTER_WORDS // 2:
        _, tail = units.pop()
        units[-1][1].extend(tail)
    return units


def _split_chapters(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    groups = _heading_groups(parsed)
    if len(groups) <= 1:
        # No usable heading structure (flat/scanned). Window it, but keep the single group's
        # title rather than dropping it to "" (T-DOC82 deferred-minor fix).
        title = groups[0][0] if groups else ""
        blocks = parsed.blocks
        return [
            (title, list(blocks[i : i + _FALLBACK_WINDOW_BLOCKS]))
            for i in range(0, len(blocks), _FALLBACK_WINDOW_BLOCKS)
        ]
    return _split_by_markers(groups) or _merge_to_target(groups)


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
