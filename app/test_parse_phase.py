"""Tests for `app.parse_phase` (T-DOC29) -- offline, no real subprocess/GPU/network.

`_run_parse_phase` was pulled out of `__main__` (same pattern as `app/test_ingest.py`'s
`_run_finish_phase` tests) specifically so these two real, previously-`os.environ`-backed
branches can be driven directly:

1. `cfg.db_path`/`cfg.blob_dir`/`cfg.collection` (now real `Config` fields) must reach
   `build_ingestion_orchestrator` unchanged.
2. `cfg.ingest_paper_ids` (also now a real `Config` field) must route through
   `app.assembly.harvest_refs`'s `ArxivSource.fetch_by_ids` branch instead of the default
   query-driven `harvest()` -- and when unset, `harvest()` must still be used, unchanged.
"""

from contracts.config import Config
from contracts.harvester import PaperRef

from app.parse_phase import _run_parse_phase


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
    `os.environ` reads) must be forwarded to `build_ingestion_orchestrator` exactly."""
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
