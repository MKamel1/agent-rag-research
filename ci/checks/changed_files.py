"""Computes the changed-file list the enforcement job scans — the one thing that differs between
a `pull_request` run and a `push` run (CI job design note in the T-F6 ticket): a PR diffs against
its merge-base with the base branch; a push diffs against the commit before it, or, if this is a
branch's very first push (no "before" commit to diff against), against its merge-base with the
repo's default branch — deliberately *not* the empty tree. Diffing a first push against the empty
tree would list every file in the whole repository (a full-repo scan in disguise), re-flagging
legitimate pre-existing content the exact way the T-F6 ticket's design constraint warns against;
merge-base-with-default-branch keeps a first push scoped to what that branch actually adds, same
as every subsequent push on it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ZERO_SHA = "0000000000000000000000000000000000000000"


def compute_diff_base(event_name: str, event: dict, repo_root: Path) -> str:
    """The ref/sha to diff `HEAD` against, given the GitHub Actions event that triggered this run.

    `event` is the parsed `GITHUB_EVENT_PATH` payload. Raises `ValueError` on any event this
    workflow doesn't run for — the caller should not have invoked this for anything else.
    """
    if event_name == "pull_request":
        base_sha = event["pull_request"]["base"]["sha"]
        head_sha = event["pull_request"]["head"]["sha"]
        return _merge_base(repo_root, base_sha, head_sha)
    if event_name == "push":
        before = event.get("before", "")
        # A force-push (routine here -- GIT-WORKFLOW.md mandates `gh pr merge --rebase`, and
        # rebasing an open branch requires one) makes GitHub's `before` the branch's *previous*
        # head, which this clone no longer has any ref to. Blindly trusting it turns the next
        # `git diff before HEAD` into an exit-128 crash instead of a diff. Only trust `before` if
        # it actually resolves here; otherwise fall through to the same merge-base fallback used
        # for a brand-new branch's first push.
        if before and before != ZERO_SHA and _rev_exists(repo_root, before):
            return before
        default_branch = event.get("repository", {}).get("default_branch", "main")
        return _merge_base(repo_root, f"origin/{default_branch}", "HEAD")
    raise ValueError(f"compute_diff_base: unsupported event_name {event_name!r}")


def _rev_exists(repo_root: Path, rev: str) -> bool:
    """Whether `rev` resolves to a commit reachable in this clone. `check=False` is deliberate:
    a missing object is the expected case here (an orphaned pre-force-push SHA), not an error.
    """
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _merge_base(repo_root: Path, ref_a: str, ref_b: str) -> str:
    result = subprocess.run(
        ["git", "merge-base", ref_a, ref_b],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def list_changed_paths(diff_base: str, repo_root: Path) -> list[str]:
    """Repo-relative paths changed between `diff_base` and `HEAD`. A path deleted by the diff is
    included too (callers that need on-disk content, e.g. `build_diff_files`, skip those
    themselves).
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", diff_base, "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in result.stdout.splitlines() if p]


def list_deleted_paths(diff_base: str, repo_root: Path) -> list[str]:
    """Repo-relative paths the diff between `diff_base` and `HEAD` *deleted* -- the subset of
    `list_changed_paths` that no longer exists on disk at `HEAD`. `ci.checks.diff.build_diff_files`
    drops these (nothing to lint in a file that's gone), so this is the one place that information
    survives long enough to reach `ci.checks.sibling_tests.check_g`, which needs it to notice a
    deleted test file whose module wasn't otherwise touched (PR #12 design review, finding 1).
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=D", diff_base, "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [p for p in result.stdout.splitlines() if p]


def compute_changed_files(event_name: str, event: dict, repo_root: Path) -> list[str]:
    """Convenience wrapper: `list_changed_paths(compute_diff_base(...), repo_root)`."""
    return list_changed_paths(compute_diff_base(event_name, event, repo_root), repo_root)
