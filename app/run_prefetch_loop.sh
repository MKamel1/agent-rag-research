#!/usr/bin/env bash
# app/run_prefetch_loop.sh — crash-restart wrapper for `python -m app.prefetch_pdfs`.
#
# app/prefetch_pdfs.py already loops internally until PREFETCH_TARGET is reached (harvest, drain
# the backlog, sleep, re-harvest) and exits 0 only once that target is hit. This wrapper exists
# purely for the OTHER failure mode: an unexpected exception (bug, infra blip) killing the whole
# process. Not a supervisor daemon — just a bounded restart loop that resumes from the same
# durable ingest_state/pdf_cache checkpoint the script itself already uses, and stops for good
# once the script exits 0.
#
# Usage: RAG_DB_PATH=... RAG_PDF_CACHE_DIR=... PREFETCH_TARGET=30000 ./app/run_prefetch_loop.sh

set -uo pipefail

while true; do
    python -m app.prefetch_pdfs
    status=$?
    if [ "$status" -eq 0 ]; then
        echo "run_prefetch_loop: app.prefetch_pdfs exited 0 (target reached) -- stopping." >&2
        break
    fi
    echo "run_prefetch_loop: app.prefetch_pdfs exited $status -- restarting in 10s." >&2
    sleep 10
done
