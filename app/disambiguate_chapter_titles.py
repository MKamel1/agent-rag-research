"""`python -m app.disambiguate_chapter_titles` -- CQ-20: apply `rag.book_summarizer.
disambiguate_titles` to an ALREADY-BUILT corpus, no re-summarize and no re-embed.

A chapter title lives in two places: `summaries.title` (SQLite -- what `retrieve_papers()` returns
as `chapter`) and the `section_path` payload key of the chapter's `kind="summary"` point. This
rewrites both. The embedded/sparse text of a chapter point is `ChapterSummary.text` only (never the
title), so those vectors stay exactly right. The one place a title is inside embedded text is the
whole-book summary's "Contents:" list (and the overview it was written from): its vector keeps
the old duplicate labels -- slightly stale against the new labels, deliberately not re-embedded.

Dry run by default: prints every (paper_id, chapter index, old title, new title), checks each
point exists in the collection, writes nothing (SQLite opened `mode=ro`). `--apply` needs the
shared snapshot/clone guard (`app.resparse.check_apply_guard`), writes the payload first and SQLite
second (so a crash is fixed by simply re-running), and checks that matched points == renames and
that a re-plan is empty. Idempotent: an already-disambiguated corpus plans zero renames.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

from app.resparse import backup_root_resolver, check_apply_guard, open_index
from contracts.errors import ContractError
from rag.book_summarizer import disambiguate_titles

_CHAPTER_ID = re.compile(r"^(?P<paper_id>.+):summary:ch(?P<n>\d+)$")


class Rename(NamedTuple):
    paper_id: str
    index: int
    summary_id: str
    old: str
    new: str


class PayloadStore(Protocol):
    def paper_point_ids(self, collection=None) -> dict[str, list[str]]: ...
    def set_payload(self, fields, *, point_ids=None, batch_size=..., **kw): ...


def plan_renames(con: sqlite3.Connection) -> list[Rename]:
    """Every chapter unit whose title `disambiguate_titles` would change, in (paper, index) order."""
    books: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for summary_id, title in con.execute(
        "SELECT summary_id, title FROM summaries WHERE summary_id LIKE '%:summary:ch%'"
    ):
        m = _CHAPTER_ID.match(summary_id)
        if m:
            books[m["paper_id"]].append((int(m["n"]), summary_id, title or ""))
    renames = []
    for paper_id, units in sorted(books.items()):
        units.sort()
        new_titles = disambiguate_titles([t for _, _, t in units])
        renames += [
            Rename(paper_id, n, sid, old, new)
            for (n, sid, old), new in zip(units, new_titles, strict=True)
            if new != old
        ]
    return renames


def format_listing(renames: list[Rename]) -> str:
    return "paper_id\tchapter_index\told_title\tnew_title\n" + "".join(
        f"{r.paper_id}\t{r.index}\t{r.old}\t{r.new}\n" for r in renames
    )


def run_disambiguation(
    db_path: Path,
    store: PayloadStore,
    *,
    collection: str,
    apply: bool,
    backup_root: Callable[[], Path],
    have_snapshot: bool,
    target_is_clone: bool,
    clone_of: str | None,
    count_of: Callable[[str], int],
) -> tuple[str, list[Rename]]:
    """Returns (text to print, the planned renames)."""
    ro = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        renames = plan_renames(ro)
    finally:
        ro.close()
    existing = {pid for ids in store.paper_point_ids().values() for pid in ids}
    missing = [r.summary_id for r in renames if r.summary_id not in existing]
    books = len({r.paper_id for r in renames})
    head = f"{len(renames)} chapter title(s) in {books} book(s) to rename in {db_path} / {collection!r}"
    if missing:
        raise ContractError(f"disambiguate_chapter_titles: {len(missing)} unit(s) have no vector "
                            f"point in {collection!r}, e.g. {missing[:3]} -- corpus/collection mismatch")
    if not apply:
        return f"DRY RUN -- nothing written; {head}. All points present.", renames
    if not renames:
        return f"nothing to do; {head}.", renames

    guard_note = check_apply_guard(
        tool="disambiguate_chapter_titles", collection=collection, backup_root=backup_root,
        have_snapshot=have_snapshot, target_is_clone=target_is_clone, clone_of=clone_of,
        count_of=count_of,
    )
    # Payload first: retrieval reads SQLite, so a crash between the stores changes nothing a user
    # sees, and re-running redoes both idempotently.
    matched = sum(
        store.set_payload({"section_path": r.new}, point_ids=[r.summary_id]) for r in renames
    )
    if matched != len(renames):
        raise ContractError(f"disambiguate_chapter_titles: matched {matched} points, "
                            f"expected {len(renames)} -- investigate before retrying")
    rw = sqlite3.connect(db_path)
    try:
        with rw:
            changed = sum(
                rw.execute(
                    "UPDATE summaries SET title = ? WHERE summary_id = ? AND title = ?",
                    (r.new, r.summary_id, r.old),
                ).rowcount
                for r in renames
            )
        if changed != len(renames):
            raise ContractError(f"disambiguate_chapter_titles: updated {changed} SQLite rows, "
                                f"expected {len(renames)}")
        leftover = plan_renames(rw)
    finally:
        rw.close()
    if leftover:
        raise ContractError(f"disambiguate_chapter_titles: {len(leftover)} renames still planned")
    return f"APPLIED {head}; payload + SQLite agree, re-plan is empty. Guard: {guard_note}.", renames


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--db", required=True, help="papers.db of the corpus")
    p.add_argument("--collection", required=True)
    p.add_argument("--listing-out", help="also write the rename listing (TSV) to this file")
    p.add_argument("--config", default="config.yaml", help="config.yaml (backup-root lookup)")
    p.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    p.add_argument("--i-have-a-snapshot", action="store_true")
    p.add_argument("--target-is-clone", action="store_true")
    p.add_argument("--clone-of", default=None)
    p.add_argument("--backup-root", default=None)
    p.add_argument("--vector-store-host", default="localhost")
    p.add_argument("--vector-store-port", type=int, default=6333)
    return p.parse_args(argv)


def main() -> None:
    args = _parse_args()
    text, renames = run_disambiguation(
        Path(args.db), open_index(args, args.collection), collection=args.collection,
        apply=args.apply, backup_root=backup_root_resolver(args),
        have_snapshot=args.i_have_a_snapshot, target_is_clone=args.target_is_clone,
        clone_of=args.clone_of, count_of=lambda name: open_index(args, name).point_count(),
    )
    listing = format_listing(renames)
    if args.listing_out:
        Path(args.listing_out).write_text(listing)
    print(listing + text)


if __name__ == "__main__":
    main()
