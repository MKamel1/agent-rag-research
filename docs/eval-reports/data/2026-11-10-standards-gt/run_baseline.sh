#!/usr/bin/env bash
# Standards-corpus baseline. Needs the GPU (query embedding + reranker) -- run when it is free.
#   conda activate agent-rag-research && ./run_baseline.sh
# Measures the live index as-is: nothing is re-chunked, re-embedded or written to the corpus.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO=/home/omar/ai-projects/research-system-rag
DATA=/home/omar/ai-projects/research-system-rag-standards/data
OUT="$HERE/runs/$(date +%Y%m%dT%H%M%S)"
mkdir -p "$OUT"
export PYTHONPATH="$REPO"

cd "$HERE" && python merge_gt.py > "$OUT/merge.log"   # re-verify the fixture against today's DB
cd "$DATA" && python -m app.doctor                    # cwd is the data dir; exits non-zero if not ready

run() {  # run <rerank_depth> <sparse_mode>
  local cfg="$OUT/config-depth$1.yaml"
  sed "s/^rerank_depth: .*/rerank_depth: $1/" "$DATA/config.yaml" > "$cfg"
  # Collection, db and blobs are named explicitly: omitting --collection silently queries the
  # default corpus (AGENT-OPERATIONS-LESSONS; precision-95 plan, constraint 8).
  (cd "$REPO" && python -m app.retrieval_eval --ground-truth "$HERE/standards_gt.json" \
      --config "$cfg" --collection av_standards --db-path "$DATA/papers.db" \
      --blob-dir "$DATA/blobs" --k 10 --sparse-mode "$2" \
      --report-path "$OUT/depth$1-$2.json") | tee "$OUT/depth$1-$2.log"
}

run 128 fused        # the shipped standards config
run 32  fused        # the value every other corpus uses -- was the 32 -> 128 change a win?
run 64  fused
run 128 dense_only   # is the sparse arm helping or hurting here? (it hurt on Waymo's full set)
run 128 sparse_only

cd "$HERE" && python analyze_run.py "$OUT"/depth*.json | tee "$OUT/analysis.txt"
echo "done -> $OUT"
