#!/bin/bash
# Простой скрипт для удобного опроса RAG-системы (гибридный поиск + реранкер)
SCRIPT_DIR=$(dirname "$0")

if [ ! -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    echo "Error: Virtual environment not found at $SCRIPT_DIR/venv"
    exit 1
fi

QUERY=$1
if [ -z "$QUERY" ]; then
    echo "Использование: $0 'ваш вопрос' [--top-k N] [--exclude PATTERN]"
    exit 1
fi

"$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/unified_search.py" "$QUERY" "${@:2}"