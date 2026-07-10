"""Negative-example fixture for check (d) — CONVENTIONS.md §3/§12 (ci/checks/env_leak.py).

Reads the process environment directly instead of going through the injected `Config` object.
Never imported or executed; `ci/checks/test_checks.py` reads this file as text.

(This docstring avoids spelling out the two flagged calls verbatim — see the function bodies
below — so it doesn't trip the check itself and inflate the expected-violation count.)
"""

import os


def top_k_from_env() -> int:
    return int(os.getenv("TOP_K", "10"))


def gpu_lock_path() -> str:
    return os.environ["GPU_LOCK_PATH"]
