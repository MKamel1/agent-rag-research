"""Offline unit tests for `ArxivSource` (T-A1) — feeds a canned arXiv Atom feed string through
`_parse_entries`/`_entry_to_ref` directly, no network call. `Harvester`'s own dormant suite
(`rag/test_harvester.py`) covers dedup/resume/retry/quarantine against `FakeSource`; this file
covers only the vendor-specific parsing `ArxivSource` hides (CONVENTIONS.md §1).
"""

import re
import time
from datetime import date
from pathlib import Path

import httpx
import pytest

from contracts.errors import PermanentError, TransientError
from rag.config import load_config
from rag.harvester import ArxivSource

REAL_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

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


# --- T-DOC8: one request per focus_area entry, not one combined boolean-OR query -----------------
# (root cause: a real ~1,100-char " OR "-joined query is genuinely unreliable at any timeout, see
# harvester.py's `fetch()` docstring for the real measured numbers.)


def test_fetch_issues_one_query_per_focus_area_entry_not_one_combined_query():
    queries_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["search_query"])
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    list(
        source.fetch(["causal inference", "causal discovery"], cap=100, ordering="freshest_first")
    )
    # Each entry gets its own quoted `all:"<term>"` query -- never the old " OR "-joined megastring.
    assert queries_seen == ['all:"causal inference"', 'all:"causal discovery"']


# --- T-DOC11: quote multi-word terms so arXiv doesn't silently OR-split them ------------------
# (root cause: a real 250-paper ingest run found `all:causal inference` unquoted matches arXiv's
# search API as `causal OR inference` -- e.g. also matching a paper that only says "inference",
# with no real conceptual connection to the focus area.)


def test_multi_word_term_is_sent_as_a_quoted_phrase():
    queries_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["search_query"])
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    list(source.fetch(["causal inference"], cap=100, ordering="freshest_first"))
    # Quoted -> exact-phrase match, not a bare-words string arXiv would OR-split.
    assert queries_seen == ['all:"causal inference"']


def test_single_word_term_is_quoted_too():
    # Quoting a plain single word is a documented no-op on arXiv's side -- always quoting (rather
    # than branching on whether the term "looks like" multiple words) means the fix doesn't have
    # to correctly guess every separator arXiv's tokenizer splits on. See the hyphenated-term test
    # below for a real config.yaml term that a naive `" " in term` check would have missed.
    queries_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["search_query"])
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    list(source.fetch(["discovery"], cap=100, ordering="freshest_first"))
    assert queries_seen == ['all:"discovery"']


def test_hyphenated_single_token_term_is_quoted():
    # Real regression: config.yaml's "difference-in-differences" has no space, but arXiv's
    # tokenizer OR-splits on the hyphen too (verified live against export.arxiv.org) -- a
    # `" " in term` check would have missed this real, currently-shipping focus_area_queries
    # entry. Always-quote (no substring heuristic) covers it without needing to know arXiv's
    # tokenization rules.
    queries_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["search_query"])
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    list(source.fetch(["difference-in-differences"], cap=100, ordering="freshest_first"))
    assert queries_seen == ['all:"difference-in-differences"']


def test_every_configured_focus_area_query_is_quoted():
    # Derived from the actual config.yaml contents rather than hand-picked example terms -- this
    # is what would have caught the hyphenated-term gap above before it shipped.
    terms = load_config(REAL_CONFIG_PATH).focus_area_queries
    assert terms, "config.yaml's focus_area_queries is empty -- nothing to check"

    queries_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries_seen.append(request.url.params["search_query"])
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    list(source.fetch(terms, cap=len(terms) * 100, ordering="freshest_first"))
    assert queries_seen == [f'all:"{term}"' for term in terms]


def test_fetch_shares_one_cap_budget_across_focus_area_entries():
    # cap is a total budget across the whole focus_area list, not per-entry -- otherwise 33
    # entries at corpus_cap=15000 each would massively over-fetch.
    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        entry_id = f"2504.0999{start}v1"
        body = _ATOM_ENTRY.replace("2504.09999v2", entry_id)
        return httpx.Response(200, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=1)
    refs = list(source.fetch(["term-a", "term-b", "term-c"], cap=2, ordering="freshest_first"))
    assert len(refs) == 2  # stops at the shared cap, never reaches term-c


def test_fetch_moves_to_the_next_focus_area_entry_when_one_is_exhausted():
    # term-a comes back empty immediately; term-b then contributes one page (its second page is
    # empty, same as any real exhausted term) -- proves fetch() doesn't stop early just because
    # one entry has no matches.
    term_b_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["search_query"]
        if query == 'all:"term-a"':
            return httpx.Response(200, text=_EMPTY_FEED)
        term_b_calls.append(request.url.params["start"])
        if len(term_b_calls) == 1:
            return httpx.Response(200, text=_ATOM_ENTRY)
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, page_size=10)
    refs = list(source.fetch(["term-a", "term-b"], cap=100, ordering="freshest_first"))
    assert len(refs) == 1
    assert refs[0].paper_id == "2504.09999"


def test_fetch_applies_rate_limit_sleep_between_requests_across_focus_area_entries():
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = ArxivSource(client=client, sleep=lambda s: sleeps.append(s), page_size=10)
    list(source.fetch(["term-a", "term-b", "term-c"], cap=100, ordering="freshest_first"))
    # 3 requests total (one per term, each exhausted on its first empty page) -> 2 sleeps; never
    # sleeps before the very first request of the whole fetch().
    assert sleeps == [3.0, 3.0]


@pytest.mark.real_adapter  # hits the real export.arxiv.org API — never run by default
def test_real_arxiv_api_returns_one_well_formed_paper_ref():
    """Never exercised against the actual vendor before now -- only the canned Atom feed above.
    Capped at one result via a narrow query so this stays fast and doesn't hammer arXiv's API."""
    source = ArxivSource()
    try:
        refs = list(source.fetch(["causal inference"], cap=1, ordering="freshest_first"))
    except TransientError as e:
        pytest.skip(f"arXiv API not reachable: {e}")

    assert len(refs) == 1
    ref = refs[0]
    assert re.fullmatch(r"\d{4}\.\d{4,5}", ref.paper_id), ref.paper_id
    assert ref.title.strip()
    assert isinstance(ref.published, date)
    assert ref.pdf_url.startswith("https://arxiv.org/pdf/")


@pytest.mark.real_adapter  # hits the real export.arxiv.org API — never run by default
def test_real_arxiv_api_quoted_multi_word_term_does_not_or_split():
    """T-DOC11 regression: a real 250-paper ingest run found arXiv's search API silently treats
    an unquoted `all:causal inference` as `causal OR inference`, matching papers that contain
    only one of the two words with no real conceptual connection to the focus area (confirmed
    live: unquoted + freshest-first pulled supernovae-kinematics and quantum-many-body papers
    into a "causal inference" query). Quoting forces an exact-phrase match -- assert every
    result's title+abstract actually contains the phrase "causal inference", not just one word.
    """
    time.sleep(3)  # space out from the real call the previous test just made -- avoid 429s
    source = ArxivSource()
    try:
        refs = list(source.fetch(["causal inference"], cap=5, ordering="freshest_first"))
    except TransientError as e:
        pytest.skip(f"arXiv API not reachable: {e}")

    assert refs, "expected at least one real result for a quoted-phrase query"
    for ref in refs:
        text = f"{ref.title} {ref.abstract}".lower()
        assert "causal" in text and "inference" in text, (
            f"{ref.paper_id!r} matched without the actual phrase -- OR-split regressed: "
            f"{ref.title!r}"
        )


# --- fetch_by_ids: fetch specific known papers by id, not a query-driven search -----------------


def test_fetch_by_ids_uses_id_list_param_not_search_query():
    params_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        params_seen.append(dict(request.url.params))
        return httpx.Response(200, text=_ATOM_ENTRY)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client)
    source.fetch_by_ids(["2504.09999"])
    assert params_seen[0]["id_list"] == "2504.09999"
    assert "search_query" not in params_seen[0]


def test_fetch_by_ids_returns_parsed_refs():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=_ATOM_ENTRY)))
    source = make_source(client=client)
    refs = source.fetch_by_ids(["2504.09999"])
    assert len(refs) == 1
    assert refs[0].paper_id == "2504.09999"


def test_fetch_by_ids_chunks_large_id_lists_and_rate_limits_between_chunks():
    calls = []
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["id_list"])
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client, sleep=sleeps.append)
    ids = [f"2504.{i:05d}" for i in range(120)]  # 3 chunks at _ID_LIST_CHUNK_SIZE=50
    source.fetch_by_ids(ids)
    assert len(calls) == 3
    assert calls[0].count(",") == 49  # 50 ids in the first chunk
    assert calls[2].count(",") == 19  # remaining 20 ids in the last chunk
    assert sleeps == [3.0, 3.0], "rate-limit sleep between chunks, not before the first one"


def test_fetch_by_ids_empty_list_makes_no_requests():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text=_EMPTY_FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = make_source(client=client)
    assert source.fetch_by_ids([]) == []
    assert calls == []


def test_fetch_by_ids_maps_retryable_status_to_transient_error():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    source = make_source(client=client)
    with pytest.raises(TransientError):
        source.fetch_by_ids(["2504.09999"])


def test_fetch_by_ids_429_diagnostics_carries_the_retry_after_header():
    """T-DOC58: a caller with its own retry loop (app/assembly.py's `_fetch_by_ids_with_backoff`)
    reads `Retry-After` off `TransientError.diagnostics["retry_after"]` -- the opportunistic
    convention contracts/errors.py already documents (T-DOC17), not a new field on the frozen
    taxonomy."""
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "42"}))
    )
    source = make_source(client=client)
    with pytest.raises(TransientError) as excinfo:
        source.fetch_by_ids(["2504.09999"])
    assert excinfo.value.diagnostics == {"retry_after": "42"}


def test_fetch_by_ids_429_diagnostics_retry_after_absent_is_none():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    source = make_source(client=client)
    with pytest.raises(TransientError) as excinfo:
        source.fetch_by_ids(["2504.09999"])
    assert excinfo.value.diagnostics == {"retry_after": None}


def test_fetch_by_ids_maps_other_status_to_permanent_error():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    source = make_source(client=client)
    with pytest.raises(PermanentError):
        source.fetch_by_ids(["2504.09999"])


@pytest.mark.real_adapter  # hits the real export.arxiv.org API — never run by default
def test_real_arxiv_api_fetch_by_ids_returns_the_exact_requested_papers():
    time.sleep(3)  # space out from other real-adapter tests in this file
    source = ArxivSource()
    try:
        refs = source.fetch_by_ids(["2409.01266", "2409.02332"])
    except TransientError as e:
        pytest.skip(f"arXiv API not reachable: {e}")

    assert {r.paper_id for r in refs} == {"2409.01266", "2409.02332"}
