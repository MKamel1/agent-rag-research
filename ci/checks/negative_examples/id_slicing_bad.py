"""Negative-example fixture for check (h) — CONVENTIONS.md §0.8/§12 (ci/checks/id_slicing.py).

Manually slices the `.id` field's `"{paper_id}:c{n}"` encoding (`Hit.id`/`RerankCandidate.id`,
contracts/vector_index.py, contracts/retriever.py) instead of resolving it via
`DocumentStore.get_chunk`. Never imported or executed; `ci/checks/test_checks.py` reads this file
as text.
"""


def paper_id_of(candidate) -> str:
    return candidate.id.split(":")[0]
