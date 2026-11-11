# Cross-verification 2 report
Items: 56  survive: 48, fix: 8 (kills: 0)

## Non-survive items
- **Q-STD-D-003** (fix): gold_chapter_title '5 2 Contract' is a subsection heading (chunk c1432 header '5 2 Contract > 5.2.1 Basis for Contractual Liability'), not a chapter title. Fix: Drop gold_chapter_title or replace with the UK chapter's real title.
- **Q-STD-D-013** (fix): gold_chapter_title is wrong: chunk c36 is section 2.1 'Confusing Safety with Reliability' of ESW Chapter 2 'Questioning the Foundations of Traditional Safety Engineering' (TOC chunk c4); the parser filed it under Chapter 1's heading, and the label carries <sup> markup. Fix: Set gold_chapter_title to 'Questioning the Foundations of Traditional Safety Engineering' (or drop it).
- **Q-STD-D-016** (fix): Question does not name Volume 2. Volume 1 (local:a6b537ff5738) c194/c55 also says the RISC 'makes the case to decision makers' that safety objectives are achieved; only Vol 2 c71 says the pursuit is 'on track to be successful throughout the system life cycle'. Fix: Name 'Volume 2 (SP-2014-612)' in the question, as D-017/D-018 do.
- **Q-STD-E-002** (fix): ISO 21448 itself restates the 26262-1 functional-safety definition (local:d4ceb75c64ab:c9), so the 26262-1 passage is not necessary; and ISO PAS 21448:2019 (local:c0d3ca177aaf:c17) carries the same 'does not apply to faults covered by the ISO 26262 series' sentence. Fix: Accept local:c0d3ca177aaf as an alternative for passage 1, note d4ceb75c64ab:c9 shortcut, or reword to ask for the 26262-1 term number/clause wording.
- **Q-STD-E-003** (fix): AVSC-I-04 alone answers the whole question: c7 quotes the EU sentence verbatim ('The remote intervention operator shall not drive the fully automated vehicle and the ADS shall continue to perform the DDT') and c39 gives the AVSC side. Fix: Accept local:b4287480c380:c7 as an alternative support for the EU half, or reword so the EU regulation's own text (e.g. definition 24/25 wording) is required.
- **Q-STD-E-005** (fix): UL 4600 16.2.1.1 list has six items; item 6 'Fatality rates' is in the next chunk (c1238) and is omitted from answer_text, which lists only through major injury; excerpt ends at item 4. Fix: Add 'fatality rates' to answer_text and either add c1238 as a supporting chunk or phrase question as 'which of these loss-related rates (incident ... injury)'.
- **Q-STD-E-017** (fix): Content absence holds, but the stated evidence is wrong: ISO 23793-1:2024 (titled 'Minimal risk manoeuvre (MRM) for automated driving') IS cited in local:61b72628b14f:c14 and the 'ISO 23793' pattern misses it because the text reads 'ISO Standard No. 23793-1'. Also MIRA c988 gives a 4.0 m/s2 MRM deceleration aim and EU 2022/1426 c161 a 5 m/s2 emergency-braking test, near-misses. Fix: Correct answer_text to 'cited only as a reference in AVSC-I-06 c14; its limits are not reproduced'; fix the misdescription 'emergency intervention' (23793-1 is MRM).
- **Q-STD-E-025** (fix): Corpus-wide the 130 km/h fact is present: Steege local:5c15efe64f30:c1305 says 'As of January 2023, the amended Regulation 157 limits its maximum operational speed to 130kph'. No paragraph number is given anywhere, so the paragraph question is still unanswerable, but answer_text implies 130 km/h is absent from the corpus. Fix: Reword answer_text: held R157 text is 60 km/h only; Steege c1305 mentions the amended 130 km/h limit but no paragraph is given.

## Survive with notes
- Q-STD-D-001: Survive; note gold_chapter_title is a section (2.2) of a chapter, minor.
- Q-STD-D-002: Survive; gold_chapter_title is a numbered section of the US chapter, minor.
- Q-STD-D-014: Survive; c210 (same book, Ch 3) also states emergent properties are controlled by constraints, so same-book second passage possible.
- Q-STD-D-017: Survive; answer expands 'UU' as unknown and underappreciated, which is true in the book but not in c113.
- Q-STD-D-027: Survive; the phase C purpose also sits in the table row c49 (same doc).
- Q-STD-D-028: Survive; same sentence also at c58 and c347 (same doc).
- Q-STD-D-030: Survive; question stem ('use Bayes' theorem') is somewhat conspicuous as a false premise. c252 mentions 'prior probabilities' only in passing.
- Q-STD-E-004: Survive; HSE nuclear tolerability doc (local:caf714759f86 c29) also uses gross disproportion but does not state the compliance test.
- Q-STD-E-014: Survive; near-miss: EU 2022/1426 c120 says the SMS certificate of compliance is valid max three years (SMS, not CSMS/R155).
- Q-STD-E-016: Survive; near-miss: AAMVA c148 / NHTSA ADS 2.0 c98 mention a generic $5 million minimum insurance, not California/CPUC.
