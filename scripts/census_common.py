"""Scaffolding shared between this repo's artefact-census instruments (RI-M1's archived
run-log census, `archived_run_census.py`; RI-M4's truncation census, `truncation_census.py`).

Both walk artefacts the system has already produced and rank where a count concentrates -- this
module holds only that shared ranking mechanic. Nothing pipeline-specific lives here; each
census still owns its own data model, since a chunk-token tally and a log-event tally have
nothing else in common worth forcing into one shape.
"""

from collections.abc import Mapping


def rank_by_count(counts: Mapping[str, int], n: int = 10) -> list[tuple[str, int]]:
    """Highest count first, ties broken by key for a deterministic report. A key with a zero (or
    absent) count is dropped -- a census exists to show where something concentrates, not to
    list every key that was never involved."""
    return sorted(
        ((key, count) for key, count in counts.items() if count),
        key=lambda pair: (-pair[1], pair[0]),
    )[:n]
