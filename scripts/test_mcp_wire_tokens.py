"""Tests for scripts/mcp_wire_tokens.py on a tiny throwaway papers.db (opened read-only by the script)."""

import json
import sqlite3

from scripts.mcp_wire_tokens import measure, sample_results


def _db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE papers (paper_id TEXT, title TEXT, authors_json TEXT, pdf_path TEXT, "
                "doc_type TEXT)")
    con.execute("CREATE TABLE chunks (chunk_id TEXT, paper_id TEXT, text TEXT, anchor_json TEXT, "
                "section_path TEXT)")
    con.execute("INSERT INTO papers VALUES ('p1', 'A Standard', '[\"X\"]', 'x.pdf', 'paper')")
    for i in range(12):
        anchor = {"paper_id": "p1", "block_id": f"p1:b{i}", "page": 1, "bbox": [0, 0, 1, 1],
                  "snippet": "s", "section_path": "3 Scope"}
        con.execute("INSERT INTO chunks VALUES (?, 'p1', ?, ?, '3 Scope')",
                    (f"p1:c{i}", "passage " * 40, json.dumps(anchor)))
    con.commit()
    con.close()


def test_projection_is_measurably_smaller_on_sampled_real_shaped_chunks(tmp_path):
    db = tmp_path / "papers.db"
    _db(db)
    results = sample_results(str(db), 12)
    unit, full, wire = measure(results, k=5, batches=5)
    assert len(results) == 12 and wire < full
