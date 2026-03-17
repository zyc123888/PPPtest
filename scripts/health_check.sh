#!/usr/bin/env bash
set -euo pipefail

echo "检查前端服务 http://localhost:3000"
curl -fsS http://localhost:3000 >/dev/null

echo "检查后端服务 http://localhost:8000/api/v1/system/health"
curl -fsS http://localhost:8000/api/v1/system/health
echo

echo "检查 MySQL 连接"
docker-compose exec -T mysql env MYSQL_PWD=tester123 mysql -utester -e "SELECT 1;" test_platform >/dev/null

echo "检查 Redis 连接"
docker-compose exec -T redis redis-cli ping | grep -q PONG

echo "健康检查通过"
