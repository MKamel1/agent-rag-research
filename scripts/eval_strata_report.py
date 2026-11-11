"""Per-stratum report over app.retrieval_eval JSON reports joined to a ground-truth file.
(Stub commit: full docstring and implementation follow.)

Intended behaviour: read-only post-processing -- per-dimension recall/P@1/anchor+member passage
hit, stub-chunk share, authority/edition outranking, cross-document coverage, absent arm, and
(optional topic labels) off-topic contamination. Never averages across ground-truth files.
"""
