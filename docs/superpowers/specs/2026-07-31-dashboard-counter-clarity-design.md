# Dashboard counter clarity — design spec

**Date:** 2026-07-31
**Owner:** @MKamel1
**Status:** approved (owner, 2026-07-31)
**Backlog:** new item **D-5**; supersedes the display half of **O-1**

## The problem, as the operator hit it

Three separate confusions, all from the same panel:

> "the numbers dosn't make sense and confusing. why I see the pdf cached ~11500 lower than
> processed ~12000??? why I see the 30,000 target and the 20,000 target. the library being totall
> pulled for the tags we have should be clear to user."

Every one is a real defect in the display. None is a defect in the data.

## Findings (verified 2026-07-31 against the live corpus)

### 1. Downloads are divided by the wrong target

`app/dashboard/server.py:271`:

```python
"downloads": status_module.read_downloads(data_dir, live.get("target")),
```

`live` is the run manifest, so the count of **downloaded PDFs** is paired with the **processing**
target (20,000). The downloader does not aim at that number — `app/prefetch_pdfs.py:127` reads
`cfg.prefetch_target` (30,000), and its own log says so:

```
prefetch stalled: 11556/30000 cached, only 6 new available, next attempt in 3600s
```

`controller._spawn_download`'s docstring already documents the distinction ("`app.prefetch_pdfs`
reads its own stopping point from `config.prefetch_target`, unaffected by this run's `target`").
The display simply does not honor it. Wrong numerator/denominator pairing.

### 2. `pdf_cache` is a staging area, not a corpus mirror

Measured:

```
blobs/*.md        = 12,333   <- one per processed paper. This IS the corpus.
pdf_cache/*.pdf   = 11,612   <- downloads staged ahead of processing
done but NOT cached =  745
cached but NOT done =   24
```

The 745 were ingested by fetching the PDF live from arXiv during a run, never passing through the
cache — their `papers.pdf_path` is a URL, not a local path:

```
2504.08836 | https://arxiv.org/pdf/2504.08836v1 | .../blobs/2504.08836.md
```

**Nothing deletes cached PDFs** — grepped for `unlink`/`rmtree`/`remove`/`prune`/`evict` against
`pdf_cache` across `app/` and `rag/`, no hits. There is no eviction path; the cache was simply
never a complete record. Presenting a staging count beside a corpus count invites exactly the
comparison the operator made.

### 3. Harvest exhaustion is logged hourly and thrown away

`app/prefetch_pdfs.py:417` already emits the fact:

```python
"prefetch_pdfs: prefetch stalled: %d/%d cached, only %d new available, next attempt in %ds"
```

`status.read_downloader` reads that same log file, but its only pattern is
`_DOWNLOAD_PACE_RE = re.compile(r"downloaded (\d+) / target (\d+)")` (`status.py:440`). The stall
line is never parsed. The system knows it has exhausted arXiv for the configured queries, records
it every hour, and never tells the operator — who is left looking at a bar stuck at 58% with no
explanation.

## Decisions (operator, 2026-07-31)

| # | decision |
|---|---|
| 1 | **Pair downloads with `prefetch_target`.** Two honest bars — downloads against 30,000, processing against the run target — rather than one mixed-up bar. |
| 2 | **Prominent exhaustion banner, including the query count.** Makes it obvious the ceiling comes from the operator's own filters, not a failure. |
| 3 | **Present corpus and staged as separate things.** Relabel rather than reconcile; do not surface the 745 as its own number. |

## Design

### 3.1 `status.read_downloads` — correct denominator, add stall state

Signature changes from `read_downloads(data_dir, target)` to:

```python
def read_downloads(data_dir: str | Path, prefetch_target: int | None) -> dict
```

`server._status_dict` passes `_static_config(data_dir).prefetch_target` instead of
`live.get("target")`. The run target keeps its own home in the existing `run` block, untouched —
`read_telemetry`'s ETA and papers/hour math is not involved here and must not change.

Returned keys:

| key | meaning |
|---|---|
| `staged_pdfs` | renamed from `cached_pdfs` — PDFs downloaded ahead of processing |
| `sidecars` | unchanged |
| `prefetch_target` | renamed from `target`, now sourced from `Config.prefetch_target` |
| `stalled` | `True` when the newest stall line is more recent than the newest pace line |
| `new_last_pass` | the `only N new available` figure, or `None` when never stalled |
| `query_count` | `len(cfg.focus_area_queries)` — what the banner names |

`stalled` and `new_last_pass` come from a new regex over the same `prefetch.log` tail
`read_downloader` already reads:

```python
_DOWNLOAD_STALL_RE = re.compile(
    r"prefetch stalled: (\d+)/(\d+) cached, only (\d+) new available"
)
```

Both regexes scan the same tail; whichever match appears later in the file wins, so a stall that is
followed by a fresh pace line correctly clears. Absent log, unreadable log, or no match ⇒
`stalled: False`, `new_last_pass: None` — never a fabricated zero.

### 3.2 Frontend — three labelled quantities

`app/dashboard/static/index.html`, matching the existing panels' idiom:

- **Corpus** — `funnel.done` (12,333). The authoritative size. This is what `blobs/` holds.
- **Staged for processing** — `downloads.staged_pdfs` / `downloads.prefetch_target`
  (11,612 / 30,000), labelled as downloads waiting their turn.
- **Processing target** — stays in the run panel where it already lives.

Corpus and staged are rendered as **separate quantities in separate rows**, never as a shared
ratio. Per decision 3, the 745-paper gap is not surfaced as its own figure: once the two stop being
presented as comparable, the gap stops reading as an inconsistency.

When `downloads.stalled` is true, a banner renders above the panel:

> **Harvest exhausted** — every arXiv paper matching your **33 queries** has been downloaded.
> **+6 new** in the last pass. Widen `focus_area_queries` or `arxiv_categories` to grow further.

The query count is load-bearing: it is what makes the ceiling legible as a consequence of the
operator's own configuration rather than a system failure.

---

# Part 2 — Tag pool: one persistent library of queries

**Operator request (2026-07-31):**

> "I want a better design for the tags. I want to be able to add tags and delete them (put them on
> hold to be able to easily bring them back) — now I end up with different pool of added new
> tags/keywords. I want these to be added to the main pool and next user can keep them or put them
> on hold."

## Why pools currently diverge (root cause, verified)

Tag edits made from the dashboard are **run-scoped and thrown away**:

1. `POST /api/control` accepts `keywords` / `remove_keywords`
   (`server.py::_editable_query_kwargs`).
2. `controller._maybe_build_override` merges them and writes the result to a **scratch
   `config.yaml` in a run-scoped override directory** — never to the real one.
3. `_cleanup_run_cwd` later deletes that directory.
4. The next run calls `_load_base_config(data_dir)`, which reads `<data_dir>/config.yaml` — the
   **base** file, which never saw the edit.

So every run that edits tags creates its own private pool, that pool dies with the run, and the
next run silently reverts to the original 33 queries. That is exactly the "different pool of added
new tags" the operator describes. `remove_keywords` has the same lifetime: it suppresses a query
for one run, is invisible afterwards, and cannot be undone because nothing recorded it.

## Design: a sidecar tag pool, active vs held

**Storage:** `<data_dir>/tag_pool.json`, owned by the dashboard.

**Deliberately NOT a new field on `contracts/config.py`.** That file is CODEOWNERS
foundation-frozen; a sidecar needs no foundation review, no migration, and no change to how every
other consumer of `Config.focus_area_queries` behaves.

```json
{
  "active": ["causal inference", "do-calculus causal", "..."],
  "held":   [{"query": "synthetic control method", "held_at": "2026-07-31T20:00:00Z"}],
  "seeded_from": "config.yaml",
  "updated_at": "2026-07-31T20:00:00Z"
}
```

**Seeding.** On first read, if `tag_pool.json` is absent, it is created with `active` =
`config.yaml`'s current `focus_area_queries` and `held` = `[]`. The operator's 33 queries carry
over untouched; nothing is lost on adoption.

**Authority.** Once the file exists it is the source of truth for *what a run searches*.
`_maybe_build_override` composes `focus_area_queries` from `active` rather than from the base
config. `config.yaml` remains the seed and the fallback, and is never rewritten by the dashboard —
the operator's own file stays theirs.

**Hold, never delete.** Removing a tag moves it from `active` to `held` with a timestamp. It stays
listed, and one click restores it. Nothing about a tag is ever destroyed, which is the whole point
of the request.

### Actions on `POST /api/control`

| action | effect |
|---|---|
| `add_tags` | appends to `active`; de-duplicates; a tag currently in `held` is **moved back to active** rather than duplicated |
| `hold_tags` | moves `active` → `held`, stamped `held_at` |
| `restore_tags` | moves `held` → `active` |

The existing `keywords` / `remove_keywords` parameters keep working and keep their current
add/remove meaning, but now **write through to the pool** instead of a scratch file. That is the
fix: an edit made during a run persists into the main pool, and the next run inherits it.

**Guard, carried over:** holding every tag is refused with `InvalidOverrideError`, the same rule
`_maybe_build_override` already applies to `remove_keywords` — an empty query list leaves the
downloader with nothing to search.

**Unchanged semantics worth restating:** holding a tag only stops *future* downloads matching it.
Papers already in the corpus stay. Deleting corpus content is a separate destructive action and
remains out of scope.

### Read surface

`GET /api/status` gains a `tags` block:

```json
{"active": [...], "held": [...], "active_count": 33, "held_count": 0}
```

The exhaustion banner from Part 1 reads its query count from `tags.active_count`, so the two
features stay consistent by construction rather than by coincidence.

### Frontend

A "Tags" panel in `index.html`: active tags as chips each with a **Hold** control, a collapsed
**Held** section each with **Restore**, and an add box. Held tags are visibly present but styled as
inactive — the operator can see at a glance what has been parked and bring it back without
retyping.

## Non-goals

- No change to `funnel`, `read_telemetry`, ETA, or papers-per-hour. The combined funnel stays
  frozen for the reason recorded in the D-3 plan.
- No change to `app/prefetch_pdfs.py`. It already logs everything needed.
- **The dashboard never rewrites `config.yaml`.** The tag pool is a sidecar; the operator's config
  file is seed and fallback only.
- No change to either target value. Whether to widen the queries is the operator's call (backlog
  **O-1**); this spec only makes that call *informed* and *reversible*.
- No backfill of the 745 PDFs into the cache. They are already processed; re-downloading them
  would buy nothing.
- No tag-level analytics (papers harvested per tag). Worth having later; not required to fix the
  divergence, and it would need per-paper provenance the corpus does not currently record.

## Testing

Per `TEST-STRATEGY.md`: zero-GPU, zero-network, fakes over live services, `--disable-socket`.

| unit | test |
|---|---|
| `read_downloads` denominator | asserts `prefetch_target` comes from `Config.prefetch_target`, **not** the run manifest's `target` — a direct regression test for the mispairing |
| stall parsing | `tmp_path` log with a stall line ⇒ `stalled: True`, `new_last_pass: 6` |
| stall clearing | stall line **followed by** a newer pace line ⇒ `stalled: False` |
| absent log | ⇒ `stalled: False`, `new_last_pass: None` — never a fabricated `0` |
| `_status_dict` wiring | asserts the value passed to `read_downloads` is the config's `prefetch_target` |
| tag pool seeding | absent `tag_pool.json` ⇒ seeded from `config.yaml`'s `focus_area_queries`, `held == []` |
| **tag persistence across runs** | add a tag, build an override, build a **second** override — the tag is still there. This is the regression test for the actual bug; it fails against today's code |
| hold / restore round-trip | hold moves active→held with a timestamp; restore moves it back; the tag is never absent from the file |
| add of a held tag | moves it back to active rather than creating a duplicate |
| hold-everything guard | refused with `InvalidOverrideError`; pool left unmodified |
| override composition | `_maybe_build_override` writes `focus_area_queries` from `active`, not from the base config |

## Risk

Renaming `cached_pdfs` → `staged_pdfs` and `target` → `prefetch_target` is a breaking change to the
`/api/status` shape. The only consumer is `index.html` in this repo, updated in the same PR.
`test_status_route_shape_matches_api_contract` (`test_server.py:284`) asserts the full key set and
will fail loudly if either side is missed — which is the desired behavior, not an obstacle.
