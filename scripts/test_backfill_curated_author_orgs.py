"""The backfill writes the `curated` tag that `SearchFilters.author_org_curated_only` filters on --
a wrong write here silently answers "not Waymo" for a Waymo paper, which is exactly the failure the
curated tier exists to prevent. Qdrant is not exercised (no vector store in unit tests); the SQLite
half carries the set-membership logic, which is the part that can be wrong."""

import json
import sqlite3

from scripts.backfill_curated_author_orgs import CURATED_VALUE, backfill_sqlite, load_ids


def _db(tmp_path, paper_ids):
    path = tmp_path / "papers.db"
    conn = sqlite3.connect(path)
    conn.execute("create table papers (paper_id text primary key, author_orgs text)")
    conn.executemany("insert into papers values (?, null)", [(p,) for p in paper_ids])
    conn.commit()
    conn.close()
    return path


def test_tags_only_curated_ids_and_leaves_the_rest_null(tmp_path):
    db = _db(tmp_path, ["2508.19425", "local:abc", "9999.99999"])
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("2508.19425\nlocal:abc\n")

    rows = backfill_sqlite(db, load_ids(ids_file))

    assert rows == 2
    stored = dict(sqlite3.connect(db).execute("select paper_id, author_orgs from papers"))
    assert json.loads(stored["2508.19425"]) == CURATED_VALUE
    assert json.loads(stored["local:abc"]) == CURATED_VALUE
    # A non-curated paper must stay untagged -- over-tagging is as wrong as under-tagging.
    assert stored["9999.99999"] is None


def test_load_ids_dedups_and_drops_blank_lines(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("b\n\na\n  \nb\n")
    assert load_ids(f) == ["a", "b"]


def test_rowcount_reveals_a_curated_id_the_corpus_does_not_have(tmp_path):
    """The count mismatch the script warns on -- the signal that list and corpus disagree."""
    db = _db(tmp_path, ["2508.19425"])
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("2508.19425\nnot-ingested-yet\n")

    assert backfill_sqlite(db, load_ids(ids_file)) == 1
