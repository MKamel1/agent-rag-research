# Book RAG experiment plan

> **HISTORICAL** — executed; superseded by docs/BOOK-INTEGRATION-CLOSEOUT.md + eval-reports. Current state: [PROJECT-STATUS.md](PROJECT-STATUS.md).

*2026-07-28. Companion to `docs/RESEARCH-book-rag-established-methods.md` (the evidence this plan
acts on) and `docs/METHODS-books-and-chunk-quality.md`/`docs/DESIGN-book-chapters-and-hierarchy.md`
(the internal plan this pressure-tests). Written so a later implementer can execute without
redesigning it.*

---

## 0. What this plan reuses instead of building

Per the brief's instruction that reuse beats building, three existing tools cover most of what's
needed:

- **`app/retrieval_eval.py`** (on `origin/feat/book-retrieval-eval`, not yet merged) already scores
  paper/passage/chapter recall+MRR, breaks out `by_doc_type`, and accepts `--collection` to point
  at a throwaway vector-store collection — this is the scoring harness for every experiment below.
  Nothing here proposes a new metric or a new runner.
- **`app/reembed_experiment.py`** is the exact shape needed for a matched A/B re-embed: reads
  `paper_ids` from the corpus, writes into a named non-production `--collection`, refuses to touch
  `Config.collection` by accident. Experiment 2 (contextual retrieval) reuses it directly.
  Experiment 1 (chapter re-split) needs the same *shape* (read corpus, write throwaway collection)
  but a different payload (`ChapterSummary`, not chunk vectors) — see Experiment 1's tooling note.
- **`app/rechunk.py`** is the precedent for "retrofit a fix onto already-stored papers from
  `blocks`, without re-parsing" — relevant if Experiment 1 needs to regenerate `ChapterSummary`
  records for the 5 books without re-running MinerU (it doesn't; `blocks` are untouched by a
  chapter-splitter change, same as `rechunk.py`'s own rationale for chunk-splitter changes).

No new eval runner, no new A/B script skeleton is proposed. Where an experiment needs something
neither tool does today (Experiment 1's `ChapterSummary`-shaped upsert), it's called out explicitly
as the one piece of new tooling, sized in LOC terms, not hand-waved.

---

## 1. The eval set

### Current state

15 questions, 2 books (`local:14b7e283bdcd` Trustworthy OCE, no outline; `local:f0929288d4f3` CI in
Python, 223-entry outline), `fixtures/eval/eval_book_questions.json`. Every question already
carries `gold_chapter_title`, `gold_chunk_id`, `gold_block_id`, `excerpt_block_id`, `section_path`,
`page`, `passage_excerpt` — a `Question` schema that already supports all 5 books and all
experiments below without a shape change.

### Extending to 5 books

**Per-book count.** Match the existing set's density (15 questions / 2 books ≈ 7-8/book) rather
than inventing a new target: **8 questions per book × 5 books = 40 questions**, sampled the same
way the existing 15 were — "chapters sampled across the full chapter range (not just first/last)"
per the fixture's own `authoring_method` metadata. This lands inside the design doc's original
"~40-60" estimate without over-committing to the top of that range before Experiment 0 (below)
tells us whether 40 is even enough to see anything.

**Authoring method — preserve exactly, per book:**
1. Read a book's `ChapterSummary.text`/`title` rows read-only from `papers.db` (`file:...?mode=ro`)
   to find a chapter with a concrete, quotable, checkable fact (a number, a named law, a specific
   claim) — not a vague "explains regression" chapter.
2. Read that chapter's source `blocks` read-only (via the *current* `_split_chapters()`, unmodified
   — this fixes gold labels to *today's* split, exactly as the existing 15 do, and exactly as
   Experiment 1 below re-derives against the *new* split rather than assuming carryover).
3. Write the question from the quoted block's content. **The question is written and locked before
   any `search_papers`/`semantic_search` call is made against it.** This is the one discipline that
   must not be relaxed, because it's the only thing standing between this eval set and encoding our
   own retrieval assumptions.
4. Record `gold_chunk_id`/`gold_block_id` as the fact-bearing block's *owning chunk's anchor block*
   (not the fact block itself) — same convention as the existing 15, for the same reason
   (`rag/chunker.py` anchors a chunk to its first block, so scoring against the literal fact block
   is unwinnable by construction, not a retrieval miss).

**Fields each question carries** (no schema change — `Question`/the JSON fixture shape already
supports all of this): `question_id`, `question_text`, `answer_text`, `doc_type="book"`,
`source_paper_id`, `source_paper_title`, `question_type`, `gold_chapter_title`,
`gold_chapter_index`, `gold_chunk_id`, `gold_block_id`, `excerpt_block_id`, `section_path`, `page`,
`passage_excerpt`.

**Guarding against encoded assumptions**, beyond the "write before retrieval" rule already in
place:
- Sample chapters **across the full range** per book, not clustered at the start (front matter is
  disproportionately represented if you only sample the first few chapters, and front matter is
  exactly where Experiment 1's outline-join risk concentrates per the research doc's Area 3
  finding — sampling only early chapters would bias the eval toward the case Experiment 1 is
  *least* confident about).
- At least 1-2 questions per book should target a fact that appears in a *mid-content* section
  (not a section-opening claim), since M4's title-scoring failure mode ("every heading in a window
  is mid-content") and Q1's outline-boundary risk both concentrate around ambiguous section
  membership, not clean chapter openings.
- The same author (or reviewer) who writes a question should not also be the one who later
  interprets a borderline scoring result — not enforced by tooling, stated here so it isn't
  silently skipped under time pressure.

### What N is actually needed — and the honest answer

The brief asks for a stated N with power reasoning, not just a round number. Two-proportion power
calculation (standard formula, computed here for this task — not a literature citation, shown so
the arithmetic can be checked):

```
n per arm ≈ [ z_(α/2)·√(2p̄(1−p̄)) + z_β·√(p1(1−p1)+p2(1−p2)) ]² / (p1−p2)²
```

Plugging in the baseline's actual chapter-routing recall (p1 = 0.467) against a plausible
"outline wins" target (p2 = 0.65, a 18-point swing — roughly what M3-vs-M4's title-quality jump
looked like qualitatively), α = 0.05 (z=1.96), power = 0.80 (z=0.84):

- p̄ = 0.5585, √(2·p̄·(1−p̄)) = 0.7024
- √(p1(1−p1) + p2(1−p2)) = √(0.2489 + 0.2275) = 0.6902
- n ≈ (1.96·0.7024 + 0.84·0.6902)² / (0.467−0.65)² ≈ (1.9565)² / 0.0335 ≈ **114 questions**

That's an independent-samples approximation (conservative — a matched/paired design, same
question scored under both splitters, McNemar-style, would need somewhat fewer since it only
counts *discordant* answers). But even halving it for the paired-design efficiency gain lands
well north of 40, and north of the design doc's own upper estimate of 60.

**Say the honest thing:** **40-60 hand-written questions cannot reliably distinguish an 18-point
chapter-routing swing at conventional significance.** They can detect a much larger swing (e.g.
0.467 → 0.80+) by eye, and they're enough to catch a gross regression or a clear qualitative win
(all-front-matter-book routes correctly now, or every question on the outline-less book gets
*worse* — that kind of thing doesn't need a power calculation to see). What they cannot do is
adjudicate a close call.

**What to do about it, concretely** (this is where the synthetic-question-generation research
finding earns its keep): the research doc's Area 6 finding is that synthetic LLM-generated
questions reliably rank *retriever configurations* against human baselines — which is exactly
Experiment 1/2's shape (A/B two index configs, not comparing generator quality). So: **keep the
40-question hand-written core set as the trusted, assumption-audited signal**, and if Experiment 1
comes back as a close call (neither a clear win nor a clear loss on the hand-written 40), generate
an LLM-authored supplementary set (same schema, same per-book distribution, explicitly labeled
`"authoring_method": "synthetic"` in its own fixture file, never merged into the hand-written
fixture) to push toward the ~114-question power target *before* concluding the outline is
"aesthetic, no better than size-merge" — the exact failure mode the design doc's Q2 falsification
criterion warns against rationalizing past. If even the combined hand-written+synthetic set still
can't separate the two splitters, that itself is the answer: report "no measurable difference at
N≈100+" rather than picking a winner on 40 questions' worth of noise.

---

## 2. Named experiments

Numbered in the order they should run (see §3 for the dependency reasoning). Each states
hypothesis, exact comparison, metrics, the number to beat, and a pre-committed falsification
criterion.

### Experiment 0 — Extend the eval set and re-run the existing baseline on all 5 books

**Hypothesis:** none — this is instrumentation, not a test. Needed before Experiment 1 can mean
anything, because the current baseline (`docs/eval-reports/2026-07-28-book-retrieval-baseline.md`)
only covers 2 of 5 books.

**Exact comparison:** N/A. Run `app/retrieval_eval.py --ground-truth
fixtures/eval/eval_book_questions_5book.json --k 10` against the **unmodified, current** chapter
split (today's M3/M4 size-merge output, already ingested for all 5 books) and record per-book and
overall paper/passage/chapter recall+MRR, same report shape as the existing baseline doc.

**Metrics:** paper/passage/chapter recall@10, MRR@10 — reuses `build_report`'s existing
`by_doc_type` breakdown unchanged.

**Number to beat:** N/A (this *produces* the number everything else is measured against, extended
from 2 books to 5).

**Falsification criterion:** N/A.

**Cost:** Zero GPU, zero ingestion — purely a question-writing task (§1) plus running the existing
eval script read-only against the live corpus. Wall clock: the question-authoring is the actual
cost (reading ~5×8 = 40 chapter summaries + source blocks, one sitting), the eval run itself is
seconds against an already-embedded, already-served collection.

**Can this be simulated without building anything?** It **is** the "nothing to build" case — no
ingestion, no migration, no schema change, no re-embed. Pure read-only harness use.

---

### Experiment 1 — Q1/Q2: outline-based chapter split vs. size-merge (A1 vs. A2/A3)

**Hypothesis:** Using `pypdfium2.get_toc()` outline entries as chapter boundaries (A1) beats
today's size-merge heuristic (A2, M3+M4) on chapter-routing recall, for the 4 books that ship an
outline.

**Exact comparison:** Same 5-book, 40-question eval set (Experiment 0's set), same `k=10`, same
retriever/embedder/reranker config — the **only** thing that varies is which chapter-splitting
function produced the `ChapterSummary` rows that got embedded. Concretely:
1. Build an outline-based `_split_chapters()` equivalent (new function, not a rewrite of the
   existing one — A2 must stay available per the design doc's own "A1 helps 4 of 5 books... A2
   can't be deleted" risk note) that maps `pdf.get_toc()` entries onto `blocks` via page anchors.
2. Run `summarize_book()` (unmodified — only its `_split_chapters` input changes) against the new
   splits for the 4 outline-bearing books, producing new `ChapterSummary` records.
3. Embed those into a **throwaway collection** (`app/reembed_experiment.py`'s pattern: never the
   production collection, refuses to run if pointed at `Config.collection`).
4. Re-run `app/retrieval_eval.py --collection <throwaway>` against the same 40-question set,
   **re-deriving `gold_chapter_title`/chapter-membership fields against the new split first** (the
   existing fixture's own `chapter_split_note` already documents that this re-derivation is
   required, block-level provenance unchanged, chapter labels not carried over).

**Metrics:** chapter-routing recall@10 and MRR@10, overall and **per book** (the outline-vs-no-
outline split matters more than the overall number, since the one book without an outline, OCE, is
untouched by this experiment and should show ~0 change — a useful built-in sanity check: if OCE's
number moves, something in the harness broke, not the splitter).

**The number to beat (stated in the existing design doc, restated here unchanged so it can't be
rationalized later):** chapter routing recall@10 = 0.467 overall, 0.286 on CI in Python
specifically (the 223-entry-outline book). Once Experiment 0 extends the baseline to 5 books, use
the 5-book baseline number instead — the 2-book number above remains the reference until then.

**Falsification criterion (pre-committed):** if outline-based chapters (A1) do not beat size-merge
(A2) on chapter-routing recall, for the outline-bearing books, **at the power level established in
§1** (i.e., a difference that survives being checked against N≈100+ if the 40-question result is a
close call) — **A1's structural correctness is aesthetic and A2 wins.** Do not ship A1 on the
strength of "it's obviously more correct" alone; that is precisely the rationalization this
criterion exists to block. This also settles A3 (repair the marker-regex Strategy A) without
running it: if A1 doesn't clear this bar either, A3 is doubly not worth building (it was already
deprioritized as "superseded if A1 lands" — a losing A1 makes repairing the thing A1 was meant to
replace even less justified, not more).

**Ordering and dependencies:** depends on Experiment 0 (needs the 5-book eval set) and needs the
one piece of new tooling flagged in §0 — an outline-to-block-page join function and an
outline-based `_split_chapters` equivalent. **Prove the join on one book's front matter first**
(the research doc's Area 3 finding: page-offset drift concentrates in front matter/preface
pagination) before running it across all 4 outline-bearing books — this is the design doc's own
"prove it on one book before committing" requirement, sharpened by external evidence to specify
*which part of the book* to prove it on first.

**Cost:** Re-summarizing chapters for 4 books (101 existing chapters total across all 5, so
roughly 85-95 chapters need re-summarizing under the new split — the exact count depends on how
many outline-derived units result) is the same order of magnitude as the original book ingestion's
summarization pass — hours, not days, since it's chapter-level map-step calls against already-
parsed `blocks`, no re-parsing (MinerU is untouched). Embedding ~90 chapter summaries into a
throwaway collection: minutes. **No schema migration, no `contracts/` change** — `ChapterSummary`
already has everything needed; this experiment only changes which function produces its inputs.

**Requires re-embedding?** Only the ~90 chapter-summary vectors, not the corpus's 11,026 papers or
even the 5 books' 1,939 chunks — chunk-level vectors are untouched, since chapter splitting only
affects `summaries`, never `chunks`.

**What can be simulated read-only, without any ingestion:** the outline-to-block **join itself**
can be prototyped and sanity-checked entirely read-only — read `blocks` via the RO connection,
compute the proposed new chapter boundaries, and check plausibility (unit count, word-share, front-
matter handling) exactly the way `docs/DESIGN-book-chapters-and-hierarchy.md` Part 4's sequencing
already calls for, **before** spending any summarization/embedding budget. This is the cheapest
possible negative result: if the join produces implausible boundaries (e.g., a "chapter" that's
90% of the book because two outline page numbers collided), that's discoverable in minutes with no
GPU involved, and should stop the experiment before step 2 above runs.

---

### Experiment 2 — Contextual Retrieval, book-scoped (T-DOC41 revival)

**Hypothesis:** Prepending a short LLM-generated context blurb to each of the 5 books' chunks
before embedding improves passage recall, and this book-scoped re-run is properly powered where
the original T-DOC41 paper-scale spike (n=40 questions, 809 papers) was not.

**Exact comparison:** `app/reembed_experiment.py --with-headers` vs. `--no-headers`, restricted to
the 5 books' `paper_ids` (not the full corpus), into two throwaway collections, scored by
`app/retrieval_eval.py` against the same 40-question set's `gold_block_id`/passage-level scoring
(chapter-routing is not affected by this experiment — it doesn't touch `ChapterSummary` at all).

**Metrics:** passage recall@10, MRR@10 — the metric T-DOC41 already used, restricted to `doc_type`
book questions via the existing `by_doc_type` breakout so this doesn't need a new eval set beyond
Experiment 0's.

**Number to beat:** passage recall@10 = 0.600 overall (2-book baseline; use the Experiment 0
5-book number once it exists), and T-DOC41's own paper-scale result as context (+0.025 recall,
+0.047 MRR, inside the noise band at n=40) — this experiment's whole point is finding out whether
the same technique, on a smaller, more homogeneous (book-only) question set, produces a *clearer*
signal than the paper-scale spike did, not a bigger one.

**Falsification criterion:** if headered passage recall is not measurably better than baseline at
this experiment's own achievable N (40 book questions — smaller than T-DOC41's original 40, but
now book-only rather than mixed with paper questions, which should reduce variance even at the
same N) — **treat this exactly as T-DOC41 already is: HOLD, not rejected**, and do not spend
further GPU budget scaling it to the full corpus until a properly-powered (~100+) book-only eval
exists. This experiment is explicitly *not* trying to resolve T-DOC41's open status corpus-wide —
only to get a second, cheaper data point for the book-specific case.

**Ordering:** independent of Experiment 1 (touches `chunks`, not `summaries`) — can run in
parallel, but should be **sequenced after** Experiment 1 in practice, because Experiment 1 targets
the metric (chapter routing) the baseline shows is actually weak; this experiment targets a metric
(passage recall) that's already the *stronger* of the two. Fixing the worse number first is the
higher-value use of the same GPU budget.

**Cost:** ~1,939 chunks (5 books) vs. T-DOC41's 809 papers (each paper being far larger than one
book chunk-for-chunk, but each *header call* here is against a chapter-scale document, not a
whole-book document, so per-call cost is comparable to T-DOC41's per-paper cost) — order 1-3
GPU-hours per arm, matching the research doc's estimate. Two arms (headers on/off) = order 2-6
GPU-hours total, a single afternoon, not the ~18 GPU-days the 30k-paper full-corpus case would
cost.

**Requires re-embedding?** Yes, but only the 5 books' ~1,939 chunk vectors, into throwaway
collections — never the production collection, never the other 11,021 papers.

**Foundation/contract touch:** none. `chunks.contextual_header` column already exists
(migration already landed per DATA-CONTRACTS, currently always NULL) — this experiment can
populate it for the 5-book throwaway run without a new migration; whether to ever write it into
the *production* row is a separate go/no-go this experiment doesn't need to resolve.

---

### Experiment 3 — Hierarchy simulation (Q3), read-only, no build

**Hypothesis:** A Part → Chapter hierarchy (H1: `parent_summary_id` + `level` on `summaries`)
improves routing over a flat list of the same chapters — or it doesn't, and H1 shouldn't be built.

**Exact comparison:** This is explicitly a **simulate-before-build** experiment per the design
doc's own Part 3 Step 3, and the research doc found no external paper that measures this specific
comparison (hierarchical vs. flat chapter routing for an agent consumer) — so there's no external
number-to-beat, only the internal one. Simulate by: for the 4 outline-bearing books (which carry
real Part/Chapter/Section levels in `pdf.get_toc()`, 2-4 levels deep per the design doc's table),
construct the parent/level relationship **in memory** from the outline data already read for
Experiment 1, without writing it to `summaries` or migrating anything. Score chapter routing two
ways against the *same* embedded chapter vectors from Experiment 1: (a) as already scored — flat,
top-`k` over all chapters regardless of level; (b) simulated two-step — first route to the
top-level Part (scored against a query embedding of the Part's own top-level outline entry text,
computed but never persisted), then only consider that Part's child chapters for the chapter-level
score. This tests whether hierarchy *as a routing strategy* helps, without touching the schema.

**Metrics:** chapter routing recall@10/MRR@10 under (a) flat vs. (b) simulated-hierarchical, same
40-question set.

**Number to beat:** Experiment 1's own result (whatever A1 achieves flat) — H1 only earns its
schema migration if hierarchical routing beats *flat outline-based* routing, not if it merely beats
the *original* M3/M4 baseline (that comparison would conflate two different improvements and not
tell you which one is doing the work).

**Falsification criterion:** if simulated hierarchical routing does not beat Experiment 1's flat
outline-based routing, **do not build H1** — the design doc already states this framing
("Hierarchy... should be evaluated as its own question... simulating the hierarchy in the eval
harness before committing to a migration"); this plan just makes the simulation mechanism concrete
enough to execute (compute Part-level embeddings ad hoc, don't persist them) rather than leaving it
as an intention.

**Ordering:** strictly gated on Experiment 1 (needs A1's chapter vectors to exist first — there's
no hierarchy to simulate over M3/M4's flat, unlabeled-by-level split). This is the clearest
sequencing dependency in the whole plan.

**Cost:** Near-zero beyond Experiment 1's already-paid cost — a handful of additional embedding
calls (one per top-level Part per book, computed ad hoc, not stored) and a scoring-logic change in
a throwaway analysis script, not in `app/retrieval_eval.py` itself (no need to touch the harness
for a simulation that's testing an idea, not shipping a feature).

**Foundation/contract touch:** **none, by design** — that's the entire point of simulating first.
If Experiment 3 says hierarchy helps, *then* H1's `parent_summary_id`/`level` migration
(`migrations/`, foundation-protected, needs human sign-off per CODEOWNERS) and the `ChapterSummary`
contract change (also foundation-protected) become justified future work — explicitly **not**
part of this plan's scope to implement.

---

### Experiment 4 — Section-aware boost/filter (Q4)

**Hypothesis:** Boosting or filtering `semantic_search` results by `section_path` type (favoring
Method/Results-shaped sections over Introduction-shaped ones) improves passage recall or precision
for the question types where it should matter (methods/results-seeking questions, a subset of
`question_type` in the eval set).

**Exact comparison:** Add a boost/filter step in `Retriever.retrieve()` gated behind a config
flag or a throwaway code path (not shipped to production during the experiment), scored against
the same `question_type`-broken-out metrics `build_report` already produces (`by_question_type`
already exists in the harness output — no new breakdown needed, just questions tagged with a
`question_type` that lets Method/Results-seeking questions be isolated, which the existing schema
already supports).

**Metrics:** passage recall@10/MRR@10, broken out by `question_type`, boosted vs. unboosted.

**Number to beat:** current passage recall (0.600 2-book baseline / Experiment 0's 5-book number),
specifically on the subset of question types this is meant to help — an aggregate-only comparison
would dilute a real effect on a minority of questions into noise.

**Falsification criterion:** if boosting doesn't measurably help the targeted question-type subset
at whatever N that subset has (likely small — a handful of the 40 questions, which is itself a
power problem worth flagging honestly rather than glossing over), **don't ship it as a retrieval-
time change**; it remains a documented idea (T-DOC64) without measured support, same status as
today.

**Ordering:** "should ride along with Q1/Q2" per the existing design doc, because it needs the
same harness — practically, this means running it in the **same Experiment 0/1 sitting**, not as a
separate multi-week effort, since the marginal cost of also tagging question types and adding a
boost path is small once the harness and 5-book eval set already exist.

**Cost:** Cheap — no re-embedding, no migration; `section_path` is already stored on every chunk.
Pure retrieval-logic change plus eval-question tagging.

**Requires re-embedding?** No.

---

### Experiment 5 — Self-Route-style agent escalation (new, from the research doc's Area 4/7 finding)

**Hypothesis:** Letting the agent (not the index) decide whether a `search_papers`/
`semantic_search` result is sufficient, and escalate to `get_span` across more of a chapter when
not, recovers some of chapter-routing's residual miss rate regardless of which splitter (M3/M4 or
A1) is in production.

**Exact comparison:** This is a **consumer-side prompting experiment**, not an index change — it
can't be scored by `app/retrieval_eval.py` as-is, since that harness scores raw retrieval hits, not
agent-mediated multi-call sessions. Scoring this properly needs an agent-loop harness (issue
`search_papers`, decide "is this chapter plausible," optionally call `get_span` on neighboring
blocks, then re-answer) — **this is the one experiment in this plan that is not just a reuse of
existing tooling**, and is flagged as such rather than glossed over. Sized: a thin wrapper script
(order 100-150 LOC) around the existing MCP server calls plus a fixed decision prompt, scored by
whether the *final* answer after up to one escalation matches `gold_chapter_title`/`gold_block_id`
— not a new metric, an extra scoring pass using the same gold fields.

**Metrics:** chapter routing / passage recall **after one allowed escalation**, compared to the
same metrics with zero escalation (today's numbers) — the delta is the whole result.

**Number to beat:** the no-escalation baseline (whichever splitter is in production at the time
this runs — Experiment 1's winner, if it has landed).

**Falsification criterion:** if allowing escalation doesn't recover a meaningful fraction of the
misses at whatever splitter is current, the residual error is not a "the agent needs a second
chance" problem, and this is not worth building into the MCP consumer pattern — drop it, don't
retrofit escalation logic into the production agent prompt on a hunch.

**Ordering:** should run **last**, after Experiment 1 has picked a splitter — testing escalation
against a splitter that's about to be replaced wastes the (small) effort building the scoring
wrapper.

**Cost:** No GPU-heavy cost (no re-embedding), but real engineering cost (the one new script this
plan asks for) — cheapest to defer until the splitter question is settled, so it's evaluated once,
not twice.

**Requires re-embedding / migration?** No. Pure agent-orchestration/prompting layer on top of the
existing MCP surface.

---

## 3. Ordering and dependencies

```
Experiment 0 (extend eval set to 5 books, baseline re-run)
   │  read-only, no build — must run first, nothing else is measurable without it
   ▼
Experiment 1 (Q1/Q2: outline split vs. size-merge)  ◄── gated: prove outline→block join
   │  on ONE book's front matter first (cheapest negative result in this plan)
   │
   ├──► Experiment 3 (Q3: hierarchy simulation)         [strictly needs Exp 1's output]
   │
   └──► Experiment 5 (agent escalation)                 [should run against the WINNING splitter]

Experiment 2 (contextual retrieval, book-scoped)     [independent of Exp 1 — different table
   │                                                    (`chunks` not `summaries`) — but sequence
   │                                                    it after Exp 1 anyway: it targets the
   │                                                    ALREADY-BETTER metric (passage recall),
   │                                                    Exp 1 targets the WORSE one (chapter
   ▼                                                    routing) — fix the worse number first]

Experiment 4 (Q4: section-aware boost)               [rides along with Exp 0/1's harness sitting —
                                                         no hard dependency, just shares infra]
```

**What's foundation-frozen and therefore expensive/gated, flagged per experiment above:**
Experiment 3 is the only one that, *if it succeeds*, produces a foundation-protected follow-on (H1:
`migrations/`, `contracts/` `ChapterSummary` change, CODEOWNERS sign-off) — but Experiment 3 itself,
as specified, touches neither. No experiment in this plan requires a `contracts/`, `rag/config.py`,
`migrations/`, `fixtures/` (beyond adding new eval fixture files, which is additive, not a change
to an existing frozen fixture), `ci/`, or `.github/` change to **run**. Only a *successful*
Experiment 3 result creates foundation-protected follow-on work, and that work is explicitly out of
this plan's scope.

---

## 4. Cost estimate summary (single RTX 5090, order-of-magnitude)

| Experiment | GPU cost | Wall clock | Needs re-embed? | Needs migration? |
|---|---|---|---|---|
| 0 — extend eval set | ~0 (harness run only) | 1 sitting to author 25 new questions + run | No | No |
| 1 — outline split A/B | Low (~90 chapter summaries + embeds) | Hours, single day incl. join-proof step | Yes — ~90 chapter vectors only | No |
| 2 — contextual retrieval | 2-6 GPU-hours (2 arms × 1,939 chunks) | Single afternoon | Yes — 5 books' ~1,939 chunk vectors | No |
| 3 — hierarchy simulation | ~0 (handful of ad hoc Part-level embeds) | Hours | No (nothing persisted) | No (simulation only) |
| 4 — section-aware boost | ~0 | Rides along with Exp 0/1 | No | No |
| 5 — agent escalation | ~0 (no GPU-heavy step; LLM calls at agent-loop cost, small N) | 1-2 days incl. building the scoring wrapper | No | No |

Every number above is explicitly order-of-magnitude, not a committed estimate — sized to be
"not wrong by 10×," per the brief's own stated bar, not to be precise.

---

## 5. What can be simulated in the harness, read-only, right now — the cheap-negative-results list

Called out explicitly because the brief marks this as the most valuable category:

1. **Outline→block page join plausibility** (prerequisite inside Experiment 1) — fully read-only,
   no GPU, no ingestion. Can fail fast and cheaply if the join is broken.
2. **Hierarchy-vs-flat routing** (Experiment 3) — read-only against Experiment 1's already-embedded
   chapter vectors, no new persistence.
3. **Front-matter handling sanity check** — reading `blocks` for the first N pages of each book and
   checking whether outline level-0 entries (`Cover`, `Copyright`, `Dedication`) produce sane vs.
   garbage boundaries, entirely offline, before Experiment 1's summarization step runs at all.
4. **Question-type coverage audit** — before writing Experiment 0's 25 new questions, a read-only
   pass over each book's existing `ChapterSummary` rows can confirm every book has at least one
   plausible fact-bearing, mid-content-section chapter to draw a question from, catching a "this
   book's chapters are all front-matter-shaped" problem before any question gets written and locked.

Everything else in this plan (Experiments 1's actual re-embed, Experiment 2, Experiment 5's scoring
wrapper) does require either GPU time or new (non-foundation) code — flagged as such, not folded
into this "free" list.
