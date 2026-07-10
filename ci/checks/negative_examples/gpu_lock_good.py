"""Positive-example fixture for check (f) (ci/checks/gpu_lock.py) — the real adapter's `__init__`
declares `gpu_lock: GpuLock`, so the single-GPU rule (CONVENTIONS §6) can hold across processes.
"""

from contracts.gpu_lock import GpuLock


class TeiEmbedder:
    def __init__(self, model_id: str, base_url: str, gpu_lock: GpuLock) -> None:
        self.model_id = model_id
        self.base_url = base_url
        self.gpu_lock = gpu_lock
