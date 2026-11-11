# RQ-3 pre-registration: relevance demotion arms (STUB, committed before any code or run)

Status: stub. Arms, fixtures, the adoption rule and the what-if table are completed in the next commit, still before
any arm runs. Governing documents: `2026-11-10-topic-focus-benchmark-protocol.md` (section 5-6 and the 2026-11-11
addendum) and `docs/superpowers/plans/2026-11-10-enhancement-programme-issues/parked/RQ-2-*.md`, `RQ-3-*.md`.

Intended arms: baseline; tail@0.25; tail@0.30; penalty@0.30 with one fixed p. Flags (RQ-2):
`--relevance-demotion {tail,penalty} --relevance-tau T [--relevance-penalty P]` on `app/retrieval_eval.py`.
Rule in one line: ADOPT a mode only if contamination@10 falls AND no guard set loses more than one question
(on-topic paper passages, books, `collision`; `offtopic-legit` recall, off-topic-gold paper passages); else REJECT and
the default stays off. Nothing is switched on by default.
