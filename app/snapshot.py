"""`python -m app.snapshot` -- T-DOC57: one-command, consistent backup of all V0 durable state.

Why this exists: a power-down this session destroyed an in-progress ingest run, and a multi-day
30k-paper ingest is coming next. Nothing in this repo took a *consistent* point-in-time backup of
the three stores that together make up "the corpus" -- SQLite (papers/blocks/chunks/summaries),
the blob directory (raw markdown text), and the vector store (retrieval index) -- so a crash mid-run
could leave them silently out of sync with each other even where each individually survived.

Three artifacts, one snapshot directory:

1. **SQLite** (`Config.db_path`) -- `VACUUM INTO` against a **read-only** connection to the source,
   not a raw file copy: transactionally consistent even against a live writer (same precedent as
   `LESSONS-LEARNED.md`'s manual `.backup` snapshots before T-DOC23/T-DOC31/T-DOC35's production
   sweeps -- this module mechanizes that same "always back up with a real online-consistent
   snapshot first" habit instead of leaving it to be remembered by hand each time).
2. **Blobs** (`Config.blob_dir`) -- a recursive copy.
3. **Vector store** (`Config.collection`) --
   `rag.vector_index.VectorIndex.create_and_download_snapshot` does both the vendor-side create and
   the out-of-container download; this module never names or imports the vector-store vendor itself
   (CONVENTIONS.md §1 -- `rag/vector_index.py` is the only module allowed to).

**Atomicity:** everything is written under `<backup-root>/snapshot-<UTC timestamp>.partial/`; the
directory is renamed to its final (`.partial`-less) name only after all three artifacts and the
manifest have been written successfully. A crash, OOM, or power-kill partway through leaves the
`.partial` directory behind for inspection instead of a half-written snapshot that looks complete --
nothing here catches and swallows a mid-run failure, so an uncaught exception (and the interpreter's
normal non-zero exit) is the intended failure signal, not a bug to guard against.

`--keep N` (default 7) prunes all but the newest N completed (non-`.partial`) snapshot directories
under `--backup-root` after a successful run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from contracts.config import Config
from rag.config import load_config

# Same host/port/dim wiring app/assembly.py's real composition roots use for the vector store --
# named vendor-neutrally here since this module must never say the vector store's vendor name
# (CONVENTIONS.md §1). `_VECTOR_STORE_DIM` only matters if the target collection doesn't exist yet
# (the vector-store adapter creates a fresh one in that case); a real backup target's collection
# always already exists, so this is a safety-net default, not a lever anyone should need to tune.
_DEFAULT_VECTOR_STORE_HOST = "localhost"
_DEFAULT_VECTOR_STORE_PORT = 6333
_VECTOR_STORE_DIM = 2560

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class SnapshotableVectorStore(Protocol):
    """The one method this module needs from the vector store adapter -- injected (CONVENTIONS.md
    §2) so tests can hand in a fake without a live service, real `main()` hands in a real
    `rag.vector_index.VectorIndex`."""

    def create_and_download_snapshot(self, dest_path: str) -> None: ...


# --- SQLite --------------------------------------------------------------------------------------


def _table_row_counts(con: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def backup_sqlite(db_path: str, dest_dir: Path) -> dict:
    """`VACUUM INTO` a consistent copy of `db_path` into `dest_dir/papers.db`, opening the source
    **read-only** (a live writer must never be blocked or corrupted by taking a backup). Row counts
    below are read back from the written copy itself -- proof the copy actually opens and holds the
    same data, not just that `VACUUM INTO` returned without raising.
    """
    dest_path = dest_dir / "papers.db"
    source_uri = f"file:{Path(db_path).resolve()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    try:
        source.execute("VACUUM INTO ?", (str(dest_path),))
    finally:
        source.close()

    copy = sqlite3.connect(str(dest_path))
    try:
        row_counts = _table_row_counts(copy)
    finally:
        copy.close()

    return {
        "source": str(Path(db_path).resolve()),
        "dest": dest_path.name,
        "bytes": dest_path.stat().st_size,
        "row_counts": row_counts,
    }


# --- blobs -----------------------------------------------------------------------------------


def backup_blobs(blob_dir: str, dest_dir: Path) -> dict:
    """Recursive copy of the blob directory into `dest_dir/blobs`."""
    dest_path = dest_dir / "blobs"
    shutil.copytree(blob_dir, dest_path)
    files = [f for f in dest_path.rglob("*") if f.is_file()]
    return {
        "source": str(Path(blob_dir).resolve()),
        "dest": dest_path.name,
        "bytes": sum(f.stat().st_size for f in files),
        "file_count": len(files),
    }


# --- vector store ------------------------------------------------------------------------------


def backup_vector_store(
    vector_index: SnapshotableVectorStore, collection: str, dest_dir: Path
) -> dict:
    """Delegates the vendor-specific create+download to `vector_index` (real adapter or, in
    tests, a fake) and reports back on the file it must have written -- if it didn't, `.stat()`
    below raises, which is exactly the fail-loud behavior a missing backup artifact should have.
    """
    dest_path = dest_dir / f"{collection}.snapshot"
    vector_index.create_and_download_snapshot(str(dest_path))
    return {
        "collection": collection,
        "dest": dest_path.name,
        "bytes": dest_path.stat().st_size,
    }


# --- orchestration -----------------------------------------------------------------------------


def run_snapshot(
    cfg: Config,
    backup_root: Path,
    *,
    keep: int,
    vector_index: SnapshotableVectorStore,
    now: datetime | None = None,
) -> Path:
    """Runs all three backups into a `.partial` dir, writes `manifest.json`, and only then renames
    to the final `snapshot-<timestamp>` directory -- see module docstring for the atomicity
    contract. Prunes to the newest `keep` completed snapshots afterward. Returns the final dir.
    """
    ts = (now or datetime.now(timezone.utc)).strftime(_TIMESTAMP_FORMAT)
    backup_root.mkdir(parents=True, exist_ok=True)
    partial_dir = backup_root / f"snapshot-{ts}.partial"
    final_dir = backup_root / f"snapshot-{ts}"
    partial_dir.mkdir(parents=True)

    manifest = {
        "timestamp_utc": ts,
        "sqlite": backup_sqlite(cfg.db_path, partial_dir),
        "blobs": backup_blobs(cfg.blob_dir, partial_dir),
        "vector_store": backup_vector_store(vector_index, cfg.collection, partial_dir),
    }
    (partial_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    partial_dir.rename(final_dir)
    prune_old_snapshots(backup_root, keep=keep)
    return final_dir


def prune_old_snapshots(backup_root: Path, *, keep: int) -> None:
    """Deletes all but the newest `keep` completed snapshot directories under `backup_root`.
    Never touches `.partial` directories (a crashed run's leftovers stay for inspection, per the
    module docstring's atomicity contract -- pruning is not a cleanup mechanism for those).
    Snapshot dir names sort chronologically as plain strings (`snapshot-<UTC timestamp>`), so no
    filesystem-mtime dependency is needed.
    """
    completed = sorted(
        p
        for p in backup_root.iterdir()
        if p.is_dir() and p.name.startswith("snapshot-") and not p.name.endswith(".partial")
    )
    stale = completed[:-keep] if keep > 0 else completed
    for old_dir in stale:
        shutil.rmtree(old_dir)


def default_backup_root(cfg: Config) -> Path:
    """No `--backup-root` given: default to a `backups/` dir next to the configured `db_path`.
    Production's real `Config.db_path` already lives on the big data volume (this repo's `app/`
    entrypoints are run from a directory whose `db_path`/`blob_dir` point at the real data dir, not
    the repo itself -- DATA-CONTRACTS.md's `Config` note), so this rides along automatically
    instead of hardcoding a path that could silently diverge from wherever the real data lives.
    """
    return Path(cfg.db_path).resolve().parent / "backups"


def print_summary(final_dir: Path, manifest: dict) -> None:
    sq = manifest["sqlite"]
    bl = manifest["blobs"]
    vs = manifest["vector_store"]
    print(f"snapshot: wrote {final_dir}")
    print(f"  sqlite:       {sq['dest']:<20} {sq['bytes']:>14,} bytes")
    print(f"                row_counts={sq['row_counts']}")
    print(f"  blobs:        {bl['dest']:<20} {bl['bytes']:>14,} bytes  ({bl['file_count']} files)")
    print(f"  vector store: {vs['dest']:<20} {vs['bytes']:>14,} bytes")
    print(f"                collection={vs['collection']}")


# --- composition root --------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="config.yaml",
        help="config.yaml to read db_path/blob_dir/collection from",
    )
    parser.add_argument(
        "--backup-root", default=None,
        help="dir to write snapshot-<timestamp>/ dirs into (default: backups/ next to db_path)",
    )
    parser.add_argument(
        "--keep", type=int, default=7, help="prune all but the newest N completed snapshots"
    )
    parser.add_argument("--vector-store-host", default=_DEFAULT_VECTOR_STORE_HOST)
    parser.add_argument("--vector-store-port", type=int, default=_DEFAULT_VECTOR_STORE_PORT)
    return parser.parse_args()


def main() -> None:
    from rag.vector_index import VectorIndex  # only imported here -- see module docstring

    args = _parse_args()
    cfg = load_config(args.config)
    backup_root = Path(args.backup_root) if args.backup_root else default_backup_root(cfg)

    vector_index = VectorIndex(
        args.vector_store_host, args.vector_store_port, cfg.collection, _VECTOR_STORE_DIM
    )
    final_dir = run_snapshot(cfg, backup_root, keep=args.keep, vector_index=vector_index)

    manifest = json.loads((final_dir / "manifest.json").read_text())
    print_summary(final_dir, manifest)


if __name__ == "__main__":
    main()
