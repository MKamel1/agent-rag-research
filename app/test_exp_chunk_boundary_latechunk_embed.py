"""Tests for `app/exp_chunk_boundary_latechunk_embed.py` -- SB-1 arm (a).

Zero-GPU, zero-network: every function here is a pure `(PaperRecord, Chunk) -> str` text
transform or an offline counter -- no DocumentStore/embedder/vector-store instance is ever
constructed. Fixtures build minimal real `contracts.chunker.Chunk` / `contracts.document_store.
PaperRecord` objects directly rather than touching `papers.db`.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.exp_chunk_boundary_latechunk_embed import (
    build_section_context_text,
    make_embed_text_fn,
    price_corpus,
    sorted_chunks,
)
from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor
from contracts.harvester import PaperRef


def _chunk(paper_id: str, index: int, text: str, section_path: str = "S1") -> Chunk:
    return Chunk(
        chunk_id=f"{paper_id}:c{index}",
        paper_id=paper_id,
        text=text,
        anchor=Anchor(
            paper_id=paper_id, block_id=f"{paper_id}:b{index}", page=1, bbox=[0, 0, 1, 1],
            snippet=text[:50], section_path=section_path,
        ),
        section_path=section_path,
        parent_id=f"{paper_id}:b{index}",
    )


def _record(paper_id: str, chunks: list[Chunk]) -> PaperRecord:
    ref = PaperRef(
        paper_id=paper_id, version="v1", title="T", abstract="A", authors=["X"],
        categories=["cs.RO"], published=date(2024, 1, 1), updated=date(2024, 1, 1),
        pdf_url="http://x", doc_type="paper",
    )
    parsed = ParsedDoc(
        paper_id=paper_id, markdown="# T", blocks=[], figures=[], tables=[], references=[],
        parser_id="",
    )
    return PaperRecord(ref=ref, parsed=parsed, chunks=chunks, summary_text="s", summary_id=f"{paper_id}:summary")


# --- sorted_chunks: the DB-row-order caveat --------------------------------------------------


def test_sorted_chunks_reorders_regardless_of_input_order():
    c0 = _chunk("P", 0, "zero")
    c1 = _chunk("P", 1, "one")
    c2 = _chunk("P", 2, "two")
    record = _record("P", [c2, c0, c1])  # deliberately out of order, like an un-ordered DB read

    ordered = sorted_chunks(record)

    assert [c.chunk_id for c in ordered] == ["P:c0", "P:c1", "P:c2"]


# --- build_section_context_text ---------------------------------------------------------------


def test_middle_chunk_gets_both_neighbours_windowed():
    c0 = _chunk("P", 0, "alpha beta gamma delta")
    c1 = _chunk("P", 1, "own own own")
    c2 = _chunk("P", 2, "epsilon zeta eta theta")
    record = _record("P", [c0, c1, c2])

    text = build_section_context_text(record, c1, window_words=2)

    assert text == "gamma delta\n\nown own own\n\nepsilon zeta"


def test_first_chunk_has_no_prev_context():
    c0 = _chunk("P", 0, "own text")
    c1 = _chunk("P", 1, "next text here")
    record = _record("P", [c0, c1])

    text = build_section_context_text(record, c0, window_words=2)

    assert text == "own text\n\nnext text"


def test_last_chunk_has_no_next_context():
    c0 = _chunk("P", 0, "prev text here")
    c1 = _chunk("P", 1, "own text")
    record = _record("P", [c0, c1])

    text = build_section_context_text(record, c1, window_words=2)

    assert text == "text here\n\nown text"


def test_single_chunk_paper_is_identical_to_baseline():
    c0 = _chunk("P", 0, "only chunk here")
    record = _record("P", [c0])

    text = build_section_context_text(record, c0, window_words=100)

    assert text == "only chunk here"


def test_window_words_zero_yields_no_context_at_all():
    c0 = _chunk("P", 0, "a")
    c1 = _chunk("P", 1, "b")
    c2 = _chunk("P", 2, "c")
    record = _record("P", [c0, c1, c2])

    assert build_section_context_text(record, c1, window_words=0) == "b"


def test_unknown_chunk_raises():
    record = _record("P", [_chunk("P", 0, "x")])
    foreign = _chunk("Q", 0, "y")
    with pytest.raises(ValueError):
        build_section_context_text(record, foreign)


# --- make_embed_text_fn: the exact shape reembed()'s embed_text_fn expects --------------------


def test_make_embed_text_fn_matches_direct_call():
    c0 = _chunk("P", 0, "alpha beta")
    c1 = _chunk("P", 1, "gamma delta")
    record = _record("P", [c0, c1])
    fn = make_embed_text_fn(window_words=1)

    assert fn(record, c0) == build_section_context_text(record, c0, window_words=1)


# --- price_corpus: offline dry-run counting -----------------------------------------------------


def test_price_corpus_counts_papers_chunks_and_word_ratio():
    p1 = _record("P1", [_chunk("P1", 0, "one two three"), _chunk("P1", 1, "four five six")])
    p2 = _record("P2", [_chunk("P2", 0, "solo chunk paper")])

    result = price_corpus([p1, p2], window_words=1)

    assert result["n_papers"] == 2
    assert result["n_chunks"] == 3
    assert result["baseline_total_words"] == 3 + 3 + 3
    # p2's single chunk has no neighbours -- arm text == baseline for it. p1's two chunks each
    # gain exactly one neighbour word (window_words=1, one side each).
    assert result["arm_total_words"] == result["baseline_total_words"] + 2
    assert result["arm_vs_baseline_word_ratio"] == pytest.approx(11 / 9)


def test_price_corpus_counts_multi_chunk_sections():
    # Two chunks sharing a section_path (a split-oversized-section case) vs. one that doesn't.
    c0 = _chunk("P", 0, "a", section_path="S1")
    c1 = _chunk("P", 1, "b", section_path="S1")
    c2 = _chunk("P", 2, "c", section_path="S2")
    record = _record("P", [c0, c1, c2])

    result = price_corpus([record])

    assert result["multi_chunk_sections"] == 1  # only S1 has >1 chunk
