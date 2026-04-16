#!/usr/bin/env bash
# Pull the latest images and (re)deploy Atlas in production.
#
# Uses docker-compose.prod.yml, which references GHCR-hosted images
# (built by the build.yml workflow). Run this on the droplet, typically
# triggered from a deploy CI job or by hand:
#
#   ATLAS_VERSION=main ./infra/scripts/deploy.sh

set -euo pipefail

cd "$(dirname "$0")/../.."

if [[ ! -f .env ]]; then
  echo ".env not found at $(pwd)/.env" >&2
  exit 1
fi

export $(grep -v '^\s*#' .env | grep -v '^\s*$' | xargs -d '\n')
export ATLAS_VERSION="${ATLAS_VERSION:-latest}"

echo "==> Pulling images (version=${ATLAS_VERSION})"
docker compose -f docker-compose.prod.yml pull

echo "==> Deploying"
docker compose -f docker-compose.prod.yml up -d --remove-orphans

echo "==> Running migrations"
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

echo "==> Health check"
sleep 5
docker compose -f docker-compose.prod.yml exec -T api \
  curl -fsS http://localhost:8000/health/ready >/dev/null \
  && echo "OK" \
  || { echo "readiness check FAILED" >&2; exit 1; }

echo "==> Done."
