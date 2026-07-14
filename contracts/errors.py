"""The three-class error taxonomy (CONVENTIONS.md §4). Every module in this system raises one of
these — never an ad-hoc exception, never a bare `except:`.

    TransientError — temporary (network timeout, 503, rate limit) -> retry with backoff, then
                      quarantine
    PermanentError — this paper is bad (unparseable PDF, corrupt e-print) -> quarantine and
                      continue
    ContractError  — a broken invariant / a bug (a block with no bbox, a wrong-dim vector) ->
                      crash early

Note: these are for *pipeline* errors raised by module code while doing pipeline work. They are
distinct from the `pydantic.ValidationError` a `contracts/` model raises at construction time
when handed a wrong-shaped value (DATA-CONTRACTS.md's "runtime-validating form" requirement,
T-F1) — that validation failure is a bug too (a caller built a contract object wrong), and
callers that want it folded into the pipeline taxonomy should catch `pydantic.ValidationError`
and re-raise as `ContractError` themselves; `contracts/` does not do that wrapping on their
behalf, so this module has no pydantic dependency.

**Optional `.diagnostics` convention (T-DOC17):** any raise site MAY, opportunistically, set a
`.diagnostics` dict attribute on the exception instance before raising (plain `setattr`, e.g.
`err = PermanentError(msg); err.diagnostics = {"pdf_size_bytes": len(raw)}; raise err`) to attach
best-effort forensic context. `rag/ingest_state_sqlite.py`'s `SqliteIngestState.quarantine()`
opportunistically captures it (`migrations/0003_quarantine_diagnostics.sql`'s
`diagnostics_json`) when present. This is NOT part of the three-class taxonomy contract above — a
missing `.diagnostics` is always fine and defaults to NULL; it is not a typed attribute/kwarg on
these classes themselves.
"""


class TransientError(Exception):
    """Temporary failure — retry with bounded backoff, then quarantine if retries are
    exhausted."""


class PermanentError(Exception):
    """This paper is unusable — quarantine it and continue the run. Never kills the run."""


class ContractError(Exception):
    """A broken invariant — a bug. Crash early; do not default around it."""
