"""Tests for scripts/chunk_quality_census.py (SQLite only, no network/GPU)."""

import sqlite3

from scripts.chunk_quality_census import _BARE_NUMBER, body_of, census


def _chunk(body: str) -> str:
    return f"Title\nSection\n\n{body}"


def test_body_of():
    assert body_of("Title\nSec\n\n  hello  ") == "hello"
    assert body_of("Title\nSec\n\n") == ""
    assert body_of("no separator") == ""


def test_bare_number_regex():
    for ok in ("3.159", "3.1.2", "3.159."):
        assert _BARE_NUMBER.fullmatch(ok)
    for bad in ("3", "3.159 audit", "v3.1", ""):
        assert not _BARE_NUMBER.fullmatch(bad)


def test_census_end_to_end(tmp_path):
    db = tmp_path / "papers.db"
    con = sqlite3.connect(db)
    con.execute("create table papers(paper_id text, title text)")
    con.execute("create table chunks(chunk_id text, paper_id text, text text)")
    con.execute("insert into papers values ('p1', 'Doc One')")
    dup = _chunk("z" * 60)
    rows = [
        ("stub", _chunk("short")),
        ("bare", _chunk("3.159")),
        ("big", _chunk("y" * 300)),
        ("dup1", dup),
        ("dup2", dup),
        ("ok", _chunk("w" * 60)),
    ]
    con.executemany("insert into chunks values (?, 'p1', ?)", rows)
    con.commit()
    con.close()

    r = census(str(db), stub_chars=40, oversize_chars=200, thin_chunks=20)

    assert (r["documents"], r["chunks"]) == (1, 6)
    assert r["stub"] == 2 and r["bare_number"] == 1
    assert r["oversized"] == 1
    assert r["duplicate"] == 1
    assert sorted(r["_stub_ids"]) == ["bare", "stub"]
    assert r["thin_documents"] == [(6, "p1", "Doc One")]
