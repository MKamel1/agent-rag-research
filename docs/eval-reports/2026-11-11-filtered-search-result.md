# Filtered-search overlap, exact vs approximate (EV-14, shrunk): result, 2026-11-11

**Verdict (pre-registered rule): CQ-9 TRIGGER MET: binding filters below 0.99 on `papers`: F1 (`kind=summary`, mean overlap@10 0.988).**
The margin is 0.002 below the bar. The other three binding filters (F3, F4, F6) are at 1.000. One clause of the pre-registered
kill criterion is also literally satisfied on `papers` (0 short result lists); see section 4, "ambiguity". Nothing was changed; no
payload index was created.

Pre-registration: `docs/eval-reports/data/2026-11-11-session2/PREREGISTRATION.md` section 4. Register: `EXPERIMENT-REGISTER.md`.

## 1. Question asked

Does filtered approximate (HNSW) search in the vector store miss neighbours that exact search finds, for the filters production
queries use? If mean overlap@10 is >= 0.99 on all binding filters on `papers`, payload-index work (parked CQ-9) is closed; any binding
filter below 0.99 means CQ-9's trigger is met.

## 2. What was run

| item | value | source |
|---|---|---|
| code commit | `03cfd1854b7d37c8116d35545c3f54a309e6da40` | `MANIFEST.txt` |
| window | 2026-11-11 12:19:59 to 12:28:47 (-07:00), 8 min 48 s; `papers` about 8 min 28 s, `av_standards` about 20 s | `MANIFEST.txt`, `q3_filtered.log` timestamps |
| method | no embedder, no GPU, no fixtures; seeded sample (seed 20261111) of 100 stored points per filter supplies the query vector; each query run approximate and with `params.exact = true`, k = 10 after dropping the query's own point; REST calls `GET /collections`, `scroll`, `query` only | prereg section 4, `MANIFEST.txt` |
| collections | `papers` (412,167 points), `av_standards` (36,031 points); both report `payload_schema={}` (no payload indexes) | `papers.log`, `av_standards.log` |
| HTTP calls | 2,780 (`papers`), 2,956 (`av_standards`) | `papers.json`, `av_standards.json` (`http_calls`) |

Evidence committed in full: `docs/eval-reports/data/2026-11-11-session2/runs/filtered-20261111T121957/` (`papers.{json,log}`,
`av_standards.{json,log}`, `MANIFEST.txt`). Console log: `.../scratchpad/q3_filtered.log`.

## 3. Results: mean overlap@10 (n queries, min overlap, share of queries with perfect overlap, short result lists); source `papers.json`, `av_standards.json`

| filter | binding | `papers`: mean (n; min; perfect; short) | `av_standards`: mean (n; min; perfect; short) |
|---|---|---|---|
| F1 `kind=summary` | yes | **0.988** (100; 0.6; 0.92; 0) | 1.000 (100; 1.0; 1.00; 0) |
| F2 `kind=chunk` | no | 0.993 (100; 0.8; 0.95; 0) | 1.000 (100; 1.0; 1.00; 0) |
| F3 `kind=summary` + `doc_type=book` | yes | 1.000 (88; 1.0; 1.00; 0) | 1.000 (100; 1.0; 1.00; 0) |
| F4 `kind=chunk` + `doc_type=book` | yes | 1.000 (100; 1.0; 1.00; 0) | 0.886 (100; 0.0; 0.81; 0) |
| F5 `kind=chunk` + `doc_type=paper` | no | 0.995 (100; 0.7; 0.97; 0) | 0.998 (100; 0.9; 0.98; 0) |
| F6 `kind=chunk` + own `paper_id` | yes | 1.000 (100; 1.0; 1.00; 0) | 0.939 (100; 0.0; 0.92; 4) |
| F7 `kind=summary` + own categories | no | 0.987 (100; 0.6; 0.92; 0) | 1.000 (4; 1.0; 1.00; 4) |
| F8 `kind=chunk` + own categories | no | 0.982 (100; 0.4; 0.90; 0) | 1.000 (10; 1.0; 1.00; 0) |

The population for `papers` F3 is 88 (fewer than 100 book summaries available), and `av_standards` F7 has 4 and F8 10 eligible points.

## 4. Rule evaluated literally

| clause | evaluation |
|---|---|
| binding filters on `papers`: F1, F3, F4, F6; each must be >= 0.99 to close CQ-9 | F1 0.988 < 0.99; F3 1.000, F4 1.000, F6 1.000 |
| "any binding filter below 0.99 on `papers` means CQ-9's trigger is met" | **met** (F1 only) |
| `av_standards` and non-binding filters (F2, F5, F7, F8): reported, do not change the verdict | `av_standards` F4 0.886 and F6 0.939 are below 0.99 (the script prints "TRIGGER MET: ['F4', 'F6']" for it) but are informational by rule |
| kill criterion: CQ-9 killed if no query returned fewer than k hits (count of short result lists) | `papers`: short lists = 0 on all eight filters, so the clause is literally satisfied; `av_standards` has 4 short lists (F6) and 4 (F7) |

**Ambiguity (not resolved here).** The pre-registration states two rules in the same section: a falsifier (any binding filter < 0.99
means TRIGGER MET) and a kill criterion (killed if no query returned fewer than k hits). On `papers` both fire: F1 is below 0.99, and no
query returned a short list. The text does not say which wins; the ticket text (CQ-9 "killed if EV-14 overlap is at least 0.99 on all
three filters, or no baseline query returned fewer than k hits") has the same two clauses and names three filters where the
pre-registration names four binding ones (F1, F3, F4, F6). The script's printed verdict, which this report adopts as the
pre-registered one, is TRIGGER MET. Whether CQ-9 should start is an operator reading of that conflict.

## 5. Validity and caveats

- Overlap is a recall proxy for the dense arm only; production asks the dense side for up to 10,000 results, not 10, and the sparse arm
  is untested. Query vectors are stored document vectors, atypically close to their neighbours, which flatters HNSW.
- The F1 shortfall is 0.002, one 100-query sample at one seed: 8 of 100 queries below perfect with a minimum of 0.6 (that is
  `share_perfect` 0.92 for F1). No repeat with another seed was run, so the sampling variability of the 0.988 is not measured.
- `av_standards` F4 minimum 0.0 and F6 minimum 0.0 (and the 4 short lists) are unexamined; the standards table is informational.
- Read-only: only allowed REST calls (the script refuses others); no collection or payload was modified.

## 6. Do not re-run unless

1. The collection changed: points added or removed, re-ingest, re-chunk, clone promoted (e.g. `papers__ligrepair_20261111`), or a
   payload index created (then `payload_schema` is no longer `{}` and the point of the test changes). Check: `GET /collections/papers`
   (point count 412,167, `payload_schema`).
2. The vector store version or HNSW parameters (`m`, `ef_construct`, search `ef`) changed.
3. The operator wants the F1 shortfall confirmed: re-run F1 only, with at least two other seeds and more queries (the 0.002 margin is
   inside sampling noise); that needs a dated addendum fixing the seed and n. Cost is about 8 CPU minutes and no GPU.
4. A threshold change (0.99) or a decision on the rule conflict in section 4: dated addendum; the stored per-filter numbers need no
   re-run to be re-read.
5. Real-query-vector overlap is wanted (embedder required) or the sparse arm is to be tested: a different experiment.
