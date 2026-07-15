"""Tests for `app.corpus_integrity` (T-DOC35) -- synthetic in-memory-equivalent SQLite DB, zero-GPU,
zero-network (CONVENTIONS.md §12): builds a real schema via `migrations/migrate.py` against a temp
file (sqlite3's `:memory:` can't be reused across `migrate()`'s own connection + this test's
connection), then inserts minimal rows directly -- no ingest pipeline involved.
"""

import sqlite3

from app.corpus_integrity import IntegrityOffender, find_done_papers_without_chunks
from migrations.migrate import migrate


def _db(tmp_path):
    path = str(tmp_path / "papers.db")
    migrate(path)
    return sqlite3.connect(path)


def _insert_paper(conn, paper_id: str, stage: str, with_chunk: bool, with_block: bool) -> None:
    conn.execute(
        """
        INSERT INTO papers
            (paper_id, version, title, abstract, authors_json, categories_json,
             published, updated, pdf_path, markdown_path, relevance_score)
        VALUES (?, 'v1', 't', 'a', '[]', '[]', '2026-01-01', '2026-01-01', 'p', 'm.md', 0.5)
        """,
        (paper_id,),
    )
    conn.execute(
        "INSERT INTO ingest_state (paper_id, stage, updated_at) VALUES (?, ?, '2026-01-01T00:00:00Z')",
        (paper_id, stage),
    )
    if with_chunk:
        conn.execute(
            """
            INSERT INTO chunks (chunk_id, paper_id, text, anchor_json, section_path, parent_id,
                                 contextual_header)
            VALUES (?, ?, 'text', '{}', 'sec', NULL, NULL)
            """,
            (f"{paper_id}:chunk:0", paper_id),
        )
    if with_block:
        conn.execute(
            """
            INSERT INTO blocks (block_id, paper_id, idx, type, text, page, bbox_json, section_path)
            VALUES (?, ?, 0, 'text', 'text', 0, '[0,0,0,0]', 'sec')
            """,
            (f"{paper_id}:block:0", paper_id),
        )
    conn.commit()


def test_flags_a_done_paper_with_zero_chunks_and_blocks(tmp_path):
    conn = _db(tmp_path)
    _insert_paper(conn, "2411.14665", stage="done", with_chunk=False, with_block=False)

    offenders = find_done_papers_without_chunks(conn)

    assert offenders == [IntegrityOffender(paper_id="2411.14665", chunk_count=0, block_count=0)]


def test_passes_a_healthy_done_paper(tmp_path):
    conn = _db(tmp_path)
    _insert_paper(conn, "2411.14665", stage="done", with_chunk=True, with_block=True)

    assert find_done_papers_without_chunks(conn) == []


def test_ignores_a_not_yet_done_paper_with_no_chunks(tmp_path):
    conn = _db(tmp_path)
    _insert_paper(conn, "2411.14665", stage="chunked", with_chunk=False, with_block=False)

    assert find_done_papers_without_chunks(conn) == []


def test_flags_a_done_paper_with_blocks_but_no_chunks(tmp_path):
    conn = _db(tmp_path)
    _insert_paper(conn, "2411.14665", stage="done", with_chunk=False, with_block=True)

    offenders = find_done_papers_without_chunks(conn)

    assert offenders == [IntegrityOffender(paper_id="2411.14665", chunk_count=0, block_count=1)]
