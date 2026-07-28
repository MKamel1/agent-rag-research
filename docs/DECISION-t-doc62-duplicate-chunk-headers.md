# Decision needed — T-DOC62: duplicated section headers in stored chunks

*Prepared 2026-07-28. All figures measured against the live corpus, read-only. Nothing has been
changed.*

## TL;DR

**The ticket is out of date and overstates the problem.** T-DOC62's code fix landed on 2026-07-17
and works. What remains is stale *data* from before that date: **809 papers (7.3% of the corpus)**,
of which roughly **14,850 chunks (4.1% of all chunks)** carry a duplicated header.

It does **not** need a full 11k re-embed, and it does **not** need re-parsing. The blocks for all
809 papers still exist, so they can be re-chunked and re-embedded directly, skipping the expensive
stage.

The decision is whether that 4.1% is worth fixing now, later, or at all.

---

## What the problem actually is

A stored chunk's text is `title\nsection_path\n\n<body>`. The body's first block is usually that
same heading, so the heading appeared twice:

```
Inside the Unfair Judge: A Mechanistic Interpretability Account of LLM-as-Judge Bias
1. Introduction

1. Introduction

Large language models are now r...
```

This costs twice: the duplicate is embedded (wasting tokens in the vector that decides retrieval)
and it is displayed verbatim in every retrieved passage.

## What the ticket says, and why it's wrong now

> **T-DOC62 (not started) — 🟡** ... **This is a chunker change = a re-embed trigger**, so it must
> land BEFORE the seed builds the corpus, or we pay a full re-embed to fix it.

Two claims no longer hold:

**1. It is not "not started".** `rag/chunker.py:58` defines `_strip_duplicate_heading` and line 178
applies it. Commit `157af4d`, *"fix(chunker): de-dupe leading section heading in chunk text
(T-DOC62)"*, landed **2026-07-17 17:23**. Same stale-status problem as T-DOC63, which had also
already been implemented.

**2. It is not a full re-embed.** The corpus build began 2026-07-14, *before* the fix. Only chunks
written before the cutoff are affected. Measured:

| ingested | chunks | duplicated | rate |
|---|---|---|---|
| **before** 2026-07-17 | 25,387 | 14,850 | **58.49%** |
| **on/after** 2026-07-17 | 94,613 | 7 | **0.01%** |

The fix demonstrably works. Everything ingested since is clean.

## Scope

| | count | share |
|---|---|---|
| papers in corpus | 11,026 | |
| papers affected (pre-fix) | **809** | 7.3% |
| chunks in corpus | 361,614 | |
| chunks affected (pre-fix) | 25,387 | 7.0% |
| chunks actually carrying a duplicate | **~14,850** | **4.1%** |
| blocks still available for those papers | 166,561 | **100% of the 809** |

That last row is the important one: **no re-parsing is required.** MinerU parsing is the expensive
stage, and we can skip it entirely.

---

## Options

### A. Do nothing

Leave 4.1% of chunks with a duplicated header. They remain retrievable and correct — the duplication
wastes embedding tokens and looks untidy in a displayed passage, but nothing is *wrong*.

- **Cost:** zero.
- **Risk:** the affected 809 papers have slightly degraded embeddings relative to the other 92.7%,
  so the corpus is not uniform. Any future retrieval measurement is measuring a mixture.
- **Reversible:** yes, trivially — options B/C stay available indefinitely, since the blocks persist.

### B. Re-chunk + re-embed the 809 affected papers *(recommended)*

Read the existing `blocks`, re-run the Chunker (which now strips the duplicate), write new chunk
text, re-embed those chunks. Skips harvest, parse, and summarize.

- **Cost:** 25,387 chunks re-chunked and re-embedded. No MinerU, no LLM summarization. Precedent
  exists — `app/reembed_experiment.py` already re-embeds a chosen `paper_ids` set, and
  `app/reindex_idf.py` is a retrofit migration of the same shape.
- **Gets you:** a uniform corpus, and the 4.1% cleaned before any retrieval measurement is taken.
- **Risk:** needs a small tool that doesn't exist yet (re-chunk-from-blocks). Chunk ids change if
  chunking boundaries shift, so stale vectors must be deleted rather than only upserted — that is
  exactly the orphaned-points failure mode T-DOC23/T-DOC40 dealt with, so it needs the cross-store
  delete path (which now works, per T-DOC84).
- **Reversible:** the blocks are the source, so it can be re-run.

### C. Full-corpus re-embed

Re-embed all 361,614 chunks.

- **Cost:** ~14× option B for the same benefit.
- **Only justified if** something else also requires a full re-embed — e.g. changing the embedding
  model, or adopting the contextual-header approach that `app/reembed_experiment.py` was built to
  A/B test. **If that A/B is going to happen anyway, do this once, together, and skip B.**
- **Reversible:** yes, but expensive to repeat.

### D. Strip at read time

Leave stored data alone; remove the duplicate line when displaying a passage.

- **Cost:** very small code change.
- **Does not fix the embedding** — the wasted tokens are already baked into the vectors, which is
  the half that affects *retrieval quality*. Cosmetic only.
- Worth doing **in addition to** A if you choose A, since it removes the visible symptom for free.

---

## Trade-off summary

| | effort | fixes embeddings | fixes display | corpus uniform |
|---|---|---|---|---|
| **A** do nothing | none | no | no | no |
| **B** re-chunk 809 | small tool + ~25k chunks | **yes** | **yes** | **yes** |
| **C** full re-embed | ~14× B | yes | yes | yes |
| **D** strip on read | tiny | no | yes | no |

## The question for you

**Is 4.1% of chunks carrying a duplicated header worth building a re-chunk-from-blocks tool now?**

Three reasonable answers:

1. **Yes, do B** — cleans it before any retrieval measurement, and the tool is reusable for the next
   time a chunker change needs retrofitting to existing data. My recommendation, mainly because the
   book work will need retrieval measurement and measuring a mixed corpus is a false start.
2. **Not yet — do D, defer B** — remove the visible symptom cheaply, revisit if a full re-embed
   becomes necessary for another reason. Rational if the contextual-header A/B is likely, since that
   would subsume it.
3. **No — do A** — 4.1% with a cosmetic-plus-minor-quality issue isn't worth the work.

**What I need from you:** which of the three, and if (1), whether the re-chunk tool should be
general (`--paper-ids`, reusable for future chunker changes) or a one-off script.

## Not in scope of this decision

- The ⚠️ *"fix before the 30k seed"* warning on the ticket is now moot for the code — the fix is in,
  so the seed will produce clean chunks regardless.
- Whether to run the contextual-header A/B at all (T-DOC41). It is mentioned only because it would
  change the economics of option C.
- Updating T-DOC62's stale `(not started)` status — that will be corrected regardless of the
  decision here.
