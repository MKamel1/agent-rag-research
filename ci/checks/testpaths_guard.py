"""Check that every `test_*.py` in the repository sits inside pytest's collected set -- the
mechanical guard over `pyproject.toml`'s `testpaths` allow-list (CONVENTIONS.md §0: a rule that
only lives in prose is a suggestion, and an allow-list with no checker is exactly that).

`testpaths` names the directories pytest collects from; files outside them are invisible to CI
while still sitting in the tree. That is correct for the one documented exclusion --
`ci/proof_socket_block/`, whose suite proves a real network call gets blocked and so is invoked
explicitly by the enforcement job rather than picked up by the default socket-disabled collection
(see pyproject.toml's comment and that file's own docstring) -- and silently wrong for anything
else: add a top-level package, move a directory, or mistype a `testpaths` entry, and tests stop
running while the build stays green. This check turns that state into a red build instead, with
`ci/proof_socket_block/` as the single named exemption, so removing the exemption is a visible
code change here rather than a side effect of some unrelated edit.

Repo-wide by nature, unlike checks (a)-(d)/(f)-(h): those scan only the changed files because
their rules are about *content*, where a full-repo scan would re-flag pre-existing violations on
every future push (the accumulating-debt trap described in `ci/run_enforcement.py`'s docstring).
This check has no such trap -- either the tree satisfies it today or it does not, so fixing it
fixes it permanently -- and its failure mode lives precisely in changes a `.py`-diff cannot see:
the edited half (`pyproject.toml`) is not Python source, and the affected half (tests dropped out
of collection) may be no diff whatsoever when a directory moves or an entry is deleted.
Diff-scoping this check would guard nothing.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from ci.checks.model import Violation

# The one deliberate exclusion (module docstring has the reasoning; pyproject.toml's comment and
# ci/proof_socket_block/test_real_network_blocked.py's own docstring have the provenance).
_EXEMPT_PREFIXES = ("ci/proof_socket_block/",)

# Walk hygiene, not collection semantics: hidden directories (.git, .venv, ...) and bytecode
# caches contain no reportable test files. pytest's default norecursedirs skips more than this;
# anything beyond these two categories is a testpaths entry's business to name, not ours to guess.
_SKIP_DIR_NAMES = frozenset({"__pycache__"})


def check_testpaths(repo_root: Path) -> list[Violation]:
    """Returns one Violation per file matching pyproject.toml's `python_files` that no `testpaths`
    entry covers. The allow-list is read from pyproject.toml itself rather than hardcoded, so the
    guard tracks the config as it changes. A missing pyproject.toml / `[tool.pytest.ini_options]`
    table raises here on purpose: without the list there is no invariant to verify, and failing
    loudly beats silently passing.
    """
    ini = tomllib.loads((repo_root / "pyproject.toml").read_text())["tool"]["pytest"][
        "ini_options"
    ]
    patterns = ini.get("python_files") or ["test_*.py"]
    # No `testpaths` key means pytest falls back to collecting from the rootdir, which makes
    # every matching file here part of the collected set.
    roots = [str(p).strip().rstrip("/") for p in (ini.get("testpaths") or ["."])]

    violations = []
    for dirpath, dirnames, filenames in repo_root.walk(top_down=True):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIR_NAMES
        )
        for filename in filenames:
            if not any(Path(filename).match(pat) for pat in patterns):
                continue
            rel = (Path(dirpath) / filename).relative_to(repo_root).as_posix()
            if rel.startswith(_EXEMPT_PREFIXES):
                continue
            if any(rel == r or rel.startswith(r + "/") for r in roots):
                continue
            violations.append(
                Violation(
                    check="testpaths",
                    path=rel,
                    message=(
                        "matches python_files but sits outside every testpaths entry "
                        f"{roots} -- pytest collects nothing from it, so it cannot fail CI; "
                        "add its directory to pyproject.toml's testpaths or exempt it "
                        "explicitly in ci/checks/testpaths_guard.py"
                    ),
                )
            )
    return sorted(violations, key=lambda v: v.path)
