# W-A4 authoring log -- Author A (GT-A)

Ticket SB-2, set W-A4 (partial-absent ground truth). Blind pairing with Author B in a
separate worktree; this author never inspected the B lane (see "Blindness" at the bottom).

## Protocol (committed before any item is authored)

1. Harvest candidate "supported" facts by reading real block text straight out of
   `waymo/data/papers.db` (`blocks.text`, keyed by `block_id`) -- never invented, never
   hand-typed into the fixture. The excerpt placed in `gold_ref.excerpt` is a substring of
   that same DB read, copy-pasted programmatically (`scripts/wa4_author_a_probe.py`, `fidelity`
   command / `build_items.py`'s verbatim-substring assertion).
2. Pick each item's "absent" sub-part as a *sibling* of the supported fact: something the
   same block/paper visibly does **not** report (a finer breakdown, a different stratum, a
   numeric threshold the text never states), so the absence claim can be eyeballed against
   the source paper before it is ever run against retrieval.
3. Confirm the absence is corpus-wide, not just paper-local, with probes:
   - **Lexical**: `SELECT COUNT(*) FROM chunks WHERE text LIKE '%...%'`, run once corpus-wide
     (denominator 46155) and once scoped to the specific paper (denominator = that paper's own
     chunk count) for the fact's most distinguishing phrase.
   - **Semantic**: a real round trip through
     `python -m app.mcp_verify_client "<query>" --k 5 --data-dir /home/omar/ai-projects/research-system-rag/waymo/data`
     (denominator 47893, the live Qdrant `waymo_av_safety` point count -- `waymo/data/config.yaml`
     pins `collection: waymo_av_safety`, so every round trip in this log resolves against that
     collection even though `mcp_verify_client` itself takes no `--collection` flag). The top hit
     was read by hand every time -- a returned result that merely shares vocabulary but does not
     state the queried fact is logged as `hits: 0` with a `relevance_note` explaining why.
4. Verify excerpt fidelity: every `gold_ref.excerpt` is checked against every chunk in the
   same paper (`scripts/wa4_author_a_probe.py fidelity`) -- a chunk's `anchor_json.block_id`
   only marks where the chunk *starts*, so fidelity is checked against the paper's full chunk
   set, not just the chunk anchored at the exact block_id (this was a real bug caught mid-run,
   see Lessons below). All 21 surviving items scored **1.0 coverage** (exact substring match) --
   zero corrections needed to any excerpt.
5. **Freeze rule**: an item is only looked at through retrieval *after* its supported and
   absent sub-parts are fixed. Once probed, `frozen_after_retrieval: true` is set. A probe that
   surfaces a real hit for a claimed-absent sub-part kills the item -- removed from `items`,
   logged below with cause, not silently reshaped into a safer claim.
6. `--collection waymo_av_safety` is used per the ticket's per-command rule; `app.mcp_verify_client`
   has no such flag, so the corpus's own `config.yaml` (pinned to that collection) is relied on
   instead and verified once (`db_path`/`collection` line in the tool's own log output).

## Final counts

- **Items authored and probed: 22** (20 primary + 2 spares, per target).
- **Items killed after retrieval: 1** (`Q-WA4-A-013`, see below).
- **Items surviving: 21**, `frozen_after_retrieval: true` on all.
- **Sub-parts total: 42** (2 per item) -- **21 supported**, **21 absent**.
- **Absence probes logged: 83** (lexical corpus-wide + lexical paper-scoped + one semantic
  round trip per absent sub-part; several items carry a 4th probe where the first two lexical
  terms were both worth logging). Every `"status": "absent"` sub-part carries at least 3 probes
  and a verdict; none is a bare "I could not find it."
- Gold papers span **20 distinct papers** (one per surviving item) plus the killed item's
  paper (2503.00077), giving real topical spread rather than repeated sampling of 2-3 papers.

## Killed items

- **`Q-WA4-A-013`** -- "What maximum operating speed ... does this survey attribute to
  Waymo's AV service, and what is that maximum speed limit specifically for Waymo's Phoenix
  operations?" The supported sub-part (2503.00077:b7, "speeds up to 65 mph") was solid; the
  absent sub-part claimed no Phoenix-specific Waymo speed limit exists anywhere in the corpus.
  Lexical probes (corpus-wide "65 mph": 4 hits, all generic; paper-scoped: 1 hit, the same
  blanket figure) supported that. The **semantic round trip surfaced a genuine hit**: paper
  `2212.08148` ("Collision Avoidance Testing of the Waymo Automated Driving System") states the
  East Valley Phoenix ODD "includes 24 hours per day, 7 days a week driving on roads up to a
  speed limit of 45 mph" -- a real, Phoenix-specific Waymo speed figure the lexical probes
  missed because they searched for "65 mph" / "Phoenix mph", not "45 mph". This is exactly the
  freeze rule's purpose: once seen, the item cannot be quietly rewritten to ask about some other
  city instead -- it is killed and the id gap (013 missing from the final 21) is left as the
  record. Full item + probe log preserved at `killed_Q-WA4-A-013.json` in this directory.

## Flagged doubt (not killed, but worth a second look)

- **`Q-WA4-A-004`** (VRU pedestrian/bicyclist/scooter split): the semantic probe's top hit was
  not the source paper (2403.14648) but a *different* paper in the corpus
  (`local:6b9ccd0431f6`, the 56.7M-mile crash-type study), which **does** report separate
  Cyclist/Motorcyclist/Pedestrian crash rates -- by location, for its own, much larger dataset.
  The question text is scoped tightly to "those 145 SF crashes" from the specific DMV study, so
  the other paper's breakdown is not actually an answer to this sub-part -- it's a different
  study with different crash counts. I judge the item correct as scoped, but flag it because a
  retrieval system (or a grader skimming only paper titles) could easily conflate the two
  Waymo studies and credit a wrong-paper "hit" as answering this sub-part. This is precisely the
  kind of near-miss the cross-verification pass should target.

## Lessons hit mid-run (logged, not hidden)

1. **A chunk's `anchor_json.block_id` is only its first block, not every block it covers.**
   The initial fidelity-check implementation matched chunks by exact `anchor_json.block_id ==
   gold_block_id` and found 0 matching chunks for every single item, because chunks in this
   corpus span a run of several blocks and are anchored at the first one. Fixed by checking
   fidelity against every chunk in the same paper instead (`chunk_texts_for_block` in
   `scripts/wa4_author_a_probe.py`). All 21 surviving excerpts then scored coverage 1.0.
2. **A block-level excerpt can look absent while the fuller chunk it lives inside is not.**
   The first draft of `Q-WA4-A-003` paired a supported "AV collision-type" prose sentence
   (rear-end 29%, sideswipe 11%) with a claimed-absent "head-on % for the AV itself" --
   plausible from the prose alone, but the full chunk (which includes the underlying table)
   actually lists Head-On: 9 (6.2%) for the AV. Caught by reading the full served chunk, not
   just the narrower block, before finalizing; the item was redesigned around the injury-
   severity split instead (which the fuller chunk also confirms is genuinely absent -- only a
   binary No-Injuries/Injuries-Reported split is given).
3. Two more planned absent claims were caught the same way before probing and swapped:
   `Q-WA4-A-019` (TerraZero) originally planned to use "TerraZero vs Gigaflow benchmark score"
   as absent -- the full paper actually reports this comparison (94.19 vs 93.8 on nuPlan val14).
   Swapped: that comparison became the *supported* fact, and "TerraZero's CARLA leaderboard
   score" (never evaluated) became the absent claim. `Q-WA4-A-020` (Fractional Collisions)
   similarly had "aggregate stats across the dataset" planned as absent when the paper actually
   reports them (17.15 vs 17 GT); swapped to use the aggregate stats as supported and a
   weather-condition breakdown (a variable this paper never uses at all) as absent.

## Blindness

Never read, listed, grepped, or ran `git show` against
`.claude/worktrees/P95-SB2-WA4-authorB` or the `P95-SB2-WA4-authorB` branch, or anything
under either. No accidental exposure to Author B's lane occurred during this session.
