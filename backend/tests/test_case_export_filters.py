import time


def test_ui_case_export_respects_folder_and_review_status(client) -> None:
    from app.core.database import SessionLocal
    from app.models import UICase
    suffix = time.time_ns()
    project_id = None
    case_ids: list[int] = []

    try:
        project_response = client.post(
            "/projects",
            json={
                "name": f"ExportFilter_{suffix}",
                "base_url": "http://export-filter.local",
                "description": "case export filter regression fixture",
            },
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]

        cases = [
            {
                "name": f"ExportMatch_{suffix}",
                "folder_path": "登录/正常流程",
                "review_status": "APPROVED",
            },
            {
                "name": f"ExportWrongReview_{suffix}",
                "folder_path": "登录/正常流程",
                "review_status": "DRAFT",
            },
            {
                "name": f"ExportWrongFolder_{suffix}",
                "folder_path": "退出/正常流程",
                "review_status": "APPROVED",
            },
        ]
        for case in cases:
            response = client.post(
                "/ui-cases",
                json={
                    "project_id": project_id,
                    "name": case["name"],
                    "folder_path": case["folder_path"],
                    "target_url": "http://export-filter.local/login",
                    "expect_text": "Dashboard",
                    "review_status": case["review_status"],
                    "steps_json": [],
                },
            )
            assert response.status_code == 201, response.text
            case_ids.append(response.json()["id"])

        with SessionLocal() as db:
            for case_id in (case_ids[0], case_ids[2]):
                db.get(UICase, case_id).review_status = 'APPROVED'
            db.commit()

        exported = client.get(
            "/cases/export",
            params={
                "case_type": "UI",
                "project_id": project_id,
                "folder_path": "登录/正常流程",
                "review_status": "APPROVED",
            },
        )
        assert exported.status_code == 200, exported.text
        payload = exported.json()
        assert payload["count"] == 1
        assert [item["case_id"] for item in payload["items"]] == [case_ids[0]]
    finally:
        for case_id in reversed(case_ids):
            client.delete(f"/ui-cases/{case_id}")
        if project_id is not None:
            client.delete(f"/projects/{project_id}")
