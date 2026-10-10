#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${IMAGE_OWNER:?IMAGE_OWNER is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"
: "${GHCR_TOKEN:?GHCR_TOKEN is required}"

cd "$DEPLOY_PATH"
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u "$IMAGE_OWNER" --password-stdin
export BACKEND_IMAGE="ghcr.io/$IMAGE_OWNER/aiwerewolf-backend:$IMAGE_TAG"
export FRONTEND_IMAGE="ghcr.io/$IMAGE_OWNER/aiwerewolf-frontend:$IMAGE_TAG"

docker compose pull backend match-worker analysis-worker frontend
docker compose up -d --remove-orphans backend match-worker analysis-worker frontend nginx
docker compose ps
curl --fail --silent --show-error http://127.0.0.1/api/v1/health/ready >/dev/null
printf '%s\n' 'Deployment health check passed.'
