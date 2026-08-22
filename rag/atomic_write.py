"""One atomic file-write primitive shared by the whole tree (RI-21).

Every "persist a file durably" site in this repo needs the same shape — write a temp sibling,
then swap it into place — because a plain write can die halfway and leave a torn file that later
readers take for valid content (a corrupt `<paper_id>.json` sidecar wedges every later corpus
build: `app.assembly._cached_ref` re-validates it on each retry with no recovery path). This
module owns that shape once. Before RI-21 there were eight inline copies of it, four of them
missing the pid-qualification below — including one whose own docstring claimed it had it.

Why the temp name carries the pid (OG-49 M12): two processes writing the SAME target around the
same time otherwise share one temp path — one truncates the other's partial write, and whichever
publish lands second installs an interleaved/corrupt file or raises on a temp already moved away.
The 24/7 prefetcher and the live pipeline are structurally likely to converge on the same newest
paper_id (both modules' own comments say exactly this), so the two-writer case is real here, not
theoretical. A pid-qualified name gives each process its own staging file — distinct pids cannot
collide, which is the OS's per-process pid allocation, exercised by `rag/test_atomic_write.py` —
and publication is `os.replace` (POSIX-atomic; defined to overwrite, unlike `Path.rename`, which
raises if the target exists on some platforms), so whichever publisher lands last simply leaves
one complete, valid target behind.

Why this lives in `rag/` and nowhere else: every caller may depend downward on `rag/` (the
dashboard already imports `rag.config`/`rag.mcp_server`), while `rag/document_store.py` must
never import back up into `app/`; `contracts/` is foundation-frozen (CONVENTIONS.md §0.2) and
holds data shapes, not filesystem mechanics.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

# What open()/Path.write_text/create use pre-umask -- plain sites keep their historical
# permissions (typically 0644); credential writers opt into 0600 explicitly.
_DEFAULT_MODE = 0o666


def _pid_tmp_path(target: Path) -> Path:
    """`<name>.<pid>.tmp` beside `target` — see the module docstring for why the pid is there."""
    return target.with_name(f"{target.name}.{os.getpid()}.tmp")


@contextmanager
def staged_write(
    path: Path,
    *,
    binary: bool = False,
    mode: int = _DEFAULT_MODE,
    encoding: str = "utf-8",
) -> Iterator[IO]:
    """Stage `path`'s next content in a pid-qualified temp sibling; publish on a clean exit.

    Yields a writable stream. The temp file is created `O_CREAT|O_EXCL` at creation mode `mode`
    (umask applies, matching `open()`'s own semantics) BEFORE any content exists, so a credential
    file is never briefly readable at a wider mode. On a clean exit the stream is flushed and
    closed, then swapped onto `path` with `os.replace` — a concurrent reader sees either the old
    content or the new content in full, never a torn one. On ANY failure (in the body, in the
    close/flush, or in the replace itself) the temp is discarded and the original exception is
    re-raised with `path` untouched — cleanup-then-reraise, not error suppression (RI-6's
    `_write_private_file`, the model this generalizes).

    Prefer `atomic_write`; use this directly only when the publish must wait for a second durable
    action inside the body (`DocumentStore.put` stages the blob, commits its DB transaction, and
    only then lets the swap happen at exit — preserving its stage-before-commit ordering).
    """
    tmp = _pid_tmp_path(path)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    stream = os.fdopen(fd, "wb" if binary else "w", **({} if binary else {"encoding": encoding}))
    try:
        yield stream
    except BaseException:  # noqa: BLE001 -- cleanup-then-reraise, not error suppression
        stream.close()
        tmp.unlink(missing_ok=True)
        raise
    try:
        stream.close()
        os.replace(tmp, path)
    except BaseException:  # noqa: BLE001 -- cleanup-then-reraise, not error suppression
        tmp.unlink(missing_ok=True)
        raise


def atomic_write(
    path: Path,
    data: str | bytes,
    *,
    mode: int = _DEFAULT_MODE,
    encoding: str = "utf-8",
) -> None:
    """Write `data` to `path` atomically: staged in a pid-qualified temp sibling (module
    docstring), then swapped into place whole. `str` data is encoded with `encoding`; `bytes` are
    written verbatim. `mode` sets the temp file's CREATION mode (umask applies) — the default
    matches `Path.write_text`/`write_bytes`; pass `mode=0o600` for credential files.
    """
    with staged_write(path, binary=not isinstance(data, str), mode=mode, encoding=encoding) as f:
        f.write(data)
