# RESUME (EV-4 focus-gt, paused)
Branch EP-EV4-focus-gt. Dir: docs/eval-reports/data/2026-11-10-focus-gt/

Done:
- gt_tools.py extended (STRATA + `label` subcommand + labels()); merge_gt.py adapted (globs author/items.json, writes focus_gt.json) -- NOT yet run.
- author/items.json: 40 items. collision 26 (verify 0 failures), offtopic-legit 14 (verify 0 failures). Difficulty 12 easy/21 medium/7 hard (add absent for mix).
- Built from tools/data_ab.py by tools/build.py (build.py needs paths adjusted: it reads data from scratchpad .../b/ and writes author/items.json; run from this dir; ABSENT list comes from optional data_c.py).
Remaining:
1. focus-absent: 10 items (tests "absent", dimension "focus-absent", answer_text "Not in the corpus: ...", >=2 absence_evidence, one broad, nearest_distractor_paper_id = off paper). Candidates in authoring-log.md. Specific regexes must be re-checked by verify (hits must reproduce exactly); use fuzzy forms like `Hausman.{1,8}Taylor`. Broad counts from scans/abs1.tsv, abs2.tsv (e.g. Hausman 250, dynamic panel 215, postulates? 964, local linear|kernel matching 77, long.run restriction 2, externalit ~190). Needs a few more candidates to reach 10 (and pick an off paper per item).
2. verify --write to 0 failures; run merge_gt.py; load_questions check (conda run -n agent-rag-research ...); update authoring-log with killed count (currently 0 killed items; candidates abandoned listed).
3. Common-brief runs (pytest, ruff, enforcement), final report.
Background scan: tools/abs3.py may still be running; output at /tmp/claude-1000/-home-omar-ai-projects/3426f8b7-1c1a-4487-ad8c-3b6a5cbe5792/scratchpad/abs3.out (last lines are tuples `(pattern, broad) [spec_hits, broad_hits, first_off_chunk_with_broad]`). Do not re-run.
Scratch helpers (f.py find chunks by label+regex, c.py print chunk) are in tools/.
