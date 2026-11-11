"""`python -m scripts.rerank_score_census` -- EV-13/EV-19: does the cross-encoder score separate
answerable from absent queries? (STUB: behaviour specified in
docs/eval-reports/2026-11-11-ev19-rerank-score-census-prereg.md; implemented in the next commit.)

Input: per set, one or more `app.retrieval_eval --record-rerank-scores` reports plus their ground-truth
files. Output per set (never pooled in the headline): distributions, seeded-bootstrap AUROC CIs, best
threshold with Wilson-interval error rates for the frozen features, the fusion `top_score` comparison
and the question-length control. Decides nothing; ships no threshold.
"""
