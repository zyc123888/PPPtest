#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BACKEND_URL="${PPPTEST_BACKEND_URL:-http://127.0.0.1:8000}"
FRONTEND_URL="${PPPTEST_FRONTEND_URL:-http://127.0.0.1:3000}"
RUN_MODE="${PPPTEST_RUN_MODE:-local}"

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "未找到 docker compose / docker-compose" >&2
    return 1
  fi
}

echo "检查前端服务 ${FRONTEND_URL}"
curl -fsS "${FRONTEND_URL}" >/dev/null

echo "检查后端服务 ${BACKEND_URL}/api/v1/system/health"
HEALTH_PAYLOAD="$(curl -fsS "${BACKEND_URL}/api/v1/system/health")"
echo "${HEALTH_PAYLOAD}"

echo "基础健康检查通过"

if [[ "${RUN_MODE}" == "docker" ]]; then
  echo "检查 MySQL 连接"
  compose_cmd exec -T mysql env MYSQL_PWD=tester123 mariadb -utester -e "SELECT 1;" test_platform >/dev/null

  echo "检查 Redis 连接"
  compose_cmd exec -T redis redis-cli ping | grep -q PONG

  echo "Docker 依赖检查通过"
fi
