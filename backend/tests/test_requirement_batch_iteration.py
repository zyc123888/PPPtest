"""需求批量规划到迭代（C7）回归测试。"""

import time


def _create_project(client, name: str) -> int:
    resp = client.post("/projects", json={"name": name, "base_url": "http://example.com"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_requirement(client, project_id: int, title: str) -> dict:
    resp = client.post(f"/projects/{project_id}/requirements", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_batch_plan_requirements_to_iteration(client) -> None:
    project_id = _create_project(client, f"批量迭代项目_{time.time_ns()}")

    iteration_resp = client.post(
        f"/projects/{project_id}/iterations",
        json={"name": f"迭代_{time.time_ns()}", "status": "PLANNING"},
    )
    assert iteration_resp.status_code == 201, iteration_resp.text
    iteration_id = iteration_resp.json()["id"]

    first = _create_requirement(client, project_id, f"需求A_{time.time_ns()}")
    second = _create_requirement(client, project_id, f"需求B_{time.time_ns()}")

    planned = client.put(
        "/requirements/batch-iteration",
        json={"requirement_ids": [first["id"], second["id"]], "iteration_id": iteration_id},
    )
    assert planned.status_code == 200, planned.text
    planned_items = planned.json()
    assert {item["id"] for item in planned_items} == {first["id"], second["id"]}
    assert all(item["iteration_id"] == iteration_id for item in planned_items)

    listed = client.get(f"/projects/{project_id}/requirements?page=1&page_size=50")
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()["items"]}
    assert by_id[first["id"]]["iteration_id"] == iteration_id
    assert by_id[second["id"]]["iteration_id"] == iteration_id

    unplanned = client.put(
        "/requirements/batch-iteration",
        json={"requirement_ids": [first["id"]], "iteration_id": None},
    )
    assert unplanned.status_code == 200, unplanned.text
    assert unplanned.json()[0]["iteration_id"] is None


def test_batch_plan_rejects_cross_project_mix(client) -> None:
    project_a = _create_project(client, f"批量迭代项目A_{time.time_ns()}")
    project_b = _create_project(client, f"批量迭代项目B_{time.time_ns()}")

    req_a = _create_requirement(client, project_a, f"需求A_{time.time_ns()}")
    req_b = _create_requirement(client, project_b, f"需求B_{time.time_ns()}")

    resp = client.put(
        "/requirements/batch-iteration",
        json={"requirement_ids": [req_a["id"], req_b["id"]], "iteration_id": None},
    )
    assert resp.status_code == 400, resp.text
    assert "同一项目" in resp.json()["detail"]


def test_batch_plan_rejects_missing_requirement(client) -> None:
    project_id = _create_project(client, f"批量迭代项目C_{time.time_ns()}")
    requirement = _create_requirement(client, project_id, f"需求C_{time.time_ns()}")

    resp = client.put(
        "/requirements/batch-iteration",
        json={"requirement_ids": [requirement["id"], 999999], "iteration_id": None},
    )
    assert resp.status_code == 404, resp.text

    resp = client.put(
        "/requirements/batch-iteration",
        json={"requirement_ids": [], "iteration_id": None},
    )
    assert resp.status_code == 422, resp.text
