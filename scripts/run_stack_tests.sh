#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CURRENT_STEP="bootstrap"

# 默认保留数据卷（docker compose down），避免误删本地开发数据；
# 显式传入 --purge 时才连同卷一起删除（down -v）。
PURGE_VOLUMES=false
for arg in "$@"; do
  case "${arg}" in
    --purge) PURGE_VOLUMES=true ;;
    *)
      echo "未知参数：${arg}（支持：--purge）" >&2
      exit 2
      ;;
  esac
done

cleanup() {
  if [[ "${PURGE_VOLUMES}" == "true" ]]; then
    compose_cmd down -v >/dev/null 2>&1 || true
  else
    compose_cmd down >/dev/null 2>&1 || true
  fi
}

dump_diagnostics() {
  echo ""
  echo "==== Stack diagnostics (step: ${CURRENT_STEP}) ===="
  compose_cmd ps || true
  compose_cmd logs backend --tail=200 || true
  compose_cmd logs frontend --tail=200 || true
  compose_cmd logs worker --tail=200 || true
  compose_cmd logs mysql --tail=200 || true
}

on_error() {
  local exit_code=$?
  local failed_command="${BASH_COMMAND:-unknown}"
  echo "❌ Stack tests failed at step: ${CURRENT_STEP}"
  echo "❌ Failed command: ${failed_command}"
  echo "❌ Exit code: ${exit_code}"
  dump_diagnostics
  exit "${exit_code}"
}

run_step() {
  local name="$1"
  shift
  CURRENT_STEP="${name}"
  echo "==== Running step: ${CURRENT_STEP} ===="
  "$@"
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
trap on_error ERR

run_step "compose_up" compose_cmd up --build -d

for _ in {1..40}; do
  if PPPTEST_RUN_MODE=docker bash scripts/health_check.sh >/tmp/test-platform-health.log 2>&1; then
    cat /tmp/test-platform-health.log
    break
  fi
  sleep 5
done

run_step "health_check" env PPPTEST_RUN_MODE=docker bash scripts/health_check.sh
run_step "backend_pytest" compose_cmd exec -T backend pytest
run_step "build_e2e_image" compose_cmd build e2e

E2E_SPECS=(
  tests/admin_layout.spec.js
  tests/full_flow.spec.js
  tests/workspace_membership_flow.spec.js
  tests/workspace_owner_guard.spec.js
  tests/execution_artifact_download.spec.js
)

run_step "run_e2e_specs" compose_cmd run --rm e2e npx playwright test "${E2E_SPECS[@]}" --reporter=line
