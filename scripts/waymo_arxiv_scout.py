"""Phase D of docs/superpowers/plans/2026-08-06-waymo-av-safety-corpus-expansion-v2.md: queries
arXiv's public API directly with docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §2b's real boolean/author
queries, scores and deduplicates the results, drops legacy-format ids, and writes a ranked
candidate list. `ALREADY_CAPTURED_IDS` is deliberately empty -- see §2b.3 above and
docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §3's banner for why the old exclusion-list use was a bug.

Deliberately does NOT go through rag.harvester.ArxivSource's end-to-end `fetch()`/`Harvester.
harvest()` path -- that class's `_build_query` wraps every term as `all:"<term>"` and rejects
quotes/booleans (an injection-safety fix for dashboard-editable input, see rag/harvester.py's
_UNSAFE_QUERY_CHARS_RE). The queries here are operator-fixed literals from a reviewed doc,
evaluated once, not runtime input -- the exact case that safety check doesn't need to cover.

This refactor DOES reuse `ArxivSource._fetch_page` (the real HTTP GET + status-code handling +
Atom-to-PaperRef parsing) and `Harvester._backoff` (the exact exponential curve already proven
against arXiv's real 429/503 behavior during the 30,000-paper causal-inference harvest -- see
that method's docstring). This script's first version hand-rolled its own HTTP/retry machinery
and needed two fix rounds in a row (a 503-causing page size, then insufficient 429 backoff) to
converge on... the same shape this codebase already had, tested, in production. Rather than tune
a third bespoke variant, this version reuses the proven machinery directly: `_fetch_page` is
private, but this repo already has a same-package-reuse convention for private helpers (e.g.
app/init_config.py imports rag.config._PATH_FIELDS/_resolve_paths directly), and this follows it.

Run from the repo root:
    python -m app.doctor  # not required for this script, just confirms sanity if unsure
    python scripts/waymo_arxiv_scout.py --out waymo/data/candidates.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root
from contracts.errors import TransientError  # noqa: E402
from contracts.harvester import PaperRef  # noqa: E402
from rag.harvester import ArxivSource, Harvester, _RATE_LIMIT_SECONDS  # noqa: E402

import re

_PAGE_SIZE = 25  # arXiv 503s on 100-result pages for these compound queries; 25 verified reliable
_MAX_RESULTS_PER_QUERY = 600  # broadened scope (§2b): narrower queries, 300 would truncate them
_MAX_FETCH_ATTEMPTS = 8  # Harvester._backoff(1..7): 1,2,4,8,16,32,64s -- covers sustained 429s

# docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §2b.1 "Category priority" / category filter string.
_CATEGORY_FILTER = "(cat:cs.RO OR cat:stat.AP OR cat:stat.ME OR cat:cs.LG OR cat:eess.SY OR cat:cs.CV)"

# arXiv modern id: YYMM.NNNNN (4-5 digit sequence). Legacy archive-prefixed ids
# (e.g. "hep-th/9304006") are rejected -- rag/harvester.py's pre-2007-id bug (§2 of the v2 plan)
# mangles them, and this corpus's earliest genuinely relevant paper is from 2016 anyway.
_MODERN_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")


def _is_modern_arxiv_id(paper_id: str) -> bool:
    return bool(_MODERN_ARXIV_ID_RE.match(paper_id))


# docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §2b.2 "The 11 topic areas -> query set" — verbatim,
# ANDed with the category filter. Queries 1-18 are §2's original set; 19-36 are the broadened scope.
_TOPIC_QUERIES = [
    'abs:"autonomous vehicle" AND abs:safety AND (abs:evaluation OR abs:assessment)',
    'abs:"crash rate" AND (abs:"automated driving" OR abs:"autonomous vehicle")',
    '(abs:"rare event" OR abs:"extreme value") AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:traffic)',
    'abs:"importance sampling" AND (abs:"autonomous vehicle" OR abs:"automated driving")',
    'abs:"surrogate safety" OR abs:"time-to-collision" OR abs:"post-encroachment time"',
    'abs:"scenario-based" AND (abs:testing OR abs:validation) AND (abs:"automated driving" OR abs:"autonomous vehicle")',
    'abs:"safety case" AND (abs:"automated driving" OR abs:"autonomous vehicle" OR abs:"self-driving")',
    'abs:simulation AND abs:realism AND (abs:driving OR abs:traffic)',
    'cat:cs.RO AND abs:"trajectory prediction" AND (abs:driving OR abs:vehicle)',
    'abs:"Waymo Open Dataset" OR abs:"Waymo Open Motion"',
    'abs:"concept drift" AND (abs:monitoring OR abs:production)',
    'abs:bayesian AND abs:"rare event" AND (abs:safety OR abs:risk)',
    'abs:"responsibility sensitive safety" OR abs:"safety force field"',
    'abs:"traffic conflict" AND (abs:risk OR abs:safety)',
    'abs:"deployment readiness" AND (abs:"automated driving" OR abs:autonomous)',
    'abs:"naturalistic driving" AND (abs:risk OR abs:crash)',
    'abs:"vulnerable road user" AND (abs:injury OR abs:risk) AND abs:vehicle',
    'abs:"operational design domain" AND (abs:safety OR abs:standard)',
    '(abs:"driving simulation" OR abs:"driving simulator" OR abs:"autonomous driving simulator") AND (abs:evaluation OR abs:validation OR abs:fidelity OR abs:realism)',
    'abs:"closed-loop simulation" AND (abs:driving OR abs:"autonomous vehicle" OR abs:traffic)',
    '(abs:"sim agents" OR abs:"simulation agents") AND (abs:driving OR abs:traffic OR abs:realism)',
    'abs:"simulation-based testing" AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:"cyber-physical")',
    '(abs:"traffic simulation" OR abs:"microscopic traffic" OR abs:"car-following model" OR abs:"lane change model") AND (abs:calibration OR abs:validation OR abs:realism OR abs:safety)',
    'abs:"driver behavior model" AND (abs:simulation OR abs:calibration OR abs:validation)',
    '(abs:"sim-to-real" OR abs:"sim2real" OR abs:"reality gap" OR abs:"distributional realism" OR abs:"distribution shift") AND (abs:driving OR abs:"autonomous vehicle" OR abs:traffic)',
    '(abs:"scenario generation" OR abs:"critical scenario" OR abs:"adversarial scenario" OR abs:"safety-critical scenario") AND (abs:"autonomous vehicle" OR abs:"automated driving" OR abs:simulation)',
    '(abs:"motion forecasting" OR abs:"behavior prediction" OR abs:"trajectory prediction") AND (abs:calibration OR abs:"uncertainty quantification" OR abs:"failure mode" OR abs:robustness OR abs:"safety impact" OR abs:"evaluation metric")',
    'abs:"prediction" AND abs:"planner" AND (abs:"safety" OR abs:"downstream") AND (abs:driving OR abs:"autonomous vehicle")',
    'abs:"UL 4600" OR (abs:"safety case" AND abs:"autonomous" AND abs:standard)',
    'abs:SOTIF OR abs:"safety of the intended functionality" OR abs:"ISO 21448"',
    'abs:PEGASUS OR (abs:"scenario database" AND abs:"automated driving") OR abs:"logical scenario"',
    '(abs:"ISO 26262" OR abs:"functional safety") AND (abs:"automated driving" OR abs:"autonomous vehicle")',
    'abs:Waymo',
    'abs:Waymax OR abs:"Waymo Open Sim Agents" OR abs:"WOMD"',
    '(abs:"runtime monitoring" OR abs:"safety envelope" OR abs:"reachability analysis") AND (abs:"autonomous vehicle" OR abs:"automated driving")',
    '(abs:"miles per intervention" OR abs:disengagement OR abs:"safety benchmark") AND (abs:"autonomous vehicle" OR abs:"automated driving")',
]
# Author-field queries — no category filter ANDed in (an author's own paper may sit outside the
# listed categories; category-restricting these would defeat the point of an author search).
# docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §2b.2's extended 13-author roster.
_AUTHOR_QUERIES = [
    'au:Kusano_K AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Scanlon_J AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Favaro_F AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Engström_J AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:McMurry_T AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Victor_T AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Fraade-Blanar_L AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Schnelle_S AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Campolettano_E AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Dinparastdjadid_A AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Schumann_J AND (abs:vehicle OR abs:driving OR abs:safety)',
    'au:Anguelov_D AND (abs:driving OR abs:vehicle)',
    'au:Sapp_B AND (abs:driving OR abs:vehicle)',
]

# docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §2b.3 "Extended relevance-scoring keyword weights".
_KEYWORD_WEIGHTS = {
    "waymo": 5, "rare event": 4, "extreme value": 4, "surrogate safety": 4, "crash rate": 4,
    "importance sampling": 4, "time-to-collision": 3, "post-encroachment": 3, "safety case": 3,
    "deployment readiness": 3, "bayesian": 2, "simulation": 2, "autonomous vehicle": 2,
    "automated driving": 2, "self-driving": 1, "traffic conflict": 3, "scenario-based": 2,
    "concept drift": 2, "responsibility sensitive safety": 3, "safety force field": 3,
    "trajectory prediction": 1, "motion forecasting": 1, "naturalistic driving": 2,
    "collision avoidance": 2, "operational design domain": 2, "benchmark": 1,
    "risk estimation": 3, "injury risk": 2, "vulnerable road user": 2,
    "scenario generation": 4, "safety-critical scenario": 4, "sim-to-real": 3, "sim2real": 3,
    "distributional realism": 4, "traffic simulation": 3, "car-following": 2,
    "driving simulator": 2, "closed-loop simulation": 3, "sim agents": 4, "waymax": 5,
    "waymo open": 5, "sotif": 4, "ul 4600": 4, "iso 21448": 4, "iso 26262": 3, "pegasus": 3,
    "functional safety": 2, "reachability analysis": 3, "runtime monitoring": 3,
    "uncertainty quantification": 2, "calibration": 2, "failure mode": 2, "disengagement": 2,
    "safety benchmark": 3, "scenario database": 2, "logical scenario": 2,
}

# §5 of the v2 plan: repurposed as a seed/priority list, NOT an exclusion list -- treating it as an
# exclusion list is what kept every one of Waymo's 114 own-authored arXiv papers out of the corpus
# (docs/ONBOARDING_AND_ARXIV_KEYWORDS.md §3's banner). `app/build_corpus.py::cached_not_done` is the
# real "already have it" authority (subtracts `stage='done'` every iteration), so this stays empty.
ALREADY_CAPTURED_IDS = frozenset()


def score_text(text: str) -> int:
    text = text.lower()
    return sum(weight for kw, weight in _KEYWORD_WEIGHTS.items() if kw in text)


def dedup_by_id(refs: list[PaperRef]) -> list[PaperRef]:
    seen: dict[str, PaperRef] = {}
    for ref in refs:
        seen.setdefault(ref.paper_id, ref)
    return list(seen.values())


def _fetch_page_with_retry(
    source: ArxivSource, query: str, start: int, page_cap: int, sleep
) -> list[PaperRef]:
    """Retries `ArxivSource._fetch_page` on `TransientError` using `Harvester._backoff`'s
    already-proven exponential curve -- the same retry shape `Harvester.harvest()` uses in
    production, reused here rather than reimplemented."""
    for attempt in range(1, _MAX_FETCH_ATTEMPTS + 1):
        try:
            return source._fetch_page(query, start, page_cap, "relevance")
        except TransientError:
            if attempt == _MAX_FETCH_ATTEMPTS:
                raise
            sleep(Harvester._backoff(attempt))
    return []  # unreachable


def _run_query(source: ArxivSource, query: str, sleep, first: list[bool]) -> list[PaperRef]:
    """`first` is a single-element mutable flag shared across every call in a `scout()` run, so the
    pre-fetch sleep is skipped only before the very first page of the whole run -- mirroring
    `ArxivSource.fetch()`'s `first_request` (rag/harvester.py), which lives outside its per-term
    loop for the same reason: back-to-back requests across query boundaries still need the delay."""
    entries: list[PaperRef] = []
    start = 0
    while start < _MAX_RESULTS_PER_QUERY:
        if not first[0]:
            sleep(_RATE_LIMIT_SECONDS)
        first[0] = False
        page_cap = min(_PAGE_SIZE, _MAX_RESULTS_PER_QUERY - start)
        page = _fetch_page_with_retry(source, query, start, page_cap, sleep)
        if not page:
            break
        entries.extend(page)
        start += len(page)
    return entries


def scout(sleep=time.sleep) -> list[dict]:
    source = ArxivSource(sleep=sleep)
    raw: list[PaperRef] = []
    first = [True]
    for query in _TOPIC_QUERIES:
        raw.extend(_run_query(source, f"{query} AND {_CATEGORY_FILTER}", sleep, first))
    for query in _AUTHOR_QUERIES:
        raw.extend(_run_query(source, query, sleep, first))

    deduped = dedup_by_id(raw)
    modern = [ref for ref in deduped if _is_modern_arxiv_id(ref.paper_id)]
    kept = [ref for ref in modern if ref.paper_id not in ALREADY_CAPTURED_IDS]
    scored = [
        {
            "id": ref.paper_id,
            "title": ref.title,
            "authors": ref.authors,
            "categories": ref.categories,
            "published": ref.published.isoformat(),
            "score": score_text(ref.title + " " + ref.abstract),
        }
        for ref in kept
    ]
    scored = [c for c in scored if c["score"] > 0]
    scored.sort(key=lambda c: c["score"], reverse=True)
    print(
        f"waymo_arxiv_scout: {len(raw)} raw hits -> {len(deduped)} unique -> "
        f"{len(modern)} modern-id ({len(deduped) - len(modern)} legacy dropped) -> "
        f"{len(kept)} after excluding {len(modern) - len(kept)} already-captured -> "
        f"{len(scored)} after dropping score-0",
        file=sys.stderr,
    )
    print("Top 20 by relevance score:", file=sys.stderr)
    for c in scored[:20]:
        print(f"  [{c['score']:>2}] {c['id']}  {c['title'][:90]}", file=sys.stderr)
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="path to write candidates.json")
    args = parser.parse_args()
    candidates = scout()
    Path(args.out).write_text(json.dumps(candidates, indent=2))
    print(f"waymo_arxiv_scout: wrote {len(candidates)} candidates to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
