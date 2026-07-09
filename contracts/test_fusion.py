"""Unit test for contracts/fusion.py's rrf_fuse, against synthetic rank inputs — this IS the
arbiter of "is the RRF formula right" per TEST-STRATEGY.md ("Contract tests" / VectorStore
contract, item 1): the formula is frozen in a checkable sense here, not left as a shared prose
description two adapters each reimplement.
"""

import pytest

from contracts.errors import ContractError
from contracts.fusion import RRF_K, rrf_fuse


def test_rrf_k_is_60():
    assert RRF_K == 60


def test_single_list_matches_hand_computed_1_indexed_formula():
    # doc "a" is rank 1 in both lists; doc "b" is rank 2 in both. hybrid_dense_weight=0.5 (vanilla
    # RRF).
    result = rrf_fuse(["a", "b"], ["a", "b"], hybrid_dense_weight=0.5)
    scores = dict(result)
    expected_a = 0.5 * (1 / (RRF_K + 1)) + 0.5 * (1 / (RRF_K + 1))
    expected_b = 0.5 * (1 / (RRF_K + 2)) + 0.5 * (1 / (RRF_K + 2))
    assert scores["a"] == pytest.approx(expected_a)
    assert scores["b"] == pytest.approx(expected_b)
    # rank 1 must outscore rank 2.
    assert scores["a"] > scores["b"]


def test_doc_missing_from_one_list_is_excluded_from_that_term_not_given_a_rank():
    # "only_dense" appears solely in the dense list; its score must be exactly the dense term alone,
    # not e.g. penalized by treating the missing sparse rank as some large number.
    result = rrf_fuse(["only_dense"], [], hybrid_dense_weight=0.5)
    scores = dict(result)
    assert scores["only_dense"] == pytest.approx(0.5 * (1 / (RRF_K + 1)))


def test_union_of_both_lists_is_returned_no_id_dropped():
    result = rrf_fuse(["a", "b"], ["c"], hybrid_dense_weight=0.5)
    ids = {doc_id for doc_id, _ in result}
    assert ids == {"a", "b", "c"}


def test_changing_hybrid_dense_weight_changes_result_in_expected_direction():
    # "d" is top of the dense list only; "s" is top of the sparse list only. Weighting toward dense
    # must raise d's score and lower s's score, and vice versa.
    dense_ranked = ["d", "s"]
    sparse_ranked = ["s", "d"]

    mostly_dense = dict(rrf_fuse(dense_ranked, sparse_ranked, hybrid_dense_weight=0.9))
    mostly_sparse = dict(rrf_fuse(dense_ranked, sparse_ranked, hybrid_dense_weight=0.1))

    assert mostly_dense["d"] > mostly_sparse["d"]
    assert mostly_dense["s"] < mostly_sparse["s"]


def test_result_sorted_descending_by_score_with_deterministic_tiebreak():
    # "x" and "y" tie exactly (same rank in both lists) -> tie-break by id ascending.
    result = rrf_fuse(["x", "y", "z"], ["x", "y", "z"], hybrid_dense_weight=0.5)
    ids_in_order = [doc_id for doc_id, _ in result]
    assert ids_in_order == ["x", "y", "z"]
    scores = [score for _, score in result]
    assert scores == sorted(scores, reverse=True)


def test_duplicate_id_within_one_ranked_list_is_a_contract_error():
    with pytest.raises(ContractError):
        rrf_fuse(["a", "a"], ["b"], hybrid_dense_weight=0.5)


@pytest.mark.parametrize("bad_weight", [-0.1, 1.1])
def test_hybrid_dense_weight_out_of_range_is_a_contract_error(bad_weight):
    with pytest.raises(ContractError):
        rrf_fuse(["a"], ["b"], hybrid_dense_weight=bad_weight)


def test_non_positive_rrf_k_is_a_contract_error():
    with pytest.raises(ContractError):
        rrf_fuse(["a"], ["b"], hybrid_dense_weight=0.5, rrf_k=0)
