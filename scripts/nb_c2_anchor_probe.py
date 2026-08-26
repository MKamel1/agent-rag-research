"""`python -m scripts.nb_c2_anchor_probe` -- NB-C2 pre-retrieval lexical anchor-coverage probe.

Ticket NB-C2 (A-series C2, per `docs/eval-reports/2026-08-25-nb-a1-abstention-signal-design.md`
§C2). Measures ONE feature per question -- the fraction of the question's high-IDF lexical
anchor tokens that have >=1 corpus hit under sparse-only presence queries against the
`waymo_av_safety` collection -- and evaluates A-1's PRE-COMMITTED falsification criterion on
both fixtures. Measurement only: decides nothing at serve time, builds no mechanism.

Subcommands:
  capture  -- extract anchors per question, probe each against Qdrant (read-only), write JSON
  analyze  -- AUROC / best-cut FP-FN / Spearman length-leakage guard -> results.json + verdict

Reuse mandate: anchor probing reuses `rag.vector_index._sparse_vector` tokenization VERBATIM
(lowercase whitespace tokens, sha1-hashed indices, raw TF; Qdrant's native IDF modifier does
the weighting server-side). This script never imports `qdrant_client` (CONVENTIONS.md §1 --
only rag/vector_index.py may): presence checks go over Qdrant's own REST API via stdlib
urllib. Read-only: only `POST /collections/{c}/points/query`, limit=1, no filters.

STUB COMMIT -- implementation lands in commit 2.
"""

from __future__ import annotations

raise NotImplementedError("NB-C2 probe implementation lands in commit 2")
