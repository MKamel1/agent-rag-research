"""Sibling test for rag/config.py (T-F2). Covers the loader: reading the real repo-root
`config.yaml`, and each of pydantic's strict-validation failure modes propagating uncaught
through `load_config` (missing required field, unknown key, out-of-range value).
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rag.config import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_CONFIG_PATH = REPO_ROOT / "config.yaml"


def test_loads_real_repo_config():
    config = load_config(REAL_CONFIG_PATH)
    assert len(config.focus_area_queries) == 33
    assert config.corpus_cap == 15_000
    assert config.gpu_lock_path == ".gpu.lock"


def test_missing_required_field_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"corpus_cap": 100}))
    with pytest.raises(ValidationError):
        load_config(path)


def test_unknown_key_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump({"focus_area_queries": ["causal inference"], "not_a_real_field": 1})
    )
    with pytest.raises(ValidationError):
        load_config(path)


def test_out_of_range_value_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump({"focus_area_queries": ["causal inference"], "hybrid_dense_weight": 1.5})
    )
    with pytest.raises(ValidationError):
        load_config(path)
