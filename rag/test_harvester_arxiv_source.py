"""Offline unit tests for `ArxivSource` (T-A1) — feeds a canned arXiv Atom feed string through
`_parse_entries`/`_entry_to_ref` directly, no network call. `Harvester`'s own dormant suite
(`rag/test_harvester.py`) covers dedup/resume/retry/quarantine against `FakeSource`; this file
covers only the vendor-specific parsing `ArxivSource` hides (CONVENTIONS.md §1).
"""

import httpx
import pytest

from contracts.errors import PermanentError
from rag.harvester import ArxivSource

_ATOM_ENTRY = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2504.09999v2</id>
    <published>2026-04-15T00:00:00Z</published>
    <updated>2026-04-20T00:00:00Z</updated>
    <title>  Representation Learning
      for Causal Inference  </title>
    <summary>We study causal representation
      learning.</summary>
    <author><name>D. Author</name></author>
    <author><name>E. Author</name></author>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

_EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def make_source(**kw):
    kw.setdefault("sleep", lambda _seconds: None)
    return ArxivSource(**kw)


def test_parses_id_into_base_paper_id_and_version():
    refs = make_source()._parse_entries(_ATOM_ENTRY)
    assert len(refs) == 1
    ref = refs[0]
    assert ref.paper_id == "2504.09999"
    assert ref.version == "v2"


def test_parses_title_and_abstract_collapsing_whitespace():
    ref = make_source()._parse_entries(_ATOM_ENTRY)[0]
    assert ref.title == "Representation Learning for Causal Inference"
    assert ref.abstract == "We study causal representation learning."


def test_parses_authors_and_categories():
    ref = make_source()._parse_entries(_ATOM_ENTRY)[0]
    assert ref.authors == ["D. Author", "E. Author"]
    assert ref.categories == ["cs.CL", "cs.LG"]


def test_parses_dates():
    ref = make_source()._parse_entries(_ATOM_ENTRY)[0]
    assert ref.published.isoformat() == "2026-04-15"
    assert ref.updated.isoformat() == "2026-04-20"


def test_derives_pdf_and_latex_urls_from_the_versioned_id():
    ref = make_source()._parse_entries(_ATOM_ENTRY)[0]
    assert ref.pdf_url == "https://arxiv.org/pdf/2504.09999v2"
    assert ref.latex_url == "https://arxiv.org/e-print/2504.09999v2"


def test_empty_feed_parses_to_no_entries():
    assert make_source()._parse_entries(_EMPTY_FEED) == []


def test_malformed_xml_raises_permanent_error():
    with pytest.raises(PermanentError):
        make_source()._parse_entries("not xml")


def test_unsupported_ordering_raises_permanent_error():
    with pytest.raises(PermanentError):
        list(make_source().fetch(["x"], cap=10, ordering="oldest_first"))


def test_fetch_paginates_until_cap_reached(monkeypatch):
    # Two pages of one entry each, from a fake transport (no real network) — proves fetch()
    # advances `start` and stops once `cap` is reached without a third request.
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        start = int(request.url.params["start"])
        entry_id = f"2504.0999{start}v1"
        body = _ATOM_ENTRY.replace("2504.09999v2", entry_id)
        return httpx.Response(200, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=1)
    refs = list(source.fetch(["causal inference"], cap=2, ordering="freshest_first"))
    assert len(refs) == 2
    assert len(calls) == 2
    assert calls[0]["start"] == "0"
    assert calls[1]["start"] == "1"


def test_fetch_stops_when_a_page_comes_back_empty(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    assert list(source.fetch(["x"], cap=100, ordering="freshest_first")) == []
