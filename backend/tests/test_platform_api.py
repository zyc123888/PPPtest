import hashlib
import time

from fastapi.testclient import TestClient


def test_system_health(client) -> None:
    response = client.get("/system/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["app_status"] in {"healthy", "degraded"}
    assert payload["database"] == "healthy"
    assert payload["redis"] in {"healthy", "unhealthy"}


def test_system_info_and_bootstrap(client) -> None:
    info_response = client.get("/system/info")
    assert info_response.status_code == 200
    info_payload = info_response.json()
    assert info_payload["app_name"] == "自动化测试平台"
    assert info_payload["database_backend"] in {"sqlite", "mysql+pymysql", "mysql"}
    assert info_payload["backend_public_url"].startswith("http")

    bootstrap_response = client.post("/system/bootstrap", json={"seed_demo_data": True})
    assert bootstrap_response.status_code == 200
    bootstrap_payload = bootstrap_response.json()
    assert bootstrap_payload["success"] is True
    assert isinstance(bootstrap_payload["created_tables"], list)
    assert isinstance(bootstrap_payload["schema_changes"], list)
    assert isinstance(bootstrap_payload["seeded_resources"], list)


def test_protected_system_endpoints_require_login(client) -> None:
    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        assert anonymous_client.get("/system/info").status_code == 401
        assert anonymous_client.post("/system/bootstrap", json={"seed_demo_data": False}).status_code == 401


def test_admin_can_manage_users(client) -> None:
    username = f"tester_{time.time_ns()}"
    create_response = client.post(
        "/users",
        json={
            "username": username,
            "password": "tester123",
            "display_name": "测试用户",
            "role": "tester",
        },
    )
    assert create_response.status_code == 201
    user_id = create_response.json()["id"]

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        login_response = anonymous_client.post("/auth/login", json={"username": username, "password": "tester123"})
        assert login_response.status_code == 200
        assert login_response.json()["user"]["username"] == username

    update_response = client.put(
        f"/users/{user_id}",
        json={"status": "DISABLED", "role": "viewer", "password": "tester456"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "DISABLED"
    assert update_response.json()["role"] == "viewer"

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        disabled_login = anonymous_client.post("/auth/login", json={"username": username, "password": "tester456"})
        assert disabled_login.status_code == 401


def test_legacy_password_hash_upgrades_on_login(client) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import User
    from app.services import hash_password

    legacy_username = f"legacy_{time.time_ns()}"
    legacy_password = "legacy123"
    legacy_hash = hash_password("unused")
    assert legacy_hash.startswith("pbkdf2_sha256$")

    with SessionLocal() as db:
        user = User(
            username=legacy_username,
            display_name="旧哈希用户",
            role="tester",
            status="ACTIVE",
            password_hash=hashlib.sha256(legacy_password.encode("utf-8")).hexdigest(),
        )
        db.add(user)
        db.commit()

    with TestClient(client.app, base_url="http://testserver/api/v1") as anonymous_client:
        login_response = anonymous_client.post(
            "/auth/login",
            json={"username": legacy_username, "password": legacy_password},
        )
        assert login_response.status_code == 200

    with SessionLocal() as db:
        upgraded_user = db.scalar(select(User).where(User.username == legacy_username))
        assert upgraded_user is not None
        assert upgraded_user.password_hash is not None
        assert upgraded_user.password_hash.startswith("pbkdf2_sha256$")


def test_tools_endpoints(client) -> None:
    json_response = client.post("/tools/json/format", json={"payload": '{"name":"平台","type":"测试"}'})
    assert json_response.status_code == 200
    assert '"name": "平台"' in json_response.json()["result"]

    encoded = client.post("/tools/base64/encode", json={"payload": "hello-test"}).json()["result"]
    decoded = client.post("/tools/base64/decode", json={"payload": encoded}).json()["result"]
    assert decoded == "hello-test"

    timestamp_result = client.post(
        "/tools/timestamp/convert",
        json={"payload": "2026-03-09T09:30:00+08:00"},
    )
    assert timestamp_result.status_code == 200
    assert "时间戳" in timestamp_result.json()["result"]


def test_seeded_resources_exist(client) -> None:
    workspaces = client.get("/workspaces")
    projects = client.get("/projects")
    api_cases = client.get("/api-cases")
    ui_cases = client.get("/ui-cases")
    environments = client.get("/environments")
    plans = client.get("/test-plans")

    assert workspaces.status_code == 200
    assert projects.status_code == 200
    assert api_cases.status_code == 200
    assert ui_cases.status_code == 200
    assert environments.status_code == 200
    assert plans.status_code == 200

    assert any(workspace["name"] == "默认空间" for workspace in workspaces.json())
    assert any(project["name"] == "平台自检项目" for project in projects.json())
    assert any(case["name"] == "示例健康检查接口" for case in api_cases.json())
    assert any(case["name"] == "示例前端首页巡检" for case in ui_cases.json())
    assert any(env["name"] == "本地环境" for env in environments.json())
    assert any(plan["name"] == "演示回归计划" for plan in plans.json())


def test_api_case_run(client) -> None:
    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    trigger = client.post(f"/executions/api/{case_id}/run")
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    final_payload = None
    for _ in range(40):
        final_payload = client.get(f"/executions/runs/{run_id}").json()
        if final_payload["status"] in {"SUCCESS", "FAILED"}:
            break
        time.sleep(2)

    assert final_payload is not None
    assert final_payload["status"] == "SUCCESS", final_payload


def test_ui_case_run(client) -> None:
    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    trigger = client.post(f"/executions/ui/{case_id}/run")
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    final_payload = None
    for _ in range(50):
        final_payload = client.get(f"/executions/runs/{run_id}").json()
        if final_payload["status"] in {"SUCCESS", "FAILED"}:
            break
        time.sleep(2)

    assert final_payload is not None
    assert final_payload["status"] in {"SUCCESS", "FAILED"}, final_payload
    assert final_payload["summary"]


def test_plan_run_report(client) -> None:
    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={})
    assert trigger.status_code == 200
    plan_run_id = trigger.json()["id"]

    report_payload = None
    for _ in range(60):
        report_payload = client.get(f"/reports/{plan_run_id}").json()
        if report_payload["plan_run"]["status"] in {"SUCCESS", "FAILED"}:
            break
        time.sleep(2)

    assert report_payload is not None
    assert report_payload["plan_run"]["status"] in {"SUCCESS", "FAILED"}, report_payload
    total = report_payload["plan_run"]["total_count"]
    pass_count = report_payload["plan_run"]["pass_count"]
    fail_count = report_payload["plan_run"]["fail_count"]
    assert total == pass_count + fail_count
    download_json = client.get(f"/reports/{plan_run_id}/download?format=json")
    assert download_json.status_code == 200
    assert download_json.headers.get("content-type", "").startswith("application/json")
    download_junit = client.get(f"/reports/{plan_run_id}/download?format=junit")
    assert download_junit.status_code == 200
    assert download_junit.headers.get("content-type", "").startswith("application/xml")
