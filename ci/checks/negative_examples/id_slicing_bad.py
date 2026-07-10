"""Negative-example fixture for check (h) — CONVENTIONS.md §0.8/§12 (ci/checks/id_slicing.py).

Manually slices `chunk_id`'s `"{paper_id}:c{n}"` encoding instead of resolving it via
`DocumentStore.get_chunk`. Never imported or executed; `ci/checks/test_checks.py` reads this file
as text.
"""


def paper_id_of(chunk_id: str) -> str:
    return chunk_id.split(":")[0]
