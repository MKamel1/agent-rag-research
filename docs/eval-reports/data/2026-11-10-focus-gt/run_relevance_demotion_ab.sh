#!/usr/bin/env bash
# RQ-3 relevance-demotion A/B on the main corpus (collection `papers`), pre-registered in
# docs/eval-reports/2026-11-11-rq3-relevance-demotion-prereg.md. Needs the GPU (embedder + reranker + Qdrant up).
#   conda activate agent-rag-research && ./run_relevance_demotion_ab.sh
# All arms run back to back at ONE commit (baseline re-run here, not reused): baseline, tail@0.25, tail@0.30,
# penalty@0.30 (p=5). Sets: focus (primary), papers (split by paper_topic), causal books. Read-only against the
# corpus and every fixture; no clone, no collection change. Writes only $HERE/runs-rq3/<stamp>/<arm>/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
DATA=/home/omar/ai-projects/research-system-rag-data
COLL=papers
DB="$DATA/papers.db"
BLOBS="$DATA/blobs"
D=docs/eval-reports/data
HASHES="$REPO/$D/2026-11-10-FIXTURE-HASHES.json"
LABELS_REL=$D/2026-11-10-topic-labels/topic_labels.tsv
FOCUS="$REPO/$D/2026-11-10-focus-gt/focus_gt.json"
PAPERS="$REPO/$D/2026-11-10-papers-passage-gt/papers_passage_gt.json"
BOOKS="$REPO/$D/2026-11-10-causal-books-gt/causal_books_gt.json"
TOOLS="$REPO/scripts/eval_protocol_tools.py"
OUT="$HERE/runs-rq3/$(date +%Y%m%dT%H%M%S)"
export PYTHONPATH="$REPO"
P=5   # penalty-arm rank positions; chosen in the prereg (k/2: keeps a below-tau rank-1..5 result inside the top-10)
# arm name -> extra retrieval_eval flags
ARMS=(baseline "tail-0.25" "tail-0.30" "penalty-0.30-p$P")
flags_for() {
  case "$1" in
    baseline) echo "" ;;
    tail-0.25) echo "--relevance-demotion tail --relevance-tau 0.25" ;;
    tail-0.30) echo "--relevance-demotion tail --relevance-tau 0.30" ;;
    penalty-0.30-p$P) echo "--relevance-demotion penalty --relevance-tau 0.30 --relevance-penalty $P" ;;
  esac
}
die() { echo "STOP: $*" >&2; exit 1; }

# GPU estimate: ~3.6 s/query at rerank depth 32 (measured 2026-11-11), 49 focus + 61 papers + 74 books per arm.
QUERIES=$((49 + 61 + 74))
SECS=$(awk -v q=$QUERIES -v a=${#ARMS[@]} 'BEGIN{printf "%d", q*a*3.6}')
echo "ESTIMATE: $QUERIES queries x ${#ARMS[@]} arms x 3.6 s = ${SECS} s (~$((SECS / 60)) min GPU), plus ~1 min post-processing"

[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] \
  || die "working tree has uncommitted changes to tracked files; commit or stash them so the run names one commit"
GIT_COMMIT="$(git -C "$REPO" rev-parse HEAD)"
NEED=("$D/2026-11-10-focus-gt/focus_gt.json" "$D/2026-11-10-papers-passage-gt/papers_passage_gt.json"
      "$D/2026-11-10-causal-books-gt/causal_books_gt.json" "$LABELS_REL")

# 0. Fixture integrity before any service is touched; read-only GT verification.
(cd "$REPO" && python "$TOOLS" check-hash "$HASHES" "${NEED[@]}") || die "fixture hash check failed (fixtures are never edited to fit)"
(cd "$REPO/$D/2026-11-10-papers-passage-gt" && python gt_tools.py verify papers_passage_gt.json) || die "papers GT verification failed"
(cd "$REPO/$D/2026-11-10-causal-books-gt" && python gt_tools.py verify causal_books_gt.json) || die "books GT verification failed"
# 1. Services ready (never auto-started) and the wrong-corpus guard.
(cd "$DATA" && python -m app.doctor --no-auto-start) || die "services not ready (app.doctor non-zero)"
python "$TOOLS" check-points --collection "$COLL" --db "$DB" || die "collection/db mismatch -- refusing to measure"

mkdir -p "$OUT"
echo "$GIT_COMMIT" > "$OUT/GIT_COMMIT"
cp "$DATA/config.yaml" "$OUT/config-shipped.yaml"
{ echo "git_rev $GIT_COMMIT"; echo "started $(date -Is)"; echo "collection $COLL"; echo "db $DB"; echo "arms ${ARMS[*]}";
  (cd "$REPO" && sha256sum "${NEED[@]}" "$D/2026-11-10-FIXTURE-HASHES.json"); } > "$OUT/MANIFEST.txt"

run() {  # run <arm> <tag> <gt-file>; collection, db and blobs named explicitly
  local arm="$1" tag="$2" gt="$3"
  # shellcheck disable=SC2046  # flags_for is intentionally word-split
  (cd "$REPO" && python -m app.retrieval_eval --ground-truth "$gt" --config "$OUT/config-shipped.yaml" \
      --collection "$COLL" --db-path "$DB" --blob-dir "$BLOBS" --k 10 --sparse-mode fused \
      $(flags_for "$arm") --report-path "$OUT/$arm/$tag.json") 2>&1 | tee "$OUT/$arm/$tag.log"
}
strata() {  # strata <arm> <json-tag> <report> <gt-file> [extra args]
  local arm="$1" tag="$2" rep="$3" gt="$4"; shift 4
  (cd "$REPO" && python scripts/eval_strata_report.py --ground-truth "$gt" --db "$DB" --k 10 \
      --json-out "$OUT/$arm/strata-$tag.json" "$@" "$rep") | tee "$OUT/$arm/strata-$tag.txt"
}

for arm in "${ARMS[@]}"; do
  mkdir -p "$OUT/$arm"
  echo "$arm: $(flags_for "$arm")" >> "$OUT/MANIFEST.txt"
  run "$arm" focus "$FOCUS";   strata "$arm" focus "$OUT/$arm/focus.json" "$FOCUS" --topic-labels "$REPO/$LABELS_REL"
  run "$arm" papers "$PAPERS"; strata "$arm" papers "$OUT/$arm/papers.json" "$PAPERS" --topic-labels "$REPO/$LABELS_REL"
  python "$TOOLS" split --field paper_topic "$PAPERS" "$OUT/$arm/papers.json" "$OUT/$arm/split"
  for v in on off; do
    strata "$arm" "papers-topic-$v" "$OUT/$arm/split/papers.paper_topic-$v.json" "$PAPERS"
  done
  run "$arm" books "$BOOKS";   strata "$arm" books "$OUT/$arm/books.json" "$BOOKS"
done
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
python "$REPO/scripts/relevance_demotion_ab_table.py" "$OUT" | tee "$OUT/COMPARISON.md"
echo "done -> $OUT (COMPARISON.md; apply the prereg rule, do not edit it)"
