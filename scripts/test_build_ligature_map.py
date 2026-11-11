"""Tests for scripts/build_ligature_map.py."""

from collections import Counter

from scripts.build_ligature_map import NEVER_REPAIR, build_map, candidates


def test_candidates_reinsert_after_each_f():
    c = candidates("efect")
    assert {"effect", "efiect", "eflect", "effiect", "efflect"} <= c
    assert "efect" not in c


def test_maps_unique_frequent_target_and_skips_real_words_and_ambiguity():
    counts = Counter({"efect": 900, "effect": 800, "fied": 5, "fixed": 100, "flied": 100,
                      "fiied": 100, "tif": 10, "tifi": 100})
    mapping, ambiguous = build_map(counts, {"effect", "fixed", "flied", "fiied", "tifi"},
                                   min_freq=50)
    assert mapping == {"efect": "effect"}  # "tif": too short; "fied": no frequent target
    counts["fiied"] = counts["flied"] = 100
    counts["ffied"] = 100  # now "fied" has several qualifying targets
    mapping, ambiguous = build_map(counts, {"effect", "flied", "fiied", "ffied"}, min_freq=50)
    assert "fied" not in mapping and ambiguous[0][0] == "fied"


def test_target_must_be_a_dictionary_word_unless_very_frequent():
    counts = Counter({"coeficient": 900, "coefficient": 800, "efect": 900, "effect": 800})
    mapping, _ = build_map(counts, {"effect"}, min_freq=50, nondict_min_freq=1000)
    assert mapping == {"efect": "effect"}


def test_real_word_t_is_never_remapped_and_denylist_honoured():
    counts = Counter({"fetcher": 5, "fletcher": 900})
    assert "fetcher" in NEVER_REPAIR
    assert build_map(counts, set(), min_freq=50, nondict_min_freq=100)[0] == {}
