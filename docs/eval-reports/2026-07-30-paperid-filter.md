# `paper_id` search filter (Decision 3, option A) — measurement — 2026-07-30

`docs/DECISIONS-PENDING-operator.md` Decision 3, option A (operator-approved): add
`paper_id: str | None = None` to `SearchFilters` (`contracts/vector_index.py`), plumb it into the
vector-store payload filter (`rag/vector_index.py`), and extend `_is_scoped()`
(`rag/retriever.py`) so it counts as scoping the same way `doc_type` does.

**Foundation-frozen**: `contracts/` is CODEOWNERS-protected. This change needs the
`foundation-change` label and operator sign-off before merge — see the PR body.

## The change, in one paragraph

`SearchFilters`'s own docstring already says "every field maps to a `VectorPayload` field of the
same name," and `paper_id` **is** a `VectorPayload` field — the shape existed, the filter just
wasn't exposed. Three edits: (1) the new optional field on `SearchFilters`, defaulting to `None`
so every existing construction site keeps working unchanged; (2) one more `FieldCondition` in
`rag/vector_index.py::_qdrant_filter` (the only module allowed to name the vendor,
`CONVENTIONS.md §1`); (3) `_is_scoped()` now returns `True` when either `doc_type` or `paper_id` is
set — its own docstring already anticipated this exact addition and said to add it here.
`_MAX_HITS_PER_PAPER`/`_MAX_HITS_PER_PAPER_SCOPED` themselves are untouched, per the task
constraint — this only widens which filters route a query through the existing relaxed cap.

`FakeVectorStore._passes_filters` got the matching `paper_id` branch (needed for the fakes-based
test suite to exercise the behavior at all), and `rag/mcp_server.py`'s `semantic_search` docstring
— which explicitly said "[`SearchFilters`] has no paper-id field, so this tool alone cannot be
scoped to one paper" — was corrected, along with the same now-false claim in `ARCHITECTURE.md`'s
M8 section and `DATA-CONTRACTS.md`'s `SearchFilters` mirror. Those were stale documentation, not
behavior changes, but leaving a docstring that flatly contradicts the code it's attached to is
worse than not touching it.

## Measurements

All three runs: **production `papers` collection** (372,741 points, sparse IDF on — this task's
honest target per its own instructions), `k=10`, real TEI embedder/reranker (no fakes), read-only
`retrieve_papers()` calls only (no writes to the corpus, no ingest/rechunk/delete/snapshot).
115-question `fixtures/eval/eval_book_questions.json` set (23 questions × 5 books), scored at
chapter-routing level: a hit is `PaperSearchResult.view.paper_id == source_paper_id AND
PaperSearchResult.chapter == gold_chapter_title`, within the top 10 — same hit definition
`app/retrieval_eval.py` and the Decision 2 scratch script already use.

Reproduce: `python -m scripts.scratch_paperid_filter_eval --out /tmp/x.json` (GPU lock acquired
and released cleanly, 0.0001s wait — uncontended at run time; total wall time ~11 minutes for
115 × 3 = 345 retrieval calls against production).

### Overall (n=115)

| configuration | recall@10 | MRR | Δ vs `doc_type="book"` | Δ vs unfiltered |
|---|---|---|---|---|
| unfiltered | 0.487 | 0.349 | — | — |
| `doc_type="book"` | 0.713 | 0.449 | — | — |
| **`paper_id`** | **0.939** | **0.567** | **+0.226** | **+0.452** |

Both baselines reproduce the task brief's "numbers to beat" **exactly** (0.487 unfiltered / 0.713
`doc_type`-scoped) — confirms this script is measuring the same thing, against the same production
corpus, the brief's own numbers came from.

**+0.226 clears the noise floor (~0.125 at N=40; this run is N=115, so the floor here is if
anything tighter) by a comfortable margin — not a marginal call.**

### Per book

| book (`source_paper_id`) | unfiltered | `doc_type="book"` | `paper_id` | Δ (`paper_id` − `doc_type`) |
|---|---|---|---|---|
| `local:14b7e283bdcd` — Trustworthy Online Controlled Experiments | 0.522 | 0.739 | 0.957 | **+0.217** |
| `local:f0929288d4f3` — Causal Inference in Python | 0.435 | 0.652 | 0.783 | +0.130 |
| `local:f6c64e1e8c7d` — Elements of Causal Inference | 0.217 | 0.522 | **1.000** | **+0.478** |
| `local:dfe850b3281a` — Causal Inference and Discovery in Python | 0.435 | 0.696 | **1.000** | **+0.304** |
| `local:54d6ca71dda9` — Causal Inference and ML in Econ/Social/Health | 0.826 | 0.957 | 0.957 | **+0.000** |

(23 questions per book — n is uniform because the 115-question set is exactly 23 × 5.)

**Per-book is the view that catches what the aggregate hides (the explicit lesson this task's brief
draws from T-DOC87): the +0.226 aggregate is not five books each gaining ~0.226.** Two books
(`f6c64e1e8c7d`, `dfe850b3281a`) go from the weakest `doc_type`-scoped baselines in the set (0.522,
0.696) to a **perfect 1.000**. Per the eval fixture's own metadata (`fixtures/eval/
eval_book_questions.json`'s `chapter_split_note`), these are this corpus's two *smallest*
chapter-unit books (8 and 7 units, vs. 16/26/44 for the other three) — under `doc_type="book"`
scoping the candidate pool is drawn from *all five* books' chapters pooled together (106 chapter+
summary units total), so a book with only 7-8 units of its own is easiest for the other four
books' far larger chapter counts to out-rank in the shared rerank pool before a top-`k`
truncation ever sees it. `paper_id` scoping removes that cross-book competition entirely — the
candidate pool is this one book's ~7-8 units alone, so the gold chapter has nothing else to lose
to. This matches the mechanism the task brief itself names for why the measured 0.900 lower bound
is conservative: a real filter pushes scoping into the vector store, not just the pool a caller
sees after the fact.

**`local:54d6ca71dda9` shows a flat +0.000 delta — not a regression, a ceiling.** Its
`doc_type="book"` recall was already 0.957 (22/23), one question short of perfect; `paper_id`
scoping matches it exactly rather than improving it. This book's own chapter-recall was never the
problem `doc_type="book"` under-served, so there was no room for `paper_id` to add. One book at
n=23 sitting flat inside a 5-book set otherwise showing +0.13 to +0.48 is consistent with a real,
book-dependent effect, not noise erasing the gain — but it's also the one number here worth a
second look if this book's chapter split changes later (T-DOC80/81 chapter-routing work).

`local:f0929288d4f3`'s +0.130 delta is the narrowest margin above the noise floor of the five
(0.130 vs. ~0.125) — real per-book N here is 23, not the 40 the floor was measured at, so this
book's own delta carries less statistical weight than the aggregate's +0.226 does. Flagging rather
than rounding it up to "clearly beats the floor" the way the other four books do.

## Mutation tests

Per the task's own instruction: prove the two claims that matter have teeth, not just that the
tests pass.

**(a) Restriction claim — remove `paper_id` from the payload-filter construction
(`rag/vector_index.py::_qdrant_filter`).** With the `paper_id` branch commented out:

- `rag/test_vector_index.py::test_qdrant_filter_paper_id` — **FAILED**
  (`AttributeError: 'NoneType' object has no attribute 'must'` — with no other filter set, an empty
  `SearchFilters(paper_id=...)` now produces no filter at all).
- `rag/test_vector_index.py::test_qdrant_filter_paper_id_combines_with_doc_type_and_kind` —
  **FAILED** (the expected `paper_id` `FieldCondition` is simply absent from `f.must`).
- `rag/test_vector_index.py::test_real_adapter_satisfies_contract[assert_filters_by_paper_id]` —
  **FAILED** against a live local Qdrant service (`assert ['a', 'b'] == ['b']` — both documents
  came back, the wrong one included).
- `rag/test_vector_index.py::test_real_adapter_satisfies_contract[assert_filters_by_paper_id_combines_with_doc_type_and_kind]`
  — **FAILED** (`assert ['match', 'wrong_paper'] == ['match']`).

Restored the code; all four green again.

**(b) Relaxed-cap claim — remove `paper_id` from `_is_scoped()`
(`rag/retriever.py`, reverting to `filters.doc_type is not None` only).** With that mutation:

- `rag/test_retriever.py::test_is_scoped_true_when_doc_type_or_paper_id_set` — **FAILED**
  (`assert False is True` — `_is_scoped(SearchFilters(paper_id="local:abc123def456"))` came back
  `False`).
- `rag/test_retriever.py::test_search_papers_scoped_by_paper_id_allows_more_than_unscoped_cap` —
  **FAILED** (`assert 3 > 3` — a `paper_id`-scoped search of a 9-hit paper (1 whole-book summary +
  8 chapters) got capped back down to the unscoped `_MAX_HITS_PER_PAPER=3` instead of the relaxed
  50).

Restored the code; both green again.

Both mutations were reverted immediately after confirming the failure and the full suite was
re-run green (see below) — no mutation is left in the tree.

## Test suite / CI

- Full suite: **1461 tests, 0 failures, 0 errors, 0 skipped** (`pytest --junitxml`).
- `GITHUB_EVENT_NAME=push python -m ci.run_enforcement` — **PASS**, checks (a)-(d), (f)-(h); check
  (e) (the `foundation-change` label) is a `pull_request`-only check and correctly reports
  "skipped" on this local `push`-style dry run — it will run for real once the PR is opened.

## `McpServer` — verified, not assumed

`rag/mcp_server.py`'s `McpServer.semantic_search`/`search_papers` both take `filters:
SearchFilters | None` and pass it straight through to `Retriever.retrieve()`/`retrieve_papers()`
(`results, retrieval_coverage = self._retriever.retrieve(query, filters, self._resolve_k(k))`,
same for `retrieve_papers`) — no field-by-field reconstruction, no allowlist of recognized filter
fields. **This layer needed no code change**: a caller passing `SearchFilters(paper_id=...)`
already flows through untouched, confirmed by reading both methods in full rather than assumed
from the type signature alone. The only change at this layer was `semantic_search`'s own docstring,
which had explicitly and now-incorrectly claimed `SearchFilters` had no `paper_id` field — a stale
comment left in place would have actively misled the calling agent this docstring is written for.

## Verdict

**`paper_id` scoping beats `doc_type="book"` by +0.226 overall — well past the ~0.125 noise
floor — and both mutation tests confirm the two load-bearing pieces of code (the payload filter,
the scoped-cap trigger) actually do the work the tests claim.** Per-book, four of five books show
a genuine, non-trivial gain (+0.130 to +0.478); the fifth is flat at a ceiling `doc_type="book"`
had already nearly reached, not a regression. This clears the criterion the task set: the contract
change earns its keep. `contracts/` is CODEOWNERS-protected — recommend merging under the
`foundation-change` label with operator sign-off, per Decision 3 option A.
