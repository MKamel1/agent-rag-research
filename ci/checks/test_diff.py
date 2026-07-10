"""Direct unit tests for the composition seams `ci/run_enforcement.py` wires together, previously
only exercised indirectly by live CI runs and not by this package's per-function self-tests (PR #12
design review, finding 3):

- `ci.checks.diff.build_diff_files` and its hunk-parser (`_added_lines`) — the seam every check's
  `added_lines` input flows through. Needs a throwaway `tmp_path` git repo to diff against.
- `ci.checks.changed_files.compute_diff_base` — in particular its first-push fallback (a brand-new
  branch's `before` SHA is all-zeros, so it must diff against the merge-base with the default
  branch instead of the empty tree). Also needs a throwaway git repo.
- `ci.run_enforcement._is_scannable` — pure path-string logic (`.py`-only, excludes this package's
  own fixture/proof directories), so it needs no git fixture at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ci.checks.changed_files import ZERO_SHA, compute_diff_base
from ci.checks.diff import build_diff_files
from ci.run_enforcement import _is_scannable


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_build_diff_files_reports_added_lines_with_correct_line_numbers(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "mod.py"
    target.write_text("a = 1\nb = 2\nc = 3\n")
    base_sha = _commit(repo, "base")

    target.write_text("a = 1\nb = 2\nnew_line = 4\nc = 3\n")
    _commit(repo, "add a line")

    files = build_diff_files(["mod.py"], repo, base_sha)

    assert len(files) == 1
    f = files[0]
    assert f.path == "mod.py"
    assert f.content == "a = 1\nb = 2\nnew_line = 4\nc = 3\n"
    assert f.added_lines == [(3, "new_line = 4")]


def test_build_diff_files_running_line_counter_survives_a_removal_before_an_addition(tmp_path):
    # Regression coverage for the hunk-parser's running line counter: a removed line consumes no
    # line number in the new file, so a later addition in the same diff must still land on the
    # right post-edit line number, not be thrown off by the earlier removal.
    repo = _init_repo(tmp_path)
    target = repo / "mod.py"
    target.write_text("a = 1\nb = 2\nnew_line = 4\nc = 3\n")
    base_sha = _commit(repo, "base")

    target.write_text("a = 1\nc = 3\nd = 4\n")  # removes "b = 2" and "new_line = 4", adds "d = 4"
    _commit(repo, "remove two, add one")

    files = build_diff_files(["mod.py"], repo, base_sha)

    assert len(files) == 1
    assert files[0].added_lines == [(3, "d = 4")]


def test_build_diff_files_skips_a_path_deleted_since_the_diff_base(tmp_path):
    # There's nothing to lint in a file that no longer exists in the diff's result -- this is the
    # behavior `ci.checks.changed_files.list_deleted_paths` exists to route around for check_g.
    repo = _init_repo(tmp_path)
    target = repo / "mod.py"
    target.write_text("a = 1\n")
    base_sha = _commit(repo, "base")

    target.unlink()
    _commit(repo, "delete mod.py")

    assert build_diff_files(["mod.py"], repo, base_sha) == []


def test_build_diff_files_treats_a_brand_new_file_as_entirely_added(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "existing.py").write_text("x = 1\n")
    base_sha = _commit(repo, "base")

    (repo / "new_mod.py").write_text("y = 1\nz = 2\n")
    _commit(repo, "add new_mod.py")

    files = build_diff_files(["new_mod.py"], repo, base_sha)

    assert len(files) == 1
    assert files[0].added_lines == [(1, "y = 1"), (2, "z = 2")]


# --- compute_diff_base ----------------------------------------------------------------------


def test_compute_diff_base_push_uses_before_sha_when_present(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    before_sha = _commit(repo, "first")
    (repo / "a.py").write_text("x = 2\n")
    _commit(repo, "second")

    event = {"before": before_sha, "repository": {"default_branch": "main"}}
    assert compute_diff_base("push", event, repo) == before_sha


def test_compute_diff_base_first_push_falls_back_to_merge_base_with_default_branch(tmp_path):
    # A brand-new branch's push event has an all-zeros "before" SHA -- there's no prior commit on
    # this branch to diff against. Diffing against the empty tree (the naive fallback) would list
    # every file in the repo, a full-repo scan in disguise (PR #12 design review, finding 3 names
    # this as one of the three composition seams with no direct test coverage). The real fallback
    # is the merge-base with the default branch, matching how a PR diffs against its base.
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    main_sha = _commit(repo, "on main")
    # Simulate the remote-tracking ref that `.github/workflows/ci.yml`'s explicit
    # `git fetch origin main` sets up in the real job -- no actual remote needed for this test.
    _git(repo, "update-ref", "refs/remotes/origin/main", main_sha)

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "b.py").write_text("y = 1\n")
    _commit(repo, "on feature")

    event = {"before": ZERO_SHA, "repository": {"default_branch": "main"}}
    assert compute_diff_base("push", event, repo) == main_sha


# --- _is_scannable ----------------------------------------------------------------------------


def test_is_scannable_accepts_an_ordinary_python_file():
    assert _is_scannable("rag/config.py") is True


def test_is_scannable_rejects_non_python_files():
    assert _is_scannable("README.md") is False
    assert _is_scannable(".github/workflows/ci.yml") is False


def test_is_scannable_rejects_negative_examples_fixtures():
    assert _is_scannable("ci/checks/negative_examples/blind_except_bad.py") is False


def test_is_scannable_rejects_proof_socket_block_files():
    assert _is_scannable("ci/proof_socket_block/test_real_network_blocked.py") is False
