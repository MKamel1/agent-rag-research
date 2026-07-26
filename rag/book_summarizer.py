"""Map-reduce summarization for doc_type="book" (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

A book's markdown is 10-50x a paper's and cannot go through one `summarize()` call (the real
adapter's num_ctx ceiling truncates it to noise). Instead: split into chapters (top-level
`section_path` groups), summarize each (map), then summarize the chapter summaries into one
overview + table of contents (reduce). Chapter summaries are RETURNED, not discarded -- the
orchestrator persists and embeds them as routing units (ARCHITECTURE §M7 search_papers).

Takes any `Summarizer` as an argument (accept-dependencies principle) -- the GPU lock, eviction
hooks, retry taxonomy all stay the injected summarizer's concern, unchanged.
"""

from contracts.document_store import ChapterSummary
from contracts.parser import ParsedDoc
from contracts.provenance import Block

# ponytail: fixed thresholds, not adaptive. _MAX_CHAPTER_WORDS stays under the real adapter's
# truncation point (_NUM_CTX_CEILING 16384 tok / 2.2 tok-per-word ~= 7400 words) so a chapter is
# summarized whole, not silently truncated; retune both together if the ceiling moves.
_MAX_CHAPTER_WORDS = 6000
_FALLBACK_WINDOW_BLOCKS = 150  # flat/scanned books with no usable section structure


def _top_level(section_path: str) -> str:
    return section_path.split(" > ", 1)[0]  # separator per rag/parser.py's section-stack join


def _split_chapters(parsed: ParsedDoc) -> list[tuple[str, list[Block]]]:
    groups: list[tuple[str, list[Block]]] = []
    for block in parsed.blocks:
        top = _top_level(block.section_path)
        if groups and groups[-1][0] == top:
            groups[-1][1].append(block)
        else:
            groups.append((top, [block]))
    if len(groups) <= 1:
        blocks = parsed.blocks
        return [
            ("", list(blocks[i : i + _FALLBACK_WINDOW_BLOCKS]))
            for i in range(0, len(blocks), _FALLBACK_WINDOW_BLOCKS)
        ]
    return groups


def _doc_from_text(parsed: ParsedDoc, text: str) -> ParsedDoc:
    # Both real and fake Summarizer read only `parsed.markdown` (rag/summarizer.py's
    # `summarize()`, rag/fakes/fake_summarizer.py's `FakeSummarizer.summarize()`); blocks/
    # figures/tables ride along untouched for shape-validity.
    return parsed.model_copy(update={"markdown": text})


def _summarize_text(parsed: ParsedDoc, summarizer, text: str) -> str:
    words = text.split()
    if len(words) <= _MAX_CHAPTER_WORDS:
        return summarizer.summarize(_doc_from_text(parsed, text))
    # Bounded depth-2 windowing (spec): summarize fixed word-windows, then combine those.
    windows = [
        " ".join(words[i : i + _MAX_CHAPTER_WORDS])
        for i in range(0, len(words), _MAX_CHAPTER_WORDS)
    ]
    partials = [summarizer.summarize(_doc_from_text(parsed, w)) for w in windows]
    return summarizer.summarize(_doc_from_text(parsed, "\n\n".join(partials)))


def summarize_book(parsed: ParsedDoc, summarizer) -> tuple[str, list[ChapterSummary]]:
    chapters: list[ChapterSummary] = []
    for n, (title, blocks) in enumerate(_split_chapters(parsed)):
        chapter_text = "\n\n".join(b.text for b in blocks)
        text = _summarize_text(parsed, summarizer, chapter_text)
        chapters.append(
            ChapterSummary(summary_id=f"{parsed.paper_id}:summary:ch{n}", title=title, text=text)
        )
    joined = "\n\n".join(f"{c.title}: {c.text}" if c.title else c.text for c in chapters)
    overview = _summarize_text(parsed, summarizer, joined)
    toc = "\n".join(f"{n + 1}. {c.title}" for n, c in enumerate(chapters) if c.title)
    summary_text = overview + ("\n\nContents:\n" + toc if toc else "")
    return summary_text, chapters
