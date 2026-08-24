"""Invariants for the Waymo safety-research priority list and its corpus resolution.

The 55-paper list is transcribed from https://waymo.com/safety/research/ (fetched 2026-08-23);
the resolution map ties each publication to an ingested `papers.db` paper_id (53 of 55; two are
documented as not ingested). GT-WMR ground-truth authoring draws exclusively from resolved ids,
so this suite pins both files before any item exists.
"""

import json
import sqlite3
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent
LIST_PATH = FIXTURE_DIR / "waymo_safety_research_55.json"
RESOLUTION_PATH = FIXTURE_DIR / "waymo_safety_research_55_resolution.json"

_MIN_REAL_DB_BYTES = 1_000_000


def _find_real_db_path() -> Path | None:
    for ancestor in (FIXTURE_DIR, *FIXTURE_DIR.parents):
        candidate = ancestor / "waymo" / "data" / "papers.db"
        if candidate.exists() and candidate.stat().st_size >= _MIN_REAL_DB_BYTES:
            return candidate
    return None


DB_PATH = _find_real_db_path()


def test_priority_list_shape():
    data = json.loads(LIST_PATH.read_text())
    papers = data["papers"]
    assert data["_metadata"]["entry_count"] == 55
    assert len(papers) == 55, f"expected the full 55-paper page, got {len(papers)}"
    titles = [p["title"] for p in papers]
    assert len(set(titles)) == 55, "duplicate titles in the transcribed list"
    for p in papers:
        assert p["slug"].startswith("/research/")
        assert isinstance(p["year"], int) and 2020 <= p["year"] <= 2026
        assert p["topics"], f"{p['title'][:50]!r}: no topics"
        if p["arxiv_id"] is not None:
            assert len(p["arxiv_id"].split(".")) == 2, f"bad arxiv id {p['arxiv_id']!r}"


def test_resolution_shape():
    data = json.loads(RESOLUTION_PATH.read_text())
    res = data["resolution"]
    assert data["_metadata"]["resolved"] == len(res) == 53
    assert data["_metadata"]["missing"] == len(data["not_ingested"]) == 2
    listed = {p["title"] for p in json.loads(LIST_PATH.read_text())["papers"]}
    covered = set(res) | {m["title"] for m in data["not_ingested"]}
    assert covered == listed, (
        f"resolution does not partition the list: missing-from-map={listed - covered}, "
        f"unknown-in-map={covered - listed}"
    )
    for title, r in res.items():
        assert r["paper_id"], f"{title[:50]!r}: empty paper_id"
        assert r["how"], f"{title[:50]!r}: unresolved-by-method"


@pytest.mark.skipif(DB_PATH is None, reason="real Waymo corpus DB not found near this checkout")
def test_resolved_ids_exist_in_corpus_db():
    res = json.loads(RESOLUTION_PATH.read_text())["resolution"]
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        known = {pid for (pid,) in conn.execute("SELECT paper_id FROM papers")}
    finally:
        conn.close()
    for title, r in res.items():
        assert r["paper_id"] in known, (
            f"{title[:60]!r}: resolved paper_id {r['paper_id']!r} not in papers.db"
        )


if __name__ == "__main__":
    test_priority_list_shape()
    test_resolution_shape()
    if DB_PATH is not None:
        test_resolved_ids_exist_in_corpus_db()
