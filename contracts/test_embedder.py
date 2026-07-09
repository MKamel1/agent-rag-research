"""Sibling test for contracts/embedder.py (T-F1 DoD: imported by a trivial test; constructing one
with a wrong type raises).
"""

import pytest
from pydantic import ValidationError

from contracts.embedder import EmbedderInfo


def test_constructs_with_valid_fields():
    info = EmbedderInfo(model_id="Qwen3-Embedding-4B", dim=2560, version="1.0.0")
    assert info.dim == 2560


def test_dim_must_be_positive():
    with pytest.raises(ValidationError):
        EmbedderInfo(model_id="m", dim=0, version="1.0.0")
    with pytest.raises(ValidationError):
        EmbedderInfo(model_id="m", dim=-1, version="1.0.0")


def test_wrong_type_raises():
    with pytest.raises(ValidationError):
        EmbedderInfo(model_id="m", dim="a lot", version="1.0.0")
