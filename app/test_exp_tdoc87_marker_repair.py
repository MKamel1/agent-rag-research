"""`app/exp_tdoc87_marker_repair.py` test suite. Zero-GPU, zero-network, zero-corpus
(TEST-STRATEGY.md golden rule). This module reuses almost all of its infrastructure directly from
`app/exp1_outline_split.py` -- that reused code (`_check_collection_is_not_production`,
`duplicate_titles`, `split_report`, `rederive_fixture`, `_row_to_block`/`load_blocks_readonly`
plumbing) is already covered by `app/test_exp1_outline_split.py` and is not re-tested here.

The only new logic this module adds is `compute_splits`: load each of `BOOK_IDS`'s blocks from a
`sqlite3.Connection` and run them through the ALREADY-REPAIRED `book_summarizer._split_chapters`
(no outline, no `mock.patch` substitution -- see the module docstring for why). Exercised here
against a real in-memory sqlite3 connection carrying the same `blocks` table shape
`papers.db` has, not a real corpus file.
"""

import sqlite3

import pytest

from app.exp_tdoc87_marker_repair import BOOK_IDS, TDoc87Error, compute_splits

_BLOCKS_SCHEMA = """
CREATE TABLE blocks (
  block_id     TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL,
  idx          INTEGER NOT NULL,
  type         TEXT NOT NULL,
  text         TEXT NOT NULL,
  page         INTEGER NOT NULL,
  bbox_json    TEXT NOT NULL,
  section_path TEXT NOT NULL
)
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(_BLOCKS_SCHEMA)
    yield c
    c.close()


def _insert(conn, paper_id: str, idx: int, section_path: str, text: str) -> None:
    conn.execute(
        "INSERT INTO blocks VALUES (?, ?, ?, 'prose', ?, 0, '[0.0,0.0,100.0,200.0]', ?)",
        (f"{paper_id}:b{idx}", paper_id, idx, text, section_path),
    )


def test_compute_splits_covers_every_book_id(conn):
    for paper_id in BOOK_IDS:
        for i, title in enumerate(["Chapter 1 A", "Chapter 2 B", "Chapter 3 C"]):
            _insert(conn, paper_id, i, title, "word " * 200)
    conn.commit()

    splits = compute_splits(conn)

    assert set(splits) == set(BOOK_IDS)


def test_compute_splits_uses_the_live_repaired_split_chapters(conn):
    # Two numbered-list-item headings ("1. https://...", "3. Finally, let's look...") that skip 2
    # -- the exact non-sequential shape T-DOC87's repaired `_bare_numbers_are_sequential` rejects
    # (rag/test_book_summarizer.py already pins that logic; this only confirms `compute_splits`
    # actually reaches the LIVE repaired function, not a stale/reimplemented copy). Pre-repair,
    # each numbered heading became its own chapter (4 units); repaired, neither is a real chapter
    # boundary, so word-share merging collapses all 4 tiny groups into 1 unit.
    paper_id = BOOK_IDS[0]
    _insert(conn, paper_id, 0, "Preface", "word " * 200)
    _insert(conn, paper_id, 1, "1. https://example.com/bogus", "word " * 200)
    _insert(conn, paper_id, 2, "Body", "word " * 200)
    _insert(conn, paper_id, 3, "3. Finally, let's look at Table 3.1", "word " * 200)
    conn.commit()

    splits = compute_splits(conn)

    assert len(splits[paper_id].units) == 1, (
        f"expected the non-sequential bare markers to fall back to size-merge, "
        f"got {len(splits[paper_id].units)} units: {[t for t, _ in splits[paper_id].units]}"
    )


def test_tdoc87_error_is_a_runtime_error():
    assert issubclass(TDoc87Error, RuntimeError)
