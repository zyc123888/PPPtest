#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/compose.production.yml"
ENV_FILE="${SCRIPT_DIR}/.env.production"
STATE_FILE="${SCRIPT_DIR}/.last-successful-image-tag"
LOCK_DIR="${SCRIPT_DIR}/.deploy-lock"
NEW_TAG="${1:-}"

if [[ -z "${NEW_TAG}" ]]; then
  echo "Usage: ./deploy.sh <image-tag>" >&2
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Create it from .env.production.example first." >&2
  exit 3
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 4
fi

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "Another deployment is already running." >&2
  exit 5
fi
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

compose() {
  IMAGE_TAG="${IMAGE_TAG}" docker compose \
    --env-file "${ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    "$@"
}

healthcheck() {
  local attempt
  for attempt in $(seq 1 36); do
    if compose exec -T backend curl -fsS \
      http://127.0.0.1:8000/api/v1/system/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

PREVIOUS_TAG=""
if [[ -f "${STATE_FILE}" ]]; then
  PREVIOUS_TAG="$(tr -d '[:space:]' < "${STATE_FILE}")"
fi

export IMAGE_TAG="${NEW_TAG}"
echo "Deploying OmniTest image tag ${NEW_TAG}"
compose pull
compose up -d --remove-orphans

if healthcheck; then
  printf '%s\n' "${NEW_TAG}" > "${STATE_FILE}"
  compose ps
  docker image prune -f --filter "until=168h" >/dev/null 2>&1 || true
  echo "Deployment succeeded: ${NEW_TAG}"
  exit 0
fi

echo "Deployment health check failed for ${NEW_TAG}." >&2
compose logs --tail=120 backend frontend worker case-worker >&2 || true

if [[ -n "${PREVIOUS_TAG}" && "${PREVIOUS_TAG}" != "${NEW_TAG}" ]]; then
  echo "Rolling back to ${PREVIOUS_TAG}." >&2
  export IMAGE_TAG="${PREVIOUS_TAG}"
  compose pull
  compose up -d --remove-orphans
  if healthcheck; then
    echo "Rollback succeeded: ${PREVIOUS_TAG}" >&2
  else
    echo "Rollback also failed; manual intervention is required." >&2
  fi
else
  echo "No previous successful image tag is available for rollback." >&2
fi

exit 1
