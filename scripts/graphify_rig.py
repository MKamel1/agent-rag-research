"""RIG-lite build/test structure collector (T-G15) — a deterministic, execution-free map of this
repo's test suite and CI enforcement surface, so an agent can answer "which tests exist, what do
they import (hence roughly exercise), and which checks enforce CI?" without re-deriving it by
exploration (RIG/SPADE: build/test artifacts as a first-class graph layer).

Usage:

    python -m scripts.graphify_rig --root PATH [--out FILE] [--ci-dir ci]

Emits one JSON document: discovered ``test_*.py``/``*_test.py`` files with their prefixed imports
extracted via :mod:`ast` only (no test is ever executed), the enforcement script and check-module
names under ``--ci-dir``, counts, and per-file parse failures. Stdlib only; all ordering is
deterministic. Exit 2 when ``--root`` is missing/not a directory, else 0.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any

SKIP_DIRS = frozenset(
    {
        ".git",
        ".worktrees",
        ".claude",
        "graphify-out",
        "__pycache__",
        "pdf_cache",
        "fixtures",
        "blobs",
        "node_modules",
        ".venv",
    }
)

COVERED_PREFIXES = ("rag.", "app.", "contracts.", "scripts.", "migrations.")

ENFORCEMENT_SCRIPT_NAME = "run_enforcement.py"

STDOUT = "-"


def _is_test_file(name: str) -> bool:
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def node_id_hint(relpath: str | Path) -> str:
    """Graphify node-id convention: posix relpath, extension dropped, ``/`` and ``.`` to ``_``,
    lowercased (e.g. ``rag/test_chunker.py`` -> ``rag_test_chunker``)."""
    stem = str(Path(relpath).with_suffix("")).replace(os.sep, "/")
    return stem.replace("/", "_").replace(".", "_").lower()


def _covered_imports(tree: ast.Module) -> list[str]:
    """Module names imported by a parsed test file that start with a known package prefix.

    Only absolute imports participate (``level == 0``): resolving a relative import against the
    test file's own package would guess at runtime path config this static scan deliberately
    avoids. Third-party/stdlib imports are filtered out here, not recorded.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(
                alias.name for alias in node.names if alias.name.startswith(COVERED_PREFIXES)
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.startswith(COVERED_PREFIXES):
                found.add(node.module)
    return sorted(found)


def _parse_test(path: Path, rel: str) -> tuple[list[str], dict[str, str] | None]:
    """Parse one test file AST-only; returns (covered_imports, parse_error_entry_or_None)."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], {"file": rel, "error": f"OSError: {exc}"}
    except UnicodeDecodeError as exc:
        return [], {"file": rel, "error": f"UnicodeDecodeError: {exc.reason}"}
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        location = f" line {exc.lineno}" if exc.lineno else ""
        return [], {"file": rel, "error": f"SyntaxError: {exc.msg}{location}"}
    except ValueError as exc:  # e.g. source containing null bytes
        return [], {"file": rel, "error": f"ValueError: {exc}"}
    return _covered_imports(tree), None


def _ci_checks(root: Path, ci_dir: str) -> dict[str, Any]:
    checks_dir = root / ci_dir / "checks"
    check_modules = sorted(
        path.stem
        for path in checks_dir.glob("*.py")
        if path.name != "__init__.py" and not path.name.startswith("test_")
    )
    return {
        "enforcement_script": (Path(ci_dir) / ENFORCEMENT_SCRIPT_NAME).as_posix(),
        "check_modules": check_modules,
    }


def collect_inventory(root: Path, ci_dir: str = "ci") -> dict[str, Any]:
    """Build the full RIG-lite inventory for ``root``. Pure function of the tree contents."""
    tests: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    covered: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            if not _is_test_file(filename):
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(root).as_posix()
            covers, error = _parse_test(path, rel)
            covered.update(covers)
            tests.append({"file": rel, "covers_modules": covers, "node_id_hint": node_id_hint(rel)})
            if error is not None:
                parse_errors.append(error)

    tests.sort(key=lambda entry: entry["file"])
    parse_errors.sort(key=lambda entry: entry["file"])
    return {
        "tests": tests,
        "ci_checks": _ci_checks(root, ci_dir),
        "counts": {"test_files": len(tests), "covered_modules": len(covered)},
        "parse_errors": parse_errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="repository root to scan")
    parser.add_argument("--out", default=STDOUT, help=f"output file path, or {STDOUT!r} for stdout")
    parser.add_argument("--ci-dir", default="ci", help="CI directory relative to --root")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"graphify_rig: root is not an existing directory: {args.root}", file=sys.stderr)
        return 2

    payload = json.dumps(collect_inventory(root, args.ci_dir), indent=2)
    if args.out == STDOUT:
        print(payload)
    else:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
