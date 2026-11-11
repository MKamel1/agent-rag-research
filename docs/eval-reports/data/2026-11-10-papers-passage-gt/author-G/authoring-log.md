# Author G authoring log (papers passage GT)

Result: 30 items from 30 of 32 papers, `verify --write` = 30 items, 0 failures.
Dimensions: numeric-result 8, method-detail 10, equation-context 5, paper-passage 7.
Difficulty: easy 9, medium 15, hard 6. Killed after drafting: 0 (one item reworded after the 6-word-copy check failed: Q-PAPG-026).
Per-item checks: a paper-scoped `scan` on key answer terms for every item. Two items have `alternative_gold_chunk_ids`: 2210.11186 (c23 Summary restates the stress-energy result) and 2105.00416 (c16 states the Naive-vs-selective-inference reason generically).

## Papers skipped (2)
- 2303.10544 (quantum causal inference): skipped only because the dimension quotas were already full; text is usable but Results chunks (4 chunks of 5-7k chars) are dense math with 12 array-style equations and the section header is just "Results" for all of them.
- 2204.01169 (extended tetrad analysis): same reason; 19 array equations, 10 consecutive "5 From Local to Global Separability" chunks of 5-6.8k chars that are theorem/proof text with little quotable prose.
Both papers (and 2210.11186, a physics paper, plus 2207.13512, 2606.* ML papers) are off-topic for a causal-inference corpus.

## Text-quality observations (counts over the 32 papers, 1,073 chunks)
- Oversized chunks (>8,000 chars): 25 (2.3% of chunks), up to 14,891 chars (2410.23521:c29, tables and figure legends) and 12,593 (2306.01969:c20, empirical application). Several mix unrelated material: 2606.05448:c8 (11.7k) is the whole Discussion; 2306.01969 c19/c20 are 9.1k/12.6k.
- Missing section structure: 1808.04246 has 10 chunks (c0-c9, ~66k chars, whole main body incl. theorems) with an empty section path, and "8. Auxiliary results" is placed after References. 2210.15829 has a stray "5. Simulation illustration for RSMD and D-RSMD" chunk (c52) after Appendix D.
- OCR damage: 2512.19349 (VIGOR+) contains 2,318 `<sub>` tags, with words split letter-by-letter (e.g. "W<sub>e eva</sub>l<sub>ua</sub>t..."), unusable for lexical matching; I could only use a clean bullet line from it. Other papers carry 1-133 stray `<sub>` tags (2210.15829: 133).
- Broken or unreadable equations/tables: LaTeX is letter-spaced ("$N = 5 0 0$") in nearly all papers; 289 chunks contain `\begin{array}`. Result tables are flattened into mis-aligned pipe rows with merged cells (e.g. 2105.00416:c17, 2606.22126:c14, 2606.15637:c34), so table numbers cannot be quoted cleanly; I used prose sentences instead. Unrecoverable glyphs (U+FFFD) appear as variable names in 2512.19349 (e.g. "[�,�, �]"). Ligature-dropped words ("efect", "diference", "eficient") occur in most papers.
- Reference lists: 23 of the 30 papers that have a References section keep only a heading stub (60-190 chars); the other 7 hold 78k chars of bibliography as content, 65k of it in 12 chunks of 1808.04246 ("References." section, ~5.5k chars each). 2512.18997 has 3.8k, 2103.15218 2.8k, 2210.15829 2.2k.
- Stub chunks: 81 non-reference chunks under 150 chars (heading-only, e.g. "2 Theory", "Results"); 2606.22126 has 17 micro-chunks for dataset case studies (Case N / Question: / Candidate answers:).
- Appendix boilerplate chunked as content: long proof appendices (2210.15829 c25-c51 = 27 chunks, 2602.07825 c62-c90, 2510.14780 c32-c56, 2204.01169 c46-c52) outnumber main-text chunks.
- Internal inconsistency in source: 1803.08218 states T0 = surgery+chemo+radiation (1286) and T1 = surgery+chemo only in the dataset chunk but T0 = S+CT, T1 = S+CT+RT in the algorithm chunk.
- Boilerplate preamble: 2606.15637 chunks carry "Graphical Abstract" as the doc header; 2606.22126 and 2606.23548 repeat the paper title as the first line of every chunk.
