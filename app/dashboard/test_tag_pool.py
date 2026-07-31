"""Tests for `app.dashboard.tag_pool` -- offline, no real subprocess/manifest. Every mutation goes
through `controller._control_lock`, which is exercised for real here (a real `filelock.FileLock`
over `tmp_path`), never faked."""

import pytest

from app.dashboard import controller, tag_pool


def test_pool_seeds_from_config_queries_on_first_load(tmp_path):
    pool = tag_pool.load(tmp_path, ["causal inference", "do-calculus causal"])
    assert pool["active"] == ["causal inference", "do-calculus causal"]
    assert pool["held"] == []


def test_hold_moves_a_tag_to_held_without_destroying_it(tmp_path):
    seed = ["a", "b", "c"]
    pool = tag_pool.hold(tmp_path, seed, ["b"])
    assert pool["active"] == ["a", "c"]
    assert [h["query"] for h in pool["held"]] == ["b"]
    assert pool["held"][0]["held_at"]          # timestamped


def test_restore_brings_a_held_tag_back(tmp_path):
    seed = ["a", "b"]
    tag_pool.hold(tmp_path, seed, ["b"])
    pool = tag_pool.restore(tmp_path, seed, ["b"])
    assert "b" in pool["active"]
    assert pool["held"] == []


def test_adding_a_held_tag_reactivates_it_instead_of_duplicating(tmp_path):
    seed = ["a", "b"]
    tag_pool.hold(tmp_path, seed, ["b"])
    pool = tag_pool.add(tmp_path, seed, ["b"])
    assert pool["active"].count("b") == 1
    assert pool["held"] == []


def test_holding_every_tag_is_refused_and_leaves_the_pool_untouched(tmp_path):
    seed = ["a", "b"]
    with pytest.raises(controller.InvalidOverrideError):
        tag_pool.hold(tmp_path, seed, ["a", "b"])
    assert tag_pool.load(tmp_path, seed)["active"] == ["a", "b"]


def test_add_is_idempotent_and_preserves_order(tmp_path):
    seed = ["a"]
    tag_pool.add(tmp_path, seed, ["b"])
    pool = tag_pool.add(tmp_path, seed, ["b"])
    assert pool["active"] == ["a", "b"]


def test_hold_of_a_tag_not_currently_active_is_a_harmless_no_op(tmp_path):
    seed = ["a", "b"]
    pool = tag_pool.hold(tmp_path, seed, ["not-present"])
    assert pool["active"] == ["a", "b"]
    assert pool["held"] == []


def test_restore_of_a_tag_not_currently_held_is_a_harmless_no_op(tmp_path):
    seed = ["a", "b"]
    pool = tag_pool.restore(tmp_path, seed, ["not-held"])
    assert pool["active"] == ["a", "b"]
    assert pool["held"] == []


def test_active_queries_returns_just_the_active_list(tmp_path):
    seed = ["a", "b"]
    tag_pool.hold(tmp_path, seed, ["b"])
    assert tag_pool.active_queries(tmp_path, seed) == ["a"]


def test_corrupt_pool_file_reseeds_with_a_warning(tmp_path, caplog):
    (tmp_path / "tag_pool.json").write_text("not json")
    with caplog.at_level("WARNING"):
        pool = tag_pool.load(tmp_path, ["a", "b"])
    assert pool["active"] == ["a", "b"]
    assert pool["held"] == []
    assert any("tag_pool.json" in r.message for r in caplog.records)
