"""`app/exp3_hierarchy_sim.py` test suite -- Experiment 3 simulation script. Zero-GPU, zero-network,
zero-corpus (TEST-STRATEGY.md golden rule), same split `app/test_exp1_outline_split.py` already
follows: only the pure/synchronous logic (level-parent detection, boundary/title construction,
part-routing math, candidate-list restriction, rank lookup) is exercised here. `survey_books`,
`build_hierarchy`, `run_flat_arm`, `run_hierarchical_arm`, `stage_exp1_db_copy`, `main` all touch a
real corpus connection, PDF, throwaway db copy, a live vector store, or the real GPU-backed embedder --
deliberately not exercised here; this run's actual end-to-end behavior is exercised by the real
run itself (see docs/eval-reports/2026-07-29-exp3-hierarchy-simulation.md).
"""

from app.exp3_hierarchy_sim import (
    assign_boundary,
    boundary_titles,
    chapter_to_part,
    rank_of,
    recall_mrr,
    restrict_and_rank,
    route_part,
    usable_parent_level,
)
from rag.book_summarizer import OutlineEntry


def _entry(level: int, title: str, page: int) -> OutlineEntry:
    return OutlineEntry(level=level, title=title, page_index=page)


def test_usable_parent_level_finds_coarser_level_when_chapters_are_nested():
    # Mirrors Causal Inference in Python: Parts at level 0, "Chapter N" markers at level 1 -- the
    # picked chapter level (1) has a coarser level (0) above it.
    entries = [
        _entry(0, "Part I. Fundamentals", 22),
        _entry(0, "Part II. Adjusting for Bias", 114),
        _entry(1, "Chapter 1. Introduction", 24),
        _entry(1, "Chapter 2. Randomized Experiments", 52),
        _entry(1, "Chapter 3. Graphical Causal Models", 82),
    ]
    assert usable_parent_level(entries) == 0


def test_usable_parent_level_none_when_chapters_are_already_outermost():
    # Mirrors the other 3 outline-bearing books: chapters picked AT level 0, nothing coarser exists.
    entries = [
        _entry(0, "Chapter 1: Intro", 0),
        _entry(0, "Chapter 2: More", 40),
        _entry(1, "Some subsection", 5),
    ]
    assert usable_parent_level(entries) is None


def test_usable_parent_level_none_with_no_markers_falls_back_to_level_0():
    entries = [_entry(0, "Introduction", 0), _entry(0, "Methods", 40)]
    assert usable_parent_level(entries) is None


def test_boundary_titles_dedupes_by_page_earliest_wins():
    entries = [
        _entry(0, "About the Author", 407),
        _entry(0, "Colophon", 407),  # same page as above -- earliest listed wins the title
        _entry(0, "Index", 388),
    ]
    boundaries, titles = boundary_titles(entries, 0)
    assert boundaries == [388, 407]
    assert titles == {388: "Index", 407: "About the Author"}


def test_assign_boundary_picks_last_boundary_at_or_before_page():
    boundaries = [0, 22, 114, 198]
    assert assign_boundary(0, boundaries) == 0
    assert assign_boundary(21, boundaries) == 0
    assert assign_boundary(22, boundaries) == 1
    assert assign_boundary(200, boundaries) == 3


def test_chapter_to_part_maps_each_chapter_to_its_enclosing_part():
    part_boundaries = [0, 22, 114]
    first_pages = [0, 24, 52, 116]
    assert chapter_to_part(first_pages, part_boundaries) == [0, 1, 1, 2]


def test_route_part_picks_highest_cosine_similarity():
    # L2-normalized 2D vectors, same contract TeiEmbedder.embed() documents.
    qvec = [1.0, 0.0]
    part_vecs = [[0.0, 1.0], [0.9, 0.1], [1.0, 0.0]]
    assert route_part(qvec, part_vecs) == 2


def test_restrict_and_rank_keeps_only_allowed_ids_in_existing_order():
    hit_ids = ["a", "b", "c", "d", "e"]
    allowed = {"b", "d"}
    assert restrict_and_rank(hit_ids, allowed, k=10) == ["b", "d"]


def test_restrict_and_rank_truncates_to_k():
    hit_ids = ["a", "b", "c"]
    allowed = {"a", "b", "c"}
    assert restrict_and_rank(hit_ids, allowed, k=2) == ["a", "b"]


def test_rank_of_returns_1_indexed_position_or_none():
    ranked = ["x", "y", "z"]
    assert rank_of("y", ranked) == 2
    assert rank_of("missing", ranked) is None


def test_recall_mrr_matches_hand_computed_values():
    m = recall_mrr([1, None, 3, None])
    assert m["n"] == 4
    assert m["recall_at_k"] == 0.5
    assert m["mrr"] == (1.0 + 1 / 3) / 4


def test_recall_mrr_empty_is_none_not_zero_division():
    assert recall_mrr([]) == {"recall_at_k": None, "mrr": None, "n": 0}
