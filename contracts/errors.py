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
"""


class TransientError(Exception):
    """Temporary failure — retry with bounded backoff, then quarantine if retries are
    exhausted."""


class PermanentError(Exception):
    """This paper is unusable — quarantine it and continue the run. Never kills the run."""


class ContractError(Exception):
    """A broken invariant — a bug. Crash early; do not default around it."""
