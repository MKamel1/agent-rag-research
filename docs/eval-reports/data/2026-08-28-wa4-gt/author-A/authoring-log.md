# W-A4 authoring log -- Author A (GT-A)

Ticket SB-2, set W-A4 (partial-absent ground truth). Blind pairing with Author B in a
separate worktree; this author never inspected the B lane.

## Protocol (committed before any item is authored)

1. Harvest candidate "supported" facts by reading real block text straight out of
   `waymo/data/papers.db` (`blocks.text`, keyed by `block_id`) -- never invented, never
   hand-typed into the fixture. The excerpt placed in `gold_ref.excerpt` is a substring of
   that same DB read, copy-pasted programmatically.
2. Pick each item's "absent" sub-part as a *sibling* of the supported fact: something the
   same block/paper visibly does **not** report (a finer breakdown, a different stratum, a
   numeric threshold the text never states), so the absence claim can be eyeballed against
   the source paper before it is ever run against retrieval.
3. Confirm the absence is corpus-wide, not just paper-local, with two independent probes
   per absent sub-part:
   - **Lexical**: `SELECT COUNT(*) FROM chunks WHERE text LIKE '%...%'` over the full
     46,155-row `chunks` table (denominator = 46155), run for the specific numeric/phrase
     combination the sub-part would need to be answerable.
   - **Semantic**: a real round trip through
     `python -m app.mcp_verify_client "<query>" --k 10 --data-dir <abs waymo/data> --collection waymo_av_safety`
     (denominator = 47893, the live Qdrant `waymo_av_safety` point count), with the top
     hits inspected by hand for topical relevance -- a returned result that merely shares
     vocabulary but does not state the queried fact still counts as `hits: 0`.
4. Verify excerpt fidelity: every `gold_ref.excerpt` is checked with `difflib` against the
   `chunks.text` for the chunk(s) whose `anchor_json.block_id` matches the item's
   `block_id`. Required: >=85% coverage (in practice, exact substring containment, since
   the excerpt is copied verbatim from the same underlying block that chunks are built
   from). Any substitution needed is logged in `_metadata.corrections`.
5. **Freeze rule**: an item is only looked at through retrieval *after* its supported and
   absent sub-parts are fixed. Once probed, `frozen_after_retrieval: true` is set and the
   item's text/gold_ref is not edited again. A probe that surfaces a real hit for a
   claimed-absent sub-part kills the item -- it is removed from `items` and logged below
   under "Killed items", not silently reshaped.
6. `--collection waymo_av_safety` is passed on every retrieval/Qdrant command.

## Counts (filled in as batches land)

- Items authored: TBD
- Sub-parts total / absent: TBD
- Probes run (lexical + semantic): TBD
- Items killed: TBD

## Killed items

(none yet)
