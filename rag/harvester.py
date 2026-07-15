"""M1 Harvester (ARCHITECTURE.md "M1 · Harvester", owner A).

`Harvester.harvest(focus_area, cap, ordering) -> Iterator[PaperRef]` wraps an injected `Source`
(the "Seam: `Source` (arXiv adapter)" ARCHITECTURE.md names but does not pin the shape of — the
shape used here is the one `rag/fakes/fake_source.py` and `rag/test_harvester.py` already
committed: `source.fetch(focus_area, cap, ordering) -> Iterator[PaperRef]`) and adds the four
things ARCHITECTURE.md says this module hides: dedup by base `paper_id` (latest version wins),
resume (skip ids already seen in a prior run), and turning a `Source` failure into either a
retried attempt or a quarantined-and-continue outcome (CONVENTIONS.md §4/§5).

`ArxivSource` is the one real `Source` — the arXiv API client CONVENTIONS.md §1 restricts to this
file. It is a thin, swappable adapter: `Harvester` never imports `httpx` or knows arXiv's Atom
feed shape; only `ArxivSource` does.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime

import httpx

from contracts.errors import PermanentError, TransientError
from contracts.harvester import PaperRef

# --------------------------------------------------------------------------------------------
# Harvester — dedup / resume / retry, source-agnostic.
# --------------------------------------------------------------------------------------------

QuarantineSink = Callable[[str, Exception], None]
RetrySleep = Callable[[float], None]

# `FakeSource` (and any well-behaved `Source`) names the paper_id it's failing on in its raised
# error's message as `paper_id=<repr>` (see rag/fakes/fake_source.py's `_as_exception`) — this is
# the only channel a `Source.fetch()` failure has to say *which* paper it choked on, since the
# failing `PaperRef` itself is (by construction) never yielded. Documented convention, not a
# coincidental scrape (CONVENTIONS.md §8): `ArxivSource` below follows the identical convention
# for its own per-entry failures, so this extraction works for both the fake and the real source.
_PAPER_ID_IN_MESSAGE = re.compile(r"paper_id=(['\"]?)(?P<id>[^'\"\s]+)\1")


def _paper_id_from_error(error: Exception) -> str:
    match = _PAPER_ID_IN_MESSAGE.search(str(error))
    return match.group("id") if match else "<unknown>"


def _version_num(version: str) -> int:
    # `version` is "v1", "v2", ... "v10", ... — compare the integer, not the string
    # ("v9" > "v10" lexically, which would keep the older version for 10+-version papers).
    return int(version.lstrip("v"))


def _default_retry_sleep(seconds: float) -> None:
    time.sleep(seconds)


class Harvester:
    """Preconditions: `cap >= 0`; `ordering` is whatever the injected `source` accepts (V0: only
    `"freshest_first"`, DATA-CONTRACTS.md §Config). Postcondition: `harvest()` yields at most one
    `PaperRef` per distinct base `paper_id` (the latest `version` seen), never one already in
    `seen_ids`, and never raises — a `Source` failure is either retried (`TransientError`, up to
    `max_retries` times, with `retry_sleep` backoff between attempts) or quarantined
    (`PermanentError`, or a `TransientError` whose retry budget is exhausted) via the injected
    `quarantine` sink, and the run finishes with whatever was collected before the failure
    (CONVENTIONS.md §4 "quarantine and continue... never kills the run").
    """

    def __init__(
        self,
        source,
        *,
        seen_ids: Iterable[str] = (),
        quarantine: QuarantineSink | None = None,
        max_retries: int = 2,
        retry_sleep: RetrySleep | None = None,
    ):
        self._source = source
        self._seen_ids = set(seen_ids)
        self._quarantine = quarantine or (lambda paper_id, error: None)
        self._max_retries = max_retries
        self._retry_sleep = retry_sleep or _default_retry_sleep

    def harvest(self, focus_area: list[str], cap: int, ordering: str) -> Iterator[PaperRef]:
        # ponytail ceiling: `seen_ids`/`cap` are post-fetch filters, not fetch cursors — a resume
        # still re-fetches every page from `source` and discards most of it, and `cap` counts raw
        # refs (pre-dedup, so a paper with 5 versions costs 5 of the cap) rather than distinct
        # papers returned. Fine for a one-shot V0 seed at current scale; revisit if resume cost or
        # cap accuracy ever matters (real fetch cursor / dedup-aware cap).
        latest: dict[str, PaperRef] = {}
        retry_counts: dict[str, int] = {}

        while True:
            try:
                for ref in self._source.fetch(focus_area, cap, ordering):
                    prev = latest.get(ref.paper_id)
                    if prev is None or _version_num(ref.version) > _version_num(prev.version):
                        latest[ref.paper_id] = ref
                break  # this attempt reached the end of the source without error
            except PermanentError as error:
                # This paper is unusable — quarantine it and stop; whatever was collected before
                # it (earlier refs already merged into `latest`) is still delivered below.
                self._quarantine(_paper_id_from_error(error), error)
                break
            except TransientError as error:
                # ceiling: this retry/quarantine model is per-paper by contract (it recovers
                # "which paper failed" from `paper_id=...` in the error text), but the real
                # `ArxivSource` below fails per-STREAM — a page-fetch error carries no paper_id,
                # so at runtime every transient error lands in one `"<unknown>"` bucket here. That
                # means: (a) a transient error restarts the WHOLE fetch from page 0 next attempt
                # (costly at the 15k-paper M4 scale), (b) `max_retries` is effectively a global
                # per-run budget rather than per-paper, and (c) exhausting it quarantines
                # `"<unknown>"` and `harvest()` ends early with a partial corpus, silently. Not
                # fixed here — out of scope for this change. If the M4 15k-paper run shows this
                # biting, follow up with a resume-cursor / per-page retry redesign.
                paper_id = _paper_id_from_error(error)
                retry_counts[paper_id] = retry_counts.get(paper_id, 0) + 1
                if retry_counts[paper_id] > self._max_retries:
                    self._quarantine(paper_id, error)
                    break
                self._retry_sleep(self._backoff(retry_counts[paper_id]))
                continue  # re-call source.fetch() from scratch (its own retry contract)

        for paper_id, ref in latest.items():
            if paper_id not in self._seen_ids:
                yield ref

    @staticmethod
    def _backoff(attempt: int) -> float:
        # Simple exponential backoff (1s, 2s, 4s, ...) — the exact curve doesn't matter, only
        # that `retry_sleep` is applied at all (a test asserts backoff was applied, not its shape;
        # `retry_sleep` is always injected as a no-op in tests, so this never really sleeps there).
        return float(2 ** (attempt - 1))


# --------------------------------------------------------------------------------------------
# ArxivSource — the real `Source` adapter. Only file allowed to import `httpx` for arXiv access
# (CONVENTIONS.md §1) / to know the arXiv Atom feed shape.
# --------------------------------------------------------------------------------------------

_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_API_URL = "https://export.arxiv.org/api/query"
_DEFAULT_PAGE_SIZE = 100
# arXiv's API usage policy asks for no more than one request every 3 seconds.
_RATE_LIMIT_SECONDS = 3.0
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
# Conservative chunk size for `fetch_by_ids`' `id_list` param -- verified working with a real
# 2-id request; arXiv doesn't publish a hard id_list length limit, so this stays well under any
# plausible URL-length ceiling rather than testing the edge live against a real service.
_ID_LIST_CHUNK_SIZE = 50


class ArxivSource:
    """Real `Source`: paginates https://export.arxiv.org/api/query (Atom feed) via `httpx`.

    Constructor-injectable (an `httpx.Client` and the rate-limit sleep hook), so it is itself
    unit-testable offline by feeding a canned Atom response through `_parse_entries` — see
    `rag/test_harvester_arxiv_source.py`. `Harvester` never imports this class's vendor
    dependency; a caller wires `Harvester(ArxivSource(), ...)` at the composition root.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ):
        self._client = client or httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._page_size = page_size

    def fetch(self, focus_area: list[str], cap: int, ordering: str) -> Iterator[PaperRef]:
        """Precondition: `ordering == "freshest_first"` (V0's only supported ordering,
        DATA-CONTRACTS.md §Config) -> anything else is a caller bug, `PermanentError`.

        Issues one paginated request **per `focus_area` entry** rather than combining all of
        them into a single `" OR "`-joined query — see the real numbers below. `cap` is one
        budget shared across the whole `focus_area` list (unchanged external contract: still
        counts raw refs pre-dedup, same as before this split existed); once it's hit, later
        `focus_area` entries are skipped. `Harvester.harvest()` merges/dedupes whatever this
        yields by base paper_id exactly as it already did, so nothing upstream changes.

        Why split (T-DOC8, real measured numbers, not a guess): V0's `config.yaml` ships 33
        `focus_area_queries`; the old code joined them into one ~1,100-char boolean-OR query.
        Root-cause testing found that single query gets a genuine `httpx.ReadTimeout` at 30s on
        a clean call. Raising the timeout doesn't fix it either: 4 further real attempts against
        that exact combined query (this ticket, 2026-07-13/14), spaced minutes apart with a
        120s timeout, got zero real responses -- every attempt came back `HTTP 429 "Rate
        exceeded"`, arriving anywhere from 0.27s to 46s later (never a timeout, never a 200). A
        single-term query (`all:causal inference`, `all:test`), by contrast, succeeds instantly
        when not caught by that same rate limiter. The giant combined query is the actual
        problem; a bigger timeout has nothing to wait out.
        """
        if ordering != "freshest_first":
            raise PermanentError(f"ArxivSource: unsupported ordering={ordering!r}")

        yielded = 0
        first_request = True
        for term in focus_area:
            if yielded >= cap:
                return
            # arXiv's search API silently OR-splits an unquoted multi-word term (e.g. `all:causal
            # inference` matches `causal OR inference`) -- and it doesn't just split on spaces: a
            # hyphenated single-token term like `all:difference-in-differences` gets split too
            # (verified live). Always quoting sidesteps needing to model arXiv's tokenizer at all;
            # quoting a single plain word is a documented no-op on arXiv's side.
            query = f'all:"{term}"'
            start = 0
            while yielded < cap:
                if not first_request:
                    self._sleep(_RATE_LIMIT_SECONDS)
                first_request = False

                page_cap = min(self._page_size, cap - yielded)
                entries = self._fetch_page(query, start, page_cap)
                if not entries:
                    break  # this term is exhausted -> move to the next focus_area entry
                for ref in entries:
                    if yielded >= cap:
                        return
                    yield ref
                    yielded += 1
                start += len(entries)

    def fetch_by_ids(self, ids: list[str]) -> list[PaperRef]:
        """Fetch specific, known papers by base arXiv id -- not the query-driven `fetch()` above.
        For one-off scripts that need exact papers (e.g. T-EVAL's 210-question eval set names 100
        specific `source_paper_id`s that must be in the corpus for the eval to be meaningful),
        where a `focus_area` search can't guarantee hitting them. Not part of the `Source`
        interface `Harvester` depends on (`Harvester.harvest()` never calls this) -- a caller
        that wants exact papers bypasses `Harvester` entirely and uses this directly.

        Chunks `ids` into pages of `_ID_LIST_CHUNK_SIZE` (arXiv's `id_list` has no documented hard
        limit, but a large single request risks an untested URL-length/server-side ceiling --
        chunking conservatively sidesteps needing to find that limit the hard way) and applies the
        same inter-request rate-limit delay `fetch()`'s pagination uses.

        A `paper_id` that doesn't resolve to a real arXiv entry is silently absent from the
        result (arXiv's `id_list` API omits unknown ids from the feed rather than erroring) --
        callers that need to detect a missing id should diff the input list against the returned
        `PaperRef.paper_id`s themselves.
        """
        refs: list[PaperRef] = []
        for i in range(0, len(ids), _ID_LIST_CHUNK_SIZE):
            if i > 0:
                self._sleep(_RATE_LIMIT_SECONDS)
            chunk = ids[i : i + _ID_LIST_CHUNK_SIZE]
            refs.extend(self._fetch_by_id_list(chunk))
        return refs

    def _fetch_by_id_list(self, ids: list[str]) -> list[PaperRef]:
        params = {"id_list": ",".join(ids), "max_results": len(ids)}
        try:
            response = self._client.get(_API_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in _RETRYABLE_STATUSES:
                raise TransientError(f"ArxivSource: arXiv API returned {status}") from error
            raise PermanentError(f"ArxivSource: arXiv API returned {status}") from error
        except httpx.HTTPError as error:
            raise TransientError(f"ArxivSource: arXiv API request failed: {error}") from error
        return self._parse_entries(response.text)

    def _fetch_page(self, query: str, start: int, page_cap: int) -> list[PaperRef]:
        params = {
            "search_query": query,
            "start": start,
            "max_results": page_cap,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        try:
            response = self._client.get(_API_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in _RETRYABLE_STATUSES:
                raise TransientError(f"ArxivSource: arXiv API returned {status}") from error
            raise PermanentError(f"ArxivSource: arXiv API returned {status}") from error
        except httpx.HTTPError as error:
            # Timeouts, connection errors, etc. — all transient (retry with backoff).
            raise TransientError(f"ArxivSource: arXiv API request failed: {error}") from error

        return self._parse_entries(response.text)

    def _parse_entries(self, atom_xml: str) -> list[PaperRef]:
        try:
            root = ET.fromstring(atom_xml)
        except ET.ParseError as error:
            raise PermanentError(f"ArxivSource: malformed arXiv Atom feed: {error}") from error
        return [self._entry_to_ref(entry) for entry in root.findall(f"{_ATOM_NS}entry")]

    def _entry_to_ref(self, entry: ET.Element) -> PaperRef:
        raw_id = (entry.findtext(f"{_ATOM_NS}id") or "").strip()
        versioned_id = raw_id.rsplit("/", 1)[-1]  # e.g. "2504.09999v2"
        paper_id = versioned_id
        version = "v1"
        m = re.match(r"^(?P<base>.+)v(?P<version>\d+)$", versioned_id)
        if m:
            paper_id, version = m.group("base"), f"v{m.group('version')}"

        title = " ".join((entry.findtext(f"{_ATOM_NS}title") or "").split())
        abstract = " ".join((entry.findtext(f"{_ATOM_NS}summary") or "").split())
        authors = [
            " ".join((author.findtext(f"{_ATOM_NS}name") or "").split())
            for author in entry.findall(f"{_ATOM_NS}author")
        ]
        categories = [
            cat.get("term", "") for cat in entry.findall(f"{_ATOM_NS}category") if cat.get("term")
        ]
        published = self._parse_date(entry.findtext(f"{_ATOM_NS}published"), versioned_id)
        updated = self._parse_date(entry.findtext(f"{_ATOM_NS}updated"), versioned_id)

        return PaperRef(
            paper_id=paper_id,
            version=version,
            title=title,
            abstract=abstract,
            authors=authors,
            categories=categories,
            published=published,
            updated=updated,
            pdf_url=f"https://arxiv.org/pdf/{versioned_id}",
            latex_url=f"https://arxiv.org/e-print/{versioned_id}",
        )

    @staticmethod
    def _parse_date(raw: str | None, paper_id: str) -> date:
        if not raw:
            raise PermanentError(f"ArxivSource: entry paper_id={paper_id!r} missing a date")
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError as error:
            raise PermanentError(
                f"ArxivSource: entry paper_id={paper_id!r} has an unparseable date {raw!r}"
            ) from error
