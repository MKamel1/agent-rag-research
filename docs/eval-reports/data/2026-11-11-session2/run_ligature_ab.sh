#!/usr/bin/env bash
# EV-22: ligature-repair A/B. Arm A = live `papers`, arm B = the repaired clone from prepare_ligature_clone.sh;
# modes sparse_only and fused (optional --dense-control adds dense_only on both as an index-build-noise control);
# sets papers + books (stratified by damaged vs clean GOLD chunk) + legacy 210 (regression anchor, unstratified).
# Rules: PREREGISTRATION.md section 3 (CQ-2 runbook adoption criterion, restated there verbatim). Needs the GPU.
# Read-only against everything; both collections are only searched. Writes only $HERE/runs/ligab-<stamp>/.
#   conda activate agent-rag-research && ./run_ligature_ab.sh BASELINE_MAIN_RUN_DIR CLONE_NAME [--dense-control]
#
# WHAT EACH ARM MEASURES (read rag/vector_index.py::_sparse_vector: query AND index both go through
# repair_ligatures, no flag): A = repaired QUERY vs UNREPAIRED index; B = repaired query vs repaired index.
# A-vs-B therefore isolates the index-side repair (+ its IDF effect). No pre-CQ-1 rows exist (CQ-1 is in the
# baseline commit); the query-repair-check below proves repair changes none of these question strings, so A
# behaves as pre-CQ-1 on these fixtures. If that check fails the script stops (EV-22: arm A would need the
# pre-CQ-1 checkout).
set -euo pipefail
source "$(dirname "$0")/session2_common.sh"

BASE="${1:-}"; CLONE="${2:-}"; DENSE_CTRL=0
[ -n "$BASE" ] && [ -n "$CLONE" ] || die "usage: $0 BASELINE_MAIN_RUN_DIR CLONE_NAME [--dense-control]"
[ "${3:-}" != "--dense-control" ] || DENSE_CTRL=1
[[ "$CLONE" =~ ^papers__ligrepair_[0-9]{8}$ ]] || die "clone name must match papers__ligrepair_<8 digits>"
LIVE=papers
OUT="$HERE/runs/ligab-$(date +%Y%m%dT%H%M%S)"
LEG_REL=fixtures/eval/eval_ground_truth.json
need_baseline "$BASE" GIT_COMMIT papers.json books.json legacy-eval_ground_truth.json
guard_clean_tree
set_vars papers; P_GT=$GT_REL; set_vars books; B_GT=$GT_REL
check_hashes "$P_GT" "$B_GT" "$LEG_REL" fixtures/eval/eval_questions_blind.json
need_python
warn_code_drift "$BASE"

# 0. CPU-only preconditions
(cd "$REPO" && python "$AB" query-repair-check --gt "$P_GT" --gt "$B_GT" --gt "$LEG_REL") \
  || die "query-side repair changes some question strings: arm A is not pre-CQ-1-equivalent; see EV-22 (do not run)"
vector_store_ready
qexists "$CLONE" || die "clone '$CLONE' not found (run prepare_ligature_clone.sh first)"
LIVE_N="$(qcount "$LIVE")"; CLONE_N="$(qcount "$CLONE")"
[ "$LIVE_N" = "$CLONE_N" ] || die "point counts differ: live $LIVE_N vs clone $CLONE_N"
STALE="$(python -m app.resparse --collection "$CLONE" --verify-sample 2000)"; echo "$STALE"
echo "$STALE" | grep -qE ': 0/[0-9,]+ ' || die "clone still holds stale sparse vectors: not a repaired clone"
verify_gt papers; verify_gt books
services_ready "$MAIN_DATA"
check_points "$LIVE" "$MAIN_DATA/papers.db"; check_points "$CLONE" "$MAIN_DATA/papers.db"

mkdir -p "$OUT"; manifest_start "ligature A/B live=$LIVE clone=$CLONE baseline=$BASE dense_control=$DENSE_CTRL" "$P_GT" "$B_GT" "$LEG_REL"
echo "live_points $LIVE_N clone_points $CLONE_N baseline_run $BASE" >> "$OUT/MANIFEST.txt"
cp "$MAIN_DATA/config.yaml" "$OUT/config-shipped.yaml"; CFG="$OUT/config-shipped.yaml"
for s in papers books; do
  set_vars "$s"
  python "$AB" ligature-flag --gt "$REPO/$GT_REL" --db "$DB" --out "$OUT/flags-$s.json" | tee "$OUT/flags-$s.txt"
done
MODES=(sparse_only fused); [ $DENSE_CTRL -eq 0 ] || MODES+=(dense_only)
GTS=("papers:$REPO/$P_GT" "books:$REPO/$B_GT" "legacy:$REPO/$LEG_REL")

for entry in "${GTS[@]}"; do
  s="${entry%%:*}"; GT="${entry#*:}"
  for mode in "${MODES[@]}"; do
    run_arm "$s.$mode.live"  "$GT" "$CFG" "$LIVE"  "$MAIN_DATA/papers.db" "$MAIN_DATA/blobs" "$mode"
    run_arm "$s.$mode.clone" "$GT" "$CFG" "$CLONE" "$MAIN_DATA/papers.db" "$MAIN_DATA/blobs" "$mode"
    extra=(); [ "$s" = legacy ] || extra=(--db "$MAIN_DATA/papers.db")
    [ "$s" = legacy ] || extra+=(--flags "$OUT/flags-$s.json")
    python "$AB" paired --gt "$GT" "${extra[@]}" --base "$OUT/$s.$mode.live.json" --arm "$OUT/$s.$mode.clone.json" \
        --label "$s" --tag "mode=$mode" --json-out "$OUT/pair-$s.$mode.json" | tee "$OUT/pair-$s.$mode.txt"
    if [ "$s" != legacy ]; then
      strata_of "$s" "$GT" "$s.$mode" "$OUT/$s.$mode.live.json" "$OUT/$s.$mode.clone.json"
    fi
  done
  # validity gate: live fused arm vs the baseline run's same arm (legacy: stock paper metric only)
  jdb=(); [ "$s" = legacy ] || jdb=(--db "$MAIN_DATA/papers.db")
  bname="$s.json"; [ "$s" != legacy ] || bname="legacy-eval_ground_truth.json"
  jrc=0; python "$AB" paired --gt "$GT" "${jdb[@]}" --base "$BASE/$bname" --arm "$OUT/$s.fused.live.json" \
      --label "$s-jitter" --max-abs-net 1 --json-out "$OUT/pair-$s.jitter.json" | tee "$OUT/pair-$s.jitter.txt" || jrc=$?
  [ "$jrc" -eq 0 ] || echo "$s: VALIDITY GATE FAILED (live fused re-run differs from baseline by >1): NOT INTERPRETABLE" | tee -a "$OUT/RESULT.txt"
done
PAIRS=(); for f in "$OUT"/pair-*.sparse_only.json "$OUT"/pair-*.fused.json; do PAIRS+=(--pair "$f"); done
{ echo "== ligature verdict (CQ-2 rule; standards fixture NOT run: best possible outcome is ADOPT-PENDING-STANDARDS) =="
  python "$AB" verdict ligature "${PAIRS[@]}"; } | tee -a "$OUT/RESULT.txt"
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT   (no default changed). Afterwards delete the clone: curl -fsS -X DELETE $QURL/collections/$CLONE"
