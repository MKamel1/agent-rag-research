"""Tests for `app.db_guard` (OP-6)."""

import pytest

from app.db_guard import MissingDatabaseError, require_existing_db


def test_missing_db_is_refused_and_not_created(tmp_path):
    with pytest.raises(MissingDatabaseError, match="no database at"):
        require_existing_db(tmp_path / "papers.db")
    assert list(tmp_path.iterdir()) == []


def test_directory_is_not_a_database(tmp_path):
    with pytest.raises(MissingDatabaseError):
        require_existing_db(tmp_path)


def test_existing_db_is_returned(tmp_path):
    db = tmp_path / "papers.db"
    db.write_bytes(b"x")
    assert require_existing_db(db) == db
