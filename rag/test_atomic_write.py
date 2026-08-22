"""`rag/atomic_write.py` — the tree's one atomic file-write primitive (RI-21).

The behaviour that matters is not "a file appeared" — it is that two concurrent writers of the
same target never share a temp path (the T-DOC18 bug shape: one truncates the other's partial
write, and whichever rename lands second installs a corrupt file or crashes on a moved-away
temp), and that a reader only ever sees the old file or the new file in full.

Two pids are simulated the way `app/test_prefetch_pdfs.py`'s OG-49 M12 tests already do: the
temp-name convention is asserted against `os.getpid()`, and the *other* writer is materialized
as a foreign-pid temp file that must survive our write untouched. No real concurrency, no
flakiness — the collision-freedom property is forced by the name construction, not by timing.
"""

import json
import os
from pathlib import Path

import pytest

from rag import atomic_write as mod
from rag.atomic_write import atomic_write, staged_write

# ================================================================================================
# The temp-name convention: pid-qualified, in the target's own directory.
# ================================================================================================


def test_pid_tmp_path_is_qualified_by_this_process_pid():
    target = Path("some_dir") / "paper.json"
    assert mod._pid_tmp_path(target) == Path("some_dir") / f"paper.json.{os.getpid()}.tmp"


def test_pid_tmp_path_differs_between_two_concurrent_pids():
    # Simulates what a second, concurrent writer process would compute for the SAME target --
    # a different pid must never produce the same temp path (OG-49 M12's two-writer convention).
    ours = mod._pid_tmp_path(Path("some_dir") / "paper.json")
    other_pid = os.getpid() + 1
    theirs = Path("some_dir") / f"paper.json.{other_pid}.tmp"
    assert ours != theirs


def test_pid_tmp_path_is_a_sibling_of_the_target_not_a_shared_tmp_dir():
    # Same-directory staging is load-bearing: os.replace is only atomic within one filesystem,
    # so a cross-device tempfile.gettempdir() name would turn the publish into a copy.
    target = Path("data_dir") / "sub" / "file.md"
    assert mod._pid_tmp_path(target).parent == target.parent


# ================================================================================================
# Collision-freedom under two writers, and whole-file publication.
# ================================================================================================


def test_write_never_touches_another_writers_temp_file(tmp_path):
    """The two-writer scenario end to end: the foreign writer's staged temp (different pid, same
    target) must survive our write byte-for-byte, and our own publish must land complete."""
    target = tmp_path / "tag_pool.json"
    payload = json.dumps({"active": ["x" * 5000]})
    foreign_tmp = tmp_path / f"tag_pool.json.{os.getpid() + 1}.tmp"
    foreign_tmp.write_text("another writer's partial write")

    atomic_write(target, payload)

    assert foreign_tmp.read_text() == "another writer's partial write"
    assert json.loads(target.read_text()) == json.loads(payload), (
        "the target must end up complete and valid, never interleaved with the other writer"
    )


def test_second_write_publishes_its_whole_file_not_a_merge_of_both(tmp_path):
    target = tmp_path / "data.bin"
    atomic_write(target, b"A" * 100_000)
    atomic_write(target, b"B" * 100_000)

    assert target.read_bytes() == b"B" * 100_000


def test_no_temp_file_is_left_behind_after_success(tmp_path):
    target = tmp_path / "x.md"
    atomic_write(target, "content")

    assert target.read_text() == "content"
    assert list(tmp_path.glob("*.tmp")) == []


# ================================================================================================
# Failure handling: cleanup-then-reraise, target untouched.
# ================================================================================================


def test_failed_body_discards_the_staged_temp_and_leaves_the_target_untouched(tmp_path):
    target = tmp_path / "x.json"
    target.write_text("old-good-content")

    with pytest.raises(RuntimeError, match="boom"):
        with staged_write(target) as f:
            f.write("half-written garbage")
            raise RuntimeError("boom")

    assert target.read_text() == "old-good-content"
    assert list(tmp_path.glob("*.tmp")) == []


def test_failed_publish_also_cleans_up_the_staged_temp(tmp_path, monkeypatch):
    target = tmp_path / "x.json"
    target.write_text("old-good-content")

    def failing_replace(src, dst):
        raise OSError("EDQUOT: disk full")

    monkeypatch.setattr(mod.os, "replace", failing_replace)

    with pytest.raises(OSError):
        atomic_write(target, "new content")

    assert target.read_text() == "old-good-content"
    assert list(tmp_path.glob("*.tmp")) == []


def test_publish_happens_at_exit_not_during_the_body(tmp_path):
    """`staged_write` exists for the one caller whose publish must wait for a second durable
    action (DocumentStore.put: blob staged, then the DB transaction, then the swap) -- so the
    target must not exist while the body runs."""
    target = tmp_path / "blob.md"
    seen_inside = None

    with staged_write(target) as f:
        f.write("# staged")
        seen_inside = target.exists()

    assert seen_inside is False
    assert target.read_text() == "# staged"


# ================================================================================================
# Modes and encodings: the helper must serve the dashboard's 0600 token file AND the plain
# write_text/write_bytes sites without either falling back to its own inline copy (RI-21).
# ================================================================================================


def test_mode_kwarg_creates_the_file_private(tmp_path):
    target = tmp_path / ".dashboard_token"
    atomic_write(target, "secret-token", mode=0o600)

    assert oct(target.stat().st_mode)[-3:] == "600"


def test_default_creation_mode_matches_stdlib_write_text(tmp_path):
    # 0o666 pre-umask is what open()/Path.write_text create with -- the plain sites must keep
    # their historical permissions (typically 0644), only the dashboard opts into 0600.
    mask = os.umask(0)
    os.umask(mask)

    target = tmp_path / "plain.md"
    atomic_write(target, "content")

    assert oct(target.stat().st_mode)[-3:] == oct(0o666 & ~mask)[-3:]


def test_bytes_data_round_trips_verbatim(tmp_path):
    target = tmp_path / "paper.pdf"
    raw = b"%PDF-1.7 \x00\x01\x02 binary payload"

    atomic_write(target, raw)

    assert target.read_bytes() == raw


def test_str_data_is_encoded_with_the_given_encoding(tmp_path):
    target = tmp_path / "blob.md"
    atomic_write(target, "café", encoding="utf-8")
    assert target.read_bytes() == b"caf\xc3\xa9"

    other = tmp_path / "other.md"
    atomic_write(other, "café", encoding="latin-1")
    assert other.read_bytes() == b"caf\xe9"
