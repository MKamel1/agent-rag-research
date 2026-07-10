"""The shared vocabulary every check in this package speaks: `Violation` (a check's output) and
`DiffFile` (a check's input). Centralizing these here means each check function's signature is
`(files: list[DiffFile], ...) -> list[Violation]` — uniform enough that `run_enforcement.py` can
compose all of them the same way, and small enough that a test can build one by hand without
touching git at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# The RAG pipeline's own module tree (ARCHITECTURE.md/CONVENTIONS.md's "modules"). Checks whose
# CONVENTIONS.md rule is inherently about pipeline code (vendor isolation, os.getenv, id-slicing,
# sibling tests) are scoped to this — *not* repo-wide — precisely because this package's own
# source under `ci/` legitimately talks about vendor names (as check data), reads
# `GITHUB_EVENT_*` env vars (as a CI script, not a pipeline module), and so on. Without this scope,
# those checks would flag their own implementation on the very push that adds them — the
# self-referential trap this ticket's design constraint warns about, just one level removed from
# the "negative_examples" one.
PIPELINE_SCOPE_PREFIXES = ("rag/", "contracts/")


def in_pipeline_scope(path: str) -> bool:
    return path.startswith(PIPELINE_SCOPE_PREFIXES)


@dataclass(frozen=True)
class Violation:
    """One thing a check found wrong. `check` is the short id (e.g. "a", "gpu_lock") so CI output
    and this repo's docs (CONVENTIONS.md §12) can be cross-referenced by eye.
    """

    check: str
    path: str
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"[{self.check}] {where}: {self.message}"


@dataclass(frozen=True)
class DiffFile:
    """One file's worth of input a check can look at.

    `path` is the repo-relative path used for every *rule-matching* decision (vendor-adapter
    exemptions, the `rag/config.py`/`rag/document_store.py` carve-outs, CODEOWNERS prefixes,
    contracts/ exclusion). `abs_path`/`content` are only where the bytes came from.

    These are deliberately allowed to disagree: `from_whole_file` always sets `path` to wherever
    it read the content from, but a caller (chiefly `ci/checks/test_checks.py`) can construct a
    `DiffFile` directly with a *different* `path` than the fixture file it borrowed content from —
    e.g. reusing `negative_examples/env_leak_good.py`'s bytes under the logical path
    `rag/config.py` to prove the exemption fires, without checking a stray file into the real,
    CODEOWNERS-protected `rag/config.py`. Every check in this package must key its rules off
    `path`, never off `abs_path`, for this to work.

    `added_lines` is the diff's added lines as `(1-indexed line number in `content`, text)` pairs
    — what the lexical checks (vendor names, `os.getenv`, bare `except`, id-slicing) grep. For a
    file treated as "entirely new" (a fixture, or a freshly-added file in a real diff), every line
    is an added line.
    """

    path: str
    abs_path: Path
    content: str
    added_lines: list[tuple[int, str]] = field(default_factory=list)

    @staticmethod
    def from_whole_file(path: str, repo_root: Path, *, logical_path: str | None = None) -> DiffFile:
        """Read `repo_root / path` off disk and treat every line as added.

        `logical_path` overrides `path` for rule-matching (see class docstring) while still
        reading bytes from the real file at `path` — the mechanism `test_checks.py` uses to test
        an exemption without touching the exempted file itself.
        """
        abs_path = repo_root / path
        content = abs_path.read_text()
        lines = content.splitlines()
        return DiffFile(
            path=logical_path if logical_path is not None else path,
            abs_path=abs_path,
            content=content,
            added_lines=list(enumerate(lines, start=1)),
        )
