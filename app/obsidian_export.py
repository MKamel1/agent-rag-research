"""`python -m app.obsidian_export` -- T-V1-OBSIDIAN: a generated Obsidian note-per-paper view
over the SQLite store.

PRD §11 Q5: notes are a GENERATED VIEW, SQLite is the source of truth. Regenerating overwrites
the note for a paper (filename keyed on `paper_id`, which never changes); there is no
sync-back-from-Obsidian path and none should ever be added here -- edit the paper in the store,
then re-run this module.

Claims are deliberately NOT rendered here (V1's claim-layer ticket owns that) -- each note has a
placeholder "## Claims" section instead, so a later regeneration slots claims in without changing
the note's shape.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import yaml

from contracts.config import Config
from contracts.document_store import PaperRecord
from rag.config import load_config

INDEX_FILENAME = "_index.md"
_STABLE_TAG = "paper"


class PaperSource(Protocol):
    """The one method this module needs from a paper store -- injected (CONVENTIONS.md §2) so
    tests can hand in a small in-memory fake instead of standing up a real `DocumentStore`/DB."""

    def iter_papers(self) -> Iterable[PaperRecord]: ...


# --- filenames -------------------------------------------------------------------------------


def slugify(paper_id: str) -> str:
    """Filename stem for `paper_id`. Keyed on `paper_id` alone (not title): `paper_id` is the
    store's own primary key and never changes across regenerations, so the filename it produces
    is stable for free. A title-based slug would drift if a paper's title were ever corrected
    on re-`put()`, orphaning the old file instead of overwriting it -- exactly what "idempotent"
    rules out. arXiv ids are already filesystem-safe (digits/dot, optionally a trailing
    `vN`); the substitution below is a safety net for any other id shape, not the common case.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


def note_filename(paper_id: str) -> str:
    return f"{slugify(paper_id)}.md"


# --- one note ----------------------------------------------------------------------------------


def _tag(category: str) -> str:
    """Obsidian tags can't contain `.` -- categories like `cs.LG` become `cs-LG`."""
    return re.sub(r"[^A-Za-z0-9_/-]", "-", category)


def _section_structure(record: PaperRecord) -> list[str]:
    """Unique `section_path`s from the paper's blocks, in reading order -- cheap because it's
    already on every `Block` (`section_path`, parser-assigned, DATA-CONTRACTS.md), no re-parsing.
    """
    seen: list[str] = []
    for block in record.parsed.blocks:
        if block.section_path and block.section_path not in seen:
            seen.append(block.section_path)
    return seen


def render_note(record: PaperRecord) -> str:
    ref = record.ref
    frontmatter = {
        "title": ref.title,
        "arxiv_id": f"{ref.paper_id}{ref.version}",
        "authors": list(ref.authors),
        "categories": list(ref.categories),
        "published": ref.published.isoformat(),
        "tags": [_STABLE_TAG] + [_tag(c) for c in ref.categories],
    }
    lines = ["---", yaml.safe_dump(frontmatter, sort_keys=False).rstrip(), "---", ""]
    lines.append(f"# {ref.title}")
    lines.append("")
    authors_links = ", ".join(f"[[{a}]]" for a in ref.authors)
    lines.append(f"**Authors:** {authors_links}" if authors_links else "**Authors:** (none listed)")
    lines.append(f"**Published:** {ref.published.isoformat()}")
    lines.append(
        f"**Source:** [PDF]({ref.pdf_url}) · [arXiv](https://arxiv.org/abs/{ref.paper_id})"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(record.summary_text or "_(no summary stored)_")
    lines.append("")

    sections = _section_structure(record)
    if sections:
        lines.append("## Sections")
        lines.append("")
        lines.extend(f"- {s}" for s in sections)
        lines.append("")

    lines.append("## Claims")
    lines.append("")
    lines.append("_Not yet generated -- deferred to the claim-layer V1 ticket._")
    lines.append("")
    return "\n".join(lines)


# --- index / MOC note --------------------------------------------------------------------------


def render_index(records: list[PaperRecord]) -> str:
    ordered = sorted(records, key=lambda r: (r.ref.published, r.ref.paper_id), reverse=True)
    lines = ["# Papers Index", "", f"{len(ordered)} papers.", ""]
    for r in ordered:
        stem = slugify(r.ref.paper_id)
        lines.append(f"- [[{stem}|{r.ref.title}]] ({r.ref.published.isoformat()})")
    lines.append("")
    return "\n".join(lines)


# --- orchestration -------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportResult:
    out_dir: Path
    n_notes: int


def export_vault(store: PaperSource, out_dir: Path, *, limit: int | None = None) -> ExportResult:
    """Renders one note per paper plus `_index.md` into `out_dir`. Idempotent: each paper's
    filename is deterministic (`slugify(paper_id)`), so re-running overwrites the same files
    rather than accumulating duplicates -- and never touches any *other* file already in
    `out_dir` (a real Obsidian vault has other notes in it).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[PaperRecord] = []
    for record in store.iter_papers():
        if limit is not None and len(records) >= limit:
            break
        records.append(record)

    for record in records:
        (out_dir / note_filename(record.ref.paper_id)).write_text(
            render_note(record), encoding="utf-8"
        )
    (out_dir / INDEX_FILENAME).write_text(render_index(records), encoding="utf-8")

    return ExportResult(out_dir=out_dir, n_notes=len(records))


def default_vault_dir(cfg: Config) -> Path:
    """No `--out-dir` given: default to an `obsidian_vault/` dir next to the configured
    `db_path` -- same rationale as `app/snapshot.py::default_backup_root` (production's `Config`
    points at the real data dir, not the repo, so this rides along instead of hardcoding /tmp).
    """
    return Path(cfg.db_path).resolve().parent / "obsidian_vault"


def print_summary(result: ExportResult) -> None:
    print(f"obsidian_export: wrote {result.n_notes} notes + {INDEX_FILENAME} to {result.out_dir}")


# --- composition root -------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="config.yaml", help="config.yaml to read db_path/blob_dir from"
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Obsidian vault dir to write notes into (default: obsidian_vault/ next to db_path)",
    )
    parser.add_argument("--limit", type=int, default=None, help="export at most N papers")
    return parser.parse_args()


def main() -> None:
    from rag.document_store import DocumentStore

    args = _parse_args()
    cfg = load_config(args.config)
    out_dir = Path(args.out_dir) if args.out_dir else default_vault_dir(cfg)

    store = DocumentStore(cfg.db_path, cfg.blob_dir)
    result = export_vault(store, out_dir, limit=args.limit)
    print_summary(result)


if __name__ == "__main__":
    main()
