"""Check (f) — CONVENTIONS.md §6 / §12: a real `Embedder`/`Summarizer`/`Reranker` adapter's
`__init__` must declare a `gpu_lock: GpuLock` parameter — the single-GPU rule's only enforcement
mechanism, since two such adapters constructed without one can co-reside and blow the 24GB budget
across processes. "Real adapter" here means a class named like one of the three, outside
`contracts/` (the interfaces) and `rag/fakes/` (which are exempt by construction — a `FakeEmbedder`
holds no GPU) — a `Fake`-prefixed class name is skipped defensively even inside neither directory.

Structural, so (unlike the lexical checks) this reads each changed file's *whole* current content,
not just the diff's added lines — a constructor's shape is a property of the file as it now
stands, not of which lines happened to change this push.
"""

from __future__ import annotations

import ast

from ci.checks.model import DiffFile, Violation

# Curated, not derived -- extend this when a new GPU-bound adapter class name pattern lands.
_ADAPTER_SUFFIXES = ("Embedder", "Summarizer", "Reranker")
_EXEMPT_PREFIXES = ("contracts/", "rag/fakes/")


def check_f(files: list[DiffFile]) -> list[Violation]:
    violations = []
    for f in files:
        if f.path.startswith(_EXEMPT_PREFIXES):
            continue
        if not f.path.endswith(".py"):
            continue
        try:
            tree = ast.parse(f.content, filename=f.path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name.startswith("Fake"):
                continue
            if not node.name.endswith(_ADAPTER_SUFFIXES):
                continue
            init = _find_init(node)
            if init is None or not _has_gpu_lock_param(init):
                violations.append(
                    Violation(
                        check="f",
                        path=f.path,
                        line=node.lineno,
                        message=(
                            f"class {node.name!r} looks like a real GPU-bound adapter but its "
                            "__init__ doesn't declare a `gpu_lock: GpuLock` parameter"
                        ),
                    )
                )
    return violations


def _find_init(class_node: ast.ClassDef) -> ast.FunctionDef | None:
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            return item
    return None


def _has_gpu_lock_param(init_node: ast.FunctionDef) -> bool:
    args = init_node.args
    all_params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    return any(param.arg == "gpu_lock" for param in all_params)
