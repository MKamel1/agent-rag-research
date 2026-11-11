# Crossverify-1

Items: 72; survive 67, fix 5, kill 0.

## Non-survive items
- Q-STD-A-018 (fix): ISO 26262-12 chunk dbb1c4619d93 carries the same independence NOTE ('aim of the independence defined in Table 1 is to ensure an objective, unbiased viewpoint ... organizational independence'); question names part 2 only. Fix: Add local:dbb1c4619d93 to additional_gold_paper_ids.
- Q-STD-B-014 (fix): Identical DFMEA severity table (S9 'Noncompliance with regulations') also sits in same-paper chunk c473 (Annex C1.1); FMEA-MSR tables c343/c530 differ in name only. Chunk-level scoring could penalise a correct hit on c473. Fix: Accept 0aa9a802631e:c473 as an alternative gold chunk.
- Q-STD-C-002 (fix): AVSC00005 (superseded predecessor, chunk text '6.1.1.8 De-Powering ADS-DV. Describe the vehicle's electrical power source(s)...') has identical wording; question does not exclude it. Fix: Add local:fff17ed80281 to additional_gold_paper_ids.
- Q-STD-C-018 (fix): The two listed 'commentary' slide decks contain the clause verbatim (1c1a92b73224:c13 '6.4.1.2 REQUIRED: a) Use of at least one of the following risk evaluation approaches: 1) Risk table ...'; 9adcc5121bd5 same), so they answer equally and are not commentary. Fix: Move both ids from commentary_paper_ids to additional_gold_paper_ids (or drop authority label).
- Q-STD-C-019 (fix): Commentary local:9f51671af209 (chunk c15) only has a bullet '(e.g., use of leading and lagging metrics)' and does not discuss the topic; 8a590e370f52 and 36fe900b97bc do. Fix: Remove local:9f51671af209 from commentary_paper_ids.

Absent/partial-absent items (A-023, A-024, B-023, B-024, C-023, C-024) all survived falsification scans.
