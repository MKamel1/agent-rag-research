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
from ci.run_enforcement import _is_scannable, main_local


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


def test_compute_diff_base_push_falls_back_when_before_sha_is_unreachable(tmp_path):
    # After a force-push (routine here -- GIT-WORKFLOW.md's rebase-merge policy requires one on
    # every rebased PR), GitHub's `before` is the branch's orphaned *previous* head: a real-looking
    # 40-hex SHA this clone has no ref to. Trusting it blindly used to make the next
    # `git diff before HEAD` crash with exit 128 (PR #174, `enforcement` job, 2026-07-27). It must
    # fall back to the merge-base instead of raising.
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    main_sha = _commit(repo, "on main")
    _git(repo, "update-ref", "refs/remotes/origin/main", main_sha)

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "b.py").write_text("y = 1\n")
    _commit(repo, "on feature")

    orphaned_before = "e8c552d" + "0" * 33  # well-formed 40-hex SHA, unreachable in this clone
    event = {"before": orphaned_before, "repository": {"default_branch": "main"}}
    assert compute_diff_base("push", event, repo) == main_sha


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


def test_compute_diff_base_pull_request_uses_merge_base_of_base_and_head_unaffected_by_before_sha(
    tmp_path,
):
    # The pull_request branch never reads event["before"] at all, so it was never susceptible to
    # the force-push orphaned-SHA bug above -- this is why violations were never actually missed
    # in practice: the pull_request-triggered run (unaffected) still caught them even while the
    # push-triggered `enforcement` job crashed with exit 128.
    repo = _init_repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    base_sha = _commit(repo, "base")

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "b.py").write_text("y = 1\n")
    head_sha = _commit(repo, "on feature")

    event = {"pull_request": {"base": {"sha": base_sha}, "head": {"sha": head_sha}}}
    assert compute_diff_base("pull_request", event, repo) == base_sha


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


# --- ci.run_enforcement.main_local (RI-23) ------------------------------------------------------
#
# The dev-machine entrypoint composes the same seams this file already covers (diff base → changed
# paths → DiffFiles → checks), so it belongs here with the throwaway-git-repo helpers above. These
# tests run the *real* checks against a scratch repo's real diff -- only check_testpaths is
# stubbed, since its subject (pyproject.toml's testpaths vs the whole tree) has no counterpart in
# a bare fixture repo.


def _pipeline_module(repo: Path, text: str = "x = 1\n") -> None:
    """A module under check scope, plus the sibling test file check (g) requires to let it be."""
    (repo / "rag").mkdir(exist_ok=True)
    (repo / "rag" / "retriever.py").write_text(text)
    (repo / "rag" / "test_retriever.py").write_text("")


def test_main_local_flags_a_real_violation_on_the_branch_diff(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _pipeline_module(repo)
    main_sha = _commit(repo, "base")
    # Simulate the remote-tracking ref a developer's clone has after `git fetch origin` --
    # `main_local`'s default base, no actual remote needed (same trick as the
    # compute_diff_base fallback tests above).
    _git(repo, "update-ref", "refs/remotes/origin/main", main_sha)

    _git(repo, "checkout", "-q", "-b", "feature")
    _pipeline_module(repo, "import os\nvalue = os.environ['X']\n")
    _commit(repo, "leak an env read")

    monkeypatch.setattr("ci.run_enforcement.check_testpaths", lambda repo_root: [])

    exit_code = main_local(repo_root=repo)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "[d]" in out  # the env read is flagged by the real check (d), not a stub
    assert "check (e): not run locally" in out  # honest about what a dev machine cannot check


def test_main_local_passes_a_clean_branch_diff(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    _pipeline_module(repo)
    main_sha = _commit(repo, "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", main_sha)

    _git(repo, "checkout", "-q", "-b", "feature")
    _pipeline_module(repo, "y = 2\n")
    _commit(repo, "clean change")

    monkeypatch.setattr("ci.run_enforcement.check_testpaths", lambda repo_root: [])

    assert main_local(repo_root=repo) == 0
    assert "enforcement: PASS" in capsys.readouterr().out


def test_main_local_names_the_unresolvable_base_ref_and_exits_nonzero_without_a_traceback(
    tmp_path, capsys
):
    # A fresh/local clone may simply not have fetched origin/main yet; that must come back as a
    # readable message naming the ref, not a git CalledProcessError traceback.
    repo = _init_repo(tmp_path)
    _pipeline_module(repo)
    _commit(repo, "base")

    exit_code = main_local(["no-such-ref"], repo_root=repo)

    out = capsys.readouterr().out
    assert exit_code == 2
    assert "no-such-ref" in out
