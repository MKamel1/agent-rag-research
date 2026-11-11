#!/usr/bin/env bash
# Standards-corpus (av_standards) baseline, per docs/eval-reports/2026-11-10-standards-benchmark-protocol.md.
# Needs the GPU (query embedding + reranker) -- run when it is free (see 2026-11-10-GPU-DAY-RUNBOOK.md).
#   conda activate agent-rag-research && ./run_baseline.sh
# Read-only against the corpus AND the fixture: nothing is re-chunked, re-embedded or written, and
# standards_gt.json is only hashed and verified (gt_tools.py verify WITHOUT --write), never rewritten.
# Writes only $HERE/runs/<stamp>/ (derived title-ablated GT, config copies, reports, strata output).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"   # this script lives 4 levels below the repo root
DATA=/home/omar/ai-projects/research-system-rag-standards/data
COLL=av_standards
DB="$DATA/papers.db"
BLOBS="$DATA/blobs"
HASHES="$REPO/docs/eval-reports/data/2026-11-10-FIXTURE-HASHES.json"
GT_REL=docs/eval-reports/data/2026-11-10-standards-gt/standards_gt.json
GT="$REPO/$GT_REL"
TOOLS="$REPO/scripts/eval_protocol_tools.py"
OUT="$HERE/runs/$(date +%Y%m%dT%H%M%S)"
export PYTHONPATH="$REPO"

die() { echo "STOP: $*" >&2; exit 1; }
# Frozen-baseline guard: measure committed code only, and record which commit. --untracked-files=no
# because $OUT (runs/<stamp>/) lives inside the repo; tracked edits are what could change a number.
[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] \
  || die "working tree has uncommitted changes to tracked files; commit or stash them so the run names one commit"
GIT_COMMIT="$(git -C "$REPO" rev-parse HEAD)"

# 0. Fixture integrity -- before any service is touched. A changed or unfrozen fixture is not measured.
(cd "$REPO" && python "$TOOLS" check-hash "$HASHES" "$GT_REL") || die "fixture hash check failed"
# 1. Verify only (excerpts verbatim in today's DB, absence scans reproduce). Read-only; exits non-zero on failure.
(cd "$HERE" && python gt_tools.py verify standards_gt.json) || die "ground-truth verification failed (fixture NOT rewritten)"
# 2. Services ready (GPU lock/headroom, TEI, vector store). cwd is the data dir: load_config() reads ./config.yaml.
(cd "$DATA" && python -m app.doctor --no-auto-start) || die "services not ready (app.doctor non-zero); start them with the runbook's doctor step; GPU busy? see GPU-DAY-RUNBOOK"
# 3. Wrong-corpus guard: collection point count must be plausible for THIS db.
python "$TOOLS" check-points --collection "$COLL" --db "$DB" || die "collection/db mismatch -- refusing to measure"

mkdir -p "$OUT"
echo "$GIT_COMMIT" > "$OUT/GIT_COMMIT"
cp "$DATA/config.yaml" "$OUT/config-shipped.yaml"
{ echo "git_rev $GIT_COMMIT"; echo "started $(date -Is)"; echo "collection $COLL"; echo "db $DB";
  sha256sum "$GT" "$HASHES"; } > "$OUT/MANIFEST.txt"
python "$TOOLS" ablate "$GT" "$OUT/standards_gt.title-ablated.json" | tee -a "$OUT/MANIFEST.txt"
python "$TOOLS" wilson "$GT" | tee "$OUT/strata-n-and-halfwidth.txt"

# run <tag> <gt-file> <rerank_depth> <sparse_mode>. Collection, db and blobs are named explicitly:
# omitting --collection silently queries the default `papers` corpus.
run() {
  local tag="$1" gt="$2" depth="$3" mode="$4" cfg="$OUT/config-depth$3.yaml"
  sed "s/^rerank_depth: .*/rerank_depth: $depth/" "$DATA/config.yaml" > "$cfg"
  grep -q "^rerank_depth: $depth\$" "$cfg" || die "could not set rerank_depth $depth in config copy"
  (cd "$REPO" && python -m app.retrieval_eval --ground-truth "$gt" --config "$cfg" \
      --collection "$COLL" --db-path "$DB" --blob-dir "$BLOBS" --k 10 --sparse-mode "$mode" \
      --report-path "$OUT/$tag.json") 2>&1 | tee "$OUT/$tag.log"
}

ARMS=("depth128-fused 128 fused" "depth32-fused 32 fused" "depth64-fused 64 fused"
      "depth128-dense_only 128 dense_only" "depth128-sparse_only 128 sparse_only")
for arm in "${ARMS[@]}"; do
  set -- $arm
  run "$1" "$GT" "$2" "$3"                                     # authored questions
  run "$1.ablated" "$OUT/standards_gt.title-ablated.json" "$2" "$3"   # control (i)
done
# Run-to-run jitter envelope: the shipped arm again, same config. The depth decision is only valid if
# this repeat and depth128-fused differ on <= 1 question's member-passage hit@10 (protocol section 6).
run "depth128-fused-repeat" "$GT" 128 fused

# Strata report of record (member-passage metric). One GT file per invocation; never blended.
for suffix in "" ".ablated"; do
  gt="$GT"; [ -n "$suffix" ] && gt="$OUT/standards_gt.title-ablated.json"
  reports=(); for arm in "${ARMS[@]}"; do set -- $arm; reports+=("$OUT/$1$suffix.json"); done
  [ -z "$suffix" ] && reports+=("$OUT/depth128-fused-repeat.json")
  (cd "$REPO" && python scripts/eval_strata_report.py --ground-truth "$gt" --db "$DB" --k 10 \
      --json-out "$OUT/strata$suffix.json" "${reports[@]}") | tee "$OUT/strata$suffix.txt"
done
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT"
