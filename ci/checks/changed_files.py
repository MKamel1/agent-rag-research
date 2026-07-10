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
        if before and before != ZERO_SHA:
            return before
        default_branch = event.get("repository", {}).get("default_branch", "main")
        return _merge_base(repo_root, f"origin/{default_branch}", "HEAD")
    raise ValueError(f"compute_diff_base: unsupported event_name {event_name!r}")


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


def compute_changed_files(event_name: str, event: dict, repo_root: Path) -> list[str]:
    """Convenience wrapper: `list_changed_paths(compute_diff_base(...), repo_root)`."""
    return list_changed_paths(compute_diff_base(event_name, event, repo_root), repo_root)
