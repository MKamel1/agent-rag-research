"""Warn-only CI nudge (`docs/AGENT-PROCEDURES.md` section B): flags a diff that touches `app/` or
`rag/` source with no accompanying doc change, and points the author at what's usually expected.
Never blocks anything -- deliberately **not** in `ci/run_enforcement.py`'s composed check list, and
`main()` below always exits 0 regardless of what it finds. CONVENTIONS.md §0.1's "a checkable rule
must be a blocking CI job" applies to CONVENTIONS.md's own checklist (§12); this is a separate,
explicitly-advisory nudge for `docs/AGENT-PROCEDURES.md` §B, not one of those checks.

Reuses `ci/checks/changed_files.py`'s diff-base/changed-path machinery -- the same plumbing
`ci/run_enforcement.py` uses -- rather than reinventing a diff mechanism. Deliberately does not use
`ci/checks/diff.py`'s `DiffFile`/`build_diff_files`: this check only needs *which paths* changed, not
file content, and it specifically needs to see `.md` doc paths that `ci/run_enforcement.py`'s
`_is_scannable` filters out before ever building a `DiffFile` (that filter exists because the lexical
checks are Python-source-specific). `check_e` (`ci/checks/foundation_label.py`) sets the precedent
for a check taking a plain `list[str]` of paths instead of `DiffFile`s when content isn't needed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from ci.checks.changed_files import compute_diff_base, list_changed_paths

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Top-level docs an agent is expected to be updating alongside app/rag changes per
# docs/AGENT-PROCEDURES.md section B. Curated, not derived -- same style as
# ci/checks/vendor_isolation.py's VENDOR_RULES. Verified against `ls *.md` at the repo root
# 2026-08-06; extend if a new top-level doc joins that set.
_TRACKED_TOP_LEVEL_DOCS = {
    "AGENTS.md",
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "DATA-CONTRACTS.md",
    "CONVENTIONS.md",
    "WORK-BREAKDOWN.md",
    "PRD.md",
    "GIT-WORKFLOW.md",
    "CONTEXT.md",
    "TEST-STRATEGY.md",
}

_SOURCE_PREFIXES = ("app/", "rag/")

_MESSAGE = (
    "docs: this diff touches app/ or rag/ source with no doc changes -- see "
    "docs/AGENT-PROCEDURES.md section B for what's usually expected."
)


def check_doc_touch(changed_paths: list[str]) -> list[str]:
    """Pure check: given the diff's changed paths, return zero or one reminder message.

    Fires when the diff touches `app/`/`rag/` source (`*.py`, excluding `test_*.py`) and touches no
    doc (nothing under `docs/`, none of `_TRACKED_TOP_LEVEL_DOCS`). Returns a list, not a bool, so
    the result is directly printable by a caller -- empty means nothing to say.
    """
    if not any(_is_source(p) for p in changed_paths):
        return []
    if any(_is_doc(p) for p in changed_paths):
        return []
    return [_MESSAGE]


def _is_source(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    name = path.rsplit("/", 1)[-1]
    if name.startswith("test_"):
        return False
    return path.startswith(_SOURCE_PREFIXES)


def _is_doc(path: str) -> bool:
    return path.startswith("docs/") or path in _TRACKED_TOP_LEVEL_DOCS


def main() -> int:
    # Always returns 0 -- this is a nudge, never a gate (see module docstring). No try/except here:
    # CONVENTIONS.md §12 check (c) blocks any `except Exception`/bare `except:` in the diff with no
    # exemption mechanism (§0.1 -- a checkable rule is a CI job, not a comment a reviewer trusts). The
    # "never block CI" guarantee instead comes entirely from this always-0 return plus the workflow
    # step's own `continue-on-error: true` -- an uncaught exception here still can't fail the build.
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = _load_event()
    diff_base = compute_diff_base(event_name, event, REPO_ROOT)
    changed = list_changed_paths(diff_base, REPO_ROOT)
    for message in check_doc_touch(changed):
        print(message)
    return 0


def _load_event() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    return json.loads(Path(event_path).read_text())


if __name__ == "__main__":
    sys.exit(main())
