# Author A log (2026-11-10)

Result: 24 items, `verify --write` = 0 failures. Mix: 7 clause, 6 definition (4 from 26262-1, plus 21434, 8800), 7 table-requirement, 2 edition, 2 partial-absent.
Max per doc: 26262-1 = 4, all others <= 2. Docs not used: 26262-4, -10 (no need to reach them), ISO TS 5083 (see below).

## Killed / reworked
- 0 items killed outright. Two first-pass failures were reworked: Q-020 (26262-6 Table 1 row too short; switched to row 1a with the header row, since the header is not adjacent to row 1d) and Q-021 (question shared a 6-word run with the PAS 21448 excerpt).
- Candidate dropped before authoring: a 21434 shall-requirement (RQ-09-05) to stay at 2 items for 21434; a TS 5083 item (nothing authorable).

## Corpus-quality observations
- **Heading-only stub chunks** are everywhere. In 26262-1 and ISO 21448/21434/8800/PAS 21448 each definition number ("3.61", "3.1.34") sits in its own tiny chunk whose section title is the PREVIOUS term (e.g. section "ASIL decomposition > 3.4" is just "3.4"). The definition text itself lives in a chunk titled with the term, but the number is detached and often attached to the next/previous term (e.g. "audit > 3.6" holds the ASIL definition; "fault tolerance > 3.61" holds FTTI). Gold chunks for definitions are therefore found by term title, not number; number-based questions ("what is 3.6?") would mis-map.
- **Tables** are rendered as Markdown pipe tables with flattened cells; table notes/footnotes and header rows are sometimes split into separate chunks (26262-3 Tables 1-4 each in own chunk; Table 4 ASIL matrix lost row spans for S/E; 26262-2 Table 1 cells merged with text, e.g. "Level of independenceaapplies to"). The 26262-5 PMHF table uses "<10-8 h-1" (superscripts lost). Footnote letters glued to labels ("complexitya", "techniquesd").
- **ISO PAS 8800**: OCR-style spacing damage and wrong glyphs ("Al" for "AI", "faultsand", "residualrisk", "quantitativetargets"); 106 chunks sit under a repeated page-header "section" `ISO/PAS8800:2024(en)`. Verbatim excerpts must reproduce the damage.
- **Section path pollution** in 21448-2022 and 26262-2/8: later clauses inherit stray section titles ("NOTE 1 Proper situational awareness relies on: > 4.3 ...", "b) Tool qualification aspects > 11.4 ...", "a) Tool usage aspects"), so section_path is not a reliable clause label.
- **ISO 34502-2022** is a 15-page iTeh preview (contents, scope, terms, start of clause 4): usable for scope/definition/4.2 only. **ISO/TS 5083-2025** is contents + foreword + licence boilerplate (17 chunks, no normative body); nothing authorable except the foreword change list, so no item was written. Its table of contents does list clause titles, so a "clause title" question would only ever hit the TOC chunk.
- iTeh watermark/URL text is spliced into body text (34502 4.2.2, TS 5083 foreword), harming chunk quality.
- Edition pair PAS 21448:2019 / 21448:2022: terminology shifts (triggering event -> triggering condition, performance limitation -> performance insufficiency, functional improvement -> functional modification), which makes good edition items; the 2022 "functional modification" definition even notes the 26262 term "change".
- Part 12 (motorcycles) near-duplicates part 3 HARA text (same S/E/C class tables, MSIL instead of ASIL): risk of cross-document confusion for table/clause questions; I avoided questions answerable from both.

## Absent items
- Q-023: PMHF in 26262-3 (0 hits in that part; PMHF lives in 26262-5 cl. 9.4.2).
- Q-024: TCL table in 26262-7 (0 hits for TCL; the 1 broad hit is the Foreword change list; TCL lives in 26262-8 cl. 11).
