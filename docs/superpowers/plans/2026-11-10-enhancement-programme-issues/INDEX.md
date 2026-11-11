# Enhancement programme: issue list for operator confirmation

Nothing here has been posted to GitHub. Each file below is the body of one proposed issue; the first lines of each file are the title and labels (parked files also carry a `Parked-until:` line). The programme plan is `docs/superpowers/plans/2026-11-10-enhancement-programme.md`. The operator approved the minimizer verdicts (`docs/eval-reports/2026-11-10-ticket-set-minimizer.md`) in full; this list is the result (51 original tickets: 7 merged away, 2 cut, 21 parked, 22 active including the new EV-6b).

**ACTIVE is the list proposed for posting as GitHub issues now. PARKED is NOT to be posted unless the operator asks: those tickets stay in the plan behind a checkable trigger.** Confirm, strike or change rows, then the active list is mirrored. Tickets already done or in progress on other branches (EV-4, EV-4b, CQ-1..CQ-6, EP-1, OP-1, ...) are in the plan (section 7), not here.

Label set is closed: `wave:*`, `area:*`, `needs-gpu`, `needs-signoff`, `needs-services`, `size:S|M`, and `parked` (parked files only).

## ACTIVE (22 issues)

Waves: W1 do now, no GPU = 17, W2 first GPU session, measurements only = 4, W3 gated changes after baselines = 0, W4 rider and what it unblocks = 1. Rows are in minimal-critical-path-first order (plan section 6).

| id | title | labels | wave | depends on | file |
|---|---|---|---|---|---|
| OP-4 | Take and verify a fresh main-corpus snapshot | wave:1-no-gpu, area:ops, size:S | 1 | none | [OP-4-take-verify-main-snapshot.md](OP-4-take-verify-main-snapshot.md) |
| OP-3 | Add integrity check and checksums to snapshot manifests | wave:1-no-gpu, area:ops, size:S | 1 | none | [OP-3-snapshot-integrity-and-checksums.md](OP-3-snapshot-integrity-and-checksums.md) |
| OP-6 | Guard every corpus tool against a missing or mismatched database | wave:1-no-gpu, area:ops, needs-services, size:M | 1 | OP-3 | [OP-6-wrong-corpus-guards.md](OP-6-wrong-corpus-guards.md) |
| OP-5 | Name the GPU lock holder and list foreign GPU processes in doctor | wave:1-no-gpu, area:ops, size:M | 1 | OP-6 | [OP-5-gpu-lock-holder-and-fast-fail.md](OP-5-gpu-lock-holder-and-fast-fail.md) |
| OP-7 | Track the four container definitions in ops/docker-compose.yml | wave:1-no-gpu, area:ops, needs-services, size:S | 1 | OP-5 | [OP-7-tracked-container-definitions.md](OP-7-tracked-container-definitions.md) |
| EP-6 | Add CORPORA.md and fix drift rows outside EP-1's files | wave:1-no-gpu, area:docs, size:S | 1 | none | [EP-6-docs-corpora-and-drift-remainder.md](EP-6-docs-corpora-and-drift-remainder.md) |
| MC-1 | Raise an error for an unknown paper_id filter instead of returning empty | wave:1-no-gpu, area:mcp, size:S | 1 | none | [MC-1-unknown-paper-id-raises.md](MC-1-unknown-paper-id-raises.md) |
| MC-2 | Make the MCP server describe its corpus, filters and limits | wave:1-no-gpu, area:mcp, size:M | 1 | MC-1 | [MC-2-self-describing-mcp-server.md](MC-2-self-describing-mcp-server.md) |
| MC-3 | Record arguments and errors for scan and get tools in the usage log | wave:1-no-gpu, area:mcp, size:S | 1 | MC-2 | [MC-3-scan-tool-telemetry.md](MC-3-scan-tool-telemetry.md) |
| EV-14 | Measure filtered-search overlap with exact search on the live collection (read-only) | wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:S | 1 | F2 | [EV-14-payload-index-overlap-measurement.md](EV-14-payload-index-overlap-measurement.md) |
| EV-7 | Require --collection, stamp the fixture hash, preflight gold ids | wave:1-no-gpu, area:eval, size:M | 1 | none | [EV-7-eval-entrypoints-explicit-collection.md](EV-7-eval-entrypoints-explicit-collection.md) |
| EV-8 | Add an excerpt-containment passage metric that honours alternative gold chunks | wave:1-no-gpu, area:eval, size:M | 1 | EV-7 | [EV-8-passage-excerpt-hit-metric.md](EV-8-passage-excerpt-hit-metric.md) |
| EV-9 | Record retrieved chunk ids in eval rows | wave:1-no-gpu, area:eval, size:S | 1 | EV-8 | [EV-9-chunk-ids-in-eval-rows.md](EV-9-chunk-ids-in-eval-rows.md) |
| EV-10 | Mark an eval run invalid when any error is a GPU lock timeout | wave:1-no-gpu, area:eval, size:S | 1 | EV-9 | [EV-10-invalid-run-on-lock-timeout.md](EV-10-invalid-run-on-lock-timeout.md) |
| EV-11 | Record note-only duplicates as alternatives and re-freeze fixture hashes | wave:1-no-gpu, area:eval, size:S | 1 | EV-8, EV-4b | [EV-11-record-alternatives-refreeze-hashes.md](EV-11-record-alternatives-refreeze-hashes.md) |
| EV-15 | Add the plain BM25 floor script named EV-5b in the protocols | wave:1-no-gpu, area:eval, size:S | 1 | none | [EV-15-bm25-floor-script.md](EV-15-bm25-floor-script.md) |
| EV-6b | Dry-run and independently review the strata report script before the first baseline | wave:1-no-gpu, area:eval, size:S | 1 | EV-9 | [EV-6b-review-strata-report-script.md](EV-6b-review-strata-report-script.md) |
| EV-16 | Run the frozen main-corpus baselines (papers, books, legacy) | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M | 2 | EV-7, EV-8, EV-9, EV-10, EV-11, EV-15, EV-6b, F3 | [EV-16-baseline-main-corpus.md](EV-16-baseline-main-corpus.md) |
| EV-17 | Run the frozen topic-focus baseline | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S | 2 | EV-16, EV-4b, F3 | [EV-17-baseline-topic-focus.md](EV-17-baseline-topic-focus.md) |
| EV-18 | Run the frozen standards baseline and evaluate the structure gate | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M | 2 | EV-16, EV-9, EV-11, EV-15, F3 | [EV-18-baseline-standards.md](EV-18-baseline-standards.md) |
| EV-20 | Run the depth grid (32 versus 128) on papers and books, only if headroom allows | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S | 2 | EV-16, EV-18, F3 | [EV-20-depth-weight-grid.md](EV-20-depth-weight-grid.md) |
| RIDER-1 | Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step) | wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M | 4 | EV-11, EV-18, F4 | [RIDER-1-foundation-signoff-rider.md](RIDER-1-foundation-signoff-rider.md) |

## PARKED (21 issues, do not post, do not start)

Each file is in `parked/` and starts with a `Parked-until:` line stating the checkable trigger and the kill criterion. The wave column is the wave the ticket had in the original plan.

| id | title | labels | wave | depends on | file |
|---|---|---|---|---|---|
| CQ-19 | Author 38 more standards ground-truth items for the weak stratum (authority or edition) | wave:1-no-gpu, area:eval, area:corpus, size:M, parked | 1 | EV-11, EV-18 | [CQ-19-standards-authority-items.md](parked/CQ-19-standards-authority-items.md) |
| CQ-7 | Build a ligature-repaired clone of the main collection on CPU | wave:1-no-gpu, area:corpus, needs-services, size:M, parked | 1 | OP-4, EV-16, F2, F3 | [CQ-7-ligature-resparse-clone-cpu.md](parked/CQ-7-ligature-resparse-clone-cpu.md) |
| CQ-8 | Make rechunk re-embed only chunks whose text changed | wave:1-no-gpu, area:corpus, size:M, parked | 1 | EV-18 | [CQ-8-rechunk-reuse-vectors-by-text-hash.md](parked/CQ-8-rechunk-reuse-vectors-by-text-hash.md) |
| EV-12 | Amend the CQ-3 stub A/B pre-registration (fixtures, minimum effect) | wave:1-no-gpu, area:eval, size:S, parked | 1 | EV-9, EV-11 | [EV-12-cq3-preregistration-addendum.md](parked/EV-12-cq3-preregistration-addendum.md) |
| EV-13 | Capture cross-encoder scores and build the absence census tool | wave:1-no-gpu, area:eval, area:retrieval, size:M, parked | 1 | RQ-1 | [EV-13-rerank-score-capture-and-census.md](parked/EV-13-rerank-score-capture-and-census.md) |
| OP-2 | Construct the vector index lazily so the server starts without it | wave:1-no-gpu, area:ops, area:mcp, size:M, parked | 1 | OP-5, OP-6, MC-3 | [OP-2-lazy-vector-index-construction.md](parked/OP-2-lazy-vector-index-construction.md) |
| RQ-1 | Fix three one-line retrieval defects (payload, partial rerank, cap) | wave:1-no-gpu, area:retrieval, size:S, parked | 1 | EV-18 | [RQ-1-three-retrieval-one-liners.md](parked/RQ-1-three-retrieval-one-liners.md) |
| RQ-2 | Add an opt-in, default-off relevance demotion to the Retriever | wave:1-no-gpu, area:retrieval, size:M, parked | 1 | RQ-1, EV-10, EV-17, F6 | [RQ-2-opt-in-relevance-demotion.md](parked/RQ-2-opt-in-relevance-demotion.md) |
| RQ-5 | Extract one shared sparse_tokens() used by the index | wave:1-no-gpu, area:retrieval, size:S, parked | 1 | RQ-1 | [RQ-5-shared-sparse-tokens.md](parked/RQ-5-shared-sparse-tokens.md) |
| EV-19 | Run the reranker-score census on the absent arms | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S, parked | 2 | EV-13, EV-16, EV-18, F3 | [EV-19-rerank-score-absence-census.md](parked/EV-19-rerank-score-absence-census.md) |
| EV-21 | Run the amended CQ-3 stub-filter A/B | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M, parked | 2 | EV-12, EV-9, EV-16, EV-18, F3 | [EV-21-stub-filter-ab.md](parked/EV-21-stub-filter-ab.md) |
| EV-22 | Run the ligature-repair A/B on the repaired clone | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:M, parked | 2 | CQ-7, EV-16, EV-18, F3 | [EV-22-ligature-resparse-ab.md](parked/EV-22-ligature-resparse-ab.md) |
| CQ-12 | Add golden tests and rules to the section tracker (standards) | wave:3-gated-change, area:corpus, size:M, parked | 3 | EV-18 | [CQ-12-section-tracker-rules-and-golden-tests.md](parked/CQ-12-section-tracker-rules-and-golden-tests.md) |
| CQ-13 | Add the running-furniture pre-pass (standards) | wave:3-gated-change, area:corpus, size:M, parked | 3 | CQ-12, EV-18 | [CQ-13-furniture-prepass-and-table-spans.md](parked/CQ-13-furniture-prepass-and-table-spans.md) |
| CQ-14 | Fold heading-only chunks into the next group and guard normalisation regexes | wave:3-gated-change, area:corpus, size:M, parked | 3 | EV-18, EV-21 | [CQ-14-stub-folding-and-regex-guard.md](parked/CQ-14-stub-folding-and-regex-guard.md) |
| CQ-16 | Rebuild the standards clone from re-derived paths and measure it against baseline (absorbs CQ-15) | wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:S, parked | 3 | CQ-12, CQ-13, CQ-14, CQ-8, EV-18, F2, F3, F7 | [CQ-16-standards-rechunk-verdict.md](parked/CQ-16-standards-rechunk-verdict.md) |
| CQ-18 | Add BM25 weighting behind a flag and run the A/B on a repaired clone (absorbs CQ-17) | wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:M, parked | 3 | RQ-5, EV-22, EV-16, EV-18, F2, F3 | [CQ-18-bm25-weighting-ab.md](parked/CQ-18-bm25-weighting-ab.md) |
| CQ-9 | Add idempotent payload indexes and verify them on a clone | wave:3-gated-change, area:corpus, area:retrieval, needs-services, size:M, parked | 3 | EV-14, RQ-5, RQ-1, F2 | [CQ-9-payload-indexes-on-clone.md](parked/CQ-9-payload-indexes-on-clone.md) |
| MC-4 | Slim the MCP wire by projecting duplicated envelope fields away | wave:3-gated-change, area:mcp, size:S, parked | 3 | MC-3, F5 | [MC-4-mcp-wire-projection.md](parked/MC-4-mcp-wire-projection.md) |
| RQ-3 | Run the relevance-demotion arms on the focus and passage sets | wave:3-gated-change, area:retrieval, area:eval, needs-gpu, needs-services, size:M, parked | 3 | RQ-2, EV-16, EV-17, F3, F6 | [RQ-3-focus-lever-ab.md](parked/RQ-3-focus-lever-ab.md) |
| RQ-4 | Expose the cross-encoder score in result metadata | wave:4-rider, area:retrieval, area:mcp, needs-signoff, size:S, parked | 4 | RIDER-1, EV-19, RQ-1 | [RQ-4-expose-rerank-score-metadata.md](parked/RQ-4-expose-rerank-score-metadata.md) |

Dependency entries of the form F1..F8 are operator questions (plan section 3); EV-4b is the in-progress repair of the merged focus ground truth; CQ-4, CQ-5, EP-1 are done. Entries marked "ordering only" in an issue's Gates line are file-ownership orders, not data dependencies. No active ticket depends on a parked one.

## Status after the 2026-11-11 measurements (git and run verdicts; nothing adopted)

Rows above keep their original wave and trigger text; this section records what the runs show. Results and "do not re-run unless"
conditions: `docs/eval-reports/EXPERIMENT-REGISTER.md`.

| id | status | verdict (report in `docs/eval-reports/`) |
|---|---|---|
| EV-14 | done | CQ-9 TRIGGER MET: `papers` F1 0.988 < 0.99; kill clause (0 short lists) also literally met, ambiguity recorded (`2026-11-11-filtered-search-result.md`) |
| EV-19 | done | CANDIDATE (focus, standards pass; legacy fails length control) (`2026-11-11-rerank-score-census-result.md`) |
| EV-20 | done | papers: no change (G-1 not met); books: G-1 met; operator decided 2026-11-11: main `rerank_depth` 32 -> 128, not a rule outcome (`2026-11-11-rerank-depth-result.md` section 8) |
| EV-21 | done | KILLED by its own ceiling rule, no arm run (`2026-11-11-stub-filter-result.md`) |
| EV-22 | done | REJECT, clause (a) fails 22 vs 22 (`2026-11-11-ligature-repair-result.md`) |
| CQ-7 | done | clone `papers__ligrepair_20261111` built (412,167 points, 138,484 sparse vectors changed); not deleted |
| RQ-3 | done | REJECT, all three arms (`2026-11-11-relevance-demotion-result.md`); RQ-2 lever stays default off |
| CQ-9 | parked, trigger met | see EV-14 |
| CQ-14 | parked | kill criterion as written met (standards stub-at-rank-1 = 1 < 3); not closed here |
| RQ-4 | parked | EV-19 gave CANDIDATE; the "CI contains 0.5 on two of three sets" kill criterion is not met; other gates unchanged |
