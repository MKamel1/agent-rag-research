# Cross-verification report

Totals: 75 items. survive 43, fix 31, kill 1.

Method: read every gold chunk, compared against the 23 existing items per book, grepped each book for the answer terms, and re-scanned the 5 absent items with ligature-tolerant regexes and synonyms.

## Kill
- Q-CB-H-022: duplicate of existing QB-037 (local:54d6ca71dda9:c419, Abadie-Imbens analytical SE because bootstrap fails on discrete matching). Same fact also in c408 (gold) and c417.

## Fix (all label-only: delete gold_chapter_title)
- Q-CB-I-001..015, I-017..028 (27 items): titles such as 'Malware Reduction', 'Peeking at p-values', 'The Bias Equation', 'T-Learner' are subsection headings; the corpus heading hierarchy is flat for these two books so they were taken for chapters. I-016 ('The Most Dangerous Equation') opens a chapter and was accepted.
- Q-CB-J-002, J-003, J-005: 'Notation and Terminology' is the front-matter heading mis-propagated onto ch.1-2 content (section_path 1.4.1 / 2.3.3 / 2.2).
- Q-CB-J-012: '{probabilistically/interventionally/counterfactually} equivalent' is a stray fragment, not a chapter heading.
- Alternatives noted: I-022 also c180 (only one model needs to be right); I-026 also c285 (attribution is not incrementality, geo units).

## Survive with alternatives
- Q-CB-H-013 also c459 (DECI chunk restates R(A)=0 iff DAG); Q-CB-H-026 also c566, c567 (McCrary test).

## Absent items (all 5 hold)
- H-015 (Granger, Molak): 0 hits for granger; autoregress hits are normalizing flows only.
- H-030 (mediation, Econ ML): 0 for mediat (3 hits are 'immediate/intermediate'), no NDE/NIE/ACME/Sobel.
- I-029 (synthetic control, Trustworthy): 0 for 'synthetic', donor, CausalImpact; c117 DMA TV-ads and c112 BSTS mention do not describe a synthetic-control construction.
- I-030 (Heckman, Facure): 0 for heckman|mills|tobit|censor|truncat.
- J-015 (RDD, Elements): 0 for discontinuit|RDD|running variable|cutoff.

All other items: answer fully supported by the gold chunk, no duplicate of existing items, book-anchored.