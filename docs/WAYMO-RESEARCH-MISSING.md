# Waymo research papers missing from the corpus

*Compiled 2026-08-23 from a per-entry audit of both public index pages against the live corpus
(`waymo/data/papers.db` + Qdrant `waymo_av_safety`). Re-scrape both pages and re-run the checks
below before treating this list as current — Waymo's pages change without notice.*

| page | entries on page | in corpus + tagged `curated=Waymo` | missing |
|---|---|---|---|
| `https://waymo.com/safety/research/` | 55 | 54 | **1** |
| `https://waymo.com/research/` | 98 | 98 | **0** |

Labeling state: every present paper from both pages carries
`{"name": "Waymo", "method": "curated"}` in SQLite (`papers.author_orgs`) and the matching Qdrant
payload keys — verified per entry, plus `scripts/verify_curated_filter.py` (0 leaks).

## The one missing paper

| | |
|---|---|
| title | Representative cyclist collision injury risk distributions for a dense-urban US ODD using naturalistic dash camera data |
| authors | Campolettano, E. T.; Scanlon, J. M.; Kusano, K. D. |
| venue | SAE Technical Paper 2024-01-2645 (2024) |
| DOI | `10.4271/2024-01-2645` |
| access | SAE paywall — purchase required; Waymo publishes no free copy (its own page links only to the SAE product page; no arXiv mirror) |
| status | **ACCEPTED GAP 2026-08-18** (operator ruling, `WAYMO-CORPUS-STATUS.md` §9); listed here 2026-08-23 at operator request as the sole outstanding item |

Confirmed absent, not mislabeled: zero chunks corpus-wide contain `2024-01-2645`, and the
near-identically-titled *pedestrian* sibling (`local:aa069e80dac9`, ESV 2023) is in the corpus —
one word apart, easy to confuse when checking by title alone.

### If it is ever obtained

```bash
cp <pdf> waymo/data/drop_in/papers/
cd waymo/data && /home/omar/miniconda3/envs/agent-rag-research/bin/python -m app.ingest_local
# then add the minted local:<sha> id to fixtures/waymo/waymo_authored_ids.txt (foundation-
# protected — needs operator sign-off) and re-tag:
conda run -n agent-rag-research python scripts/backfill_curated_author_orgs.py
conda run -n agent-rag-research python scripts/verify_curated_filter.py   # expect 0 leaks
```

## How this was checked (for the next re-run)

- Scrape each page raw (`curl`), enumerate `<h3><a href="/research/<slug>">` entries; extract arXiv
  ids (`arxiv.org/abs|pdf/` **and** bare `arXiv:` forms) and DOIs per entry block.
- arXiv-id entries: direct `papers.paper_id` lookup, assert `author_orgs` contains curated Waymo.
- No-id entries: match stored title or opening ~3,500 chars of markdown, falling back to ≥5 shared
  content words — then hand-check fallback hits against near-duplicate siblings (the cyclist/
  pedestrian trap).
- Known variant-title mappings so future audits don't mark present papers missing:
  #46 safety-page *"An active inference model of car following…"* = `2303.15201`; *"SceneDiffuser…"*
  (research page) = `2412.12129`; *"Rate-Informed Discovery…"* (research page) = `2411.17826`;
  plus the four recorded in `WAYMO-CORPUS-STATUS.md` §15.
