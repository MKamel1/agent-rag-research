"""Tests for `app.disambiguate_chapter_titles` -- offline, real tiny SQLite + in-memory store."""

from __future__ import annotations

import sqlite3

import pytest

from app import disambiguate_chapter_titles as dct
from contracts.errors import ContractError

ROWS = [  # (summary_id, title)
    ("b1:summary", None),
    ("b1:summary:ch0", "Part 2"),
    ("b1:summary:ch1", "Intro"),
    ("b1:summary:ch2", "Part 2"),
    ("b1:summary:ch10", "Part 2"),
    ("b2:summary:ch0", "Part 2"),
]


class _Store:
    def __init__(self, ids):
        self.payload = {i: {"section_path": "old"} for i in ids}

    def paper_point_ids(self, collection=None):
        return {"x": list(self.payload)}

    def set_payload(self, fields, *, point_ids=None, **kw):
        n = 0
        for i in point_ids:
            if i in self.payload:
                self.payload[i].update(fields)
                n += 1
        return n


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "papers.db"
    con = sqlite3.connect(path)
    con.execute("create table summaries (summary_id text primary key, paper_id text, text text, title text)")
    con.executemany("insert into summaries values (?, 'p', 't', ?)", ROWS)
    con.commit()
    con.close()
    return path


def _run(db, store, tmp_path, **kw):
    args = dict(collection="c", apply=False, backup_root=lambda: tmp_path, have_snapshot=False,
                target_is_clone=False, clone_of=None, count_of=lambda n: 0)
    args.update(kw)
    return dct.run_disambiguation(db, store, **args)


def _titles(db):
    con = sqlite3.connect(db)
    return dict(con.execute("select summary_id, title from summaries"))


def test_dry_run_lists_numeric_chapter_order_and_writes_nothing(db, tmp_path):
    store = _Store(i for i, _ in ROWS)
    text, renames = _run(db, store, tmp_path)
    assert [(r.paper_id, r.index, r.new) for r in renames] == [
        ("b1", 2, "Part 2 (2)"), ("b1", 10, "Part 2 (3)")]
    assert "DRY RUN" in text and _titles(db)["b1:summary:ch2"] == "Part 2"
    assert store.payload["b1:summary:ch2"]["section_path"] == "old"


def test_apply_refuses_without_snapshot_guard(db, tmp_path):
    with pytest.raises(ContractError, match="refusing to write"):
        _run(db, _Store(i for i, _ in ROWS), tmp_path, apply=True)
    assert _titles(db)["b1:summary:ch2"] == "Part 2"


def test_apply_updates_both_stores_and_is_idempotent(db, tmp_path):
    store = _Store(i for i, _ in ROWS)
    _run(db, store, tmp_path, apply=True, target_is_clone=True, clone_of="src",
         count_of=lambda n: 5)
    assert _titles(db)["b1:summary:ch10"] == "Part 2 (3)"
    assert store.payload["b1:summary:ch10"]["section_path"] == "Part 2 (3)"
    assert store.payload["b1:summary:ch1"]["section_path"] == "old"  # untouched
    _, renames = _run(db, store, tmp_path)
    assert renames == []


def test_missing_vector_point_aborts(db, tmp_path):
    with pytest.raises(ContractError, match="no vector point"):
        _run(db, _Store(["b1:summary:ch0"]), tmp_path)
