"""`python -m app.reindex_idf` -- OG-27: retrofit the native sparse-vector IDF modifier
(T-DOC27, `rag/vector_index.py`'s `_sparse_vector_params()`) onto a vector-store collection that
was created before that fix landed. `_ensure_collection` only sets the modifier at *creation*
time -- there's no in-place "alter collection" for it -- so the production `papers` collection
(created pre-T-DOC27) is still running without real IDF weighting even though the fix has been
in code for a while (V0's quality gate was met without it, so this was never urgent).

`VectorIndex.rebuild()` already does exactly this migration: scroll every point out, drop the
collection, recreate it (now WITH the modifier, via `_ensure_collection`), re-upsert every point
verbatim. No re-embed, no GPU. What was missing was a CLI wrapping it with the safety this
destructive-in-place operation needs -- see `rebuild()`'s own docstring: it holds every point
only in memory between `delete_collection` and the re-upsert, so a crash/OOM/power-loss mid-run
loses the collection outright.

Three safety layers, in order:

1. **Snapshot-first.** Refuses to touch the collection without a snapshot on disk. Default:
   takes one itself via `app.snapshot.run_snapshot` (the same consistent SQLite+blobs+vector-store
   backup T-DOC57 built). `--i-have-a-snapshot` skips taking a new one but does NOT just trust the
   flag -- `_verify_snapshot_present` still checks a completed backup of this exact collection,
   with a non-empty vector-store snapshot file, actually exists on disk.
2. **Point-count invariant.** `VectorIndex.point_count()` is read before and after `rebuild()`;
   any mismatch raises `ContractError` (CONVENTIONS.md §4 -- a broken invariant, crash early)
   instead of printing success over a partial rebuild (the OG-28 lesson).
3. **IDF post-check.** `VectorIndex.has_idf_modifier()` must be `True` after `rebuild()`, or this
   raises `ContractError` too -- confirms the whole point of the operation actually landed.

Idempotent: if the collection already has the modifier, this reports that and exits 0 without
running `rebuild()` at all (including on a fresh collection -- `VectorIndex.__init__` already
creates one with the modifier baked in via `_ensure_collection`, so nothing further is needed).

`--dry-run` reports the current point count and whether the modifier is already set, and takes no
snapshot and calls no `rebuild()` -- read-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Protocol

from app.snapshot import default_backup_root, run_snapshot
from contracts.config import Config
from contracts.errors import ContractError
from rag.config import load_config

# Same host/port/dim wiring app/snapshot.py's real composition root uses -- named vendor-neutrally
# here since this module must never say the vector store's vendor name (CONVENTIONS.md §1). `_DIM`
# only matters if the target collection doesn't exist yet; the reindex target always already does.
_DEFAULT_VECTOR_STORE_HOST = "localhost"
_DEFAULT_VECTOR_STORE_PORT = 6333
_VECTOR_STORE_DIM = 2560


class ReindexableVectorStore(Protocol):
    """Everything this module needs from the vector store adapter -- injected (CONVENTIONS.md
    §2) so tests can hand in a fake, real `main()` hands in a real `rag.vector_index.VectorIndex`.
    """

    def point_count(self) -> int: ...
    def has_idf_modifier(self) -> bool: ...
    def rebuild(self) -> None: ...
    def create_and_download_snapshot(self, dest_path: str) -> None: ...  # for run_snapshot


def _verify_snapshot_present(backup_root: Path, collection: str) -> Path:
    """`--i-have-a-snapshot` still gets checked, never just trusted: a completed (non-`.partial`)
    `app.snapshot` backup of exactly `collection`, with a non-empty vector-store snapshot file on
    disk, must actually exist under `backup_root`. Returns the newest one that qualifies; raises
    `ContractError` (a broken safety precondition -- crash early) otherwise.
    """
    if backup_root.is_dir():
        completed = sorted(
            p
            for p in backup_root.iterdir()
            if p.is_dir() and p.name.startswith("snapshot-") and not p.name.endswith(".partial")
        )
        for snapshot_dir in reversed(completed):
            manifest_path = snapshot_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            vs = json.loads(manifest_path.read_text()).get("vector_store", {})
            if vs.get("collection") != collection:
                continue
            snapshot_file = snapshot_dir / vs.get("dest", "")
            if snapshot_file.is_file() and snapshot_file.stat().st_size > 0:
                return snapshot_dir

    raise ContractError(
        f"reindex_idf: --i-have-a-snapshot given, but no completed snapshot of collection "
        f"{collection!r} with a non-empty vector-store snapshot file was found under "
        f"{backup_root} -- run `python -m app.snapshot` first, or drop --i-have-a-snapshot to "
        f"let this command take one for you."
    )


def run_reindex_idf(
    cfg: Config,
    vector_index: ReindexableVectorStore,
    *,
    collection: str,
    backup_root: Path,
    dry_run: bool,
    have_snapshot: bool,
    keep: int,
    now=None,
) -> str:
    """The full OG-27 flow -- see module docstring for the three safety layers. Returns a
    human-readable summary on success (including the idempotent no-op and dry-run cases); raises
    `ContractError` on any safety-gate failure (never prints a false success).
    """
    point_count_before = vector_index.point_count()

    if vector_index.has_idf_modifier():
        return (
            f"reindex_idf: collection {collection!r} already has the IDF modifier "
            f"({point_count_before:,} points) -- nothing to do."
        )

    if dry_run:
        snapshot_plan = "verify an existing snapshot" if have_snapshot else "take a fresh snapshot"
        return (
            f"reindex_idf: DRY RUN -- collection {collection!r} has {point_count_before:,} "
            f"points, IDF modifier is NOT set. Would {snapshot_plan}, then rebuild() to add it. "
            f"No changes made."
        )

    if have_snapshot:
        snapshot_dir = _verify_snapshot_present(backup_root, collection)
        safety_note = f"verified existing snapshot at {snapshot_dir}"
    else:
        snapshot_cfg = cfg.model_copy(update={"collection": collection})
        snapshot_dir = run_snapshot(
            snapshot_cfg, backup_root, keep=keep, vector_index=vector_index, now=now
        )
        safety_note = f"took a fresh snapshot at {snapshot_dir}"

    vector_index.rebuild()

    point_count_after = vector_index.point_count()
    if point_count_after != point_count_before:
        raise ContractError(
            f"reindex_idf: POINT COUNT MISMATCH after rebuilding {collection!r} -- "
            f"before={point_count_before:,} after={point_count_after:,}. Data may have been "
            f"lost. Restore from {snapshot_dir} immediately; do not retry blindly."
        )

    if not vector_index.has_idf_modifier():
        raise ContractError(
            f"reindex_idf: rebuilt {collection!r} ({point_count_after:,} points preserved) but "
            f"the IDF modifier is still NOT set afterward -- something is wrong with "
            f"_ensure_collection/_sparse_vector_params. Investigate before retrying; a snapshot "
            f"is at {snapshot_dir}."
        )

    return (
        f"reindex_idf: rebuilt collection {collection!r} -- {point_count_before:,} points "
        f"preserved, IDF modifier now set. Safety: {safety_note}."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection", required=True,
        help="vector-store collection to add the IDF sparse modifier to (e.g. 'papers')",
    )
    parser.add_argument(
        "--config", default="config.yaml", help="config.yaml to read db_path/blob_dir from"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report current point count / IDF status; take no snapshot, run no rebuild",
    )
    parser.add_argument(
        "--i-have-a-snapshot", action="store_true",
        help="skip taking a new snapshot -- still verifies a completed one for this collection "
        "already exists on disk before rebuilding",
    )
    parser.add_argument(
        "--backup-root", default=None,
        help="dir snapshots live under (default: same as `python -m app.snapshot`'s default)",
    )
    parser.add_argument(
        "--keep", type=int, default=7,
        help="when taking a new snapshot, prune all but the newest N completed snapshots",
    )
    parser.add_argument("--vector-store-host", default=_DEFAULT_VECTOR_STORE_HOST)
    parser.add_argument("--vector-store-port", type=int, default=_DEFAULT_VECTOR_STORE_PORT)
    return parser.parse_args()


def main() -> None:
    from rag.vector_index import VectorIndex  # only imported here (CONVENTIONS.md §1)

    args = _parse_args()
    cfg = load_config(args.config)
    backup_root = Path(args.backup_root) if args.backup_root else default_backup_root(cfg)

    vector_index = VectorIndex(
        args.vector_store_host, args.vector_store_port, args.collection, _VECTOR_STORE_DIM
    )

    result = run_reindex_idf(
        cfg,
        vector_index,
        collection=args.collection,
        backup_root=backup_root,
        dry_run=args.dry_run,
        have_snapshot=args.i_have_a_snapshot,
        keep=args.keep,
    )
    print(result)


if __name__ == "__main__":
    main()
