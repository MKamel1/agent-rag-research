"""Sibling test for rag/config.py (T-F2). Covers the loader: reading the real repo-root
`config.yaml`, each of pydantic's strict-validation failure modes propagating uncaught through
`load_config` (missing required field, unknown key, out-of-range value), malformed YAML syntax,
the non-mapping precondition (`ContractError`), the `str`-path branch, and the no-arg
default-path branch.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from contracts.errors import ContractError
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


def test_malformed_yaml_raises(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("focus_area_queries: [causal inference\n  bad_indent: -\n")
    with pytest.raises(yaml.YAMLError):
        load_config(path)


def test_str_path_works(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"focus_area_queries": ["causal inference"]}))
    config = load_config(str(path))
    assert config.focus_area_queries == ["causal inference"]


def test_default_path_uses_cwd(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump({"focus_area_queries": ["causal inference"]}))
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.focus_area_queries == ["causal inference"]


def test_empty_file_raises_contract_error(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("")
    with pytest.raises(ContractError):
        load_config(path)


def test_top_level_list_raises_contract_error(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(["causal inference", "treatment effects"]))
    with pytest.raises(ContractError):
        load_config(path)
