"""Check (h) — CONVENTIONS.md §0.8 / §12: no manual slicing/parsing of the `.id` string that
`Hit`/`RerankCandidate` carry (contracts/vector_index.py, contracts/retriever.py — the frozen
`chunk_id`/`block_id`/`summary_id` spine, DATA-CONTRACTS.md §IDs) outside `DocumentStore`'s own
module. Callers resolve ids through `get_chunk`/`get_block`/`get_summary`, never by
reverse-engineering the `"{paper_id}:c{n}"`/`"{paper_id}:summary"` encoding themselves — that
encoding is `DocumentStore`'s secret to keep.

Keyed off the actual frozen field (`.id` attribute access), not a variable-name substring: an
earlier version of this check required the sliced variable's *name* to contain
`chunk_id`/`block_id`/`summary_id`, so it never matched real code slicing `candidate.id` (`Hit`/
`RerankCandidate`'s actual, generically-named field) — and it only matched `.split(`/slice syntax,
missing `.removesuffix(`/`.removeprefix(` entirely (`.phase0-data/retriever-summary-id-proposal.md`
§5, both blind spots hit by the same real line of code). This version matches any `.id` attribute
access followed by `.split(`, `.removesuffix(`, `.removeprefix(`, or a slice.

`DocumentStore` doesn't exist yet (Owner D's M5 ticket, T-D1). Its path is hardcoded here per this
repo's established convention of a `rag/<module>.py` implementation next to its
`contracts/<module>.py` interface (e.g. `rag/config.py` beside `contracts/config.py`) — so
`contracts/document_store.py` implies `rag/document_store.py`.

One sanctioned exception, fenced by name+line-range, not by whole file: `rag/retriever.py`'s
`_paper_id_from_summary_hit_id` function is the ONE call site allowed to parse the
`"{paper_id}:summary"` format (DATA-CONTRACTS.md's `get_summary` entry) because `get_summary`/
`Hit` carry no `paper_id` field to resolve() against. The exemption is scoped to that function's
own line range within that one file — any OTHER function added to `rag/retriever.py` (or any other
pipeline file) that parses `.id` the same way still trips this check.

Scoped to `rag/`/`contracts/`/`app/` (`model.in_pipeline_scope`; `app/` added by T-DOC29) — the
id-encoding secret this check protects belongs to the pipeline; this package's own fixtures/docs
are allowed to talk about it.
"""

from __future__ import annotations

import ast
import re

from ci.checks.model import DiffFile, Violation, in_pipeline_scope

# Curated, not derived -- extend/update this if `DocumentStore` (the one module allowed to slice
# these ids) ever moves or gains a sibling once M5/T-D1 lands it.
EXEMPT_PATH = "rag/document_store.py"

# The one sanctioned ad-hoc parse site (DATA-CONTRACTS.md's get_summary entry) -- fenced to this
# function's own line range within this one file, not a whole-file exemption (see module
# docstring). Curated, not derived -- update if this helper is ever renamed/moved.
SANCTIONED_PATH = "rag/retriever.py"
SANCTIONED_FUNCTION = "_paper_id_from_summary_hit_id"

_MANUAL_SLICE = re.compile(
    r"\.id\s*(?:\.split\(|\.removesuffix\(|\.removeprefix\(|\[[^\]]*:[^\]]*\])",
)


def _sanctioned_line_range(content: str) -> range:
    """Line range (1-indexed, `range` end exclusive) covering `SANCTIONED_FUNCTION`'s full body
    (signature through last statement, docstring included) in `content`. Empty range if the
    function isn't found or `content` doesn't parse -- fail closed, i.e. nothing gets exempted.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return range(0, 0)
    func_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, func_types) and node.name == SANCTIONED_FUNCTION:
            end = getattr(node, "end_lineno", None) or node.lineno
            return range(node.lineno, end + 1)
    return range(0, 0)


def check_h(files: list[DiffFile]) -> list[Violation]:
    violations = []
    for f in files:
        if not in_pipeline_scope(f.path) or f.path == EXEMPT_PATH:
            continue
        sanctioned_range = (
            _sanctioned_line_range(f.content) if f.path == SANCTIONED_PATH else range(0, 0)
        )
        for line_no, text in f.added_lines:
            if line_no in sanctioned_range:
                continue
            if _MANUAL_SLICE.search(text):
                violations.append(
                    Violation(
                        check="h",
                        path=f.path,
                        line=line_no,
                        message=(
                            "manual .id slicing/parsing (chunk_id/block_id/summary_id format) "
                            f"outside {EXEMPT_PATH} — resolve via get_chunk/get_block/get_summary "
                            f"instead (or {SANCTIONED_PATH}::{SANCTIONED_FUNCTION} if this really "
                            f"is the sanctioned parse site): {text.strip()!r}"
                        ),
                    )
                )
    return violations
