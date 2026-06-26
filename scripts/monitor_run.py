#!/usr/bin/env python3
"""实时监控指定任务执行状态"""
import sys
import json
import time
import urllib.request
from datetime import datetime

API_URL = "http://127.0.0.1:8000/api/v1/executions/runs/57"
TOKEN = "r0zKpo0Vz8O9ygJEFZ8GtuEOm4JwqjQ6t_bKq9pLFvU"
INTERVAL = 5

STATUS_EMOJI = {
    "PENDING": "⏳",
    "RUNNING": "🔄",
    "SUCCESS": "✅",
    "FAILED": "❌",
    "ERROR": "💥",
    "TIMEOUT": "⏰",
    "CANCELLED": "🚫",
}

last_status = None

print(f"🔍 开始监控任务 #57 (每 {INTERVAL}s 轮询)...")
print(f"   按 Ctrl+C 停止监控\n")

try:
    while True:
        req = urllib.request.Request(API_URL, headers={"Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            print(f"=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
            print(f"  ❌ 请求失败: {e}")
            time.sleep(INTERVAL)
            continue

        if "detail" in data:
            print(f"=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
            print(f"  ❌ API 错误: {data['detail']}")
            time.sleep(INTERVAL)
            continue

        status = data.get("status", "?")
        emoji = STATUS_EMOJI.get(status, "?")
        summary = data.get("summary", "N/A")
        duration = data.get("duration_ms", "N/A")
        case_name = data.get("case_name", "N/A")

        # 状态变化时打印分隔线
        if status != last_status and last_status is not None:
            print("\n" + "=" * 50)

        last_status = status
        print(f"=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
        print(f"  状态: {emoji} {status}")
        print(f"  摘要: {summary}")
        print(f"  耗时: {duration}ms")
        print(f"  用例: {case_name}")

        # 检查响应中的健康状态
        resp_payload = data.get("response_payload", {})
        if resp_payload:
            body = resp_payload.get("body", {})
            redis_st = body.get("redis", "N/A")
            db_st = body.get("database", "N/A")
            app_st = body.get("app_status", "N/A")
            print(f"  Redis: {redis_st} | DB: {db_st} | App: {app_st}")

            if redis_st == "unhealthy":
                print("  ⚠️  警告: Redis 状态异常!")
            if app_st == "degraded":
                print("  ⚠️  警告: 应用状态降级!")

        # 如果是终态，提示
        if status in ("SUCCESS", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"):
            print(f"  ℹ️  任务已到达终态: {status}")
        else:
            print(f"  ℹ️  任务仍在进行中...")

        print()
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\n🛑 监控已停止")
    sys.exit(0)
