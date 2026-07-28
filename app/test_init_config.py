"""Tests for app/init_config.py (T-DOC65) -- zero-GPU, zero-network (TEST-STRATEGY).

`create_symlink` writes at module-level `_REPO_ROOT` -- every `--link` test monkeypatches that to
a tmp_path fake repo root so a test run never touches this actual repo's own config.yaml.
"""

import yaml

from app import init_config
from rag.config import load_config


def test_write_config_produces_loadable_absolute_paths(tmp_path):
    data_dir = tmp_path / "data"

    dest = init_config.write_config(data_dir, force=False)

    assert dest == data_dir / "config.yaml"
    written = yaml.safe_load(dest.read_text())
    assert written["db_path"] == str(data_dir / "papers.db")
    assert written["blob_dir"] == str(data_dir / "blobs")
    assert written["drop_in_dir"] == str(data_dir / "drop_in")
    # collection is a name, not a path field -- untouched from the template.
    assert written["collection"] == "papers"

    cfg = load_config(dest)
    assert cfg.db_path == str(data_dir / "papers.db")


def test_write_config_refuses_overwrite_without_force(tmp_path, capsys):
    data_dir = tmp_path / "data"
    init_config.write_config(data_dir, force=False)

    try:
        init_config.write_config(data_dir, force=False)
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 1

    assert raised
    assert "already exists" in capsys.readouterr().err


def test_write_config_force_allows_overwrite(tmp_path):
    data_dir = tmp_path / "data"
    dest = init_config.write_config(data_dir, force=False)
    dest.write_text("focus_area_queries: []\n")  # simulate a hand-edited file

    init_config.write_config(data_dir, force=True)

    written = yaml.safe_load(dest.read_text())
    assert written["db_path"] == str(data_dir / "papers.db")


def test_main_prints_resolved_paths(tmp_path, capsys):
    data_dir = tmp_path / "data"

    rc = init_config.main(["--data-dir", str(data_dir)])

    assert rc == 0
    out = capsys.readouterr().out
    assert str(data_dir / "papers.db") in out
    assert str(data_dir / "blobs") in out


def test_link_is_opt_in(tmp_path, monkeypatch):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(init_config, "_REPO_ROOT", fake_repo)
    data_dir = tmp_path / "data"

    init_config.main(["--data-dir", str(data_dir)])

    assert not (fake_repo / "config.yaml").exists()


def test_link_creates_symlink_that_load_config_resolves(tmp_path, monkeypatch):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(init_config, "_REPO_ROOT", fake_repo)
    monkeypatch.delenv("RAG_CONFIG", raising=False)
    data_dir = tmp_path / "data"

    rc = init_config.main(["--data-dir", str(data_dir), "--link"])

    assert rc == 0
    link = fake_repo / "config.yaml"
    assert link.is_symlink()
    assert link.resolve() == (data_dir / "config.yaml").resolve()

    # T-DOC89 §3 discovery: plain load_config() from the repo root (cwd rung) follows the
    # symlink and resolves paths against the REAL target's directory (data_dir), not fake_repo.
    monkeypatch.chdir(fake_repo)
    cfg = load_config()
    assert cfg.db_path == str((data_dir / "papers.db").resolve())


def test_link_refuses_to_replace_existing_without_force(tmp_path, monkeypatch):
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setattr(init_config, "_REPO_ROOT", fake_repo)
    (fake_repo / "config.yaml").write_text("focus_area_queries: []\n")
    data_dir = tmp_path / "data"

    try:
        init_config.main(["--data-dir", str(data_dir), "--link"])
        raised = False
    except SystemExit as exc:
        raised = True
        assert exc.code == 1

    assert raised
