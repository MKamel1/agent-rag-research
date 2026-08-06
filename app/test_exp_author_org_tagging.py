"""`app/exp_author_org_tagging.py` test suite. Zero-GPU, zero-network, zero-corpus
(TEST-STRATEGY.md golden rule): drives the module's pure/synchronous helpers
(`_first_page_text`, `_reservoir_sample`, `_score`) against small synthetic fixtures.

`run`/`main` touch a real DocumentStore/corpus, the live Ollama-backed OllamaSummarizer, and a
real GpuLock -- deliberately NOT exercised here. Their actual end-to-end behavior (including the
tp=0/fp=0 precision=nan edge case for `_score`) was exercised by the real corpus/GPU validation
run documented in
.superpowers/sdd/2026-08-05-author-org-tagging-validation/task-4-report.md.
"""

import random

from app.exp_author_org_tagging import _first_page_text, _reservoir_sample, _score
from contracts.provenance import Block

PAPER_ID = "local:deadbeef0000"


def _block(idx: int, text: str, page: int = 0) -> Block:
    return Block(
        block_id=f"{PAPER_ID}:b{idx}",
        paper_id=PAPER_ID,
        text=text,
        type="prose",
        page=page,
        bbox=(0.0, 0.0, 100.0, 200.0),
        section_path="",
        index=idx,
    )


def test_first_page_text_joins_only_page_zero_blocks():
    blocks = [_block(0, "hello", page=0), _block(1, "world", page=0)]
    assert _first_page_text(blocks) == "hello\nworld"


def test_first_page_text_excludes_blocks_on_other_pages():
    blocks = [_block(0, "keep", page=0), _block(1, "drop", page=1)]
    assert _first_page_text(blocks) == "keep"


def test_reservoir_sample_returns_exactly_k_items_when_stream_is_larger():
    sample = _reservoir_sample(range(100), 10)
    assert len(sample) == 10


def test_reservoir_sample_returns_all_items_when_stream_is_smaller_than_k():
    sample = _reservoir_sample(range(3), 10)
    assert sorted(sample) == [0, 1, 2]


def test_reservoir_sample_is_uniform_ish_over_a_known_population():
    # Fixed seed: reproducible, not a full statistical test -- just confirms no item is
    # structurally favored (e.g. always taking the first k) over many independent draws.
    rng_state = random.getstate()
    random.seed(0)
    try:
        counts = {i: 0 for i in range(10)}
        for _ in range(2000):
            for item in _reservoir_sample(range(10), 3):
                counts[item] += 1
        # Each of the 10 items should appear in roughly 3/10 of draws (~600 of 2000 samples-worth
        # of slots, i.e. ~600 counts each out of 6000 total slots). Loose bounds only.
        for item, count in counts.items():
            assert 400 < count < 800, f"item {item} appeared {count} times, expected ~600"
    finally:
        random.setstate(rng_state)


def test_score_normal_case_computes_precision_recall_tp_fp_fn():
    predicted = {"a", "b", "c"}
    actual = {"a", "b", "d"}
    result = _score(predicted, actual)
    assert result["tp"] == 2
    assert result["fp"] == 1
    assert result["fn"] == 1
    assert result["precision"] == 2 / 3
    assert result["recall"] == 2 / 3


def test_score_empty_predicted_and_actual_returns_nan_precision_and_recall():
    result = _score(set(), set())
    assert result["tp"] == 0
    assert result["fp"] == 0
    assert result["fn"] == 0
    assert result["precision"] != result["precision"]  # nan != nan
    assert result["recall"] != result["recall"]
