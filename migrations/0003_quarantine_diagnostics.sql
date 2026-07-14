-- 0003_quarantine_diagnostics.sql — structured parse/pipeline-failure diagnostics, additive to the
-- `quarantine` dead-letter table.
--
-- Additive only: 0001_init.sql's `quarantine` table is untouched (its own header comment already
-- says the schema is additive, new tables in a later migration, never a migration of the tables it
-- defines). Today `quarantine.error` is just `str(exception)` -- no structured category, no
-- queryable diagnostics. This is a new table, not an `ALTER TABLE` on `quarantine`, for two
-- reasons: (a) `quarantine`'s DDL is a frozen, parity-tested (see
-- `test_0001_init_matches_data_contracts_schema` in migrations/test_migrate.py), CODEOWNERS-gated
-- source-of-truth shape -- a new table is a smaller disturbance to that frozen contract than
-- editing it; (b) `error_type TEXT NOT NULL` cannot be added to the existing `quarantine` table via
-- `ALTER TABLE ADD COLUMN` -- SQLite forbids adding a NOT NULL column without a default to a table
-- that already has rows, and the live `quarantine` table already has rows. A new table lets
-- `error_type` stay cleanly `NOT NULL` for all future rows.
--
-- Source of truth: DATA-CONTRACTS.md "SQLite schema" -> "quarantine_diagnostics" subsection -- this
-- file is a literal transcription of that DDL, not a redesign.

CREATE TABLE quarantine_diagnostics (
  paper_id         TEXT PRIMARY KEY REFERENCES quarantine(paper_id),
  error_type       TEXT NOT NULL,   -- type(error).__name__, e.g. "PermanentError"
  diagnostics_json TEXT             -- optional best-effort context, e.g. {"pdf_size_bytes": ...}
);
