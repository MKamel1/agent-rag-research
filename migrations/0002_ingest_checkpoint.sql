-- 0002_ingest_checkpoint.sql — durable storage for IngestionOrchestrator checkpoint artifacts.
--
-- Additive only: 0001_init.sql's `ingest_state` table is untouched (its own header comment already
-- says the schema is additive, new tables in a later migration, never a migration of the tables it
-- defines). This fixes the T-A2 (PR #38) foundation-level gap: `ingest_state` has no column for the
-- parsed/chunks/summary_text artifacts a resumed run needs to skip re-invoking Chunker/Summarizer —
-- see `.phase0-data/orchestrator-checkpoint-proposal.md` (Option A) for the full decision record.
--
-- Source of truth: DATA-CONTRACTS.md "SQLite schema" -> "ingest_checkpoint" subsection — this file
-- is a literal transcription of that DDL, not a redesign.

CREATE TABLE ingest_checkpoint (
  paper_id       TEXT PRIMARY KEY REFERENCES ingest_state(paper_id),
  artifacts_json TEXT NOT NULL   -- serialized CheckpointArtifacts (contracts/ingest_state.py)
);
