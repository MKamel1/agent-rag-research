"""Negative-example fixture for check (f) — CONVENTIONS.md §6/§12 (ci/checks/gpu_lock.py).

A real, GPU-bound `Embedder` adapter whose `__init__` omits `gpu_lock: GpuLock` — the exact bug
§6 says is "not a judgment call". Never imported or executed; `ci/checks/test_checks.py` parses
this file's source with `ast`.
"""


class TeiEmbedder:
    def __init__(self, model_id: str, base_url: str) -> None:
        self.model_id = model_id
        self.base_url = base_url
