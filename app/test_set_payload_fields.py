"""Tests for `app.set_payload_fields` -- offline. `_FakeStore` is an in-memory stand-in for
`VectorIndex` with the real MERGE semantics; the sqlite builder runs against a tiny real DB opened
read-only. The adapter's own batching/merge behaviour is tested in `rag/test_vector_index.py`."""

from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from app import set_payload_fields as spf
from contracts.errors import ContractError


class _FakeStore:
    def __init__(self, drop_on_write=False):
        self.points = {  # ext_id -> payload
            "p1:c0": {"paper_id": "p1", "text": "a", "kind": "chunk"},
            "p1:c1": {"paper_id": "p1", "text": "b", "kind": "chunk"},
            "p2:c0": {"paper_id": "p2", "text": "c", "kind": "chunk"},
            "p3:c0": {"paper_id": "p3", "text": "d", "kind": "chunk"},
        }
        self.writes = 0
        self.drop_on_write = drop_on_write

    def paper_point_ids(self, collection=None):
        out: dict[str, list[str]] = {}
        for ext, payload in self.points.items():
            out.setdefault(payload["paper_id"], []).append(ext)
        return out

    def set_payload(self, fields, *, paper_ids=None, point_ids=None, collection=None, batch_size=0):
        self.writes += 1
        for ext in point_ids:
            if self.drop_on_write:
                self.points.pop(ext)
            else:
                self.points[ext].update(fields)  # merge
        return len(point_ids)

    def sample_payloads(self, n, collection=None):
        return [dict(p) for p in self.points.values()][:n]


def _run(store, mapping, tmp_path, **kw):
    args = dict(
        collection="clone", only_fields={"relevance_score"}, apply=False,
        backup_root=lambda: tmp_path, have_snapshot=False, target_is_clone=False, clone_of=None,
        count_of=lambda name: 4,
    )
    args.update(kw)
    return spf.run_set_payload_fields(store, mapping, **args)


MAPPING = {
    "p1": {"relevance_score": 0.5},
    "p2": {"relevance_score": 0.7},
    "zz": {"relevance_score": 1.0},
}
APPLY = dict(apply=True, target_is_clone=True, clone_of="live")


def test_dry_run_is_the_default_and_writes_nothing(tmp_path):
    store = _FakeStore()
    out = _run(store, MAPPING, tmp_path)
    assert "DRY RUN" in out and "would touch 3 points" in out
    assert "mapping_papers_not_in_collection=1" in out
    assert store.writes == 0 and "relevance_score" not in store.points["p1:c0"]


def test_apply_without_guard_is_refused(tmp_path):
    store = _FakeStore()
    with pytest.raises(ContractError, match="refusing to write"):
        _run(store, MAPPING, tmp_path, apply=True)
    assert store.writes == 0


def test_apply_merges_and_keeps_every_existing_key(tmp_path):
    store = _FakeStore()
    out = _run(store, MAPPING, tmp_path, **APPLY)
    assert "APPLIED" in out and "3 points written" in out
    assert store.points["p1:c1"] == {
        "paper_id": "p1", "text": "b", "kind": "chunk", "relevance_score": 0.5,
    }
    assert "relevance_score" not in store.points["p3:c0"]  # unmapped paper untouched


def test_only_fields_allow_list_drops_other_fields(tmp_path):
    store = _FakeStore()
    mapping = {"p1": {"relevance_score": 0.5, "topic_label": "on"}}
    out = _run(store, mapping, tmp_path, **APPLY)
    assert "mapping_fields_dropped_by_allowlist=1" in out
    assert "topic_label" not in store.points["p1:c0"]


def test_identical_value_sets_share_one_sweep(tmp_path):
    store = _FakeStore()
    mapping = {pid: {"topic_label": "on"} for pid in ("p1", "p2", "p3")}
    _run(store, mapping, tmp_path, only_fields={"topic_label"}, **APPLY)
    assert store.writes == 1


def test_lost_points_are_detected(tmp_path):
    with pytest.raises(ContractError, match="POINTS-PER-PAPER"):
        _run(_FakeStore(drop_on_write=True), MAPPING, tmp_path, **APPLY)


def test_readback_mismatch_is_detected(tmp_path):
    store = _FakeStore()
    store.sample_payloads = lambda n, collection=None: [
        {"paper_id": "p1", "relevance_score": 0.0}
    ]
    with pytest.raises(ContractError, match="read-back"):
        _run(store, MAPPING, tmp_path, **APPLY)


def test_relevance_score_builder_reads_sqlite_and_skips_nulls(tmp_path):
    db = tmp_path / "papers.db"
    con = sqlite3.connect(db)
    con.execute("create table papers (paper_id text, relevance_score real)")
    con.executemany("insert into papers values (?, ?)", [("a", 0.25), ("b", None), ("c", 0.9)])
    con.commit()
    con.close()
    assert spf.build_relevance_score_mapping(db) == {
        "a": {"relevance_score": 0.25}, "c": {"relevance_score": 0.9},
    }
    # opened read-only: the builder cannot write even by accident
    before = db.read_bytes()
    spf.build_relevance_score_mapping(db)
    assert db.read_bytes() == before


def test_topic_label_builder_reads_the_real_labels_file_format(tmp_path):
    tsv = tmp_path / "labels.tsv"
    tsv.write_text("1.1\ton\tcausal\n2.2\toff\tphysics\n3.3\tborderline\tadjacent\n4.4\tjunk\tx\n")
    assert spf.build_topic_label_mapping(tsv) == {
        "1.1": {"topic_label": "on"}, "2.2": {"topic_label": "off"},
        "3.3": {"topic_label": "borderline"},
    }


def test_mapping_file_json_and_tsv(tmp_path):
    j = tmp_path / "m.json"
    j.write_text(json.dumps({"a": {"f": 1}}))
    assert spf.load_mapping_file(j) == {"a": {"f": 1}}
    t = tmp_path / "m.tsv"
    t.write_text("paper_id\tscore\tlabel\na\t0.5\tword\n")
    assert spf.load_mapping_file(t) == {"a": {"score": 0.5, "label": "word"}}
    bad = tmp_path / "bad.tsv"
    bad.write_text("id\tscore\na\t1\n")
    with pytest.raises(ContractError):
        spf.load_mapping_file(bad)


def test_cli_requires_collection_and_only_fields(capsys):
    with pytest.raises(SystemExit):
        spf._parse_args(["--build", "topic_label", "--labels", "x", "--only-fields", "topic_label"])
    assert "--collection" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        spf._parse_args(["--collection", "c", "--build", "topic_label", "--labels", "x"])
    assert "--only-fields" in capsys.readouterr().err
    args = spf._parse_args(
        ["--collection", "c", "--build", "topic_label", "--labels", "x", "--only-fields", "f"]
    )
    assert args.apply is False  # dry run unless --apply
    assert sys.argv  # (argv untouched)
