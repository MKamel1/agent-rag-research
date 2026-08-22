"""Tests for `app.parse_phase` (T-DOC29) -- offline, no real subprocess/GPU/network.

`_run_parse_phase` was pulled out of `__main__` (same pattern as `app/test_ingest.py`'s
`_run_finish_phase` tests) specifically so these two real, previously process-environment-backed
branches can be driven directly:

1. `cfg.db_path`/`cfg.blob_dir`/`cfg.collection` (now real `Config` fields) must reach
   `build_ingestion_orchestrator` unchanged.
2. `cfg.ingest_paper_ids` (also now a real `Config` field) must route through
   `app.assembly.harvest_refs`'s `ArxivSource.fetch_by_ids` branch instead of the default
   query-driven `harvest()` -- and when unset, `harvest()` must still be used, unchanged.
"""

from app.parse_phase import _run_parse_phase, _shard
from contracts.config import Config
from contracts.harvester import PaperRef


class FakeOrchestrator:
    def __init__(self, refs_to_return: list[PaperRef]):
        self._refs_to_return = refs_to_return
        self.harvest_calls: list[tuple[list[str], int]] = []
        self.parse_phase_calls: list[list[PaperRef]] = []

    def harvest(self, focus_area_queries: list[str], cap: int) -> list[PaperRef]:
        self.harvest_calls.append((focus_area_queries, cap))
        return self._refs_to_return

    def parse_phase(self, refs: list[PaperRef]) -> None:
        self.parse_phase_calls.append(refs)


def _make_ref(paper_id: str) -> PaperRef:
    from datetime import date

    return PaperRef(
        paper_id=paper_id, version="v1", title="t", abstract="a", authors=["A"],
        categories=["cs.LG"], published=date(2026, 1, 1), updated=date(2026, 1, 1),
        pdf_url=f"https://arxiv.example/pdf/{paper_id}v1",
    )


def test_run_parse_phase_wires_db_path_blob_dir_collection_from_config(monkeypatch, tmp_path):
    """`cfg.db_path`/`cfg.blob_dir`/`cfg.collection` (T-DOC29: real Config fields, not
    process-environment reads) must be forwarded to `build_ingestion_orchestrator` exactly."""
    captured_kwargs = {}
    fake_orchestrator = FakeOrchestrator(refs_to_return=[])

    def fake_build(cfg, *, db_path=None, blob_dir=None, collection="papers"):
        captured_kwargs["db_path"] = db_path
        captured_kwargs["blob_dir"] = blob_dir
        captured_kwargs["collection"] = collection
        return fake_orchestrator

    monkeypatch.setattr("app.parse_phase.build_ingestion_orchestrator", fake_build)

    cfg = Config(
        focus_area_queries=["causal inference"],
        db_path=str(tmp_path / "custom.db"),
        blob_dir=str(tmp_path / "custom_blobs"),
        collection="custom_collection",
    )
    _run_parse_phase(cfg)

    assert captured_kwargs == {
        "db_path": str(tmp_path / "custom.db"),
        "blob_dir": str(tmp_path / "custom_blobs"),
        "collection": "custom_collection",
    }
    assert fake_orchestrator.parse_phase_calls == [[]]


def test_run_parse_phase_uses_query_harvest_when_ingest_paper_ids_unset(monkeypatch):
    """Default behavior (`cfg.ingest_paper_ids` unset) must be completely unchanged: the
    query-driven `harvest(focus_area_queries, corpus_cap)` path, not `fetch_by_ids`."""
    ref = _make_ref("2601.00001")
    fake_orchestrator = FakeOrchestrator(refs_to_return=[ref])
    monkeypatch.setattr(
        "app.parse_phase.build_ingestion_orchestrator", lambda *a, **k: fake_orchestrator
    )

    def _boom(*a, **k):
        raise AssertionError("ArxivSource.fetch_by_ids must not be called when unset")

    monkeypatch.setattr("app.assembly.ArxivSource", _boom)

    cfg = Config(focus_area_queries=["causal inference"], corpus_cap=7)
    _run_parse_phase(cfg)

    assert fake_orchestrator.harvest_calls == [(["causal inference"], 7)]
    assert fake_orchestrator.parse_phase_calls == [[ref]]


def test_run_parse_phase_uses_fetch_by_ids_when_ingest_paper_ids_set(monkeypatch):
    """`cfg.ingest_paper_ids` (T-EVAL harvest-scoping override, T-DOC29: now a real Config field
    instead of a comma-separated `RAG_INGEST_PAPER_IDS` env var) must route through
    `ArxivSource.fetch_by_ids` instead of the default query-driven `harvest()`."""
    ref = _make_ref("2601.00099")
    fake_orchestrator = FakeOrchestrator(refs_to_return=[])
    monkeypatch.setattr(
        "app.parse_phase.build_ingestion_orchestrator", lambda *a, **k: fake_orchestrator
    )

    fetch_calls = []

    class FakeArxivSource:
        def fetch_by_ids(self, ids: list[str]) -> list[PaperRef]:
            fetch_calls.append(ids)
            return [ref]

    monkeypatch.setattr("app.assembly.ArxivSource", FakeArxivSource)

    cfg = Config(focus_area_queries=["causal inference"], ingest_paper_ids=["2601.00099"])
    _run_parse_phase(cfg)

    assert fetch_calls == [["2601.00099"]]
    assert fake_orchestrator.harvest_calls == [], "harvest() must not be called when ids are set"
    assert fake_orchestrator.parse_phase_calls == [[ref]]


# --- T-DOC51: sharded N-worker parallel Pass 1 ---------------------------------------------


def test_shard_default_reproduces_todays_single_worker_behavior():
    """shard_index=0, shard_count=1 (the argparse defaults) must return every ref, unchanged --
    `--parse-workers 1` (the `app.ingest` default) must be byte-for-byte today's behavior."""
    refs = [_make_ref(f"2601.{i:05d}") for i in range(7)]
    assert _shard(refs, 0, 1) == refs


def test_shard_is_disjoint_and_complete():
    """The property that makes N concurrent workers safe to share one `papers.db` (T-DOC51,
    `rag/ingest_state_sqlite.py`'s "Cross-PROCESS safety" docstring): every ref lands in exactly
    one shard. Union of all N shards must equal the original set; pairwise intersections must be
    empty."""
    refs = [_make_ref(f"2601.{i:05d}") for i in range(17)]  # prime-ish, doesn't divide evenly
    shard_count = 4
    shards = [_shard(refs, i, shard_count) for i in range(shard_count)]

    union: list[PaperRef] = []
    for shard in shards:
        union.extend(shard)
    assert sorted(r.paper_id for r in union) == sorted(r.paper_id for r in refs), (
        "union of all shards must equal the original ref set (complete)"
    )

    ids_per_shard = [{r.paper_id for r in shard} for shard in shards]
    for a in range(shard_count):
        for b in range(a + 1, shard_count):
            assert ids_per_shard[a].isdisjoint(ids_per_shard[b]), (
                f"shard {a} and shard {b} overlap -- two workers would touch the same paper_id"
            )


def test_shard_same_paper_same_shard_when_two_workers_harvest_lists_diverge():
    """RI-22: each of N workers re-harvests independently, and the two lists are NOT guaranteed
    to agree -- a query-driven harvest paginates the source for many minutes at the shipped
    `corpus_cap`, and under `freshest_first` one new submission between worker W0's page-k fetch
    and worker W1's page-k fetch inserts at rank 0 and shifts every later position by one.
    Positional slicing (`refs[i::n]`) then hands the same paper to two workers -- concurrent
    dual-writer access to `ingest_state` from separate OS processes, plus up to ~2x the GPU work.
    Shard membership must therefore be identity-stable: the same paper_id lands in the same shard
    from either worker's list even when the lists differ."""
    base = [_make_ref(f"2601.{i:05d}") for i in range(17)]
    diverged = [_make_ref("2601.99999")] + base  # one new submission landed at rank 0
    shard_count = 4

    def _assignments(refs: list[PaperRef]) -> dict[str, int]:
        return {
            r.paper_id: i for i in range(shard_count) for r in _shard(refs, i, shard_count)
        }

    base_assignment = _assignments(base)
    diverged_assignment = _assignments(diverged)

    for paper_id, shard_index in base_assignment.items():
        assert diverged_assignment[paper_id] == shard_index, (
            f"{paper_id} moved from shard {shard_index} to shard "
            f"{diverged_assignment[paper_id]} when one ref was prepended -- a second worker "
            f"would parse it again, concurrently"
        )


def test_shard_membership_depends_only_on_paper_id_not_list_position():
    """RI-22 replaces the stride slice (`refs[i::n]`) with identity-stable hash partitioning:
    which shard a paper belongs to is a function of its paper_id alone, so no reordering of the
    harvested list -- not a prepend, not a full reversal -- can reassign papers between workers.
    (The test this replaces pinned the stride slice's exact positional membership, i.e. the
    mechanism the fix removes.)"""
    refs = [_make_ref(f"2601.{i:05d}") for i in range(6)]
    forward = [{r.paper_id for r in _shard(refs, i, 3)} for i in range(3)]
    backward = [{r.paper_id for r in _shard(list(reversed(refs)), i, 3)} for i in range(3)]
    assert forward == backward


def test_run_parse_phase_logs_resolved_paths(monkeypatch, tmp_path, caplog):
    # T-DOC89 §4: `cfg` here is already this subprocess's own final config -- see the module
    # docstring note added alongside the log line for why nothing further overrides it.
    fake_orchestrator = FakeOrchestrator(refs_to_return=[])
    monkeypatch.setattr(
        "app.parse_phase.build_ingestion_orchestrator", lambda *a, **k: fake_orchestrator
    )
    cfg = Config(
        focus_area_queries=["causal inference"],
        db_path=str(tmp_path / "papers.db"), blob_dir=str(tmp_path / "blobs"),
        collection="papers",
    )
    caplog.set_level("INFO")

    _run_parse_phase(cfg)

    assert f"db_path={cfg.db_path}" in caplog.text
    assert f"blob_dir={cfg.blob_dir}" in caplog.text
    assert f"collection={cfg.collection}" in caplog.text


def test_run_parse_phase_applies_shard_before_calling_parse_phase(monkeypatch):
    """`_run_parse_phase`'s optional `shard_index`/`shard_count` kwargs must select this worker's
    identity-stable slice of the harvested refs before `orchestrator.parse_phase()` is called --
    not pass the full list through. The expected ids are the sha256-assigned members of shard 1
    of 2 for this id list; sha256 is stable across processes, so the pin is deterministic (a
    builtin-`hash()` implementation would make it vary run to run -- see `_shard`)."""
    refs = [_make_ref(f"2601.{i:05d}") for i in range(4)]
    fake_orchestrator = FakeOrchestrator(refs_to_return=refs)
    monkeypatch.setattr(
        "app.parse_phase.build_ingestion_orchestrator", lambda *a, **k: fake_orchestrator
    )

    cfg = Config(focus_area_queries=["causal inference"])
    _run_parse_phase(cfg, shard_index=1, shard_count=2)

    assert [r.paper_id for r in fake_orchestrator.parse_phase_calls[0]] == [
        "2601.00000", "2601.00002",
    ]
