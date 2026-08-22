-- 0006_figures_tables.sql — RI-18: persist Figure/TableItem artifacts the Parser already extracts
-- on every parse (contracts/parser.py) instead of discarding them at the storage boundary.
--
-- Additive only (0001_init.sql's own header: schema changes are additive, never a rewrite of an
-- already-applied file): two new tables, not ALTERs -- a paper has MANY figures/tables (a child
-- relationship, like blocks/chunks), not one scalar value per paper (unlike doc_type/author_orgs).
--
-- figures.image_path: filesystem path to the extracted PNG (source-of-truth blob,
-- DATA-CONTRACTS.md "M2 Parser output"). figures.vlm_description is nullable and always NULL in
-- V0 (contracts/parser.py's Figure: "filled by the V3 VLM enricher") -- put() never writes a
-- non-NULL value into it.
--
-- tables.markdown: the table rendered as markdown (contracts/parser.py's TableItem).
--
-- Neither table is surfaced in retrieval (chunking/embedding/search) -- persistence only, RI-18
-- scope; indexing figure/table captions into search is a separate, not-yet-made decision.
--
-- No natural stable id exists on either contract type (unlike block_id/chunk_id) -- a plain
-- `INTEGER PRIMARY KEY` (SQLite's ROWID alias, monotonically increasing within one table's
-- lifetime -- no AUTOINCREMENT needed, which would additionally create a bookkeeping
-- `sqlite_sequence` table with no benefit here) surrogate key is enough since nothing resolves an
-- individual figure/table by id (no get_figure/get_table getter; only get() reads the whole list
-- back per paper_id, ordered by this key, which matches ParsedDoc's own list order).

CREATE TABLE figures (
  figure_id       INTEGER PRIMARY KEY,
  paper_id        TEXT NOT NULL REFERENCES papers(paper_id),
  image_path      TEXT NOT NULL,
  caption         TEXT NOT NULL,
  page            INTEGER NOT NULL,
  bbox_json       TEXT NOT NULL,       -- JSON [x0,y0,x1,y1]
  vlm_description TEXT                 -- ALWAYS NULL in V0 (see header above)
);

CREATE TABLE tables (
  table_id     INTEGER PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  markdown     TEXT NOT NULL,
  caption      TEXT NOT NULL,
  page         INTEGER NOT NULL,
  bbox_json    TEXT NOT NULL           -- JSON [x0,y0,x1,y1]
);

CREATE INDEX idx_figures_paper_id ON figures(paper_id);
CREATE INDEX idx_tables_paper_id ON tables(paper_id);
