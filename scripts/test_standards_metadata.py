"""Tests for scripts/standards_metadata.py (SQLite only, no network/GPU)."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from contracts.errors import ContractError
from scripts.standards_metadata import (
    DEFAULT_DB,
    DEFAULT_TABLE,
    build_payload_mapping,
    build_sql,
    check,
    emit,
    existing_categories,
    load_table,
    merged_categories,
    tags_for,
    validate,
)


def _row(pid, **kw):
    row = dict(
        paper_id=pid, title=f"T {pid}", kind="standard", issuer="ISO", designation="ISO 1:2018",
        edition_label="First", edition_year=2018, year_basis="document", status="current",
        supersedes=[], superseded_by=[], withdrawn_by=[], supersedes_external=[], normative=True,
        completeness="full", evidence=[{"chunk_id": f"{pid}:c0", "quote": "First edition 2018"}],
        null_reasons={},
    )
    row.update(kw)
    return row


def _db(tmp_path, cats=None):
    path = tmp_path / "p.db"
    con = sqlite3.connect(path)
    con.execute("create table papers (paper_id, title, categories_json)")
    con.execute("create table chunks (chunk_id, paper_id, text)")
    for pid in ("a", "b"):
        con.execute("insert into papers values (?,?,?)",
                    (pid, f"T {pid}", (cats or {}).get(pid, "[]")))
        con.execute("insert into chunks values (?,?,?)",
                    (f"{pid}:c0", pid, "x | --- | First  edition\n2018  foo"))
    con.commit()
    con.close()
    return str(path)


def _table(*rows):
    return {"meta": {}, "documents": list(rows)}


def test_valid_table_passes(tmp_path):
    assert validate(_table(_row("a"), _row("b")), _db(tmp_path)) == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.update(kind="treatise"), "kind"),
    (lambda r: r.update(status="old"), "status"),
    (lambda r: r.update(completeness="half"), "completeness"),
    (lambda r: r.update(designation=None), "requires a designation"),
    (lambda r: r.update(issuer=None), "issuer is null"),
    (lambda r: r.update(edition_year=None), "together"),
    (lambda r: r.update(superseded_by=["zzz"], status="superseded"), "orphan"),
    (lambda r: r.update(superseded_by=["b"], status="superseded"), "not reciprocated"),
    (lambda r: r.update(status="superseded"), "superseded"),
    (lambda r: r.update(status="preview-only"), "preview-only"),
    (lambda r: r.update(evidence=[{"chunk_id": "a:c0", "quote": "nope"}]), "verbatim"),
    (lambda r: r.update(evidence=[{"chunk_id": "a:c9", "quote": "x"}]), "not in DB"),
    (lambda r: r.update(evidence=[]), "no evidence"),
    (lambda r: r.update(title="other"), "title"),
])
def test_validation_failures_are_reported(tmp_path, mutate, needle):
    a = _row("a")
    mutate(a)
    errors = validate(_table(a, _row("b")), _db(tmp_path))
    assert any(needle in e for e in errors), errors


def test_unknown_and_missing_ids(tmp_path):
    errors = validate(_table(_row("a"), _row("ghost")), _db(tmp_path))
    assert "ghost: not in DB" in errors and "b: in DB but missing from table" in errors


def test_check_raises_contract_error(tmp_path):
    with pytest.raises(ContractError, match="invalid"):
        check(_table(_row("a")), _db(tmp_path))


def test_reciprocal_supersession_is_valid(tmp_path):
    a = _row("a", supersedes=["b"])
    b = _row("b", status="superseded", superseded_by=["a"])
    assert validate(_table(a, b), _db(tmp_path)) == []


def test_tags_and_null_handling():
    assert tags_for(_row("a")) == [
        "kind:standard", "status:current", "completeness:full", "kindstatus:standard+current",
        "issuer:iso", "normative:true", "normstatus:true+current"]
    bare = _row("a", issuer=None, normative=None)
    assert not any(t.startswith(("issuer:", "normative:", "normstatus:")) for t in tags_for(bare))
    assert "issuer:iso-iec-ieee" in tags_for(_row("a", issuer="ISO/IEC/IEEE"))


def test_merge_keeps_real_categories_and_is_idempotent():
    doc = _row("a")
    once = merged_categories(["cs.AI"], doc)
    assert once[0] == "cs.AI" and "kind:standard" in once
    assert merged_categories(once, doc) == once
    stale = merged_categories(["status:draft", "cs.AI"], doc)
    assert "status:draft" not in stale


def test_mapping_sql_and_emit(tmp_path):
    db = _db(tmp_path, {"a": '["cs.AI"]', "b": "[]"})
    table = _table(_row("a"), _row("b", title="T b"))
    existing = existing_categories(db)
    mapping = build_payload_mapping(table, existing)
    assert mapping["a"]["categories"][0] == "cs.AI"
    sql = build_sql(table, existing)
    assert sql.startswith("-- CQ-5") and "AND categories_json = '[\"cs.AI\"]'" in sql
    path = tmp_path / "t.json"
    path.write_text(json.dumps(table))
    out = tmp_path / "out"
    assert "wrote 2 rows" in emit(path, db, out)
    assert {p.name for p in out.iterdir()} == {
        "payload_mapping.json", "categories_update.sql", "categories_update.tsv"}
    # the source DB was only read
    con = sqlite3.connect(db)
    got = con.execute("select categories_json from papers where paper_id='a'").fetchone()[0]
    assert got == '["cs.AI"]'


@pytest.mark.skipif(not Path(DEFAULT_DB).exists(), reason="standards corpus DB not present")
def test_committed_table_is_valid_against_real_db():
    table = load_table(DEFAULT_TABLE)
    assert validate(copy.deepcopy(table), DEFAULT_DB) == []
    assert len(table["documents"]) == 119
