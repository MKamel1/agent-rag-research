#!/usr/bin/env bash
# EV-14 (shrunk): approximate (default graph) vs exact filtered dense search on the LIVE collections `papers` and
# `av_standards`. CPU + vector store only: no embedder, no reranker, no GPU, no clone, no write. Stored vectors are
# the queries. Rules: PREREGISTRATION.md section 4. Plain HTTP via filtered_search_check.py (docs/, outside the CI
# vendor-isolation scope), which can only call GET /collections/<c> and POST points/scroll|points/query.
#   conda activate agent-rag-research && ./run_filtered_search_check.sh [N_PER_FILTER=100]
# Dry run first: ./run_filtered_search_check.sh 10    (8 filters x N queries x 2 searches per collection)
# No fixtures are used, so there is no fixture hash to check. Writes only $HERE/runs/filtered-<stamp>/.
# Estimate (unmeasured): exact search scans the filtered set, tens of seconds to a few minutes per filter.
set -euo pipefail
source "$(dirname "$0")/session2_common.sh"

N="${1:-100}"; [[ "$N" =~ ^[0-9]+$ ]] && [ "$N" -ge 1 ] || die "N must be a positive integer"
OUT="$HERE/runs/filtered-$(date +%Y%m%dT%H%M%S)"
guard_clean_tree
need_python
(cd "$MAIN_DATA" && python -m app.doctor --no-auto-start --cpu-only) || die "vector store not ready (app.doctor --cpu-only)"
for c in papers av_standards; do qexists "$c" || die "collection '$c' not found"; done
mkdir -p "$OUT"
{ echo "git_rev $GIT_COMMIT"; echo "started $(date -Is)"; echo "n_per_filter $N"; echo "seed 20261111"; echo "fixtures none"; } > "$OUT/MANIFEST.txt"
for c in papers av_standards; do
  log "collection $c"
  python "$HERE/filtered_search_check.py" --collection "$c" --n "$N" --url "$QURL" --out-json "$OUT/$c.json" 2>&1 | tee "$OUT/$c.log"
done
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT   (binding verdict = the papers table; av_standards is informational; see PREREGISTRATION.md section 4)"
