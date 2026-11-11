#!/usr/bin/env bash
# EV-20 (shrunk): rerank depth 32 vs 128 at dense weight 0.5 on main-corpus paper passages and causal books ONLY.
# Rules and fixtures: PREREGISTRATION.md section 1 (pre-registered; do not edit after a number is seen).
# Needs the GPU. Read-only against the corpus, the live collection and every fixture.
#   conda activate agent-rag-research && ./run_depth_compare.sh BASELINE_MAIN_RUN_DIR [SET ...]
# BASELINE_MAIN_RUN_DIR = the main baseline's runs/<stamp> (needs GIT_COMMIT, <set>.json, strata-<set>.json).
# SET in: papers books (default both). Standards depth is decided by the standards baseline; Waymo excluded.
# Per set: skipped ("skipped: ceiling", exit 0 for that set) if the baseline's member-passage hit@10 leaves
# fewer than 6 items of headroom. Writes only $HERE/runs/depth-<stamp>/.
set -euo pipefail
source "$(dirname "$0")/session2_common.sh"

BASE="${1:-}"; [ -n "$BASE" ] || die "usage: $0 BASELINE_MAIN_RUN_DIR [papers|books ...]"; shift
SETS=("$@"); [ ${#SETS[@]} -gt 0 ] || SETS=(papers books)
for s in "${SETS[@]}"; do case "$s" in papers|books) ;; *) die "set '$s' not allowed (papers books only)";; esac; done
OUT="$HERE/runs/depth-$(date +%Y%m%dT%H%M%S)"
S32=${S32:-3.6}; S128=${S128:-10}   # s/query assumptions, printed only

for s in "${SETS[@]}"; do need_baseline "$BASE" GIT_COMMIT "$s.json" "strata-$s.json"; done
guard_clean_tree
NEED=(); for s in "${SETS[@]}"; do set_vars "$s"; NEED+=("$GT_REL"); done
check_hashes "${NEED[@]}"
need_python
warn_code_drift "$BASE"

# 0. Precondition from the BASELINE strata output (CPU only): headroom >= 6 else skip the set.
ELIGIBLE=()
for s in "${SETS[@]}"; do
  rc=0; python "$AB" headroom --strata "$BASE/strata-$s.json" --report-suffix "/$s.json" --min 6 || rc=$?
  case "$rc" in
    0)  ELIGIBLE+=("$s");;
    10) echo "skipped: ceiling ($s: baseline member-passage hit@10 leaves < 6 items of headroom)";;
    *)  die "headroom check failed for $s (rc $rc): baseline run unusable";;
  esac
done
[ ${#ELIGIBLE[@]} -gt 0 ] || { echo "all sets skipped: ceiling; nothing to run (exit 0)"; exit 0; }

for s in "${ELIGIBLE[@]}"; do verify_gt "$s"; done
services_ready "$MAIN_DATA"
check_points papers "$MAIN_DATA/papers.db"
manifest_start "depth-compare 32 vs 128, weight 0.5, sets: ${ELIGIBLE[*]}; baseline $BASE" "${NEED[@]}"
echo "baseline_run $BASE" >> "$OUT/MANIFEST.txt"
cfg_with_depth "$MAIN_DATA/config.yaml" "$OUT/config-depth32.yaml" 32
cfg_with_depth "$MAIN_DATA/config.yaml" "$OUT/config-depth128.yaml" 128
grep -q '^hybrid_dense_weight: 0.5$' "$OUT/config-depth32.yaml" || die "shipped dense weight is not 0.5; not the registered arm"

for s in "${ELIGIBLE[@]}"; do
  set_vars "$s"; GT="$REPO/$GT_REL"
  log "set $s: depth32 then depth128 (original fixture)"
  run_arm "$s.depth32"  "$GT" "$OUT/config-depth32.yaml"  "$COLL" "$DB" "$BLOBS" fused
  run_arm "$s.depth128" "$GT" "$OUT/config-depth128.yaml" "$COLL" "$DB" "$BLOBS" fused
  strata_of "$s" "$GT" "$s" "$OUT/$s.depth32.json" "$OUT/$s.depth128.json"
  # validity gate: this step's depth-32 arm vs the baseline run's same arm, |net| <= 1
  jrc=0; python "$AB" paired --gt "$GT" --db "$DB" --base "$BASE/$s.json" --arm "$OUT/$s.depth32.json" \
      --label "$s-jitter" --max-abs-net 1 --json-out "$OUT/pair-$s.jitter.json" | tee "$OUT/pair-$s.jitter.txt" || jrc=$?
  python "$AB" paired --gt "$GT" --db "$DB" --base "$OUT/$s.depth32.json" --arm "$OUT/$s.depth128.json" \
      --label "$s" --json-out "$OUT/pair-$s.json" | tee "$OUT/pair-$s.txt"
  prc=0; python "$AB" verdict depth --pair "$OUT/pair-$s.json" > "$OUT/verdict-$s.preliminary.json" || prc=$?
  if grep -q '"rule_ge2_prefers": "128' "$OUT/verdict-$s.preliminary.json"; then
    log "set $s: 128 leads by the >=2 rule -> spending the title-ablated arms (G-1 same-sign clause)"
    python "$TOOLS" ablate "$GT" "$OUT/$s.title-ablated.json" | tee -a "$OUT/MANIFEST.txt"
    run_arm "$s.ablated.depth32"  "$OUT/$s.title-ablated.json" "$OUT/config-depth32.yaml"  "$COLL" "$DB" "$BLOBS" fused
    run_arm "$s.ablated.depth128" "$OUT/$s.title-ablated.json" "$OUT/config-depth128.yaml" "$COLL" "$DB" "$BLOBS" fused
    python "$AB" paired --gt "$OUT/$s.title-ablated.json" --db "$DB" --base "$OUT/$s.ablated.depth32.json" \
        --arm "$OUT/$s.ablated.depth128.json" --label "$s-ablated" --json-out "$OUT/pair-$s.ablated.json" \
        | tee "$OUT/pair-$s.ablated.txt"
    python "$AB" verdict depth --pair "$OUT/pair-$s.json" --ablated-pair "$OUT/pair-$s.ablated.json" > "$OUT/verdict-$s.json"
  else
    python "$AB" verdict depth --pair "$OUT/pair-$s.json" > "$OUT/verdict-$s.json"
  fi
  if [ "$jrc" -ne 0 ]; then
    echo "$s: VALIDITY GATE FAILED (depth-32 re-run differs from baseline by >1): NOT INTERPRETABLE" | tee -a "$OUT/RESULT.txt"
  else
    { echo "== $s (validity gate passed) =="; cat "$OUT/verdict-$s.json"; } | tee -a "$OUT/RESULT.txt"
  fi
done
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT   (read RESULT.txt against PREREGISTRATION.md section 1; no default is changed by this script)"
