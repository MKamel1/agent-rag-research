# Author E log (cross-document + absent), 2026-11-10

Result: 26 items, verify 0 failures. 12 cross-document, 9 absent, 5 partial-absent. 0 items killed
(two initial drafts failed verbatim checks because of PDF-slide bullet glyphs U+F06C in the Koopman slides; fixed by copying the glyph).
Difficulty: 4 easy-ish/ 15 medium / 7 hard (approx).

## Cross-document (Q-STD-E-001..012)
001 MIL-STD-882E severity vs ISO 26262-3 S0-S3; 002 ISO 21448 scope vs ISO 26262-1 functional safety;
003 EU 2022/1426 vs AVSC-I-04 remote assistance/DDT; 004 HSE R2P2 gross disproportion vs Koopman L131 ALARP;
005 UL 4600 voting SPI categories vs Koopman 3rd-ed slides; 006 SaFAD vs Koopman-Wagner positive risk balance;
007 hazard: MIL-STD-882E / STPA Handbook / ISO 26262-1 (3 docs); 008 ODD: UN R157 vs AVSC00002;
009 FAA AC 25.1309-1B 1e-9 caveat vs ISO 26262-5 PMHF table; 010 MIL-STD-882E matrix vs Krisper range compression;
011 UL 4600 (acceptable risk out of scope) vs EU 2022/1426 unreasonable risk; 012 IEC 31010 RPN vs AIAG-VDA RPN.
21 distinct documents; max per doc: MIL-STD-882E 3, ISO 26262-1 2, EU 2022/1426 2, UL 4600 voting 2.

## Absent (013-021) and partial-absent (022-026)
Absent: IEEE 2846, UN R155 certificate validity, China GB/T 40429, California CPUC permit, ISO 23793-1, IEC 62443 FRs,
ISO 15622 ACC, EU AI Act Art. 9, ISO 13849 PL/PFHd. Partial-absent: UL 4600 numeric SPI threshold, ISO 26262-5 PMHF for ASIL A
(table has D/C/B only), ISO 34502 Annex B (preview only), UN R157 130 km/h (00 series is 60 km/h), ISO/TS 5083 cl. 6.2 (preview only).

Candidates REJECTED after scanning (they ARE answerable): IEC 61508 SIL/PFH table (Rausand and Haugen has it),
UK Automated Vehicles Act statement of safety principles (Steege book covers it), EN 50126 (Rausand discusses), DO-178C (FAA handbook discusses).
Pitfall: gt_tools scan is case-insensitive, so short patterns like NIST/PLd/THR match inside ordinary words (thousands of hits).

## Corpus observations
- UL 4600 voting version (local:c3c5f9de20cc, 1384 chunks): every chunk is prefixed with the running header
  "16 Metrics and Safety Performance Indicators (SPIs)" / "FOR UL INTERNAL REFERENCE..." regardless of real clause, so clause
  section_paths are wrong for most of the document; a retriever will see "SPI" in ~1400 chunks. Table of clauses is also chunked.
- Koopman slide decks carry private-use bullet glyphs (U+F06C, U+F06E) in text; exact-string matching fails without them.
- Duplicate/superseded: ISO 15026-2 2022 ANSI preview and VDE preview (10/11 chunks) plus ISO-IEC 15026-2-2011 (full);
  ISO PAS 21448-2019 and ISO 21448-2022; ISO 31000-2009 and 2018; AVSC00005 superseded by AVSC-I-01-2024; NHTSA AV STEP NPRM
  (2025) superseded by the 2026 withdrawal; MIL-STD-882E only (882C is only quoted in Krisper); UL 4600 held as voting draft 2019,
  Koopman paper/slides, not the final edition 1-3 text.
- Thin previews: ISO 34502 (15 pages, 41 chunks), ISO/TS 5083 (17 chunks), both 15026-2 2022 previews; SAE J3016 not held as a
  document (only via AAMVA/AVSC quotation). ISO 26262 part 3 table cells are chunked as separate table chunks without headings.
- Expected-but-missing: IEEE 2846, ISO 22737 (only cited in MIRA), ISO 34503, ISO 23793, UN R155/R156 (cited only), SAE J3016 full text,
  IEC 61508 (only via Rausand), DO-178C, EN 50126/50128/50129, ISO 13849, IEC 62443, ISO/IEC 42001, EU AI Act, Chinese GB/T,
  UL 4600 ed.1-4 final text, UN R157 01 series, ISO 26262-13/14 do not exist.
