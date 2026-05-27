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


def test_api_case_body_modes_build_request_kwargs() -> None:
    from app.tasks.executions import _build_request_body_kwargs

    raw_json = _build_request_body_kwargs({"mode": "raw", "raw_type": "json", "raw": '{"name":"ppp"}'})
    assert raw_json == {"json": {"name": "ppp"}}

    form = _build_request_body_kwargs(
        {
            "mode": "form-data",
            "form_data": [
                {"enabled": True, "key": "token", "value": "abc", "type": "text"},
                {"enabled": False, "key": "ignored", "value": "nope", "type": "text"},
            ],
        }
    )
    assert form == {"files": {"token": (None, "abc")}}

    urlencoded = _build_request_body_kwargs(
        {"mode": "x-www-form-urlencoded", "urlencoded": [{"enabled": True, "key": "page", "value": "1"}]}
    )
    assert urlencoded == {"data": {"page": "1"}}

    graphql = _build_request_body_kwargs(
        {"mode": "graphql", "graphql": {"query": "query Viewer { viewer { id } }", "variables": {"id": 1}}}
    )
    assert graphql == {"json": {"query": "query Viewer { viewer { id } }", "variables": {"id": 1}}}

    binary = _build_request_body_kwargs({"mode": "binary", "binary": {"content": "aGVsbG8=", "encoding": "base64"}})
    assert binary == {"content": b"hello"}


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

    validate_response = client.get(f"/environments/{env_id}/validate")
    assert validate_response.status_code == 200
    assert validate_response.json()["environment_id"] == env_id
    assert validate_response.json()["is_valid"] is True
    assert validate_response.json()["summary"] == "未发现缺失变量"
    assert validate_response.json()["scope_counts"] == {}
    assert validate_response.json()["missing_variables"] == []

    draft_validate_response = client.post(
        "/environments/validate-draft",
        json={
            "project_id": project_id,
            "name": "draft env",
            "base_url": "http://testserver",
            "headers_json": {"x-env": "{{draft_token}}"},
            "variables_json": {"token": "xyz"},
            "auth_config_json": {"header_name": "Authorization", "token": "{{token}}"},
        },
    )
    assert draft_validate_response.status_code == 200
    assert draft_validate_response.json()["environment_id"] == 0
    assert draft_validate_response.json()["is_valid"] is False
    assert "draft_token" in draft_validate_response.json()["missing_variables"]
    assert draft_validate_response.json()["scope_counts"]["environment"] >= 1
    assert any("headers_json.x-env" == item["field"] for item in draft_validate_response.json()["issues"])

    variables_update_response = client.put(
        f"/environments/{env_id}/variables",
        json={
            "headers_json": {"x-env": "changed"},
            "variables_json": {"token": "final"},
            "auth_config_json": {"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{missing_token}}"},
        },
    )
    assert variables_update_response.status_code == 200
    assert variables_update_response.json()["variables_json"]["token"] == "final"

    validate_fail_response = client.get(f"/environments/{env_id}/validate")
    assert validate_fail_response.status_code == 200
    assert validate_fail_response.json()["is_valid"] is False
    assert "missing_token" in validate_fail_response.json()["missing_variables"]
    assert validate_fail_response.json()["summary"].startswith("存在缺失变量：")
    assert any("auth_config_json.token" == item["field"] for item in validate_fail_response.json()["issues"])

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
    performance_cases = client.get("/performance-cases")
    environments = client.get("/environments")
    plans = client.get("/test-plans")

    assert workspaces.status_code == 200
    assert projects.status_code == 200
    assert api_cases.status_code == 200
    assert ui_cases.status_code == 200
    assert performance_cases.status_code == 200
    assert environments.status_code == 200
    assert plans.status_code == 200

    assert any(workspace["name"] == "默认空间" for workspace in workspaces.json())
    assert any(project["name"] == "平台自检项目" for project in projects.json())
    assert any(case["name"] == "示例健康检查接口" for case in api_cases.json())
    assert any(case["name"] == "示例前端首页巡检" for case in ui_cases.json())
    assert any(case["name"] == "示例健康检查压测" for case in performance_cases.json())
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
    trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 7, "max_retries": 2})
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
    assert final_payload["timeout_seconds"] == 7
    assert final_payload["max_retries"] == 2
    assert final_payload["stdout_text"] is not None
    assert isinstance(final_payload["artifacts_json"], list)

    log_payload = client.get(f"/executions/runs/{run_id}/logs")
    assert log_payload.status_code == 200
    assert "stdout_text" in log_payload.json()
    steps_payload = client.get(f"/executions/runs/{run_id}/steps")
    assert steps_payload.status_code == 200
    assert len(steps_payload.json()) >= 1
    assert steps_payload.json()[0]["run_id"] == run_id

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

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    plan_precheck = client.get(f"/test-plans/{plan_id}/precheck")
    assert plan_precheck.status_code == 200
    assert "summary" in plan_precheck.json()
    assert "scope_counts" in plan_precheck.json()
    assert "missing_variables" in plan_precheck.json()


def test_cancel_pending_execution(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase
    from app.services import create_test_run

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        run = create_test_run(
            db,
            project_id=case.project_id,
            environment_id=None,
            case_type="API",
            case_id=case.id,
            case_name=case.name,
        )
        run_id = run.id

    cancel_response = client.post(f"/executions/runs/{run_id}/cancel")
    assert cancel_response.status_code == 200
    payload = cancel_response.json()
    assert payload["status"] == "CANCELLED"
    assert payload["error_type"] == "CANCELLED"

    second_cancel = client.post(f"/executions/runs/{run_id}/cancel")
    assert second_cancel.status_code == 400


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


def test_ui_case_collects_trace_and_step_artifacts(client, monkeypatch) -> None:
    from app.tasks import executions

    class FakeLocator:
        def __init__(self, page):
            self.page = page
            self.first = self

        def wait_for(self, timeout=None):
            return None

        def click(self, timeout=None):
            self.page.url = f"{self.page.url}#clicked"

        def fill(self, value="", timeout=None):
            self.page.filled_value = value

    class FakePage:
        def __init__(self):
            self.url = "http://frontend:3000/"
            self.filled_value = ""

        def goto(self, value, wait_until=None, timeout=None):
            self.url = value

        def locator(self, selector):
            return FakeLocator(self)

        def screenshot(self, full_page=True):
            return b"fake-png"

    class FakeTracing:
        def start(self, screenshots=True, snapshots=True, sources=True):
            return None

        def stop(self, path):
            with open(path, "wb") as handle:
                handle.write(b"trace")

    class FakeContext:
        def __init__(self):
            self.tracing = FakeTracing()
            self.page = FakePage()

        def new_page(self):
            return self.page

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, viewport=None):
            return FakeContext()

        def close(self):
            return None

    class FakePlaywrightManager:
        def __enter__(self):
            chromium = type("FakeChromium", (), {"launch": lambda self, headless=True: FakeBrowser()})()
            return type("FakePlaywright", (), {"chromium": chromium})()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(executions, "sync_playwright", lambda: FakePlaywrightManager())

    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    trigger = client.post(f"/executions/ui/{case_id}/run")
    assert trigger.status_code == 200
    run_payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert run_payload["status"] == "SUCCESS"
    artifact_names = [item["name"] for item in run_payload["artifacts_json"]]
    assert "ui-trace.zip" in artifact_names
    assert "ui-success.png" in artifact_names
    assert any(name.startswith("step-01-") for name in artifact_names)
    assert any(step["detail"].get("page_url") for step in run_payload["step_results_json"])
    assert any(step["detail"].get("screenshot") for step in run_payload["step_results_json"])


def test_performance_case_run_and_rerun(client) -> None:
    performance_cases = client.get("/performance-cases").json()
    case_id = next(case["id"] for case in performance_cases if case["name"] == "示例健康检查压测")

    precheck_response = client.get(f"/executions/perf/{case_id}/precheck")
    assert precheck_response.status_code == 200
    assert precheck_response.json()["target_type"] == "PERF"

    trigger = client.post(f"/executions/perf/{case_id}/run", json={"timeout_seconds": 30})
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    run_payload = client.get(f"/executions/runs/{run_id}").json()
    assert run_payload["case_type"] == "PERF"
    assert run_payload["status"] in {"SUCCESS", "FAILED"}
    assert run_payload["response_payload"]["avg_response_ms"] >= 0
    assert run_payload["response_payload"]["p95_response_ms"] >= 0
    assert "throughput_rps" in run_payload["response_payload"]
    artifact_names = [item["name"] for item in run_payload["artifacts_json"]]
    assert "performance-summary.json" in artifact_names
    assert "performance-results.json" in artifact_names
    assert any(step["name"] == "performance_summary" for step in run_payload["step_results_json"])

    rerun_response = client.post(f"/executions/runs/{run_id}/rerun")
    assert rerun_response.status_code == 200
    assert rerun_response.json()["case_type"] == "PERF"


def test_defect_record_can_link_report_and_failure_run(client) -> None:
    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={"timeout_seconds": 9})
    assert trigger.status_code == 200
    plan_run_id = trigger.json()["id"]

    report_payload = client.get(f"/reports/{plan_run_id}").json()
    failure_run_id = next((item["id"] for item in report_payload["test_runs"] if item["status"] != "SUCCESS"), report_payload["test_runs"][0]["id"])
    project_id = report_payload["plan_run"]["project_id"]

    create_response = client.post(
        "/defects",
        json={
            "project_id": project_id,
            "plan_run_id": plan_run_id,
            "run_id": failure_run_id,
            "title": "登录页失败缺陷",
            "platform": "JIRA",
            "external_key": "QA-123",
            "external_url": "https://jira.example.com/browse/QA-123",
            "status": "OPEN",
            "severity": "P1",
            "summary": "执行失败，需排查"
        },
    )
    assert create_response.status_code == 201
    defect_id = create_response.json()["id"]

    list_response = client.get(f"/defects?plan_run_id={plan_run_id}")
    assert list_response.status_code == 200
    assert any(item["id"] == defect_id for item in list_response.json())

    report_response = client.get(f"/reports/{plan_run_id}")
    assert report_response.status_code == 200
    assert any(item["id"] == defect_id for item in report_response.json()["defects"])


def test_plan_run_report(client) -> None:
    from sqlalchemy import select, update

    from app.core.database import SessionLocal
    from app.models import TestPlanRun

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    trigger = client.post(f"/test-plans/{plan_id}/run", json={"timeout_seconds": 9, "max_retries": 1})
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
        from app.models import TestRun

        child_runs = db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id)).all()
        assert child_runs
        assert all(run.timeout_seconds == 9 for run in child_runs)
        assert all(run.max_retries == 1 for run in child_runs)
        db.execute(update(TestPlanRun).where(TestPlanRun.id == plan_run_id).values(retry_count=None))
        db.commit()

    list_response = client.get("/reports")
    assert list_response.status_code == 200
    list_item = next(item for item in list_response.json() if item["id"] == plan_run_id)
    assert isinstance(list_item["failure_reason_counts"], dict)
    assert isinstance(list_item["failure_reason_summary"], list)

    insights_response = client.get("/reports/insights")
    assert insights_response.status_code == 200
    insights_payload = insights_response.json()
    assert insights_payload["report_count"] >= 1
    assert "recent_trend" in insights_payload
    assert "plan_histories" in insights_payload
    assert any(item["plan_run_id"] == plan_run_id for item in insights_payload["recent_trend"])
    assert any(item["plan_id"] == plan_id for item in insights_payload["plan_histories"])

    refreshed_report_payload = client.get(f"/reports/{plan_run_id}").json()
    assert "recent_history" in refreshed_report_payload
    assert any(item["plan_run_id"] == plan_run_id for item in refreshed_report_payload["recent_history"])

    download_json = client.get(f"/reports/{plan_run_id}/download?format=json")
    assert download_json.status_code == 200
    assert download_json.headers.get("content-type", "").startswith("application/json")
    download_junit = client.get(f"/reports/{plan_run_id}/download?format=junit")
    assert download_junit.status_code == 200
    assert download_junit.headers.get("content-type", "").startswith("application/xml")


def test_api_case_auto_retry_until_success(client, monkeypatch) -> None:
    from app.tasks import executions

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    call_count = {"value": 0}

    def flaky_execute(db, run, case, project, deadline=None):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "status": "FAILED",
                "summary": "首次失败",
                "error_type": "ASSERTION",
                "exit_code": 1,
                "stdout_text": "attempt-1",
                "stderr_text": "boom",
                "artifacts_json": [],
                "step_results_json": [],
                "request_payload": {"attempt": 1},
                "response_payload": {"ok": False},
            }
        return {
            "status": "SUCCESS",
            "summary": "第二次成功",
            "exit_code": 0,
            "stdout_text": "attempt-2",
            "stderr_text": "",
            "artifacts_json": [],
            "step_results_json": [],
            "request_payload": {"attempt": 2},
            "response_payload": {"ok": True},
        }

    monkeypatch.setattr(executions, "_execute_api_case", flaky_execute)

    trigger = client.post(f"/executions/api/{case_id}/run", json={"max_retries": 1})
    assert trigger.status_code == 200
    payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert payload["status"] == "SUCCESS"
    assert payload["retry_count"] == 1
    assert payload["max_retries"] == 1
    assert "重试轨迹" in payload["summary"]


def test_api_case_auto_retry_exhausted(client, monkeypatch) -> None:
    from app.tasks import executions

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    call_count = {"value": 0}

    def always_fail(db, run, case, project, deadline=None):
        call_count["value"] += 1
        return {
            "status": "FAILED",
            "summary": f"失败-{call_count['value']}",
            "error_type": "ASSERTION",
            "exit_code": 1,
            "stdout_text": f"attempt-{call_count['value']}",
            "stderr_text": "failed",
            "artifacts_json": [],
            "step_results_json": [],
            "request_payload": {"attempt": call_count["value"]},
            "response_payload": {"ok": False},
        }

    monkeypatch.setattr(executions, "_execute_api_case", always_fail)

    trigger = client.post(f"/executions/api/{case_id}/run", json={"max_retries": 2})
    assert trigger.status_code == 200
    payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert payload["status"] == "FAILED"
    assert payload["retry_count"] == 2
    assert payload["max_retries"] == 2
    assert "第1次FAILED" in payload["summary"]
    assert "第2次FAILED" in payload["summary"]


def test_api_case_pytest_timeout_honors_run_timeout(client, monkeypatch) -> None:
    from app.core.config import settings
    from app.tasks import executions

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    original_engine = settings.execution_engine
    settings.execution_engine = "pytest"

    observed = {}

    class DummyResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_subprocess_run(*args, **kwargs):
        observed["timeout"] = kwargs.get("timeout")
        return DummyResult()

    monkeypatch.setattr(executions.subprocess, "run", fake_subprocess_run)
    try:
        trigger = client.post(f"/executions/api/{case_id}/run", json={"timeout_seconds": 3})
        assert trigger.status_code == 200
        payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
        assert payload["status"] == "SUCCESS"
        assert observed["timeout"] <= 3.0
        assert observed["timeout"] > 0
    finally:
        settings.execution_engine = original_engine


def test_ui_case_timeout_uses_total_deadline(client, monkeypatch) -> None:
    from app.tasks import executions

    ui_cases = client.get("/ui-cases").json()
    case_id = next(case["id"] for case in ui_cases if case["name"] == "示例前端首页巡检")
    observed = {"timeouts": []}

    class DummyLocator:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log
            self.first = self

        def wait_for(self, timeout=None, state=None):
            if timeout is not None:
                self.timeout_log.append(timeout)

        def click(self, timeout=None):
            if timeout is not None:
                self.timeout_log.append(timeout)

        def fill(self, value="", timeout=None):
            if timeout is not None:
                self.timeout_log.append(timeout)

    class DummyPage:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def goto(self, value, wait_until=None, timeout=None):
            if timeout is not None:
                self.timeout_log.append(timeout)
            time.sleep(0.7)

        def locator(self, selector):
            return DummyLocator(self.timeout_log)

        def screenshot(self, full_page=True):
            return b"fake-image"

    class DummyContext:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def new_page(self):
            return DummyPage(self.timeout_log)

        def close(self):
            return None

    class DummyBrowser:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def new_context(self, viewport=None):
            return DummyContext(self.timeout_log)

        def close(self):
            return None

    class DummyPlaywright:
        def __init__(self, timeout_log):
            self.chromium = self
            self.timeout_log = timeout_log

        def launch(self, headless=True):
            return DummyBrowser(self.timeout_log)

    class DummyManager:
        def __init__(self, timeout_log):
            self.timeout_log = timeout_log

        def __enter__(self):
            return DummyPlaywright(self.timeout_log)

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(executions, "sync_playwright", lambda: DummyManager(observed["timeouts"]))

    trigger = client.post(f"/executions/ui/{case_id}/run", json={"timeout_seconds": 1})
    assert trigger.status_code == 200
    payload = client.get(f"/executions/runs/{trigger.json()['id']}").json()
    assert payload["status"] in {"SUCCESS", "TIMEOUT", "ERROR"}
    assert observed["timeouts"]
    assert max(observed["timeouts"]) <= 1000


def test_api_case_missing_template_variable_fails_with_clear_message(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Environment

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        env = db.get(Environment, environment_id)
        assert case is not None
        assert env is not None
        original_path = case.path
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        case.path = "/api/v1/{{missing_token}}/health"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        precheck = client.get(f"/executions/api/{case_id}/precheck?environment_id={environment_id}")
        assert precheck.status_code == 200
        assert precheck.json()["is_valid"] is False
        assert "missing_token" in precheck.json()["missing_variables"]
        trigger = client.post(f"/executions/api/{case_id}/run", json={"environment_id": environment_id})
        assert trigger.status_code == 400
        assert trigger.json()["detail"] == "执行预检失败：存在缺失变量：1 个API 用例"
    finally:
        with SessionLocal() as db:
            case = db.get(APICase, case_id)
            env = db.get(Environment, environment_id)
            assert case is not None
            assert env is not None
            case.path = original_path
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_api_case_precheck_blocks_trigger_when_environment_variables_missing(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Environment

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        env = db.get(Environment, environment_id)
        assert case is not None
        assert env is not None
        original_path = case.path
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        case.path = "/api/v1/{{missing_from_precheck}}/health"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        precheck_response = client.get(f"/executions/api/{case_id}/precheck?environment_id={environment_id}")
        assert precheck_response.status_code == 200
        assert precheck_response.json()["is_valid"] is False
        trigger = client.post(f"/executions/api/{case_id}/run", json={"environment_id": environment_id})
        assert trigger.status_code == 400
        assert "执行预检失败" in trigger.json()["detail"]
    finally:
        with SessionLocal() as db:
            case = db.get(APICase, case_id)
            env = db.get(Environment, environment_id)
            assert case is not None
            assert env is not None
            case.path = original_path
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_api_case_rerun_is_blocked_when_environment_variables_missing(client) -> None:
    from app.core.database import SessionLocal
    from app.models import APICase, Environment

    api_cases = client.get("/api-cases").json()
    case_id = next(case["id"] for case in api_cases if case["name"] == "示例健康检查接口")
    trigger = client.post(f"/executions/api/{case_id}/run")
    assert trigger.status_code == 200
    run_id = trigger.json()["id"]

    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        case = db.get(APICase, case_id)
        env = db.get(Environment, environment_id)
        assert case is not None
        assert env is not None
        original_path = case.path
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        case.path = "/api/v1/{{rerun_missing}}/health"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        with SessionLocal() as db:
            from app.models import TestRun

            run = db.get(TestRun, run_id)
            assert run is not None
            run.environment_id = environment_id
            db.commit()

        rerun_response = client.post(f"/executions/runs/{run_id}/rerun")
        assert rerun_response.status_code == 400
        assert "执行预检失败" in rerun_response.json()["detail"]
    finally:
        with SessionLocal() as db:
            case = db.get(APICase, case_id)
            env = db.get(Environment, environment_id)
            assert case is not None
            assert env is not None
            case.path = original_path
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_plan_precheck_aggregates_multiple_case_issues(client) -> None:
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import APICase, Environment, UICase

    plans = client.get("/test-plans").json()
    plan_id = next(plan["id"] for plan in plans if plan["name"] == "演示回归计划")
    environments = client.get("/environments").json()
    environment_id = next(env["id"] for env in environments if env["name"] == "本地环境")

    with SessionLocal() as db:
        api_case = db.scalar(select(APICase).where(APICase.name == "示例健康检查接口"))
        ui_case = db.scalar(select(UICase).where(UICase.name == "示例前端首页巡检"))
        env = db.get(Environment, environment_id)
        assert api_case is not None
        assert ui_case is not None
        assert env is not None
        original_api_path = api_case.path
        original_ui_target = ui_case.target_url
        original_variables = env.variables_json
        original_auth_config = env.auth_config_json
        api_case.path = "/api/v1/{{plan_api_missing}}/health"
        ui_case.target_url = "{{plan_ui_missing}}"
        env.variables_json = {"frontend_url": "http://frontend:3000"}
        env.auth_config_json = None
        db.commit()

    try:
        response = client.get(f"/test-plans/{plan_id}/precheck?environment_id={environment_id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_valid"] is False
        assert payload["issue_count"] >= 2
        assert payload["scope_counts"]["api_case"] >= 1
        assert payload["scope_counts"]["ui_case"] >= 1
        assert "plan_api_missing" in payload["missing_variables"]
        assert "plan_ui_missing" in payload["missing_variables"]
    finally:
        with SessionLocal() as db:
            api_case = db.scalar(select(APICase).where(APICase.name == "示例健康检查接口"))
            ui_case = db.scalar(select(UICase).where(UICase.name == "示例前端首页巡检"))
            env = db.get(Environment, environment_id)
            assert api_case is not None
            assert ui_case is not None
            assert env is not None
            api_case.path = original_api_path
            ui_case.target_url = original_ui_target
            env.variables_json = original_variables
            env.auth_config_json = original_auth_config
            db.commit()


def test_unified_case_center_lists_and_filters_cases(client) -> None:
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": client.get("/projects").json()[0]["id"],
            "name": f"统一中心筛选_{time.time_ns()}",
            "folder_path": "冒烟测试/登录模块",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "tags_json": ["smoke", "login"],
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201

    response = client.get("/cases")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["case_type"] == "API" for item in payload)
    assert any(item["case_type"] == "UI" for item in payload)

    api_only = client.get("/cases?case_type=API")
    assert api_only.status_code == 200
    assert api_only.json()
    assert all(item["case_type"] == "API" for item in api_only.json())

    active_cases = client.get("/cases?status=ACTIVE")
    assert active_cases.status_code == 200
    assert active_cases.json()
    assert all(item["status"] == "ACTIVE" for item in active_cases.json())

    folder_cases = client.get("/cases?folder_path=登录模块")
    assert folder_cases.status_code == 200
    assert folder_cases.json()
    assert any(item["folder_path"] == "冒烟测试/登录模块" for item in folder_cases.json())

    any_tag_cases = client.get("/cases?tags=smoke,not_exists&tag_mode=ANY")
    assert any_tag_cases.status_code == 200
    assert any(item["name"] == create_response.json()["name"] for item in any_tag_cases.json())

    all_tag_cases = client.get("/cases?tags=smoke,login&tag_mode=ALL")
    assert all_tag_cases.status_code == 200
    assert any(item["name"] == create_response.json()["name"] for item in all_tag_cases.json())


def test_case_folder_tree_lists_nested_paths(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"目录树用例_{time.time_ns()}",
            "folder_path": "核心回归/登录/短信登录",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201

    response = client.get(f"/cases/folders?project_id={project_id}&case_type=API")
    assert response.status_code == 200
    payload = response.json()
    assert payload
    root = next((item for item in payload if item["path"] == "核心回归"), None)
    assert root is not None
    assert root["count"] >= 1
    child = next((item for item in root["children"] if item["path"] == "核心回归/登录"), None)
    assert child is not None
    leaf = next((item for item in child["children"] if item["path"] == "核心回归/登录/短信登录"), None)
    assert leaf is not None
    assert leaf["count"] >= 1


def test_case_export_and_import_json(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    exported = client.get(f"/cases/export?project_id={project_id}&case_type=API")
    assert exported.status_code == 200
    payload = exported.json()
    assert "items" in payload

    imported = client.post(
        "/cases/import",
        json={
            "items": [
                {
                    "case_type": "API",
                    "project_id": project_id,
                    "name": f"导入接口_{time.time_ns()}",
                    "method": "GET",
                    "path": "/api/v1/system/health",
                    "priority": "P1",
                    "status": "ACTIVE",
                    "review_status": "APPROVED",
                    "expected_status": 200,
                },
                {
                    "case_type": "UI",
                    "project_id": project_id,
                    "name": f"导入UI_{time.time_ns()}",
                    "target_url": "http://frontend:3000/login",
                    "steps_json": [{"action": "goto", "value": "http://frontend:3000/login"}],
                    "expect_text": "登录",
                    "priority": "P2",
                    "status": "ACTIVE",
                    "review_status": "DRAFT",
                },
            ]
        },
    )
    assert imported.status_code == 200
    assert imported.json()["affected_count"] == 2


def test_case_batch_move_folder_records_history(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"移动目录用例_{time.time_ns()}",
            "folder_path": "旧目录",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    moved = client.post(
        "/cases/batch-move-folder",
        json={
            "items": [{"case_type": "API", "case_id": case_id}],
            "folder_path": "新目录/登录",
        },
    )
    assert moved.status_code == 200
    assert moved.json()["affected_count"] == 1

    listed = client.get("/cases?folder_path=新目录/登录")
    assert listed.status_code == 200
    assert any(item["case_type"] == "API" and item["case_id"] == case_id for item in listed.json())

    history = client.get(f"/cases/API/{case_id}/history")
    assert history.status_code == 200
    assert history.json()[0]["action"] == "MOVE_FOLDER"


def test_case_duplicate_detection_groups_matching_entries(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    duplicate_path = f"/api/v1/duplicate-{time.time_ns()}"
    for index in range(2):
        response = client.post(
            "/api-cases",
            json={
                "project_id": project_id,
                "name": f"重复检测用例_{index}_{time.time_ns()}",
                "method": "GET",
                "path": duplicate_path,
                "priority": "P1",
                "status": "ACTIVE",
                "review_status": "APPROVED",
                "expected_status": 200,
            },
        )
        assert response.status_code == 201

    detected = client.get(f"/cases/duplicates?project_id={project_id}&case_type=API")
    assert detected.status_code == 200
    groups = detected.json()
    group = next((item for item in groups if item["duplicate_key"] == f"get {duplicate_path}"), None)
    assert group is not None
    assert group["count"] == 2
    assert {item["case_type"] for item in group["items"]} == {"API"}


def test_case_center_batch_update_and_add_to_plan(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"批量用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    api_case_id = create_response.json()["id"]

    batch_update = client.post(
        "/cases/batch-update",
        json={
            "items": [{"case_type": "API", "case_id": api_case_id}],
            "status": "DISABLED",
            "add_tags": ["batch", "core"],
        },
    )
    assert batch_update.status_code == 200
    assert batch_update.json()["affected_count"] == 1

    updated_case = next(item for item in client.get("/cases?case_type=API").json() if item["case_id"] == api_case_id)
    assert updated_case["status"] == "DISABLED"
    assert "batch" in (updated_case["tags_json"] or [])

    plan_id = next(plan["id"] for plan in client.get("/test-plans").json() if plan["project_id"] == project_id)
    batch_add = client.post(
        f"/test-plans/{plan_id}/cases/batch",
        json={
            "items": [{"case_type": "API", "case_id": api_case_id}],
            "order_start": 50,
        },
    )
    assert batch_add.status_code == 200
    assert batch_add.json()["affected_count"] == 1

    plan_cases = client.get(f"/test-plans/{plan_id}/cases")
    assert plan_cases.status_code == 200
    assert any(item["case_id"] == api_case_id and item["case_type"] == "API" for item in plan_cases.json())

    batch_review = client.post(
        "/cases/batch-review",
        json={
            "items": [{"case_type": "API", "case_id": api_case_id}],
            "review_status": "APPROVED",
            "review_note": "批量评审通过",
        },
    )
    assert batch_review.status_code == 200
    assert batch_review.json()["affected_count"] == 1

    reviewed_cases = client.get("/cases?review_status=APPROVED")
    assert reviewed_cases.status_code == 200
    assert any(
        item["case_id"] == api_case_id
        and item["review_status"] == "APPROVED"
        and item["review_note"] == "批量评审通过"
        for item in reviewed_cases.json()
    )


def test_plan_case_review_gate_requires_override_and_records_creator(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"待评审计划用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "review_note": "等待计划准入评审",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    api_case_id = create_response.json()["id"]

    plan_id = next(plan["id"] for plan in client.get("/test-plans").json() if plan["project_id"] == project_id)

    blocked = client.post(
        f"/test-plans/{plan_id}/cases",
        json={
            "case_type": "API",
            "case_id": api_case_id,
            "order_index": 88,
        },
    )
    assert blocked.status_code == 400
    assert "用例未通过评审" in blocked.json()["detail"]

    allowed = client.post(
        f"/test-plans/{plan_id}/cases",
        json={
            "case_type": "API",
            "case_id": api_case_id,
            "order_index": 88,
            "allow_unapproved": True,
        },
    )
    assert allowed.status_code == 201
    payload = allowed.json()
    assert payload["created_by"] is not None

    plan_cases = client.get(f"/test-plans/{plan_id}/cases")
    assert plan_cases.status_code == 200
    created = next(item for item in plan_cases.json() if item["case_id"] == api_case_id and item["case_type"] == "API")
    assert created["created_by"] == payload["created_by"]
    assert created["case_snapshot_json"]["review_status"] == "IN_REVIEW"
    assert created["case_snapshot_json"]["review_note"] == "等待计划准入评审"


def test_plan_cases_reorder_updates_order_index(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    plan_id = next(plan["id"] for plan in client.get("/test-plans").json() if plan["project_id"] == project_id)

    first = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"重排用例A_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    second = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"重排用例B_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "expected_status": 200,
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201
    first_case_id = first.json()["id"]
    second_case_id = second.json()["id"]

    add_first = client.post(
        f"/test-plans/{plan_id}/cases",
        json={"case_type": "API", "case_id": first_case_id, "order_index": 10},
    )
    add_second = client.post(
        f"/test-plans/{plan_id}/cases",
        json={"case_type": "API", "case_id": second_case_id, "order_index": 20},
    )
    assert add_first.status_code == 201
    assert add_second.status_code == 201

    reorder = client.post(
        f"/test-plans/{plan_id}/cases/reorder",
        json={
            "items": [
                {"id": add_first.json()["id"], "order_index": 2},
                {"id": add_second.json()["id"], "order_index": 1},
            ]
        },
    )
    assert reorder.status_code == 200
    assert reorder.json()["affected_count"] == 2

    listed = client.get(f"/test-plans/{plan_id}/cases")
    assert listed.status_code == 200
    latest = [
        item for item in listed.json() if item["id"] in {add_first.json()["id"], add_second.json()["id"]}
    ]
    assert [item["id"] for item in latest] == [add_second.json()["id"], add_first.json()["id"]]


def test_case_history_tracks_create_update_and_review(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"历史用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/api-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "历史追踪/接口",
            "method": "GET",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "review_note": "提交评审",
            "tags_json": ["history"],
            "headers_json": None,
            "body_json": None,
            "assertions_json": None,
            "expected_status": 200,
        },
    )
    assert update_response.status_code == 200

    batch_review = client.post(
        "/cases/batch-review",
        json={
            "items": [{"case_type": "API", "case_id": case_id}],
            "review_status": "APPROVED",
            "review_note": "评审通过",
        },
    )
    assert batch_review.status_code == 200

    history_response = client.get(f"/cases/API/{case_id}/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert [item["action"] for item in history[:3]] == ["BATCH_REVIEW", "UPDATE", "CREATE"]
    assert history[0]["review_status"] == "APPROVED"
    assert history[0]["review_note"] == "评审通过"
    assert history[1]["version_no"] == "1.0.1"


def test_api_case_update_bumps_version_and_review_status(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/api-cases",
        json={
            "project_id": project_id,
            "name": f"编辑用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expected_status": 200,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/api-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "核心回归/系统接口",
            "method": "GET",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "review_note": "接口字段已调整，等待复核",
            "tags_json": ["core"],
            "headers_json": None,
            "body_json": None,
            "assertions_json": None,
            "expected_status": 200,
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["review_status"] == "IN_REVIEW"
    assert payload["version_no"] == "1.0.1"
    assert payload["review_note"] == "接口字段已调整，等待复核"
    assert payload["path"] == "/api/v1/system/info"


def test_ui_case_update_bumps_version_and_review_status(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/ui-cases",
        json={
            "project_id": project_id,
            "name": f"UI编辑用例_{time.time_ns()}",
            "target_url": "http://frontend:3000",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expect_text": "自动化测试平台",
            "steps_json": [{"action": "goto", "value": "http://frontend:3000"}],
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/ui-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "UI回归/首页",
            "target_url": "http://frontend:3000/login",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "APPROVED",
            "version_no": "1.0.0",
            "tags_json": ["ui"],
            "assertions_json": None,
            "steps_json": [{"action": "goto", "value": "http://frontend:3000/login"}],
            "expect_text": "登录",
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["review_status"] == "APPROVED"
    assert payload["version_no"] == "1.0.1"
    assert payload["target_url"].endswith("/login")


def test_performance_case_update_bumps_version_and_review_status(client) -> None:
    project_id = client.get("/projects").json()[0]["id"]
    create_response = client.post(
        "/performance-cases",
        json={
            "project_id": project_id,
            "name": f"性能编辑用例_{time.time_ns()}",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P2",
            "status": "ACTIVE",
            "review_status": "DRAFT",
            "version_no": "1.0.0",
            "expected_status": 200,
            "concurrency": 5,
            "total_requests": 20,
            "max_avg_response_ms": 1500,
            "max_p95_response_ms": 2500,
            "max_error_rate": 0.1,
        },
    )
    assert create_response.status_code == 201
    case_id = create_response.json()["id"]

    update_response = client.put(
        f"/performance-cases/{case_id}",
        json={
            "project_id": project_id,
            "name": create_response.json()["name"],
            "folder_path": "性能基线/系统接口",
            "method": "POST",
            "path": "/api/v1/system/info",
            "priority": "P1",
            "status": "ACTIVE",
            "review_status": "IN_REVIEW",
            "version_no": "1.0.0",
            "tags_json": ["perf"],
            "headers_json": None,
            "body_json": None,
            "expected_status": 200,
            "concurrency": 8,
            "total_requests": 30,
            "max_avg_response_ms": 1200,
            "max_p95_response_ms": 2200,
            "max_error_rate": 0.05,
        },
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["review_status"] == "IN_REVIEW"
    assert payload["version_no"] == "1.0.1"
    assert payload["method"] == "POST"
