# Author I log (2026-11-10)
Books: Trustworthy Online Controlled Experiments (local:14b7e283bdcd), Causal Inference in Python (local:f0929288d4f3).
Per book: 11 book-passage, 2 equation-context, 1 table-requirement, 1 partial-absent (15 each; Q-CB-I-001..014 and 029 = TW; 015..028 and 030 = CI). Hard: TW 6, CI 5. Items built by author-I/build.py.
Killed: 0 at verify. Dropped before writing (not authored): CI c71 sample-size formula (adjacent to existing geo-experiment / sample-size-source items), TW c153 equation text (answer lives in the LaTeX, used the prose sentence instead), many CI chunks with LaTeX-only answers.
Existing-set overlap: avoided all facts in eval_book_questions.json for both books (it holds ~19 TW / ~21 CI items, more than 8 each).

## Text-quality observations
Both books
- section_path is a single leaf heading, not a chapter path; "chapter" is not recoverable, so gold_chapter_title = the leaf heading. Chapters appear only as running text.
- Every chunk is prefixed with a running header line (book title) before the section title.
TW
- c0/c1 cover/blurbs, c2 "Contents", c3 "How to Read" chunked as content; the back-of-book index is glued onto the end of c214 (11,068 chars, also the largest chunk) under "Method #4: Holdback and Reverse Experiment".
- Chapter-opening chunks have junk titles: c135 "14" and c204 "23" (46 chars), c196 "Examples" (52 chars), c32/c38 heading-only stubs (180/244 chars). Chapter title text is merged into the previous chunk body (e.g. c156 ends with the next chapter's epigraph and "Why you care").
- Equations are OCR LaTeX with spacing damage ("\Pelegant", "P o w e r", "$\mathbf { Y } ^ { * }$" for a quote), page-break artifacts ("Volumne 80 (2)").
- Bullet items sometimes promoted to section titles (c43-c47 "• Residual or carryover effects").
CI
- c3 "Table of Contents" is an empty 46-char stub; c4 (9.7k chars, titled "Part I. Fundamentals") is the TOC chunked as content; glossary/index chunks c333-c354 titled by single letters A..X, c341 has an empty title.
- "PRACTICAL EXAMPLE" (c58, c68, c101, c129, c143, c169, c192, c207, c228, c256, c284, c325) are 46-char heading stubs; 11 "Key Ideas" and 19 "See Also" titles repeat across chapters.
- c326 mixes the end of the IV chapter with the "Next Steps" closing text (chapter boundary not respected). c285 mixes the end of one chapter with the start of the next.
- Code, tables and plots are mangled: regression tables survive as markdown, but data-frame prints are scrambled (c262), code cells lose indentation/line breaks (c254), figures are absent so "the following plot" references dangle. Section titles carry ligature loss ("Efect", "Diference").
