"""FakeReranker — the default `Reranker` dependency for every zero-GPU `Retriever` test (T-F4).

Real interface (ARCHITECTURE.md M7, owner E, `Reranker` is Retriever's injected collaborator):
`rerank(query: str, candidates: list[RerankCandidate]) -> list[RerankCandidate]`.

Deliberately **non-identity** — TEST-STRATEGY.md's "Fakes" section is explicit that an identity
fake was tried first and rejected: it made every `Retriever` test pass identically whether or not
`rerank()` was even called, so a `retrieve()` that dropped the call, reranked the wrong slice, or
mismatched ids would still have passed. Reversing the input order means a `Retriever` test must
assert the final order actually differs from the pre-rerank RRF order and matches this reversal.
"""

from contracts.retriever import RerankCandidate


class FakeReranker:
    """Deterministic, non-identity: reverses `candidates`. Records every call into `.calls` as
    `(query, [c.id for c in candidates])` — the *pre-rerank* candidate ids, in their input order —
    so a test can assert `rerank()` was actually invoked with the expected candidates.
    """

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, candidates: list[RerankCandidate]) -> list[RerankCandidate]:
        self.calls.append((query, [c.id for c in candidates]))
        return list(reversed(candidates))
