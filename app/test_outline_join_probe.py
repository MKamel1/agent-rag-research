"""`app/outline_join_probe.py` -- pure-function tests only (CONVENTIONS.md §12(g) sibling-test
requirement). The script itself is a throwaway, read-only, no-GPU scratch tool (see its own
docstring) whose numbers are already captured in
docs/eval-reports/2026-07-29-outline-join-feasibility.md; this file exists to give its handful of
pure helpers (word matching, level picking, unit building) a runnable check, not to re-derive that
report. `load_toc`/`load_blocks`/`analyze_book`/`main` all touch a real PDF or `papers.db` and are
deliberately not exercised here.
"""

from app.outline_join_probe import (
    MAX_OFFSET,
    ProbeBlock,
    TocEntry,
    _sig_words,
    find_match,
    page_word_index,
    pick_chapter_level,
    units_at_level,
)


def test_sig_words_lowercases_and_drops_stopwords_and_short_tokens():
    assert _sig_words("The Causal Model and Its Effects") == {"causal", "model", "effects"}


def test_find_match_prefers_smaller_offset_on_equal_overlap():
    entry = TocEntry(level=0, title="Chapter One Estimation", page_index=10)
    pages = {9: {"chapter", "one", "estimation"}, 11: {"chapter", "one", "estimation"}}
    result = find_match(entry, pages)
    assert result.offset == -1  # |-1| < |+1|, both are 100% overlap


def test_find_match_rejects_below_threshold():
    entry = TocEntry(level=0, title="Chapter One Estimation", page_index=10)
    pages = {10: {"unrelated", "words", "only"}}
    result = find_match(entry, pages)
    assert result.offset is None


def test_find_match_none_page_index_is_unmatched():
    entry = TocEntry(level=0, title="Cover", page_index=None)
    result = find_match(entry, {0: {"cover"}})
    assert result.offset is None


def test_find_match_searches_within_max_offset_window():
    entry = TocEntry(level=0, title="Estimation Methods", page_index=0)
    pages = {MAX_OFFSET: {"estimation", "methods"}}
    assert find_match(entry, pages).offset == MAX_OFFSET
    pages_too_far = {MAX_OFFSET + 1: {"estimation", "methods"}}
    assert find_match(entry, pages_too_far).offset is None


def _block(idx: int, page: int, text: str) -> ProbeBlock:
    return ProbeBlock(idx=idx, page=page, text=text)


def test_page_word_index_groups_by_page():
    blocks = [_block(0, 0, "Intro text"), _block(1, 0, "more intro"), _block(2, 1, "Chapter one")]
    idx = page_word_index(blocks)
    assert idx[0] == {"intro", "text", "more"}
    assert idx[1] == {"chapter", "one"}


def test_units_at_level_needs_at_least_two_boundaries():
    entries = [TocEntry(level=0, title="Chapter 1", page_index=0)]
    blocks = [_block(0, 0, "word " * 10)]
    assert units_at_level(blocks, entries, level=0) is None


def test_units_at_level_assigns_words_by_page_and_reports_shares():
    entries = [
        TocEntry(level=0, title="Chapter 1", page_index=0),
        TocEntry(level=0, title="Chapter 2", page_index=5),
    ]
    blocks = [_block(0, 0, "word " * 100), _block(1, 5, "word " * 300)]
    stat = units_at_level(blocks, entries, level=0)
    assert stat is not None
    assert stat.num_units == 2
    assert stat.word_shares == sorted([100 / 400, 300 / 400])


def test_pick_chapter_level_falls_back_to_zero_with_no_markers():
    entries = [TocEntry(level=1, title="Some Topic", page_index=0)]
    assert pick_chapter_level(entries) == 0


def test_pick_chapter_level_picks_the_level_with_the_most_markers():
    entries = [
        TocEntry(level=0, title="Part I", page_index=0),
        TocEntry(level=1, title="Chapter 1", page_index=0),
        TocEntry(level=1, title="Chapter 2", page_index=5),
    ]
    assert pick_chapter_level(entries) == 1
