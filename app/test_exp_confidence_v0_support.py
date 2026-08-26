"""Offline tests for app/exp_confidence_v0_support.py plumbing (NB-QW2 commit ①).

Zero-GPU, zero-network by suite config: these exercise capture loading/validation, sentence
splitting, and pair accounting with synthetic fixtures on disk. The scorer itself (commit ②)
is exercised through its pure aggregation helpers only.
"""

from __future__ import annotations

import json

import pytest

from app.exp_confidence_v0_support import (
    CaptureError,
    build_pairs,
    load_capture,
    split_answer_sentences,
)


def _write_capture(tmp_path, name="cap.json", arm="answerable", items=None):
    payload = {
        "_metadata": {"arm": arm, "description": "synthetic"},
        "ground_truth": items
        if items is not None
        else [
            {
                "question_id": "Q-SYNTH-001",
                "question_text": "What is the rate?",
                "answer_text": "The rate was 0.6 per million miles. This is lower than before.",
                "supporting_passages": [
                    {"paper_id": "1234.5678", "passage_excerpt": "Context passage one."},
                    {"paper_id": "1234.5678", "passage_excerpt": "Context passage two."},
                ],
                "n_passages_retrieved": 10,
                "n_passages_used": 2,
                "passages_truncated": False,
            }
        ],
    }
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def test_load_capture_round_trips_fields(tmp_path):
    path = _write_capture(tmp_path)
    arm, items = load_capture(path)
    assert arm == "answerable"
    assert len(items) == 1
    item = items[0]
    assert item.question_id == "Q-SYNTH-001"
    assert len(item.passages) == 2
    assert item.passages[0].paper_id == "1234.5678"
    assert item.n_passages_used == 2
    assert item.n_passages_retrieved == 10
    assert item.passages_truncated is False


def test_load_capture_rejects_missing_metadata_arm(tmp_path):
    path = _write_capture(tmp_path)
    payload = json.loads(path.read_text())
    del payload["_metadata"]["arm"]
    path.write_text(json.dumps(payload))
    with pytest.raises(CaptureError, match="_metadata.arm"):
        load_capture(path)


def test_load_capture_rejects_missing_item_key(tmp_path):
    bad_item = {"question_id": "Q-X", "answer_text": "text"}  # no passages / question_text
    path = _write_capture(tmp_path, items=[bad_item])
    with pytest.raises(CaptureError, match="missing"):
        load_capture(path)


def test_load_capture_rejects_zero_served_passages(tmp_path):
    item = {
        "question_id": "Q-ZERO",
        "question_text": "q",
        "answer_text": "a",
        "supporting_passages": [],
        "n_passages_used": 0,
    }
    path = _write_capture(tmp_path, items=[item])
    with pytest.raises(CaptureError, match="zero served passages"):
        load_capture(path)


def test_split_answer_sentences_basic_and_markdown():
    text = "**0.6 incidents** per million miles. That is `80%` lower!\nSecond line here."
    sentences = split_answer_sentences(text)
    assert any(s.startswith("0.6 incidents") for s in sentences)
    assert any("80%" in s for s in sentences)
    assert "Second line here." in sentences


def test_split_answer_sentences_drops_degenerate_fragments():
    sentences = split_answer_sentences("Short. This sentence is long enough to keep.")
    assert all(len(s) >= 8 for s in sentences)
    assert "This sentence is long enough to keep." in sentences


def test_build_pairs_counts_sentence_x_passage_grid(tmp_path):
    _, items = load_capture(_write_capture(tmp_path))
    # One answer -> 2 sentences x 2 served passages = 4 pairs.
    assert build_pairs(items) == 4
