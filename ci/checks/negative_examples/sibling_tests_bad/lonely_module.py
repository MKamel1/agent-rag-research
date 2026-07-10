"""Negative-example fixture for check (g) — CONVENTIONS.md §0.7/§12 (ci/checks/sibling_tests.py).

A module source file with no sibling `test_lonely_module.py` next to it. `check_g` only cares
about existence at the *logical* path it's told to check, so `ci/checks/test_checks.py` attributes
this file's content to a synthetic `rag/lonely_module.py` path rather than checking this real
directory — this directory itself is never in scope for the real enforcement job (`check_g`'s
scope is `rag/` and `contracts/` only).
"""
