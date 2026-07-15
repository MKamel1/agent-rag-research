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

import csv
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.gpu_headroom import free_vram_mib

logger = logging.getLogger(__name__)

_DECISION_LOG_HEADER = [
    "timestamp",
    "old_size",
    "new_size",
    "free_vram_mib",
    "safety_margin_mib",
    "growth_threshold_mib",
    "zone",
]


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

    `decision_log_path`, if given, appends one CSV row per `next_size()` call (timestamp, old/new
    size, free VRAM at decision time, the configured margin/threshold, and which zone the decision
    landed in) -- real, structured evidence for investigating a real Pass-1 run after the fact,
    the same pattern this project's own continuous `gpu_cpu_perf_log.csv` sampler has already
    proven valuable for. Deliberately a plain CSV append, not Python `logging` -- this project
    already found that `logger.info()` calls silently vanish in `app/ingest.py`/`app/
    parse_phase.py` today (neither configures a handler), and a scattered stdout line is harder to
    analyze after the fact than one row per decision in a dedicated file regardless. `None`
    (default) disables logging entirely -- no file created, no per-call overhead.
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
        decision_log_path: str | Path | None = None,
    ):
        """Three real zones, not two: shrink at or below `safety_margin_mib` (danger); grow only
        once free VRAM clears `growth_threshold_mib` (comfortable, defaults to `2 *
        safety_margin_mib` -- at least another full margin's worth of headroom beyond the minimum
        safe level); hold steady in between. A two-zone (shrink-or-grow) design has no stable
        resting point -- it would oscillate every call even in a perfectly steady state.
        """
        if min_size < 1:
            # Guards the real origin of a caller (`rag/orchestrator.py`'s parse_phase()) doing
            # `i += size` with no floor -- a size of 0 would hang the loop forever. Loud and
            # immediate here, not a silent max(size, 1) clamp downstream that would mask it.
            raise ValueError(f"min_size={min_size} must be >= 1")
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
        self._decision_log_path = Path(decision_log_path) if decision_log_path else None

    def next_size(self) -> int:
        free_mib = self._vram_probe()
        if free_mib is None:
            logger.warning(
                "AdaptiveBatchSizer: VRAM probe unavailable, holding size at %d", self._current
            )
            self._log_decision(self._current, self._current, None, "probe_unavailable")
            return self._current

        if free_mib <= self._safety_margin_mib:
            new_size = max(self._current // 2, self._min_size)
            zone = "shrink"
        elif free_mib >= self._growth_threshold_mib:
            new_size = min(self._current + self._growth_step, self._max_size)
            zone = "grow"
        else:
            new_size = self._current
            zone = "hold"

        if new_size != self._current:
            logger.info(
                "AdaptiveBatchSizer: %d -> %d (free=%dMiB, margin=%dMiB)",
                self._current,
                new_size,
                free_mib,
                self._safety_margin_mib,
            )
        old_size = self._current
        self._current = new_size
        self._log_decision(old_size, new_size, free_mib, zone)
        return self._current

    def _log_decision(
        self, old_size: int, new_size: int, free_mib: int | None, zone: str
    ) -> None:
        """Append one CSV row -- real, structured evidence for a post-hoc investigation of a real
        Pass-1 run (per the user's explicit request after this session's real, still-unexplained
        OOM history: "keep a close log of it to be able to investigate later"). No-op when
        `decision_log_path` wasn't configured, so this stays free for tests/default usage.
        """
        if self._decision_log_path is None:
            return
        is_new_file = not self._decision_log_path.exists()
        with self._decision_log_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if is_new_file:
                writer.writerow(_DECISION_LOG_HEADER)
            writer.writerow(
                [
                    datetime.now(UTC).isoformat(),
                    old_size,
                    new_size,
                    free_mib if free_mib is not None else "",
                    self._safety_margin_mib,
                    self._growth_threshold_mib,
                    zone,
                ]
            )
