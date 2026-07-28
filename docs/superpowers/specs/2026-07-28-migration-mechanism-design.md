# T-DOC81 — a migration mechanism that can reach a populated database

*2026-07-28. Design decision for the ticket's three candidate fixes. Foundation change:
`migrations/` and `rag/document_store.py` are CODEOWNERS-frozen.*

## The gap, restated

`migrate()` applies every numbered `.sql` file on every call with unguarded DDL, so it can only
succeed against a brand-new database — and that is deliberate, documented, and pinned by
`migrations/test_migrate.py::test_migrate_on_already_migrated_db_fails_loudly_not_silently`.
`DocumentStore.__init__` only calls it when the DB file is absent. Between them there is **no
supported path for an additive migration to reach a populated database**. 0004 never ran against
production; every ingest crashed on `papers has no column named doc_type` until the two `ALTER`s
were applied by hand.

Every existing test starts from a fresh `tmp_path`, where 0001→0004 in order works perfectly. The
bug is invisible to any test that starts empty.

## Decision: (a) + (c), with bounded auto-adoption

The ticket offers (a) `schema_version` tracking, (b) a separate `migrate --upgrade` operator
command, (c) detect-and-refuse. (c) is complementary by the ticket's own reasoning.

**Rejecting (b) as the primary fix.** It leaves the operator responsible for knowing *when* to run
an upgrade. The incident being fixed is precisely that nobody knew a migration needed applying —
a mechanism that still requires that knowledge does not close the gap, it relocates it. It also
contradicts the standing preference established for T-DOC89: correct by default, loud only when it
genuinely cannot proceed.

**Taking (a).** A `schema_version` table makes `migrate()` idempotent, which in turn makes it safe
to call unconditionally from `DocumentStore.__init__`. That is what permanently closes the gap: a
database behind the `migrations/` directory catches up the next time anything opens it, with no
operator action and no knowledge required.

### The adoption problem, and why it is bounded

Production already has 0001-0004 applied and no `schema_version` table. A naive idempotent
`migrate()` would find nothing recorded and try to re-apply 0001, failing exactly as today.

Adoption is resolvable exactly because each existing migration left a distinct, cheap artifact:

| migration | probe |
|---|---|
| `0001_init` | table `papers` exists |
| `0002_ingest_checkpoint` | table `ingest_checkpoint` exists |
| `0003_quarantine_diagnostics` | table `quarantine_diagnostics` exists |
| `0004_doc_type_and_chapter_titles` | column `doc_type` on `papers` |

**This probe table is historical and never grows.** It exists only to classify databases created
before `schema_version` did. Every migration from 0005 onward is recorded at the moment it is
applied, so it needs no probe, ever. That is what makes this approach cheap rather than a
per-migration maintenance tax — the objection that would otherwise sink it.

### Behaviour

`migrate(db_path)`:

1. `CREATE TABLE IF NOT EXISTS schema_version (filename TEXT PRIMARY KEY, applied_at TEXT NOT NULL)`.
   The one legitimate `IF NOT EXISTS` in this codebase: it is the tracking mechanism itself, which
   by definition cannot be tracked.
2. If `schema_version` is empty **and** the database already has application tables, adopt: run
   each probe and record every migration whose artifact is present.
3. Apply every numbered file not recorded, in order, recording each immediately after it succeeds.
4. A brand-new database takes the same path: nothing recorded, no tables to adopt, so all files
   apply and all are recorded. One code path, not two.

`DocumentStore.__init__` calls `migrate(db_path)` **unconditionally**, dropping the
`if not db_file.exists()` guard.

**(c), complementary:** after migrating, assert the columns `DocumentStore` actually writes are
present, and raise a clear, actionable error naming the missing column and the migration that adds
it. This converts a confusing mid-ingest `OperationalError` on the first `put()` into a startup
failure that says what to do — worth keeping even though (a) should prevent it from ever firing.

## The contract this reverses

`migrate()`'s docstring says re-running "is expected to fail loudly ... rather than silently doing
nothing", and `test_migrate_on_already_migrated_db_fails_loudly_not_silently` pins it.

That contract is being **deliberately reversed**, and the reversal is the point: "re-running is a
bug" was the assumption that made the gap structural. The test must be rewritten to assert
idempotency, and the docstring updated to say re-running is now the supported, expected path. The
old intent — never silently skip work that was actually needed — survives in a better form: the
`schema_version` table records exactly what was applied and when, so "did this migration run?" is
answerable rather than inferred.

Check `DATA-CONTRACTS.md` for the same claim and update it in the same change.

## Testing

The ticket is explicit that a fresh-`tmp_path` test cannot exercise this path. Required:

- **Populated DB at an older version** — apply 0001-0003, insert rows into `papers`/`chunks`, then
  run `migrate()` with 0004 present. Assert 0004 applied, `schema_version` records all four, **and
  the inserted rows survived**. This is the test that would have caught the incident.
- **Adoption of production's exact shape** — a DB with 0001-0004 applied and no `schema_version`
  (0004 applied by hand, as production was). Assert `migrate()` adopts all four, applies nothing,
  does not raise, and leaves data intact.
- **Idempotency** — `migrate()` twice in a row on the same DB is a no-op the second time.
- **Fresh DB** — all files apply, all recorded. Pins that the new path did not break the old one.
- **Partial adoption** — a DB with 0001-0002 only (no `quarantine_diagnostics`, no `doc_type`):
  adopt two, apply two.
- **Rewritten** `test_migrate_on_already_migrated_db_fails_loudly_not_silently` → asserts
  idempotency, with a comment recording that T-DOC81 deliberately reversed it and why.

## Risks

- **Reversing a documented, tested contract** is the main one. It is intentional and argued above,
  but a reviewer must see it flagged rather than discover it.
- **Adoption probes are a judgement about history.** If a database exists whose schema does not
  match any probe pattern — half-applied, hand-edited — adoption will mis-classify it. Mitigation:
  probes test for the artifact each migration creates, which is the most direct evidence available;
  and (c) catches a mis-classification at startup rather than mid-ingest.
- **Production is WAL and live.** The first run against it will adopt. That is a write to a real
  database — back up first, exactly as the 0004 hand-application did
  (`backups/papers-pre-0004-20260726T054148Z.db` is the precedent).
- **`migrations/` and `rag/document_store.py` are foundation-frozen** — needs the
  `foundation-change` label.

## Out of scope

- Down-migrations / rollback. Nothing in this system has ever needed one; YAGNI.
- Checksumming migration files to detect edits after application. Real in principle, no evidence of
  the failure here, and it would add a maintenance burden the adoption table deliberately avoids.
- The hierarchy migration that motivated the priority (book `parent`/`level` columns) — that is the
  first *consumer* of this fix, not part of it.
