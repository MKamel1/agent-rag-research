# Author H log (2026-11-10)

Books: A = local:dfe850b3281a (Molak, Causal Inference and Discovery in Python), B = local:54d6ca71dda9 (Causal Inference and ML in Economics, Social, and Health Sciences).
30 items (15/book): 11 book-passage, 2 equation-context, 1 table-requirement, 1 partial-absent each. Verify: 30 items, 0 failures.
Killed: 0 items at verify time. Before drafting, dropped candidates that duplicated fixtures/eval/eval_book_questions.json (causal Markov names, minimality name, Willig meta-SCM, NOTEARS joint optimization, Gini, SUTVA, DML1/DML2, etc.) and candidates whose excerpts were mostly LaTeX (B honest-tree pruning step, ASCM weights).
Absent items: A = Granger causality (0 hits; also 0 for vector autoregression); B = causal mediation (0 hits for mediation/mediator and "indirect efect"; "mediat" matches only immediate/intermediate). Verifier requires absent items to carry no source_paper_id, so the book is named in the question text and scans are paper-scoped.

## Text-quality observations
Both books
- Ligature loss throughout: "efect", "difer", "eficient", "coeficient", "dificult". Regexes must allow it (e.g. `ef+ect`), and excerpts must keep the typos. A scan for "differences-in-differences" silently misses A's "diference-in-diferences".
- Chapter titles are not recoverable: section_path top level is the nearest heading (not the chapter), so gold_chapter_title was omitted for all items except two B items under "Introduction".

Book A (Molak, 535 chunks)
- Front matter, full table of contents (chunked as 3 pieces plus many one-line "section" stubs such as "1", "2", "Part 2: Causal Inference", page numbers like "173") and the index (single letters "C", "F", "I"...) are chunked as content; the TOC also pollutes scans (e.g. "propensity score" hits in contents).
- Heading stubs: many chunks have body of only tens of chars ("Let's practice!", "Ready?", "Let's start!", "Forks" 181 chars). Section titles are often chatty sub-headings or bogus (e.g. "DML with DoWhy and EconML > 0.00810075098627887", "P(book A|book B)", "Answer").
- Equations are LaTeX OCR with stray spacing ("$U = ~ 0$"); code listings are missing (text says "Let's put all of this in the code" but the code is absent; only outputs sometimes survive). Footer "Causal Inference and Discovery in Python" repeated as first line of every chunk body.

Book B (671 chunks)
- Section paths are corrupted by code output/comments being promoted to headings: "## Expected MSPE: 60.9356 > 5.3 ...", "## Best lambda for Ridge regression: 0.2529632 > 12.4 ...", "## [1] 120", "1. https://freakonometrics.hypotheses.org/52776 > 14.1 ...", "Family Income Distribution > 20.2.3 ...". Top-level "chapter" is junk ("Notes", "Note", "Error", "Reminder:", "Overfitting" spanning chapters 6-8).
- Oversized chunks: c21 "Notes" 9,980 chars (footnotes plus the whole Alex garlic story), c32 10,011, c36 9,758, c408 8,665 chars.
- Tables mangled: Anscombe table in c26 is fine, but a correlation-matrix R printout (~line 1474 of the dump) is split into malformed pipe rows. Index (single-letter chunks D, H, N...) and contents are chunked as content. R code and "## [1]" output lines are inline prose; step/algorithm blocks use "\-" escapes and heavy LaTeX.
