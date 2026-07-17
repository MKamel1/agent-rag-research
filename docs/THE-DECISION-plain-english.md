# The One Decision I Need From You — In Plain English

*Written 2026-07-17. I asked you a question using shorthand and it wasn't clear. Here it is properly.*

---

## The short version

We've finished **designing** the next big feature (the "claim layer"). So the "how do we build it"
question is answered.

The question left is simpler: **should we build that big feature next — or should we do two smaller,
cheaper things first?**

That's it. That's the whole decision. The rest of this file explains the two paths so you can pick.

---

## What are the things we're choosing between?

### Path A — Build the big feature next: the "claim layer"

**What it is, plainly:** right now the system finds *passages* — chunks of text from papers. The
claim layer would go a step further and pull out **individual facts** from each paper, like:

> "Method X reached 94% accuracy on dataset Y, under condition Z."

...and store each fact as its own tidy, structured entry that links back to the exact spot in the
paper it came from.

**Why it sounds appealing:** instead of getting back a paragraph to read, you'd get back specific
facts. And in theory, the system could line up facts from different papers side by side.

**The honest catch (this is important):**
- It's a **big build** — the biggest single thing on the whole roadmap. Weeks of work, and it has to
  run over all 30,000 papers (days of computer-time).
- Its headline selling point is **comparing facts across papers** — e.g. "Paper A and Paper B
  disagree about method X." **But you already told me that's something you "won't use much."**
- And when I actually tested it this week, I found that even when two papers study the *same*
  benchmark, they usually measure *different things* — so there's often nothing to line up. The
  comparison feature has less to work with than the plan assumed.

So: a big, expensive feature whose main payoff is something you've said you don't care much about.
That doesn't mean it's worthless — pulling facts out is still useful — but it's a lot of effort for
uncertain reward.

### Path B — Do two cheaper, high-confidence things first

**Thing 1 — Actually use the system yourself for a bit ("dogfooding").**

The system is already connected to your Claude Code, but you haven't actually used it for real work
yet. Its own definition of success is literally *"an agent answers with a citation **and it gets
used**."* We haven't done the "gets used" part.

If you spent even a little time actually asking it real research questions, we'd learn — from
reality, not guesswork — *what's actually weak*. Maybe search is great and you just want faster
answers. Maybe it's missing whole topics you care about. Maybe the claim layer turns out to be
exactly what you want after all. **We don't know yet, because it hasn't been used.** A few days of
real use would tell us, and would let us re-rank this entire roadmap based on facts instead of a plan
written before anything existed. This costs almost nothing.

**Thing 2 — Prove the search still works at full size ("scale-validation").**

Today the system holds **809 papers** and searches them well (it finds the right passage about 95%
of the time). We're about to grow it to **30,000 papers** — 37 times bigger.

Here's the risk: **we don't actually know the search stays that good at 37× the size.** More papers
means more near-identical passages competing to be "the answer," which can make search worse. And
*everything* else — the claim layer, future features, all of it — sits on top of search. If search
quietly gets worse at full size and we don't check, every feature we build on top inherits a cracked
foundation.

So before building *anything* new on top, we should grow to 30,000 and re-run the quality test. If it
still scores well — great, build with confidence. If it dropped — we fix the foundation first. This
is already partly planned; I'm just saying it should come *before* the claim layer, not after.

---

## The trade-off, in one line each

- **Path A (claim layer now):** commit weeks of work to the biggest feature — betting it's worth it,
  before we've confirmed the foundation holds at scale or seen what you actually need from real use.
- **Path B (use it + prove it first):** spend a little effort making the system *real and trusted*
  first, then decide what to build next with actual evidence — at the cost of delaying the big
  feature.

---

## My recommendation

**Path B, and it's not close.** Here's the plain reasoning:

1. Building a big feature on an unproven foundation is how you end up rebuilding it. Prove search at
   30,000 first — it's cheap insurance.
2. You've never actually used the thing. A few days of real use is the single most valuable
   information we could get, and it might completely change what we build next. It would be a shame
   to spend weeks on the claim layer and *then* discover from real use that you needed something else.
3. The claim layer's big selling point is something you've said you won't use much. That's a reason
   to build a *small* version and see if you like it — not to commit to the full thing up front.

**Concretely, Path B means:** let the paper download finish, run the growth to 30,000, re-check
search quality, and meanwhile you actually use the system a bit. Then we look at what we learned and
pick the next feature with real evidence in hand. The claim layer stays fully designed and ready — we
can build it the moment there's a reason to.

---

## What I need from you

Just tell me: **A or B?** (Or "explain X more" if any part is still fuzzy.)

- **"Go with B"** → I focus on getting to 30,000 + proving quality, and hand you the system to try.
- **"Go with A"** → I start building the claim layer (I'd still suggest the thin version first).
- **"Something else"** → tell me what matters most to you and I'll shape the plan around it.
