# Author C log (2026-11-10)

Result: 24 items, `verify --write` = 0 failures. Mix: 5 clause-lookup, 10 guidance-factual (7 numeric/count answers), 5 authority, 2 definition-lookup, 2 partial-absent. Max 2 items per document. Killed items: 0 after verification (3 drafts failed mechanical checks and were rephrased/extended, not abandoned: two 6-word question/excerpt overlaps, one excerpt under 8 words).

## Coverage
- Clause: UN R157 7.1.1; AVSC-I-01-2024 6.1.1.8; AVSC00002 4.4; EU 2022/1426 Annex III Part 2 s.7; SAE J3018 6.3.
- Definition: SAE J3018 3.16 shadow mode; AVSC00003 PEC.
- Guidance: RAND RR1478, PEGASUS, AV STEP withdrawal, AAMVA, Wachenfeld/Winner, Koopman L144, Krisper, SUNRISE D8.1, SaFAD, AVSC-D-04.
- Authority (gold = normative doc; commentary listed): UL 4600 6.4.1.2 (commentary: Koopman Key Ideas slides, UL 4600 3rd-ed slides); UL 4600 16.2.2 lagging metrics (Koopman book preview, Positive Trust Balance, WAISE UL4600 paper); R157 5.4.4.1 (Steege book); SGO 30-second window (CRS R48605, AV STEP NPRM, which restates it); EU 2022/1426 Annex II 5.1 MRM deceleration (MIRA framework, which reproduces it).
- Partial-absent: R157 at 130 km/h with lane changes (00 series is 60 km/h max); AVSC00001 numeric daily-hours cap (only "policy should set" + FAA/FMCSA analogies).

## Corpus-quality observations
1. UL 4600 Voting Version: ~196+ chunks carry the running footer "FOR UL INTERNAL REFERENCE OR CSDS USE ONLY" as their section_path root, and the page header "16 Metrics and SPIs" is prepended to chunks from unrelated clauses (e.g. 6.4.1.2). Section paths are unreliable; the clause number lives only in the body. The same clause text is reproduced verbatim in Koopman slides (Key Ideas, 3rd-ed update), so authority retrieval can legitimately land on commentary.
2. UN R157: section_path mismatches body (chunk c29 is labelled "5.2.5.2 ... cutting in vehicle" but contains 5.4.3-5.4.4.1). Many "Where:" paths. Tables flattened to Markdown (time-gap table).
3. SAE J3018: OCR spacing damage inside words in headings and body ("6 .3 I FTD S tate Mon i toring", "pu rposes of th is documen t"); excerpts must be chosen from clean sentences. Section 6.5 has a missing full stop.
4. AAMVA: section paths collapse to generic labels ("Background" x74, "Recommendations for Jurisdictions" x64), recommendations appear twice with different footnote numbers (chapter body and consolidated list), and a page header ("SAE J3016 LEVELS OF DRIVING AUTOMATION Learn more...") is injected into chunk text.
5. Slide decks (Koopman L144 etc.) are parsed one slide per chunk with a repeated slide-title prefix ("Humans are terrible drivers"); content is bullet fragments, titles-only chunks and image captions are frequent. PEGASUS (8 chunks) is a brochure of tables of contents; only c1 holds prose.
6. NHTSA AV STEP withdrawal: chunk c0 is the end of the document (figure caption, signature), order is rotated. Zenzic section paths are wrong ("PHYSICAL SECURITY CONTROLS > 7.1 Change control" over change-control text). EU 2022/1426 and R157 embed `<sup>` tags; some formulas are LaTeX in RSS/Wachenfeld.
7. Superseded versions: AVSC00005 and AVSC-I-01-2024 both have the first-responder plan elements; clause item 2 names AVSC-I-01-2024 explicitly. Not tested as an `edition` item (outside my brief).
