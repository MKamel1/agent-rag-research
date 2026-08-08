-- 0005_author_orgs.sql — T-ORG1: wire author-org tagging into the ingest pipeline.
--
-- Additive only (0001_init.sql's own header: schema changes are additive, never a rewrite of an
-- already-applied file): two ALTER TABLE ADD COLUMNs, no new tables.
--
-- papers.raw_affiliations: JSON list of the extracted candidate affiliation strings -- the
-- evidence (rag/author_org_tagger.py::extract_affiliations_rule_based's output).
-- papers.author_orgs: JSON list of {"name": ..., "method": "email_domain"|"keyword"} objects
-- (contracts/author_orgs.py's AuthorOrgMatch) -- the matched orgs AND which signal fired.
--
-- Both nullable, unlike papers.doc_type (migration 0004, NOT NULL DEFAULT 'paper'): every
-- pre-existing row genuinely has no value here -- the tagger has never run against it -- and
-- unlike doc_type there is no sensible default. "[]" would silently assert "checked, found
-- nothing" for a row that was never checked at all, which is a different fact than "checked,
-- found nothing."
--
-- `method` is stored per match, not a bare "is this org X" boolean, because the underlying signal
-- is measured, not exact: rag/author_org_tagger.py's keyword matching scores precision 0.569 /
-- recall 0.763 over 1,741 done papers against 114 enumerated Waymo-authored ids (T-ORG2, commit
-- d3e79c3). At 0.569 precision, close to half of keyword-derived tags are wrong -- so a consumer
-- needs to see which signal fired (email_domain: precision 0.700 but recall only 0.123, since 81%
-- of extracted affiliation regions carry no email at all) to decide whether to trust a given match
-- for its own use case.

ALTER TABLE papers ADD COLUMN raw_affiliations TEXT;
ALTER TABLE papers ADD COLUMN author_orgs TEXT;
