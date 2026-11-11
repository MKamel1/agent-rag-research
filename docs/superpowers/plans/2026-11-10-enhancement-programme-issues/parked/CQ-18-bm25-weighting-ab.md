Title: CQ-18: Add BM25 weighting behind a flag and run the A/B on a repaired clone (absorbs CQ-17)
Labels: wave:3-gated-change, area:corpus, area:eval, needs-gpu, needs-services, size:M, parked
Parked-until: start only if on some set fused minus dense-only passage hit@10 is 3 items or more AND sparse-only passage hit@10 is more than 3 items from the plain-BM25 floor on that set (the sparse arm matters and is not merely BM25); needs F2 and F3, and a repaired base if EV-22 ran. Kill criterion: killed if on every set fused minus dense-only passage hit@10 is 2 items or fewer, or sparse-only is within 3 items of the BM25 floor on every set, or EV-22 shows ligature repair itself changed the sparse arm so that attribution is muddied and no gain remains.

## CQ-18 -- Add BM25 weighting behind a flag and run the A/B on a repaired clone (absorbs CQ-17)

**Review cross-reference:** S-25. **Wave:** W3 gated changes after baselines.

**Parked, do not start.** Parked-until: start only if on some set fused minus dense-only passage hit@10 is 3 items or more AND sparse-only passage hit@10 is more than 3 items from the plain-BM25 floor on that set (the sparse arm matters and is not merely BM25); needs F2 and F3, and a repaired base if EV-22 ran. Kill criterion: killed if on every set fused minus dense-only passage hit@10 is 2 items or fewer, or sparse-only is within 3 items of the BM25 floor on every set, or EV-22 shows ligature repair itself changed the sparse arm so that attribution is muddied and no gain remains.

**Absorbs CQ-17** (CQ-17: Add BM25 saturation and length normalisation to the sparse arm behind a flag). The merged ticket is one unit: the flag-gated implementation and the clone A/B are one ticket; the dependency CQ-9 -> CQ-17 (a file-ownership artefact of `rag/vector_index.py`) is cut.

**Why.** Whether length normalisation and saturation help the sparse arm is unmeasured; a separate A/B keeps attribution clean after the ligature A/B (review S-25). Absorbed from CQ-17: The sparse arm is raw term frequency times IDF with no saturation or length normalisation although its docstring says 'BM25-style' (`rag/vector_index.py:112`); legacy main chunks are unbounded (8,487 chunks over 8,000 characters), so long chunks can dominate (RV-1 F-1.6). A sparse recompute is CPU-only, so bundling it with ligature repair 'to save cost' is wrong and would confound attribution (review S-25).

**Scope.**
- In:
  - On a fresh clone: resparse with the option on (CPU), run the standards, causal-books and papers-passage sets and the lexical strata (standards clause lookups, books terminology) against the live baseline, paired flips.
  - Absorbed from CQ-17: Index-time weight `tf*(k1+1)/(tf + k1*(1-b+b*len/avglen))` behind an explicit option, `avglen` measured once per corpus from stored chunks (CPU) and recorded; applies only when (re)computing sparse vectors (`app.resparse` on a clone); default off.
  - Absorbed from CQ-17: Starts only after EV-22 (S-17 done).
- Out (explicitly):
  - Live application (follow-on on ADOPT only). Combining with any other change.
  - Absorbed from CQ-17: Edge-punctuation stripping in the tokenizer (measured effect on 12-26% of tokens, but it changes tokens; include only if the operator wants it in this A/B: stated as a separate flag, never bundled). Applying to any live collection. The A/B (CQ-18).

**Owns** (files this ticket may touch; anything else is out of bounds):
- `docs/eval-reports/<run-date>-bm25-weighting-ab.md`
- `docs/eval-reports/data/<run-date>-bm25-weighting-ab/`
- `rag/vector_index.py`
- `rag/test_vector_index.py`
- `rag/sparse_tokens.py`
- `rag/test_sparse_tokens.py`
- `app/resparse.py`
- `app/test_resparse.py`

**Commits** (① is a stub, committed before any real work):
① stub: report skeleton; rule: ADOPT only if net +3 items on at least one set, no set losing more than 1, and a gain on the lexical strata, else REJECT
② Pre-registered in commit 1; no metric, threshold or fixture changes afterwards (dated addendum only).
③ clone built and resparsed; counts recorded
④ arms run; MANIFEST
⑤ report; clone deleted
⑥ [absorbed CQ-17] stub: docstring with the formula, parameters (k1, b, avglen), the default-off guarantee and the one-recompute-per-arm rule
⑦ [absorbed CQ-17] failing tests: option off leaves vectors byte-identical; option on gives the expected weights on a toy corpus
⑧ [absorbed CQ-17] implementation to green
⑨ [absorbed CQ-17] avglen measurement helper and recorded constants per corpus

**Verification:**
- `conda run -n agent-rag-research python -m pytest -q -o addopts="--disable-socket -m 'not real_adapter'"` (zero GPU, zero network; report the summary line)
- `EV=$(mktemp) && echo '{}' > "$EV" && GITHUB_EVENT_NAME=push GITHUB_EVENT_PATH="$EV" conda run -n agent-rag-research python -m ci.run_enforcement` (report the verdict line)
- Every command names `--collection`; the live collection is never an apply target
- `conda run -n agent-rag-research ruff check rag/vector_index.py rag/test_vector_index.py rag/sparse_tokens.py rag/test_sparse_tokens.py app/resparse.py app/test_resparse.py`
- Identical sparse vectors with the option off on 200 stored chunks (RQ-5 check reused)
- `conda run -n agent-rag-research python -m pytest -q rag/test_vector_index.py rag/test_sparse_tokens.py app/test_resparse.py -o addopts="--disable-socket"`

**Acceptance / falsification criterion.** Verdict applies the stated rule per set (never averaged); the ceiling is stated per stratum (BM25 floor from EV-15 shows where lexical headroom exists). Falsified if the baseline arm differs from EV-16/EV-18 beyond the jitter envelope.

Absorbed from CQ-17: Option off: byte-identical vectors; option on: weights match a hand-computed toy example; avglen constants recorded with the command that produced them. Falsified if default behaviour changes by one byte.

**Gates / depends on.** Depends on: RQ-5, EV-22, EV-16, EV-18. Operator answers: F2, F3. Gates: none.

**Needs.** GPU: y · services up: embedder + reranker containers, vector store, corpus database (read-only) · operator sign-off: n (no protected path is touched); operator answers: F2, F3 · re-embed: n. Also: GPU free (F3); vector store (F2); 6-8 GB for a clone. Absorbed from CQ-17: GPU: n · services up: none · operator sign-off: n (no protected path is touched) · re-embed: n

**Model tier and size.** Sonnet; M (up to 1 day of agent work). Logic or authoring work; no Opus-level design adjudication is needed.

**Risk and rollback.** Disk or contention; mitigations as CQ-7. Rollback: delete the clone. Absorbed from CQ-17: Query-side tokens stay binary while index weights change, which a later reader might misread as a bug. Mitigation: documented in the docstring. Rollback: revert; no index depends on it.

**Docs to update in the same PR.** The report or note this ticket writes is its doc (section 7 doc-map row). Per `docs/AGENT-PROCEDURES.md` section B, in this same PR: flip this ticket's row in `docs/BACKLOG.md` (Enhancement programme section) to DONE with the landing SHA; add one entry to the `docs/PROJECT-STATUS.md` section 3 shipped-work ledger (ticket, what it did, SHA); add a section 7 doc-map row for every new `docs/*.md`; add the section 2 entry-point row for any new entry point or flag; HISTORICAL banner on any doc this PR supersedes. `docs/PROJECT-STATUS.md` and `docs/BACKLOG.md` are shared append-or-flip files, deliberately not listed under Owns; the orchestrator resolves append conflicts when it merges.
