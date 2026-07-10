"""CONVENTIONS.md §12's nine PR-checklist items, mechanized (T-F6, WORK-BREAKDOWN.md).

Every lexical/structural check (a)-(d), (f)-(h) shares one shape: `(files: list[DiffFile], ...)
-> list[Violation]`, `files` built by `ci.checks.diff.build_diff_files` from a real diff, or by
`DiffFile.from_whole_file` from a single fixture in a test. Check (e) takes a plain path list
instead of `DiffFile`s (it doesn't need file content, and only runs on `pull_request` events —
see `ci.checks.foundation_label`). Check (i) isn't a function here at all — it's proven by a
pytest test (`ci/proof_socket_block/test_real_network_blocked.py`) that the `unit-tests` job's
existing `--disable-socket` wiring actually blocks a real connection; see that file and
`ci/run_enforcement.py`'s module docstring.

`run_enforcement.py` is the only caller that composes these against a real diff; everything below
is importable and independently callable for that, and for `ci/checks/test_checks.py`.
"""

from ci.checks.blind_except import check_c
from ci.checks.contract_shadowing import check_b, discover_contract_names
from ci.checks.env_leak import check_d
from ci.checks.foundation_label import check_e, read_codeowners_paths
from ci.checks.gpu_lock import check_f
from ci.checks.id_slicing import check_h
from ci.checks.model import DiffFile, Violation
from ci.checks.sibling_tests import check_g
from ci.checks.vendor_isolation import check_a

__all__ = [
    "DiffFile",
    "Violation",
    "check_a",
    "check_b",
    "check_c",
    "check_d",
    "check_e",
    "check_f",
    "check_g",
    "check_h",
    "discover_contract_names",
    "read_codeowners_paths",
]
