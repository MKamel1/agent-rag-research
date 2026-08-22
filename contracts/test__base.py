"""Sibling test for contracts/_base.py (RI-23: check (g) flags any edit to a module without one).

Pins FrozenModel's four model_config choices against real pydantic behaviour, so a future edit to
that base cannot silently change every contract shape at once. The nested-dict caveat is
contractual too: _base.py's docstring warns that strict mode does NOT stop a plain dict being
coerced into a nested FrozenModel field -- this suite fails if someone changes that behaviour
without updating the warning (or vice versa).
"""

import pytest
from pydantic import ValidationError

from contracts._base import FrozenModel


class _Point(FrozenModel):
    x: int


class _Named(FrozenModel):
    name: str


class _Wrapper(FrozenModel):
    point: _Point


def test_strict_mode_rejects_coercing_a_string_into_an_int_field():
    with pytest.raises(ValidationError):
        _Point(x="1")  # non-strict pydantic accepts this as 1


def test_strict_mode_rejects_coercing_a_whole_float_into_an_int_field():
    # A whole float (1.0) is chosen deliberately: non-strict pydantic accepts it as 1, whereas it
    # already rejects most other wrong-typed inputs (it does not coerce int->str), so this is the
    # second direction that actually distinguishes strict from non-strict rather than pinning
    # behaviour both modes share.
    with pytest.raises(ValidationError):
        _Point(x=1.0)


def test_correctly_typed_construction_still_works():
    assert _Point(x=1).x == 1
    assert _Named(name="ok").name == "ok"


def test_frozen_model_rejects_attribute_mutation():
    point = _Point(x=1)
    with pytest.raises(ValidationError):
        point.x = 2


def test_unknown_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        _Point(x=1, y=2)  # a typo'd/drifted kwarg must fail loudly, not be ignored


def test_nested_frozen_model_field_still_accepts_a_plain_dict_under_strict_mode():
    # The documented caveat in _base.py's docstring: strict mode restricts scalar/container
    # coercion, not dict-into-submodel construction.
    wrapper = _Wrapper.model_validate({"point": {"x": 1}})
    assert wrapper.point == _Point(x=1)
