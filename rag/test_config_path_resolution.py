"""T-DOC89: §1 (a config resolves its own relative paths against its own directory, not cwd) and
§3 (discovery precedence: explicit -> RAG_CONFIG env var -> config.yaml in cwd -> walk up parent
directories -> a loud error naming every location tried). Sibling test for `rag/config.py`,
split from `rag/test_config.py` (T-F2's original loader coverage) since this is a distinct,
later-added concern.

None of these tests touch the real repo-root config or the real data-dir database -- every config
here is a throwaway `tmp_path` fixture.
"""

import logging
from pathlib import Path

import pytest
import yaml

import rag.config as config_mod
from contracts.errors import ContractError
from rag.config import find_config_path, load_config


def _write_config(path: Path, **fields) -> Path:
    data = {"focus_area_queries": ["causal inference"], **fields}
    path.write_text(yaml.safe_dump(data))
    return path


# --- §1: a config resolves against its own directory, not cwd -----------------------------------


def test_same_config_file_loaded_from_two_cwds_yields_identical_absolute_paths(tmp_path, monkeypatch):
    config_dir = tmp_path / "somewhere"
    config_dir.mkdir()
    config_path = _write_config(config_dir / "config.yaml", db_path="papers.db", drop_in_dir="drop_in")

    other_cwd_a = tmp_path / "cwd_a"
    other_cwd_a.mkdir()
    monkeypatch.chdir(other_cwd_a)
    cfg_a = load_config(config_path)

    other_cwd_b = tmp_path / "cwd_b" / "nested"
    other_cwd_b.mkdir(parents=True)
    monkeypatch.chdir(other_cwd_b)
    cfg_b = load_config(config_path)

    assert cfg_a.db_path == cfg_b.db_path == str(config_dir / "papers.db")
    assert cfg_a.drop_in_dir == cfg_b.drop_in_dir == str(config_dir / "drop_in")


def test_relative_path_fields_resolve_against_config_dir_not_cwd(tmp_path, monkeypatch):
    config_dir = tmp_path / "corpus"
    config_dir.mkdir()
    config_path = _write_config(
        config_dir / "config.yaml",
        db_path="papers.db", blob_dir="blobs", pdf_cache_dir="pdf_cache",
        drop_in_dir="drop_in", gpu_lock_path=".gpu.lock", batch_size_log_path="batch_log.csv",
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    cfg = load_config(config_path)

    assert cfg.db_path == str(config_dir / "papers.db")
    assert cfg.blob_dir == str(config_dir / "blobs")
    assert cfg.pdf_cache_dir == str(config_dir / "pdf_cache")
    assert cfg.drop_in_dir == str(config_dir / "drop_in")
    assert cfg.gpu_lock_path == str(config_dir / ".gpu.lock")
    assert cfg.batch_size_log_path == str(config_dir / "batch_log.csv")


def test_already_absolute_path_fields_pass_through_unchanged(tmp_path):
    config_dir = tmp_path / "corpus"
    config_dir.mkdir()
    real_db = tmp_path / "elsewhere" / "papers.db"
    config_path = _write_config(config_dir / "config.yaml", db_path=str(real_db))

    cfg = load_config(config_path)

    assert cfg.db_path == str(real_db)


def test_empty_string_pdf_cache_dir_sentinel_is_left_alone(tmp_path):
    """`pdf_cache_dir: ""` means "PDF cache disabled" (contracts/config.py) -- must not become
    the config directory itself."""
    config_dir = tmp_path / "corpus"
    config_dir.mkdir()
    config_path = _write_config(config_dir / "config.yaml", pdf_cache_dir="")

    cfg = load_config(config_path)

    assert cfg.pdf_cache_dir == ""


def test_unset_batch_size_log_path_stays_none(tmp_path):
    config_dir = tmp_path / "corpus"
    config_dir.mkdir()
    config_path = _write_config(config_dir / "config.yaml")

    cfg = load_config(config_path)

    assert cfg.batch_size_log_path is None


# --- §3: discovery precedence ---------------------------------------------------------------


def test_explicit_path_wins_over_everything_else(tmp_path, monkeypatch):
    explicit_dir = tmp_path / "explicit"
    explicit_dir.mkdir()
    explicit_path = _write_config(explicit_dir / "config.yaml", db_path="explicit.db")

    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    _write_config(cwd_dir / "config.yaml", db_path="cwd.db")
    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("RAG_CONFIG", str(cwd_dir / "config.yaml"))

    found = find_config_path(explicit_path)
    assert found == explicit_path.resolve()


def test_rag_config_env_var_wins_over_cwd_and_walkup(tmp_path, monkeypatch):
    env_dir = tmp_path / "env_target"
    env_dir.mkdir()
    env_path = _write_config(env_dir / "config.yaml", db_path="env.db")

    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    _write_config(cwd_dir / "config.yaml", db_path="cwd.db")
    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("RAG_CONFIG", str(env_path))

    found = find_config_path(None)
    assert found == env_path.resolve()


def test_rag_config_pointing_nowhere_falls_through_to_cwd(tmp_path, monkeypatch):
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    cwd_path = _write_config(cwd_dir / "config.yaml", db_path="cwd.db")
    monkeypatch.chdir(cwd_dir)
    monkeypatch.setenv("RAG_CONFIG", str(tmp_path / "does_not_exist.yaml"))

    found = find_config_path(None)
    assert found == cwd_path.resolve()


def test_config_yaml_in_cwd_is_found_with_no_explicit_or_env(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_CONFIG", raising=False)
    cwd_path = _write_config(tmp_path / "config.yaml", db_path="cwd.db")
    monkeypatch.chdir(tmp_path)

    found = find_config_path(None)
    assert found == cwd_path.resolve()


def test_walks_up_parent_directories_when_cwd_has_none(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_CONFIG", raising=False)
    ancestor_path = _write_config(tmp_path / "config.yaml", db_path="ancestor.db")
    deep_cwd = tmp_path / "a" / "b" / "c"
    deep_cwd.mkdir(parents=True)
    monkeypatch.chdir(deep_cwd)

    found = find_config_path(None)
    assert found == ancestor_path.resolve()


def test_load_config_with_no_args_uses_discovery(tmp_path, monkeypatch):
    """End-to-end: load_config()'s default (no path) goes through find_config_path, not a bare
    cwd-relative open()."""
    monkeypatch.delenv("RAG_CONFIG", raising=False)
    _write_config(tmp_path / "config.yaml", db_path="cwd.db")
    monkeypatch.chdir(tmp_path)

    cfg = load_config()
    assert cfg.db_path == str(tmp_path / "cwd.db")


def test_no_config_anywhere_raises_contract_error_naming_every_location_tried(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_CONFIG", raising=False)
    deep_cwd = tmp_path / "isolated" / "nested"
    deep_cwd.mkdir(parents=True)
    monkeypatch.chdir(deep_cwd)

    with pytest.raises(ContractError) as exc_info:
        find_config_path(None)

    message = str(exc_info.value)
    # every rung actually walked must be named
    assert str(deep_cwd.resolve() / "config.yaml") in message
    assert str((tmp_path / "isolated").resolve() / "config.yaml") in message
    assert str(tmp_path.resolve() / "config.yaml") in message
    # both ways to fix it
    assert "RAG_CONFIG" in message
    assert "config.example.yaml" in message


def test_error_names_the_failed_rag_config_attempt_too(tmp_path, monkeypatch):
    deep_cwd = tmp_path / "isolated"
    deep_cwd.mkdir()
    monkeypatch.chdir(deep_cwd)
    bad_env_path = tmp_path / "nope.yaml"
    monkeypatch.setenv("RAG_CONFIG", str(bad_env_path))

    with pytest.raises(ContractError) as exc_info:
        find_config_path(None)

    assert str(bad_env_path) in str(exc_info.value)


# --- §2: stub validation -- repo-tree db_path warns, a fresh 0-row DB outside the repo doesn't --


def test_db_path_inside_repo_logs_a_warning(tmp_path, monkeypatch, caplog):
    """Never touches the real repo tree -- `_REPO_ROOT` is monkeypatched to a throwaway `tmp_path`
    stand-in, matching the shape config.example.yaml's own defaults produce (a config at the
    "repo" root with a bare relative `db_path`)."""
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(config_mod, "_REPO_ROOT", fake_repo)
    config_path = _write_config(fake_repo / "config.yaml", db_path="papers.db")

    with caplog.at_level(logging.WARNING, logger="rag.config"):
        load_config(config_path)

    assert any("INSIDE this repo" in r.message for r in caplog.records)


def test_db_path_outside_repo_with_zero_rows_does_not_warn(tmp_path, monkeypatch, caplog):
    """Pins the deliberate non-validation of row count (T-DOC89 design doc): a genuinely fresh,
    zero-row corpus OUTSIDE the (fake) repo is a legitimate setup and must not warn."""
    import sqlite3

    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(config_mod, "_REPO_ROOT", fake_repo)

    data_dir = tmp_path / "sibling_data_dir"
    data_dir.mkdir()
    db_path = data_dir / "papers.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE papers (id TEXT)")
    conn.commit()
    conn.close()
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM papers").fetchone() == (0,)

    config_path = _write_config(data_dir / "config.yaml", db_path=str(db_path))

    with caplog.at_level(logging.WARNING, logger="rag.config"):
        load_config(config_path)

    assert caplog.records == []
