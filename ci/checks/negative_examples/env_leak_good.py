"""Positive-example fixture for check (d) (ci/checks/env_leak.py) — the knob comes from the
injected `Config` object, not the environment.
"""

from contracts.config import Config


def top_k(cfg: Config) -> int:
    return cfg.top_k
