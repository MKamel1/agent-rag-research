"""Adaptive Pass-1 batch sizing (T-DOC21, `.claude/plans/giggly-tumbling-globe.md`).

Real data this session: TEI eviction (T-DOC19) genuinely frees ~24GB during Pass 1, but the
static `parse_batch_size` config default (4) never grew to use it -- a real Pass 1 run's batches
never exceeded 3 documents, MinerU's peak VRAM stayed ~6.7GB, and Pass 1 utilization landed at
43-46%, far below Pass 2's ~82-100% on the same hardware.

A precomputed batch-size-vs-VRAM curve isn't the right fix: two earlier real spikes found MinerU's
pipeline-backend peak VRAM is *flat* regardless of batch size (identical ~16GB peak at N=4 and
N=8) -- the real ceiling is MinerU's own internal 64-page window/`batch_ratio`, not document
count, so there's no stable per-document VRAM cost to divide free-VRAM by.

Instead: AIMD-style adaptive sizing (the same additive-increase/multiplicative-decrease shape TCP
congestion control uses for the same "find the ceiling without knowing it in advance" problem).
Grow the next batch a little if there's comfortable headroom; shrink it a lot if the margin is
thin. Converges toward "as large as safely fits" over a real run, self-tuning per-machine/
per-paper-mix, with no separate calibration step.
"""

import logging
from collections.abc import Callable

from app.gpu_headroom import free_vram_mib

logger = logging.getLogger(__name__)


class AdaptiveBatchSizer:
    """`next_size()` is the whole interface -- call it once per Pass-1 batch, immediately before
    slicing the next group of refs. No separate "record the result" callback: measuring free VRAM
    immediately before the *next* batch already reflects whatever the *previous* one (and any
    un-released model-cache residue accumulated across batches within one Pass-1 subprocess --
    ARCHITECTURE.md §3) actually did to the card. If residue piles up, free VRAM naturally shrinks
    and this backs off on its own -- an emergent property, not something handled separately.

    `safety_margin_mib` defaults to 3GB (not the 1GB first considered), given the real,
    still-unexplained OOM inside the TEI container this project hit even when total tracked usage
    looked under capacity (suspected CUDA allocator fragmentation, `.phase0-data/
    known-issue-pass2-oom.md`) -- a thinner margin risks reproducing exactly that class of failure.

    `max_size` is a hard ceiling *independent* of VRAM feedback -- a purely VRAM-driven grower
    could in principle keep growing indefinitely if VRAM stays comfortable, silently exhausting
    host RAM instead (N raw PDFs held in memory during batching is a real, separate resource VRAM
    measurement never sees, flagged by the PR #82 design review).
    """

    def __init__(
        self,
        initial_size: int,
        *,
        min_size: int = 1,
        max_size: int = 64,
        safety_margin_mib: int = 3072,
        growth_threshold_mib: int | None = None,
        growth_step: int = 4,
        vram_probe: Callable[[], int | None] = free_vram_mib,
    ):
        """Three real zones, not two: shrink at or below `safety_margin_mib` (danger); grow only
        once free VRAM clears `growth_threshold_mib` (comfortable, defaults to `2 *
        safety_margin_mib` -- at least another full margin's worth of headroom beyond the minimum
        safe level); hold steady in between. A two-zone (shrink-or-grow) design has no stable
        resting point -- it would oscillate every call even in a perfectly steady state.
        """
        if initial_size < min_size:
            raise ValueError(f"initial_size={initial_size} is below min_size={min_size}")
        if initial_size > max_size:
            raise ValueError(f"initial_size={initial_size} is above max_size={max_size}")
        self._current = initial_size
        self._min_size = min_size
        self._max_size = max_size
        self._safety_margin_mib = safety_margin_mib
        self._growth_threshold_mib = (
            growth_threshold_mib if growth_threshold_mib is not None else 2 * safety_margin_mib
        )
        self._growth_step = growth_step
        self._vram_probe = vram_probe

    def next_size(self) -> int:
        free_mib = self._vram_probe()
        if free_mib is None:
            logger.warning(
                "AdaptiveBatchSizer: VRAM probe unavailable, holding size at %d", self._current
            )
            return self._current

        if free_mib <= self._safety_margin_mib:
            new_size = max(self._current // 2, self._min_size)
        elif free_mib >= self._growth_threshold_mib:
            new_size = min(self._current + self._growth_step, self._max_size)
        else:
            new_size = self._current

        if new_size != self._current:
            logger.info(
                "AdaptiveBatchSizer: %d -> %d (free=%dMiB, margin=%dMiB)",
                self._current,
                new_size,
                free_mib,
                self._safety_margin_mib,
            )
        self._current = new_size
        return self._current
