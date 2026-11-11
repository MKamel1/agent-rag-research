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

**OP-3 (stub, implemented in the following commits):** the manifest gains `quick_check` (SQLite
`PRAGMA quick_check` on the written copy; anything but `ok` fails the snapshot and leaves it
`.partial`) and `sha256` per artifact (SQLite file, every blob file, vector-store file).
`--verify PATH` re-checks an existing snapshot without a config or a vector store -- a
`snapshot-*/` dir (manifest.json), a `MANIFEST.sha256` dir (qdrant file copy) or a single
`papers.db.snapshot-*` file with its `.sha256`. `--sqlite-only` takes a consistent SQLite backup
(stdlib backup API, read-only source) with integrity check, row-count comparison and a `.sha256`
file, with no vector store needed. **OP-6:** a missing `db_path` is refused, never created.

`--keep N` (default 7) prunes all but the newest N completed (non-`.partial`) snapshot directories
under `--backup-root` after a successful run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.db_guard import MissingDatabaseError, require_existing_db
from contracts.config import Config
from rag.config import load_config

logger = logging.getLogger(__name__)

# Same host/port/dim wiring app/assembly.py's real composition roots use for the vector store --
# named vendor-neutrally here since this module must never say the vector store's vendor name
# (CONVENTIONS.md §1). `_VECTOR_STORE_DIM` only matters if the target collection doesn't exist yet
# (the vector-store adapter creates a fresh one in that case); a real backup target's collection
# always already exists, so this is a safety-net default, not a lever anyone should need to tune.
_DEFAULT_VECTOR_STORE_HOST = "localhost"
_DEFAULT_VECTOR_STORE_PORT = 6333
_VECTOR_STORE_DIM = 2560

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# Operator rule (OP-3/OP-6): a snapshot aborts when the backup device has less than this free.
MIN_FREE_GIB = 20.0


class SnapshotIntegrityError(RuntimeError):
    """A produced artifact failed its integrity check; the snapshot stays `.partial`."""


def require_free_space(path: Path, *, min_free_gib: float = MIN_FREE_GIB) -> None:
    free_gib = shutil.disk_usage(path).free / 1024**3
    if free_gib < min_free_gib:
        raise SystemExit(
            f"snapshot: only {free_gib:.1f} GiB free at {path} (abort rule: >= {min_free_gib:g})"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_sha256sum(text: str) -> dict[str, str]:
    """`sha256sum` output (`<hex>  <relpath>` per line) -> {relpath: hex}."""
    out = {}
    for line in text.splitlines():
        if line.strip():
            digest, _, name = line.partition("  ")
            out[name.lstrip("*")] = digest
    return out


def sqlite_pragma_check(path: Path, pragma: str = "integrity_check") -> str:
    """`ok`, or the first problem line SQLite reports. Opens `immutable=1`: a finished backup is
    static, and a plain read-only open of a WAL-mode file would create `-wal`/`-shm` files beside
    it -- verifying a backup must not write into the backup directory."""
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        return con.execute(f"PRAGMA {pragma}").fetchone()[0]
    finally:
        con.close()


def _ro_row_counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        return _table_row_counts(con)
    finally:
        con.close()


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

    check = sqlite_pragma_check(dest_path, "quick_check")
    if check != "ok":
        raise SnapshotIntegrityError(f"quick_check on {dest_path} failed: {check}")

    return {
        "source": str(Path(db_path).resolve()),
        "dest": dest_path.name,
        "bytes": dest_path.stat().st_size,
        "row_counts": _ro_row_counts(dest_path),
        "quick_check": check,
        "sha256": sha256_file(dest_path),
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
        "sha256": {str(f.relative_to(dest_path)): sha256_file(f) for f in sorted(files)},
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
        "sha256": sha256_file(dest_path),
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
    require_existing_db(cfg.db_path)  # before anything is created -- OP-6
    ts = (now or datetime.now(timezone.utc)).strftime(_TIMESTAMP_FORMAT)
    backup_root.mkdir(parents=True, exist_ok=True)
    require_free_space(backup_root)
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


def snapshot_sqlite_only(
    cfg: Config, backup_root: Path, *, now: datetime | None = None
) -> Path:
    """SQLite-only backup that needs no vector store (the operator's 2026-11-10 manual shape):
    `<backup_root>/papers.db.snapshot-<YYYYMMDD>` plus `<same>.sha256` (`sha256sum` format).

    Stdlib backup API from a **read-only** source connection; row counts are read inside one read
    transaction on the source so the comparison with the copy is not racy; `integrity_check` runs
    on the copy. Any failure leaves `<name>.partial` behind and raises -- no `.sha256` is written
    for a bad copy. Refuses to overwrite an existing snapshot of the same day.
    """
    require_existing_db(cfg.db_path)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    backup_root.mkdir(parents=True, exist_ok=True)
    require_free_space(backup_root)
    dest = backup_root / f"papers.db.snapshot-{stamp}"
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; refusing to overwrite a backup")
    partial = dest.with_name(dest.name + ".partial")
    partial.unlink(missing_ok=True)

    source = sqlite3.connect(f"file:{Path(cfg.db_path).resolve()}?mode=ro", uri=True)
    try:
        source.execute("BEGIN")
        source_counts = _table_row_counts(source)
        target = sqlite3.connect(str(partial))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    check = sqlite_pragma_check(partial)
    if check != "ok":
        raise SnapshotIntegrityError(f"integrity_check on {partial} failed: {check}")
    copy_counts = _ro_row_counts(partial)
    if copy_counts != source_counts:
        raise SnapshotIntegrityError(
            f"row counts differ (source {source_counts} vs copy {copy_counts}); is a writer active?"
        )
    digest = sha256_file(partial)
    partial.rename(dest)
    dest.with_name(dest.name + ".sha256").write_text(f"{digest}  {dest.name}\n")
    print(f"snapshot: wrote {dest} ({dest.stat().st_size:,} bytes)")
    print(f"  integrity_check=ok sha256={digest}")
    print(f"  row_counts={copy_counts}")
    return dest


# --- verify ------------------------------------------------------------------------------------


def _check_hashes(base: Path, expected: dict[str, str], problems: list[str]) -> None:
    for rel, digest in expected.items():
        f = base / rel
        if not f.is_file():
            problems.append(f"missing file: {rel}")
        elif sha256_file(f) != digest:
            problems.append(f"sha256 mismatch: {rel}")


def verify_snapshot(path: Path) -> tuple[list[str], list[str]]:
    """Re-check an existing snapshot. Returns (report lines, problems); empty problems == good.

    Read-only; needs no config and no vector store. Three shapes:
    - `snapshot-*/` dir with `manifest.json` (this module's full snapshot),
    - dir with `MANIFEST.sha256` (file copy of the vector-store storage, `sha256sum -c` format),
    - a single SQLite file with a sibling `<name>.sha256` (`--sqlite-only` / the manual backup).
    """
    report: list[str] = []
    problems: list[str] = []
    if path.is_dir() and (path / "manifest.json").is_file():
        manifest = json.loads((path / "manifest.json").read_text())
        sq = manifest["sqlite"]
        db = path / sq["dest"]
        if not db.is_file():
            problems.append(f"missing file: {sq['dest']}")
        else:
            check = sqlite_pragma_check(db)
            report.append(f"sqlite integrity_check: {check}")
            if check != "ok":
                problems.append(f"sqlite integrity_check: {check}")
            if _ro_row_counts(db) != sq["row_counts"]:
                problems.append("sqlite row counts differ from manifest")
            if "sha256" in sq:
                _check_hashes(path, {sq["dest"]: sq["sha256"]}, problems)
        blobs = manifest["blobs"]
        if "sha256" in blobs:
            _check_hashes(path / blobs["dest"], blobs["sha256"], problems)
            report.append(f"blobs: {len(blobs['sha256'])} files hashed")
        vs = manifest["vector_store"]
        if "sha256" in vs:
            _check_hashes(path, {vs["dest"]: vs["sha256"]}, problems)
        if not all("sha256" in manifest[k] for k in ("sqlite", "blobs", "vector_store")):
            report.append("note: manifest predates OP-3 -- some sha256 values were never recorded")
    elif path.is_dir() and (path / "MANIFEST.sha256").is_file():
        expected = parse_sha256sum((path / "MANIFEST.sha256").read_text())
        _check_hashes(path, expected, problems)
        report.append(f"MANIFEST.sha256: {len(expected)} files checked")
    elif path.is_file():
        sidecar = path.with_name(path.name + ".sha256")
        if not sidecar.is_file():
            problems.append(f"no checksum file {sidecar.name} next to {path.name}")
        else:
            expected = parse_sha256sum(sidecar.read_text())
            _check_hashes(path.parent, {path.name: expected.get(path.name, "")}, problems)
        check = sqlite_pragma_check(path)
        report.append(f"sqlite integrity_check: {check}")
        if check != "ok":
            problems.append(f"sqlite integrity_check: {check}")
        report.append(f"row_counts={_ro_row_counts(path)}")
    else:
        problems.append(f"{path} is neither a snapshot dir, a MANIFEST.sha256 dir nor a file")
    return report, problems


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
    print(f"                row_counts={sq['row_counts']} quick_check={sq['quick_check']}")
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
    parser.add_argument(
        "--verify", metavar="PATH", default=None,
        help="re-check an existing backup (snapshot-*/ dir, MANIFEST.sha256 dir, or a SQLite file "
        "with its .sha256): sha256s, integrity_check, row counts. Read-only; no vector store.",
    )
    parser.add_argument(
        "--sqlite-only", action="store_true",
        help="back up only SQLite (backup API, integrity check, row-count comparison, .sha256) "
        "into --backup-root; needs no vector store",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args()
    if args.verify:
        report, problems = verify_snapshot(Path(args.verify))
        print("\n".join(report))
        if problems:
            print(f"verify: FAILED -- {len(problems)} problem(s):")
            print("\n".join(f"  - {p}" for p in problems))
            sys.exit(1)
        print(f"verify: OK -- {args.verify}")
        return

    cfg = load_config(args.config)
    # T-DOC89 §4: report what was resolved, same pattern as app/delete_docs.py -- an operator
    # standing in the wrong directory should see where this process actually pointed, not guess.
    logger.info(
        "snapshot: resolved db_path=%s blob_dir=%s collection=%s",
        cfg.db_path, cfg.blob_dir, cfg.collection,
    )
    try:
        require_existing_db(cfg.db_path)
    except MissingDatabaseError as error:
        sys.exit(f"snapshot: {error}")
    backup_root = Path(args.backup_root) if args.backup_root else default_backup_root(cfg)
    if args.sqlite_only:
        snapshot_sqlite_only(cfg, backup_root)
        return

    from rag.vector_index import VectorIndex  # only imported here -- see module docstring

    vector_index = VectorIndex(
        args.vector_store_host, args.vector_store_port, cfg.collection, _VECTOR_STORE_DIM
    )
    final_dir = run_snapshot(cfg, backup_root, keep=args.keep, vector_index=vector_index)

    manifest = json.loads((final_dir / "manifest.json").read_text())
    print_summary(final_dir, manifest)


if __name__ == "__main__":
    main()
