#!/usr/bin/env bash
# T-G10: append to .git/hooks/post-commit (after the graphify update block).
# Runs the drift/health gate and leaves .needs_update.json when unhealthy.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$(head -1 "$(command -v graphify)" | tr -d '#!')"
"$PYTHON" -m scripts.graphify_validate --graph-dir "$REPO/graphify-out" --repo "$REPO" || true
