"""Tests for `app.ingest` (T-DOC19 bug fix) -- offline, no real Docker/GPU/network calls.

The bug (confirmed by design review, PR #85): `rag/orchestrator.py`'s `finish_phase()` embeds its
once-per-run `topic_query_vec` BEFORE its own `before_finish_phase` hook fires (see that module's
`finish_phase` docstring -- frozen, unchanged by this fix). PR #85 originally wired
`before_finish_phase=tei_lifecycle.start_tei_containers` in `app/assembly.py`, which restarts TEI
too late: `app/ingest.py` runs Pass 1 as a subprocess (which stops TEI via `before_parse_phase`),
the subprocess exits, and then THIS process calls `orchestrator.finish_phase(refs)` directly --
`docker stop` is global container state that persists across that subprocess boundary, so the
topic-query embed call hits a still-stopped `rag-tei-embed` and fails before the (too-late) restart
hook ever runs.

The fix: `app/ingest.py`'s `_run_finish_phase` now calls `tei_lifecycle.start_tei_containers()`
itself, explicitly, before calling `orchestrator.finish_phase()` at all -- see that function's
docstring. `FakeFlakyEmbedder` below reproduces the bug's exact shape (raises `TransientError` --
the real mapping of `httpx.ConnectError` against a stopped container, `rag/embedder.py` -- for any
call made before TEI's "started" flag is observed true) so these tests can prove not just that
`start_tei_containers()` gets called, but that it completes BEFORE the topic-query embed is ever
attempted -- an ordering bug a "both hooks fire eventually" test would miss entirely.
"""

import pytest

from contracts.config import Config
from contracts.embedder import EmbedderInfo
from contracts.errors import TransientError
from contracts.harvester import PaperRef
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_ingest_state import FakeIngestState
from rag.orchestrator import IngestionOrchestrator

import app.ingest as ingest_mod


class FakeTeiLifecycle:
    """Local, test-only stand-in for `app.tei_lifecycle`'s public interface (named `Fake`-prefixed,
    no leading underscore, so `ci/checks/gpu_lock.py`'s check (f) leaves it alone the same way
    `app/test_assembly.py`'s `FakeSummarizer` does -- this class isn't a GPU-bound adapter, but its
    name doesn't end in Embedder/Summarizer/Reranker either way)."""

    def __init__(self, call_log: list[str]):
        self.started = False
        self._call_log = call_log

    def start_tei_containers(self) -> None:
        self._call_log.append("tei_start")
        self.started = True

    def stop_tei_containers(self) -> None:
        self._call_log.append("tei_stop")


class FakeFlakyEmbedder:
    """Reproduces the real `TeiEmbedder` hitting a `docker stop`-ped `rag-tei-embed` container:
    raises `TransientError` (the real `httpx.ConnectError` -> `TransientError` mapping,
    `rag/embedder.py`) on every call made while `tei.started` is still `False`, succeeds once it
    flips `True`. Appends into the SAME shared `call_log` list `FakeTeiLifecycle` writes to --
    that shared list is what lets a test assert the real cross-object sequence (tei restart, then
    embed), not just each object's own call count."""

    def __init__(self, tei: FakeTeiLifecycle, call_log: list[str]):
        self._tei = tei
        self.info = EmbedderInfo(model_id="flaky-embedder", dim=4, version="v1")
        self._call_log = call_log

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._tei.started:
            self._call_log.append("embed_attempt_while_stopped")
            raise TransientError("rag-tei-embed: connection refused (container stopped)")
        self._call_log.append("embed_attempt_while_started")
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class StubHarvester:
    """Returns no refs -- `finish_phase()`'s per-paper loop is irrelevant to this bug (the
    ordering it exercises is entirely in the once-per-run `topic_query_vec` embed, which
    `finish_phase()` computes unconditionally before that loop even starts, `rag/orchestrator.py`).
    Real `harvester.harvest(focus_area, cap, ordering)` interface, deliberately trivial."""

    def harvest(self, focus_area: list[str], cap: int, ordering: str) -> list[PaperRef]:
        return []


def _make_orchestrator(embedder, *, max_retries: int, retry_sleeps: list[float]):
    # parser/chunker/summarizer/document_store/vector_index are never called: StubHarvester
    # returns no refs, so finish_phase()'s per-paper loop body never runs -- only harvest() and
    # the once-per-run topic_query_vec embed() execute, which is exactly what this bug is about.
    return IngestionOrchestrator(
        harvester=StubHarvester(),
        parser=object(),
        chunker=object(),
        summarizer=object(),
        embedder=embedder,
        document_store=object(),
        vector_index=object(),
        state=FakeIngestState(),
        gpu_lock=FakeGpuLock(),
        config=Config(focus_area_queries=["causal inference"]),
        max_retries=max_retries,
        retry_sleep=retry_sleeps.append,
    )


def test_fixture_reproduces_the_original_bug_shape():
    """Sanity check on the fixtures themselves: calling `finish_phase()` before TEI has been
    restarted (PR #85's original, buggy order) must fail with `TransientError` -- proves
    `FakeFlakyEmbedder`/`FakeTeiLifecycle` actually reproduce the bug, so the fix test below is
    proving something real."""
    call_log: list[str] = []
    tei = FakeTeiLifecycle(call_log)
    embedder = FakeFlakyEmbedder(tei, call_log)
    retry_sleeps: list[float] = []
    orchestrator = _make_orchestrator(embedder, max_retries=0, retry_sleeps=retry_sleeps)

    try:
        orchestrator.finish_phase([])  # TEI never restarted -- the exact PR #85 bug
        raised = False
    except TransientError:
        raised = True

    assert raised, "finish_phase() before a TEI restart must fail, reproducing the PR #85 bug"
    assert call_log == ["embed_attempt_while_stopped"]


def test_run_finish_phase_restarts_tei_before_the_topic_query_embed(monkeypatch, tmp_path):
    """The actual fix: `app.ingest._run_finish_phase` must call
    `tei_lifecycle.start_tei_containers()` and have it complete BEFORE `finish_phase()`'s
    topic-query embed is ever attempted -- not just call both eventually. If the ordering
    regresses (e.g. someone moves the restart back behind `finish_phase()`, or back into a
    `before_finish_phase` hook), `FakeFlakyEmbedder` raises `TransientError` and this test fails
    loud, the same way a real Pass 2 run crashes today without the fix.
    """
    call_log: list[str] = []
    tei = FakeTeiLifecycle(call_log)
    embedder = FakeFlakyEmbedder(tei, call_log)
    retry_sleeps: list[float] = []
    orchestrator = _make_orchestrator(embedder, max_retries=0, retry_sleeps=retry_sleeps)

    monkeypatch.setattr(ingest_mod, "build_ingestion_orchestrator", lambda *a, **k: orchestrator)
    monkeypatch.setattr(ingest_mod, "tei_lifecycle", tei)

    cfg = Config(focus_area_queries=["causal inference"])
    ingest_mod._run_finish_phase(cfg)  # must not raise

    # The real sequence proof: TEI's restart is the first thing recorded, and the embed call that
    # follows sees `started == True` on its very first (and only) attempt -- no retry was needed
    # because the ordering was correct, not because a retry happened to paper over a wrong order.
    assert call_log == ["tei_start", "embed_attempt_while_started"]
    assert retry_sleeps == [], "no retry should have been needed once the ordering is correct"


# --- T-DOC51: sharded N-worker parallel Pass 1 ---------------------------------------------


class FakePopen:
    """Stand-in for `subprocess.Popen` -- records the argv it was launched with and returns a
    pre-scripted exit code from `.wait()` instead of spawning a real `app.parse_phase`/GPU
    subprocess."""

    _next_returncodes: list[int] = []
    launches: list[list[str]] = []

    def __init__(self, argv: list[str]):
        FakePopen.launches.append(argv)
        self._returncode = FakePopen._next_returncodes.pop(0)

    def wait(self) -> int:
        return self._returncode


@pytest.fixture(autouse=True)
def _reset_fake_popen():
    FakePopen.launches = []
    FakePopen._next_returncodes = []
    yield


def test_parse_workers_default_one_uses_original_subprocess_run(monkeypatch):
    """`parse_workers=1` (the `--parse-workers` default) must be byte-for-byte the original
    single `subprocess.run([sys.executable, "-m", "app.parse_phase"], check=True)` call -- no
    `--shard-index`/`--shard-count` args, no `Popen`."""
    run_calls = []
    monkeypatch.setattr(
        ingest_mod.subprocess, "run", lambda *a, **k: run_calls.append((a, k))
    )
    monkeypatch.setattr(ingest_mod.subprocess, "Popen", FakePopen)

    ingest_mod._run_parse_phase_subprocesses(1)

    assert run_calls == [
        (([ingest_mod.sys.executable, "-m", "app.parse_phase"],), {"check": True})
    ]
    assert FakePopen.launches == [], "single-worker path must not use Popen"


def test_parse_workers_n_spawns_n_shard_subprocesses(monkeypatch):
    """`--parse-workers N` (N>1) must spawn exactly N `app.parse_phase` subprocesses, each with
    its own disjoint `--shard-index i --shard-count N` -- verified via mocked `Popen`, no real
    GPU subprocess spawned."""
    monkeypatch.setattr(ingest_mod.subprocess, "Popen", FakePopen)
    FakePopen._next_returncodes = [0, 0, 0]

    ingest_mod._run_parse_phase_subprocesses(3)

    assert FakePopen.launches == [
        [ingest_mod.sys.executable, "-m", "app.parse_phase",
         "--shard-index", "0", "--shard-count", "3"],
        [ingest_mod.sys.executable, "-m", "app.parse_phase",
         "--shard-index", "1", "--shard-count", "3"],
        [ingest_mod.sys.executable, "-m", "app.parse_phase",
         "--shard-index", "2", "--shard-count", "3"],
    ]


def test_parse_workers_fails_the_run_if_any_worker_exits_nonzero(monkeypatch):
    """A non-zero exit from ANY worker (e.g. an OOM'd shard) must fail the whole run, not
    silently ship a partial corpus -- the exact benchmark pitfall the ticket calls out. All N
    workers are still waited on (both wait() calls happen) before the failure is raised."""
    monkeypatch.setattr(ingest_mod.subprocess, "Popen", FakePopen)
    FakePopen._next_returncodes = [0, 1, 0]  # shard 1 "OOM'd"

    with pytest.raises(RuntimeError, match=r"1/3 shard worker\(s\) failed"):
        ingest_mod._run_parse_phase_subprocesses(3)

    assert len(FakePopen.launches) == 3, "all 3 workers must have been launched"


def test_parse_workers_all_succeed_returns_normally(monkeypatch):
    monkeypatch.setattr(ingest_mod.subprocess, "Popen", FakePopen)
    FakePopen._next_returncodes = [0, 0]

    ingest_mod._run_parse_phase_subprocesses(2)  # must not raise
