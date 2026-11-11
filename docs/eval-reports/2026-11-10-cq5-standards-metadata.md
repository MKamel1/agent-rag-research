# CQ-5: document-kind / edition / issuer metadata for the standards corpus

Status: reviewed table, validator and emitter delivered; **nothing applied** to any database or index.
Files (all new): `docs/eval-reports/data/2026-11-10-standards-metadata/` (`standards_metadata.json`,
`review-changes.md`, `ACQUISITIONS.md`, and the emitted `payload_mapping.json`,
`categories_update.sql`, `categories_update.tsv`), `scripts/standards_metadata.py` + test.
Reused: `app/set_payload_fields.py` (consumes the mapping unchanged), the CQ-2 `--only-fields` /
snapshot guard, `gt_tools.py` (read-only corpus access during review), and the draft table.

## 1. The problem and the choice

The standards DB stores all 119 documents as `doc_type` paper (10 book), 114 have empty
`categories_json`, and 92 `published` dates are placeholders. Retrieval cannot tell a normative
standard from slides about it, a current edition from a superseded one, or a full text from a preview.
`review-changes.md` records the review; of the draft, 52 rows changed.

**Tags in `categories` now.** Touches no protected file, is reversible (the TSV holds the old values),
and uses the one list filter `SearchFilters` already has. **Typed fields later** (section 7) is the
right end state but needs `contracts/` and `migrations/`, i.e. operator sign-off.

### Tag vocabulary (all emitted by `scripts/standards_metadata.py`)

| Tag | Values | Emitted when |
|---|---|---|
| `kind:<v>` | standard, technical-specification, regulation, guidance, handbook, report, book, paper, slides, commentary, letter | always |
| `status:<v>` | current, superseded, draft, withdrawn, preview-only | always |
| `completeness:<v>` | full, preview | always |
| `issuer:<slug>` | e.g. iso, avsc, nhtsa, iso-iec-ieee | issuer known (null for authored papers/slides/letters/books) |
| `normative:<true/false>` | | not null (3 rows are null: no tag, never a silent false) |
| `kindstatus:<kind>+<status>` | e.g. `kindstatus:standard+current` | always |
| `normstatus:<true/false>+<status>` | e.g. `normstatus:true+current` | normative not null |

Distinct values after tagging: 88 (including the 5 real arXiv category codes, which are kept). The
colon namespace cannot collide with arXiv codes (RV-1's request for a recorded namespace).

## 2. Exact filter semantics (read from `rag/vector_index.py::_qdrant_filter`)

`SearchFilters.categories` becomes one `FieldCondition(key="categories", match=MatchAny(any=[...]))`.
A point passes iff its payload `categories` list **shares at least one value** with the requested
list: OR within `categories`. That condition is added to a `must` list with every other filter field
set, so across *different* SearchFilters fields it is AND. There is no AND between two category values
and no negation.

- `categories=["kind:standard","kind:regulation"]` -> standards OR regulations. Fine.
- `categories=["kind:standard","status:current"]` -> standards OR anything current: **not** "current
  standards" (it matches 107 current documents plus the 29 standards).
- Hence the combined tags: `["kindstatus:standard+current"]` is a single value = current standards;
  `["normstatus:true+current"]` = normative and current. For an OR of conjunctions, list several
  combined tags: `["kindstatus:standard+current","kindstatus:technical-specification+current"]`.
- Not expressible with tags: "not superseded" (negation) other than as the OR of the positive
  statuses; "issuer X AND current" (no such combined tag; use `issuer:x` and read `status` from the
  result, or add a tag family later).
- `SearchFilters.kind` is chunk|summary and unrelated to `kind:` tags: easy to confuse.
- Payload indexes do not exist (RV-1 F-1.1), so this filter is evaluated unindexed; acceptable at
  35,714 points, not something to rely on at 400k.

## 3. Do the tags survive re-ingest? (code read, not assumed)

- `rag/orchestrator.py::vector_payload` sets `"categories": list(record.ref.categories)` (line 151):
  confirmed. It is the single producer for ingest upsert **and** `app/rechunk.py` (line 197), which
  builds its record with `document_store.get(paper_id)`.
- Therefore a **rechunk keeps the payload tags only if the SQLite `categories_json` carries them**:
  the SQL file is not optional.
- `app/ingest_local.py::mint_local_ref` writes `categories=[]` for every `local:` document (line 257);
  an arXiv-resolved ref keeps arXiv's own categories (comment at line 348). `DocumentStore.put` is an
  upsert with `categories_json=excluded.categories_json`, and the vector upsert rebuilds the payload
  from the same ref. So **a re-ingest of a drop-in overwrites the tags in both stores** (the id is a
  content digest, so the same bytes hit the same row). After any re-ingest or `ingest_paper_ids` run, re-run
  `emit` and the apply sequence (idempotent: managed tags are stripped before being re-added).
- `app.resparse` writes only the sparse vector; payload untouched.

## 4. Using the tags through the existing MCP tools today

`app/serve.py::semantic_search(query, filters: SearchFilters | None, k)` and `search_papers` take the
whole `SearchFilters` model, so `categories` is already a tool argument (undescribed in the schema, RV-4
F-4.3). Example:

```json
{"tool": "semantic_search",
 "arguments": {"query": "hazard severity categories",
               "filters": {"categories": ["kindstatus:standard+current"], "max_hits_per_paper": 2},
               "k": 10}}
```

An agent must already know the tag names (nothing advertises them): either from the tool docstring RV-4
proposes, or from `corpus_stats`. After the apply, `corpus_stats()` (`rag/document_store.py::corpus_stats`)
would keep `papers: 119`, `doc_types: {paper: 109, book: 10}` and the wrong date range, and its
`top_categories` (hard-capped at 10) would read: completeness:full 112, status:current 107,
normative:false 93, normstatus:false+current 88, kind:guidance 30, kindstatus:guidance+current 29,
kind:standard 29, kindstatus:standard+current 23, normative:true 23, issuer:avsc 20. The rare and most
important values (superseded, draft, withdrawn, preview-only) fall below the cap and stay hidden; RV-4
F-4.4's "return all tags with counts" removes that. The superseded_by facts are not in the tags; they are
only in `standards_metadata.json` until typed fields or the proposed `corpus_stats.documents` list exist.

## 5. Pre-registered measurement (run when the embedder/reranker are back)

Ground truth: `standards_gt.json`, strata `authority` (Q-STD-C-019..022) and `edition` (Q-STD-A-021/022,
B-021/022), **4 items each**. Outcome per item: gold anchor block in the top 10 (`app/retrieval_eval.py`
scoring, as for the baseline). Paired design: each item is run unfiltered and filtered.

- authority arm: `categories=["normative:true"]` (not `normstatus:true+current`: Q-STD-C-019's gold is
  the UL 4600 draft, status draft, which a `current` filter would exclude).
- edition arm: `categories=["kind:standard","kind:technical-specification"]` (Q-STD-A-021's gold is
  ISO/PAS 21448:2019, a technical-specification; the two 2011/2019 gold documents are superseded, so a
  `status:current` filter would make them unanswerable by design and is excluded from the test).
- Descriptive extra for edition questions that do not name an edition: share of top-10 hits that are
  superseded documents, unfiltered.

**What 4 items can support: description only.** With n = 4 the best possible outcome (all four items
discordant in the filter's favour) gives an exact two-sided McNemar/sign p = 2 * 0.5^4 = 0.125, which can
never reach 0.05. No adoption claim can rest on these strata.

**Items a follow-up authoring ticket must add.** Target: detect a 30-point difference in hit@10 (e.g.
0.50 -> 0.80, delta = p10 - p01 = 0.30) at two-sided alpha 0.05, power 80%, McNemar paired design. Connor's
formula for the number of pairs: n = (z_a * sqrt(psi) + z_b * sqrt(psi - delta^2))^2 / delta^2, where psi
is the fraction of items on which the two arms disagree, z_a = 1.960, z_b = 0.842.

| psi (disagreement) | arithmetic | n per stratum |
|---|---|---|
| 0.3 | (1.960*0.5477 + 0.842*0.4583)^2 / 0.09 = 1.4593^2/0.09 = 23.66 | 24 |
| **0.5 (planning value)** | (1.960*0.7071 + 0.842*0.6403)^2 / 0.09 = 1.9248^2/0.09 = 41.17 | **42** |
| 0.6 | (1.960*0.7746 + 0.842*0.7141)^2 / 0.09 = 2.1192^2/0.09 = 49.90 | 50 |

Planning on psi = 0.5: 42 items per stratum, so **38 more authority items and 38 more edition items (76
total)**; 46 + 46 if psi turns out to be 0.6, 20 + 20 if 0.3. The new items must come from many different
documents (the current four rest on four documents each), be phrased as a user would without hinting the
tag, and be authored with the existing `gt_tools.py verify`. Adoption requires, in addition, no item
hurt among the other 120 items when the filter is off (it is opt-in, so unfiltered results are unchanged
by construction) and a report of paired flips, not rates.

## 6. Operator apply sequence (every step defaults to dry run; run from the repo root)

Prereq: Qdrant up for the standards collection; no ingest or rechunk running; embedder not needed.
`CFG=/home/omar/ai-projects/research-system-rag-standards/data/config.yaml`,
`DB=/home/omar/ai-projects/research-system-rag-standards/data/papers.db`,
`D=docs/eval-reports/data/2026-11-10-standards-metadata`.

```bash
# 0. validate the table against the DB (read-only); non-zero exit on any problem
python scripts/standards_metadata.py validate --db $DB
# 1. snapshot (SQLite VACUUM INTO + blobs + Qdrant snapshot); required by --i-have-a-snapshot
python -m app.snapshot --config $CFG
# 2. regenerate the artefacts if the table changed (reads DB read-only, writes only $D)
python scripts/standards_metadata.py emit --db $DB --out-dir $D
# 3. DRY RUN payload (reports points it would touch; writes nothing)
python -m app.set_payload_fields --config $CFG --collection av_standards \
   --only-fields categories --mapping-file $D/payload_mapping.json
# 4. APPLY payload (point counts per paper must match before/after; read-back sample checked)
python -m app.set_payload_fields --config $CFG --collection av_standards \
   --only-fields categories --mapping-file $D/payload_mapping.json --apply --i-have-a-snapshot
# 5. DRY RUN SQL on a throwaway copy
cp $DB /tmp/papers_cq5_copy.db && sqlite3 /tmp/papers_cq5_copy.db < $D/categories_update.sql
sqlite3 /tmp/papers_cq5_copy.db "select count(*) from papers where categories_json like '%kind:%'"   # 119
# 6. APPLY SQL to the real DB (stop anything writing to it first; each UPDATE is guarded by the old value)
sqlite3 $DB < $D/categories_update.sql
# 7. verify
sqlite3 -readonly $DB "select count(*) from papers where categories_json like '%kind:%'"            # 119
sqlite3 -readonly $DB "select count(*) from papers where categories_json like '%status:superseded%'" # 4
python scripts/standards_metadata.py emit --db $DB --out-dir /tmp/cq5_recheck \
  && diff $D/payload_mapping.json /tmp/cq5_recheck/payload_mapping.json && echo idempotent
# then a live check through MCP: corpus_stats top_categories; semantic_search with
# filters.categories=["status:superseded"] returns only AVSC00005, ISO PAS 21448, ISO 31000:2009, 15026-2:2011
```

Rollback: restore the step-1 snapshot, or apply the TSV's `old_categories_json` column back with the
same guarded-UPDATE pattern and re-run step 4 with a mapping built from the old values.

Expected: 119 papers, all points of those papers get `categories` replaced by their merged list;
per-paper point counts unchanged (the tool enforces it).

## 7. Typed fields later: exact proposed diff for the sign-off rider (NOT applied)

Protected paths (`contracts/`, `migrations/`); needs operator sign-off. Payoff: AND across fields
(`doc_kinds` AND `doc_statuses`) without combined tags, filterable ranges, and fields that exist on
`PaperRef` so ingest sets them.

```diff
--- /dev/null
+++ b/migrations/0007_doc_metadata.sql
+-- Additive. NULL = never classified (not "unknown value").
+ALTER TABLE papers ADD COLUMN doc_kind TEXT;
+ALTER TABLE papers ADD COLUMN doc_status TEXT;
+ALTER TABLE papers ADD COLUMN issuer TEXT;
+ALTER TABLE papers ADD COLUMN normative INTEGER;      -- 0/1/NULL
+ALTER TABLE papers ADD COLUMN completeness TEXT;
+ALTER TABLE papers ADD COLUMN edition_year INTEGER;
+ALTER TABLE papers ADD COLUMN superseded_by TEXT;     -- JSON list of paper_ids

--- a/contracts/harvester.py   (PaperRef)
     doc_type: Literal["paper", "book"] = "paper"
+    doc_kind: str | None = None          # closed vocab, see standards_metadata.json meta
+    doc_status: str | None = None
+    issuer: str | None = None
+    normative: bool | None = None
+    completeness: Literal["full", "preview"] | None = None
+    edition_year: int | None = None
+    superseded_by: list[str] = Field(default_factory=list)

--- a/contracts/vector_index.py   (SearchFilters; every field ANDed, each list is any-of)
+    doc_kinds: list[str] | None = None
+    doc_statuses: list[str] | None = None
+    issuers: list[str] | None = None
+    normative: bool | None = None
+    completeness: Literal["full", "preview"] | None = None
--- a/contracts/vector_index.py   (VectorPayload; absent, not None, on legacy points)
+    doc_kind: str
+    doc_status: str
+    issuer: str
+    normative: bool
+    completeness: str

--- a/rag/vector_index.py::_qdrant_filter
+    for field, wanted in (("doc_kind", filters.doc_kinds), ("doc_status", filters.doc_statuses),
+                          ("issuer", filters.issuers)):
+        if wanted is not None:
+            must.append(models.FieldCondition(key=field, match=models.MatchAny(any=wanted)))
+    if filters.normative is not None:
+        must.append(models.FieldCondition(key="normative", match=models.MatchValue(value=filters.normative)))
+    if filters.completeness is not None:
+        must.append(models.FieldCondition(key="completeness", match=models.MatchValue(value=filters.completeness)))
--- a/rag/fakes/fake_vector_store.py::_passes_filters   (parity, same five conditions)
--- a/rag/orchestrator.py::vector_payload   (copy the five fields when not None, like relevance_score)
--- a/rag/document_store.py   (put/get/corpus_stats: read and write the seven columns; corpus_stats
                              reports counts per doc_kind/doc_status)
--- a/app/ingest_local.py   (read an optional `<file>.meta.json` sidecar into PaperRef so a re-ingest keeps them)
```

Backfill path: load `standards_metadata.json` into the new columns (read-only DB opened rw by the
operator only), then `app.set_payload_fields --only-fields doc_kind,doc_status,issuer,normative,completeness`.
Also add `create_payload_index` for these keys (RV-1 F-1.1). Migrate readers off the tags, then delete the
tags with the same tool pattern.

## 8. Not verified / limits

- Retrieval with filters was not run (embedder and reranker down; zero GPU allowed here).
- `status: current` is relative to the corpus, not the world (see `standards_metadata.json` `meta.rules`).
- `AVSC00006/7/8` designations and months come from other corpus documents citing them; `ADS 2.0`,
  `AV 3.0` and `NASA SP-2010-580` years likewise (flagged `year_basis: cross-reference`).
- 9 documents have no dated text; their edition_year is null with a reason.
