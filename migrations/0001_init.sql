-- 0001_init.sql — V0 SQLite schema.
--
-- Source of truth: DATA-CONTRACTS.md "SQLite schema" section — this file is a literal transcription
-- of that DDL, not a redesign. If this ever needs to diverge from DATA-CONTRACTS.md, that is a
-- frozen-contract change requiring human sign-off (CONVENTIONS.md §0.2) — fix DATA-CONTRACTS.md first,
-- then this file, never the other way around.
--
-- V1+ tables (claims, claim_relations, citation_edges) are intentionally NOT created here — see
-- DATA-CONTRACTS.md's "DO NOT CREATE IN V0" note. The schema is additive (new tables in a later
-- migration), never a migration of the tables below.

CREATE TABLE papers (
  paper_id     TEXT PRIMARY KEY,
  version      TEXT NOT NULL,
  title        TEXT NOT NULL,
  abstract     TEXT NOT NULL,
  authors_json TEXT NOT NULL,       -- JSON array
  categories_json TEXT NOT NULL,
  published    TEXT NOT NULL,        -- ISO date
  updated      TEXT NOT NULL,
  pdf_path     TEXT NOT NULL,
  markdown_path TEXT NOT NULL,
  relevance_score REAL              -- written by IngestionOrchestrator via put(PaperRecord), post-summarize;
                                      -- NULL only if a row predates the paper reaching that stage. Unused
                                      -- by V0 filtering (relevance_filter="off"), but must not be silently
                                      -- left NULL after "done" — see TEST-STRATEGY Orchestrator test.
);

CREATE TABLE blocks (
  block_id     TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  idx          INTEGER NOT NULL,
  type         TEXT NOT NULL,
  text         TEXT NOT NULL,
  page         INTEGER NOT NULL,
  bbox_json    TEXT NOT NULL,        -- JSON [x0,y0,x1,y1]
  section_path TEXT NOT NULL
);

CREATE TABLE chunks (
  chunk_id     TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  text         TEXT NOT NULL,
  anchor_json  TEXT NOT NULL,        -- serialized Anchor
  section_path TEXT NOT NULL,
  parent_id    TEXT,
  contextual_header TEXT
);

-- DocumentStore reconstruction (get/get_paper) filters blocks and chunks by paper_id; without these
-- indexes each lookup full-scans these ~1-5M-row tables on the always-on query server at corpus_cap ~15k.
CREATE INDEX idx_blocks_paper_id ON blocks(paper_id);
CREATE INDEX idx_chunks_paper_id ON chunks(paper_id);

CREATE TABLE summaries (
  summary_id   TEXT PRIMARY KEY,
  paper_id     TEXT NOT NULL REFERENCES papers(paper_id),
  text         TEXT NOT NULL
);

-- The idempotency spine (CONVENTIONS "operational invariants"):
CREATE TABLE ingest_state (
  paper_id     TEXT PRIMARY KEY,
  stage        TEXT NOT NULL,        -- harvested|parsed|chunked|summarized|embedded|stored|done
                                       -- `stored` = DocumentStore.put() succeeded (source-of-truth
                                       -- written). VectorIndex.upsert() runs AFTER `stored` is recorded
                                       -- and BEFORE `done` is recorded — it is a separate step, not part
                                       -- of `put()`. A paper stuck at `stored` on resume has NOT
                                       -- necessarily reached the vector index; resume must re-run
                                       -- upsert() for it (idempotent, safe to repeat) before advancing to
                                       -- `done` (ARCHITECTURE "Operational invariants" §1).
  updated_at   TEXT NOT NULL
);

CREATE TABLE quarantine (            -- dead-letter: one bad paper must not kill the run
  paper_id     TEXT PRIMARY KEY,
  stage        TEXT NOT NULL,
  error        TEXT NOT NULL,
  ts           TEXT NOT NULL
);

-- V1+ (DO NOT CREATE IN V0): claims(claim_id, paper_id, method, dataset, metric, value,
--   conditions_json, anchor_json, ...), claim_relations(...), citation_edges(...). Named here only so
--   Owner D leaves room; the schema is additive (new tables), never a migration of the above.
