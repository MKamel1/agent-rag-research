# Issues proposed for posting (prepared 2026-11-11)

Nothing here has been posted. Each file is the body of one proposed issue; the first two lines are the title and labels. Prepared after the 2026-11-11 measurements (`docs/eval-reports/EXPERIMENT-REGISTER.md`).

| file | proposed title | labels | id |
|---|---|---|---|
| [RIDER-1-foundation-signoff-rider.md](RIDER-1-foundation-signoff-rider.md) | RIDER-1: Raise the single foundation rider PR (promote ground-truth sets, reject dead lever, ruff step) | wave:4-rider, area:ops, area:eval, area:retrieval, needs-signoff, size:M | RIDER-1 |
| [RQ-6-diagnose-weak-sparse-arm.md](RQ-6-diagnose-weak-sparse-arm.md) | RQ-6: Diagnose why the keyword (sparse) arm scores far below plain BM25 on the main collection | wave:1-no-gpu, area:eval, area:retrieval, needs-services, size:M | RQ-6 (new) |
| [EV-23-rerank-depth-other-corpora.md](EV-23-rerank-depth-other-corpora.md) | EV-23: Measure rerank depth 32 versus 128 on the Waymo, Motional and Waabi corpora where a ground-truth set exists | wave:2-gpu-measure, area:eval, needs-gpu, needs-services, size:S | EV-23 (new) |
| [EV-24-rerank-score-calibration-study.md](EV-24-rerank-score-calibration-study.md) | EV-24: Pre-registered calibration study for the reranker-score "not in corpus" signal | wave:2-gpu-measure, area:eval, area:retrieval, needs-gpu, needs-services, size:M | EV-24 (new) |
| [CQ-9-payload-indexes-on-clone.md](CQ-9-payload-indexes-on-clone.md) | CQ-9: Resolve the filtered-search trigger, then add idempotent payload indexes and verify them on a clone | wave:3-gated-change, area:corpus, area:retrieval, needs-services, size:M | CQ-9 |
| [EV-18b-standards-structure-gate-count.md](EV-18b-standards-structure-gate-count.md) | EV-18b: Produce the standards structure-gate count (remainder of EV-18) | wave:1-no-gpu, area:eval, area:corpus, size:S | EV-18b (remainder of EV-18) |

The 20 other formerly-active tickets are done and are not posted.

The rerank-depth question (32 versus 128) is no longer an open decision: the operator chose 128 for the main corpus on 2026-11-11 (`docs/eval-reports/2026-11-11-rerank-depth-result.md` section 8); EV-23 covers the corpora not yet measured.

Posted 2026-11-11 as GitHub issues: RIDER-1 #250, RQ-6 #251, EV-18b #252, CQ-9 #253, EV-24 #254, EV-23 #255.
