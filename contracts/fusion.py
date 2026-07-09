"""RRF fusion (DATA-CONTRACTS.md "M6 VectorIndex" — "RRF fusion formula (frozen)").

This formula is a pure function, factored once here, and both `FakeVectorStore` and the real
Qdrant adapter must call it — never reimplement it locally (that would silently reintroduce the
two-implementations-of-one-decision problem `contracts/` exists to prevent).

    score(d) = hybrid_dense_weight     * 1/(RRF_K + rank_dense(d))
             + (1 - hybrid_dense_weight) * 1/(RRF_K + rank_sparse(d))

`rank_dense`/`rank_sparse` are each item's 1-indexed rank in the dense-only and sparse/BM25-only
result lists respectively — a document missing from one list is simply excluded from that term,
not given a rank (i.e. NOT treated as an infinite/worst rank; its score is just the other term
alone).
"""

from contracts.errors import ContractError

RRF_K = 60  # named constant, not a Config lever — part of the fusion algorithm itself (CONTEXT.md
# "Lever" definition), so it lives here rather than on Config.


def rrf_fuse(
    dense_ranked_ids: list[str],
    sparse_ranked_ids: list[str],
    hybrid_dense_weight: float,
    rrf_k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Fuse two independently-ranked id lists into one score per id, via weighted Reciprocal Rank
    Fusion.

    Preconditions:
      - `dense_ranked_ids`/`sparse_ranked_ids` each contain no duplicate ids (a proper ranking
        lists each document once); violating this is a `ContractError`, not a silently-wrong
        score.
      - `0.0 <= hybrid_dense_weight <= 1.0` (it is a convex-combination weight,
        DATA-CONTRACTS.md §M6).
      - `rrf_k > 0`.

    Postcondition: returns one `(id, score)` pair for every id appearing in *either* input list
    (their union — no id is dropped for appearing in only one list), sorted by `score`
    descending; ties are broken by `id` ascending so the result is fully deterministic for a
    given input (needed for a reproducible unit test and for `VectorIndex.rebuild()`'s
    "reproduces the same references" invariant, ADR-04).
    """
    if len(set(dense_ranked_ids)) != len(dense_ranked_ids):
        raise ContractError("rrf_fuse: dense_ranked_ids contains a duplicate id")
    if len(set(sparse_ranked_ids)) != len(sparse_ranked_ids):
        raise ContractError("rrf_fuse: sparse_ranked_ids contains a duplicate id")
    if not (0.0 <= hybrid_dense_weight <= 1.0):
        raise ContractError(
            f"rrf_fuse: hybrid_dense_weight must be in [0, 1], got {hybrid_dense_weight}"
        )
    if rrf_k <= 0:
        raise ContractError(f"rrf_fuse: rrf_k must be > 0, got {rrf_k}")

    dense_rank = {doc_id: i + 1 for i, doc_id in enumerate(dense_ranked_ids)}  # 1-indexed
    sparse_rank = {doc_id: i + 1 for i, doc_id in enumerate(sparse_ranked_ids)}

    scores: dict[str, float] = {}
    for doc_id in dense_rank.keys() | sparse_rank.keys():
        score = 0.0
        if doc_id in dense_rank:
            score += hybrid_dense_weight * (1.0 / (rrf_k + dense_rank[doc_id]))
        if doc_id in sparse_rank:
            score += (1.0 - hybrid_dense_weight) * (1.0 / (rrf_k + sparse_rank[doc_id]))
        scores[doc_id] = score

    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
