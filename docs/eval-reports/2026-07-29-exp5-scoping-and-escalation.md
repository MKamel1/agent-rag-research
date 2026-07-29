# Experiment 5 — scoping ceiling + Self-Route-style escalation — 2026-07-29

Two tasks against the same 40-question, 5-book fixture (`fixtures/eval/eval_book_questions.json`),
`k=10`, collection `exp1_ctrl_sizemerge_idf` (372,741 points, IDF on). Full per-question detail:
`2026-07-29-exp5-scoping-and-escalation.json`. Code: `app/escalation_eval.py` +
`app/test_escalation_eval.py` (14 fake-based unit tests, zero GPU/network).

## Task A — the scoping ceiling

### Method

All three variants call `Retriever.retrieve_papers()` — never a `contracts/` change:

1. **No filter**: `retrieve_papers(query, filters=None, k=10)`.
2. **`doc_type="book"`**: `retrieve_papers(query, filters=SearchFilters(doc_type="book"), k=10)`.
3. **Gold-book-scoped**: `retrieve_papers(query, filters=SearchFilters(doc_type="book"), k=32)`
   through the **normal public method**, then post-hoc keep only rows whose `paper_id` is the
   question's gold paper, take the first `min(len, 10)`. `k=32` isn't an arbitrary "large" choice:
   `retrieve_papers`'s candidate pool is `max(k, rerank_pool_size)`, `rerank_pool_size` is clamped
   to 32 (`app/assembly.py`, TEI's own hard batch-size ceiling), and `TeiReranker.rerank()`
   truncates its candidate batch to the first 32 unconditionally (`rag/reranker.py`
   `_MAX_BATCH_SIZE`) — no `k` above 32 changes the output at all, so 32 is this pipeline's real
   ceiling, not a tuning choice.

### The confound in variant 3 — read this before trusting the "0.000 gap" number

Because variant 3 goes through the **public** `retrieve_papers()`, `rag/retriever.py`'s
`_cap_per_paper` (`_MAX_HITS_PER_PAPER = 3`, T-DOC82) runs **inside** that call, before the
post-hoc gold-paper filter ever sees the results. At most 3 of the gold book's chapters can appear
in what gets filtered down — the exact same cap the `doc_type="book"` arm is also subject to.
`gold_book_scoped_chapter` came back **numerically identical** to `doc_type_book_chapter` (0.650
both, matching per book too), which is consistent with either "a `paper_id` filter adds nothing"
or "the shared cap of 3 is binding in both arms and hides whatever it would add" — this
measurement cannot tell those two apart.

An independent measurement (not reproduced here, per instruction not to duplicate it) found that
relaxing the cap from 3 to 10, still under `doc_type="book"`, raises chapter R@10 from 0.650 to
**0.725** — with no `paper_id` filter involved at all. That confirms the cap, not filter
tightness, is doing real work here, and it reopens (rather than closes) the question this task set
out to answer: **whether a `paper_id` filter adds anything on top of a properly-sized cap remains
unmeasured.** Do not read this report as having closed that question.

### The three numbers, overall and per book

| scope | overall chapter R@10 | overall MRR |
|---|---|---|
| no filter | **0.425** (reproduces the established baseline) | 0.274 |
| `doc_type="book"` | **0.650** (reproduces the established number) | 0.344 |
| gold-book-scoped (confounded — see above) | **0.650** (identical to the row above) | 0.442 |

| book | no filter | `doc_type="book"` | gold-book-scoped |
|---|---|---|---|
| Trustworthy Online Controlled Experiments | 0.625 | 0.750 | 0.750 |
| Causal Inference and ML in Econ/Social/Health | 0.625 | 0.750 | 0.750 |
| Causal Inference and Discovery in Python | 0.375 | 0.750 | 0.750 |
| Causal Inference in Python | 0.250 | 0.500 | 0.500 |
| Elements of Causal Inference | 0.250 | 0.500 | 0.500 |

Recall is identical between `doc_type="book"` and gold-book-scoped in **every** book, not just in
aggregate — strong evidence the two arms hit the same cap-bound ceiling, not that scoping is
inert.

**A real, uncomfounded finding buried in the same numbers: MRR moved (0.344 → 0.442) while recall
did not.** Under a fixed 3-per-paper cap, scoping to one book can only reorder the same (≤3,
already hit-or-miss) candidates from that book ahead of other books' competing chapters in the
ranking — it cannot introduce a 4th candidate the cap excluded from the pool. That is the
mechanical signature of a **ranking-position** effect, not a **candidate-set** effect. The
complementary fact — that raising the cap (the reviewer's 0.650→0.725 number) moved *recall*, not
just MRR — places the real remaining fix in the candidate-set stage (the cap), not in reranking.

### Paper-level ceiling (0.750) and the two-stage projection

`app/retrieval_eval.py`'s standard run (`Retriever.retrieve()`, passage-level, `filters=None`)
reproduces the programme's established **paper-level recall of 0.750** exactly — this is the
natural ceiling on any "find the book, then route within it" two-stage strategy's first stage.

**Projection** (arithmetic, not a measurement): `stage1(0.750) × stage2(0.650) = 0.4875`.

This projected two-stage number is *lower* than what `doc_type="book"` filtering already achieves
in one shot (0.650). An imperfect book-picking stage (75% accurate) throws away answer mass that a
one-shot filtered search never gambles on — one-shot search lets every book's chapters compete
directly and lets rerank sort out the winner, instead of committing to one book up front and
failing outright 25% of the time. **This qualitative conclusion is not sensitive to the cap
confound above** — it only uses the two clean numbers (0.750, 0.650), whatever mechanism explains
the 0.650. **Recommendation: do not build two-stage book-then-chapter routing.**

## Task B — escalation vs. the falsification bar

### Method

`app/escalation_eval.py`: one unfiltered `retrieve_papers()` call; escalate (retry once with
`SearchFilters(doc_type="book")`) iff the top hit's `doc_type` isn't `"book"` (or there were no
hits at all) — a signal read straight off `search_papers`' own response, no gold label involved.
At most one retry, per Experiment 5's "one allowed escalation" framing.

### Bar

The brief's original bar was 0.650 (`doc_type="book"` on every call, cap=3). **That bar is revised
upward to 0.725** — `doc_type="book"` measured at a relaxed per-paper cap (10 instead of 3),
reported by the task reviewer and not independently reproduced here per instruction. Escalation
must beat whichever single-shot configuration is actually best available, not a stale one.

### Result

| configuration | chapter R@10 |
|---|---|
| no filter | 0.425 |
| escalation (60.0% of questions escalated) | **0.575** |
| `doc_type="book"` always (cap=3) | 0.650 |
| `doc_type="book"` always (cap=10, reviewer-reported) | **0.725** |

**Escalation fails both bars.** It beats the unfiltered baseline (0.425 → 0.575), which the brief
explicitly rules out as sufficient: *"Beating 0.425 only proves the filter works."* It does not
beat either always-filter configuration.

### Why always-filter wins

Every gold answer in this fixture is `doc_type="book"`. Filtering to books can only narrow the
candidate pool toward the right answer or leave it unchanged for a book question — it has no
mechanism to hurt one. Any policy that sometimes skips the filter (escalation's heuristic skips it
for the 40% of questions whose unfiltered top hit already looked book-shaped) forgoes whatever the
filter would have added on exactly those questions. The measurement shows that forgone value
exceeds what the other 60% gained by escalating: always-filtering dominates adaptive escalation on
this fixture.

## Recommendation

- **Ship:** always pass `filters={"doc_type": "book"}` for book-shaped queries (already the
  documented `search_papers` guidance — this just confirms the eval harness should exercise it,
  which it never had). Measured value: +0.225 chapter R@10 over unfiltered (0.425 → 0.650), zero
  extra retrieval calls, versus escalation's +0.150 (0.425 → 0.575) at the cost of a second call on
  60% of questions and a result that still trails always-filtering.
- **Do not ship:** Self-Route-style escalation logic in the MCP consumer pattern — it does not
  clear either falsification bar. Do not ship two-stage "pick a book, then route within it"
  retrieval — the projection shows it loses to one-shot filtering even at the most favorable
  available stage-1 number.
- **Open, not resolved by this report:** whether a dedicated `paper_id` field on `SearchFilters`
  (a foundation-frozen `contracts/` change) is worth proposing. This report's gold-book-scoped
  measurement is confounded by the shared `_MAX_HITS_PER_PAPER=3` cap and cannot answer that
  question. The cap itself (`rag/retriever.py`, not `contracts/`, not foundation-frozen) is the
  cheaper lever to investigate first — the reviewer's cited 0.650→0.725 delta from a cap raise
  alone, with no `paper_id` filter involved, suggests it should be tuned and re-measured before any
  `contracts/` change is proposed on top of it.
