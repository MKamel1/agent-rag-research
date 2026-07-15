"""M5 DocumentStore (T-D1) — SQLite + blob filesystem, the source of truth (ARCHITECTURE.md §M5,
DATA-CONTRACTS.md §M5, migrations/0001_init.sql).

`sqlite3` is imported here and in `migrations/` only (CONVENTIONS.md §1) — those are the two
seams legitimately allowed to touch it directly (applying the schema vs. querying it).

Round-trip note (T-D1 open question, resolved): the V0 schema is a deliberate *projection* of the
richer contract objects — no columns for `ParsedDoc.parser_id`/`figures`/`tables`/`references`,
and `PaperRef.latex_url` has no column either. `get()` fills those back in with empty/placeholder
values; callers must not rely on them surviving a round-trip. `papers.pdf_path` has no PDF-bytes
source in `PaperRecord` to point at (the Harvester downloads the PDF separately, outside this
ticket's scope) — `PaperRef.pdf_url` is stored there instead of a fabricated local path, which
also happens to round-trip `pdf_url` exactly. `papers.markdown_path` DOES have a real source
(`ParsedDoc.markdown`) — that text is written to `blob_dir` as a real blob and read back on
`get()`, matching `PaperRecord`'s own docstring ("blobs ... are written to the filesystem").
"""

import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from contracts.chunker import Chunk
from contracts.document_store import PaperRecord
from contracts.errors import ContractError
from contracts.harvester import PaperRef
from contracts.parser import ParsedDoc
from contracts.provenance import Anchor, Block
from migrations.migrate import migrate


class DocumentStore:
    """`DocumentStore(db_path, blob_dir)` — a SQLite file plus a filesystem root for blobs.

    `db_path` is migrated (schema applied) automatically the first time it's opened; an
    already-migrated path is just connected to (re-running the schema DDL against it is a bug,
    per `migrations/migrate.py`'s own contract, not this module's to paper over).
    """

    def __init__(self, db_path: str, blob_dir: str):
        self._blob_dir = Path(blob_dir)
        self._blob_dir.mkdir(parents=True, exist_ok=True)

        db_file = Path(db_path)
        if not db_file.exists():
            db_file.parent.mkdir(parents=True, exist_ok=True)
            migrate(db_path)

        self._con = sqlite3.connect(db_path)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL;")

    # ----------------------------------------------------------------------------------------
    # put — atomic upsert by paper_id (idempotent, reflects changed content on re-put)
    # ----------------------------------------------------------------------------------------

    def put(self, record: PaperRecord) -> None:
        """Atomic: either the whole paper (papers/blocks/chunks/summaries rows) is written, or
        none of it. Re-putting an existing `paper_id` replaces its blocks/chunks/summary with the
        new content (delete-then-insert), never leaves stale rows from the old content behind.

        Relies on `sqlite3`'s own transaction handling: the first DML statement below opens an
        implicit transaction; the `with self._con:` block commits it on success or rolls it back
        (and re-raises) on any exception — no manual BEGIN/COMMIT/ROLLBACK bookkeeping needed.

        The blob write has to honor the same all-or-nothing rule even though it lives outside
        the DB transaction: since `markdown_path` is deterministic (`{paper_id}.md`), writing the
        new content straight to that path would overwrite the prior good blob before the DB
        transaction below is known to succeed. A rolled-back re-put would then leave `get()`
        returning old DB rows paired with the NEW (should-have-been-discarded) markdown text —
        a torn read. So the new content is written to a temp file first and only swapped into
        place (`os.replace`, atomic on the same filesystem) after the transaction commits; on any
        failure the temp file is discarded and the prior blob is untouched.
        """
        ref = record.ref
        paper_id = ref.paper_id
        markdown_path = self._blob_dir / f"{paper_id}.md"
        tmp_path = self._blob_dir / f"{paper_id}.md.tmp"
        tmp_path.write_text(record.parsed.markdown, encoding="utf-8")

        try:
            with self._con:
                self._con.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
                self._con.execute("DELETE FROM blocks WHERE paper_id = ?", (paper_id,))
                self._con.execute("DELETE FROM summaries WHERE paper_id = ?", (paper_id,))
                self._con.execute(
                    """
                    INSERT INTO papers
                        (paper_id, version, title, abstract, authors_json, categories_json,
                         published, updated, pdf_path, markdown_path, relevance_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id) DO UPDATE SET
                        version=excluded.version, title=excluded.title, abstract=excluded.abstract,
                        authors_json=excluded.authors_json, categories_json=excluded.categories_json,
                        published=excluded.published, updated=excluded.updated,
                        pdf_path=excluded.pdf_path, markdown_path=excluded.markdown_path,
                        relevance_score=excluded.relevance_score
                    """,
                    (
                        paper_id,
                        ref.version,
                        ref.title,
                        ref.abstract,
                        json.dumps(ref.authors),
                        json.dumps(ref.categories),
                        ref.published.isoformat(),
                        ref.updated.isoformat(),
                        ref.pdf_url,  # see module docstring: no local PDF-blob path to store instead
                        str(markdown_path),
                        record.relevance_score,
                    ),
                )
                for block in record.parsed.blocks:
                    self._con.execute(
                        """
                        INSERT INTO blocks
                            (block_id, paper_id, idx, type, text, page, bbox_json, section_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            block.block_id,
                            block.paper_id,
                            block.index,
                            block.type,
                            block.text,
                            block.page,
                            json.dumps(list(block.bbox)),
                            block.section_path,
                        ),
                    )
                for chunk in record.chunks:
                    self._con.execute(
                        """
                        INSERT INTO chunks
                            (chunk_id, paper_id, text, anchor_json, section_path, parent_id,
                             contextual_header)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.chunk_id,
                            chunk.paper_id,
                            chunk.text,
                            chunk.anchor.model_dump_json(),
                            chunk.section_path,
                            chunk.parent_id,
                            chunk.contextual_header,
                        ),
                    )
                self._con.execute(
                    "INSERT INTO summaries (summary_id, paper_id, text) VALUES (?, ?, ?)",
                    (record.summary_id, paper_id, record.summary_text),
                )
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        os.replace(tmp_path, markdown_path)

    # ----------------------------------------------------------------------------------------
    # delete — cascade removal by paper_id (T-DOC23)
    # ----------------------------------------------------------------------------------------

    def delete(self, paper_id: str) -> None:
        """Removes `paper_id`'s rows from `chunks`/`blocks`/`summaries`/`papers` in one
        transaction (same `with self._con:` atomicity as `put()`), plus a best-effort blob
        removal. Deleting an unknown/already-gone `paper_id` is a safe no-op, not an error.

        The three non-`papers` deletes run unconditionally -- NOT gated on a `papers` row
        existing first. This is the one deliberate departure from mirroring `put()`: it's what
        lets this method clean up a real orphan (chunks/blocks with no matching `papers` row,
        the exact shape of the T-DOC23 bug -- an earlier cleanup pass ran a raw `DELETE FROM
        papers` with no cascade, since SQLite doesn't enforce the declared foreign keys anywhere
        in this codebase), not just support a normal future single-paper deletion.
        """
        with self._con:
            self._con.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
            self._con.execute("DELETE FROM blocks WHERE paper_id = ?", (paper_id,))
            self._con.execute("DELETE FROM summaries WHERE paper_id = ?", (paper_id,))
            self._con.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
        # Best-effort: a missing blob isn't a failure here (unlike the read path's
        # ContractError) -- deleting something already-gone is fine, not an error.
        (self._blob_dir / f"{paper_id}.md").unlink(missing_ok=True)

    # ----------------------------------------------------------------------------------------
    # reads
    # ----------------------------------------------------------------------------------------

    def get(self, paper_id: str) -> PaperRecord | None:
        row = self._con.execute(
            "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            return None

        ref = PaperRef(
            paper_id=row["paper_id"],
            version=row["version"],
            title=row["title"],
            abstract=row["abstract"],
            authors=json.loads(row["authors_json"]),
            categories=json.loads(row["categories_json"]),
            published=date.fromisoformat(row["published"]),
            updated=date.fromisoformat(row["updated"]),
            pdf_url=row["pdf_path"],
            # latex_url has no column (schema projection gap) — always None on read.
        )
        parsed = ParsedDoc(
            paper_id=paper_id,
            markdown=self._read_markdown_blob(row["markdown_path"]),
            blocks=self.get_blocks(paper_id),
            figures=[],  # no schema table (schema projection gap)
            tables=[],  # no schema table (schema projection gap)
            references=[],  # no schema table (schema projection gap)
            parser_id="",  # no column (schema projection gap)
        )
        chunks = [
            self._row_to_chunk(r)
            for r in self._con.execute(
                "SELECT * FROM chunks WHERE paper_id = ?", (paper_id,)
            ).fetchall()
        ]
        summary_row = self._con.execute(
            "SELECT summary_id, text FROM summaries WHERE paper_id = ?", (paper_id,)
        ).fetchone()

        return PaperRecord(
            ref=ref,
            parsed=parsed,
            chunks=chunks,
            summary_text=summary_row["text"] if summary_row else "",
            summary_id=summary_row["summary_id"] if summary_row else f"{paper_id}:summary",
            relevance_score=row["relevance_score"],
        )

    @staticmethod
    def _read_markdown_blob(markdown_path: str) -> str:
        """A missing/unreadable blob means the store's own papers-row -> blob-file invariant is
        broken (put() always writes it first) — a bug, not a normal "not found" case, so it's a
        ContractError rather than a raw FileNotFoundError leaking out of this module."""
        try:
            return Path(markdown_path).read_text(encoding="utf-8")
        except OSError as e:
            raise ContractError(f"unreadable markdown blob: {markdown_path!r} ({e})") from e

    def get_blocks(self, paper_id: str) -> list[Block]:
        rows = self._con.execute(
            "SELECT * FROM blocks WHERE paper_id = ? ORDER BY idx", (paper_id,)
        ).fetchall()
        return [self._row_to_block(r) for r in rows]

    def get_block(self, block_id: str) -> Block:
        row = self._con.execute(
            "SELECT * FROM blocks WHERE block_id = ?", (block_id,)
        ).fetchone()
        if row is None:
            raise ContractError(f"unknown block_id: {block_id!r}")
        return self._row_to_block(row)

    def get_chunk(self, chunk_id: str) -> Chunk:
        row = self._con.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            raise ContractError(f"unknown chunk_id: {chunk_id!r}")
        return self._row_to_chunk(row)

    def get_summary(self, summary_id: str) -> str:
        row = self._con.execute(
            "SELECT text FROM summaries WHERE summary_id = ?", (summary_id,)
        ).fetchone()
        if row is None:
            raise ContractError(f"unknown summary_id: {summary_id!r}")
        return row["text"]

    def get_span(self, anchor: Anchor) -> str:
        """Resolves to the FULL text of `anchor.block_id` — deliberately NOT `anchor.snippet`."""
        return self.get_block(anchor.block_id).text

    def iter_papers(self) -> Iterator[PaperRecord]:
        rows = self._con.execute("SELECT paper_id FROM papers").fetchall()
        for row in rows:
            record = self.get(row["paper_id"])
            assert record is not None  # just SELECTed it; a concurrent delete is out of V0 scope
            yield record

    # ----------------------------------------------------------------------------------------
    # row -> contract-object helpers
    # ----------------------------------------------------------------------------------------

    @staticmethod
    def _row_to_block(row: sqlite3.Row) -> Block:
        return Block(
            block_id=row["block_id"],
            paper_id=row["paper_id"],
            text=row["text"],
            type=row["type"],
            page=row["page"],
            bbox=tuple(json.loads(row["bbox_json"])),
            section_path=row["section_path"],
            index=row["idx"],
        )

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"],
            paper_id=row["paper_id"],
            text=row["text"],
            anchor=Anchor(**json.loads(row["anchor_json"])),
            section_path=row["section_path"],
            parent_id=row["parent_id"],
            contextual_header=row["contextual_header"],
        )
