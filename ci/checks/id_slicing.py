"""Check (h) — CONVENTIONS.md §0.8 / §12: no manual slicing/parsing of `chunk_id`/`block_id`/
`summary_id` strings outside `DocumentStore`'s own module. Callers resolve ids through
`get_chunk`/`get_block`/`get_summary`, never by reverse-engineering the `"{paper_id}:c{n}"`
encoding (DATA-CONTRACTS.md §IDs) themselves — that encoding is `DocumentStore`'s secret to keep.

`DocumentStore` doesn't exist yet (Owner D's M5 ticket, T-D1). Its path is hardcoded here per this
repo's established convention of a `rag/<module>.py` implementation next to its
`contracts/<module>.py` interface (e.g. `rag/config.py` beside `contracts/config.py`) — so
`contracts/document_store.py` implies `rag/document_store.py`.

Scoped to `rag/`/`contracts/` (`model.in_pipeline_scope`) — the id-encoding secret this check
protects belongs to the pipeline; this package's own fixtures/docs are allowed to talk about it.
"""

from __future__ import annotations

import re

from ci.checks.model import DiffFile, Violation, in_pipeline_scope

EXEMPT_PATH = "rag/document_store.py"

_ID_FIELDS = r"(?:chunk_id|block_id|summary_id)"
_MANUAL_SLICE = re.compile(
    rf"\b\w*{_ID_FIELDS}\w*\s*(?:\.split\(|\[[^\]]*:[^\]]*\])",
)


def check_h(files: list[DiffFile]) -> list[Violation]:
    violations = []
    for f in files:
        if not in_pipeline_scope(f.path) or f.path == EXEMPT_PATH:
            continue
        for line_no, text in f.added_lines:
            if _MANUAL_SLICE.search(text):
                violations.append(
                    Violation(
                        check="h",
                        path=f.path,
                        line=line_no,
                        message=(
                            "manual chunk_id/block_id/summary_id slicing outside "
                            f"{EXEMPT_PATH} — resolve via get_chunk/get_block/get_summary "
                            f"instead: {text.strip()!r}"
                        ),
                    )
                )
    return violations
