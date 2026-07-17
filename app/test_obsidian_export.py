"""Tests for `app.obsidian_export` (T-V1-OBSIDIAN) -- offline, no GPU/network, no production data.

Most tests drive `export_vault` against a small in-memory fake (`_FakePaperSource`, the seam this
module defines via `PaperSource`) since rendering only ever calls `iter_papers()`. One test wires
a real `rag.document_store.DocumentStore` over a `tmp_path` DB to prove the module still works
against the actual store interface, not just the fake's shape.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from app.obsidian_export import (
    INDEX_FILENAME,
    export_vault,
    note_filename,
    render_index,
    render_note,
    slugify,
)
from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block

BBOX = (0.0, 0.0, 100.0, 200.0)


def make_block(paper_id: str, **o) -> Block:
    f = dict(
        block_id=f"{paper_id}:b0", paper_id=paper_id, text="Some prose.", type="prose",
        page=0, bbox=BBOX, section_path="1. Introduction", index=0,
    )
    f.update(o)
    return Block(**f)


def make_paper_ref(paper_id: str, **o) -> PaperRef:
    f = dict(
        paper_id=paper_id, version="v1", title=f"Title for {paper_id}",
        abstract="We propose...", authors=["A. Author", "B. Author"],
        categories=["cs.LG", "stat.ME"], published=date(2026, 6, 1), updated=date(2026, 6, 1),
        pdf_url=f"https://arxiv.org/pdf/{paper_id}v1",
    )
    f.update(o)
    return PaperRef(**f)


def make_paper_record(paper_id: str, **o) -> PaperRecord:
    blocks = o.pop("blocks", [make_block(paper_id)])
    ref = o.pop("ref", None) or make_paper_ref(paper_id, **o.pop("ref_overrides", {}))
    f = dict(
        ref=ref,
        parsed=ParsedDoc(
            paper_id=paper_id, markdown="# doc", blocks=blocks, figures=[], tables=[],
            references=[], parser_id="test-parser",
        ),
        chunks=[],
        summary_text=f"Summary of {paper_id}.",
        summary_id=f"{paper_id}:summary",
        relevance_score=0.5,
    )
    f.update(o)
    return PaperRecord(**f)


class _FakePaperSource:
    def __init__(self, records: list[PaperRecord]):
        self._records = records

    def iter_papers(self):
        return iter(self._records)


# --------------------------------------------------------------------------------------------
# slugify / filenames
# --------------------------------------------------------------------------------------------


def test_slugify_is_stable_across_calls():
    assert slugify("2506.01234") == slugify("2506.01234")


def test_slugify_replaces_unsafe_characters():
    assert slugify("2506.01234/v1 final") == "2506.01234_v1_final"


def test_note_filename_keyed_on_paper_id_not_title():
    assert note_filename("2506.01234") == "2506.01234.md"


# --------------------------------------------------------------------------------------------
# render_note
# --------------------------------------------------------------------------------------------


def test_render_note_frontmatter_and_summary_body():
    record = make_paper_record("2506.01234")
    text = render_note(record)

    assert text.startswith("---\n")
    fm_text = text.split("---\n")[1]
    frontmatter = yaml.safe_load(fm_text)
    assert frontmatter["title"] == "Title for 2506.01234"
    assert frontmatter["arxiv_id"] == "2506.01234v1"
    assert frontmatter["authors"] == ["A. Author", "B. Author"]
    assert frontmatter["categories"] == ["cs.LG", "stat.ME"]
    assert frontmatter["published"] == "2026-06-01"
    assert "paper" in frontmatter["tags"]
    assert "cs-LG" in frontmatter["tags"]  # dot sanitized for Obsidian tag syntax

    assert "Summary of 2506.01234." in text
    assert "[[A. Author]]" in text  # author wikilink
    assert "https://arxiv.org/pdf/2506.01234v1" in text
    assert "https://arxiv.org/abs/2506.01234" in text
    assert "## Claims" in text
    assert "claim-layer V1 ticket" in text  # claims explicitly deferred, not fabricated


def test_render_note_section_structure_deduped_in_order():
    paper_id = "2506.01234"
    blocks = [
        make_block(paper_id, block_id=f"{paper_id}:b0", index=0, section_path="1. Intro"),
        make_block(paper_id, block_id=f"{paper_id}:b1", index=1, section_path="2. Method"),
        make_block(paper_id, block_id=f"{paper_id}:b2", index=2, section_path="1. Intro"),
    ]
    record = make_paper_record(paper_id, blocks=blocks)
    text = render_note(record)

    sections_block = text.split("## Sections")[1].split("## Claims")[0]
    assert sections_block.count("1. Intro") == 1
    assert sections_block.index("1. Intro") < sections_block.index("2. Method")


# --------------------------------------------------------------------------------------------
# render_index
# --------------------------------------------------------------------------------------------


def test_render_index_lists_every_paper_freshest_first():
    older = make_paper_record("2501.00001", ref_overrides={"published": date(2026, 1, 1)})
    newer = make_paper_record("2506.00002", ref_overrides={"published": date(2026, 6, 1)})
    text = render_index([older, newer])

    assert "[[2501.00001|" in text
    assert "[[2506.00002|" in text
    assert text.index("2506.00002") < text.index("2501.00001")  # freshest first


# --------------------------------------------------------------------------------------------
# export_vault -- writes notes + index, --limit, idempotent regeneration
# --------------------------------------------------------------------------------------------


def test_export_vault_writes_a_note_per_paper_plus_index(tmp_path):
    records = [make_paper_record(f"250{i}.0000{i}") for i in range(3)]
    result = export_vault(_FakePaperSource(records), tmp_path)

    assert result.n_notes == 3
    md_files = sorted(p.name for p in tmp_path.glob("*.md"))
    expected = sorted([note_filename(r.ref.paper_id) for r in records] + [INDEX_FILENAME])
    assert md_files == expected
    index_text = (tmp_path / INDEX_FILENAME).read_text()
    for r in records:
        assert r.ref.title in index_text


def test_export_vault_limit_caps_notes_written(tmp_path):
    records = [make_paper_record(f"250{i}.0000{i}") for i in range(5)]
    result = export_vault(_FakePaperSource(records), tmp_path, limit=2)

    assert result.n_notes == 2
    assert len(list(tmp_path.glob("*.md"))) == 2 + 1  # +1 for _index.md


def test_export_vault_regeneration_overwrites_not_duplicates(tmp_path):
    paper_id = "2506.01234"
    v1 = make_paper_record(paper_id, ref_overrides={"title": "Old Title"})
    export_vault(_FakePaperSource([v1]), tmp_path)

    v2 = make_paper_record(paper_id, ref_overrides={"title": "New Title"})
    result = export_vault(_FakePaperSource([v2]), tmp_path)

    assert result.n_notes == 1
    assert len(list(tmp_path.glob("*.md"))) == 1 + 1  # note + index, no leftover from v1
    note_text = (tmp_path / note_filename(paper_id)).read_text()
    assert "New Title" in note_text
    assert "Old Title" not in note_text


def test_export_vault_leaves_other_vault_files_untouched(tmp_path):
    (tmp_path / "my-own-notes.md").write_text("hands off")
    export_vault(_FakePaperSource([make_paper_record("2506.01234")]), tmp_path)

    assert (tmp_path / "my-own-notes.md").read_text() == "hands off"


# --------------------------------------------------------------------------------------------
# real DocumentStore wiring (proves the module works against the real interface, not just the fake)
# --------------------------------------------------------------------------------------------


def test_export_vault_against_real_document_store(tmp_path):
    from rag.document_store import DocumentStore

    store = DocumentStore(
        db_path=str(tmp_path / "store.db"), blob_dir=str(tmp_path / "blobs")
    )
    store.put(make_paper_record("2506.01111"))
    store.put(make_paper_record("2506.02222"))

    out_dir = tmp_path / "vault"
    result = export_vault(store, out_dir)

    assert result.n_notes == 2
    assert (out_dir / "2506.01111.md").exists()
    assert (out_dir / "2506.02222.md").exists()
    assert (out_dir / INDEX_FILENAME).exists()
