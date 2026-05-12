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
    assert "默认空间" in update_response.json()["workspaces"]

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


def test_role_based_access_boundaries(client) -> None:
    viewer_username = f"viewer_{time.time_ns()}"
    tester_username = f"tester_role_{time.time_ns()}"
    for username, role in ((viewer_username, "viewer"), (tester_username, "tester")):
        response = client.post(
            "/users",
            json={
                "username": username,
                "password": "role123",
                "display_name": username,
                "role": role,
            },
        )
        assert response.status_code == 201

    def login_as(username: str) -> TestClient:
        role_client = TestClient(client.app, base_url="http://testserver/api/v1")
        login_response = role_client.post("/auth/login", json={"username": username, "password": "role123"})
        assert login_response.status_code == 200
        token = login_response.json()["token"]
        role_client.headers.update({"Authorization": f"Bearer {token}"})
        return role_client

    projects = client.get("/projects").json()
    project_id = next(project["id"] for project in projects if project["name"] == "平台自检项目")

    with login_as(viewer_username) as viewer_client:
        assert viewer_client.get("/projects").status_code == 200
        assert viewer_client.post(
            "/projects",
            json={"name": f"viewer_project_{time.time_ns()}", "base_url": "http://example.com"},
        ).status_code == 403
        assert viewer_client.post("/system/bootstrap", json={"seed_demo_data": False}).status_code == 403
        assert viewer_client.delete(f"/projects/{project_id}").status_code == 403

    with login_as(tester_username) as tester_client:
        create_response = tester_client.post(
            "/projects",
            json={"name": f"tester_project_{time.time_ns()}", "base_url": "http://example.com"},
        )
        assert create_response.status_code == 201
        created_project_id = create_response.json()["id"]
        assert tester_client.post("/system/bootstrap", json={"seed_demo_data": False}).status_code == 403
        assert tester_client.delete(f"/projects/{created_project_id}").status_code == 403


def test_workspace_membership_isolates_project_data(client) -> None:
    isolated_workspace = client.post(
        "/workspaces",
        json={"name": f"隔离空间_{time.time_ns()}", "description": "membership isolation"},
    )
    assert isolated_workspace.status_code == 201
    workspace_id = isolated_workspace.json()["id"]

    isolated_project = client.post(
        "/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"隔离项目_{time.time_ns()}",
            "base_url": "http://example.com",
        },
    )
    assert isolated_project.status_code == 201
    isolated_project_id = isolated_project.json()["id"]

    username = f"isolated_{time.time_ns()}"
    user_response = client.post(
        "/users",
        json={"username": username, "password": "role123", "display_name": username, "role": "tester"},
    )
    assert user_response.status_code == 201
    user_id = user_response.json()["id"]

    member_client = TestClient(client.app, base_url="http://testserver/api/v1")
    login_response = member_client.post("/auth/login", json={"username": username, "password": "role123"})
    assert login_response.status_code == 200
    member_client.headers.update({"Authorization": f"Bearer {login_response.json()['token']}"})

    projects_before = member_client.get("/projects")
    assert projects_before.status_code == 200
    assert all(project["id"] != isolated_project_id for project in projects_before.json())
    assert member_client.get(f"/projects?workspace_id={workspace_id}").status_code == 403
    assert member_client.post(
        "/projects",
        json={
            "workspace_id": workspace_id,
            "name": f"越权项目_{time.time_ns()}",
            "base_url": "http://example.com",
        },
    ).status_code == 403

    add_member = client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": user_id, "role": "member"},
    )
    assert add_member.status_code == 201

    update_member = client.put(
        f"/workspaces/{workspace_id}/members/{add_member.json()['id']}",
        json={"role": "owner"},
    )
    assert update_member.status_code == 200
    assert update_member.json()["role"] == "owner"

    users = client.get("/users")
    assert users.status_code == 200
    isolated_user = next(user for user in users.json() if user["id"] == user_id)
    assert "默认空间" in isolated_user["workspaces"]
    assert any(name.startswith("隔离空间_") for name in isolated_user["workspaces"])

    projects_after = member_client.get("/projects")
    assert projects_after.status_code == 200
    assert any(project["id"] == isolated_project_id for project in projects_after.json())
    assert member_client.get(f"/projects?workspace_id={workspace_id}").status_code == 200


def test_workspace_owner_guard_prevents_removing_last_owner(client) -> None:
    workspace_response = client.post(
        "/workspaces",
        json={"name": f"owner_guard_{time.time_ns()}", "description": "owner guard"},
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["id"]

    owner_members = client.get(f"/workspaces/{workspace_id}/members")
    assert owner_members.status_code == 200
    admin_member = next(member for member in owner_members.json() if member["role"] == "owner")

    downgrade_response = client.put(
        f"/workspaces/{workspace_id}/members/{admin_member['id']}",
        json={"role": "member"},
    )
    assert downgrade_response.status_code == 400
    assert "Owner" in downgrade_response.json()["detail"]

    delete_response = client.delete(f"/workspaces/{workspace_id}/members/{admin_member['id']}")
    assert delete_response.status_code == 400
    assert "Owner" in delete_response.json()["detail"]


def test_user_payload_includes_workspace_memberships(client) -> None:
    me_response = client.get("/auth/me")
    assert me_response.status_code == 200
    payload = me_response.json()
    assert "workspace_memberships" in payload
    assert any(item["workspace_name"] == "默认空间" for item in payload["workspace_memberships"])


def test_tools_endpoints(client) -> None:
    json_response = client.post("/tools/json/format", json={"payload": '{"name":"平台","type":"测试"}'})
    assert json_response.status_code == 200
    assert '"name": "平台"' in json_response.json()["result"]


def test_environment_update_and_variables_api(client) -> None:
    projects_response = client.get("/projects")
    assert projects_response.status_code == 200
    project_id = projects_response.json()[0]["id"]

    create_response = client.post(
        "/environments",
        json={
            "project_id": project_id,
            "name": f"env_{time.time_ns()}",
            "base_url": "http://backend:8000",
            "headers_json": {"accept": "application/json"},
            "variables_json": {"token": "abc"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{token}}"},
        },
    )
    assert create_response.status_code == 201
    env_id = create_response.json()["id"]

    update_response = client.put(
        f"/environments/{env_id}",
        json={
            "name": "updated env",
            "base_url": "http://testserver",
            "headers_json": {"x-env": "test"},
            "variables_json": {"token": "xyz"},
            "auth_config_json": {"header_name": "Authorization", "token": "{{token}}"},
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["name"] == "updated env"
    assert payload["base_url"] == "http://testserver"
    assert payload["variables_json"]["token"] == "xyz"

    variables_response = client.get(f"/environments/{env_id}/variables")
    assert variables_response.status_code == 200
    assert variables_response.json()["headers_json"]["x-env"] == "test"

    variables_update_response = client.put(
        f"/environments/{env_id}/variables",
        json={
            "headers_json": {"x-env": "changed"},
            "variables_json": {"token": "final"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{token}}"},
        },
    )
    assert variables_update_response.status_code == 200
    assert variables_update_response.json()["variables_json"]["token"] == "final"

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


def test_environment_variables_and_auth_config_api(client) -> None:
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    get_response = client.get(f"/environments/{environment_id}/variables")
    assert get_response.status_code == 200
    assert "variables_json" in get_response.json()

    put_response = client.put(
        f"/environments/{environment_id}/variables",
        json={
            "variables_json": {"frontend_url": "http://frontend:3000", "token": "demo-token"},
            "headers_json": {"accept": "application/json"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{token}}"},
        },
    )
    assert put_response.status_code == 200
    assert put_response.json()["auth_config_json"]["token"] == "{{token}}"


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
    assert final_payload["stdout_text"] is not None
    assert isinstance(final_payload["artifacts_json"], list)

    log_payload = client.get(f"/executions/runs/{run_id}/logs")
    assert log_payload.status_code == 200
    assert "stdout_text" in log_payload.json()

    artifacts_payload = client.get(f"/executions/runs/{run_id}/artifacts")
    assert artifacts_payload.status_code == 200
    assert len(artifacts_payload.json()["artifacts"]) >= 1
    artifact_download = client.get(f"/executions/runs/{run_id}/artifacts/0/download")
    assert artifact_download.status_code == 200

    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models import ExecutionArtifact, ExecutionLog, ExecutionStep

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionLog).where(ExecutionLog.run_id == run_id)) >= 1
        assert db.scalar(
            select(func.count()).select_from(ExecutionArtifact).where(ExecutionArtifact.run_id == run_id)
        ) >= 1
        assert db.scalar(select(func.count()).select_from(ExecutionStep).where(ExecutionStep.run_id == run_id)) >= 1

    rerun_response = client.post(f"/executions/runs/{run_id}/rerun")
    assert rerun_response.status_code == 200
    assert rerun_response.json()["retry_count"] >= 1


def test_ui_case_run(client) -> None:
    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    trigger = client.post(f"/executions/ui/{case_id}/run")
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    final_payload = None
    for _ in range(50):
        final_payload = client.get(f"/executions/runs/{run_id}").json()
        if final_payload["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}:
            break
        time.sleep(2)

    assert final_payload is not None
    assert final_payload["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}, final_payload
    assert final_payload["summary"]


def test_plan_run_report(client) -> None:
    from sqlalchemy import update

    from app.core.database import SessionLocal
    from app.models import TestPlanRun

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={})
    assert trigger.status_code == 200
    plan_run_id = trigger.json()["id"]

    report_payload = None
    for _ in range(60):
        report_payload = client.get(f"/reports/{plan_run_id}").json()
        if report_payload["plan_run"]["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}:
            break
        time.sleep(2)

    assert report_payload is not None
    assert report_payload["plan_run"]["status"] in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}, report_payload
    total = report_payload["plan_run"]["total_count"]
    pass_count = report_payload["plan_run"]["pass_count"]
    fail_count = report_payload["plan_run"]["fail_count"]
    assert total == pass_count + fail_count
    with SessionLocal() as db:
        db.execute(update(TestPlanRun).where(TestPlanRun.id == plan_run_id).values(retry_count=None))
        db.commit()

    list_response = client.get("/reports")
    assert list_response.status_code == 200
    assert any(item["id"] == plan_run_id for item in list_response.json())

    download_json = client.get(f"/reports/{plan_run_id}/download?format=json")
    assert download_json.status_code == 200
    assert download_json.headers.get("content-type", "").startswith("application/json")
    download_junit = client.get(f"/reports/{plan_run_id}/download?format=junit")
    assert download_junit.status_code == 200
    assert download_junit.headers.get("content-type", "").startswith("application/xml")
