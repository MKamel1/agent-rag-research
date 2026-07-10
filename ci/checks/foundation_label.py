"""Check (e) — CONVENTIONS.md §0.2 / §12, WORK-BREAKDOWN.md T-F7: a diff touching a
CODEOWNERS-protected path (`contracts/`, `rag/config.py`, `config.yaml`, `migrations/`,
`rag/fakes/`, `fixtures/`) must carry the `foundation-change` label.

Unlike every other check here, this one has no meaning on a bare `push` — a push event's payload
carries no PR, so there is no label list to check against (label context is a `pull_request`-only
concept in GitHub's model, not something this repo's own bootstrap invented). `run_enforcement.py`
handles that by not calling `check_e` at all on `push` runs, and printing an explicit "skipped:
push event has no label context" line instead of a silent no-op — see its module docstring.

Protected paths are read from `.github/CODEOWNERS` at check time rather than duplicated as a
constant here — `.github/CODEOWNERS` is the single source of truth (it's also what branch
protection reads), and copying its path list into a second file is exactly the kind of drift
CONVENTIONS §0.2 is warning about.
"""

from __future__ import annotations

import re
from pathlib import Path

from ci.checks.model import Violation

FOUNDATION_LABEL = "foundation-change"

_CODEOWNERS_LINE = re.compile(r"^(\S+)\s+@\S+")


def read_codeowners_paths(codeowners_path: Path) -> list[str]:
    """The path column of every non-comment, non-blank line in a CODEOWNERS file, e.g.
    `["/contracts/", "/rag/config.py", ...]`.
    """
    paths = []
    for line in codeowners_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _CODEOWNERS_LINE.match(line)
        if m:
            paths.append(m.group(1))
    return paths


def check_e(
    changed_paths: list[str], labels: list[str], codeowners_paths: list[str]
) -> list[Violation]:
    """`changed_paths` are repo-relative (no leading `/`); `codeowners_paths` are CODEOWNERS-style
    (leading `/`, directories trailing `/`) — normalized against each other here so callers don't
    have to.
    """
    if FOUNDATION_LABEL in labels:
        return []
    touched = [p for p in changed_paths if _is_protected(p, codeowners_paths)]
    if not touched:
        return []
    return [
        Violation(
            check="e",
            path=", ".join(sorted(touched)),
            message=(
                f"touches a foundation path without the {FOUNDATION_LABEL!r} label "
                "(CODEOWNERS + T-F7 sign-off protocol)"
            ),
        )
    ]


def _is_protected(changed_path: str, codeowners_paths: list[str]) -> bool:
    for owned in codeowners_paths:
        owned = owned.lstrip("/")
        if owned.endswith("/"):
            if changed_path.startswith(owned):
                return True
        elif changed_path == owned:
            return True
    return False
