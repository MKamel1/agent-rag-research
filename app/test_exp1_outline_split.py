"""`app/exp1_outline_split.py` test suite -- Experiment 1 orchestration script. Zero-GPU,
zero-network, zero-corpus (TEST-STRATEGY.md golden rule): drives the module's pure/synchronous
logic (row->Block reconstruction, the collection-not-production guard, duplicate-title/word-share
reporting, and the eval-fixture re-derivation) against small synthetic fixtures, no real `sqlite3`
connection, PDF, `DocumentStore`, `VectorIndex`, or GPU-backed adapter.

`compute_splits`/`load_outline_entries`/`build_throwaway_db`/`write_new_chapters`/
`clone_production_collection`/`swap_chapter_vectors`/`summarize_with_outline_split`/`main` all
touch a real corpus connection, PDF, throwaway SQLite copy, live Qdrant, or the real GPU-backed
Summarizer/Embedder -- deliberately NOT exercised here, same "compose real adapters only at the
very edge, test the logic against fakes" split `app/reembed_experiment.py`'s own test file follows
(that file's docstring: "`reembed()` (not `__main__`) is the unit under test"). This run's actual
end-to-end behavior is exercised by the real corpus/GPU run itself (see
docs/eval-reports/2026-07-29-exp1-outline-split-ab.md) and by `rag/book_summarizer.py`'s own
`_split_chapters_outline` unit tests, which this script only orchestrates, never reimplements.
"""

from app.exp1_outline_split import (
    BookSplit,
    Exp1Error,
    _block_id_to_unit_index,
    _check_collection_is_not_production,
    _row_to_block,
    duplicate_titles,
    rederive_fixture,
    split_report,
)
from contracts.document_store import ChapterSummary
from contracts.parser import ParsedDoc
from contracts.provenance import Block

PAPER_ID = "local:deadbeef0000"


def _block(idx: int, text: str) -> Block:
    return Block(
        block_id=f"{PAPER_ID}:b{idx}",
        paper_id=PAPER_ID,
        text=text,
        type="prose",
        page=0,
        bbox=(0.0, 0.0, 100.0, 200.0),
        section_path="",
        index=idx,
    )


def test_check_collection_is_not_production_refuses_a_match():
    try:
        _check_collection_is_not_production("papers", "papers")
        assert False, "expected Exp1Error"
    except Exp1Error:
        pass


def test_check_collection_is_not_production_allows_a_throwaway_name():
    _check_collection_is_not_production("exp1_outline_chapters", "papers")  # no raise


def test_row_to_block_matches_document_store_construction():
    # Same shape rag/document_store.py's DocumentStore._row_to_block builds from -- a plain dict
    # stands in for sqlite3.Row (both support string-keyed __getitem__).
    row = {
        "block_id": f"{PAPER_ID}:b0",
        "paper_id": PAPER_ID,
        "text": "hello",
        "type": "prose",
        "page": 3,
        "bbox_json": "[0.0, 0.0, 100.0, 200.0]",
        "section_path": "Ch1",
        "idx": 0,
    }
    block = _row_to_block(row)
    assert block.block_id == f"{PAPER_ID}:b0"
    assert block.page == 3
    assert block.bbox == (0.0, 0.0, 100.0, 200.0)
    assert block.index == 0


def test_duplicate_titles_flags_only_repeated_nonempty_titles():
    units = [("", [_block(0, "x")]), ("A", [_block(1, "x")]), ("A", [_block(2, "x")]),
             ("B", [_block(3, "x")])]
    assert duplicate_titles(units) == ["A"]


def test_duplicate_titles_empty_when_all_unique():
    units = [("A", [_block(0, "x")]), ("B", [_block(1, "x")])]
    assert duplicate_titles(units) == []


def test_split_report_computes_word_shares_and_duplicates():
    blocks_a = [_block(0, "word " * 100)]
    blocks_b = [_block(1, "word " * 300)]
    units = [("A", blocks_a), ("A", blocks_b)]
    parsed = ParsedDoc(
        paper_id=PAPER_ID, markdown="", blocks=blocks_a + blocks_b, figures=[], tables=[],
        references=[], parser_id="test",
    )
    report = split_report({PAPER_ID: BookSplit(PAPER_ID, parsed, units)})
    r = report[PAPER_ID]
    assert r["unit_count"] == 2
    assert r["duplicate_titles"] == ["A"]
    assert r["word_share_min"] == 100 / 400
    assert r["word_share_max"] == 300 / 400


def test_block_id_to_unit_index_maps_every_block_to_its_unit():
    units = [("A", [_block(0, "x"), _block(1, "x")]), ("B", [_block(2, "x")])]
    mapping = _block_id_to_unit_index(units)
    assert mapping[f"{PAPER_ID}:b0"] == 0
    assert mapping[f"{PAPER_ID}:b1"] == 0
    assert mapping[f"{PAPER_ID}:b2"] == 1


def _fixture(records: list[dict]) -> dict:
    return {"_metadata": {"note": "test fixture"}, "ground_truth": records}


def test_rederive_fixture_updates_touched_book_and_preserves_untouched_book():
    touched_units = [("Front", [_block(0, "x")]), ("Chapter 1", [_block(1, "x")])]
    parsed = ParsedDoc(
        paper_id=PAPER_ID, markdown="", blocks=[b for _, bs in touched_units for b in bs],
        figures=[], tables=[], references=[], parser_id="test",
    )
    splits = {PAPER_ID: BookSplit(PAPER_ID, parsed, touched_units)}
    final_chapters = {
        PAPER_ID: [
            ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch0", title="Front", text="t"),
            ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch1", title="Chapter 1", text="t"),
        ]
    }
    old_fixture = _fixture([
        {
            "question_id": "Q1", "source_paper_id": PAPER_ID,
            "gold_block_id": f"{PAPER_ID}:b1", "gold_chapter_title": "STALE",
            "gold_chapter_index": 99,
        },
        {
            "question_id": "Q2", "source_paper_id": "local:untouched",
            "gold_block_id": "local:untouched:b0", "gold_chapter_title": "Unchanged",
            "gold_chapter_index": 0,
        },
    ])

    new_fixture, unmapped = rederive_fixture(old_fixture, splits, final_chapters)

    assert unmapped == []
    by_id = {r["question_id"]: r for r in new_fixture["ground_truth"]}
    assert by_id["Q1"]["gold_chapter_title"] == "Chapter 1"
    assert by_id["Q1"]["gold_chapter_index"] == 1
    assert by_id["Q2"]["gold_chapter_title"] == "Unchanged"  # untouched book carried over verbatim
    assert by_id["Q2"] == old_fixture["ground_truth"][1]  # byte-for-byte, not just the title field


def test_rederive_fixture_surfaces_a_gold_block_id_outside_every_unit():
    touched_units = [("Chapter 1", [_block(0, "x")])]
    parsed = ParsedDoc(
        paper_id=PAPER_ID, markdown="", blocks=[_block(0, "x")], figures=[], tables=[],
        references=[], parser_id="test",
    )
    splits = {PAPER_ID: BookSplit(PAPER_ID, parsed, touched_units)}
    final_chapters = {
        PAPER_ID: [ChapterSummary(summary_id=f"{PAPER_ID}:summary:ch0", title="Chapter 1", text="t")]
    }
    old_fixture = _fixture([
        {
            "question_id": "Q1", "source_paper_id": PAPER_ID,
            "gold_block_id": f"{PAPER_ID}:b999",  # not in any unit
            "gold_chapter_title": "STALE", "gold_chapter_index": 0,
        },
    ])

    _, unmapped = rederive_fixture(old_fixture, splits, final_chapters)

    assert unmapped == ["Q1"]
