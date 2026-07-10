"""Check (b) — CONVENTIONS.md §0.2 / §12: a diff must not define a type whose name already exists
in `contracts/`, anywhere outside `contracts/` itself. That's always a bug in the module (a second,
drifting definition of a frozen shape), never grounds for a local redefinition (CONVENTIONS §0.2).

Two pieces: `discover_contract_names` (reads the real `contracts/` package) and `check_b` (a pure
function over an explicit name set, so tests can hand it a small synthetic set instead of
depending on the real `contracts/` directory's current contents).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ci.checks.model import DiffFile, Violation

# Line-based, not `ast.parse`-per-line: a `class Foo:` header is only valid syntax together with
# its (unparsed, possibly-not-even-added) body, so parsing one added line in isolation raises
# `SyntaxError` on exactly the header line this check needs to recognize. A regex over the header
# shape avoids needing the body at all.
_CLASS_DEF = re.compile(r"^\s*class\s+(\w+)\s*[:(]")
_TYPED_DICT_ASSIGN = re.compile(r"^\s*(\w+)\s*=\s*(?:\w+\.)?TypedDict\(")


def discover_contract_names(contracts_dir: Path) -> set[str]:
    """Every top-level class name defined in `contracts_dir`'s own `.py` files (excluding its
    tests and `conftest.py`) — the frozen names a diff outside `contracts/` must not shadow.
    """
    names: set[str] = set()
    for path in contracts_dir.glob("*.py"):
        if path.name in ("conftest.py",) or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
    return names


def check_b(files: list[DiffFile], contract_names: set[str]) -> list[Violation]:
    """Flags any added line in a non-`contracts/` file that defines a class or `TypedDict` alias
    whose name is already one of `contract_names`.
    """
    violations = []
    for f in files:
        if f.path == "contracts" or f.path.startswith("contracts/"):
            continue
        for line_no, text in f.added_lines:
            name = _defined_name(text)
            if name is not None and name in contract_names:
                violations.append(
                    Violation(
                        check="b",
                        path=f.path,
                        line=line_no,
                        message=(
                            f"defines {name!r}, which already exists in contracts/ — a shape "
                            "mismatch belongs in contracts/ + the T-F7 protocol, never a second "
                            "local definition"
                        ),
                    )
                )
    return violations


def _defined_name(line: str) -> str | None:
    m = _CLASS_DEF.match(line) or _TYPED_DICT_ASSIGN.match(line)
    return m.group(1) if m else None
