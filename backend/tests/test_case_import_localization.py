"""批量导入失败定位与整批回滚（Task E7）回归测试。"""

import time

from app.domain import cases as cases_domain


def _project(client) -> int:
    resp = client.post("/projects", json={"name": f"导入项目_{time.time_ns()}", "base_url": "http://example.com"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_import_success_across_three_types(client) -> None:
    project_id = _project(client)
    resp = client.post(
        "/cases/import",
        json={
            "items": [
                {"case_type": "API", "project_id": project_id, "name": f"接口_{time.time_ns()}", "method": "GET", "path": "/health"},
                {"case_type": "UI", "project_id": project_id, "name": f"界面_{time.time_ns()}", "target_url": "http://example.com"},
                {"case_type": "PERF", "project_id": project_id, "name": f"性能_{time.time_ns()}", "method": "GET", "path": "/load"},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["affected_count"] == 3

    stats = client.get(f"/api-cases/stats?project_id={project_id}")
    assert stats.status_code == 200
    assert stats.json()["total"] == 1


def test_import_failure_localizes_item_and_rolls_back(client, monkeypatch) -> None:
    project_id = _project(client)
    items = [
        {"case_type": "API", "project_id": project_id, "name": f"接口A_{time.time_ns()}"},
        {"case_type": "UI", "project_id": project_id, "name": f"界面B_{time.time_ns()}"},
    ]

    real_history = cases_domain._record_case_history

    def fake_history(db, *, case_type, case, action, changed_by, summary):
        if case_type == "UI":
            raise RuntimeError("boom：模拟第二条失败")
        return real_history(db, case_type=case_type, case=case, action=action, changed_by=changed_by, summary=summary)

    monkeypatch.setattr(cases_domain, "_record_case_history", fake_history)

    resp = client.post("/cases/import", json={"items": items})
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "第 2 条" in detail
    assert "UI" in detail
    assert "boom" in detail

    # 整批回滚：第一条 API 用例不应落库
    listed = client.get(f"/api-cases?project_id={project_id}")
    assert listed.status_code == 200
    payload = listed.json()
    rows = payload.get("items", payload) if isinstance(payload, dict) else payload
    assert rows == []
