import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client() -> TestClient:
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
    os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
    os.environ.setdefault("EXECUTION_ENGINE", "httpx")
    os.environ.setdefault("BACKEND_INTERNAL_URL", "http://testserver")
    os.environ.setdefault("BACKEND_PUBLIC_URL", "http://testserver")
    os.environ.setdefault("FRONTEND_INTERNAL_URL", "http://127.0.0.1:3000")
    os.environ.setdefault("FRONTEND_PUBLIC_URL", "http://127.0.0.1:3000")
    os.environ.setdefault("SEED_DEMO_DATA_ON_BOOTSTRAP", "true")

    from app.main import app

    username = os.getenv("E2E_ADMIN_USER", "admin")
    password = os.getenv("E2E_ADMIN_PASSWORD", "admin123")

    with TestClient(app, base_url="http://testserver/api/v1") as client:
        response = client.get("/system/health")
        if response.status_code != 200:
            raise RuntimeError(f"后端健康检查失败: {response.text}")

        login_response = client.post("/auth/login", json={"username": username, "password": password})
        if login_response.status_code != 200:
            raise RuntimeError(f"登录失败: {login_response.text}")
        token = login_response.json()["token"]
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client
