#!/bin/bash
# Простой скрипт для удобного опроса RAG-системы
QUERY=$1
if [ -z "$QUERY" ]; then
    echo "Использование: ./ask.sh 'ваш вопрос'"
    exit 1
fi

./venv/bin/python3 query.py "$QUERY"
