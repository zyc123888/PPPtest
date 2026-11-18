import os

import pytest
from fastapi.testclient import TestClient


# Test modules import application code during collection, so these values must
# exist before fixtures run and Settings is cached. Never silently inherit a
# developer or production database connection.
external_database_url = os.environ.get("DATABASE_URL", "").strip()
allow_external_database = os.environ.get("PYTEST_DB_ALLOWED") == "1"
if external_database_url and not external_database_url.startswith("sqlite:") and not allow_external_database:
    pytest.exit(
        "拒绝在外部数据库上运行测试：清除 DATABASE_URL、改用 SQLite，"
        "或仅在明确的隔离测试库上设置 PYTEST_DB_ALLOWED=1"
    )
if not allow_external_database:
    os.environ["DATABASE_URL"] = f"sqlite:////tmp/ppptest-pytest-{os.getpid()}.db"
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("EXECUTION_ENGINE", "httpx")
os.environ.setdefault("BACKEND_INTERNAL_URL", "http://testserver")
os.environ.setdefault("BACKEND_PUBLIC_URL", "http://testserver")
os.environ.setdefault("FRONTEND_INTERNAL_URL", "http://127.0.0.1:3000")
os.environ.setdefault("FRONTEND_PUBLIC_URL", "http://127.0.0.1:3000")
os.environ.setdefault("SEED_DEMO_DATA_ON_BOOTSTRAP", "true")
os.environ.setdefault("CASE_GEN_WATCHDOG_ENABLED", "false")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "OmniTest-Test-Admin-2026")
os.environ.setdefault("E2E_ADMIN_PASSWORD", os.environ["INITIAL_ADMIN_PASSWORD"])
os.environ.setdefault("APP_ENCRYPTION_KEY", "U2eJKdn2B5HSE9Bo4Q9bWUUFSOU0ZDyICMU9t0ZZvC0=")


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.core.config import settings
    settings.case_gen_watchdog_enabled = False
    from app.db_migrate import upgrade_database
    upgrade_database()
    from app.main import app

    username = os.getenv("E2E_ADMIN_USER", "admin")
    password = os.getenv("E2E_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError(
            "E2E_ADMIN_PASSWORD 未设置：e2e / 后端集成测试需要与管理员口令一致的环境变量，"
            "请在 e2e/.env 或 CI 环境中提供"
        )

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


@pytest.fixture(scope="session")
def reviewer_client(client):
    username = f"review_fixture_{os.getpid()}"
    password = "Review-fixture-2026"
    created = client.post('/users', json={'username': username, 'password': password, 'role': 'admin'})
    assert created.status_code == 201, created.text
    with TestClient(client.app, base_url='http://testserver/api/v1') as reviewer:
        login = reviewer.post('/auth/login', json={'username': username, 'password': password})
        assert login.status_code == 200, login.text
        reviewer.headers.update({'Authorization': f"Bearer {login.json()['token']}"})
        yield reviewer
