"""Sibling test for contracts/errors.py (T-F1 DoD: imported by a trivial test)."""

import pytest

from contracts.errors import ContractError, PermanentError, TransientError


def test_three_classes_are_distinct_exception_subclasses():
    for cls in (TransientError, PermanentError, ContractError):
        assert issubclass(cls, Exception)
    # Distinct classes, not aliases of one another / of the others.
    assert TransientError is not PermanentError
    assert PermanentError is not ContractError
    assert TransientError is not ContractError


def test_each_is_raisable_and_catchable_independently():
    with pytest.raises(TransientError):
        raise TransientError("temporary network blip")
    with pytest.raises(PermanentError):
        raise PermanentError("corrupt e-print")
    with pytest.raises(ContractError):
        raise ContractError("block missing bbox")


def test_catching_one_class_does_not_catch_a_sibling():
    with pytest.raises(PermanentError):
        try:
            raise PermanentError("bad pdf")
        except TransientError:  # wrong class — must not swallow PermanentError
            pytest.fail("TransientError handler incorrectly caught a PermanentError")
