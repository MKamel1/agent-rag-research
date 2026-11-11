"""`python -m app.resparse` -- CQ-2: recompute SPARSE vectors only (no re-embedding, no GPU).

`VectorIndex.resparse()` re-derives every point's sparse (keyword) vector from `payload["text"]`
with the CURRENT `rag.vector_index._sparse_vector` and writes only that named vector; dense vectors
and payloads are never read or sent. Idempotent and resumable (points already up to date are not
rewritten, so re-running after an interruption only does the remainder).

DEPLOYMENT HAZARD -- read before shipping CQ-1 (ligature repair) anywhere. `_sparse_vector` now
repairs ligature-broken tokens ("efect" -> "effect") UNCONDITIONALLY, on both the index side
(`upsert`) and the query side (`hybrid_search`). A collection built before CQ-1 and not yet
resparsed therefore serves REPAIRED queries against UNREPAIRED stored sparse vectors. Precisely:
  * a query token that is spelled correctly ("effect") matches exactly what it matched before
    (chunks that contain "effect"); chunks holding the damaged "efect" never matched it, before or
    after -- no regression, just no gain until resparsed;
  * a query token that is itself a damaged spelling ("efect", e.g. text pasted from a damaged PDF)
    used to match chunks indexed under "efect"; it is now repaired to "effect" and no longer
    matches them. THIS is the only regression, and it is limited to queries that contain a key of
    `rag/ligature_map.json` (227 entries). The 263 questions in the 2026-11-10 ground-truth sets
    contain none, so an eval run will NOT reveal it;
  * The vector store's IDF is computed from stored vectors, so the repaired query term's
    document frequency is under-counted (it lacks the "efect" chunks) until the resparse -- a
    mild over-weighting.
Conclusion: the code is safe to deploy ahead of the resparse for ordinary (correctly spelled)
queries, but the keyword arm gets no benefit until the resparse runs (~35% of main-corpus chunks
change), and damaged-spelling queries regress in the interim. Prefer shipping them together:
resparse the clone, A/B it, swap, and only then point traffic at the CQ-1 code. See
docs/eval-reports/2026-11-10-cq2-index-maintenance.md for the sequencing.

Safety (mirrors `app/reindex_idf.py`):
  * `--collection` is REQUIRED; there is no default, so a wrong-corpus run cannot happen by
    omission, and a collection that does not exist is an error (it is never auto-created).
  * Default is a dry run. Writing needs `--apply` AND one of: `--i-have-a-snapshot` (a completed
    `app.snapshot` backup of exactly this collection must exist on disk -- checked, not trusted) or
    `--target-is-clone --clone-of SOURCE` (the target must hold the same number of points as
    SOURCE; a sanity check that it was made by `VectorIndex.clone_points_into`, not a proof).
  * Point count is read before and after and must match; after writing, a random sample is
    re-verified and must show zero stale points.
  * `--verify-sample N` is read-only: N random points are recomputed and compared with what is
    stored -- how an operator measures how stale a collection is.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.reindex_idf import _verify_snapshot_present
from app.snapshot import default_backup_root
from contracts.errors import ContractError
from rag.config import load_config

_DEFAULT_VECTOR_STORE_HOST = "localhost"
_DEFAULT_VECTOR_STORE_PORT = 6333
_VECTOR_STORE_DIM = 2560  # only used if the collection must be created, which these CLIs forbid
_POST_APPLY_SAMPLE = 200


class ResparseableVectorStore(Protocol):
    """What this module needs from `rag.vector_index.VectorIndex`; tests inject a fake."""

    def point_count(self) -> int: ...
    def resparse(self, collection=None, *, batch_size=..., dry_run=False): ...
    def sample_sparse_staleness(self, n, collection=None): ...


def check_apply_guard(
    *,
    tool: str,
    collection: str,
    backup_root: Callable[[], Path],
    have_snapshot: bool,
    target_is_clone: bool,
    clone_of: str | None,
    count_of: Callable[[str], int],
) -> str:
    """The shared write guard (also used by `app.set_payload_fields`). Returns a one-line note on
    what made the write safe; raises `ContractError` if nothing did. `backup_root` is a callable
    so a clone-guarded run never needs to load a config."""
    if not (have_snapshot or target_is_clone):
        raise ContractError(
            f"{tool}: refusing to write to {collection!r} -- pass --i-have-a-snapshot (after "
            f"`python -m app.snapshot`) or --target-is-clone --clone-of SOURCE (a clone made by "
            f"VectorIndex.clone_points_into)."
        )
    notes = []
    if target_is_clone:
        if not clone_of or clone_of == collection:
            raise ContractError(
                f"{tool}: --target-is-clone needs --clone-of SOURCE naming a DIFFERENT collection"
            )
        source_n, target_n = count_of(clone_of), count_of(collection)
        if source_n != target_n:
            raise ContractError(
                f"{tool}: {collection!r} has {target_n:,} points but its claimed source "
                f"{clone_of!r} has {source_n:,} -- not a complete clone, refusing to write."
            )
        notes.append(f"{collection!r} matches {clone_of!r} point-for-count ({target_n:,})")
    if have_snapshot:
        try:
            snapshot_dir = _verify_snapshot_present(backup_root(), collection)
        except ContractError as e:
            raise ContractError(f"{tool}: --i-have-a-snapshot not satisfied: {e}") from e
        notes.append(f"verified snapshot {snapshot_dir}")
    return "; ".join(notes)


def _format_report(report) -> str:
    skipped = ", ".join(f"{k}={v:,}" for k, v in sorted(report.skipped.items())) or "none"
    verb = "would change" if report.dry_run else "changed"
    return (
        f"scanned={report.scanned:,} {verb}={report.changed:,} unchanged={report.unchanged:,} "
        f"(of changed, no stored sparse vector: {report.stored_sparse_missing:,}) "
        f"skipped: {skipped}\n  by kind scanned={report.scanned_by_kind} "
        f"{verb}={report.changed_by_kind}"
    )


def run_resparse(
    vector_index: ResparseableVectorStore,
    *,
    collection: str,
    apply: bool,
    backup_root: Callable[[], Path],
    have_snapshot: bool,
    target_is_clone: bool,
    clone_of: str | None,
    count_of: Callable[[str], int],
    verify_sample: int | None = None,
    batch_size: int | None = None,
) -> str:
    """Returns the text to print. Raises `ContractError` on a refused guard / broken invariant."""
    if verify_sample is not None:
        if apply:
            raise ContractError("resparse: --verify-sample is read-only; drop --apply")
        report = vector_index.sample_sparse_staleness(verify_sample)
        pct = 100.0 * report.changed / report.scanned if report.scanned else 0.0
        return (
            f"resparse: VERIFY SAMPLE of {collection!r}: {report.changed:,}/{report.scanned:,} "
            f"({pct:.1f}%) sampled points have a stale sparse vector ({_format_report(report)})"
        )

    kwargs = {} if batch_size is None else {"batch_size": batch_size}
    count_before = vector_index.point_count()
    if not apply:
        report = vector_index.resparse(dry_run=True, **kwargs)
        return (
            f"resparse: DRY RUN on {collection!r} ({count_before:,} points) -- nothing written; "
            f"pass --apply to write.\n  {_format_report(report)}"
        )

    guard_note = check_apply_guard(
        tool="resparse",
        collection=collection,
        backup_root=backup_root,
        have_snapshot=have_snapshot,
        target_is_clone=target_is_clone,
        clone_of=clone_of,
        count_of=count_of,
    )
    report = vector_index.resparse(dry_run=False, **kwargs)
    count_after = vector_index.point_count()
    if count_after != count_before:
        raise ContractError(
            f"resparse: POINT COUNT MISMATCH on {collection!r}: before={count_before:,} "
            f"after={count_after:,}. Restore from the snapshot/clone; do not retry blindly."
        )
    check = vector_index.sample_sparse_staleness(_POST_APPLY_SAMPLE)
    if check.changed:
        raise ContractError(
            f"resparse: wrote {collection!r} but {check.changed}/{check.scanned} sampled points "
            f"are still stale -- investigate before swapping/serving."
        )
    return (
        f"resparse: APPLIED to {collection!r} ({count_after:,} points preserved). Guard: "
        f"{guard_note}. Post-check: 0/{check.scanned} sampled points stale.\n  "
        f"{_format_report(report)}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--collection", required=True, help="collection to operate on (no default)")
    parser.add_argument("--config", default="config.yaml", help="config.yaml (backup-root lookup)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="(default) report only")
    mode.add_argument("--apply", action="store_true", help="write the recomputed sparse vectors")
    parser.add_argument("--i-have-a-snapshot", action="store_true",
                        help="a completed app.snapshot backup of this collection exists (verified)")
    parser.add_argument("--target-is-clone", action="store_true",
                        help="the collection is a clone_points_into copy of --clone-of")
    parser.add_argument("--clone-of", default=None, help="source collection of the clone")
    parser.add_argument("--verify-sample", type=int, default=None, metavar="N",
                        help="read-only: compare N random points' stored sparse vectors")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--backup-root", default=None)
    parser.add_argument("--vector-store-host", default=_DEFAULT_VECTOR_STORE_HOST)
    parser.add_argument("--vector-store-port", type=int, default=_DEFAULT_VECTOR_STORE_PORT)
    return parser.parse_args()


def open_index(args: argparse.Namespace, collection: str):
    from rag.vector_index import VectorIndex  # only imported here (CONVENTIONS.md §1)

    return VectorIndex(
        args.vector_store_host, args.vector_store_port, collection, _VECTOR_STORE_DIM,
        create_if_missing=False,
    )


def backup_root_resolver(args: argparse.Namespace) -> Callable[[], Path]:
    def resolve() -> Path:
        if args.backup_root:
            return Path(args.backup_root)
        return default_backup_root(load_config(args.config))

    return resolve


def main() -> None:
    args = _parse_args()
    index = open_index(args, args.collection)
    print(
        run_resparse(
            index,
            collection=args.collection,
            apply=args.apply,
            backup_root=backup_root_resolver(args),
            have_snapshot=args.i_have_a_snapshot,
            target_is_clone=args.target_is_clone,
            clone_of=args.clone_of,
            count_of=lambda name: open_index(args, name).point_count(),
            verify_sample=args.verify_sample,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    main()
