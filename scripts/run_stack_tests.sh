#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

cleanup() {
  compose_cmd down -v >/dev/null 2>&1 || true
}

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

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon 未启动，无法执行整栈验证" >&2
  exit 1
fi

trap cleanup EXIT

compose_cmd up --build -d

for _ in {1..40}; do
  if PPPTEST_RUN_MODE=docker bash scripts/health_check.sh >/tmp/test-platform-health.log 2>&1; then
    cat /tmp/test-platform-health.log
    break
  fi
  sleep 5
done

PPPTEST_RUN_MODE=docker bash scripts/health_check.sh
compose_cmd exec -T backend pytest
compose_cmd run --rm e2e
