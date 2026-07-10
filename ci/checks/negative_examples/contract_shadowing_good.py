"""Positive-example fixture for check (b) (ci/checks/contract_shadowing.py) — defines a class, but
its name doesn't collide with anything in `contracts/`.
"""


class RetrieverConfig:
    top_k: int
