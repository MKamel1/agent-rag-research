# Author B authoring log (2026-11-10)

Verify: `24 items, 0 failures -- ids written`. Counts: clause-lookup 5, definition-lookup 4, table-requirement 7,
guidance-factual 4, edition 2, partial-absent 2. Max 3 per document (MIL-STD-882E 3: Task 202, severity, matrix cell; UL 4600 2: 5.5.2.2, proof test; Def Stan 2; FAA AC 2; HSE 1+1; others 1).
Killed: 0 final items; 4 drafts were reworded after the verifier flagged: two table-row excerpts under 8 words, one question with a 6-word copied run, absence scans needing `paper_id` key).

## Coverage
MIL-STD-882E, UL 4600 voting, IEC 31010, Def Stan 00-56, AMLAS, BS 31100, ISO/IEC 15026-3, FAA AC 25.1309-1B (x2),
HSE R2P2, HSE ToR 1992, AIAG-VDA, NUREG-0492, FAA SSH 2000, Kelly, Holloway-Wasson, ISO 31000 2009/2018, ISO/IEC 15026-2 2011/2022.
Not used (cap/time): NASA SP-2010-576/580, SP-2011-3421/3422, STPA Handbook, AdvoCATE, Argevide, Bloomfield-Rushby, 15026-1/-4, DoD/CAIB-like others.

## Corpus quirks observed
- Section paths are unreliable. UL 4600 body sections are nested under the page watermark "FOR UL INTERNAL REFERENCE OR CSDS USE ONLY"
  (about 196 chunks have it as their section) and every chunk carries a stale running header ("16 Metrics and Safety Performance
  Indicators"). Chunk text in the Table of Clauses duplicates clause titles, so title-matching queries can hit the contents list.
- BS 31100: the whole glossary (2.21-2.4x) sits in one chunk labelled "2.20 risk"; Def Stan 00-56 uses "Notes:" as a section label for most clauses.
- MIL-STD-882E: section labels are wrong/missing in places (Section 4 tables are under "4. GENERAL REQUIREMENTS", Table IV label spans 11 chunks).
- Tables: MIL-STD-882E and FAA AC 25.1309 tables are HTML-ish pipe tables with words fused by cell joins ("oroccupational", "reversiblesignificant",
  "Extremelyremote"); AIAG-VDA DFMEA severity table lost the effect label for S=9 (row reads "| 9 | Noncompliance ..."); the AIAG Action Priority
  table is split over chunks with rows missing their S/O/D parents. FAA AC numeric probabilities are LaTeX-fragments
  ("$1 \mathrm { ~ x ~ } 1 0 ^ { - 7 }$"), unfriendly to lexical and embedding search. FAA SSH figure matrix (Fig 3-5) is scrambled flattened text.
- OCR/typos: NUREG-0492 has math as LaTeX and inline quote damage ("gates"which); FAA SSH has "Inprobable"; HSE ToR has "169),it" and `<sup>` tags.
- Near-duplicates: the two ISO/IEC/IEEE 15026-2:2022 previews (ANSI local:5eadc6bef925, VDE local:216b19db6b0e) share identical foreword text
  (the "Clause 7 was deleted" scan hits both), so any 2022-edition item would have two valid golds; the edition item was therefore set on the
  2011 text with both previews listed as other editions. Previews are thin (10-11 chunks, no body clauses).
- ISO 31000-2009 has no heading-based section for definitions (term headings only: "risk" chunk body starts right after the heading) - small bodies.
- Absent evidence: Def Stan 00-56 contains 0 chunks for "frequency|probability" and no numeric tolerability; HSE docs hold the numbers (distractor).
