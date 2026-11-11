# CQ-2 runbook: index maintenance without re-embedding (resparse, set-payload)

Branch `EP-CQ2-resparse-setpayload`. Nothing here has been run against a live index (embedder,
reranker and Qdrant services are down; no GPU). All behaviour is unit-tested against mocked
clients only. Every time/size figure below is an ESTIMATE, not a measurement.

## 1. DEPLOYMENT HAZARD: CQ-1 query repair vs. un-resparsed collections

**Is it real?** Yes. `rag/vector_index.py::_sparse_vector` calls `repair_ligatures()`
unconditionally, and both `upsert()` (index side) and `hybrid_search()` (query side, via
`_sparse_vector(qtext)`) go through it. There is no flag. So after CQ-1, every collection built
before CQ-1 and not yet resparsed is queried with repaired tokens against unrepaired stored
sparse vectors. (The waymo and standards collections are in the same position as the main one.)

**What exactly regresses.** Sparse matching is exact hashed-token equality. Let `d` be a damaged
spelling (a key of `rag/ligature_map.json`, 227 entries) and `r` its repair.

| Query token | Stored in chunk | Before CQ-1 | After CQ-1, before resparse | After resparse |
|---|---|---|---|---|
| `r` ("effect") | `r` | match | match (unchanged) | match |
| `r` ("effect") | `d` ("efect") | no match | no match (no gain yet) | match (the gain) |
| `d` ("efect") | `d` | match | **NO MATCH (regression)** | no match* |
| `d` ("efect") | `r` | no match | match (new) | match |

\* after resparse every chunk holds `r`, and the query is repaired to `r`, so a damaged-spelling
query matches the whole corpus's correct and formerly-damaged chunks alike: the row-3 loss is
transient.

So the only token that could match before and no longer matches is a query token that is itself
a damaged spelling, against a chunk still stored under that damaged spelling. Correctly spelled
queries (the normal case) lose nothing. Two secondary effects until the resparse: (a) the keyword
arm gains nothing: 34.6% of main-corpus chunks (138,451 of 399,676, per
`docs/eval-reports/data/2026-11-10-ligature-census/repair-map-report.md`) still hold damaged
tokens; (b) Qdrant's IDF modifier derives df from stored vectors, so a repaired query term's df is
under-counted (the "efect" chunks are missing from it) and the term is mildly over-weighted.

**Measured exposure in our own evals:** 0 of the 263 questions in
`2026-11-10-papers-passage-gt` (61), `2026-11-10-causal-books-gt` (74) and `2026-11-10-standards-gt`
(128) contain a map key, so an eval run of CQ-1-on-live would NOT show the regression. It bites only
real users who paste or type damaged text.

**Conclusion.** The CQ-1 code is *safe to deploy* ahead of the resparse for normal queries, but
gives zero benefit until the resparse runs and regresses damaged-spelling queries in the interim.
Ship them as one maintenance window, in this order:

1. Do the clone A/B (section 3) FIRST; the adoption rule below decides whether CQ-1 stays at all.
2. If adopted: snapshot live, then resparse LIVE in place (sparse-only update-vectors never empties
   the collection; it is resumable) while the OLD code is still serving. Old-code queries on
   half-resparsed data lose only the mirror-image case (damaged-spelling query vs repaired store),
   while correct-spelling queries gain as pages complete.
3. Pause ingest for the window (old-code ingest writes unrepaired vectors).
4. Restart the serving process on CQ-1 code.
5. Re-run `--apply` once more (idempotent; rewrites only stragglers) and `--verify-sample 2000`
   (expect 0 stale).
Never restart serving on CQ-1 code against a collection whose `--verify-sample` shows stale
points without accepting the damaged-spelling regression for that window.
Do the same for each of `papers`, `waymo_av_safety`, `av_standards`.

## 2. What was built

- `VectorIndex.resparse(collection=None, *, batch_size=1000, dry_run=False) -> ResparseReport`.
  Pages with scroll (`with_payload=["text","kind"]`, `with_vectors=["sparse"]`: no dense vector in
  either direction), recomputes `_sparse_vector(payload["text"])`, writes ONLY changed points via
  `update_vectors` (sparse named vector only). Summary points carry sparse vectors built from
  their `text` (paper `summary_text`; chapter text for book chapter summaries), so they are
  resparsed like chunks. A point with no string `text` is counted under `skipped["no_text"]` and
  left alone. Report: scanned / changed / unchanged / skipped-by-reason / per-kind counts /
  points that had no stored sparse vector at all.
- `VectorIndex.set_payload(fields, *, paper_ids=None, point_ids=None, collection=None,
  batch_size=200) -> count`: merge-only; exactly one selector; refuses `text`, `paper_id`, `kind`,
  `_ext_id`; returns points matched (nonexistent ids not counted).
- Helpers: `sample_sparse_staleness(n)`, `sample_payloads(n)`, `paper_point_ids()`;
  `VectorIndex(..., create_if_missing=False)` so a mistyped collection raises instead of silently
  creating an empty one (`reindex_idf` has that hazard; the new CLIs do not).
- `python -m app.resparse` and `python -m app.set_payload_fields`: `--collection` required, no
  default; dry run is the default; writing needs `--apply` AND (`--i-have-a-snapshot`, verified on
  disk with `app.reindex_idf._verify_snapshot_present` for exactly that collection, OR
  `--target-is-clone --clone-of SOURCE`, which requires equal point counts: a sanity check, not
  proof the clone came from `clone_points_into`). Point count before/after; resparse also
  re-samples 200 points after writing and fails if any is stale. `set_payload_fields` requires
  `--only-fields`, checks points-per-paper before/after, and reads back 500 random points.
- Payload coverage vs `rag.orchestrator.vector_payload` (the single producer, used by ingest and
  `app/rechunk.py`):

| Field | Produced by `vector_payload` (survives re-ingest/rechunk)? |
|---|---|
| `relevance_score` | YES (added in CQ-2; from `PaperRecord.relevance_score`, key absent when unscored) |
| `topic_label` | NO. Comes from the offline labels TSV, no ingest-time source; a re-ingested or rechunked paper loses it until the backfill is re-run |
| `doc_kind` / `edition` (standards) | NO, same reason (source: `standards-gt/standards_metadata_draft.json`; load with `--mapping-file`) |

`relevance_score`/`topic_label` are NOT filterable yet: `SearchFilters` is protected. They are
stored and visible in payloads only.

## 3. Day-of sequence (GPU and services back)

Corpora: main `papers` (db `/home/omar/ai-projects/research-system-rag-data/papers.db`, config
`/home/omar/ai-projects/research-system-rag-data/config.yaml`), waymo `waymo_av_safety`,
standards `av_standards` (config `.../research-system-rag-standards/data/config.yaml`).
Run from the repo root with `conda run -n agent-rag-research`. Services up: `python -m app.doctor`.

```bash
CFG=/home/omar/ai-projects/research-system-rag-data/config.yaml
# 0. measure staleness of live (read-only)
python -m app.resparse --collection papers --verify-sample 2000
# 1. snapshot live (uses cfg.collection; point --config at a config whose `collection` is the target)
python -m app.snapshot --config $CFG
# 2. clone live -> papers_resparse (no re-embedding; ~4.2 GB extra: 412k x 2560 x 4 B)
python -c "from rag.vector_index import VectorIndex; \
print(VectorIndex('localhost',6333,'papers',2560).clone_points_into('papers_resparse'))"
# 3. dry run on the clone, then apply there
python -m app.resparse --collection papers_resparse
python -m app.resparse --collection papers_resparse --apply --target-is-clone --clone-of papers
python -m app.resparse --collection papers_resparse --verify-sample 2000   # expect 0 stale
```

**A/B (retrieval eval).** Baseline arm = the code BEFORE CQ-1's merge (commit `56d24d0^1`, in a
separate worktree) against live `papers`. Candidate arm = this branch against `papers_resparse`.
(Optional third arm, informational: CQ-1 code against un-resparsed live = the interim state.)
Ground truth (all under `docs/eval-reports/data/`): `2026-11-10-papers-passage-gt/papers_passage_gt.json`
(main-corpus passage set, 61 q), `2026-11-10-causal-books-gt/causal_books_gt.json` (74 q),
`2026-11-10-standards-gt/standards_gt.json` (128 q; standards collection `av_standards`, same
procedure, its own clone).

```bash
GT=docs/eval-reports/data/2026-11-10-papers-passage-gt/papers_passage_gt.json
for MODE in fused sparse_only dense_only; do
  python -m app.retrieval_eval --ground-truth $GT --config $CFG --collection papers_resparse \
     --k 10 --sparse-mode $MODE --report-path /tmp/cq2-cand-$MODE.json     # candidate
  # same command from the pre-CQ-1 worktree with --collection papers   -> baseline
done
python scripts/eval_strata_report.py --ground-truth $GT --db <papers.db> --k 10 \
   --topic-labels docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv \
   /tmp/cq2-base-fused.json /tmp/cq2-cand-fused.json       # per-stratum; one GT per invocation
```
Repeat for `causal_books_gt.json` and the standards set.

**Pre-registered adoption criterion (fixed before any run).**
ADOPT CQ-1's ligature repair only if BOTH hold:
(a) `sparse_only` paper Recall@10 on the main-corpus passage set (`papers_passage_gt.json`) is
strictly higher for the candidate than the baseline; and
(b) on EVERY fixture (passage-set, causal-books, standards), candidate fused paper Recall@10 AND
member-passage hit@10 are each no more than ONE question below the baseline.
Otherwise do not adopt: revert CQ-1's query-side repair too (`_sparse_vector` back to no repair on
both sides) and delete `papers_resparse`. Do not tune the criterion after seeing numbers.
With n=61 a one-question gain is within noise; (a) is a pre-registered gate, not a significance
claim, and the report must say so.

**Apply to live** (only after ADOPT), per section 1: snapshot again if more than a day old, then

```bash
python -m app.resparse --collection papers                       # dry run; compare with step 3
python -m app.resparse --collection papers --apply --i-have-a-snapshot
```
Alternative if an in-place write is not wanted: swap in the clone with the existing
`migrate_via_clone_and_swap` machinery (clone `papers_resparse` back over `papers`); it has the
brief absent-collection window its docstring describes, which in-place resparse does not.
Delete `papers_resparse` afterwards.

**Payload backfills** (independent of the above; do on a clone or after a snapshot):

```bash
python -m app.set_payload_fields --collection papers --only-fields relevance_score \
   --build relevance_score --db /home/omar/ai-projects/research-system-rag-data/papers.db
python -m app.set_payload_fields --collection papers --only-fields topic_label --build topic_label \
   --labels docs/eval-reports/data/2026-11-10-topic-labels/topic_labels.tsv
# add --apply --i-have-a-snapshot (or --target-is-clone --clone-of papers) to write
```

**Run-time estimate (ESTIMATE, unmeasured).** 412k points at 1,000 per page is ~412 pages. Per
page: scroll of ~3-4 MB text+sparse (~0.3-1 s), tokenise+repair 1,000 chunks (~0.1 s; census
measured 7.8 s/100k), and an `update_vectors` of ~35% changed points (~0.5-2 s with wait). Roughly
1-3 s/page, i.e. about 7-20 minutes for `--apply`, 3-7 minutes for a dry run or
`--verify-sample`-free scan. The expensive step on the day is the clone (full vectors, ~400 points
per upsert, ~1,000 requests), likely tens of minutes: the existing helper's cost, not this ticket's.

## 4. Needs operator sign-off (nothing below was edited; contracts/ and rag/fakes/ are protected)

1. **`contracts/vector_index.py`, payload fields** (so the TypedDict matches what
   `vector_payload` now emits; today `orchestrator.py` sets the key outside the TypedDict with a
   `# type: ignore[typeddict-unknown-key]`):
   ```diff
   -from typing import Literal, TypedDict
   +from typing import Literal, NotRequired, TypedDict
   ...
        curated_author_orgs: list[str]  # (existing)
   +    relevance_score: NotRequired[float]  # CQ-2: papers.relevance_score; absent when unscored
   +    topic_label: NotRequired[str]  # CQ-2: "on" | "borderline" | "off"; backfill only
   ```
2. **`contracts/vector_index.py`, filter levers** (makes the backfilled fields usable at query
   time; then `_qdrant_filter` in `rag/vector_index.py` gets matching `FieldCondition`s with a
   `models.Range(gte=...)` and a `MatchAny`, in my file, once the contract lands):
   ```diff
    class SearchFilters(FrozenModel):
   +    min_relevance_score: float | None = None  # inclusive; points without the key are excluded
   +    topic_labels: list[str] | None = None  # any-of match against VectorPayload.topic_label
   ```
3. **`rag/fakes/fake_vector_store.py`, parity** (`_passes_filters` plus the two maintenance
   methods, so fake and adapter stay in step):
   ```diff
   +        if filters.min_relevance_score is not None and not (
   +            payload.get("relevance_score", float("-inf")) >= filters.min_relevance_score
   +        ):
   +            return False
   +        if filters.topic_labels is not None and payload.get("topic_label") not in filters.topic_labels:
   +            return False
   ...
   +    def set_payload(self, fields, *, paper_ids=None, point_ids=None, collection=None,
   +                    batch_size=0) -> int:
   +        hit = [i for i, (_, p) in self._store.items()
   +               if (paper_ids is not None and p["paper_id"] in paper_ids)
   +               or (point_ids is not None and i in point_ids)]
   +        for i in hit:
   +            self._store[i][1].update(fields)
   +        return len(hit)
   +
   +    def resparse(self, collection=None, *, batch_size=0, dry_run=False):
   +        return None  # the fake computes token overlap from `text` on demand: never stale
   ```
   The `VectorIndex` interface is documented in prose (ARCHITECTURE.md / the contracts docstring),
   not as a `Protocol`, so no signature change is needed in `contracts/` for `resparse`/
   `set_payload`; add one sentence to the module docstring listing them if wanted.
4. **Running anything live**: the snapshot, clone, apply, and the CQ-1 deployment decision in
   section 1 (when to pause ingest and restart serving) are operator actions; none were done here.
5. **`--target-is-clone` is a count check only.** If a stronger proof is wanted (e.g. clone helper
   writing a marker into the collection), that is a change to `clone_points_into`, not made here.
