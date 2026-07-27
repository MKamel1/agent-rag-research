"""rag.book_summarizer -- map-reduce book summarization (T-DOC80, spec:
docs/superpowers/specs/2026-07-25-drop-in-folder-and-books-design.md).

Tests-first: drives `summarize_book(parsed, summarizer) -> (book_summary_text,
chapter_summaries)` entirely against `FakeSummarizer` (rag/fakes/fake_summarizer.py) --
deterministic truncation of `ParsedDoc.markdown`, no GPU, no network. Never uses the real
GPU-backed production Summarizer.
"""

import pytest

from contracts.errors import PermanentError
from contracts.parser import ParsedDoc
from contracts.provenance import Block
from rag.book_summarizer import (
    _FALLBACK_WINDOW_BLOCKS,
    _MAX_CHAPTER_WORDS,
    _TARGET_CHAPTER_WORDS,
    _split_chapters,
    summarize_book,
)
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
    # T-DOC82: the size-merge fallback only leaves top-level groups standing on their own once
    # each already meets _TARGET_CHAPTER_WORDS (below that, either the main merge loop or its
    # small-trailing-remainder check would fold them together) -- so both "Ch 1 Intro" and
    # "Ch 2 DAGs" carry enough words to survive on their own; this isolates what the test is
    # actually pinning: that `_top_level` still collapses "Ch 1 Intro > 1.1" into the "Ch 1
    # Intro" group, same as before T-DOC82.
    blocks = [
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Ch 1 Intro", 0),
        _block("s1", "Ch 1 Intro > 1.1", 1),
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Ch 2 DAGs", 2),
    ]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert [c.title for c in chapters] == ["Ch 1 Intro", "Ch 2 DAGs"]
    assert chapters[0].summary_id == f"{PAPER_ID}:summary:ch0"
    assert chapters[1].summary_id == f"{PAPER_ID}:summary:ch1"


def test_book_summary_contains_toc():
    # See test_splits_on_top_level_section_path: both headings need >= _TARGET_CHAPTER_WORDS
    # words so the size-merge fallback keeps "Ch 2 DAGs" as its own chapter (title in the TOC).
    blocks = [
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Ch 1 Intro", 0),
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Ch 2 DAGs", 1),
    ]
    text, _ = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert "Contents:" in text
    assert "Ch 2 DAGs" in text


def test_flat_doc_falls_back_to_windows():
    # 450 blocks all sharing one section_path -- no usable chapter structure -> windowed
    # fallback of _FALLBACK_WINDOW_BLOCKS-sized groups. T-DOC82 deferred-minor fix: the single
    # group's real title ("Only Section") now carries through the windows instead of "".
    n_blocks = 3 * _FALLBACK_WINDOW_BLOCKS
    blocks = [_block(f"word{i}", "Only Section", i) for i in range(n_blocks)]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert all(c.title == "Only Section" for c in chapters)
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
    # See test_splits_on_top_level_section_path: sized so the two headings don't size-merge.
    blocks = [
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Ch 1 Intro", 0),
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Ch 2 DAGs", 1),
    ]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert len(chapters) == 2
    for c in chapters:
        assert c.text.strip()


def test_flat_book_headings_do_not_become_one_chapter_each():
    """REGRESSION PIN (T-DOC82 D1): the exact real-world failure shape -- many distinct FLAT
    section_paths with no ' > ' hierarchy -- must NOT yield one chapter per heading."""
    blocks = []
    for i in range(60):  # 60 headings x ~200 words = ~12k words
        for j in range(4):
            blocks.append(_block(" ".join(["word"] * 50), f"Heading {i}", len(blocks)))
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert len(chapters) < 15, f"expected size-merged units, got {len(chapters)}"
    assert len(chapters) >= 2


def test_explicit_chapter_markers_are_used_when_plausible():
    blocks = []
    for title in [
        "Front matter",
        "Chapter 1 Intro",
        "Some subsection",
        "Chapter 2 DAGs",
        "Another subsection",
        "Chapter 3 Estimation",
    ]:
        for _ in range(3):
            blocks.append(_block(" ".join(["word"] * 100), title, len(blocks)))
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    titles = [c.title for c in chapters]
    assert titles == ["", "Chapter 1 Intro", "Chapter 2 DAGs", "Chapter 3 Estimation"]


def test_marker_variants_part_appendix_numbered():
    for marker in ["Part II Foundations", "Appendix A Proofs", "3. Estimation"]:
        blocks = []
        for title in ["Preface", marker, "Body", f"{marker} second", "More", f"{marker} third"]:
            blocks.append(_block(" ".join(["word"] * 100), title, len(blocks)))
        units = _split_chapters(_parsed_doc(blocks))
        assert any(t == marker for t, _ in units), f"{marker!r} not detected as a chapter marker"


def test_too_few_markers_falls_back_to_size_merge():
    """One stray 'Chapter 3' heading must REJECT the marker strategy (count guard) rather than
    produce 2 wildly-unbalanced 'chapters'."""
    blocks = [
        _block(" ".join(["word"] * 100), "Intro", 0),
        _block(" ".join(["word"] * 12000), "Chapter 3 mentioned in passing", 1),
    ]
    units = _split_chapters(_parsed_doc(blocks))
    assert [t for t, _ in units] != ["", "Chapter 3 mentioned in passing"]


def test_marker_split_rejected_when_one_unit_dominates():
    """Word-share guard: 3 markers pass the COUNT guard, but one unit holding >50% of the words
    means those markers aren't real chapter boundaries."""
    blocks = [
        _block(" ".join(["word"] * 100), "Chapter 1 A", 0),
        _block(" ".join(["word"] * 100), "Chapter 2 B", 1),
        _block(" ".join(["word"] * 100), "Chapter 3 C", 2),
        _block(" ".join(["word"] * 5000), "Body text", 3),
    ]
    units = _split_chapters(_parsed_doc(blocks))
    assert [t for t, _ in units] != ["Chapter 1 A", "Chapter 2 B", "Chapter 3 C"]


def test_size_merge_targets_chapter_sized_units():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(40)]  # 20k words
    units = _split_chapters(_parsed_doc(blocks))
    assert 3 <= len(units) <= 6, f"expected ~4 units of ~5000 words, got {len(units)}"
    assert units[0][0] == "H0", "unit title should be its first heading"


def test_small_trailing_remainder_merges_instead_of_stub_unit():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(21)]  # 10.5k words
    units = _split_chapters(_parsed_doc(blocks))
    assert all(
        sum(len(b.text.split()) for b in bl) > _TARGET_CHAPTER_WORDS // 2 for _, bl in units
    ), "a tiny trailing unit should have merged into the previous one"


def test_single_group_keeps_its_title_through_windowing():
    """Deferred-minor fix: a genuinely single-section doc previously lost its title to ''."""
    blocks = [_block("word " * 10, "The Only Section", i) for i in range(400)]
    units = _split_chapters(_parsed_doc(blocks))
    assert len(units) > 1, "400 blocks should still be windowed"
    assert all(t == "The Only Section" for t, _ in units)


def test_empty_parsed_doc_raises_permanent_error():
    """Deferred-minor fix: zero blocks previously produced an empty summary nobody quarantined."""
    with pytest.raises(PermanentError):
        summarize_book(_parsed_doc([]), FakeSummarizer())


# ---------------------------------------------------------------------------
# T-DOC82: summarize_book must never use the paper prompt (see rag/summarizer.py -- asked for a
# paper's "effect size"/"sample size", the model invented them for a real book). Map calls use
# "book", the single reduce call uses "book_overview".
# ---------------------------------------------------------------------------


class _KindRecorder:
    def __init__(self):
        self.kinds = []

    def summarize(self, parsed, *, kind="paper"):
        self.kinds.append(kind)
        return f"summary of {parsed.markdown[:20]}"


def test_summarize_book_uses_book_kinds_not_paper():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(20)]
    rec = _KindRecorder()
    summarize_book(_parsed_doc(blocks), rec)
    assert "paper" not in rec.kinds, "book path must never use the paper prompt"
    assert rec.kinds.count("book_overview") == 1, "exactly one reduce call"
    assert all(k == "book" for k in rec.kinds[:-1])
