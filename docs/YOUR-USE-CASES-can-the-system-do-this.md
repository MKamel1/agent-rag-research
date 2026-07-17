# Can the System Do What You Actually Want? — Method Research, "Why This Method," and Gaps

*Written 2026-07-17, in plain English. You described three real uses. Here's an honest answer for
each: can it do this now, why/why not, and how we make it work. Grounded in what's actually in the
corpus today.*

**First, the housekeeping:** yes, paper-fetching is running and healthy — it's grown the download
cache from 2,542 to 3,260 papers this session and is still going, heading toward 30,000 over the
coming days.

---

## The key thing to understand up front

Your three uses are all really **"find the right passages, then reason about them."** The system's
job is the *first* half — surface the relevant bits of the right papers, with citations. The AI
(Claude, through the doorway we call the MCP) does the *second* half — the actual reasoning,
comparing, spotting gaps.

So the real question for each use case is: **does the system reliably hand the AI the right raw
material to reason over?** If yes, the AI can do the thinking. If the material never surfaces, no
amount of AI cleverness helps.

I checked what's actually in the corpus. The good news: the "reasoning" parts of papers *are*
captured and searchable —

| Part of a paper | How much of the library it is |
|---|---|
| Method / Approach sections | 14% |
| Results / Experiments | 16% |
| Discussion / Conclusion | 5% |
| Related Work (comparisons to other methods) | 4% |
| **Limitations** | **1%** ← note this |

Keep that last row in mind — it matters for gaps.

---

## Use case 1 — "I have a problem, find me a suitable method"

**Can it do this now? Yes — this is its strongest use today.** This is exactly what the system is
built for: you describe a problem, search finds passages describing relevant methods, the AI reads
them and recommends. Method sections are 14% of the corpus and searchable. **This one you should just
try — it should work well right now.**

**Where it can fall short:** search matches on *meaning similarity* to how you phrased the problem.
If a great method is described in words that don't resemble your problem statement, it might not
surface. The fix is mostly in *how the AI searches* — trying a few different phrasings, searching for
the method type as well as the problem — which the AI can do if it's guided to (more on that below).

## Use case 2 — "Why did this paper use method A and not B?" (understanding when a method works)

**Can it do this now? Partly — the material exists, but it takes more than one search.** Papers
genuinely contain this reasoning: it lives in the *motivation* ("we use X because prior methods
can't handle Z"), *Related Work* (4%), and *Discussion* (5%) sections — all captured and searchable.
So the raw material is there.

**Why it's only "partly":** the *why* is usually scattered — the method is described in one place,
its assumptions in another, the comparison to alternatives in a third, sometimes across different
papers. A single search grabs one piece. To answer "why A over B" well, the AI needs to do **several
targeted searches** (the method's motivation, its limitations, the rival method, the head-to-head)
and then stitch them together. Claude *can* do this — it's exactly the kind of multi-step reasoning
it's good at — but it does it far better when it's *told* to work that way rather than firing one
search and stopping.

**So the bottleneck isn't the AI's reasoning — it's (a) making sure the comparison/motivation
passages surface, and (b) getting the AI to search in that multi-step way.** Both are cheap to
improve (below), and neither needs the big claim-layer build.

## Use case 3 — "Where are the gaps / opportunities in the literature?"

**Can it do this now? This is the weakest of the three, for two concrete reasons.**

1. **The raw material is thin.** Gap-hunting leans on *Limitations* and *future work* sections — and
   those are only **1%** of the corpus. They exist and are searchable, but there's much less to grab
   than for methods or results. (Some of this is just how papers are written — limitations are often
   a short paragraph.)
2. **Gaps are about *absence*, which search can't see.** Finding "what nobody has done yet" means
   reasoning over *everything that has* been done and noticing what's missing. Search finds what
   *is* there; it can't retrieve a passage that doesn't exist. So true gap-mapping needs the AI to
   survey a lot and infer the holes — which works for a narrow topic (the AI can read the limitations
   + future-work of the top papers and synthesize) but not for a sweeping "all the gaps in field X."

**What works today:** "What do papers on <narrow topic> say are the open problems / limitations?" —
the AI can gather the limitations/future-work passages and summarize them. That's genuinely useful
and available now. **What doesn't yet:** comprehensive, corpus-wide gap maps — that would need an
aggregation/knowledge layer we haven't built (and even then, it's hard).

---

## How we make these work — cheap, and aligned with "try it first"

None of this requires the big claim layer. In rough order of value-for-effort:

1. **Test with these exact tasks — this IS the useful experiment.** The single best thing right now
   is you actually asking the system these questions and seeing where it's strong vs. weak. Your
   three use cases *are* the dogfooding test. Concretely, try prompts like:
   - *"Search my papers for methods that handle <your problem>, and summarize the options with
     citations."* (use case 1)
   - *"Find where <paper/method> explains why it was chosen over alternatives, and what its
     limitations are."* (use case 2)
   - *"What do my papers on <narrow topic> list as open problems or future work?"* (use case 3)
   Where it disappoints, that tells us exactly what to fix — with evidence, not guesswork.

2. **Teach the AI to drive the system well for these patterns (cheapest real improvement).** I've
   already written a guide (a "skill") that tells Claude what the system holds and when to use it. I
   can extend it with your specific patterns — e.g. *"for 'why method A over B', don't stop at one
   search: separately find the method's motivation, its limitations, and its comparison to
   alternatives, then synthesize."* This makes the AI use the *existing* system much better, changes
   no infrastructure, and directly serves uses 1 and 2. **I recommend doing this now.**

3. **Section-aware search (a modest, high-value upgrade later).** Give search the ability to *favor*
   the reasoning sections — motivation, related-work, limitations — when the question is a "why" or a
   "gap" question. This directly boosts uses 2 and 3, and is far cheaper than the claim layer. A good
   candidate for the *first* real enhancement after you've tried the system.

4. **A "limitations & open problems" mode for gap-hunting.** A focused way to pull the
   limitations/future-work passages for a topic and summarize them. This gives the cheap 80% of
   gap-identification without the huge knowledge-graph build.

---

## What this tells us about priorities (important)

Your real uses point somewhere specific: they're about **retrieval quality + surfacing reasoning
passages + the AI driving the system in multiple steps** — *not* about the claim layer's headline
feature (lining up numeric results across papers). In fact, the "why did they choose this method"
reasoning lives in *prose* (motivation, limitations), which the structured claim layer captures
*poorly* — it's built for numbers like "94% accuracy," not "we chose X because Y can't handle Z."

**So your own use cases are further evidence for the decision you just made:** try the system, and
let its performance on these exact tasks tell us what to build — which is far more likely to be
"better retrieval + a smarter search guide + section-aware search" than "the big claim/reconciliation
system."

---

## Bottom line

- **Method-finding:** works now — try it first.
- **Why-this-method:** the material's there; needs the AI to search in several steps — cheap to
  improve via the search guide.
- **Gap-finding:** works for narrow topics now; corpus-wide gap maps are genuinely hard and not built.
- **Best next move:** use it on these tasks, and let me improve the AI's search-guide so it handles
  your "why" and "gap" questions in the multi-step way they need. No big build required to start
  getting value.
