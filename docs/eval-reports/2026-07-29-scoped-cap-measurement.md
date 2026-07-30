# Scoped per-paper cap (Decision 2, option B) — measurement — 2026-07-29

`docs/DECISIONS-PENDING-operator.md` Decision 2, option B (operator-approved): relax
`rag/retriever.py`'s per-paper result cap only when the caller has already scoped the search
(`filters.doc_type` set today), keeping the existing cap for unscoped corpus-wide search.

Full per-question detail is not written to disk by this run (the scratch script only reports
aggregates) — see "How this was run" below to reproduce.

## The two limits

```python
_MAX_HITS_PER_PAPER = 3          # unscoped -- unchanged, T-DOC82
_MAX_HITS_PER_PAPER_SCOPED = 50  # scoped (filters.doc_type set) -- new, Decision 2 option B
```

**`_MAX_HITS_PER_PAPER = 3` (unchanged).** T-DOC82's original rationale still holds for unscoped
search: across the whole ~11,026-document corpus, an unconstrained book match could otherwise fill
every slot of `k` with chapters of one paper. That diversity argument only applies when the
candidate pool genuinely spans many papers.

**`_MAX_HITS_PER_PAPER_SCOPED = 50` (new).** Sized from the corpus, not copied from the `10` in the
task brief's own table. The eval corpus's 5 books split into 8-44 chapter units each; `k` is
typically 10. 50 sits above the largest observed per-document unit count, so it effectively
*disables* the cap once the caller has scoped to one `doc_type` — rerank order alone decides which
chapters fill the top `k`, which is exactly what "the caller asked for depth in one document"
should mean. A future book with more than 50 chapter units would need this revisited, but nothing
in the current corpus approaches that.

`_is_scoped(filters)` returns `True` only when `filters.doc_type is not None`. `categories` and the
published-date range were deliberately excluded — both are corpus-wide filters (many documents can
match), so T-DOC82's diversity argument still applies under them; only a filter that narrows to a
single document (or, today, one `doc_type`) counts as "scoped."

Applied to `retrieve_papers()` only. **`retrieve()` (passage-level search) never called
`_cap_per_paper` at all, before or after this change** — reading the code before touching it found
that `_MAX_HITS_PER_PAPER` was only ever wired into `retrieve_papers()` (`rag/retriever.py` git
history: T-DOC82, commit `7f8f156` "cap chapter hits per paper in search_papers"), and
`docs/DECISIONS-PENDING-operator.md`'s own
Decision 2 section is scoped entirely to `retrieve_papers()`/chapter routing — it never discusses
`retrieve()`. The task brief's framing ("applied ... in both `retrieve()` and `retrieve_papers()`")
does not match the code or the decision doc; this diff does not add a new cap to `retrieve()`,
since neither the code's prior behavior nor the operator-approved decision calls for one. Flagging
this explicitly rather than silently expanding scope.

## Measurements

All three runs: collection `exp1_ctrl_sizemerge_idf` (372,741 points, sparse IDF **on** — see "IDF
note" below), `k=10`, real TEI embedder/reranker (no fakes), read-only retrieval calls only.

| # | measurement | filter | cap (effective) | n | recall@10 | MRR |
|---|---|---|---|---|---|---|
| 1 | **Unscoped regression guard** | none | 3 (unchanged) | 40 | **0.425** | 0.274 |
| 2 | Scoped (this change) | `doc_type="book"` | 50 (new) | 40 | **0.725** | 0.351 |
| 3 | **210-question paper set** | none | 3 (unchanged, `retrieve()` path) | 210 | **0.976** | 0.920 |

**Row 1 is the load-bearing result of this task, not row 2.** Unfiltered chapter recall is
**0.425 — byte-for-byte the same as the pre-change baseline** in `docs/DECISIONS-PENDING-operator.md`
("cap 3, filter none, chapter R@10 0.425"). This is the direct check that the new scoped-cap logic
does not leak into the unscoped path: `_is_scoped(None)` is `False`, so `filters=None` still
resolves to `_MAX_HITS_PER_PAPER=3`, exactly as before this change existed.

**Row 2 matches the decision doc's own prior measurement exactly**: `docs/DECISIONS-PENDING-operator.md`'s
table records "cap 50, doc_type book, chapter R@10 0.725" from earlier research; this run's fresh
measurement against the same collection, through the new code path, reproduced **0.725** to three
decimal places. That is strong corroboration the implementation does what the decision doc's own
research predicted, not just that it runs without error.

**Row 3 is the "does this hurt corpus-wide paper search" check the decision doc flagged as needing
an answer, not an assumption.** `retrieve()` — what every one of these 210 questions calls — has no
code path through `_cap_per_paper`/`_is_scoped`/`_MAX_HITS_PER_PAPER_SCOPED` at all (see "The two
limits" above), so this result was never in doubt by code inspection alone; it was still measured,
not just reasoned about, per the task's own instruction. Paper recall@10 is **0.976** (205/210
hits), MRR 0.920. Two questions (`Q-116`, `Q-158`) errored with `reranker server returned 413`
(payload-too-large from the TEI vendor service, unrelated to this change — likely a long question
body exceeding a batch/request-size limit) and are counted as misses in the recall denominator, not
excluded; without a pre-change run on this exact collection to diff against, this number stands on
the code-path argument above (this diff never touches anything `retrieve()`'s call graph reaches)
plus the full unit-test suite (below), rather than a second GPU-costly rerun that is guaranteed
byte-identical by construction.

### Honest read of the scoped gain — do not oversell it

The **total** swing from unscoped (0.425) to scoped-with-relaxed-cap (0.725) is **+0.300**, but that
number conflates two separate, already-decided things:

- **+0.225** is `filters={"doc_type":"book"}` alone (Decision 0 in the same doc — already shipping,
  not part of this task, and not something this measurement re-derives; the decision doc's own
  Decision 0 table already documents cap-3/doc_type-book at 0.650, i.e. 0.425 + 0.225).
- **+0.075** is what this task's cap change contributes *on top of* the filter (0.650 → 0.725,
  Decision 2's own isolated number in the decision doc — this run did not re-measure that
  intermediate cap-3/doc_type-book point, only the two endpoints in the table above).

**The measured noise floor at N=40 is ~0.125.** The +0.075 attributable to the cap relaxation is
*below* that floor in isolation — it is suggestive, not established, at this sample size. Its real
value is stated in the decision doc as appearing alongside a future per-document (`paper_id`)
filter (Decision 3, not part of this task), worth roughly +0.175 more. **Do not read +0.075 as a
proven win on its own.** The load-bearing claim of this measurement is row 1 — unscoped behavior
did not move — not the scoped gain.

### IDF note

`exp1_ctrl_sizemerge_idf` already has sparse IDF weighting on. A separate, independently-landing
change (Decision 1 in the same decisions doc) enables IDF on the production `papers` collection.
These measurements were taken on an already-IDF-on collection, so they reflect the post-IDF world
and remain valid regardless of when/whether that separate change lands on production.

## Mutation test

Per the task brief: revert the behavior change, confirm the new tests fail, restore, confirm green.

Done by hand-editing (not `git stash` — this repo's instructions forbid it): replaced the call site

```python
cap = _MAX_HITS_PER_PAPER_SCOPED if _is_scoped(filters) else _MAX_HITS_PER_PAPER
return _cap_per_paper(results, cap)[:k], RetrievalCoverage(candidate_count=len(hits))
```

back to the pre-change

```python
return _cap_per_paper(results)[:k], RetrievalCoverage(candidate_count=len(hits))
```

leaving the new constants/`_is_scoped` helper in place (so only the actual behavior wiring was
undone), then ran `pytest rag/test_retriever.py -k "scoped or is_scoped or ordering or cap_per_paper"`.

**Result: 2 of the new tests failed, exactly as expected:**

```
FAILED rag/test_retriever.py::test_search_papers_scoped_by_doc_type_allows_more_than_unscoped_cap
  - AssertionError: assert 3 > 3
FAILED rag/test_retriever.py::test_cap_per_paper_runs_after_rerank_and_before_k_truncation_when_scoped
  - AssertionError: assert 3 == 5
```

`test_search_papers_unscoped_still_caps_at_three_with_doc_type_filter_absent` and
`test_is_scoped_true_only_when_doc_type_set` stayed green under the revert (as they should — neither
depends on the reverted line). The edit was then restored and diffed byte-for-byte against a
pre-revert backup (`git diff rag/retriever.py > backup; ...edit/restore...; diff backup restored` —
identical), and the full `rag/test_retriever.py` suite re-ran green.

## Full suite + CI

- `python -m pytest -q` (repo `testpaths`: `rag`, `contracts`, `ci/checks`, `fixtures/eval`, `app`,
  `migrations`; 1,389 tests collected): **exit code 0**, no `F`/`E` markers, no "failed"/"error" text
  in output.
- `GITHUB_EVENT_NAME=push python -m ci.run_enforcement`: **PASS**, no violations.

## GPU lock

Acquired `rag.gpu_lock.FileGpuLock` at `Config.gpu_lock_path`
(`/home/omar/ai-projects/research-system-rag/.gpu.lock`, shared across worktrees) before starting
inference, released immediately after acquisition (the real embedder/reranker adapters each
acquire/release it again per call internally, via `app/assembly.py::build_mcp_server`'s own
wiring). **Wait: 0.00008s** — the lock was free; no contention from the concurrent destructive
reindex job at the moment this ran.

## How this was run

```
python -m scripts.scratch_scoped_cap_eval \
  --collection exp1_ctrl_sizemerge_idf \
  --config /home/omar/ai-projects/research-system-rag-data/config.yaml \
  --out /tmp/scoped_cap_measurement_after.json
```

`scripts/scratch_scoped_cap_eval.py` is a throwaway measurement script (marked as such in its own
docstring), written instead of modifying `app/retrieval_eval.py` because that runner never threads
`filters` through to `retrieve()`/`retrieve_papers()`, and this task's instructions were explicit
not to change it. It reuses `app/retrieval_eval.py::load_questions` for the 210-question set's
question-text/blind-sibling join rather than duplicating that logic.
