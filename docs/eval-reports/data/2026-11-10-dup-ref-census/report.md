# CQ-6: duplicate-document and reference-content census (2026-11-10)

All work is read-only. Every corpus database was opened only as `file:<path>?mode=ro`.
Nothing was written to any `papers.db`, to Qdrant, or to any service.

Corpora:

| Corpus | Papers | Chunks | Chunk chars |
|---|---|---|---|
| main `research-system-rag-data/papers.db` | 12,390 | 399,676 | 1,080,386,685 |
| waymo `research-system-rag/waymo/data/papers.db` | 1,861 | 47,771 | 99,499,771 |
| standards `research-system-rag-standards/data/papers.db` | 119 | 35,714 | 28,394,030 |

## Verified vs heuristic

- **Verified (deterministic):** title-equality groups, exact 2,000-character prefix groups, the
  section-path reference counts (last element of `section_path`), heading-only stub counts, and
  the full-text shingle overlap figures. These are exact computations over the stored text.
- **Heuristic (estimate, not verified):** the content-based "looks like a reference list" count,
  and the judgement that a duplicate-looking pair is "the same paper". The heuristic has known
  false negatives (wrapped entries whose first line has no marker) and false positives (bulleted
  in-text citation lists). I hand-checked only the 5 examples below, and I tightened the heuristic
  after the first run flagged introduction prose; the tightened version was checked on the same
  examples, so it is not an independent validation.
- **Verified but misleading:** section-matched counts only prove the *label*. Example
  `1208.4360:c39` is labelled `REFERENCES` but its text is an observation data table (470 kB).
  So "section = References" overstates real bibliography. Treat top-15 reference-character lists
  as candidates to read, not as bibliographies.
- **Not verified:** whether a title-equal pair is the same work or a different work with the same
  title (for example two different arXiv ids). Those are marked "candidate" below.

## Part A: duplicate documents

### A1. Existing instrument: `scripts/find_duplicate_papers.py`

Its argparse (`--db`, `--curated`, `--threshold`) accepts a DB path directly. Reading the source
confirms it only opens the DB with `mode=ro` and prints. It deletes nothing. Its `--curated`
default points at the Waymo fixture, which does not apply to other corpora, so I passed an empty
file to avoid misleading `curated` tags.

```
conda run -n agent-rag-research python scripts/find_duplicate_papers.py --db /home/omar/ai-projects/research-system-rag-standards/data/papers.db --curated <empty file> > find_dups_standards.txt
conda run -n agent-rag-research python scripts/find_duplicate_papers.py --db /home/omar/ai-projects/research-system-rag-data/papers.db --curated <empty file> > find_dups_main.txt
```

Results: standards 4 pairs (see below), main 7 pairs (`find_dups_main.txt`).

### A2. My census: `dup_census.py`

Written because the existing instrument only does a 5-gram Jaccard over the first 40 chunks, and
the brief asked for title-equality and 2,000-character prefix signals. It streams the chunks and
checks two signals: (i) title equal after lowercasing and removing non-alphanumerics (titles
under 10 characters ignored), and (ii) identical first 2,000 characters of chunk text in rowid
order (papers with prefix under 200 characters ignored). A looser lowercase/whitespace-collapsed
tier is also reported. `--pair` gives full-text 5-word shingle Jaccard and containment.

```
conda run -n agent-rag-research python dup_census.py --db /home/omar/ai-projects/research-system-rag-data/papers.db > main_dup_census.txt
conda run -n agent-rag-research python dup_census.py --db /home/omar/ai-projects/research-system-rag/waymo/data/papers.db > waymo_dup_census.txt
conda run -n agent-rag-research python dup_census.py --db /home/omar/ai-projects/research-system-rag-standards/data/papers.db --table > std_census.txt
conda run -n agent-rag-research python dup_census.py --db <standards db> --pair local:216b19db6b0e local:5eadc6bef925 --pair local:fff17ed80281 local:b6c10359d954 --pair local:c0d3ca177aaf local:d4ceb75c64ab --pair local:fe96edbde0ee local:7bfd4a363756 > std_pairs.txt
```

### A3. Group counts

| Corpus | Title-equal groups | Exact prefix groups (not already title) | Existing-instrument extra pairs (text overlap only) | Total candidate groups |
|---|---|---|---|---|
| main | 4 (4 redundant docs) | 0 | 4 | 8 candidate groups, 8 redundant docs |
| waymo | 6 (6 redundant) | 2 | not run | 8 groups, 8 redundant docs |
| standards | 0 | 0 | 4 pairs; 1 is a real duplicate, 3 are not | 1 confirmed group, 1 redundant doc |

Fewer than 30 clear groups exist in any corpus, so the list below is complete.

### A4. Clearest groups

**Main (title-equal, all four are candidates; arXiv ids differ):**
1. `1210.4792` / `1408.2066`: "Scalable Matrix-valued Kernel Learning for High-dimensional Nonlinear Multivariate Regression"
2. `1304.7920` / `1408.2063`: "From Ordinary Differential Equations to Structural Causal Models: the deterministic case"
3. `1910.01288` / `2103.00378`: "Towards Efficient Local Causal Structure Learning"
4. `2301.00314` / `2303.02186`: "Causal Deep Learning"

Text overlap from the existing instrument, not title-matched (candidates only):
5. `1106.0752` / `1106.0753`: "Influence of Photoexcitation Depth on Luminescence Spectra of Bulk GaAs..." (Jaccard 0.602)
6. `2212.02932` / `2307.16577`: "Learning to Bound Counterfactual Inference from Observational, Biased..." (0.577)
7. `2008.05951` / `2108.12208`: "Marginalization of Regression-Adjusted Treatment Effects in Indirect Comparisons" (0.446)
8. `2211.03195` / `2211.16938`: "Evaluating Digital Tools for Sustainable Agriculture using Causal Inference" (0.386)

**Waymo:**
1. `2205.02911` / `local:fa85983cd3c7`: "A Driver-Vehicle Model for ADS Scenario-based Testing" (title-equal; prefixes differ)
2. `2208.12833` / `local:94bdd3d09df1`: "Waymo's Fatigue Risk Management Framework..." (identical prefix; curly-apostrophe copy)
3. `2312.06371` / `local:9e227ca73ba3`: "BAT: Behavior-Aware Human-Like Trajectory Prediction for Autonomous Driving" (title-equal)
4. `2502.08121` / `local:2c0e082a7af4`: "Being good (at driving): ..." (identical prefix)
5. `2507.17943` / `local:ac6107f22da9`: "Automated Brake Onset Detection in Naturalistic Driving Data" (identical prefix)
6. `local:52b5fc5d767d` / `local:ba4d800ccb3f`: both titled "This may be the author's version of a work that was submitted/accepted..." (junk title; prefixes differ; likely NOT duplicates)
7. `1901.07849` / `local:f978147cb261`: AADS paper (`1901.07849`) and an entry titled "Science Journals — AAAS" with identical prefix. The second is a publisher-title drop-in of the same paper (exact prefix match).
8. `1911.01207` / `local:0ab5bb1007c7`: "Autonomous Vehicles Meet the Physical World: RSS, Variability, Uncertainty..." (identical prefix)

**Standards:**
1. `local:216b19db6b0e` / `local:5eadc6bef925`: "ISO IEC IEEE 15026-2 2022 ... Assurance case" (VDE preview / ANSI preview). Confirmed duplicate content; see A5.

### A5. Standards: the four suspected pairs

| Pair | Verdict | Overlap (5-word shingle Jaccard; containment) | Fuller member (chunks / chars) |
|---|---|---|---|
| `216b19db6b0e` (VDE preview) vs `5eadc6bef925` (ANSI preview), ISO IEC IEEE 15026-2 2022 | **CONFIRMED duplicate content.** Same standard, two preview publishers. Exact-prefix check missed it because the header differs. | 0.802; 0.869 / 0.912 | Tie. VDE 11 chunks / 9,137 chars; ANSI 10 chunks / 9,169 chars. Keep one. |
| `fff17ed80281` AVSC00005 (2020-12) vs `b6c10359d954` AVSC-I-01-2024 | **REFUTED as duplicate.** Different revisions; the 2024 title says it supersedes AVSC00005. Overlap is substantial but partial. | 0.370; 0.571 / 0.513 | AVSC-I-01-2024: 110 chunks / 67,834 chars. AVSC00005: 79 / 60,879. |
| `c0d3ca177aaf` ISO PAS 21448-2019 vs `d4ceb75c64ab` ISO 21448-2022 | **REFUTED as duplicate.** Different documents (a PAS and a full standard). Text overlap only. | 0.061; 0.234 / 0.077 | ISO 21448-2022: 562 chunks / 446,882 chars. PAS: 197 / 136,278. |
| `fe96edbde0ee` ISO 31000-2009 vs `7bfd4a363756` ISO 31000-2018 | **REFUTED as duplicate.** Different editions. Text overlap only. | 0.059; 0.090 / 0.147 | ISO 31000-2009: 136 chunks / 70,888 chars. 2018: 79 / 40,256 (2018 looks shorter, so check extraction completeness). |

Other standards: the existing instrument also flagged ISO 26262-5 / -6 pairs (Jaccard 0.49-0.53).
They are different parts of one series sharing boilerplate, not duplicates.

Standards: no title-equal and no exact-prefix groups exist. The only real duplicate is the 15026-2 preview pair.

## Part B: reference lists indexed as content

Script: `reference_census.py`. Run:

```
conda run -n agent-rag-research python reference_census.py --db /home/omar/ai-projects/research-system-rag-data/papers.db --name main > ref_census_main.txt
conda run -n agent-rag-research python reference_census.py --db /home/omar/ai-projects/research-system-rag/waymo/data/papers.db --name waymo > ref_census_waymo.txt
conda run -n agent-rag-research python reference_census.py --db /home/omar/ai-projects/research-system-rag-standards/data/papers.db --name standards > ref_census_standards.txt
```

Definitions:
- **SECTION (verified):** last `section_path` element (split on ` > `), numbering removed, lowercased,
  trailing `:`/`.` removed, equal to one of: references, bibliography, works cited, literature cited,
  reference list. A known miss: `Bibli<sub>ograp</sub>h<sub>y</sub>` with inline HTML is not matched.
- **Stub:** stripped chunk text of 80 characters or fewer (usually just the heading).
- **Real bibliography:** section-matched and not a stub.
- **HEURISTIC:** a chunk with at least 5 citation lines and at least 0.5 year tokens per non-empty
  line. A citation line starts with `[n]`, `n. `, a bullet, or `Surname, X.`, and contains a
  19xx/20xx year.
- **UNION:** section OR heuristic.

| Metric | main | waymo | standards |
|---|---|---|---|
| Section chunks (share of all chunks) | 12,069 (3.02%) | 1,645 (3.44%) | 181 (0.51%) |
| Section chars (share of all chars) | 9,517,224 (0.88%) | 880,128 (0.88%) | 85,457 (0.30%) |
| Heading-only stubs (chunks / chars) | 3,158 / 209,776 | 329 / 22,384 | 63 / 2,811 |
| Real bibliography text (chunks / chars) | 8,911 / 9,307,448 | 1,316 / 857,744 | 118 / 82,646 |
| Documents with real bibliography text | 8,453 of 12,390 | 1,286 of 1,861 | 38 of 119 |
| Heuristic chunks (share) / chars (share) | 640 (0.16%) / 2,828,209 (0.26%) | 35 (0.07%) / 119,221 (0.12%) | 9 (0.03%) / 9,702 (0.03%) |
| Heuristic-only (not section-matched) | 180 chunks / 735,659 chars | 15 / 56,375 | 7 / 7,307 |
| Union chunks (share) / chars (share) | 12,249 (3.06%) / 10,252,883 (0.95%) | 1,660 (3.47%) / 936,503 (0.94%) | 188 (0.53%) / 92,764 (0.33%) |
| Documents with any reference chunk | 11,552 | 1,611 | 76 |

**Reference-content share:** about 0.9-1.0% of characters in each corpus are reference-section or
reference-like text (main 0.95%, waymo 0.94%, standards 0.33%). Chunk shares are 3.1%, 3.5%, and 0.5%.
These are section-verified plus heuristic. The real-bibliography share is about 0.86% in main
(9.3M chars) and 0.86% in waymo (0.86M chars).

**Top 15 by reference characters (union):** raw output is in `ref_census_*.txt`. Main's top entry
(`1208.4360`, 472k chars in one chunk) is a data table under a REFERENCES label, which is the
label-versus-content issue noted above. The waymo and standards top lists are in the same files.

**Examples for a human to check** (chunk ids, copied from the raw output):

Real bibliography (section-matched):
- main: `2403.14573:c16`, `2403.16283:c32`, `2403.16584:c14`, `2403.18039:c26`, `2403.18039:c47`
- waymo: `2606.12500:c27`, `2405.01011:c12`, `2510.12963:c26`, `2303.07891:c25`, `2607.16156:c17`
- standards: `local:0e6dbb524dfe:c188`, `local:1a5e084cb8bb:c688`, `local:1a5e084cb8bb:c689`, `local:1a5e084cb8bb:c690`, `local:1d27d7fac441:c39`

Heading-only stubs:
- main: `2403.09580:c15`, `2403.09606:c22`, `2403.10184:c16`, `2403.10618:c23`, `2403.14696:c19`
- waymo: `2403.14648:c16`, `2508.00384:c20`, `2603.03574:c11`, `1912.03618:c13`, `2206.03418:c24`

Heuristic-only (not section-matched; several are FALSE POSITIVES, see the verified-vs-heuristic note):
- main: `2405.03579:c11`, `2405.07910:c73`, `2406.19958:c44`, `2409.14593:c21`, `2504.12345:c10`
- waymo: `1909.06041:c3`, `2201.07881:c15`, `2205.08942:c13`, `2303.15231:c40`, `2509.23922:c20`
- The main example `2405.03579:c11` is a bulleted list of thesis chapter citations, a plausible reference-like block. `2406.19958:c44` and `2409.14593:c21` look like related-work prose. Treat the heuristic as a candidate generator only.

## Files

- `dup_census.py`, `reference_census.py`: read-only scripts
- `find_dups_main.txt`, `find_dups_standards.txt`: existing instrument raw output
- `main_dup_census.txt`, `waymo_dup_census.txt`, `std_census.txt` (with `--table` rows), `std_pairs.txt`: census raw output
- `ref_census_main.txt`, `ref_census_waymo.txt`, `ref_census_standards.txt`: reference census raw output
