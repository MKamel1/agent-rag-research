"""Unit tests for `rag/method_aliases.py` — the curated method-vocabulary map behind
`McpServer.scan_methods`. Covers the three contracts the scan tool depends on: resolution
(exact / case-insensitive / unique-substring / literal fallback / ambiguity refusal), the
pattern grammar (plain fragments word-guarded; regex fragments like stems and acronyms used
verbatim), and the registry surface (`list_methods` sorted, human-readable).
"""

import re

import pytest

from rag.method_aliases import (
    METHOD_ALIASES,
    build_method_regex,
    list_methods,
    resolve_method,
)


# --- resolution --------------------------------------------------------------------------
def test_resolve_exact_canonical_family():
    canonical, aliases = resolve_method("reciprocal rank fusion (RRF)")
    assert canonical == "reciprocal rank fusion (RRF)"
    assert r"\brrf\b" in aliases


def test_resolve_case_insensitive_canonical():
    canonical, _ = resolve_method("GIDAS (german in-depth accident study)".upper())
    assert canonical.startswith("GIDAS")


def test_resolve_short_form_hits_family_via_alias_containment():
    canonical, aliases = resolve_method("RRF")
    assert "RRF" in canonical
    assert any("rrf" in a for a in aliases)


def test_resolve_long_inflected_form_hits_family_via_stem():
    # callers type the long/inflected form; the alias stem (\brerank) must still resolve
    canonical, aliases = resolve_method("reranking")
    assert "reranking" in canonical or "rerank" in canonical
    assert any("rerank" in a for a in aliases)


def test_resolve_unknown_method_falls_back_to_literal():
    canonical, aliases = resolve_method("totally unknown widget method")
    assert canonical == "totally unknown widget method"
    assert aliases == ["totally unknown widget method"]


def test_resolve_ambiguous_substring_raises_rather_than_guessing():
    # "benchmark" sits inside several families; results must never depend on dict order
    with pytest.raises(ValueError, match="multiple families"):
        resolve_method("benchmark")


# --- pattern grammar ---------------------------------------------------------------------
def test_plain_fragment_is_word_guardsed():
    pattern = build_method_regex(["lora"])
    assert re.search(pattern, "we apply LoRA adapters", re.IGNORECASE)
    assert not re.search(pattern, "exploratory lorazepam analysis", re.IGNORECASE)


def test_stem_fragment_matches_inflections():
    # the whole point of verbatim fragments: \brerank matches reranking/reranked/reranker
    pattern = build_method_regex([r"\brerank"])
    for text in ("reranking candidates", "reranked by", "the reranker"):
        assert re.search(pattern, text, re.IGNORECASE), text


def test_stem_fragment_survives_digit_suffixes():
    # \bmais\b would NOT match MAIS3+ (the digit kills the trailing boundary) — \bmais must
    pattern = build_method_regex([r"\bmais"])
    assert re.search(pattern, "MAIS3+F and MAIS2+F outcomes", re.IGNORECASE)


def test_built_pattern_is_an_alternation_of_all_family_fragments():
    _, aliases = resolve_method("RRF")
    pattern = build_method_regex(aliases)
    for text, expected in (
        ("reciprocal rank fusion (RRF)", True),
        ("fused with RRF at k=60", True),
        ("late rank fusion", True),
        ("unrelated prose", False),
    ):
        assert bool(re.search(pattern, text, re.IGNORECASE)) is expected, text


# --- registry surface --------------------------------------------------------------------
def test_registry_families_are_nonempty_and_lowercase_fragments():
    for canonical, aliases in METHOD_ALIASES.items():
        assert aliases, f"{canonical}: empty family"
        for alias in aliases:
            assert alias == alias.lower(), f"{canonical}: mixed-case fragment {alias!r}"


def test_list_methods_sorted_and_readable():
    names = list_methods()
    assert names == sorted(names)
    assert len(names) == len(METHOD_ALIASES)
    assert all("\\" not in name for name in names), "family names must be human-readable"
