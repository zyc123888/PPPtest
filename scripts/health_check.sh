#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

BACKEND_URL="${OMNITEST_BACKEND_URL:-${PPPTEST_BACKEND_URL:-http://127.0.0.1:8000}}"
FRONTEND_URL="${OMNITEST_FRONTEND_URL:-${PPPTEST_FRONTEND_URL:-http://127.0.0.1:3000}}"
RUN_MODE="${OMNITEST_RUN_MODE:-${PPPTEST_RUN_MODE:-local}}"

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
# 依赖不可用时 /system/health 返回 503，curl -fsS 会以非零退出，set -e 直接失败。
HEALTH_PAYLOAD="$(curl -fsS "${BACKEND_URL}/api/v1/system/health")"
echo "${HEALTH_PAYLOAD}"

echo "基础健康检查通过"

if [[ "${RUN_MODE}" == "docker" ]]; then
  echo "检查应用容器运行状态"
  for service in backend frontend worker fast-worker perf-worker case-worker beat mysql redis; do
    container_id="$(compose_cmd ps -q "${service}")"
    if [[ -z "${container_id}" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "${container_id}")" != "true" ]]; then
      echo "服务 ${service} 未运行" >&2
      exit 1
    fi
  done

  echo "检查 MySQL 连接"
  compose_cmd exec -T mysql sh -lc \
    'MYSQL_PWD="$MARIADB_PASSWORD" mariadb -u"$MARIADB_USER" -e "SELECT 1;" "$MARIADB_DATABASE"' >/dev/null

  echo "检查 Redis 连接"
  redis_ping="$(compose_cmd exec -T redis redis-cli ping)"
  grep -q PONG <<<"${redis_ping}"

  echo "检查浏览器执行 Worker 响应"
  execution_ping="$(compose_cmd exec -T worker sh -lc \
    'celery -A app.core.celery_app.celery_app inspect ping --timeout=5 -d "execution@$(hostname)"')"
  grep -q pong <<<"${execution_ping}"

  echo "检查快队列 Worker 响应"
  fast_ping="$(compose_cmd exec -T fast-worker sh -lc \
    'celery -A app.core.celery_app.celery_app inspect ping --timeout=5 -d "fast@$(hostname)"')"
  grep -q pong <<<"${fast_ping}"

  echo "检查性能 Worker 响应"
  perf_ping="$(compose_cmd exec -T perf-worker sh -lc \
    'celery -A app.core.celery_app.celery_app inspect ping --timeout=5 -d "perf@$(hostname)"')"
  grep -q pong <<<"${perf_ping}"

  echo "检查用例生成 Worker 响应"
  case_generation_ping="$(compose_cmd exec -T case-worker sh -lc \
    'celery -A app.core.celery_app.celery_app inspect ping --timeout=5 -d "case-generation@$(hostname)"')"
  grep -q pong <<<"${case_generation_ping}"

  echo "Docker 依赖检查通过"
fi
