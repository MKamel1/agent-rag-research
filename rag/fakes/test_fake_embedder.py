"""Tests for FakeEmbedder (T-F4) — determinism, distinctness, normalization, and dim."""

import math

import pytest

from rag.fakes.fake_embedder import FakeEmbedder


def test_same_text_yields_same_vector():
    embedder = FakeEmbedder(dim=16)
    v1 = embedder.embed(["hello world"])[0]
    v2 = embedder.embed(["hello world"])[0]
    assert v1 == v2


def test_different_texts_yield_different_vectors():
    embedder = FakeEmbedder(dim=16)
    v1, v2 = embedder.embed(["hello world", "goodbye world"])
    assert v1 != v2


def test_output_is_l2_normalized():
    embedder = FakeEmbedder(dim=32)
    for vec in embedder.embed(["some text", "", "a longer piece of text about causal inference"]):
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0)


def test_output_length_matches_configured_dim():
    embedder = FakeEmbedder(dim=8)
    vecs = embedder.embed(["a", "b", "c"])
    assert all(len(v) == 8 for v in vecs)


def test_embed_is_order_preserving():
    embedder = FakeEmbedder(dim=16)
    texts = ["one", "two", "three"]
    vecs = embedder.embed(texts)
    individually = [embedder.embed([t])[0] for t in texts]
    assert vecs == individually


def test_info_reflects_constructor_args():
    embedder = FakeEmbedder(dim=32, model_id="my-fake", version="v9")
    assert embedder.info.dim == 32
    assert embedder.info.model_id == "my-fake"
    assert embedder.info.version == "v9"
