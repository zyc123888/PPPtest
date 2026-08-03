#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_DIR="${1:-/opt/omnitest}"
DEPLOY_OWNER="${2:-${SUDO_USER:-root}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo so it can prepare ${TARGET_DIR}." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine and Compose v2 first." >&2
  exit 2
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 3
fi

if ! id "${DEPLOY_OWNER}" >/dev/null 2>&1; then
  echo "Deployment user does not exist: ${DEPLOY_OWNER}" >&2
  exit 4
fi
DEPLOY_GROUP="$(id -gn "${DEPLOY_OWNER}")"

install -d -o "${DEPLOY_OWNER}" -g "${DEPLOY_GROUP}" -m 0750 "${TARGET_DIR}"
install -o "${DEPLOY_OWNER}" -g "${DEPLOY_GROUP}" -m 0644 \
  "${SCRIPT_DIR}/compose.production.yml" "${TARGET_DIR}/compose.production.yml"
install -o "${DEPLOY_OWNER}" -g "${DEPLOY_GROUP}" -m 0750 \
  "${SCRIPT_DIR}/deploy.sh" "${TARGET_DIR}/deploy.sh"

if [[ ! -f "${TARGET_DIR}/.env.production" ]]; then
  install -o "${DEPLOY_OWNER}" -g "${DEPLOY_GROUP}" -m 0600 \
    "${SCRIPT_DIR}/.env.production.example" "${TARGET_DIR}/.env.production"
  echo "Created ${TARGET_DIR}/.env.production. Replace every placeholder before deployment."
else
  echo "Existing ${TARGET_DIR}/.env.production was preserved."
fi

cat <<EOF

Server directory prepared at ${TARGET_DIR} for ${DEPLOY_OWNER}.

Next steps:
1. Edit ${TARGET_DIR}/.env.production.
2. If GHCR images are private, run: docker login ghcr.io
3. Test with: cd ${TARGET_DIR} && ./deploy.sh latest
EOF
