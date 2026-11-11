#!/usr/bin/env bash
# Main-corpus (collection `papers`) baseline, per docs/eval-reports/2026-11-10-main-corpus-benchmark-protocol.md
# and (set `focus`) 2026-11-10-topic-focus-benchmark-protocol.md. Needs the GPU -- see 2026-11-10-GPU-DAY-RUNBOOK.md.
#   conda activate agent-rag-research && ./run_baseline_main.sh [SET ...]
# SET in: papers books legacy focus   (default: papers books legacy; `focus` stops until focus_gt.json is frozen)
# Read-only against the corpus AND every fixture: fixtures are hashed and (new sets) verified with
# gt_tools.py verify WITHOUT --write, never rewritten. Writes only $HERE/runs/<stamp>/.
# One arm only here (shipped config, rerank_depth 32, dense weight 0.5); the depth/weight grid is a later,
# separately pre-registered step (runbook step 3).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"   # this script lives 4 levels below the repo root
DATA=/home/omar/ai-projects/research-system-rag-data
COLL=papers
DB="$DATA/papers.db"
BLOBS="$DATA/blobs"
D=docs/eval-reports/data
HASHES="$REPO/$D/2026-11-10-FIXTURE-HASHES.json"
LABELS_REL=$D/2026-11-10-topic-labels/topic_labels.tsv
TOOLS="$REPO/scripts/eval_protocol_tools.py"
OUT="$HERE/runs/$(date +%Y%m%dT%H%M%S)"
export PYTHONPATH="$REPO"
SETS=("$@"); [ ${#SETS[@]} -gt 0 ] || SETS=(papers books legacy)

die() { echo "STOP: $*" >&2; exit 1; }
has() { local s; for s in "${SETS[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }
for s in "${SETS[@]}"; do case "$s" in papers|books|legacy|focus) ;; *) die "unknown set '$s'";; esac; done

# fixtures (repo-relative) needed by the chosen sets
NEED=()
has papers && NEED+=("$D/2026-11-10-papers-passage-gt/papers_passage_gt.json" "$LABELS_REL")
has books  && NEED+=("$D/2026-11-10-causal-books-gt/causal_books_gt.json")
has focus  && NEED+=("$D/2026-11-10-focus-gt/focus_gt.json" "$LABELS_REL")
has legacy && NEED+=(fixtures/eval/eval_ground_truth.json fixtures/eval/eval_questions_blind.json
                     fixtures/eval/eval_book_questions.json fixtures/eval/eval_known_absent.json
                     fixtures/eval/eval_equation_slice.json)

# 0. Fixture integrity, before any service is touched.
(cd "$REPO" && python "$TOOLS" check-hash "$HASHES" "${NEED[@]}") || die "fixture hash check failed (fixtures are never edited to fit)"
# 1. Verify only (read-only) the new GT sets against today's DB.
has papers && { (cd "$REPO/$D/2026-11-10-papers-passage-gt" && python gt_tools.py verify papers_passage_gt.json) || die "papers GT verification failed"; }
has books  && { (cd "$REPO/$D/2026-11-10-causal-books-gt" && python gt_tools.py verify causal_books_gt.json) || die "books GT verification failed"; }
# 2. Services ready; never auto-start from a measurement script.
(cd "$DATA" && python -m app.doctor --no-auto-start) || die "services not ready (app.doctor non-zero); start them with the runbook's doctor step; GPU busy? see GPU-DAY-RUNBOOK"
# 3. Wrong-corpus guard.
python "$TOOLS" check-points --collection "$COLL" --db "$DB" || die "collection/db mismatch -- refusing to measure"

mkdir -p "$OUT"
cp "$DATA/config.yaml" "$OUT/config-shipped.yaml"
{ echo "git_rev $(git -C "$REPO" rev-parse HEAD)"; echo "started $(date -Is)"; echo "collection $COLL"; echo "db $DB";
  echo "sets ${SETS[*]}"; (cd "$REPO" && sha256sum "${NEED[@]}" "$D/2026-11-10-FIXTURE-HASHES.json"); } > "$OUT/MANIFEST.txt"

# run <tag> <gt-file>: collection, db and blobs named explicitly (omitting --collection queries `papers` by default,
# which is only right by luck on this script and wrong anywhere else).
run() {
  (cd "$REPO" && python -m app.retrieval_eval --ground-truth "$2" --config "$OUT/config-shipped.yaml" \
      --collection "$COLL" --db-path "$DB" --blob-dir "$BLOBS" --k 10 --sparse-mode fused \
      --report-path "$OUT/$1.json") 2>&1 | tee "$OUT/$1.log"
}
strata() {  # strata <tag> <gt-file> [extra eval_strata_report args]; member-passage metric of record
  local tag="$1" gt="$2"; shift 2
  (cd "$REPO" && python scripts/eval_strata_report.py --ground-truth "$gt" --db "$DB" --k 10 \
      --json-out "$OUT/strata-$tag.json" "$@" "$OUT/$tag.json") | tee "$OUT/strata-$tag.txt"
}
# new passage set: authored + title-ablated control (i); strata; per-label breakdown never blended
passage_set() {  # passage_set <name> <gt-file> [split-field]
  local name="$1" gt="$2" field="${3:-}"
  python "$TOOLS" ablate "$gt" "$OUT/$name.title-ablated.json" | tee -a "$OUT/MANIFEST.txt"
  python "$TOOLS" wilson "$gt" | tee "$OUT/$name.strata-n-and-halfwidth.txt"
  run "$name" "$gt";                       strata "$name" "$gt" --topic-labels "$REPO/$LABELS_REL"
  run "$name.ablated" "$OUT/$name.title-ablated.json"; strata "$name.ablated" "$OUT/$name.title-ablated.json" --topic-labels "$REPO/$LABELS_REL"
  if [ -n "$field" ]; then
    python "$TOOLS" split --field "$field" "$gt" "$OUT/$name.json" "$OUT/split-$name"
    for r in "$OUT/split-$name/$name.$field"-*.json; do
      (cd "$REPO" && python scripts/eval_strata_report.py --ground-truth "$gt" --db "$DB" --k 10 "$r") | tee "${r%.json}.txt"
    done
  fi
}

has papers && passage_set papers "$REPO/$D/2026-11-10-papers-passage-gt/papers_passage_gt.json" paper_topic
has books  && passage_set books  "$REPO/$D/2026-11-10-causal-books-gt/causal_books_gt.json"
if has focus; then
  F="$REPO/$D/2026-11-10-focus-gt/focus_gt.json"
  run focus "$F"; strata focus "$F" --topic-labels "$REPO/$LABELS_REL"
fi
if has legacy; then  # stock reports only: these fixtures have no `dimension`/`tests` fields for the strata report
  for f in eval_ground_truth eval_book_questions eval_equation_slice eval_known_absent; do
    run "legacy-$f" "$REPO/fixtures/eval/$f.json"
  done
fi
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT"
