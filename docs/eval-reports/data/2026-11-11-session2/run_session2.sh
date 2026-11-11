#!/usr/bin/env bash
# Session 2 driver: (1) depth compare -> (2) stub A/B -> (3) ligature A/B, cheapest first, one GPU job at a time.
# Each step logs start/stop; a step that SKIPS by its own rule (exit 0, prints "skipped"/"killed") does not stop the
# next one; a step that FAILS (non-zero) stops the session (runbook stop conditions: do not start another GPU job
# to compensate). The ligature CLONE must already exist: run prepare_ligature_clone.sh first (CPU only).
#   conda activate agent-rag-research && ./run_session2.sh BASELINE_MAIN_RUN_DIR BASELINE_STANDARDS_RUN_DIR [CLONE_NAME]
# CLONE_NAME default papers__ligrepair_20261111. Details: SESSION2-README.md.
set -euo pipefail
source "$(dirname "$0")/session2_common.sh"

BASE_MAIN="${1:-}"; BASE_STD="${2:-}"; CLONE="${3:-papers__ligrepair_20261111}"
[ -n "$BASE_MAIN" ] && [ -n "$BASE_STD" ] || die "usage: $0 BASELINE_MAIN_RUN_DIR BASELINE_STANDARDS_RUN_DIR [CLONE_NAME]"
need_baseline "$BASE_MAIN" GIT_COMMIT papers.json books.json strata-papers.json strata-books.json legacy-eval_ground_truth.json
need_baseline "$BASE_STD" GIT_COMMIT depth128-fused.json
guard_clean_tree

# GPU-time estimate. ASSUMPTIONS (not measurements): 3.6 s/query at depth 32 (measured tonight, main corpus);
# 10 s/query at depth 128 (about 1 s fixed + 2.6 s per 32 candidates reranked). Override with S32=.. S128=..
S32=${S32:-3.6}; S128=${S128:-10}
python - "$S32" "$S128" <<'PY'
import sys
s32, s128 = float(sys.argv[1]), float(sys.argv[2])
m = lambda q, s: q * s / 60
depth_lo = m(61 + 74, s32 + s128)                       # originals only (ablated arms spent only if 128 leads)
depth_hi = depth_lo + m(61 + 69, s32 + s128)            # worst case: every set triggers the ablated pair
stub_lo = m(61 * 2 + 74 * 2, s32) + m(128 * 2, s128)    # standards runs at its shipped depth 128
ligab = m(345 * 2 * 2, s32)                             # 345 q x {live, clone} x {sparse_only, fused}
print(f"GPU-time estimate (S32={s32}, S128={s128} s/query):")
print(f"  1 depth compare : {depth_lo:5.0f} - {depth_hi:5.0f} min (0 if both sets skip on headroom)")
print(f"  2 stub A/B      : up to {stub_lo:5.0f} min (sets skipped by ceiling/kill cost 0; 526 queries)")
print(f"  3 ligature A/B  : {ligab:5.0f} min (1,380 queries; +{m(345*2, s32):.0f} min with --dense-control)")
print(f"  total (worst)   : {depth_hi + stub_lo + ligab:5.0f} min = {(depth_hi + stub_lo + ligab)/60:.1f} h")
PY

step() {  # step <name> <cmd...>
  local name="$1"; shift
  log "START $name"; local rc=0; "$@" || rc=$?
  log "STOP  $name (exit $rc)"
  [ "$rc" -eq 0 ] || die "step '$name' failed (exit $rc): stopping the session; fix the cause, do not adjust the script"
}
step "1 depth-compare" "$HERE/run_depth_compare.sh" "$BASE_MAIN"
step "2 stub-ab"       "$HERE/run_stub_ab.sh" "$BASE_MAIN" "$BASE_STD"
if qexists "$CLONE"; then
  step "3 ligature-ab" "$HERE/run_ligature_ab.sh" "$BASE_MAIN" "$CLONE"
else
  log "skipped: step 3 ligature-ab (clone $CLONE not found; run prepare_ligature_clone.sh)"
fi
log "session 2 finished; read each runs/*/RESULT.txt against PREREGISTRATION.md"
