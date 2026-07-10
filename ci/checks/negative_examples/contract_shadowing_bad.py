"""Negative-example fixture for check (b) — CONVENTIONS.md §0.2/§12 (ci/checks/contract_shadowing.py).

Redefines `EmbedderInfo`, a name that already exists in `contracts/embedder.py`, from outside
`contracts/`. Never imported or executed — read as text by `ci/checks/test_checks.py`.
"""


class EmbedderInfo:
    model_id: str
    dim: int
