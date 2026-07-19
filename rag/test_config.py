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

from contracts.config import Config
from contracts.errors import ContractError
from rag.config import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_CONFIG_PATH = REPO_ROOT / "config.yaml"


def test_loads_real_repo_config():
    config = load_config(REAL_CONFIG_PATH)
    assert len(config.focus_area_queries) == 33
    assert config.corpus_cap == 30_000
    assert config.gpu_lock_path == ".gpu.lock"
    assert config.parse_batch_size == 4


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


# --- Config <-> config.yaml <-> contracts parity -------------------------------------------------
# `Config(**data)`'s `extra="forbid"` (contracts/_base.py) already proves the REVERSE direction --
# every config.yaml key names a real Config field, or test_loads_real_repo_config above would raise
# ValidationError. What's untested is the FORWARD direction: a future field added to
# contracts/config.py that nobody remembers to also add to config.yaml -- it wouldn't crash (pydantic
# silently falls back to the class default), so the omission would never surface on its own.


def test_every_contracts_config_field_has_a_config_yaml_key():
    """Locks the parity contracts/config.py assumes: every declared field should have a real
    config.yaml key, not a silent fallback to the class default. Currently xfails -- the audit that
    added this test found 7 real contracts/config.py fields (all documented in DATA-CONTRACTS.md's
    Config block) missing from config.yaml today: the 5 T-DOC29 "composition-root levers"
    (`db_path`/`blob_dir`/`collection`/`pdf_cache_dir`/`batch_size_log_path`) plus `prefetch_target`/
    `ingest_paper_ids`. All 7 are harmless in practice (pydantic silently falls back to each field's
    documented class default, and every default matches what config.yaml would set anyway) but that's
    exactly the silent-skip this test exists to catch once the gap is closed. config.yaml is
    foundation-protected (out of scope for that audit's PR) -- once a follow-up adds the missing keys,
    this test should XPASS and the xfail marker below should be deleted.
    """
    yaml_keys = set(yaml.safe_load(REAL_CONFIG_PATH.read_text()))
    contract_fields = set(Config.model_fields)
    missing = contract_fields - yaml_keys
    known_gap = {
        "db_path", "blob_dir", "collection", "pdf_cache_dir", "batch_size_log_path",
        "prefetch_target", "ingest_paper_ids",
    }
    if missing == known_gap:
        pytest.xfail(f"config.yaml missing known fields (see audit): {sorted(missing)}")
    assert not missing, f"contracts/config.py field(s) missing from config.yaml: {sorted(missing)}"


def test_config_yaml_has_no_keys_outside_contracts_config_fields():
    yaml_keys = set(yaml.safe_load(REAL_CONFIG_PATH.read_text()))
    contract_fields = set(Config.model_fields)
    extra = yaml_keys - contract_fields
    assert not extra, f"config.yaml key(s) not in contracts/config.py: {sorted(extra)}"
