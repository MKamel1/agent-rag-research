"""Turns a real `git diff` into `DiffFile`s — the one place that understands unified-diff hunk
syntax, so no individual check has to.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ci.checks.model import DiffFile

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def build_diff_files(paths: list[str], repo_root: Path, diff_base: str) -> list[DiffFile]:
    """One `DiffFile` per path in `paths` (repo-relative, e.g. from `changed_files.py`), each
    carrying its current full content plus the lines added since `diff_base`.

    A path deleted since `diff_base` (no longer on disk) is silently skipped — nothing to lint in
    a file that no longer exists in the diff's result.
    """
    out = []
    for path in paths:
        abs_path = repo_root / path
        if not abs_path.is_file():
            continue
        content = abs_path.read_text()
        added = _added_lines(repo_root, diff_base, path)
        out.append(DiffFile(path=path, abs_path=abs_path, content=content, added_lines=added))
    return out


def _added_lines(repo_root: Path, diff_base: str, path: str) -> list[tuple[int, str]]:
    result = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", diff_base, "--", path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    added: list[tuple[int, str]] = []
    next_line = None
    for line in result.stdout.splitlines():
        m = _HUNK_HEADER.match(line)
        if m:
            next_line = int(m.group(1))
            continue
        if next_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            added.append((next_line, line[1:]))
            next_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue  # removed line consumes no line number in the new file
        else:
            next_line += 1
    return added
