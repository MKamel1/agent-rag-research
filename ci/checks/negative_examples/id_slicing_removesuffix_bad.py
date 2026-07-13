"""Negative-example fixture for check (h) — proves the removesuffix/removeprefix blind spot
(`.phase0-data/retriever-summary-id-proposal.md` §5, finding 2) is caught: an earlier version of
check (h) only matched split/slice syntax on the id, missing the removesuffix call below, which is
the exact pre-centralization shape `rag/retriever.py`'s `retrieve_papers()` used to have. Never
imported or executed; `ci/checks/test_checks.py` reads this file as text.
"""


def paper_id_of(candidate) -> str:
    return candidate.id.removesuffix(":summary")
