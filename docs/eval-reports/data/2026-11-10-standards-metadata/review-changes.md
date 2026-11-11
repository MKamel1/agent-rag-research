# CQ-5 review: changes versus the rule-generated draft, and corpus observations

Reviewed table: `standards_metadata.json` (119 documents, validated by `scripts/standards_metadata.py
validate`: closed vocabularies, every id in the read-only DB, reciprocal supersession, every evidence
quote verbatim in its chunk). Draft: `../2026-11-10-standards-gt/standards_metadata_draft.json`.
Every document's first chunks (title page / foreword / scope / contents) were opened; decisions rest
on that text, with the chunk id in the table's `evidence`.

## Summary

- Rows where any of kind / issuer / edition_year / status / superseded_by changed: **52 of 119**
  (44 substantive; 8 only re-name the issuer canonically, e.g. `BS` -> `BSI`, `UN` -> `UNECE`).
- By field: issuer 29 (12 become null: individually authored work; 8 are renames; the rest are new or corrected issuers), edition_year 22,
  kind 20, superseded_by 1, status 0 (the draft's status values all survived review).
- New fields the draft did not have, set for all 119: designation, edition_label, normative,
  completeness, evidence, supersedes, supersedes_external, null reasons.
- Counts: kind standard 29, guidance 30, report 15, paper 14, handbook 11, slides 5, book 5, regulation 5,
  technical-specification 3, commentary 1, letter 1. Status current 107, preview-only 6, superseded 4,
  withdrawn 1, draft 1. Completeness full 112, preview 7. Normative true 23, false 93, null 3.
- edition_year is null (with reason; the draft's unverified claim is kept in `year_hint_unverified`) for 9
  documents whose held text carries no date.
- Titles in the DB that are wrong or misleading: 8 (below).

## Decisions that need explaining

- **status "current"** means "latest edition held and nothing in the corpus says otherwise". Whether a
  document is still in force cannot be read from the document, so it is not asserted.
- **normative** is true for 23 documents that are an issuing body's own text with real `shall`
  requirements. The rule for handbooks, best practices and similar: a `shall` count alone is not enough.
  AMLAS (110 `shall`), JAMA (141), MIRA (446), L3Pilot, SUNRISE and the FAA/NASA handbooks use `shall` for
  their own method or quote other bodies, and say they are guidance or voluntary, so they are false. All 20
  AVSC documents are false (they state "entirely voluntary" and have no own-text `shall`; the 9 hits in
  AVSC-I-04 quote regulations). ISO 26262 parts 1, 10, 11, ISO 31000 (both), IEC 31010, ISO/IEC/IEEE
  15026-1 and BS 31100 are standards-body documents that are vocabulary, informative, or guidance-only, so
  they are false although their kind is `standard`. The NHTSA AV STEP NPRM is false (proposed text, never in
  force). Three are null because only front matter is held: both 15026-2:2022 previews and ISO/TS 5083.
- **issuer** is null for individually authored papers, slides, letters and books (publisher is not
  treated as issuer). That is why the draft's `Koopman` issuer disappears.
- **superseded 15026-2:2011**: its replacement (2022) is held only as two previews, so the 2011 text is the
  only full assurance-case part; both previews are linked as its `superseded_by`.

## Titles in the database that are wrong or misleading

| paper_id | Title says | Held text says |
|---|---|---|
| local:102762ff148b | Letter dated 2021-07-01 | "July 2, 2021" |
| local:1c13661fcaa8 | Kelly, SAE 2004 | "Copyright (c) 2003 SAE International"; no 2004 anywhere |
| local:5bf506972f70 | NASA SP-2014-612 (2014) | signed preface "June 2015" |
| local:a6b537ff5738 | NASA SP-2010-580 | version 1.0 is dated Nov. 2011 (cited so by local:cf129f19b0b0); the number's 2010 is not the issue date |
| local:54d6dfdea249 | MIRA for DfT (2022) | "(c) HORIBA MIRA Ltd 2023" |
| local:c3c5f9de20cc | UL 4600 Voting Version (December 13 2019) | "December 13" is not in the text; proposal issued 2019-10-02, ballots due 2020-01-27 |
| local:a9c7b643276b | NHTSA AV STEP Withdrawal (91 FR 38619) | "91 FR 38619" is not in the text; FR Doc. 2026-12912 is |
| local:cf129f19b0b0 | AdvoCATE User Guide 1.4 | describes AdvoCATE 0.34.1-s; "1.4" never appears |

Also misleading but not wrong titles: `doc_type` is `book` for 10 documents that are not books (CAIB report,
FAA AC 120-92D, JAMA framework, NASA SP-2014-612, NASA SE Handbook, RAND RR-A569-1 among them) and `paper`
for 109 documents that are standards, regulations and handbooks; `published` is a placeholder (Jan 1 or the
ingest date) for most rows, e.g. AIAG-VDA 2026-11-02 for a 2019 handbook, Wachenfeld 2007-01-01.

## Row-by-row changes

| paper_id | title | field | draft | reviewed | evidence / reason |
|---|---|---|---|---|---|
| 2004.10474 | Bloomfield and Rushby — Assurance 2.0, A Manifes | edition_year | None | 2020 | (arxiv-date) 2004.10474:c0: "Assurance 2.0: A Manifesto Assurance 2.0: A Manifesto Ro" |
| 2103.05440 | Krisper — Problems with Risk Matrices Using Ordi | edition_year | None | 2021 | (arxiv-date) 2103.05440:c0: "Problems with Risk Matrices Using Ordinal Scales Problems with Risk Matrices U" |
| 1708.06374 | On a Formal Model of Safe and Scalable Self-driv | edition_year | None | 2017 | 1708.06374:c0: "ing Cars Shai Shalev-Shwartz, Shaked Shammah, Amnon Shashua Mobileye, 2017" |
| local:1c13661fcaa8 | Kelly — A Systematic Approach to Safety Case Man | edition_year | 2004 | 2003 | local:1c13661fcaa8:c0: "Kelly University of York, UK Copyright © 2003 SAE International" |
| local:36fe900b97bc | Koopman and Wagner — Positive Trust Balance for  | issuer | Koopman | None | individually authored: no issuing body |
| local:475ad494687d | Koopman and Widen — Breaking the Tyranny of Net  | issuer | Koopman | None | individually authored: no issuing body |
| local:475ad494687d | Koopman and Widen — Breaking the Tyranny of Net  | edition_year | 2024 | None | held text carries no publication date or venue line; only the DB title says 'SCSC eJournal 2024' |
| local:44e5e7678422 | Koopman and Widen — Redefining Safety for Autono | issuer | Koopman | None | individually authored: no issuing body |
| local:884acc517acd | Koopman, Kane and Black — Credible Autonomy Safe | issuer | Koopman | None | individually authored: no issuing body |
| local:884acc517acd | Koopman, Kane and Black — Credible Autonomy Safe | edition_year | 2019 | None | held text carries no date or venue line; only the DB title says 'SSS 2019' |
| local:be80930e409d | Wachenfeld and Winner — The Release of Autonomou | edition_year | 2016 | None | held text has no publication year; only the DB title says 'Springer 2016' |
| local:5893db5c997f | UL 4600 - What to Include in an Autonomous Vehic | kind | commentary | paper | It is a magazine-style article by Koopman about UL 4600, not a UL document (c0: 'Philip Koopman, Carnegie Mellon University UL 4600 provides an umbrella...'). |
| local:5893db5c997f | UL 4600 - What to Include in an Autonomous Vehic | issuer | UL | None | Author's article; UL did not issue it. |
| local:102762ff148b | Koopman — Letter on UL 4600 (2021-07-01) | kind | commentary | letter | A letter (to a state transportation commission), not commentary on a standard. |
| local:102762ff148b | Koopman — Letter on UL 4600 (2021-07-01) | issuer | Koopman | None | individually authored: no issuing body |
| local:9adcc5121bd5 | Koopman — UL 4600 third edition update, slides ( | issuer | Koopman | None | individually authored: no issuing body |
| local:dcb47a114938 | Koopman — L131 How Safe Is Safe Enough, slides ( | issuer | Koopman | None | individually authored: no issuing body |
| local:a52a42ac3822 | Koopman — L144 AV Safety and Net Risk, slides | issuer | Koopman | None | individually authored: no issuing body |
| local:a52a42ac3822 | Koopman — L144 AV Safety and Net Risk, slides | edition_year | None | 2024 | local:a52a42ac3822:c0: "le Safety: More Than Net Risk Carnegie Mellon University May 7, 2024 www. Koopman.us" |
| local:321336803fc1 | Koopman — L152 Understanding AV Safety, slides ( | issuer | Koopman | None | individually authored: no issuing body |
| local:8a590e370f52 | Koopman — How Safe Is Safe Enough, free book pre | kind | commentary | book | A general book on AV safety measurement; only the Guidebook sample interprets a specific standard. |
| local:8a590e370f52 | Koopman — How Safe Is Safe Enough, free book pre | issuer | Koopman | None | individually authored: no issuing body |
| local:5490e626ec16 | Koopman — The UL 4600 Guidebook, free sample (20 | issuer | Koopman | None | individually authored: no issuing body |
| local:18f76aaa8a8c | Holloway and Wasson — A Primer on Argument Asses | kind | handbook | paper | A NASA/Joby primer paper, not a handbook issued by a body. |
| local:71c88a1d2bc1 | AAMVA Guidelines for Regulating Vehicles with Au | edition_year | None | 2024 | local:71c88a1d2bc1:c2: "ith Automated Driving Systems Edition 4 March 2024 AUTOMATED VEHICLES SUBCOMMITT" |
| 2102.01564 | AMLAS — Guidance on the Assurance of Machine Lea | issuer | None | University of York (AAIP) | issuer is the publishing body printed in the document |
| local:4c537c7906e8 | AVSC00006 Best Practice for Metrics and Methods  | edition_year | None | 2021 | local:4c537c7906e8:c1: "Citation: Automated Vehicle Safety Consortium. 2021. Best Practice for Metrics and Methods" |
| local:a14c3d11c6dc | AVSC00007 Information Report for Adapting a Safe | kind | guidance | report | Self-titled 'Information Report'. |
| local:a14c3d11c6dc | AVSC00007 Information Report for Adapting a Safe | edition_year | None | 2021 | local:a14c3d11c6dc:c1: "Citation: Automated Vehicle Safety Consortium. 2021. Information Report for Adapting" |
| local:b827e7b12a07 | AVSC00008 Best Practice for Evaluation of Behavi | edition_year | None | 2021 | local:b827e7b12a07:c9: "-Dedicated Vehicles (ADS-DV) (AVSC00008202111) describes an elemental set o" |
| local:a89e28ee7840 | AVSC00009 Best Practice for Interactions Between | edition_year | None | 2022 | local:a89e28ee7840:c0: "ety Consortium™ Best Practice AVSC00009202208 Issued 2022-08 Citation: Automated Vehicle S" |
| local:d6d9d9a1057d | AVSC00010 Information Report for Change Risk Man | kind | guidance | report | Self-titled 'Information Report'. |
| local:d6d9d9a1057d | AVSC00010 Information Report for Change Risk Man | edition_year | None | 2023 | local:d6d9d9a1057d:c0: "AVSC00010202304 Automated Vehicle Safety Consortium™ Information Report Issued 2023-04" |
| local:d38dea63d22f | AVSC00011 Best Practice for Continuous Monitorin | edition_year | None | 2023 | local:d38dea63d22f:c0: "fety Consortium™Best Practice AVSC00011202307 Issued 2023-07 Rationale Citation: Automated" |
| local:6a33889859b2 | AVSC00012 Best Practice for Developing ADS Safet | edition_year | None | 2023 | local:6a33889859b2:c0: "sed on Human Driving Behavior Issued 2023-08 Automated Vehicle Safety Cons" |
| local:61b72628b14f | AVSC-I-06-2025 Information Report on ADS-DV Stop | kind | guidance | report | Self-titled 'Information Report'. |
| local:c9a451f83ae4 | Assurance Case Guide (Argevide) - GSN and Assura | kind | handbook | guidance | A guide (Part 1 of a series), not a handbook. |
| local:c9a451f83ae4 | Assurance Case Guide (Argevide) - GSN and Assura | issuer | None | Argevide | A guide (Part 1 of a series), not a handbook. |
| local:c9a451f83ae4 | Assurance Case Guide (Argevide) - GSN and Assura | edition_year | None | 2025 | local:c9a451f83ae4:c1: "Part 1. Argument Structure 25.04.2025 1 Introduction ... ...2 2 The" |
| local:a41019a5b430 | BS 31100-2011 — Risk Management Code of Practice | issuer | BS | BSI | canonical name |
| local:5d92cd1f17dd | CAIB — Columbia Accident Investigation Board Rep | issuer | CAIB | Columbia Accident Investigation Board | canonical name |
| local:cf59ff8a1e69 | CRS R48605 Safety Considerations for Automated P | issuer | CRS | Congressional Research Service | canonical name |
| local:77d354cc8af7 | EU Commission Implementing Regulation 2022-1426  | issuer | EU Commission | European Commission | canonical name |
| local:d5f3d058bb27 | HSE — Reducing Risks, Protecting People: HSE dec | kind | handbook | guidance | Regulator's decision-making framework (policy); no handbook structure. |
| local:caf714759f86 | HSE — The tolerability of risk from nuclear powe | kind | handbook | guidance | Regulator's tolerability-of-risk policy document. |
| local:c0d3ca177aaf | ISO PAS 21448-2019 — SOTIF (BSI) | kind | standard | technical-specification | ISO/PAS is a publicly available specification, not an International Standard; issuer is ISO. |
| local:c0d3ca177aaf | ISO PAS 21448-2019 — SOTIF (BSI) | issuer | ISO PAS | ISO | ISO/PAS is a publicly available specification, not an International Standard; issuer is ISO. |
| local:1a5e084cb8bb | ISO PAS 8800-2024 — Safety and Artificial Intell | kind | standard | technical-specification | ISO/PAS: publicly available specification. |
| local:1a5e084cb8bb | ISO PAS 8800-2024 — Safety and Artificial Intell | issuer | ISO PAS | ISO | ISO/PAS: publicly available specification. |
| local:6c9b33bfde9d | ISO TS 5083 2025 — Road vehicles, Safety for aut | kind | standard | technical-specification | ISO/TS: technical specification. |
| local:6c9b33bfde9d | ISO TS 5083 2025 — Road vehicles, Safety for aut | issuer | ISO TS | ISO | ISO/TS: technical specification. |
| local:c22b61a61eaa | ISO-IEC 15026-2-2011 — Systems and Software Assu | superseded_by | local:5eadc6bef925 | local:5eadc6bef925, local:216b19db6b0e | The 2022 edition is held as two preview documents (same standard); both cancel 15026-2:2011. |
| local:4332c96f2fd6 | MIL-STD-882E — Department of Defense Standard Pr | issuer | MIL STD | US Department of Defense | canonical name |
| local:54d6dfdea249 | MIRA for DfT — Automated Vehicle Safety Assuranc | kind | guidance | report | Report commissioned by DfT; front matter disclaims DfT's position. |
| local:54d6dfdea249 | MIRA for DfT — Automated Vehicle Safety Assuranc | issuer | MIRA | HORIBA MIRA | canonical name |
| local:54d6dfdea249 | MIRA for DfT — Automated Vehicle Safety Assuranc | edition_year | 2022 | 2023 | local:54d6dfdea249:c0: "A TRL THE FUTURE OF TRANSPORT © HORIBA MIRA Ltd 2023. All rights reserved, subject" |
| local:a6b537ff5738 | NASA SP-2010-580 — NASA System Safety Handbook V | edition_year | 2010 | 2011 | (cross-reference) local:cf129f19b0b0:c7: "Concepts for Implementation. NASA/SP-2010-580, Version 1.0, Nov. 2011. URL: https://ntrs.nasa.gov/c" |
| local:a391e0d13fa8 | NASA SP-2011-3421 — Probabilistic Risk Assessmen | kind | paper | handbook | A NASA procedures guide (handbook-type), not a paper. |
| local:5bf506972f70 | NASA SP-2014-612 — NASA System Safety Handbook,  | edition_year | 2014 | 2015 | local:5bf506972f70:c31: "surance Requirements Division Office of Safety and Mission Assurance June 2015" |
| local:64f9538c2b0f | NHTSA A Framework for Automated Driving System T | kind | guidance | report | A contractor research report (DOT HS 812 623), 'opinions ... are those of the authors'. |
| local:0bba4df6673d | NUREG-0492 — Fault Tree Handbook (NRC, 1981) | issuer | NUREG | US Nuclear Regulatory Commission | canonical name |
| local:b468bf45f27c | PEGASUS Method - An Overview (2019) | kind | guidance | report | An index/landing page for the PEGASUS project, not guidance. |
| local:b468bf45f27c | PEGASUS Method - An Overview (2019) | issuer | None | PEGASUS project | An index/landing page for the PEGASUS project, not guidance. |
| local:b468bf45f27c | PEGASUS Method - An Overview (2019) | edition_year | 2019 | None | held text carries no date; only the DB title says 2019 |
| local:0147e45dfd6e | SUNRISE D8.1 — Final report to vehicle safety bo | kind | guidance | report | EU project deliverable (report). |
| local:0147e45dfd6e | SUNRISE D8.1 — Final report to vehicle safety bo | issuer | SUNRISE | SUNRISE project | canonical name |
| local:0147e45dfd6e | SUNRISE D8.1 — Final report to vehicle safety bo | edition_year | None | 2025 | local:0147e45dfd6e:c3: "ponsible Bryan Bourauel, BASt Status - Version Final – V1.0 Submission date 28/08/2025 Keywords Vehicle, Safet" |
| local:23f46dde097b | Safety First for Automated Driving (SaFAD white  | kind | guidance | report | Industry white paper that disclaims setting any requirement. |
| local:23f46dde097b | Safety First for Automated Driving (SaFAD white  | issuer | None | SaFAD consortium | Industry white paper that disclaims setting any requirement. |
| local:0bc74d2bea76 | UK Defence Standard 00-56 Part 1 Issue 7 — Safet | issuer | UK Defence | UK Ministry of Defence | canonical name |
| local:9def83274286 | UN Regulation No 157 — Automated Lane Keeping Sy | issuer | UN | UNECE | canonical name |
| local:3d0e31c34a0a | USDOT Ensuring American Leadership in Automated  | kind | guidance | report | 'A Report by the NSTC and the USDOT'. |

## Corpus-level observations

1. **UL 4600 is held only as the 2019 voting draft** (local:c3c5f9de20cc, status `draft`), plus Koopman's
   papers, slides, letter and two book previews. No published edition (the 2023 slides say the 3rd edition
   appeared March 2023) is held. Every chunk of the draft carries the running header "16 Metrics and Safety
   Performance Indicators (SPIs)", so its section_path is wrong for most of the document (author-E log).
2. **Seven documents are previews** (`completeness: preview`): ISO 34502, ISO/TS 5083, both ISO/IEC/IEEE
   15026-2:2022 previews, Koopman's book preview, the UL 4600 Guidebook sample, and the PEGASUS index page.
   Six are `status: preview-only`; PEGASUS is `current` but holds no chapter content.
3. **Superseded editions are held and look like peers**: AVSC00005, ISO/PAS 21448:2019, ISO 31000:2009,
   ISO/IEC 15026-2:2011. Without the status tag a search for "ISO 31000 risk" returns both editions.
4. **Withdrawn and draft text reads as authoritative**: the AV STEP NPRM (withdrawn by local:a9c7b643276b)
   and the UL 4600 draft both use requirement language.
5. **NHTSA AV STEP withdrawal file is not a clean document**: chunk c0 is the tail of another Federal
   Register document and the file includes an unrelated FTA notice.
6. **Same-lineage duplicates, not duplicates**: the two Koopman "Key Ideas: UL 4600" decks (undated one,
   and June 2023) are not linked as superseded because no document text says so.
7. **BS 31100:2011 implements ISO 31000:2009**, the superseded edition (its own text), so its status
   "current" is only "latest BS 31100 held".
8. **UN R157 is the 00 series** (EUR-Lex copy). The author-E log records the 01 series as missing and
   that the 130 km/h item is unanswerable from 00; the text says only the original UN/ECE text has legal
   effect.
9. **Missing documents**: see `ACQUISITIONS.md` (each author-E item re-checked against all 35,714 chunks;
   none is held as a document).
