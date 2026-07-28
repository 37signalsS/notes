#!/bin/bash

# Script for manual RAG index reconstruction
# Run this after significant changes to the knowledge base (>20 files)

SCRIPT_DIR=$(dirname "$0")
VENV_PATH="$SCRIPT_DIR/venv/bin/activate"

if [ ! -f "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found in $SCRIPT_DIR/venv"
    exit 1
fi

source "$VENV_PATH"

# Offline mode — модели уже закэшированы локально
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

echo "--- Starting manual RAG synchronization ---"

# Автоматический force-rebuild при первом запуске (пустой манифест)
MANIFEST="$SCRIPT_DIR/manifest.json"
FORCE_FLAG=""
if [ -f "$MANIFEST" ]; then
  HAS_IDS=$(python3 -c "
import json
m=json.load(open('$MANIFEST'))
for e in m:
    for f in m[e].get('files',{}).values():
        if f.get('chunk_ids'): exit(0)
exit(1)
" 2>/dev/null && echo "1" || echo "0")
  if [ "$HAS_IDS" = "0" ]; then
    echo "[!] Манифест пуст — выполняем полную переиндексацию..."
    FORCE_FLAG="--force"
  fi
else
  FORCE_FLAG="--force"
fi

echo "[1/2] Indexing BGE-M3..."
python3 "$SCRIPT_DIR/ingest.py" bge $FORCE_FLAG

echo "[2/2] Indexing MPNet..."
python3 "$SCRIPT_DIR/ingest.py" mpnet $FORCE_FLAG

echo "--- Synchronization complete! Indexes are up to date. ---"
