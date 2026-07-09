"""Sibling test for contracts/gpu_lock.py (T-F1 DoD: imported by a trivial test).

GpuLock is a structural Protocol, not a pydantic model — there is no "wrong type raises at
construction" for a Protocol (nothing is constructed, only implemented). Instead this proves the
two things that make it usable as a contract: (1) it can be imported and used as a type
annotation, and (2) `isinstance` against it (it's `@runtime_checkable`) actually discriminates a
conforming shape from a non-conforming one — a class missing `acquire` must not satisfy it.
"""

from contextlib import contextmanager

from contracts.gpu_lock import GpuLock


class _ConformingLock:
    @contextmanager
    def acquire(self, stage: str):
        yield


class _NonConformingLock:
    """Missing `acquire` entirely — must not satisfy the GpuLock protocol."""


def test_conforming_class_satisfies_the_protocol():
    assert isinstance(_ConformingLock(), GpuLock)


def test_non_conforming_class_does_not_satisfy_the_protocol():
    assert not isinstance(_NonConformingLock(), GpuLock)


def test_acquire_yields_a_context_manager_that_is_a_no_op_by_default_shape():
    lock = _ConformingLock()
    # must not raise; the real contract is enforced by the real FileGpuLock adapter, not here
    with lock.acquire("embed"):
        pass
