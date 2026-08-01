"""`app/dashboard/tag_pool.py` -- one persistent pool of arXiv focus-area queries, stored at
`<data_dir>/tag_pool.json`, dashboard-owned.

**Why this exists:** tag edits made from the dashboard used to be run-scoped
(`controller._maybe_build_override` wrote them into a scratch `<data_dir>/.run_overrides/<run_id>/
config.yaml` that `_cleanup_run_cwd` later deleted) -- every edit built its own private pool that
died with the run, and the next run silently reverted to the base `config.yaml` queries. This
module is the fix: a sidecar the dashboard owns, seeded from `config.yaml` on first touch and never
written back to it -- `config.yaml` stays the operator's own file, seed and fallback only.

**Shape:** `{"active": [...], "held": [{"query": ..., "held_at": ISO-8601Z}], "seeded_from":
"config.yaml", "updated_at": ISO-8601Z}`. Removal is HOLD, not delete -- a held tag stays listed
and one call to `restore` brings it back; nothing is ever destroyed.

**Locking:** mutations (`add`/`hold`/`restore`) serialize through the SAME
`controller._control_lock(data_dir)` every run-control op already uses -- imported, not
reinvented, so a tag edit can never interleave with a run-control op and there is never a second
lock over the same data dir to deadlock against. `controller._control_lock` is constructed with
`is_singleton=True` for exactly this module's sake: `_maybe_build_override` (composing a run's
`focus_area_queries`) calls `add`/`hold` from INSIDE its own already-held `_control_lock` when
`keywords`/`remove_keywords` are part of the same request -- `is_singleton=True` makes every
`_control_lock(data_dir)` call for the same data dir resolve to the SAME `FileLock` instance, so
that nested acquire is a cheap, safe, same-object reentrant increment rather than a second
open-file-description competing with the first (which is what plain `flock()` would do, and
`filelock` 3.29's own deadlock detector would immediately reject).

`load`/`active_queries` are pure reads and deliberately do NOT take that lock: `GET /api/status`
polls every ~4s, and `server.py`'s own docstring is explicit that a `POST /api/control` may block
for seconds inside `pause`/`stop`/`resume` waiting for a process to die -- a status poll must never
queue behind that. Every write (seed-on-first-touch included) is write-temp + `os.replace` (atomic
rename), so an unlocked read can never observe a torn/partial file, only the last complete write.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_POOL_NAME = "tag_pool.json"


def _pool_path(data_dir: Path) -> Path:
    return Path(data_dir) / _POOL_NAME


def _seed(seed_queries: list[str]) -> dict:
    return {
        "active": list(seed_queries), "held": [],
        "seeded_from": "config.yaml", "updated_at": datetime.now(UTC).isoformat(),
    }


def _write(data_dir: Path, pool: dict) -> dict:
    """Write-temp + `os.replace` (POSIX-atomic rename) -- matches `controller.py`'s own manifest-
    write pattern (finding #4 there): an unlocked `load()` can never observe a torn JSON file."""
    pool = {**pool, "updated_at": datetime.now(UTC).isoformat()}
    path = _pool_path(data_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pool, indent=2))
    tmp.replace(path)
    return pool


def _read_or_seed(data_dir: Path, seed_queries: list[str]) -> dict:
    """Reads the pool, seeding (and persisting) it from `seed_queries` if the file is absent, or a
    corrupt/unreadable file is found -- re-seeding rather than raising into a status poll, but
    logging a WARNING first: silently discarding an operator's held tags would be worse than the
    error would have been.

    ponytail: the seed-on-first-touch write here is NOT lock-guarded (see module docstring for
    why `load`/`active_queries` never take `_control_lock`) -- two concurrent first touches could
    both seed and both write, but both write IDENTICAL content (the same `seed_queries`), so the
    race is benign. Upgrade to a locked seed only if seeding ever stops being purely a function of
    `seed_queries`.
    """
    path = _pool_path(data_dir)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return _write(data_dir, _seed(seed_queries))
    try:
        pool = json.loads(raw)
        if not isinstance(pool, dict) or "active" not in pool or "held" not in pool:
            raise ValueError("tag_pool.json is missing 'active'/'held'")
    except (ValueError, TypeError) as e:
        logger.warning(
            "tag_pool.json at %s is corrupt (%s) -- re-seeding from config.yaml's "
            "focus_area_queries; any held tags recorded there are lost", path, e,
        )
        return _write(data_dir, _seed(seed_queries))
    return pool


def load(data_dir: Path, seed_queries: list[str]) -> dict:
    """`{"active": [...], "held": [...]}` (plus `seeded_from`/`updated_at`) -- read-only, no lock
    (see module docstring). Seeds from `seed_queries` on first touch."""
    return _read_or_seed(Path(data_dir), seed_queries)


def active_queries(data_dir: Path, seed_queries: list[str]) -> list[str]:
    """`load(...)["active"]` -- what `controller._maybe_build_override` composes a run's
    `focus_area_queries` from."""
    return load(data_dir, seed_queries)["active"]


def add(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict:
    """Appends `tags` to `active`, de-duplicated; a tag currently `held` is moved BACK to active
    rather than duplicated. Idempotent and order-preserving."""
    from app.dashboard import controller

    data_dir = Path(data_dir)
    with controller._control_lock(data_dir):
        pool = _read_or_seed(data_dir, seed_queries)
        held = {h["query"] for h in pool["held"]}
        for tag in tags:
            if tag in held:
                pool["held"] = [h for h in pool["held"] if h["query"] != tag]
                held.discard(tag)
            if tag not in pool["active"]:
                pool["active"].append(tag)
        return _write(data_dir, pool)


def hold(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict:
    """Moves `tags` from `active` to `held`, stamped `held_at`. A tag not currently active is a
    harmless no-op (mirrors the old `remove_keywords` semantics). Refused with
    `controller.InvalidOverrideError` -- pool left byte-identical -- when holding every active tag
    would leave the downloader with nothing to search."""
    from app.dashboard import controller

    data_dir = Path(data_dir)
    with controller._control_lock(data_dir):
        pool = _read_or_seed(data_dir, seed_queries)
        remaining = [q for q in pool["active"] if q not in tags]
        if not remaining:
            raise controller.InvalidOverrideError(
                "hold_tags would remove every active tag -- refusing, the downloader would have "
                "nothing left to search"
            )
        held_at = datetime.now(UTC).isoformat()
        newly_held = [{"query": q, "held_at": held_at} for q in pool["active"] if q in tags]
        pool["active"] = remaining
        pool["held"] = pool["held"] + newly_held
        return _write(data_dir, pool)


def purge(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict:
    """Removes `tags` from `held` entirely -- the one destructive tag action. Refused with
    `controller.InvalidOverrideError` -- pool left byte-identical -- if any named tag is currently
    `active`: purge is reachable only from the held column (see `index.html`'s X-button semantics),
    so a tag can never be destroyed in one gesture. An unknown/not-held tag is a harmless no-op."""
    from app.dashboard import controller

    data_dir = Path(data_dir)
    with controller._control_lock(data_dir):
        pool = _read_or_seed(data_dir, seed_queries)
        active = set(pool["active"])
        blocked = [t for t in tags if t in active]
        if blocked:
            raise controller.InvalidOverrideError(
                f"purge_tags refused: {blocked!r} is currently active -- hold it first"
            )
        tags = set(tags)
        pool["held"] = [h for h in pool["held"] if h["query"] not in tags]
        return _write(data_dir, pool)


def restore(data_dir: Path, seed_queries: list[str], tags: list[str]) -> dict:
    """Moves `tags` currently in `held` back to `active`. A tag not currently held is a harmless
    no-op."""
    from app.dashboard import controller

    data_dir = Path(data_dir)
    with controller._control_lock(data_dir):
        pool = _read_or_seed(data_dir, seed_queries)
        tags = set(tags)
        moved = [h["query"] for h in pool["held"] if h["query"] in tags]
        pool["held"] = [h for h in pool["held"] if h["query"] not in tags]
        for query in moved:
            if query not in pool["active"]:
                pool["active"].append(query)
        return _write(data_dir, pool)
