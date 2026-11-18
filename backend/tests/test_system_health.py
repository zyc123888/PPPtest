"""健康检查端点契约测试（F2）。

约定：
- /system/health：依赖全部可用返回 200，任一依赖不可用（degraded）返回 503，body 保留分项状态；
- /system/health/live：liveness，进程存活即 200，不探测依赖；
- /system/health/ready：readiness，语义与 /system/health 一致。

conftest 的 client fixture 无需真实 Redis：services.collect_system_health 在单元测试
环境跳过 Redis 探测；这里用 monkeypatch 显式模拟 healthy/degraded 两条路径。
"""

from datetime import datetime, timezone

import app.services as services


def _health_payload(app_status: str, *, database: str = "healthy", redis_status: str = "healthy") -> dict:
    return {
        "app_status": app_status,
        "database": database,
        "redis": redis_status,
        "checked_at": datetime.now(timezone.utc),
    }


def test_health_returns_200_when_all_dependencies_healthy(client, monkeypatch) -> None:
    monkeypatch.setattr(services, "collect_system_health", lambda: _health_payload("healthy"))

    response = client.get("/system/health")

    assert response.status_code == 200
    body = response.json()
    assert body["app_status"] == "healthy"
    assert body["database"] == "healthy"
    assert body["redis"] == "healthy"


def test_health_returns_503_when_degraded(client, monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "collect_system_health",
        lambda: _health_payload("degraded", redis_status="unhealthy"),
    )

    response = client.get("/system/health")

    assert response.status_code == 503
    body = response.json()
    assert body["app_status"] == "degraded"
    assert body["redis"] == "unhealthy"
    assert body["database"] == "healthy"


def test_readiness_reflects_dependency_state(client, monkeypatch) -> None:
    monkeypatch.setattr(services, "collect_system_health", lambda: _health_payload("healthy"))
    assert client.get("/system/health/ready").status_code == 200

    monkeypatch.setattr(
        services,
        "collect_system_health",
        lambda: _health_payload("degraded", database="unhealthy"),
    )
    response = client.get("/system/health/ready")

    assert response.status_code == 503
    assert response.json()["database"] == "unhealthy"


def test_liveness_always_returns_200(client, monkeypatch) -> None:
    monkeypatch.setattr(
        services,
        "collect_system_health",
        lambda: _health_payload("degraded", database="unhealthy", redis_status="unhealthy"),
    )

    response = client.get("/system/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
