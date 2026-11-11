#!/usr/bin/env bash
# EV-21 (with the EV-12 addendum in 2026-11-10-cq3-stub-chunks.md): baseline vs --drop-stub-chunks.
# Rules and fixtures: PREREGISTRATION.md section 2. Needs the GPU. Read-only everywhere (query-time flag).
#   conda activate agent-rag-research && ./run_stub_ab.sh BASELINE_MAIN_RUN_DIR BASELINE_STANDARDS_RUN_DIR [SET ...]
# SET in: standards papers books (default all three). Baseline reports used ONLY to compute the ceiling:
#   standards: <std dir>/depth128-fused.json (shipped config)   papers/books: <main dir>/<set>.json
# Both arms are re-run here back to back (baseline is NOT reused). Writes only $HERE/runs/stub-<stamp>/.
set -euo pipefail
source "$(dirname "$0")/session2_common.sh"

BASE_MAIN="${1:-}"; BASE_STD="${2:-}"
[ -n "$BASE_MAIN" ] && [ -n "$BASE_STD" ] || die "usage: $0 BASELINE_MAIN_RUN_DIR BASELINE_STANDARDS_RUN_DIR [set ...]"; shift 2
SETS=("$@"); [ ${#SETS[@]} -gt 0 ] || SETS=(standards papers books)
for s in "${SETS[@]}"; do case "$s" in standards|papers|books) ;; *) die "unknown set '$s'";; esac; done
OUT="$HERE/runs/stub-$(date +%Y%m%dT%H%M%S)"
base_report() { case "$1" in standards) echo "$BASE_STD/depth128-fused.json";; *) echo "$BASE_MAIN/$1.json";; esac; }
base_dir() { case "$1" in standards) echo "$BASE_STD";; *) echo "$BASE_MAIN";; esac; }

for s in "${SETS[@]}"; do
  need_baseline "$(base_dir "$s")" GIT_COMMIT "$(basename "$(base_report "$s")")"
done
guard_clean_tree
NEED=(); for s in "${SETS[@]}"; do set_vars "$s"; NEED+=("$GT_REL"); done
check_hashes "${NEED[@]}"
need_python
for s in "${SETS[@]}"; do warn_code_drift "$(base_dir "$s")"; done

# 0. Ceiling per set from the baseline rows (CPU only; needs retrieved_chunk_ids). Skip a set below the minimum effect.
mkdir -p "$OUT"
ELIGIBLE=(); MAXR1=0
for s in "${SETS[@]}"; do
  set_vars "$s"
  rc=0; python "$AB" stub-ceiling --report "$(base_report "$s")" --gt "$REPO/$GT_REL" --db "$DB" \
      --min-effect 2 --json-out "$OUT/ceiling-$s.json" | tee "$OUT/ceiling-$s.txt" || rc=$?
  case "$rc" in
    0)  ELIGIBLE+=("$s");;
    10) echo "skipped: ceiling ($s: fewer than 2 baseline misses carry a stub in the top 10; minimum effect unreachable)";;
    *)  die "stub ceiling failed for $s (rc $rc)";;
  esac
  r1="$(python -c "import json;print(json.load(open('$OUT/ceiling-$s.json'))['stub_rank1_answerable'])")"
  [ "$r1" -le "$MAXR1" ] || MAXR1=$r1
done
if [ "$MAXR1" -lt 3 ]; then
  echo "killed: stub-at-rank-1 occurs on fewer than 3 answerable items on every set (max $MAXR1); EV-21 trigger / minimizer s.4. No arm run."
  exit 0
fi
[ ${#ELIGIBLE[@]} -gt 0 ] || { echo "all sets skipped: ceiling; nothing to run (exit 0)"; exit 0; }

for s in "${ELIGIBLE[@]}"; do verify_gt "$s"; done
HAS_STD=0; HAS_MAIN=0
for s in "${ELIGIBLE[@]}"; do [ "$s" = standards ] && HAS_STD=1 || HAS_MAIN=1; done
[ $HAS_MAIN -eq 0 ] || { services_ready "$MAIN_DATA"; check_points papers "$MAIN_DATA/papers.db"; }
[ $HAS_STD -eq 0 ] || { services_ready "$STD_DATA"; check_points av_standards "$STD_DATA/papers.db"; }
manifest_start "stub A/B, sets: ${ELIGIBLE[*]}; baselines $BASE_MAIN $BASE_STD" "${NEED[@]}"

for s in "${ELIGIBLE[@]}"; do
  set_vars "$s"; GT="$REPO/$GT_REL"
  cp "$DATA/config.yaml" "$OUT/config-$s.yaml"        # shipped config, untouched (standards = depth 128)
  log "set $s: baseline then --drop-stub-chunks, back to back"
  run_arm "$s.base" "$GT" "$OUT/config-$s.yaml" "$COLL" "$DB" "$BLOBS" fused
  run_arm "$s.drop" "$GT" "$OUT/config-$s.yaml" "$COLL" "$DB" "$BLOBS" fused --drop-stub-chunks
  strata_of "$s" "$GT" "$s" "$OUT/$s.base.json" "$OUT/$s.drop.json"
  python "$AB" paired --gt "$GT" --db "$DB" --base "$OUT/$s.base.json" --arm "$OUT/$s.drop.json" \
      --label "$s" --tags-from "$OUT/ceiling-$s.json" --json-out "$OUT/pair-$s.json" | tee "$OUT/pair-$s.txt"
  (cd "$REPO" && python scripts/list_stub_chunks.py "$DB" --ab "$OUT/$s.base.json" "$OUT/$s.drop.json") | tee "$OUT/list-stub-ab-$s.txt"
  # validity gate: this step's baseline arm vs the baseline run's same arm, |net| <= 1
  jrc=0; python "$AB" paired --gt "$GT" --db "$DB" --base "$(base_report "$s")" --arm "$OUT/$s.base.json" \
      --label "$s-jitter" --max-abs-net 1 --json-out "$OUT/pair-$s.jitter.json" | tee "$OUT/pair-$s.jitter.txt" || jrc=$?
  [ "$jrc" -eq 0 ] || echo "$s: VALIDITY GATE FAILED (baseline re-run differs by >1): NOT INTERPRETABLE" | tee -a "$OUT/RESULT.txt"
done
PAIRS=(); for s in "${ELIGIBLE[@]}"; do PAIRS+=(--pair "$OUT/pair-$s.json"); done
{ echo "== stub A/B verdict (EV-12 addendum rule; sets run: ${ELIGIBLE[*]}) =="; python "$AB" verdict stub "${PAIRS[@]}"; } | tee -a "$OUT/RESULT.txt"
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
echo "done -> $OUT   (ADOPT only if RESULT.txt says ADOPT and no VALIDITY GATE FAILED line; the default stays off either way)"
