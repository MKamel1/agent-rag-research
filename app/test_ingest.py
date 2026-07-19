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

import argparse
import sqlite3

import pytest
import yaml

import app.doctor as doctor_mod
import app.ingest as ingest_mod
from contracts.config import Config
from contracts.embedder import EmbedderInfo
from contracts.errors import TransientError
from contracts.harvester import PaperRef
from migrations.migrate import migrate as real_migrate
from rag.fakes.fake_gpu_lock import FakeGpuLock
from rag.fakes.fake_ingest_state import FakeIngestState
from rag.orchestrator import IngestionOrchestrator


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


# --- T-DOC59 (OG-25): on_stage forwarded to build_ingestion_orchestrator -------------------


def test_run_finish_phase_forwards_on_stage_to_build_ingestion_orchestrator(monkeypatch):
    """`_run_finish_phase`'s `on_stage=` kwarg must reach `build_ingestion_orchestrator`
    unmodified -- the seam `__main__` uses to wire `run.set_stage` (app/telemetry.py) through to
    `rag/orchestrator.py`'s per-paper summarize/embed/store hook."""
    call_log: list[str] = []
    tei = FakeTeiLifecycle(call_log)
    embedder = FakeFlakyEmbedder(tei, call_log)
    orchestrator = _make_orchestrator(embedder, max_retries=0, retry_sleeps=[])
    captured_kwargs = {}

    def _fake_build(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return orchestrator

    monkeypatch.setattr(ingest_mod, "build_ingestion_orchestrator", _fake_build)
    monkeypatch.setattr(ingest_mod, "tei_lifecycle", tei)

    cfg = Config(focus_area_queries=["causal inference"])
    sentinel_on_stage = lambda stage: None  # noqa: E731 -- identity-checked below, not called
    ingest_mod._run_finish_phase(cfg, on_stage=sentinel_on_stage)

    assert captured_kwargs["on_stage"] is sentinel_on_stage


def test_run_finish_phase_default_on_stage_is_none(monkeypatch):
    """No caller-supplied `on_stage` (every pre-T-DOC59 call site) forwards `None` -- today's
    exact default behavior, `build_ingestion_orchestrator`/`IngestionOrchestrator`'s own no-op."""
    call_log: list[str] = []
    tei = FakeTeiLifecycle(call_log)
    embedder = FakeFlakyEmbedder(tei, call_log)
    orchestrator = _make_orchestrator(embedder, max_retries=0, retry_sleeps=[])
    captured_kwargs = {}

    def _fake_build(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return orchestrator

    monkeypatch.setattr(ingest_mod, "build_ingestion_orchestrator", _fake_build)
    monkeypatch.setattr(ingest_mod, "tei_lifecycle", tei)

    cfg = Config(focus_area_queries=["causal inference"])
    ingest_mod._run_finish_phase(cfg)

    assert captured_kwargs["on_stage"] is None


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


def test_parse_workers_default_one_with_cwd_passes_cwd_kwarg(monkeypatch):
    """T-DOC45/T-DOC46: when a scratch config dir is in play, the single-worker path must pass
    `cwd=` through to `subprocess.run` -- everything else about the call stays identical."""
    run_calls = []
    monkeypatch.setattr(ingest_mod.subprocess, "run", lambda *a, **k: run_calls.append((a, k)))

    ingest_mod._run_parse_phase_subprocesses(1, cwd="/tmp/some-override-dir")

    assert run_calls == [
        (
            ([ingest_mod.sys.executable, "-m", "app.parse_phase"],),
            {"check": True, "cwd": "/tmp/some-override-dir"},
        )
    ]


def test_parse_workers_n_with_cwd_passes_cwd_to_every_popen(monkeypatch):
    calls = []

    class _RecordingPopen:
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))
            self._returncode = 0

        def wait(self) -> int:
            return self._returncode

    monkeypatch.setattr(ingest_mod.subprocess, "Popen", _RecordingPopen)

    ingest_mod._run_parse_phase_subprocesses(2, cwd="/tmp/some-override-dir")

    assert len(calls) == 2
    for _argv, kwargs in calls:
        assert kwargs == {"cwd": "/tmp/some-override-dir"}


# --- T-DOC44: DB auto-provision -------------------------------------------------------------


def test_ensure_db_migrated_auto_provisions_a_fresh_db(tmp_path, monkeypatch):
    """A brand-new db_path (no file at all) must be detected as unmigrated and auto-provisioned
    via `migrations.migrate.migrate()` -- OG-2's "no such table" crash, fixed at startup."""
    db_path = str(tmp_path / "fresh" / "papers.db")
    calls = []
    monkeypatch.setattr(ingest_mod, "migrate", lambda path: calls.append(path))

    ingest_mod._ensure_db_migrated(db_path)

    assert calls == [db_path]
    assert (tmp_path / "fresh").is_dir(), "parent directory must be auto-created"


def test_ensure_db_migrated_detects_unmigrated_db_via_missing_table(tmp_path, monkeypatch):
    """A file that exists but was never migrated (no `ingest_state` table) must also trigger
    auto-provisioning -- not just a wholly-absent file."""
    db_path = str(tmp_path / "papers.db")
    sqlite3.connect(db_path).close()  # file exists, zero tables
    calls = []
    monkeypatch.setattr(ingest_mod, "migrate", lambda path: calls.append(path))

    ingest_mod._ensure_db_migrated(db_path)

    assert calls == [db_path]


def test_ensure_db_migrated_is_a_noop_on_an_already_migrated_db(tmp_path, monkeypatch):
    """Calling this on every startup must never re-run `migrate()` against an already-migrated
    DB -- `migrate()` itself fails loudly (by design) on a second run, so this guard is what
    makes "call unconditionally every startup" safe."""
    db_path = str(tmp_path / "papers.db")
    real_migrate(db_path)  # real foundation-owned migrate() -- called, not edited
    calls = []
    monkeypatch.setattr(ingest_mod, "migrate", lambda path: calls.append(path))

    ingest_mod._ensure_db_migrated(db_path)  # must not raise, must not call migrate()

    assert calls == []


# --- T-DOC43: startup preflight gate ---------------------------------------------------------


def _cfg() -> Config:
    return Config(focus_area_queries=["causal inference"])


def test_preflight_gate_no_preflight_skips_the_check_entirely(monkeypatch):
    def _boom(cfg):
        raise AssertionError("run_preflight must not be called when --no-preflight is set")

    monkeypatch.setattr(doctor_mod, "run_preflight", _boom)

    ingest_mod._preflight_gate(_cfg(), no_preflight=True, force=False)  # must not raise


def test_preflight_gate_passes_silently_when_no_issues(monkeypatch):
    monkeypatch.setattr(doctor_mod, "run_preflight", lambda cfg: [])

    ingest_mod._preflight_gate(_cfg(), no_preflight=False, force=False)  # must not raise/exit


def test_preflight_gate_refuses_to_start_with_named_reason(monkeypatch, capsys):
    """T-DOC43: refuse to start with ONE clear message naming what's missing."""
    issue = doctor_mod.PreflightIssue("gpu", "only 100 MiB free VRAM (need >= 2000 MiB)")
    monkeypatch.setattr(doctor_mod, "run_preflight", lambda cfg: [issue])

    with pytest.raises(SystemExit) as exc_info:
        ingest_mod._preflight_gate(_cfg(), no_preflight=False, force=False)

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "only 100 MiB free VRAM" in captured.err


def test_preflight_gate_force_proceeds_despite_issues(monkeypatch, capsys):
    issue = doctor_mod.PreflightIssue("gpu_lock", ".gpu.lock is held by another live process")
    monkeypatch.setattr(doctor_mod, "run_preflight", lambda cfg: [issue])

    ingest_mod._preflight_gate(_cfg(), no_preflight=False, force=True)  # must not raise/exit

    captured = capsys.readouterr()
    assert "is held by another live process" in captured.err


# --- T-DOC45: --limit --------------------------------------------------------------------------


def _args(*, limit=None, scratch=False, paper_ids_file=None):
    return argparse.Namespace(limit=limit, scratch=scratch, paper_ids_file=paper_ids_file)


def test_effective_config_no_flags_returns_the_identical_config():
    cfg = _cfg()
    assert ingest_mod._effective_config(cfg, _args()) is cfg


def test_effective_config_limit_caps_corpus_cap():
    cfg = Config(focus_area_queries=["x"], corpus_cap=30_000)

    effective = ingest_mod._effective_config(cfg, _args(limit=100))

    assert effective.corpus_cap == 100


def test_effective_config_limit_never_raises_corpus_cap_above_the_configured_value():
    cfg = Config(focus_area_queries=["x"], corpus_cap=50)

    effective = ingest_mod._effective_config(cfg, _args(limit=99_999))

    assert effective.corpus_cap == 50


# --- T-DOC46: --scratch -------------------------------------------------------------------------


def test_effective_config_scratch_provisions_isolated_paths(capsys):
    cfg = _cfg()

    effective = ingest_mod._effective_config(cfg, _args(scratch=True))

    assert effective.db_path != cfg.db_path
    assert effective.blob_dir != cfg.blob_dir
    assert effective.collection != cfg.collection
    assert effective.db_path.endswith("papers.db")
    assert effective.collection.startswith("scratch_")
    # printed prominently so the operator can find/clean it up (T-DOC46)
    assert effective.db_path in capsys.readouterr().out


def test_effective_config_scratch_is_unique_per_call():
    cfg = _cfg()

    first = ingest_mod._effective_config(cfg, _args(scratch=True))
    second = ingest_mod._effective_config(cfg, _args(scratch=True))

    assert first.db_path != second.db_path
    assert first.collection != second.collection


def test_effective_config_scratch_and_limit_combine():
    cfg = Config(focus_area_queries=["x"], corpus_cap=30_000)

    effective = ingest_mod._effective_config(cfg, _args(scratch=True, limit=7))

    assert effective.db_path != cfg.db_path
    assert effective.corpus_cap == 7


# --- T-DOC45/T-DOC46: Pass-1 subprocess override channel -----------------------------------


def test_write_override_config_dir_resolves_relative_paths_to_absolute():
    cfg = Config(
        focus_area_queries=["x"],
        gpu_lock_path=".gpu.lock",
        db_path="papers.db",
        blob_dir="blobs",
        pdf_cache_dir="pdf_cache",
        batch_size_log_path="batch.csv",
    )

    tmpdir = ingest_mod._write_override_config_dir(cfg)
    written = yaml.safe_load((tmpdir / "config.yaml").read_text())

    for field in ("gpu_lock_path", "db_path", "blob_dir", "pdf_cache_dir", "batch_size_log_path"):
        assert ingest_mod.Path(written[field]).is_absolute(), f"{field} must be absolute"


def test_write_override_config_dir_leaves_falsy_path_fields_alone():
    """An explicitly-disabled pdf cache ("") or an unset batch_size_log_path (None) must stay
    exactly that, not get resolved into a bogus absolute path (app/assembly.py's own "" ==
    disabled convention)."""
    cfg = Config(focus_area_queries=["x"], pdf_cache_dir="", batch_size_log_path=None)

    tmpdir = ingest_mod._write_override_config_dir(cfg)
    written = yaml.safe_load((tmpdir / "config.yaml").read_text())

    assert written["pdf_cache_dir"] == ""
    assert written["batch_size_log_path"] is None


def test_write_override_config_dir_preserves_non_path_fields():
    cfg = Config(focus_area_queries=["x"], corpus_cap=42, collection="scratch_abc123")

    tmpdir = ingest_mod._write_override_config_dir(cfg)
    written = yaml.safe_load((tmpdir / "config.yaml").read_text())

    assert written["corpus_cap"] == 42
    assert written["collection"] == "scratch_abc123"
    assert written["focus_area_queries"] == ["x"]


# --- OG-49#2: whole-run lock resolves absolute against db_path's own directory -------------------


def test_ingest_lock_path_is_absolute_and_shared_across_configs_with_the_same_db_path(tmp_path):
    """OG-49#2: two independently-built effective Configs that both resolve to the SAME db_path
    (e.g. a dashboard override run's scratch-cwd config vs. another run's config) must compute the
    IDENTICAL absolute lock path -- not one relative to whatever cwd each process happens to
    launch with. The exact bug: every overridden run used to get its own throwaway `.ingest.lock`
    in its own scratch cwd, silently bypassing the double-run guard."""
    db_path = tmp_path / "data" / "papers.db"
    cfg_a = Config(focus_area_queries=["x"], db_path=str(db_path))
    # cfg_b: a differently-built Config, but the SAME db_path.
    cfg_b = Config(focus_area_queries=["x"], db_path=str(db_path), corpus_cap=99)

    lock_a = ingest_mod._ingest_lock_path(cfg_a)
    lock_b = ingest_mod._ingest_lock_path(cfg_b)

    assert lock_a == lock_b
    assert lock_a.is_absolute()
    assert lock_a == db_path.resolve().parent / ".ingest.lock"


def test_ingest_lock_path_resolves_a_relative_db_path_against_cwd(tmp_path, monkeypatch):
    """The common (unedited) case: `db_path` is relative ("papers.db", the Config default) --
    resolves the same way `sqlite3.connect(db_path)` itself would (against the process's cwd),
    consistent with where the DB actually ends up."""
    monkeypatch.chdir(tmp_path)
    cfg = Config(focus_area_queries=["x"])  # db_path default: "papers.db"

    lock_path = ingest_mod._ingest_lock_path(cfg)

    assert lock_path == tmp_path / ".ingest.lock"


def test_ingest_lock_path_differs_for_different_db_paths():
    """A --scratch run (its own unique db_path every time) must NOT share a lock with anything
    else -- it never shares a corpus, so it must never contend for someone else's lock either."""
    cfg_a = Config(focus_area_queries=["x"], db_path="/tmp/scratch-a/papers.db")
    cfg_b = Config(focus_area_queries=["x"], db_path="/tmp/scratch-b/papers.db")

    assert ingest_mod._ingest_lock_path(cfg_a) != ingest_mod._ingest_lock_path(cfg_b)


# --- OG-49#3: --parse-workers < 1 rejected before the lock is even considered --------------------


def test_validate_parse_workers_zero_exits_with_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        ingest_mod._validate_parse_workers(0)
    assert exc_info.value.code == 1
    assert "--parse-workers must be >= 1" in capsys.readouterr().err


def test_validate_parse_workers_negative_exits_with_error():
    with pytest.raises(SystemExit):
        ingest_mod._validate_parse_workers(-5)


def test_validate_parse_workers_one_is_accepted():
    ingest_mod._validate_parse_workers(1)  # must not raise/exit


def test_effective_config_re_validates_and_rejects_a_bad_override():
    # OG-49#6/M8: _effective_config's own model_copy(update=...) must be re-validated -- a
    # corpus_cap <= 0 (contracts/config.py: `Field(gt=0)`) must raise, not silently build an
    # invalid Config that only fails later, deep in the pipeline.
    cfg = Config(focus_area_queries=["x"], corpus_cap=30_000)
    bad_args = _args(limit=0)  # min(30_000, 0) -> corpus_cap=0, violates gt=0

    with pytest.raises(Exception):  # pydantic.ValidationError
        ingest_mod._effective_config(cfg, bad_args)
