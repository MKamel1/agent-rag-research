"""Repair of PDF-ligature-damaged words ("efect" -> "effect") for the keyword arm and regex scans.

STUB (CQ-1). Intended behaviour: pure, deterministic, dependency-free `repair_ligatures(text)` and
`repair_token(word)`; map data loaded once from `ligature_map.json` (built by
`scripts/build_ligature_map.py` from the corpora). Never alters a word not in the map; preserves
lower/Title/UPPER case. Stored chunk/block text is NEVER changed -- only `_sparse_vector` and
`DocumentStore.scan_blocks` use this.

Pre-registered acceptance (CQ-1): (a) on a seeded random sample of 300 mappings read by hand, the
false-repair rate (mapping turns a legitimate token into a different word) must be <= 1%; (b)
applying repair to 2,000 random chunk texts must change no token that /usr/share/dict/words or the
frequent-word list recognises as correctly spelled. If run 1 fails, tighten thresholds and record
both runs.
"""
