#!/usr/bin/env bash
# CastFabric Docker Compose lifecycle helper. Persistent configuration is never removed.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

case "${1:-}" in
    start)
        docker compose up -d
        ;;
    stop)
        docker compose stop
        ;;
    restart)
        docker compose restart
        ;;
    logs)
        if [[ "${2:-}" == "-f" ]]; then
            docker compose logs -f castfabric
        else
            docker compose logs castfabric
        fi
        ;;
    status)
        docker compose ps
        ;;
    update)
        docker compose pull
        docker compose up -d --no-build
        ;;
    down)
        docker compose down
        echo "Containers removed; configuration under ${CASTFABRIC_CONFIG_DIR:-$APP_DIR/conf} was preserved."
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|logs|logs -f|status|update|down}" >&2
        exit 2
        ;;
esac
