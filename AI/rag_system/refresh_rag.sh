#!/bin/bash
set -euo pipefail

# Script for manual RAG index reconstruction
# Run this after significant changes to the knowledge base (>20 files)

SCRIPT_DIR=$(dirname "$0")
VENV_PATH="$SCRIPT_DIR/venv/bin/activate"

if [ ! -f "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found in $SCRIPT_DIR/venv"
    exit 1
fi

source "$VENV_PATH"

# Models are loaded cache-first: cached models load without network, missing ones
# are downloaded (internet required). Do NOT force HF_HUB_OFFLINE here — it makes a
# missing model (e.g. fastembed Qdrant/bm25) unloadable instead of downloading it.

echo "--- Starting manual RAG synchronization ---"

MANIFEST="$SCRIPT_DIR/manifest.json"
FORCE_FLAG=""
if [ "${1:-}" = "--force" ]; then
  FORCE_FLAG="--force"
  shift
fi

if [ -z "$FORCE_FLAG" ]; then
  if [ ! -f "$MANIFEST" ]; then
    FORCE_FLAG="--force"
  else
    HAS_CONTENT=$(python3 -c "
import json, sys
m = json.load(open('$MANIFEST'))
for e in m:
    for f in m[e].get('files', {}).values():
        if f.get('chunk_ids'):
            sys.exit(0)
sys.exit(1)
" 2>/dev/null && echo "1" || echo "0")
    if [ "$HAS_CONTENT" = "0" ]; then
      echo "[!] Manifest is empty — performing full reindex..."
      FORCE_FLAG="--force"
    fi
  fi
fi

echo "[1/2] Indexing BGE-M3..."
python3 "$SCRIPT_DIR/ingest.py" bge --repair $FORCE_FLAG

echo "[2/2] Indexing E5..."
python3 "$SCRIPT_DIR/ingest.py" e5 --repair $FORCE_FLAG

echo "--- Synchronization complete! Indexes are up to date. ---"
