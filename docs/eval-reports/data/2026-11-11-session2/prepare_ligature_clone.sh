#!/usr/bin/env bash
# CQ-7: build a ligature-repaired CLONE of the live `papers` collection. CPU + vector store only (no GPU, no
# embedder). The ONLY thing modified is the new clone collection; `papers` is read-only here (scroll + count).
# Rules: PREREGISTRATION.md section 3 (the clone is deleted after the A/B; cleanup command printed at the end,
# never executed here).
#   conda activate agent-rag-research && ./prepare_ligature_clone.sh [CLONE_NAME]
# CLONE_NAME default papers__ligrepair_20261111 (must match papers__ligrepair_<8 digits>).
# Steps: guards -> disk (abort < 20 GB free; expected clone ~6-8 GB for papers) and RAM -> live staleness sample
# and count -> clone_points_into -> count check -> resparse dry run -> resparse --apply (clone-guarded) ->
# --verify-sample on the clone (expect 0 stale) and again on live (unchanged) -> live count unchanged.
# Estimates (unmeasured): clone tens of minutes, resparse 7-20 minutes; the run records the real times.
set -euo pipefail
source "$(dirname "$0")/session2_common.sh"

SRC=papers
CLONE="${1:-papers__ligrepair_20261111}"
[[ "$CLONE" =~ ^papers__ligrepair_[0-9]{8}$ ]] || die "clone name must match papers__ligrepair_<8 digits> (got '$CLONE')"
[ "$QURL" = "http://localhost:6333" ] || die "this script drives the adapter on localhost:6333 only (QURL=$QURL)"
OUT="$HERE/runs/ligclone-$(date +%Y%m%dT%H%M%S)"

guard_clean_tree
need_python
(cd "$MAIN_DATA" && python -m app.doctor --no-auto-start --cpu-only) || die "vector store not ready (app.doctor --cpu-only)"
qexists "$SRC" || die "source collection '$SRC' not found"
! qexists "$CLONE" || die "collection '$CLONE' already exists; delete it first (cleanup command below) or choose another name"
check_points "$SRC" "$MAIN_DATA/papers.db"

# Disk and memory: clone_points_into reads 100,000-point pages (several GB of Python floats in memory).
disk_check "$QSTORE" 20
echo "expected clone size on disk: about 6-8 GB (source 5.8 GB per the runbook)"
mem_gb=$(( $(awk '/MemAvailable/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
echo "available RAM: ${mem_gb} GB (abort under 16 GB: one scroll page is several GB)"
[ "$mem_gb" -ge 16 ] || die "only ${mem_gb} GB RAM available"

mkdir -p "$OUT"; echo "$GIT_COMMIT" > "$OUT/GIT_COMMIT"
{ echo "git_rev $GIT_COMMIT"; echo "started $(date -Is)"; echo "source $SRC"; echo "clone $CLONE"; df -h "$QSTORE" | tail -1; } > "$OUT/MANIFEST.txt"
cd "$REPO"
stale_of() { sed -nE "s/.*: ([0-9,]+)\/([0-9,]+) \(.*/\1 of \2/p"; }

LIVE_N="$(qcount "$SRC")"; echo "live $SRC points before: $LIVE_N" | tee -a "$OUT/MANIFEST.txt"
python -m app.resparse --collection "$SRC" --verify-sample 2000 | tee "$OUT/live-stale-before.txt"   # read-only

log "clone $SRC -> $CLONE (no re-embedding)"
t0=$(date +%s)
python - "$SRC" "$CLONE" <<'PY' 2>&1 | tee "$OUT/clone.log"
import sys
from rag.vector_index import VectorIndex

src, dst = sys.argv[1:3]
n = VectorIndex("localhost", 6333, src, 2560, create_if_missing=False).clone_points_into(dst)
print(f"cloned {n} points {src} -> {dst}")
PY
echo "clone_seconds $(( $(date +%s) - t0 ))" | tee -a "$OUT/MANIFEST.txt"
CLONE_N="$(qcount "$CLONE")"; echo "clone points: $CLONE_N" | tee -a "$OUT/MANIFEST.txt"
[ "$CLONE_N" = "$LIVE_N" ] || die "point count mismatch: clone $CLONE_N != live $LIVE_N (delete the clone; do not resparse it)"

python -m app.resparse --collection "$CLONE" --verify-sample 2000 | tee "$OUT/clone-stale-before.txt"
python -m app.resparse --collection "$CLONE" | tee "$OUT/resparse-dry-run.txt"
log "resparse --apply on the CLONE only"
t0=$(date +%s)
python -m app.resparse --collection "$CLONE" --target-is-clone --clone-of "$SRC" --apply | tee "$OUT/resparse-apply.txt"
echo "resparse_apply_seconds $(( $(date +%s) - t0 ))" | tee -a "$OUT/MANIFEST.txt"
python -m app.resparse --collection "$CLONE" --verify-sample 2000 | tee "$OUT/clone-stale-after.txt"
python -m app.resparse --collection "$SRC" --verify-sample 2000 | tee "$OUT/live-stale-after.txt"
[ "$(stale_of < "$OUT/clone-stale-after.txt" | cut -d' ' -f1)" = 0 ] || die "clone still has stale sparse vectors (see clone-stale-after.txt)"
[ "$(qcount "$SRC")" = "$LIVE_N" ] || die "LIVE POINT COUNT CHANGED during the run -- investigate immediately"
[ "$(qcount "$CLONE")" = "$LIVE_N" ] || die "clone point count changed after resparse"
echo "live stale before/after: $(stale_of < "$OUT/live-stale-before.txt") / $(stale_of < "$OUT/live-stale-after.txt") (must be statistically equal; live never written)"
echo "finished $(date -Is)" >> "$OUT/MANIFEST.txt"
cat <<EOM
done -> $OUT
Handover for run_ligature_ab.sh: collection $CLONE, code revision $GIT_COMMIT.
CLEANUP (NOT executed by this script; run it after the A/B, once the report is written):
  curl -fsS -X DELETE $QURL/collections/$CLONE
  curl -s -o /dev/null -w '%{http_code}\n' $QURL/collections/$CLONE    # expect 404
EOM
