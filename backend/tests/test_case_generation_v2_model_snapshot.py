from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import AIModelConfig, CaseGenerationV2Attempt, CaseGenerationV2Job


def test_v2_attempt_snapshots_submitted_model_config(client, monkeypatch) -> None:
    from app import api
    from app.tasks.case_generation_v2_pipeline import engine

    # 使用独立用户 + 独立项目，避免与套件中其它用例遗留的「进行中生成任务」冲突。
    username = f"snapshot_user_{time.time_ns()}"
    created = client.post(
        "/users", json={"username": username, "password": "snapshot-pw-123", "role": "admin"}
    )
    assert created.status_code == 201, created.text

    with TestClient(client.app, base_url="http://testserver/api/v1") as isolated:
        login = isolated.post("/auth/login", json={"username": username, "password": "snapshot-pw-123"})
        assert login.status_code == 200, login.text
        isolated.headers.update({"Authorization": f"Bearer {login.json()['token']}"})

        project = isolated.post(
            "/projects", json={"name": f"快照项目_{time.time_ns()}", "base_url": "http://example.com"}
        ).json()

        with SessionLocal() as db:
            db.add(
                AIModelConfig(
                    workspace_id=project["workspace_id"],
                    provider="OPENAI",
                    name="snapshot-shared-config",
                    base_url="https://config-a.example/v1",
                    model="config-a-model",
                    api_key="test-only-key",
                    is_active=1,
                )
            )
            db.commit()

        monkeypatch.setattr(api, "_dispatch_task_or_run_inline", lambda *args, **kwargs: ("queued-task", False))
        created = isolated.post(
            "/case-generation-v2/jobs",
            json={
                "project_id": project["id"],
                "name": f"模型快照_{time.time_ns()}",
                "markdown_text": "# 登录\n覆盖登录成功和失败。",
                "openai_model": "config-b-model",
                "openai_base_url": "https://config-b.example/v1",
            },
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["id"]
        assert created.json()["input_payload_json"]["openai_model"] == "config-b-model"

    with SessionLocal() as db:
        attempt = db.query(CaseGenerationV2Attempt).filter_by(job_id=job_id).one()
        snapshot = (attempt.input_payload_json or {}).get("model_config_snapshot")
        assert snapshot["model"] == "config-b-model"
        assert snapshot["base_url"] == "https://config-b.example/v1"
        assert snapshot["provider"]
        model_config_id = snapshot["model_config_id"]

    # 排队期间修改共享配置 A，不应影响已提交 attempt 的任务级快照
    with SessionLocal() as db:
        shared = db.get(AIModelConfig, model_config_id)
        shared.model = "config-a-mutated"
        shared.base_url = "https://config-a-mutated.example/v1"
        db.commit()

    with SessionLocal() as db:
        attempt = db.query(CaseGenerationV2Attempt).filter_by(job_id=job_id).one()
        snapshot = (attempt.input_payload_json or {}).get("model_config_snapshot")
        assert snapshot["model"] == "config-b-model"
        assert snapshot["base_url"] == "https://config-b.example/v1"

        # 执行时解析：优先读 attempt 快照，Key 仍按引用解析
        job = db.get(CaseGenerationV2Job, job_id)
        api_key, model, base_url = engine._resolve_model_execution_config(
            db,
            dict(job.input_payload_json or {}),
            dict(attempt.input_payload_json or {}),
        )
        assert model == "config-b-model"
        assert base_url == "https://config-b.example/v1"
        assert api_key == "test-only-key"
