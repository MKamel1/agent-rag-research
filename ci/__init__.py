"""CI enforcement tooling (T-F6, WORK-BREAKDOWN.md).

Not a `rag/`/`contracts/` module — this package mechanizes CONVENTIONS.md §12's PR checklist
for the build *process*, it isn't part of the RAG system's runtime. See `ci/checks/__init__.py`
for the checks themselves and `ci/run_enforcement.py` for the CI entrypoint that composes them.
"""
