"""Check (c) — CONVENTIONS.md §4 / §12: no `except Exception:` and no bare `except:` in the diff.

Uses ruff's bundled `E722` (bare except) and `BLE001` (blind except, flake8-blind-except) rather
than hand-rolled regex — both are syntax-aware (won't trip on the string `"except:"` in a comment
or docstring the way a naive grep would) and `BLE`/`E` are already how this repo lints everywhere
else (`pyproject.toml`). Confirmed both actually fire (not just E722, which is bundled by default,
but BLE001 too, which needs `"BLE"` added to `[tool.ruff.lint] select` — done in this same PR)
before relying on this instead of a grep.

Ruff lints a whole file (it has to — a diff hunk alone isn't valid Python to parse), so this
reports a violation only when the flagged line is also one of the diff's added lines; that keeps
the check diff-scoped like every other lexical check here, even though the underlying tool sees
the whole file.
"""

from __future__ import annotations

import json
import subprocess

from ci.checks.model import DiffFile, Violation

_RUFF_CODES = ("E722", "BLE001")


def check_c(files: list[DiffFile]) -> list[Violation]:
    violations = []
    for f in files:
        added_line_numbers = {line_no for line_no, _ in f.added_lines}
        if not added_line_numbers:
            continue
        result = subprocess.run(
            [
                "ruff",
                "check",
                "--select",
                ",".join(_RUFF_CODES),
                "--output-format=json",
                "--no-cache",
                str(f.abs_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if not result.stdout.strip():
            continue
        for diagnostic in json.loads(result.stdout):
            row = diagnostic["location"]["row"]
            if row not in added_line_numbers:
                continue
            violations.append(
                Violation(
                    check="c",
                    path=f.path,
                    line=row,
                    message=f"{diagnostic['code']}: {diagnostic['message']}",
                )
            )
    return violations
