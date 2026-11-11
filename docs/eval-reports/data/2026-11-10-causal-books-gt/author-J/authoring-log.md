# Author J log — Elements of Causal Inference (local:f6c64e1e8c7d)

Result: 15 items, `verify --write` = 15 items, 0 failures. Killed: 0 (none attempted and dropped).
Dimensions: 9 book-passage, 4 equation-context, 1 table-requirement, 1 partial-absent. Hard: 7 (ids 003-006, 011-013).
Chapters spread: Preface; ch1; ch2 (x2); ch5; ch6.9; ch7; ch8 (x2); ch9; ch4; ch10; Appendix A.2.
Existing eval_book_questions.json facts avoided (Principles 1.1/2.1/2.2/6.53, Props 6.3/7.10/B.2, Thms 4.3/6.45/6.52/9.9/10.3/B.5, Defs 4.4/9.1, CAM, Y-structure, eye disease, butter/cheese, front-door channel, topological order, Lemma C.1, Prop 7.1 proof).
Absence item (015): regression discontinuity; paper-scoped scans (RD, "discontinuity", DiD|synthetic control) all 0 hits. nearest_distractor is the book itself (no better candidate checked).
gold_chapter_title: omitted where top-level is junk (see below); kept "Notation and Terminology" (ch1-2 really), "Time Series", "Preface" literally as they appear.

## Text quality
- Chunks: 160, 543,719 chars, median 3,023, max 8,777. >5,000 chars: 46; >10,000: 0. <300 chars: 6 (e.g. c7 90 chars, c27 111, c70 99, c142 37, c79 156, c58 165 = heading-only stubs).
- Chapter titles are mostly junk. Top-level section_path is a real chapter title for only a few chapters: Preface, Cause-Effect Models (ch3, 6 chunks), Hidden Variables (ch9 start, 2 chunks), Time Series (13). Everything else inherits a stray heading: "Notation and Terminology" (17 chunks, covers ch1 AND ch2), "b) Consider the SCM" (42 chunks, spans ch4, 5, 6), "{probabilistically/interventionally/counterfactually} equivalent" (14, ch6-7), "Example 7.9 (Conditional independence and partial correlation)" (15, ch7-8), "Example 9.2 Consider the following SCM" (16, ch9), plus "Theorem 6.45 ... Thefollowing" (2), "Definition 6.47..." (1), "Theorem 7.7..." (4), "Lemma 7.8..." (1). Chapters 4, 5, 8, 10-with-appendix numbering are never top-level. Appendix B and its heading are absent from sections (Thm B.5 text sits under A.3).
- Appendix headings misaligned: Appendix B content (DAG adjacency matrices, Table B.1) filed under "A.3 Capacity of Function Classes"; Proofs appendix is "C.x" with top-level "Proofs"/"C.n Proof of..." each as own top level.
- Equations: LaTeX is kept as `$...$`/`$$...$$` (102 chunks with display math, ~5,900 dollar signs) — readable but noisy; some damaged: "Thefollowing", "re - quire", "Scholkopf ¨" (umlaut displaced, e.g. "Scholkopf [2012]¨"), "Buhlmann [2014]¨", "Trgyve", "Augu" (truncated preface date), "$N X \perp \perp N _ { Y }$" (c17, lost subscript), "$ i f S _ { X X }$" (c133), "$\mathbf{A x}$" mis-OCR for A_X (c36). Equation (4.13) etc. survive; matrix sentences mixed into proofs.
- Page furniture: every chunk begins with a "Elements of Causal Inference" header line (160/160, from the chunk wrapper). c0 is title/copyright page (MIT Press); c1 "Contents" (3,147 chars) is chunked as content; c159 "Index" (6,701 chars) and c158 "Bibliography" are chunked as content; Index page numbers refer to the print edition.
- Table B.1 (number of DAGs) is cut: c141 ends at header "d Number of DAGs with d nodes" with no rows in that chunk.
- Chunk boundary oddities: c141 starts mid-proof (item (iii) of a Prop B.x list) under A.3; c143+ proofs are 0.4-2k chars each.
