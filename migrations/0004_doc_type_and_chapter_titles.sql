-- 0004_doc_type_and_chapter_titles.sql — T-DOC80: drop-in folder + book ingestion.
--
-- Additive only (0001_init.sql's own header: schema changes are additive, never a rewrite of an
-- already-applied file): two ALTER TABLE ADD COLUMNs, no new tables.
--
-- papers.doc_type: "paper" (default, every pre-existing row and every arXiv harvest) or "book" —
-- mirrors contracts/harvester.py's PaperRef.doc_type (Literal["paper", "book"] = "paper"). NOT
-- NULL with a default so every pre-existing row is a paper, unchanged.
--
-- summaries.title: chapter heading for `{paper_id}:summary:ch{n}` rows (contracts/document_store.py
-- ChapterSummary.title); NULL for the existing whole-document `{paper_id}:summary` rows, which have
-- no title. Nullable (not NOT NULL) for exactly that reason -- unlike doc_type, there is no sensible
-- default title for a summary row.

ALTER TABLE papers ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'paper';
ALTER TABLE summaries ADD COLUMN title TEXT;
