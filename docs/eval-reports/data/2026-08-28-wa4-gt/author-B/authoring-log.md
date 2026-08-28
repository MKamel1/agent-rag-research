# W-A4 Authoring Log — Author B

## Protocol

### Item Shape
Each item follows this structure:
```json
{
  "id": "Q-WA4-B-###",
  "question": "Multi-part question text...",
  "sub_parts": [
    {
      "text": "Sub-part text",
      "status": "supported|absent",
      "gold_ref": { "paper_id": "...", "block_id": "...", "excerpt": "..." },  // only if supported
      "absence_probe_log": { "probes": [...], "verdict": "..." }  // only if absent
    }
  ],
  "gold_paper_ids": ["..."],
  "gold_block_ids": ["..."],
  "author_id": "GT-B",
  "frozen_after_retrieval": true,
  "duplicate_of": null,
  "_metadata": { "corrections": [] }
}
```

### Mandatory Rules
1. **NEVER hand-type excerpts** — programmatically extract from papers.db
   - Use `sqlite3 'file:waymo/data/papers.db?mode=ro'` to query
   - Machine-check with difflib — if coverage < 85%, substitute exact DB span + log in _metadata.corrections
2. **Every "absent" carries probe denominator** — log queries, hit counts, denominator
   - Absence_probe_log.probes[] array must include query, hits, denominator
   - Run lexical (SQL LIKE over blocks/chunks) AND semantic (retrieval round-trip)
3. **frozen_after_retrieval**: author item → probe → freeze
   - Never edit item after seeing retrieval output for it
   - If probe kills item, kill it and log cause

### Authoring Flow
1. Author multi-part item (all sub-parts initially "supported")
2. Extract excerpts programmatically from papers.db
3. Run probes on each supported sub-part to verify they exist
4. If sub-part has 0 hits across multiple probe queries → mark "absent" with probe_log
5. Freeze item after probing
6. Commit after each batch

## Batch 1 — Authoring

Authored (stub): stub commit before real authoring
