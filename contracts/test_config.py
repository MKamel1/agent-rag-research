"""Sibling test for contracts/config.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises). This tests the `Config` *shape* only — the loader that reads
`config.yaml` into a `Config` is T-F2's ticket, not this one.
"""

import pytest
from pydantic import ValidationError

from contracts.config import Config


def test_constructs_with_only_the_one_required_field_and_documented_v0_defaults():
    config = Config(focus_area_queries=["causal inference", "treatment effect estimation"])
    assert config.corpus_cap == 15_000
    assert config.ordering == "freshest_first"
    assert config.ingestion_mode == "one_shot_seed"
    assert config.sources == ["arxiv"]
    assert config.relevance_filter == "off"
    assert config.child_parent_expansion is True
    assert config.top_k == 10
    assert config.rerank_depth == 50
    assert config.hybrid_dense_weight == pytest.approx(0.5)
    assert config.gpu_lock_path == ".gpu.lock"


def test_focus_area_queries_is_required():
    with pytest.raises(ValidationError):
        Config()  # type: ignore[call-arg]


def test_hybrid_dense_weight_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        Config(focus_area_queries=["x"], hybrid_dense_weight=1.5)
    with pytest.raises(ValidationError):
        Config(focus_area_queries=["x"], hybrid_dense_weight=-0.1)


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        Config(focus_area_queries="causal inference")  # a bare str, not list[str]


def test_is_frozen():
    config = Config(focus_area_queries=["x"])
    with pytest.raises(ValidationError):
        config.top_k = 20  # type: ignore[misc]
