# The System, In Plain English — What We're Building, Why, and What I'd Reprioritize

*Written 2026-07-17. For a non-specialist reader: jargon is explained inline the first time it
appears. Three parts: (1) what's being worked on right now, (2) the V1→V3 roadmap and what each
feature could buy us, (3) my honest recommendation on what deserves higher priority than some of
those roadmap features.*

---

## First, what this system actually is (one paragraph)

It's a private search engine over research papers. You (or an AI assistant acting for you) ask a
question, and it hands back the exact passage from a real paper that answers it, plus a checkable
citation (which paper, which page, which section). "At ~0 cost" means it runs entirely on your own
machine — no per-question API fees. The current version is called **V0**. It holds **809 papers**
today and is being scaled toward **30,000**. A few terms used throughout:

- **Ingest** — the pipeline that takes a paper from "a PDF on arXiv" to "searchable in the system":
  download → parse (read the PDF into structured text, keeping equations/tables) → chunk (cut into
  passage-sized pieces) → embed (turn each piece into a list of numbers that captures its meaning,
  so similar meanings are findable) → store.
- **Retrieval** — the search step: given a question, find the passages most likely to answer it.
- **MCP** — the doorway an AI assistant (like Claude) uses to call this system's search tools.
- **Claim** — (a V1 idea) a single factual assertion pulled out of a paper, e.g. "Method X reached
  accuracy Y on dataset Z," stored as structured data so assertions can be compared across papers.

---

## Part 1 — What's being worked on right now, and why it matters

| Task | In plain English | Why it helps the system |
|---|---|---|
| **Building the paper cache toward 30k** (running in the background) | Politely downloading paper PDFs from arXiv, a few seconds apart, over the coming days. arXiv limits how fast you can pull, so this is a multi-day drip, not an overnight job. | The big scale-up can't happen until the papers are downloaded. This is the slow part; starting it early means we're not waiting on it later. |
| **The 30k "seed run"** (queued, needs your go) | Running the full ingest pipeline over all 30,000 papers. Takes days of computer-time. | Turns the system from a 809-paper demo into the real thing. This is the headline step to make V0 "done." |
| **Re-measuring search quality at 30k** (queued, after the seed run) | Re-running the quality test once the corpus is large. Today's score (0.952 — meaning the right passage is in the top 10 results ~95% of the time) was measured at 809 papers. | We honestly don't know yet if search stays that good at 37× the size. This is the real proof V0 works, not the small-scale number. |
| **Designing the "claim layer"** (in progress right now) | Working out how to reliably pull structured claims out of papers *and* tie each claim back to the exact source passage so it's verifiable. Two approaches are being tested head-to-head against real data. | If we build the claim layer on a shaky foundation, every claim could cite the wrong passage — worse than having no claims. This design work prevents that. |
| **Spike 5** (deferred) | An experiment on whether giving the AI assistant a richer "here's what I can do and when to use me" description makes it use the system better. | Could make the system easier for an assistant to drive well — but it's hard to measure and low-stakes, so it's parked. |
| **vLLM migration** (deferred) | Swapping the local text-generation engine for a faster one, needed before running claim-extraction over 30k papers. | Purely a speed/cost enabler for the claim layer at scale. No user-visible benefit on its own. |

**The through-line:** almost everything "in hand" is about **getting V0 to real scale and proving it
holds** — plus the *first* design step of the biggest V1 feature (claims).

---

## Part 2 — The V1 → V3 roadmap, and what each feature could buy us

The roadmap adds three layers on top of V0's plain search. Each is gated — it only gets built once
the thing below it works.

### V1 — "Claim enrichment" (the knowledge layer)
Turns the pile of passages into a set of structured, comparable facts.
- **Claim extraction** — pull atomic claims (method + dataset + metric + value + conditions) from
  each paper. *Potential:* lets the system answer "what does my library say about X" with specific
  findings, not just raw passages; and it's the foundation for comparing papers.
- **Obsidian notes** *(already built)* — a browsable note per paper in a personal-wiki app.
  *Potential:* hand-browsing and serendipity, separate from search.
- **Evidence tiers** — labelling how strong/direct each piece of evidence is (A/B/C/D). *Potential:*
  the assistant can weight a strong result over a passing mention.
- **Self-describing search doorway** (the "MCP" gets richer) — the system tells the assistant what
  it holds and how to use it. *Potential:* the assistant composes the tools more intelligently.
- **Contextual headers** *(tested, on hold)* — prepend a one-sentence "what this passage is about"
  to each piece before embedding. *Potential:* better retrieval of context-poor pieces (bare
  equations) — but our test found the benefit unproven at current scale and it costs ~2.5 weeks of
  computer-time, so it's parked until we can measure it at 30k.

### V2 — "Cited-answer engine"
Moves from "here are passages" to "here's a written, cited answer."
- **Citation graph** — pull in who-cites-whom from external databases. *Potential:* "show me the
  papers around this one," influence tracing.
- **Synthesis** — the system composes a direct answer with inline citations. *Potential:* this is
  arguably the *actual product* most people want — ask a question, get a sourced answer.
- **Contradiction / benchmark surfacing** — flag when two papers disagree on the same benchmark.
  *Potential:* spot open debates. **Note: you previously marked this "won't use much."**

### V3 — "Proactive radar"
The system comes to you instead of waiting to be asked.
- **Scheduled ingestion + weekly digest** — "here's what's genuinely new and notable this week."
- **"What changed vs. what I knew"** — flags new work that challenges prior findings.
  *Potential:* keeps you current without manual searching — the long-term "research brain" dream.

---

## Part 3 — My honest recommendation: what deserves higher priority than several V1–V3 features

This session surfaced a few things that make me think **parts of the roadmap are lower-value than
they look, and a few unlisted enhancements would pay off faster.** In rough priority order:

### 1. Actually *use it* and capture what fails — before building more on top (highest ROI)
V0's own definition of success is "an agent answers with a citation **and it gets used**." Right now
it's connected to your Claude Code but **not yet used in anger.** Nothing on the roadmap is worth as
much as a week of real use with a lightweight log of *which questions it answered badly*. That log
would re-rank this entire roadmap with evidence instead of guesswork — you'd learn whether your real
bottleneck is retrieval, coverage, breadth, or answer-shape, before spending weeks building the
wrong layer. **Cost: near-zero. Payoff: redirects everything else.**

### 2. Prove and harden search at 30k before layering anything on it
Claims, synthesis, and the radar all sit on top of retrieval. If retrieval quietly degrades at 30k
(very possible — more papers means more near-duplicates competing), **every layer above inherits the
weakness.** Validating (and fixing if needed) search at full scale should outrank every new feature.
This is partly already queued (task #43) — I'm flagging that it's a *gate*, not a checkbox: don't
start V1 building until it passes. **Cost: the seed run + a re-measure. Payoff: protects everything.**

### 3. A standing "quality alarm" (automated regression + honesty checks)
The single loudest lesson of this session: **quality bugs hide behind numbers that look fine.** We
hit a search score that was secretly measuring an empty database (a fake `0.000`), an eval that
couldn't detect improvement because it was already maxed out, and — historically — a change that
silently dropped search quality from 0.96 to 0.30, and once to 0.0 in production. A system built
largely by AI agents with no memory *especially* needs an automated guard that re-runs the quality
test and **fails loudly** on any regression, plus sanity checks ("is the database non-empty?",
"do the counts add up?"). **This protects every current and future feature** and is cheap relative
to what one undetected regression costs. I'd rank this above most of V1.

### 4. A thin "cited answer" now, before the full claim graph
Your real use case is "ask a question, get a sourced answer." V0 returns passages and lets the
assistant write the answer. A **small** step — a single tool that returns a tightly-grounded answer
with its citations attached — would deliver most of what V2's "synthesis" promises, at a fraction of
the cost, and **without** first building the entire claim graph. It's a V1.5 that front-loads user
value. **Cost: modest. Payoff: the core experience, sooner.**

### 5. Re-examine whether the claim layer earns its place as V1's centerpiece
This is the uncomfortable one. The claim layer is a **big** build (new data model, extraction over
30k papers, ~weeks of work), and its headline payoff is *reconciliation* — comparing and
contradicting claims across papers. But: **you flagged the contradiction/comparison use case as
"won't use much,"** and our Spike 3 experiment found that even where papers share a benchmark they
usually measure *different things*, so automatic cross-paper comparison is genuinely sparse in this
corpus. Extraction itself works well — but the expensive part (reconciliation) may serve a use you
don't value much. **My suggestion:** build only a *thin* claim slice (extract + show claims per
paper, which enriches the Obsidian notes and per-paper Q&A), measure whether you actually reach for
claims in real use (see #1), and **defer the reconciliation machinery** until there's evidence you'd
use it. Don't pay for the whole claim graph on spec.

### 6. Keep the corpus *fresh*, cheaply (a small slice of V3, pulled early)
A "research brain" that's a frozen snapshot decays. The roadmap defers all update-handling to "after
V3." But a **cheap** version — periodically ingest just the newest papers and de-duplicate revised
ones — keeps the library current for far less than the full radar, and matches how you'd actually
use it day to day. Worth pulling a thin version of this forward.

---

### The one-line summary
**Use it, prove it at scale, and guard its quality automatically — before building the big knowledge
layers. And treat the claim layer's expensive half (reconciliation) as unproven-value until real use
says otherwise.** The roadmap's *sequence* is sound; my push is to insert "make it real and measured"
ahead of "make it fancier," and to right-size the claim layer to what you'll actually use.
