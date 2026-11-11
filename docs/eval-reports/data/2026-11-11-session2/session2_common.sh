# Sourced by the session-2 run scripts (not executable on its own). Shared safety checks and helpers,
# modelled on 2026-11-10-papers-passage-gt/run_baseline_main.sh. Nothing here writes a fixture, touches a
# live collection or starts a service.
HERE="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"   # scripts live 4 levels below the repo root
D=docs/eval-reports/data
HASHES_REL=$D/2026-11-10-FIXTURE-HASHES.json
TOOLS="$REPO/scripts/eval_protocol_tools.py"
AB="$REPO/scripts/session2_ab_tools.py"
MAIN_DATA=/home/omar/ai-projects/research-system-rag-data
STD_DATA=/home/omar/ai-projects/research-system-rag-standards/data
QURL=${QURL:-http://localhost:6333}
QSTORE=/home/omar/ai-projects/research-system-rag/.phase0-data/qdrant
export PYTHONPATH="$REPO"

die() { echo "STOP: $*" >&2; exit 1; }
log() { echo "[$(date -Is)] $*"; }

# Frozen-run guard: committed code only, and record which commit. --untracked-files=no because run
# directories live inside the repo; tracked edits are what could change a number.
guard_clean_tree() {
  [ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] \
    || die "working tree has uncommitted changes to tracked files; commit or stash them so the run names one commit"
  GIT_COMMIT="$(git -C "$REPO" rev-parse HEAD)"
}

need_python() {
  python -c "import app.retrieval_eval, rag.vector_index" 2>/dev/null \
    || die "python cannot import the repo (activate the agent-rag-research conda env first)"
}

# set_vars <papers|books|standards> -> GT_REL GT_DIR GT_FILE COLL DATA DB BLOBS
set_vars() {
  case "$1" in
    papers)    GT_DIR=2026-11-10-papers-passage-gt; GT_FILE=papers_passage_gt.json; COLL=papers; DATA=$MAIN_DATA;;
    books)     GT_DIR=2026-11-10-causal-books-gt;   GT_FILE=causal_books_gt.json;   COLL=papers; DATA=$MAIN_DATA;;
    standards) GT_DIR=2026-11-10-standards-gt;      GT_FILE=standards_gt.json;      COLL=av_standards; DATA=$STD_DATA;;
    *) die "unknown set '$1'";;
  esac
  GT_REL=$D/$GT_DIR/$GT_FILE; DB=$DATA/papers.db; BLOBS=$DATA/blobs
}

check_hashes() {  # repo-relative fixture paths
  (cd "$REPO" && python "$TOOLS" check-hash "$REPO/$HASHES_REL" "$@") \
    || die "fixture hash check failed (fixtures are never edited to fit)"
}
verify_gt() {  # read-only verification of a passage GT against today's DB (never --write)
  set_vars "$1"
  (cd "$REPO/$D/$GT_DIR" && python gt_tools.py verify "$GT_FILE") || die "$1 GT verification failed"
}
services_ready() { (cd "$1" && python -m app.doctor --no-auto-start) \
  || die "services not ready (app.doctor non-zero); GPU still busy with the queue? see GPU-DAY-RUNBOOK"; }
vector_store_ready() { curl -fsS "$QURL/collections" >/dev/null || die "vector store not reachable at $QURL"; }
check_points() { python "$TOOLS" check-points --collection "$1" --db "$2" || die "collection/db mismatch -- refusing to measure"; }

need_file() { [ -f "$1" ] || die "$2 (missing: $1)"; }
need_baseline() {  # need_baseline <dir> <file>...  fail closed on a fake/missing baseline run directory
  local dir="$1"; shift
  [ -d "$dir" ] || die "baseline run directory not found: $dir"
  local f; for f in "$@"; do need_file "$dir/$f" "baseline run directory $dir is incomplete"; done
}
warn_code_drift() {  # baseline run dir -> compare its commit with HEAD on the retrieval path
  local base; base="$(cat "$1/GIT_COMMIT" 2>/dev/null || true)"
  [ -n "$base" ] || die "no GIT_COMMIT in baseline run directory $1"
  if ! git -C "$REPO" diff --quiet "$base" HEAD -- rag app contracts; then
    echo "WARNING: rag/ app/ contracts/ differ between baseline commit $base and HEAD; arms re-run here are" >&2
    echo "         comparable with each other, NOT necessarily with the baseline run (jitter gate will tell)." >&2
  fi
}
disk_free_gb() { df --output=avail -BG "$1" | tail -1 | tr -dc '0-9'; }
disk_check() {  # disk_check <path> <min GB>
  local free; free="$(disk_free_gb "$1")"
  echo "free disk at $1: ${free} GB (abort under $2 GB)"
  [ "$free" -ge "$2" ] || die "only ${free} GB free (< $2 GB)"
}
qcount() {  # exact point count of a collection (read-only POST /points/count)
  curl -fsS -X POST -H 'Content-Type: application/json' -d '{"exact":true}' \
    "$QURL/collections/$1/points/count" | python -c 'import sys,json;print(json.load(sys.stdin)["result"]["count"])'
}
qexists() { [ "$(curl -s -o /dev/null -w '%{http_code}' "$QURL/collections/$1")" = 200 ]; }

cfg_with_depth() {  # cfg_with_depth <src config> <out> <depth>
  sed "s/^rerank_depth: .*/rerank_depth: $3/" "$1" > "$2"
  grep -q "^rerank_depth: $3\$" "$2" || die "could not set rerank_depth $3 in config copy"
}

# run_arm <tag> <gt> <cfg> <coll> <db> <blobs> <mode> [extra retrieval_eval args]   ($OUT must be set)
run_arm() {
  local tag="$1" gt="$2" cfg="$3" coll="$4" db="$5" blobs="$6" mode="$7"; shift 7
  log "arm $tag: collection=$coll mode=$mode $*"
  (cd "$REPO" && python -m app.retrieval_eval --ground-truth "$gt" --config "$cfg" \
      --collection "$coll" --db-path "$db" --blob-dir "$blobs" --k 10 --sparse-mode "$mode" "$@" \
      --report-path "$OUT/$tag.json") 2>&1 | tee "$OUT/$tag.log"
  python - "$OUT/$tag.json" <<'PY' || die "arm $tag invalid (errors or run_valid false): do not read its numbers"
import json, sys
r = json.load(open(sys.argv[1]))
bad = [q["question_id"] for q in r["questions"] if q.get("error")]
sys.exit(1 if bad or r.get("run_valid") is False else 0)
PY
}

strata_of() {  # strata_of <set> <gt> <out-tag> <report>...   member-passage metric of record
  local set="$1" gt="$2" tag="$3"; shift 3; set_vars "$set"
  (cd "$REPO" && python scripts/eval_strata_report.py --ground-truth "$gt" --db "$DB" --k 10 \
      --json-out "$OUT/strata-$tag.json" "$@") | tee "$OUT/strata-$tag.txt"
}

manifest_start() {  # manifest_start <label> <fixture rel>...
  mkdir -p "$OUT"; echo "$GIT_COMMIT" > "$OUT/GIT_COMMIT"
  { echo "git_rev $GIT_COMMIT"; echo "started $(date -Is)"; echo "script $(basename "${BASH_SOURCE[1]}")"; echo "label $1"; shift
    (cd "$REPO" && sha256sum "$@" "$HASHES_REL"); } > "$OUT/MANIFEST.txt"
}
