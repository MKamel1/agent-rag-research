"""Root conftest — loaded before any test module import, regardless of which directory under
`testpaths` pytest starts collecting from.

T-DOC19: `app/assembly.py` now does `from app import tei_lifecycle` at module import time, wiring
`build_ingestion_orchestrator`'s `before_parse_phase`/`before_finish_phase` hooks to it. That
sibling module (`app/tei_lifecycle.py`) is being built on a parallel branch and doesn't exist in
this branch yet, so *any* import of `app.assembly` — including transitive ones this ticket didn't
touch, e.g. `rag/test_composition_e2e.py`'s module-level import, which still runs at collection
time even though the test itself is `real_adapter`-marked and deselected by default — would fail
collection with `ModuleNotFoundError` without this. This stub is a bridge only: it's a no-op
(`find_spec` short-circuits it) the moment the real module lands, so it self-removes when the
sibling branch merges instead of needing a follow-up cleanup.
"""

import importlib.util
import sys
import types

if importlib.util.find_spec("app.tei_lifecycle") is None:
    _stub = types.ModuleType("app.tei_lifecycle")
    _stub.stop_tei_containers = lambda: None
    _stub.start_tei_containers = lambda: None
    sys.modules["app.tei_lifecycle"] = _stub
