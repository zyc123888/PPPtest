#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

docker-compose up --build -d

for _ in {1..40}; do
  if bash scripts/health_check.sh >/tmp/test-platform-health.log 2>&1; then
    cat /tmp/test-platform-health.log
    break
  fi
  sleep 5
done

bash scripts/health_check.sh
docker-compose exec -T backend pytest
docker-compose --profile test run --rm e2e
