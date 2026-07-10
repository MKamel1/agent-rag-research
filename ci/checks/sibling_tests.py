"""Check (g) — CONVENTIONS.md §0.7 / §12: every module source file under `rag/`/`contracts/` needs
a sibling `test_<name>.py` in the same directory. This is the mechanical *existence* proxy only —
the M1a→M1b *ordering* rule (test committed before implementation) is a git-history check at that
milestone gate, not a per-push diff check (WORK-BREAKDOWN.md M1a), and out of scope here.

Scope is `rag/`/`contracts/` (`model.in_pipeline_scope`) — that is exactly and only what
CONVENTIONS.md §12(g) names; a file elsewhere (this package included) isn't a "module source
file" in that sense.
"""

from __future__ import annotations

from pathlib import Path

from ci.checks.model import DiffFile, Violation, in_pipeline_scope

_EXEMPT_NAMES = ("__init__.py", "conftest.py")


def check_g(files: list[DiffFile], repo_root: Path) -> list[Violation]:
    violations = []
    for f in files:
        if not _in_scope(f.path):
            continue
        sibling = repo_root / f.path
        sibling = sibling.parent / f"test_{sibling.name}"
        if not sibling.is_file():
            violations.append(
                Violation(
                    check="g",
                    path=f.path,
                    message=f"no sibling test file ({sibling.name}) in the same directory",
                )
            )
    return violations


def _in_scope(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    if not in_pipeline_scope(path):
        return False
    name = path.rsplit("/", 1)[-1]
    if name in _EXEMPT_NAMES or name.startswith("test_"):
        return False
    return True
