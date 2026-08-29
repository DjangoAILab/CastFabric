#!/usr/bin/env bash
# CastFabric non-destructive Docker Compose deployment.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-local}"
export CASTFABRIC_CONFIG_DIR="${CASTFABRIC_CONFIG_DIR:-$APP_DIR/conf}"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required. Install Docker Engine and the Compose plugin first." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "The Docker Compose plugin is required." >&2
    exit 1
fi

mkdir -p "$CASTFABRIC_CONFIG_DIR"
cd "$APP_DIR"

case "$MODE" in
    local)
        docker compose build
        docker compose up -d
        ;;
    pull)
        docker compose pull
        docker compose up -d --no-build
        ;;
    *)
        echo "Usage: $0 {local|pull}" >&2
        exit 2
        ;;
esac

docker compose ps
echo "CastFabric configuration: $CASTFABRIC_CONFIG_DIR"
echo "Web UI: http://${CASTFABRIC_HOSTNAME:-<host-ip>}:8300"
