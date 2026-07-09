"""Shared pydantic base for every frozen shape in `contracts/`.

DATA-CONTRACTS.md shows these shapes as `@dataclass(frozen=True)` / `TypedDict`, but
WORK-BREAKDOWN.md's T-F1 explicitly prefers "a runtime-validating form (e.g. pydantic models or
attrs with validators) over plain dataclasses — a shape mismatch should raise loudly at
construction, not pass silently because Python didn't check it." This module is that one
decision, made once, so every shape in this package gets the same validation behaviour instead
of each file reinventing it (designing-for-change: DRY).

Config choices, and why:
- `frozen=True`   — matches the source dataclasses' `frozen=True`; a contract object is a value,
  not something a downstream module mutates after construction.
- `strict=True`   — pydantic's default (non-strict) mode *coerces* input (e.g. the int `1` into
  the str `"1"`, or a `list` into a `tuple`). That coercion is exactly the silent pass-through
  T-F1 is asking us to close off. Strict mode makes a wrong-typed field raise
  `pydantic.ValidationError` at construction instead.
- `extra="forbid"` — an unexpected field is far more likely a caller's typo/drift than an
  intentional new field (new fields go through the T-F7 foundation-change protocol, not a silent
  kwarg) — so it should fail loudly too, same rationale as strict typing.
- `validate_default=True` — defaults (e.g. `Config.corpus_cap = 15_000`) are validated the same
  as any explicitly-passed value, so a future edit that types a default wrong is caught here
  rather than at first use.
"""

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Base class for every dataclass-equivalent shape in `contracts/`. See module docstring for
    the rationale behind each `model_config` choice.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
    )
