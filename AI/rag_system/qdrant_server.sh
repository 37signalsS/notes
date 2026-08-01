#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="rag-qdrant"
VOLUME_DIR="$SCRIPT_DIR/qdrant_storage"
PORT="${QDRANT_PORT:-6333}"
GRPC_PORT="${QDRANT_GRPC_PORT:-6334}"

start() {
    if ! command -v docker &>/dev/null; then
        echo "Error: Docker is not installed. Install Docker Desktop or set mode: local in config.yaml"
        exit 1
    fi
    if ! docker info &>/dev/null; then
        echo "Error: Docker daemon is not running. Start Docker Desktop and try again"
        exit 1
    fi
    if docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        echo "Qdrant container '$CONTAINER_NAME' already running"
        return 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        echo "Starting existing stopped container '$CONTAINER_NAME'..."
        docker start "$CONTAINER_NAME" > /dev/null
    else
        mkdir -p "$VOLUME_DIR"
        echo "Starting Qdrant server on port $PORT..."
        docker run -d \
            --name "$CONTAINER_NAME" \
            -p "$PORT":6333 \
            -p "$GRPC_PORT":6334 \
            -v "$VOLUME_DIR":/qdrant/storage \
            qdrant/qdrant:latest
    fi
    echo "Waiting for Qdrant to be ready..."
    for i in $(seq 1 30); do
        if curl -sf "http://localhost:$PORT/healthz" > /dev/null 2>&1; then
            echo "Qdrant is ready at localhost:$PORT"
            exit 0
        fi
        sleep 1
    done
    echo "Timeout waiting for Qdrant to start"
    exit 1
}

stop() {
    if docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        echo "Stopping Qdrant container..."
        docker stop "$CONTAINER_NAME" > /dev/null
    fi
    if docker ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        docker rm "$CONTAINER_NAME" > /dev/null
    fi
    echo "Qdrant stopped"
}

status() {
    if docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        echo "Qdrant is RUNNING on port $PORT"
        echo "  Web UI: http://localhost:$PORT/dashboard"
    else
        echo "Qdrant is STOPPED"
    fi
}

logs() {
    docker logs "$CONTAINER_NAME" "$@"
}

case "${1:-help}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  status ;;
    logs)    shift; logs "$@" ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo
        echo "  start   - Start Qdrant in Docker"
        echo "  stop    - Stop and remove Qdrant container"
        echo "  restart - Restart Qdrant"
        echo "  status  - Check if Qdrant is running"
        echo "  logs    - View Docker logs"
        ;;
esac
