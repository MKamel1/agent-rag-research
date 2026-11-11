#!/usr/bin/env bash
# EV-19: re-run retrieval with --record-rerank-scores per set at the SHIPPED config, then the census.
# Pre-registration: docs/eval-reports/2026-11-11-ev19-rerank-score-census-prereg.md (rule fixed before any run).
# Needs the GPU. Read-only against corpora and fixtures; no clone, no Qdrant write, so no disk check is needed.
#   conda activate agent-rag-research && ./run_census.sh [SET ...]
# SET in: focus papers books legacy standards  (default: all, cheapest first). The census step uses whatever
# sets ran in THIS invocation (the verdict needs standards, focus and legacy to be present).
# Writes only $HERE/runs/<stamp>/.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
MAIN=/home/omar/ai-projects/research-system-rag-data
STD=/home/omar/ai-projects/research-system-rag-standards/data
D=docs/eval-reports/data
HASHES="$REPO/$D/2026-11-10-FIXTURE-HASHES.json"
TOOLS="$REPO/scripts/eval_protocol_tools.py"
OUT="$HERE/runs/$(date +%Y%m%dT%H%M%S)"
export PYTHONPATH="$REPO"
SETS=("$@"); [ ${#SETS[@]} -gt 0 ] || SETS=(focus papers books legacy standards)
die() { echo "STOP: $*" >&2; exit 1; }
has() { local s; for s in "${SETS[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }
for s in "${SETS[@]}"; do case "$s" in focus|papers|books|legacy|standards) ;; *) die "unknown set '$s'";; esac; done

# Estimated GPU time: ~3.6 s/query at rerank depth 32 (measured 2026-11-11); standards runs depth 128,
# 4x the rerank batches, assumed ~12 s/query (UNMEASURED estimate). Queries: focus 49, papers 61, books 74,
# legacy 24+210+40=274, standards 128.
est=0; say() { echo "  $1: $2 queries x ~$3 s = ~$(( $2 * $3 / 60 )) min"; est=$(( est + $2 * $3 )); }
echo "Estimated GPU time (cheapest first):"
has focus     && say focus 49 4;     has papers && say papers 61 4;  has books && say books 74 4
has legacy    && say legacy 274 4;   has standards && say standards 128 12
echo "  total: ~$(( est / 60 )) min"

[ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] || die "tracked files have uncommitted changes; commit first so the run names one commit"
GIT_COMMIT="$(git -C "$REPO" rev-parse HEAD)"

NEED=()
has focus     && NEED+=("$D/2026-11-10-focus-gt/focus_gt.json")
has papers    && NEED+=("$D/2026-11-10-papers-passage-gt/papers_passage_gt.json")
has books     && NEED+=("$D/2026-11-10-causal-books-gt/causal_books_gt.json")
has legacy    && NEED+=(fixtures/eval/eval_known_absent.json fixtures/eval/eval_ground_truth.json
                        fixtures/eval/eval_questions_blind.json fixtures/eval/eval_equation_slice.json)
has standards && NEED+=("$D/2026-11-10-standards-gt/standards_gt.json")
# 0. Fixture integrity before any service is touched.
(cd "$REPO" && python "$TOOLS" check-hash "$HASHES" "${NEED[@]}") || die "fixture hash check failed (fixtures are never edited to fit)"
# 1. Services ready (never auto-started from a measurement script); one doctor per corpus data dir.
(cd "$MAIN" && python -m app.doctor --no-auto-start) || die "services not ready (app.doctor, main)"
# 2. Wrong-corpus guards.
has standards && { python "$TOOLS" check-points --collection av_standards --db "$STD/papers.db" || die "standards collection/db mismatch"; }
python "$TOOLS" check-points --collection papers --db "$MAIN/papers.db" || die "papers collection/db mismatch"

mkdir -p "$OUT"
echo "$GIT_COMMIT" > "$OUT/GIT_COMMIT"
cp "$MAIN/config.yaml" "$OUT/config-main-shipped.yaml"; cp "$STD/config.yaml" "$OUT/config-standards-shipped.yaml"
{ echo "git_rev $GIT_COMMIT"; echo "started $(date -Is)"; echo "sets ${SETS[*]}"; echo "estimated_gpu_min $(( est / 60 ))"
  (cd "$REPO" && sha256sum "${NEED[@]}" "$D/2026-11-10-FIXTURE-HASHES.json"); } > "$OUT/MANIFEST.txt"

# run <tag> <gt-file> <main|standards>: collection, db and blobs named explicitly; shipped config
# (main: rerank_depth 32; standards: 128 -- read from the copied config, not overridden).
run() {
  local tag="$1" gt="$2" corpus="$3" coll data cfg
  if [ "$corpus" = standards ]; then coll=av_standards; data="$STD"; cfg="$OUT/config-standards-shipped.yaml"
  else coll=papers; data="$MAIN"; cfg="$OUT/config-main-shipped.yaml"; fi
  (cd "$REPO" && python -m app.retrieval_eval --ground-truth "$gt" --config "$cfg" \
      --collection "$coll" --db-path "$data/papers.db" --blob-dir "$data/blobs" --k 10 --sparse-mode fused \
      --record-rerank-scores --report-path "$OUT/$tag.json") 2>&1 | tee "$OUT/$tag.log"
}
G="$REPO/$D"; F="$REPO/fixtures/eval"
has focus     && run focus     "$G/2026-11-10-focus-gt/focus_gt.json" main
has papers    && run papers    "$G/2026-11-10-papers-passage-gt/papers_passage_gt.json" main
has books     && run books     "$G/2026-11-10-causal-books-gt/causal_books_gt.json" main
if has legacy; then
  run legacy-known_absent "$F/eval_known_absent.json" main
  run legacy-ground_truth "$F/eval_ground_truth.json" main
  run legacy-equation_slice "$F/eval_equation_slice.json" main
fi
has standards && run standards "$G/2026-11-10-standards-gt/standards_gt.json" standards

# Census: per set, never pooled in the headline (a pooled row is printed, labelled secondary).
ARGS=()
has focus     && ARGS+=(--set focus "$OUT/focus.json" "$G/2026-11-10-focus-gt/focus_gt.json")
has books     && ARGS+=(--set books "$OUT/books.json" "$G/2026-11-10-causal-books-gt/causal_books_gt.json")
if has legacy; then
  ARGS+=(--set legacy "$OUT/legacy-known_absent.json" "$F/eval_known_absent.json"
         --set legacy "$OUT/legacy-ground_truth.json" "$F/eval_ground_truth.json"
         --set legacy "$OUT/legacy-equation_slice.json" "$F/eval_equation_slice.json")
  # secondary robustness read: same absent arm vs the later-authored paper-passage answerable arm
  has papers && ARGS+=(--set legacy-vs-papers-SECONDARY "$OUT/legacy-known_absent.json" "$F/eval_known_absent.json"
                       --set legacy-vs-papers-SECONDARY "$OUT/papers.json" "$G/2026-11-10-papers-passage-gt/papers_passage_gt.json"
                       --secondary legacy-vs-papers-SECONDARY)
fi
has standards && ARGS+=(--set standards "$OUT/standards.json" "$G/2026-11-10-standards-gt/standards_gt.json")
if [ ${#ARGS[@]} -gt 0 ]; then
  (cd "$REPO" && python -m scripts.rerank_score_census "${ARGS[@]}" --json-out "$OUT/census.json") 2>&1 | tee "$OUT/census.txt"
fi
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT"
