"""Check (g) — CONVENTIONS.md §0.7 / §12: every module source file under `rag/`/`contracts/`/`app/`
needs a sibling `test_<name>.py` in the same directory. This is the mechanical *existence* proxy
only — the M1a→M1b *ordering* rule (test committed before implementation) is a git-history check
at that milestone gate, not a per-push diff check (WORK-BREAKDOWN.md M1a), and out of scope here.

Scope is `rag/`/`contracts/`/`app/` (`model.in_pipeline_scope`; `app/` added by T-DOC29) — that is
exactly and only what CONVENTIONS.md §12(g) names; a file elsewhere (this package included) isn't
a "module source file" in that sense.

`files` (built from `changed`) only ever contains paths that still exist on disk
(`ci.checks.diff.build_diff_files` drops deletions, and `_in_scope` below excludes `test_`-prefixed
paths anyway) — so a diff that deletes `rag/test_config.py` alone, leaving `rag/config.py`
untouched, would otherwise sail through here unnoticed: the deletion never becomes a `DiffFile`,
and the untouched module is never rescanned (PR #12 design review, finding 1). `deleted_paths` is
the raw list of paths the diff deleted (`ci.checks.changed_files.list_deleted_paths`, threaded
through by `ci/run_enforcement.py`) — the one place that information still exists before
`build_diff_files` throws it away. `check_g` uses it to flag exactly that case: a deleted
`test_<name>.py` under `rag/`/`contracts/` scope whose sibling module still exists on disk.
"""

from __future__ import annotations

from pathlib import Path

from ci.checks.model import DiffFile, Violation, in_pipeline_scope

_EXEMPT_NAMES = ("__init__.py", "conftest.py")


def check_g(
    files: list[DiffFile],
    repo_root: Path,
    deleted_paths: list[str] | None = None,
) -> list[Violation]:
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
    for path in deleted_paths or []:
        sibling = _surviving_module_for_deleted_test(path, repo_root)
        if sibling is not None:
            violations.append(
                Violation(
                    check="g",
                    path=path,
                    message=(
                        f"deleted without also deleting its module ({sibling.name}), which still "
                        "exists on disk -- the module has silently lost its only test coverage"
                    ),
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


def _surviving_module_for_deleted_test(path: str, repo_root: Path) -> Path | None:
    """If `path` is a deleted `test_<name>.py` in `rag`/`contracts` scope whose sibling module
    (`<name>.py`) still exists on disk, return that module's path -- else `None`.
    """
    if not path.endswith(".py") or not in_pipeline_scope(path):
        return None
    name = path.rsplit("/", 1)[-1]
    if not name.startswith("test_"):
        return None
    sibling = repo_root / path
    sibling = sibling.parent / name[len("test_") :]
    return sibling if sibling.is_file() else None
