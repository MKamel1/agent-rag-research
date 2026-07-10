"""Negative-example fixture for check (a) — CONVENTIONS.md §1/§12 (ci/checks/vendor_isolation.py).

Deliberately imports a vendor SDK as if from a non-adapter module (e.g. a `Retriever`). Never
imported or executed by anything except `ci/checks/test_checks.py`, which reads this file as text
and feeds it to `check_a` — it does not need to actually run.
"""

import qdrant_client  # noqa: F401 — deliberately unused; this file is never executed

from mineru import parse_pdf  # noqa: F401 — same vendor-leak shape, different vendor


class Retriever:
    def __init__(self) -> None:
        self.client = qdrant_client.QdrantClient("localhost:6333")
