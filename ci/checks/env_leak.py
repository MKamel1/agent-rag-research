"""Check (d) — CONVENTIONS.md §3 / §12: no `os.getenv`/`os.environ` outside `rag/config.py`, the
one module allowed to read the process environment.

Scoped to `rag/`/`contracts/` (`model.in_pipeline_scope`): this rule is about the RAG pipeline
never scattering env reads outside its one `Config` loader (CONVENTIONS §3) — it was never meant
to reach into this repo's own CI tooling, which legitimately reads `GITHUB_EVENT_NAME`/
`GITHUB_EVENT_PATH` as a CI script, not a pipeline module (see `ci/run_enforcement.py`).
"""

from __future__ import annotations

import re

from ci.checks.model import DiffFile, Violation, in_pipeline_scope

# Curated, not derived -- extend/update this if the one module allowed to read the environment
# ever moves or gains a sibling.
EXEMPT_PATH = "rag/config.py"

_ENV_READ = re.compile(r"\bos\.(getenv|environ)\b")


def check_d(files: list[DiffFile]) -> list[Violation]:
    violations = []
    for f in files:
        if not in_pipeline_scope(f.path) or f.path == EXEMPT_PATH:
            continue
        for line_no, text in f.added_lines:
            if _ENV_READ.search(text):
                violations.append(
                    Violation(
                        check="d",
                        path=f.path,
                        line=line_no,
                        message=(
                            f"reads the process environment outside {EXEMPT_PATH}: {text.strip()!r}"
                        ),
                    )
                )
    return violations
