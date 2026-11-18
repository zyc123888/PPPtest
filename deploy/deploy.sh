#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/compose.production.yml"
ENV_FILE="${SCRIPT_DIR}/.env.production"
STATE_FILE="${SCRIPT_DIR}/.last-successful-image-tag"
LOCK_DIR="${SCRIPT_DIR}/.deploy-lock"
NEW_TAG="${1:-}"
BACKUP_DIR="${BACKUP_DIR:-${SCRIPT_DIR}/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
DEPLOY_LOG="${SCRIPT_DIR}/deploy.log"

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

log_deploy() {
  printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" >> "${DEPLOY_LOG}"
}

# 发布前把 MariaDB 全量 dump 落盘并校验大小，保留最近 BACKUP_KEEP 份。
backup_database() {
  # 首次部署（尚无运行中的 mysql 容器）没有存量数据可备份，直接跳过。
  if [[ -z "$(compose ps -q mysql 2>/dev/null)" ]]; then
    echo "No running mysql container; skipping pre-deploy database backup."
    log_deploy "backup skipped (no running mysql)"
    return 0
  fi
  mkdir -p "${BACKUP_DIR}"
  local stamp out size
  stamp="$(date -u '+%Y%m%dT%H%M%SZ')"
  out="${BACKUP_DIR}/omnitest-${stamp}.sql.gz"
  if ! compose exec -T mysql sh -lc \
    'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb-dump -uroot --single-transaction --routines --triggers "$MARIADB_DATABASE"' \
    | gzip > "${out}"; then
    echo "Database backup failed (dump returned non-zero)." >&2
    rm -f "${out}"
    return 1
  fi
  size="$(wc -c < "${out}" | tr -d ' ')"
  if [[ -z "${size}" || "${size}" -lt 1024 ]]; then
    echo "Database backup suspiciously small (${size} bytes); aborting deployment." >&2
    rm -f "${out}"
    return 1
  fi
  ls -1t "${BACKUP_DIR}"/omnitest-*.sql.gz 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | xargs -r rm -f
  echo "Database backup: ${out} (${size} bytes)"
  log_deploy "backup ${out} (${size} bytes)"
  return 0
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

if ! backup_database; then
  echo "Pre-deploy database backup failed; aborting deployment." >&2
  exit 6
fi

export IMAGE_TAG="${NEW_TAG}"
echo "Deploying OmniTest image tag ${NEW_TAG}"
log_deploy "deploy start tag=${NEW_TAG} previous=${PREVIOUS_TAG:-none}"
compose pull
compose up -d --remove-orphans

if healthcheck; then
  printf '%s\n' "${NEW_TAG}" > "${STATE_FILE}"
  log_deploy "deploy success tag=${NEW_TAG}"
  compose ps
  docker image prune -f --filter "until=168h" >/dev/null 2>&1 || true
  echo "Deployment succeeded: ${NEW_TAG}"
  exit 0
fi

echo "Deployment health check failed for ${NEW_TAG}." >&2
compose logs --tail=120 backend frontend worker case-worker >&2 || true

if [[ -n "${PREVIOUS_TAG}" && "${PREVIOUS_TAG}" != "${NEW_TAG}" ]]; then
  echo "Rolling back to ${PREVIOUS_TAG}." >&2
  log_deploy "rollback start tag=${PREVIOUS_TAG} (from ${NEW_TAG})"
  export IMAGE_TAG="${PREVIOUS_TAG}"
  compose pull
  compose up -d --remove-orphans
  if healthcheck; then
    echo "Rollback succeeded: ${PREVIOUS_TAG}" >&2
    log_deploy "rollback success tag=${PREVIOUS_TAG}"
  else
    echo "Rollback also failed; manual intervention is required." >&2
    log_deploy "rollback failed tag=${PREVIOUS_TAG}"
  fi
else
  echo "No previous successful image tag is available for rollback." >&2
  log_deploy "deploy failed tag=${NEW_TAG} (no rollback target)"
fi

exit 1
