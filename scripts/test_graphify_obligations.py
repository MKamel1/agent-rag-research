from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.graphify_obligations import main


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    return tmp_path


def _run(repo: Path, changed: list[str], capsys: pytest.CaptureFixture) -> dict:
    changed_file = repo.parent / "changed.txt"
    changed_file.write_text("\n".join(changed), encoding="utf-8")
    rc = main(["--changed", str(changed_file), "--root", str(repo)])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


def test_r1_fires_on_app_entry_point(repo: Path, capsys: pytest.CaptureFixture) -> None:
    (repo / "app" / "newtool.py").write_text(
        "import argparse\nparser.add_argument('--x')\n", encoding="utf-8"
    )
    out = _run(repo, ["app/newtool.py"], capsys)
    r1 = next(o for o in out["obligations"] if o["rule_id"] == "R1")
    assert r1["files"] == ["app/newtool.py"]


def test_r1_ignores_app_module_without_argparse(repo: Path, capsys: pytest.CaptureFixture) -> None:
    (repo / "app" / "plain.py").write_text("x = 1\n", encoding="utf-8")
    out = _run(repo, ["app/plain.py"], capsys)
    r1 = next(o for o in out["obligations"] if o["rule_id"] == "R1")
    assert r1["files"] == []


def test_r2_fires_on_decision_doc(repo: Path, capsys: pytest.CaptureFixture) -> None:
    out = _run(repo, ["docs/DECISION-something.md", "docs/eval-reports/x.md"], capsys)
    r2 = next(o for o in out["obligations"] if o["rule_id"] == "R2")
    assert r2["files"] == ["docs/DECISION-something.md", "docs/eval-reports/x.md"]


def test_r2_ignores_plain_docs(repo: Path, capsys: pytest.CaptureFixture) -> None:
    out = _run(repo, ["docs/RANDOM-NOTES.md"], capsys)
    r2 = next(o for o in out["obligations"] if o["rule_id"] == "R2")
    assert r2["files"] == []


def test_r3_foundation_paths_flagged(repo: Path, capsys: pytest.CaptureFixture) -> None:
    out = _run(repo, ["contracts/types.py", "rag/config.py"], capsys)
    r3 = next(o for o in out["obligations"] if o["rule_id"] == "R3")
    assert r3["files"] == ["contracts/types.py", "rag/config.py"]
    assert "sign-off" in r3["action"]


def test_r4_test_files_suppressed(repo: Path, capsys: pytest.CaptureFixture) -> None:
    (repo / "app" / "test_x.py").write_text("import argparse\nadd_argument\n", encoding="utf-8")
    out = _run(repo, ["app/test_x.py", "scripts/test_graphify_rig.py"], capsys)
    for o in out["obligations"]:
        assert "app/test_x.py" not in o["files"]


def test_r5_always_on(repo: Path, capsys: pytest.CaptureFixture) -> None:
    out = _run(repo, [], capsys)
    r5 = next(o for o in out["obligations"] if o["rule_id"] == "R5")
    assert r5["files"] == ["*"]
    assert out["clean"] is False


def test_dedup_and_counting(repo: Path, capsys: pytest.CaptureFixture) -> None:
    out = _run(repo, ["contracts/a.py", "contracts/a.py", "  ", "ci/x.py"], capsys)
    assert out["changed_count"] == 2
    r3 = next(o for o in out["obligations"] if o["rule_id"] == "R3")
    assert r3["files"] == ["ci/x.py", "contracts/a.py"]


def test_unreadable_changed_file_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = main(["--changed", str(tmp_path / "missing.txt"), "--root", str(tmp_path)])
    assert rc == 2
