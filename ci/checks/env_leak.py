"""Check (d) — CONVENTIONS.md §3 / §12: no `os.getenv`/`os.environ` outside `rag/config.py`, the
one module allowed to read the process environment.

Scoped to `rag/`/`contracts/`/`app/` (`model.in_pipeline_scope`): this rule is about the RAG
pipeline never scattering env reads outside its one `Config` loader (CONVENTIONS §3) — it was
never meant to reach into this repo's own CI tooling, which legitimately reads `GITHUB_EVENT_NAME`/
`GITHUB_EVENT_PATH` as a CI script, not a pipeline module (see `ci/run_enforcement.py`). `app/`
(the composition-root/entrypoint code) was added to scope by T-DOC29, which found 7 real
`os.environ.get(...)` reads had silently accumulated there while this check was scoped to only
`rag/`/`contracts/` — see `contracts/config.py`'s "composition-root levers" fields, which is where
those reads now live instead.

Note this check is diff-based (`f.added_lines` below), not a full-repo scan (`ci/run_enforcement.py`
module docstring: a full-repo scan would re-flag pre-existing content forever). That means a
violation that lands in scope BEFORE it's ever touched by a scanned diff is invisible until someone
edits those exact lines again — `app/serve.py`'s `RAG_DB_PATH`/`RAG_BLOB_DIR`/`RAG_COLLECTION` reads
(added by T-DOC33, after T-DOC29's migration above) were exactly this: already in `app/` scope, but
never re-flagged because no later diff touched them. Fixed at the source (those reads are gone from
`app/serve.py` now) rather than papered over here — there is no separate allowlist in this file to
carve them out of; scope has always been `app/` in full. No check_d logic changed by that fix.
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
