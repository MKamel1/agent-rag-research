"""Tests for scripts/truncation_census.py (RI-M4) -- fixture content built to sit on both sides
of each real ceiling, not real corpus data (this instrument is proved on fixtures; running it
against a real corpus is operator work, per the module docstring)."""

from datetime import date

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from rag.reranker import (
    _MAX_BATCH_SIZE,
    _MAX_BATCH_TOKENS,
    _estimate_tokens,
    _truncate_to_item_budget,
)
from rag.summarizer import _NUM_CTX_CEILING, _PROMPT_OVERHEAD_TOKENS, _TOKENS_PER_WORD_ESTIMATE
from scripts.truncation_census import (
    BindTally,
    build_census,
    calibrate_estimate,
    top_offenders,
)

PAPER_ID = "2506.01234"
BBOX = (0.0, 0.0, 100.0, 200.0)


def make_ref(**o) -> PaperRef:
    f = dict(
        paper_id=PAPER_ID, version="v1", title="A Causal Method", abstract="We propose...",
        authors=["A. Author"], categories=["cs.LG"], published=date(2026, 6, 1),
        updated=date(2026, 6, 1), pdf_url="https://arxiv.org/pdf/2506.01234v1",
    )
    f.update(o)
    return PaperRef(**f)


def make_block(**o) -> Block:
    f = dict(
        block_id=f"{PAPER_ID}:b0", paper_id=PAPER_ID, text="Some prose.", type="prose", page=0,
        bbox=BBOX, section_path="1. Intro", index=0,
    )
    f.update(o)
    return Block(**f)


def make_parsed(**o) -> ParsedDoc:
    f = dict(
        paper_id=PAPER_ID, markdown="# Title\nSome body text.", blocks=[make_block()],
        figures=[], tables=[], references=[], parser_id="test-parser-1.x",
    )
    f.update(o)
    return ParsedDoc(**f)


def make_chunk(**o) -> Chunk:
    f = dict(
        chunk_id=f"{PAPER_ID}:c0", paper_id=PAPER_ID, text="Some chunk text.",
        anchor=Anchor(
            paper_id=PAPER_ID, block_id=f"{PAPER_ID}:b0", page=0, bbox=BBOX,
            snippet="Some chunk text.", section_path="1. Intro",
        ),
        section_path="1. Intro", parent_id=f"{PAPER_ID}:b0",
    )
    f.update(o)
    return Chunk(**f)


def make_record(**o) -> PaperRecord:
    f = dict(
        ref=make_ref(), parsed=make_parsed(), chunks=[make_chunk()],
        summary_text="A short summary.", summary_id=f"{PAPER_ID}:summary",
    )
    f.update(o)
    return PaperRecord(**f)


# --------------------------------------------------------------------------------------------
# Reranker item ceiling (_MAX_ITEM_TOKENS) -- the limit that actually drops text.
# --------------------------------------------------------------------------------------------


def test_reranker_item_ceiling_binds_on_an_oversized_chunk():
    huge_text = "word " * 20_000  # ~100,000 chars, comfortably over the 24,000-char item budget
    record = make_record(chunks=[make_chunk(text=huge_text)])

    census = build_census([record])

    tally = census.reranker_item.overall
    assert tally.total == 1
    assert tally.bound == 1
    assert tally.dropped > 0
    assert census.reranker_item.by_doc_type["paper"].bound == 1


def test_reranker_item_ceiling_not_bound_on_a_small_chunk():
    record = make_record(chunks=[make_chunk(text="A short chunk.")])

    census = build_census([record])

    tally = census.reranker_item.overall
    assert tally.total == 1
    assert tally.bound == 0
    assert tally.dropped == 0


def test_reranker_item_dropped_amount_matches_the_real_truncation():
    huge_text = "word " * 20_000
    record = make_record(chunks=[make_chunk(text=huge_text)])

    census = build_census([record])

    # Sibling-path check (CONVENTIONS.md §14): the reported drop is not just "nonzero", it is
    # the exact token gap the real _truncate_to_item_budget/_estimate_tokens pair produces.
    expected_dropped = _estimate_tokens(huge_text) - _estimate_tokens(
        _truncate_to_item_budget(huge_text)
    )
    assert census.reranker_item.overall.dropped == expected_dropped


# --------------------------------------------------------------------------------------------
# Reranker batch-budget pressure (_MAX_BATCH_TOKENS) -- drops nothing, just forces an extra
# HTTP call earlier than item-count alone would.
# --------------------------------------------------------------------------------------------


def test_batch_pressure_can_bind_even_when_the_item_ceiling_does_not():
    # ~1000 chars: well under _MAX_ITEM_TOKENS (8,000 tokens) so the item ceiling never fires,
    # but big enough that _MAX_BATCH_TOKENS / _MAX_BATCH_SIZE ("fair share" per batch slot) is
    # exceeded once the representative query's own tokens are added in.
    text = "word " * 250
    record = make_record(chunks=[make_chunk(text=text)])

    census = build_census([record])

    assert census.reranker_item.overall.bound == 0
    assert census.reranker_batch_pressure.overall.bound == 1
    # The batch limit never drops text -- only the item ceiling does.
    assert census.reranker_batch_pressure.overall.dropped == 0


def test_batch_pressure_not_bound_on_a_tiny_chunk():
    record = make_record(chunks=[make_chunk(text="tiny")])

    census = build_census([record])

    assert census.reranker_batch_pressure.overall.bound == 0


def test_fair_share_threshold_matches_the_real_batch_constants():
    # Anchors this test file's assumption to the real constants, so a future retune of either
    # constant is caught here instead of silently invalidating the fixture's premise.
    assert _MAX_BATCH_TOKENS / _MAX_BATCH_SIZE == 375.0


# --------------------------------------------------------------------------------------------
# Summarizer ceiling (_NUM_CTX_CEILING / _TOKENS_PER_WORD_ESTIMATE) -- whole document for
# doc_type="paper", per-chapter/window for doc_type="book".
# --------------------------------------------------------------------------------------------


def test_summarizer_ceiling_binds_on_a_long_paper():
    long_markdown = "# Title\n" + ("word " * 20_000)
    record = make_record(parsed=make_parsed(markdown=long_markdown))

    census = build_census([record])

    tally = census.summarizer_ceiling.overall
    assert tally.bound == 1
    assert tally.dropped > 0
    assert census.summarizer_ceiling.by_doc_type["paper"].bound == 1


def test_summarizer_ceiling_not_bound_on_a_short_paper():
    record = make_record(parsed=make_parsed(markdown="# Title\nShort body."))

    census = build_census([record])

    assert census.summarizer_ceiling.overall.bound == 0


def test_book_chapter_windowing_keeps_every_window_under_the_ceiling():
    # One heading group (all blocks share a top-level section_path) with more words than
    # _MAX_CHAPTER_WORDS -- rag.book_summarizer's own windowing splits it before summarize() is
    # ever called, and _MAX_CHAPTER_WORDS (6,000) is comfortably under the ceiling's own
    # ~7,356-word budget. This empirically checks that book chapters never reach
    # _NUM_CTX_CEILING by construction, rather than asserting it from reading the code alone.
    huge_chapter = "word " * 10_000
    blocks = [
        make_block(block_id=f"{PAPER_ID}:b0", text=huge_chapter, section_path="Chapter 1",
                   index=0),
    ]
    record = make_record(
        ref=make_ref(doc_type="book"),
        parsed=make_parsed(blocks=blocks),
    )

    census = build_census([record])

    book_tally = census.summarizer_ceiling.by_doc_type["book"]
    assert book_tally.total == 2  # 10,000 words split into two 6,000/4,000-word windows
    assert book_tally.bound == 0, "each window individually must stay under the ceiling"


def test_book_chapter_under_max_words_is_not_windowed():
    small_chapter = "word " * 100
    blocks = [make_block(text=small_chapter, section_path="Chapter 1")]
    record = make_record(ref=make_ref(doc_type="book"), parsed=make_parsed(blocks=blocks))

    census = build_census([record])

    book_tally = census.summarizer_ceiling.by_doc_type["book"]
    assert book_tally.total == 1
    assert book_tally.bound == 0


# --------------------------------------------------------------------------------------------
# Estimate calibration -- honesty when unmeasured, real math when it is.
# --------------------------------------------------------------------------------------------


def test_calibration_not_measured_without_real_token_counts():
    record = make_record()

    census = build_census([record])

    assert census.estimate_calibration.measured is False
    assert "not recoverable" in census.estimate_calibration.note


def test_calibration_reports_stats_when_real_counts_are_supplied():
    words_sent = {"p1": 1000, "p2": 7000}
    real_token_counts = {
        "p1": int(1000 * _TOKENS_PER_WORD_ESTIMATE),  # exact match -- zero error
        "p2": 20_000,  # the estimate badly undercounts this one
    }

    calibration = calibrate_estimate(words_sent, real_token_counts)

    assert calibration.measured is True
    assert calibration.n == 2
    assert calibration.underestimate_rate == 0.5
    assert calibration.max_underestimate_tokens == 20_000 - int(7000 * _TOKENS_PER_WORD_ESTIMATE)
    # The estimate said p2 fit the ceiling; a real count of 20,000 would not have.
    estimated_p2 = int(7000 * _TOKENS_PER_WORD_ESTIMATE)
    assert estimated_p2 + _PROMPT_OVERHEAD_TOKENS <= _NUM_CTX_CEILING
    assert 20_000 + _PROMPT_OVERHEAD_TOKENS > _NUM_CTX_CEILING
    assert calibration.false_fit_count == 1


def test_calibration_ignores_real_counts_for_units_never_measured():
    words_sent = {"p1": 1000}
    real_token_counts = {"someone-elses-unit": 999}

    calibration = calibrate_estimate(words_sent, real_token_counts)

    assert calibration.measured is False
    assert "no unit id in common" in calibration.note


# --------------------------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------------------------


def test_top_offenders_sorts_by_dropped_and_skips_units_never_bound():
    groups = {
        "a": BindTally(total=5, bound=1, dropped=10),
        "b": BindTally(total=5, bound=2, dropped=50),
        "c": BindTally(total=5, bound=0, dropped=0),  # never bound -- must not appear
    }

    ranked = top_offenders(groups, n=10)

    assert [key for key, _ in ranked] == ["b", "a"]


def test_census_groups_by_paper_so_concentration_is_visible():
    quiet = make_record(
        ref=make_ref(paper_id="quiet"), chunks=[make_chunk(paper_id="quiet", text="short")],
    )
    loud_text = "word " * 20_000
    loud = make_record(
        ref=make_ref(paper_id="loud"), chunks=[make_chunk(paper_id="loud", text=loud_text)],
    )

    census = build_census([quiet, loud])

    assert census.papers_scanned == 2
    assert census.reranker_item.by_paper["loud"].bound == 1
    assert census.reranker_item.by_paper["quiet"].bound == 0
