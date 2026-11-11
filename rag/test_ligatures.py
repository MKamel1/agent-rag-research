"""Tests for rag.ligatures: map-driven repair, case handling, and offset mapping."""

import random
import re

from rag.ligatures import _MAP, repair_ligatures, repair_token, repair_with_offsets


def test_repairs_known_damaged_words():
    assert repair_ligatures("the efect of diferent coeficients") == \
        "the effect of different coefficients"


def test_preserves_case_pattern_and_punctuation():
    assert repair_token("Efect") == "Effect"
    assert repair_token("EFECT") == "EFFECT"
    assert repair_ligatures("(Efect), 'frst'; EFECTS.") == "(Effect), 'first'; EFFECTS."


def test_mixed_case_identifiers_untouched():
    assert repair_token("eFect") == "eFect"


def test_correct_spelling_is_never_altered():
    text = "The effect of different coefficients, first-order; tariff, offset; x = 3.5."
    assert repair_ligatures(text) == text


def test_every_map_value_is_a_fixed_point_and_no_chains():
    assert all(v not in _MAP for v in _MAP.values())


def test_whitespace_and_non_ascii_preserved():
    assert repair_ligatures("efect\n\tdiferent  é") == "effect\n\tdifferent  é"


def test_offsets_map_back_to_whole_original_words():
    text = "a efect b frst."
    repaired, to_orig = repair_with_offsets(text)
    assert repaired == "a effect b first."
    m = re.search("effect", repaired)
    assert text[to_orig(m.start()):to_orig(m.end(), end=True)] == "efect"
    m = re.search("ffec", repaired)  # span ends mid-word -> whole original word
    assert text[to_orig(m.start()):to_orig(m.end(), end=True)] == "efect"
    m = re.search("b first.", repaired)
    assert text[to_orig(m.start()):to_orig(m.end(), end=True)] == "b frst."


def test_offsets_round_trip_on_random_text():
    rng = random.Random(0)
    words = ["efect", "the", "frst", "x", "diferent", "ok"]
    for _ in range(200):
        text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 8)))
        repaired, to_orig = repair_with_offsets(text)
        assert repaired == repair_ligatures(text)
        for m in re.finditer(r"\S+", repaired):
            orig = text[to_orig(m.start()):to_orig(m.end(), end=True)]
            assert repair_ligatures(orig) == m.group()
