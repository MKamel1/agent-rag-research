#!/usr/bin/env python3
"""W-A4 author-A helper: pull verbatim excerpts from papers.db and run lexical
absence probes over the chunks table. Read-only against papers.db; writes
nothing but stdout/JSON the caller redirects. Not a general-purpose tool --
scoped to this one authoring task (SB-2/W-A4/author-A).
"""
import difflib
import json
import sqlite3
import sys

DB = "/home/omar/ai-projects/research-system-rag/waymo/data/papers.db"
CHUNK_DENOM = 46155
BLOCK_DENOM = 235918


def con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def get_block(block_id):
    c = con()
    row = c.execute(
        "SELECT paper_id, section_path, text FROM blocks WHERE block_id=?", (block_id,)
    ).fetchone()
    c.close()
    if not row:
        raise ValueError(f"block not found: {block_id}")
    return {"paper_id": row[0], "section_path": row[1], "text": row[2]}


def chunk_texts_for_block(block_id):
    """Chunks belonging to the same paper as block_id -- a chunk's own text
    spans a run of consecutive blocks (its anchor_json.block_id is only the
    *first* block of that run), so fidelity is checked against every chunk in
    the paper, not just the one anchored at this exact block_id."""
    paper_id = block_id.rsplit(":", 1)[0]
    c = con()
    rows = c.execute("SELECT chunk_id, text FROM chunks WHERE paper_id=?", (paper_id,)).fetchall()
    c.close()
    return rows


def fidelity(excerpt, served_text):
    """Coverage of excerpt against served_text: 1.0 if excerpt is a normalized
    substring, else the best difflib match ratio."""
    norm_e = " ".join(excerpt.split())
    norm_t = " ".join(served_text.split())
    if norm_e in norm_t:
        return 1.0
    sm = difflib.SequenceMatcher(None, norm_e, norm_t)
    match = sm.find_longest_match(0, len(norm_e), 0, len(norm_t))
    return match.size / max(1, len(norm_e))


def lexical_probe(term, table="chunks"):
    assert table in ("chunks", "blocks")
    c = con()
    n = c.execute(f"SELECT COUNT(*) FROM {table} WHERE text LIKE ?", (f"%{term}%",)).fetchone()[0]
    c.close()
    denom = CHUNK_DENOM if table == "chunks" else BLOCK_DENOM
    return {"query": term, "hits": n, "denominator": denom, "table": table}


def paper_scoped_probe(term, paper_id):
    """Hits for `term` restricted to one paper's own chunks, denominator =
    that paper's chunk count -- the sharpest check that a specific paper's
    own text never states the claimed-absent fact."""
    c = con()
    denom = c.execute("SELECT COUNT(*) FROM chunks WHERE paper_id=?", (paper_id,)).fetchone()[0]
    n = c.execute(
        "SELECT COUNT(*) FROM chunks WHERE paper_id=? AND text LIKE ?", (paper_id, f"%{term}%")
    ).fetchone()[0]
    c.close()
    return {"query": term, "hits": n, "denominator": denom, "table": "chunks", "scope": f"paper:{paper_id}"}


def paper_title(paper_id):
    c = con()
    row = c.execute("SELECT title FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
    c.close()
    return row[0] if row else None


def _selfcheck():
    assert fidelity("the cat sat", "the cat sat on the mat") == 1.0
    assert fidelity("completely unrelated text", "the cat sat on the mat") < 0.5
    print("selfcheck ok")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "test":
        _selfcheck()
    elif cmd == "block":
        print(json.dumps(get_block(sys.argv[2]), indent=2))
    elif cmd == "fidelity":
        block_id = sys.argv[2]
        excerpt = sys.argv[3]
        chunks = chunk_texts_for_block(block_id)
        if not chunks:
            print(json.dumps({"error": "no chunk references this block_id", "block_id": block_id}))
        else:
            best = max(fidelity(excerpt, t) for _, t in chunks)
            print(json.dumps({"block_id": block_id, "n_chunks": len(chunks), "best_coverage": best}))
    elif cmd == "probe":
        table = sys.argv[3] if len(sys.argv) > 3 else "chunks"
        print(json.dumps(lexical_probe(sys.argv[2], table)))
    elif cmd == "title":
        print(paper_title(sys.argv[2]))
    else:
        print("usage: wa4_author_a_probe.py {block|fidelity|probe|title} ...", file=sys.stderr)
        sys.exit(1)
