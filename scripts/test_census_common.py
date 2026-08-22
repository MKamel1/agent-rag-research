"""Tests for scripts/census_common.py's shared ranking helper."""

from scripts.census_common import rank_by_count


def test_rank_by_count_orders_highest_first():
    assert rank_by_count({"a": 10, "b": 50, "c": 30}) == [("b", 50), ("c", 30), ("a", 10)]


def test_rank_by_count_drops_zero_counts():
    assert rank_by_count({"a": 0, "b": 5}) == [("b", 5)]


def test_rank_by_count_breaks_ties_by_key():
    assert rank_by_count({"z": 5, "a": 5}) == [("a", 5), ("z", 5)]


def test_rank_by_count_respects_n():
    assert rank_by_count({"a": 1, "b": 2, "c": 3}, n=2) == [("c", 3), ("b", 2)]
