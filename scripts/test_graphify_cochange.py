"""Tests for scripts/graphify_cochange.py (ticket T-G5).

Zero-network, zero-GPU: end-to-end cases build a throwaway git repo under
tmp_path via subprocess git and drive the CLI through ``main(argv)``; pure
parser/counter cases use fabricated log text directly.
"""

import json
import subprocess

import pytest

from scripts.graphify_cochange import (
    count_pairs,
    filter_bundle,
    main,
    parse_commit_bundles,
)


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def cochange_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Agent")
    _git(repo, "config", "user.email", "agent@example.com")
    _commit_files(repo, {"src/setup.md": "setup\n"})
    _commit_files(repo, {"src/a.py": "a\n", "src/b.py": "b\n"})
    _commit_files(repo, {"src/a.py": "a2\n", "src/b.py": "b2\n"})
    _commit_files(
        repo,
        {
            "src/a.py": "a3\n",
            "src/b.py": "b3\n",
            "src/c.py": "c\n",
            "docs/eval-reports/note.md": "n\n",
        },
    )
    return repo


def _commit_files(repo, files):
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"touch {sorted(files)}")


def _cli_args(repo, out_path, extra=()):
    return [
        "--repo",
        str(repo),
        "--since",
        "HEAD~3",
        "--min-support",
        "3",
        "--exclude",
        "docs/eval-reports/*",
        "--out",
        str(out_path),
        *extra,
    ]


def test_parse_commit_bundles_splits_fabricated_log_text():
    log_text = (
        "COMMIT:aaa111\n"
        "\n"
        "src/a.py\n"
        "src/b.py\n"
        "\n"
        "\n"
        "COMMIT:bbb222\n"
        "\n"
        "docs/x.md\n"
    )
    assert parse_commit_bundles(log_text) == [["src/a.py", "src/b.py"], ["docs/x.md"]]


def test_parse_commit_bundles_deduplicates_and_sorts_within_commit():
    log_text = "COMMIT:aaa111\nsrc/b.py\nsrc/a.py\nsrc/a.py\n"
    assert parse_commit_bundles(log_text) == [["src/a.py", "src/b.py"]]


def test_parse_commit_bundles_handles_empty_input_and_merge_commits():
    assert parse_commit_bundles("") == []
    assert parse_commit_bundles("COMMIT:aaa111\n\n") == []


def test_filter_bundle_keeps_only_source_extensions():
    files = ["src/a.py", "notes.txt", "README.md", "img.png", "conf.yaml"]
    assert filter_bundle(files) == ["README.md", "conf.yaml", "src/a.py"]

def test_filter_bundle_applies_exclude_patterns():
    files = ["docs/eval-reports/r.md", "docs/guide.md", "tests-x/test_a.py", "src/a.py"]
    assert filter_bundle(files, ["docs/eval-reports/*", "tests-*"]) == [
        "docs/guide.md",
        "src/a.py",
    ]


def test_count_pairs_counts_co_occurrence_across_commits():
    bundles = [["a.py", "b.py"], ["a.py", "b.py", "c.py"]]
    counter, considered = count_pairs(bundles)
    assert counter[("a.py", "b.py")] == 2
    assert counter[("a.py", "c.py")] == 1
    assert counter[("b.py", "c.py")] == 1
    assert considered == 4


def test_count_pairs_normalizes_pair_ordering():
    counter, _ = count_pairs([["z.py", "a.py"]])
    assert ("a.py", "z.py") in counter
    assert ("z.py", "a.py") not in counter


def test_count_pairs_skips_mass_edit_commits_entirely():
    big_commit = [f"f{i}.py" for i in range(4)]
    counter, considered = count_pairs(
        [big_commit, ["a.py", "b.py"]], max_files_per_commit=2
    )
    assert sum(counter.values()) == 1
    assert counter[("a.py", "b.py")] == 1
    assert considered == 1


def test_cli_end_to_end_shape_and_min_support(cochange_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.graphify_cochange._utcnow", lambda: "2026-01-01T00:00:00+00:00"
    )
    out = tmp_path / "report.json"
    assert main(_cli_args(cochange_repo, out)) == 0
    report = json.loads(out.read_text())
    assert set(report) == {
        "generated_at",
        "repo",
        "since",
        "commits_scanned",
        "pairs_considered",
        "edges",
    }
    assert report["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert report["repo"] == str(cochange_repo)
    assert report["since"] == "HEAD~3"
    assert report["commits_scanned"] == 3
    for edge in report["edges"]:
        assert set(edge) == {"files", "support", "confidence", "confidence_score"}
        assert len(edge["files"]) == 2
        assert edge["files"] == sorted(edge["files"])
        assert edge["confidence"] == "INFERRED"
        assert edge["confidence_score"] == 0.75
        assert edge["support"] >= 3
    supports = [edge["support"] for edge in report["edges"]]
    assert supports == sorted(supports, reverse=True)


def test_cli_edges_match_expected_pairs_and_exclude_pattern(
    cochange_repo, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "scripts.graphify_cochange._utcnow", lambda: "2026-01-01T00:00:00+00:00"
    )
    out = tmp_path / "report.json"
    assert main(_cli_args(cochange_repo, out)) == 0
    report = json.loads(out.read_text())
    edges = {(tuple(edge["files"]), edge["support"]) for edge in report["edges"]}
    assert (("src/a.py", "src/b.py"), 3) in edges
    assert all("docs/eval-reports/note.md" not in files for files, _ in edges)
    assert all(support >= 3 for _, support in edges)


def test_cli_output_is_deterministic_byte_for_byte(cochange_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.graphify_cochange._utcnow", lambda: "2026-01-01T00:00:00+00:00"
    )
    out_a = tmp_path / "run_a.json"
    out_b = tmp_path / "run_b.json"
    assert main(_cli_args(cochange_repo, out_a)) == 0
    assert main(_cli_args(cochange_repo, out_b)) == 0
    assert out_a.read_bytes() == out_b.read_bytes()


def test_cli_mass_commit_is_skipped_entirely(cochange_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.graphify_cochange._utcnow", lambda: "2026-01-01T00:00:00+00:00"
    )
    out = tmp_path / "report.json"
    args = _cli_args(cochange_repo, out, extra=["--max-files-per-commit", "1"])
    assert main(args) == 0
    report = json.loads(out.read_text())
    assert report["commits_scanned"] == 3
    assert report["pairs_considered"] == 0
    assert report["edges"] == []


def test_cli_stdout_matches_file_output(cochange_repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "scripts.graphify_cochange._utcnow", lambda: "2026-01-01T00:00:00+00:00"
    )
    assert main(_cli_args(cochange_repo, "-")) == 0
    stdout_payload = capsys.readouterr().out
    out = tmp_path / "report.json"
    assert main(_cli_args(cochange_repo, out)) == 0
    assert stdout_payload.encode() == out.read_bytes()


def test_cli_invalid_repo_exits_2(tmp_path, capsys):
    exit_code = main(["--repo", str(tmp_path / "nope"), "--since", "HEAD"])
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_cli_invalid_since_ref_exits_2(cochange_repo, capsys):
    exit_code = main(["--repo", str(cochange_repo), "--since", "not-a-real-ref"])
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err
