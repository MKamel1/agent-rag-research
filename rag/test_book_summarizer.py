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
    _MAX_MARKER_UNITS,
    _TARGET_CHAPTER_WORDS,
    OutlineEntry,
    _best_heading,
    _merge_to_target,
    _split_chapters,
    _split_chapters_outline,
    _title_score,
    pick_outline_level,
    summarize_book,
)
from rag.fakes.fake_summarizer import FakeSummarizer

PAPER_ID = "2506.09999"


def _block(text: str, section_path: str, idx: int, page: int = 0) -> Block:
    return Block(
        block_id=f"{PAPER_ID}:b{idx}",
        paper_id=PAPER_ID,
        text=text,
        type="prose",
        page=page,
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


@pytest.fixture
def make_groups():
    """Builds the `list[tuple[str, list[Block]]]` shape `_merge_to_target` consumes from
    `list[tuple[str, int]]` of (heading, word_count), reusing `_block` for the actual Blocks."""

    def _make(specs: list[tuple[str, int]]) -> list[tuple[str, list[Block]]]:
        return [
            (heading, [_block(" ".join(["word"] * word_count), heading, idx)])
            for idx, (heading, word_count) in enumerate(specs)
        ]

    return _make


def _parsed_from_groups(groups: list[tuple[str, list[Block]]]) -> ParsedDoc:
    """Flattens the `make_groups` shape back into blocks and builds a ParsedDoc from them --
    `summarize_book` re-derives its own groups from `parsed.blocks`' section_paths (`_heading_
    groups`), it does not take a groups list directly."""
    return _parsed_doc([block for _, blocks in groups for block in blocks])


def test_title_score_rejects_single_characters_and_short_fragments():
    assert _title_score("F") == 0
    assert _title_score("") == 0
    assert _title_score("A.") == 0


def test_title_score_prefers_longer_content_words():
    # "See Also" and "Regularized Regression" both have two words -- scoring by total content
    # characters, not word count, is what separates them.
    assert _title_score("Regularized Regression") > _title_score("See Also")
    assert _title_score("Canonical Difference-in-Differences") > _title_score("Assign")


def test_title_score_rejects_punctuation_heavy_headings():
    # Observed live: "\\* and : Operators" was a chapter title.
    assert _title_score("\\* and : Operators") == 0


def test_title_score_rejects_headings_long_enough_to_be_a_misparsed_paragraph():
    assert _title_score("word " * 40) == 0


def test_best_heading_picks_the_highest_scoring_not_the_first():
    headings = ["See Also", "Regularized Regression", "F"]
    assert _best_heading(headings) == "Regularized Regression"


def test_best_heading_breaks_ties_toward_the_earliest():
    # T-DOC85 fix round 1: the original fixture ("Neutral Controls" vs "Optimal Switchback")
    # scores 15 vs 17 -- not a tie, so it never exercised the tie-break branch and would have
    # passed under a naive "always return headings[0]" regression too. These two score exactly
    # 14 each (7 + 7 content chars), which pins `>` (not `>=`) keeping the earliest on a real tie.
    assert _title_score("Neutral Impacts") == _title_score("Optimal Effects") == 14
    assert _best_heading(["Neutral Impacts", "Optimal Effects"]) == "Neutral Impacts"


def test_best_heading_returns_empty_when_nothing_is_usable():
    # T-DOC85 mutation check (Step 5): "F"/""/""A."" are each rejected by a DIFFERENT guard (no
    # matching word, empty string, punctuation ratio) and none of those exercises
    # _MIN_TITLE_SCORE, so with that constant neutered to 0 this assertion still held -- a
    # tautological test. "See Also" has a nonzero raw content-char score (7) that is only
    # rejected by the _MIN_TITLE_SCORE floor (8), so it is what actually pins the floor.
    assert _best_heading(["F", "", "A.", "See Also"]) == ""


def test_merge_to_target_titles_a_unit_by_its_best_heading(make_groups):
    # Regression pin for T-DOC85: the unit's FIRST heading is junk, a later one is real. Before
    # the fix this unit was titled "See Also".
    groups = make_groups([
        ("See Also", 100),
        ("Regularized Regression", 2000),
        ("F", 100),
    ])
    units = _merge_to_target(groups)
    assert [title for title, _ in units] == ["Regularized Regression"]


def test_merge_to_target_keeps_folded_tail_headings(make_groups):
    # Regression pin for T-DOC85 fix round 1: `headings[-1].extend(headings.pop())` evaluates
    # `headings[-1]` (bound method target) before its argument `headings.pop()` -- both resolve
    # to the SAME list, so this was `X.extend(X)` on an object immediately discarded by the pop,
    # silently dropping every heading from the folded trailing remainder. "Assign" (100 words)
    # falls under the small-trailing-remainder threshold and folds into the first unit, taking
    # "F" and "Regularized Regression" with it -- if the fold drops those headings, only "Assign"
    # (score 6, below the floor) remains and the unit is wrongly titled "".
    groups = make_groups([
        ("Assign", 5000),
        ("F", 100),
        ("Regularized Regression", 100),
    ])
    units = _merge_to_target(groups)
    assert [title for title, _ in units] == ["Regularized Regression"]


def test_splits_on_top_level_section_path():
    # T-DOC82: the size-merge fallback only leaves top-level groups standing on their own once
    # each already meets _TARGET_CHAPTER_WORDS (below that, either the main merge loop or its
    # small-trailing-remainder check would fold them together) -- so both "Introduction" and
    # "Causal Graphs" carry enough words to survive on their own; this isolates what the test is
    # actually pinning: that `_top_level` still collapses "Introduction > 1.1" into the
    # "Introduction" group, same as before T-DOC82.
    # T-DOC85: headings renamed from the original "Ch 1 Intro"/"Ch 2 DAGs" -- those abbreviated
    # forms score below _MIN_TITLE_SCORE (only "Intro"/"DAGs" match _TITLE_WORD, "Ch"/"1"/"2"
    # don't) and _best_heading would reject them to "", which is not what this test is about.
    blocks = [
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Introduction", 0),
        _block("s1", "Introduction > 1.1", 1),
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Causal Graphs", 2),
    ]
    _, chapters = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert [c.title for c in chapters] == ["Introduction", "Causal Graphs"]
    assert chapters[0].summary_id == f"{PAPER_ID}:summary:ch0"
    assert chapters[1].summary_id == f"{PAPER_ID}:summary:ch1"


def test_book_summary_contains_toc():
    # See test_splits_on_top_level_section_path: both headings need >= _TARGET_CHAPTER_WORDS
    # words so the size-merge fallback keeps "Causal Graphs" as its own chapter (title in the
    # TOC), and (T-DOC85) score above _MIN_TITLE_SCORE so _best_heading keeps it rather than "".
    blocks = [
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Introduction", 0),
        _block(" ".join(["word"] * _TARGET_CHAPTER_WORDS), "Causal Graphs", 1),
    ]
    text, _ = summarize_book(_parsed_doc(blocks), FakeSummarizer())
    assert "Contents:" in text
    assert "Causal Graphs" in text


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
    # exactly ONE ChapterSummary comes out for it. The trailing 1-word "small" heading is below
    # the small-trailing-remainder threshold, so it folds into "Big Chapter" -- both headings then
    # compete in _best_heading over the merged unit (T-DOC85: intentional, ALL headings merged
    # into a unit are candidates, not just the surviving accumulator's original one). Renamed
    # from the original "Other Chapter" (score 12, beats "Big Chapter"'s 10 and became the title)
    # to "See Also" (score 0, below the floor) so "Big Chapter" remains the unambiguous winner --
    # this test is about windowing, not about which heading _best_heading should prefer.
    big_text = " ".join(f"word{i}" for i in range(_MAX_CHAPTER_WORDS + 1))
    blocks = [_block(big_text, "Big Chapter", 0), _block("small", "See Also", 1)]
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
    # T-DOC85 (Task 6): the pre-first-marker unit is titled "" by _split_by_markers itself (it
    # isn't a real chapter heading), so it's eligible for the LLM `book_title` fallback -- but
    # `FakeSummarizer` just echoes its (long) input back rather than writing a real short title,
    # so the candidate correctly fails `_title_score`'s length ceiling (cross-task fix #2: the
    # fallback response is gated through `_title_score`, not persisted unvalidated) and the unit
    # stays "" rather than being labelled with 500 characters of raw chapter text.
    assert titles[0] == ""
    assert titles[1:] == ["Chapter 1 Intro", "Chapter 2 DAGs", "Chapter 3 Estimation"]


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


def test_too_many_markers_falls_back_to_size_merge():
    """>_MAX_MARKER_UNITS numbered headings is D1's shape wearing marker clothes.

    The pass/fail bound is the fixed literal `n_headings` (80), not `_MAX_MARKER_UNITS`
    itself -- comparing against the guard constant would be tautological (raising the guard
    raises the assertion's bound right along with it, so the test would pass either way
    without ever exercising the fallback). The precondition assert instead catches that
    mutation directly: if the guard is loosened past `n_headings`, this fixture no longer
    exceeds it and the test fails here rather than silently exercising the wrong path.
    """
    n_headings = 80
    assert n_headings > _MAX_MARKER_UNITS, "fixture must exceed the guard to exercise it"
    blocks = [
        _block(" ".join(["word"] * 300), f"{i}. Section {i}", i) for i in range(n_headings)
    ]
    units = _split_chapters(_parsed_doc(blocks))
    assert len(units) < n_headings, "expected size-merged units, not one unit per heading"


def test_size_merge_targets_chapter_sized_units():
    blocks = [_block(" ".join(["word"] * 500), f"H{i}", i) for i in range(40)]  # 20k words
    units = _split_chapters(_parsed_doc(blocks))
    assert 3 <= len(units) <= 6, f"expected ~4 units of ~5000 words, got {len(units)}"
    # T-DOC85: this used to assert units[0][0] == "H0" ("unit title should be its first
    # heading"), which pinned the bug this task fixes. None of "H0".."H39" contains a real word
    # (_TITLE_WORD needs 3+ letters; "H" + a digit never matches), so every heading in this
    # fixture scores 0 and _best_heading correctly falls back to "" -- Task 6's trigger.
    assert units[0][0] == ""


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
    # One chapter (~_MAX_CHAPTER_WORDS + 500 words) exceeds the per-chapter ceiling, so the
    # windowed branch of `_summarize_text` (partials + combine, all three call sites) actually
    # runs -- a fixture where every chapter stays under the ceiling would never exercise it,
    # letting a missed `kind=kind` on that branch alone reintroduce paper-prompt fabrication.
    blocks = [_block(" ".join(["word"] * (_MAX_CHAPTER_WORDS + 500)), "Big Chapter", 0)]
    blocks += [_block(" ".join(["word"] * 500), f"H{i}", i + 1) for i in range(10)]
    rec = _KindRecorder()
    _, chapters = summarize_book(_parsed_doc(blocks), rec)
    assert "paper" not in rec.kinds, "book path must never use the paper prompt"
    assert rec.kinds.count("book_overview") == 1, "exactly one reduce call"
    # T-DOC85 (Task 6): "H1".."H9" all score below _MIN_TITLE_SCORE, so the merged unit they fold
    # into is titled "" and picks up one "book_title" fallback call -- everything else is "book".
    assert all(k in ("book", "book_title") for k in rec.kinds[:-1])
    assert rec.kinds.count("book_title") == 1
    assert len(rec.kinds) > len(chapters), "windowed branch must have actually executed"


# ---------------------------------------------------------------------------
# T-DOC85: a unit whose every merged heading is junk (_best_heading returns "") falls back to an
# LLM-written title over the chapter's own already-computed summary, kind="book_title".
# ---------------------------------------------------------------------------


def test_unit_with_no_usable_heading_gets_an_llm_title(make_groups):
    summarizer = _KindRecorder()
    parsed = _parsed_from_groups(make_groups([("F", 3000), ("A.", 3000)]))

    _, chapters = summarize_book(parsed, summarizer)

    assert "book_title" in summarizer.kinds
    assert chapters[0].title != ""


def test_unit_with_a_usable_heading_makes_no_title_call(make_groups):
    # The fallback must stay a fallback -- a book with good headings pays nothing for it. If the
    # fallback fired unconditionally this would still leave a non-empty title (masking the bug),
    # which is why the assertion is on the call log, not on the title text.
    summarizer = _KindRecorder()
    parsed = _parsed_from_groups(make_groups([("Regularized Regression", 3000)]))

    summarize_book(parsed, summarizer)

    assert "book_title" not in summarizer.kinds


class _ChattyTitleRecorder:
    """Simulates an LLM `book_title` response that ignores the "one short title" instruction --
    the exact failure mode of an unvalidated fallback: a chatty preamble lands verbatim as the
    persisted, searched-on routing label."""

    def summarize(self, parsed, *, kind="paper"):
        if kind == "book_title":
            return (
                "Sure, here's a great title for this chapter that summarizes everything nicely "
                "and thoroughly for the reader"
            )
        return "a normal chapter summary with enough real content to not be empty"


def test_llm_title_fallback_is_rejected_when_it_fails_the_title_score(make_groups):
    # Cross-task fix #2: the fallback must be gated through `_title_score`, same as every other
    # title source in this module -- not just whitespace-collapsed and persisted verbatim.
    parsed = _parsed_from_groups(make_groups([("F", 3000)]))

    _, chapters = summarize_book(parsed, _ChattyTitleRecorder())

    assert chapters[0].title == ""


class _EmptyChapterSummaryRecorder:
    """A `book`-kind summary that comes back empty -- `book_title` must never be called on it,
    since the real Summarizer adapter's `summarize`'s empty-prose guard would raise `PermanentError`
    on an empty `book_title` input, quarantining the entire book over one degraded chapter."""

    def summarize(self, parsed, *, kind="paper"):
        if kind == "book_title":
            raise PermanentError("must not be called: the chapter summary was empty")
        return ""


def test_empty_chapter_summary_skips_the_title_fallback(make_groups):
    # Cross-task fix #3.
    parsed = _parsed_from_groups(make_groups([("F", 3000)]))

    _, chapters = summarize_book(parsed, _EmptyChapterSummaryRecorder())

    assert chapters[0].title == ""


def test_windowed_fallback_title_is_scored_not_kept_verbatim():
    # Cross-task fix #9: the windowed/structureless path used to keep the single group's heading
    # verbatim, unscored -- a junk heading (e.g. a scanned book's one OCR-garbled heading) would
    # then label every window AND suppress the LLM title fallback (a junk-but-truthy title looks
    # "usable" to summarize_book's `if not title`). Latent-only: no Task-8 book takes this path.
    blocks = [_block("word " * 10, "F", i) for i in range(400)]

    _, chapters = summarize_book(_parsed_doc(blocks), _KindRecorder())

    assert all(c.title != "F" for c in chapters)


# ---------------------------------------------------------------------------
# Outline-based splitter (Experiment 1) -- pure functions, fakes only, no PDF/pypdfium2 dependency.
# ---------------------------------------------------------------------------


def test_pick_outline_level_prefers_the_level_with_the_most_markers():
    # Mirrors CI-in-Python's real shape (gate doc Q5): level 0 has fewer "Part N" markers than
    # level 1 has "Chapter N" markers, so level 1 wins even though level 0 is outermost.
    entries = [
        OutlineEntry(0, "Part I. Foundations", 0),
        OutlineEntry(0, "Part II. Estimation", 10),
        OutlineEntry(1, "Chapter 1. Intro", 0),
        OutlineEntry(1, "Chapter 2. DAGs", 3),
        OutlineEntry(1, "Chapter 3. Estimation", 10),
    ]
    assert pick_outline_level(entries) == 1


def test_pick_outline_level_falls_back_to_zero_when_no_markers_at_any_level():
    # Mirrors Elements of CI (gate doc Q5): topic titles, no "chapter"/"part"/"appendix" word
    # anywhere -- falls back to level 0 even though nothing there matched either.
    entries = [
        OutlineEntry(0, "Statistical and Causal Models", 0),
        OutlineEntry(0, "Cause-Effect Models", 20),
        OutlineEntry(1, "Some Subsection", 2),
    ]
    assert pick_outline_level(entries) == 0


def test_split_chapters_outline_cuts_at_page_boundaries_offset_zero():
    blocks = [
        _block("word " * 20, "front", 0, page=0),
        _block("word " * 3000, "ch1", 1, page=5),
        _block("word " * 3000, "ch1 cont", 2, page=6),
        _block("word " * 3000, "ch2", 3, page=12),
    ]
    entries = [
        OutlineEntry(0, "Chapter 1. Intro", 5),
        OutlineEntry(0, "Chapter 2. Estimation", 12),
    ]
    units = _split_chapters_outline(_parsed_doc(blocks), entries)
    assert units is not None
    # page 0 block has no boundary <= it among {5, 12}, so `u` starts at 0 (the first boundary,
    # per the "last boundary <= page wins, else unit 0" rule) -- it's front matter, merged below.
    titles = [t for t, _ in units]
    assert titles == ["Chapter 1. Intro", "Chapter 2. Estimation"]
    ch1_texts = {b.block_id for b in units[0][1]}
    assert ch1_texts == {f"{PAPER_ID}:b0", f"{PAPER_ID}:b1", f"{PAPER_ID}:b2"}
    ch2_texts = {b.block_id for b in units[1][1]}
    assert ch2_texts == {f"{PAPER_ID}:b3"}


def test_split_chapters_outline_returns_none_with_fewer_than_two_boundaries():
    blocks = [_block("word " * 100, "only", 0, page=0)]
    entries = [OutlineEntry(0, "Chapter 1. Intro", 0)]
    assert _split_chapters_outline(_parsed_doc(blocks), entries) is None


def test_split_chapters_outline_returns_none_for_no_outline():
    blocks = [_block("word " * 100, "only", 0, page=0)]
    assert _split_chapters_outline(_parsed_doc(blocks), []) is None


def test_split_chapters_outline_merges_leading_front_matter_into_one_empty_titled_unit():
    # Cover/Half Title/Copyright/Dedication: each a handful of words, well under
    # _FRONT_MATTER_MAX_WORDS -- merged into one leading ("", ...) unit rather than 4 tiny
    # standalone routing units, same convention _split_by_markers uses for its own front matter.
    blocks = [
        _block("Some Book Title", "Cover", 0, page=0),
        _block("Copyright 2024", "Copyright", 1, page=1),
        _block("For my family", "Dedication", 2, page=2),
        _block("word " * 3000, "real chapter content", 3, page=5),
    ]
    entries = [
        OutlineEntry(0, "Cover", 0),
        OutlineEntry(0, "Copyright Page", 1),
        OutlineEntry(0, "Dedication", 2),
        OutlineEntry(0, "Chapter 1. Intro", 5),
    ]
    units = _split_chapters_outline(_parsed_doc(blocks), entries)
    assert units is not None
    assert [t for t, _ in units] == ["", "Chapter 1. Intro"]
    front_ids = {b.block_id for b in units[0][1]}
    assert front_ids == {f"{PAPER_ID}:b0", f"{PAPER_ID}:b1", f"{PAPER_ID}:b2"}


def test_split_chapters_outline_does_not_merge_a_non_leading_small_unit():
    # A "Part II" divider page with almost no text, appearing AFTER real chapter content, stays
    # its own standalone unit -- only a LEADING run of small units is front matter.
    blocks = [
        _block("word " * 3000, "ch1", 0, page=0),
        _block("Part II", "divider", 1, page=10),
        _block("word " * 3000, "ch2", 2, page=11),
    ]
    entries = [
        OutlineEntry(0, "Chapter 1. Intro", 0),
        OutlineEntry(0, "Part II", 10),
        OutlineEntry(0, "Chapter 2. Estimation", 11),
    ]
    units = _split_chapters_outline(_parsed_doc(blocks), entries)
    assert units is not None
    assert [t for t, _ in units] == ["Chapter 1. Intro", "Part II", "Chapter 2. Estimation"]


def test_split_chapters_outline_drives_summarize_book_unmodified(monkeypatch, make_groups):
    """The experiment's actual integration seam: `summarize_book()`'s own source is never
    touched -- the module-level `_split_chapters` NAME it calls is substituted for the duration
    of one call (`app/exp1_outline_split.py` does this for real with `unittest.mock.patch`;
    `monkeypatch.setattr` here is the same substitution, pytest's own idiom for it). This proves
    the two functions really are interchangeable at that seam, not just shape-compatible on paper.
    """
    import rag.book_summarizer as book_summarizer

    blocks = [
        _block("word " * 20, "front", 0, page=0),
        _block("word " * 3000, "ch1", 1, page=5),
        _block("word " * 3000, "ch2", 2, page=12),
    ]
    entries = [
        OutlineEntry(0, "Chapter 1. Intro", 5),
        OutlineEntry(0, "Chapter 2. Estimation", 12),
    ]
    parsed = _parsed_doc(blocks)

    monkeypatch.setattr(
        book_summarizer,
        "_split_chapters",
        lambda p: _split_chapters_outline(p, entries),
    )
    _, chapters = summarize_book(parsed, FakeSummarizer())

    assert [c.title for c in chapters] == ["Chapter 1. Intro", "Chapter 2. Estimation"]
