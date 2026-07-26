"""rag.book_summarizer -- map-reduce book summarization (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

Tests-first: drives `summarize_book(parsed, summarizer) -> (book_summary_text,
chapter_summaries)` entirely against `FakeSummarizer` (rag/fakes/fake_summarizer.py) --
deterministic truncation of `ParsedDoc.markdown`, no GPU, no network. Never uses the real
Ollama-backed Summarizer.
"""

from contracts.parser import ParsedDoc
from contracts.provenance import Block
from rag.book_summarizer import _FALLBACK_WINDOW_BLOCKS, _MAX_CHAPTER_WORDS, summarize_book
from rag.fakes.fake_summarizer import FakeSummarizer

PAPER_ID = "2506.09999"


def _block(text: str, section_path: str, idx: int) -> Block:
    return Block(
        block_id=f"{PAPER_ID}:b{idx}",
        paper_id=PAPER_ID,
        text=text,
        type="prose",
        page=0,
        bbox=(0.0, 0.0, 100.0, 200.0),
        section_path=section_path,
        index=idx,
    )


def _parsed_doc(blocks: list[Block]) -> ParsedDoc:
    return ParsedDoc(
        paper_id=PAPER_ID,
        markdown="\n\n".join(b.text for b in blocks),
        blocks=blocks,
        figures=[],
        tables=[],
        references=[],
        parser_id="test-parser-1.x",
    )


def test_splits_on_top_level_section_path():
    blocks = [
        _block("intro text", "Ch 1 Intro", 0),
        _block("s1", "Ch 1 Intro > 1.1", 1),
        _block("dags", "Ch 2 DAGs", 2),
    ]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert [c.title for c in chapters] == ["Ch 1 Intro", "Ch 2 DAGs"]
    assert chapters[0].summary_id == f"{PAPER_ID}:summary:ch0"
    assert chapters[1].summary_id == f"{PAPER_ID}:summary:ch1"


def test_book_summary_contains_toc():
    blocks = [
        _block("intro text", "Ch 1 Intro", 0),
        _block("dags", "Ch 2 DAGs", 1),
    ]
    text, _ = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert "Contents:" in text
    assert "Ch 2 DAGs" in text


def test_flat_doc_falls_back_to_windows():
    # 450 blocks all sharing one section_path -- no usable chapter structure -> windowed
    # fallback of _FALLBACK_WINDOW_BLOCKS-sized groups, titles == "" per spec.
    n_blocks = 3 * _FALLBACK_WINDOW_BLOCKS
    blocks = [_block(f"word{i}", "Only Section", i) for i in range(n_blocks)]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert all(c.title == "" for c in chapters)
    assert len(chapters) == 3
    assert [c.summary_id for c in chapters] == [f"{PAPER_ID}:summary:ch{n}" for n in range(3)]


def test_oversized_chapter_summarized_in_windows():
    # One chapter's word count exceeds _MAX_CHAPTER_WORDS -> internally windowed, but still
    # exactly ONE ChapterSummary comes out for it.
    big_text = " ".join(f"word{i}" for i in range(_MAX_CHAPTER_WORDS + 1))
    blocks = [_block(big_text, "Big Chapter", 0), _block("small", "Other Chapter", 1)]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    big = [c for c in chapters if c.title == "Big Chapter"]
    assert len(big) == 1
    assert big[0].text.strip()


def test_chapter_summaries_are_nonempty_and_single_summary_per_chapter():
    blocks = [
        _block("intro text", "Ch 1 Intro", 0),
        _block("dags", "Ch 2 DAGs", 1),
    ]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert len(chapters) == 2
    for c in chapters:
        assert c.text.strip()
