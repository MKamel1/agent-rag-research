"""FakeEmbedder — the default `Embedder` dependency for every zero-GPU test (T-F4).

Real interface (ARCHITECTURE.md M4, owner C): `embed(texts: list[str]) -> list[Vector]`,
property `info -> EmbedderInfo`. `contracts/embedder.py` owns the data shapes (`Vector`,
`EmbedderInfo`); this fake owns none of its own.
"""

import hashlib
import math
import random

from contracts.embedder import EmbedderInfo, Vector


class FakeEmbedder:
    """Deterministic hash -> unit vector. No model, no GPU, no randomness across runs: the same
    text always seeds the same `random.Random`, so `embed([t])` is stable across calls and
    processes. Different texts hash to different seeds, so (barring an astronomically unlikely
    hash collision) they yield different vectors.
    """

    def __init__(self, dim: int = 64, model_id: str = "fake-embedder", version: str = "v1"):
        self._info = EmbedderInfo(model_id=model_id, dim=dim, version=version)

    @property
    def info(self) -> EmbedderInfo:
        return self._info

    def embed(self, texts: list[str]) -> list[Vector]:
        """Order-preserving: `embed(texts)[i]` is always the vector for `texts[i]`."""
        return [self._hash_to_unit_vector(t) for t in texts]

    def _hash_to_unit_vector(self, text: str) -> Vector:
        # Seed a local PRNG from a stable hash of the text (not Python's salted `hash()`, which
        # varies per-process) so the same text always produces the same raw vector.
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self._info.dim)]
        norm = math.sqrt(sum(x * x for x in raw))
        if norm == 0.0:
            # Astronomically unlikely (all-zero draw), but fall back to a valid unit vector
            # rather than dividing by zero.
            raw[0] = 1.0
            norm = 1.0
        return [x / norm for x in raw]
