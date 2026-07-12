"""Positive-example fixture for check (h) (ci/checks/id_slicing.py) — resolves the chunk through
`DocumentStore`'s own interface instead of parsing its `.id`.
"""


def paper_id_of(candidate, document_store) -> str:
    return document_store.get_chunk(candidate.id).paper_id
