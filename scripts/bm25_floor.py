"""Plain BM25 floor ("EV-5b") over the stored chunk text of a corpus database. STUB (EV-15 commit 1).

Frozen definition: Okapi BM25, k1 = 1.2, b = 0.75, tokens = lowercase [a-z0-9]+ minus
`eval_protocol_tools.STOP`, over ALL chunk texts as stored; query = `question_text` as written.
The database is opened read-only (`file:...?mode=ro`); no services, no network, standard library
only. Not the system's retrieval output: a lexical floor beside every headline number.
"""

raise NotImplementedError("EV-15 stub")
