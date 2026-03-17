import time


def test_system_health(client) -> None:
    response = client.get("/system/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["app_status"] in {"healthy", "degraded"}
    assert payload["database"] == "healthy"
    assert payload["redis"] in {"healthy", "unhealthy"}


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
