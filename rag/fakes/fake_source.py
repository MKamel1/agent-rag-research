"""FakeSource — the fake `Source` adapter Harvester (M1, owner A) injects in every zero-network
test (T-F4).

**Assumption flagged for Owner A (T-A1):** ARCHITECTURE.md/DATA-CONTRACTS.md pin Harvester's own
interface (`harvest(focus_area, cap, ordering) -> Iterator[PaperRef]`) but do NOT pin the shape of
`Source`, Harvester's own injected collaborator (ARCHITECTURE.md M1 "Seam: `Source` (arXiv
adapter)" — named, not specified). This file is the **first** concrete shape given to `Source`:

    fetch(self, focus_area: list[str], cap: int, ordering: str) -> Iterator[PaperRef]

chosen to mirror Harvester's own signature 1:1 (Harvester's `harvest()` is expected to be a thin
wrapper that adds dedup/resume/rate-limiting around a call to `Source.fetch()` with the same
three arguments). This is a **documented assumption, not a pre-existing contract** — Owner A
should confirm or adjust it when T-A1 starts; if it changes, this fake and its test move with it.
"""

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from contracts.errors import PermanentError, TransientError
from contracts.harvester import PaperRef

DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "harvester" / "paper_refs.json"
)

# An injected error may be given as an already-constructed exception instance (raised as-is) or
# as the bare exception class (instantiated with a generic message at raise time) — caller's
# choice, both are supported so a test can pick whichever is more convenient to write.
InjectedError = TransientError | PermanentError | type[TransientError] | type[PermanentError]


class FakeSource:
    """Yields a fixed list of `PaperRef`s loaded from a committed JSON fixture — no arXiv calls.

    The default fixture (`fixtures/harvester/paper_refs.json`) includes two versions (`v1`/`v2`)
    of the same base `paper_id` so Harvester's dedup-by-base-id test (T-A1) has something real to
    dedupe, per TEST-STRATEGY.md's `FakeSource` bullet.
    """

    def __init__(
        self,
        fixture_path: str | Path = DEFAULT_FIXTURE_PATH,
        errors: dict[str, InjectedError] | None = None,
    ):
        self._refs = self._load_fixture(Path(fixture_path))
        # Keyed by `PaperRef.paper_id` (the base id — see contracts/harvester.py: "base arXiv id
        # (no version)"), so mapping one entry affects every version of that base id yielded by
        # this source, not just one specific version.
        self._errors = errors or {}

    def fetch(self, focus_area: list[str], cap: int, ordering: str) -> Iterator[PaperRef]:
        """Ignores `focus_area`/`ordering` (this fake has one fixed fixture, not a queryable
        index) but honors `cap` by yielding at most `cap` refs, and honors `errors` by raising
        instead of yielding once a mapped `paper_id` is reached — both are cheap, meaningful
        things a test can assert on without a real flaky API.
        """
        count = 0
        for ref in self._refs:
            if count >= cap:
                return
            if ref.paper_id in self._errors:
                raise self._as_exception(self._errors[ref.paper_id], ref.paper_id)
            yield ref
            count += 1

    @staticmethod
    def _as_exception(error: InjectedError, paper_id: str) -> Exception:
        if isinstance(error, type):
            return error(f"FakeSource: injected error for paper_id={paper_id!r}")
        return error

    @staticmethod
    def _load_fixture(path: Path) -> list[PaperRef]:
        with path.open() as f:
            raw = json.load(f)
        return [
            PaperRef(
                paper_id=item["paper_id"],
                version=item["version"],
                title=item["title"],
                abstract=item["abstract"],
                authors=item["authors"],
                categories=item["categories"],
                published=date.fromisoformat(item["published"]),
                updated=date.fromisoformat(item["updated"]),
                pdf_url=item["pdf_url"],
                latex_url=item.get("latex_url"),
            )
            for item in raw
        ]
