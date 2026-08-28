"""Offline tests for app/exp_confidence_v0_support.py plumbing (NB-QW2 commit ①) and scoring
aggregation (commit ②).

Zero-GPU, zero-network by suite config: these exercise capture loading/validation, sentence
splitting, pair accounting, and arm inference with synthetic fixtures on disk. The real scorer
(`MiniCheckScorer`, a 770M model) is never instantiated here -- `score_item`/`score_items`/
`dump_arm` are exercised through a fake scorer with a `score_pair` method, same seam the real one
implements.
"""

from __future__ import annotations

import json

import pytest

from app.exp_confidence_v0_support import (
    CaptureError,
    ScoredItem,
    build_pairs,
    chunk_words,
    dump_arm,
    load_capture,
    score_item,
    score_items,
    scored_item_to_dict,
    split_answer_sentences,
)


class _FakeScorer:
    """Deterministic stand-in for `MiniCheckScorer.score_pair`: 1.0 if the claim's first word
    appears in the passage, else 0.0 -- enough to exercise max/mean/median aggregation without a
    model."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def score_pair(self, passage_text: str, claim_text: str) -> float:
        self.calls.append((passage_text, claim_text))
        first_word = claim_text.split()[0].strip(".,!?")
        return 1.0 if first_word in passage_text else 0.0


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


def test_load_capture_infers_arm_from_filename_when_metadata_omits_it(tmp_path):
    # The real affordance-arm captures (2026-08-24-*) carry no `_metadata.arm` field.
    path = tmp_path / "run-affordance.answerable.json"
    payload = json.loads(_write_capture(tmp_path, name="tmp.json").read_text())
    del payload["_metadata"]["arm"]
    path.write_text(json.dumps(payload))
    arm, items = load_capture(path)
    assert arm == "answerable"
    assert len(items) == 1

    absent_path = tmp_path / "run-affordance.absent.json"
    absent_path.write_text(json.dumps(payload))
    arm, _ = load_capture(absent_path)
    assert arm == "absent"


def test_load_capture_still_rejects_missing_arm_with_no_filename_hint(tmp_path):
    path = _write_capture(tmp_path, name="cap.json")
    payload = json.loads(path.read_text())
    del payload["_metadata"]["arm"]
    path.write_text(json.dumps(payload))
    with pytest.raises(CaptureError, match="_metadata.arm"):
        load_capture(path)


def test_chunk_words_splits_long_text_into_n_word_chunks():
    text = " ".join(f"w{i}" for i in range(1250))
    chunks = chunk_words(text, n=500)
    assert len(chunks) == 3
    assert len(chunks[0].split()) == 500
    assert len(chunks[-1].split()) == 250


def test_chunk_words_empty_text_yields_one_empty_chunk():
    assert chunk_words("") == [""]


def test_score_item_aggregates_max_over_passages_then_mean_median_min_max(tmp_path):
    _, items = load_capture(_write_capture(tmp_path))
    scorer = _FakeScorer()
    scored = score_item(items[0], scorer)

    assert isinstance(scored, ScoredItem)
    # "The rate was 0.6 per million miles." -> first word "The" not in either passage -> 0.0
    # "This is lower than before." -> first word "This" not in either passage -> 0.0
    # (fake scorer keys off literal first-word containment; both sentences miss both passages)
    assert scored.aggregate is not None
    assert scored.aggregate.n_sentences == len(scored.sentences)
    maxima = [s.max_support for s in scored.sentences]
    assert scored.aggregate.mean == pytest.approx(sum(maxima) / len(maxima))
    assert scored.aggregate.min == min(maxima)
    assert scored.aggregate.max == max(maxima)
    # every sentence x every served passage was actually scored (build_pairs' own invariant)
    assert len(scorer.calls) == build_pairs(items[:1])


def test_score_item_returns_none_for_zero_sentence_answer(tmp_path):
    item = {
        "question_id": "Q-EMPTY",
        "question_text": "q",
        "answer_text": "..",  # splits to zero sentences (degenerate fragment, < min chars)
        "supporting_passages": [{"paper_id": "p1", "passage_excerpt": "context"}],
    }
    _, items = load_capture(_write_capture(tmp_path, items=[item]))
    assert score_item(items[0], _FakeScorer()) is None


def test_score_items_skips_zero_sentence_items(tmp_path):
    good = {
        "question_id": "Q-GOOD",
        "question_text": "q",
        "answer_text": "This sentence is long enough to keep.",
        "supporting_passages": [{"paper_id": "p1", "passage_excerpt": "keep context"}],
    }
    empty = {
        "question_id": "Q-EMPTY",
        "question_text": "q",
        "answer_text": "..",
        "supporting_passages": [{"paper_id": "p1", "passage_excerpt": "context"}],
    }
    _, items = load_capture(_write_capture(tmp_path, items=[good, empty]))
    scored = score_items(items, _FakeScorer())
    assert len(scored) == 1
    assert scored[0].question_id == "Q-GOOD"


def test_dump_arm_writes_committed_json_with_no_level_or_probability_wording(tmp_path):
    _, items = load_capture(_write_capture(tmp_path))
    scored = score_items(items, _FakeScorer())
    out_path = tmp_path / "out.json"

    payload = dump_arm(out_path, "answerable", "fixture.json", len(items), scored)

    on_disk = json.loads(out_path.read_text())
    assert on_disk == payload
    assert payload["_metadata"]["arm"] == "answerable"
    assert payload["_metadata"]["n_items_loaded"] == 1
    assert payload["_metadata"]["n_items_scored"] == 1
    label = payload["_metadata"]["prototype_label"]
    assert "UNVALIDATED PROTOTYPE" in label
    for banned in ("high confidence", "low confidence", "medium confidence", "probability of"):
        assert banned not in label.lower()
    item = payload["items"][0]
    assert item["question_id"] == "Q-SYNTH-001"
    assert set(item["answer_aggregate"]) == {"mean", "median", "min", "max"}


def test_scored_item_to_dict_round_trips_sentence_and_passage_scores(tmp_path):
    _, items = load_capture(_write_capture(tmp_path))
    scored = score_item(items[0], _FakeScorer())
    d = scored_item_to_dict(scored)
    assert len(d["sentence_scores"]) == scored.aggregate.n_sentences
    for sent_dict, sent in zip(d["sentence_scores"], scored.sentences, strict=True):
        assert sent_dict["max_support"] == sent.max_support
        assert len(sent_dict["per_passage"]) == 2  # 2 served passages in the synthetic fixture
