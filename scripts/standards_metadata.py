"""CQ-5 (stub): validate the reviewed standards-metadata table and emit category-tag artefacts.

Intended behaviour (implemented in the next commit):
  * validate  -- check docs/eval-reports/data/2026-11-10-standards-metadata/standards_metadata.json
                 against closed vocabularies and the standards papers.db (opened mode=ro): every
                 paper id exists, every superseded_by/supersedes target exists and is reciprocal,
                 every evidence chunk exists and contains its quote. Exits non-zero on any error.
  * emit      -- write (a) a `paper_id -> {"categories": [...]}` mapping for
                 `python -m app.set_payload_fields` and (b) a reviewable SQL + TSV of the matching
                 `papers.categories_json` values. Nothing is executed against any database.
"""
