from __future__ import annotations

import json
import time
from pathlib import Path

from app.artifact_revision import artifact_revision
from app.core.database import SessionLocal
from app.models import (
    AIModelConfig,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
)


def test_v2_preview_and_download_reject_stale_artifact_revision(client, monkeypatch, tmp_path: Path) -> None:
    from app import api

    project = client.get("/projects").json()[0]
    with SessionLocal() as db:
        db.add(
            AIModelConfig(
                workspace_id=project["workspace_id"],
                provider="OPENAI",
                name="artifact-revision-test",
                base_url="https://revision.example/v1",
                model="revision-test-model",
                api_key="test-only-key",
                is_active=1,
            )
        )
        db.commit()

    monkeypatch.setattr(api, "_dispatch_task_or_run_inline", lambda *args, **kwargs: ("queued-task", False))
    created = client.post(
        "/case-generation-v2/jobs",
        json={
            "project_id": project["id"],
            "name": f"产物版本校验_{time.time_ns()}",
            "markdown_text": "# 登录\n覆盖登录成功和失败。",
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    file_path = tmp_path / "scope_index.json"
    first_payload = {"revision_data": "first"}
    second_payload = {"revision_data": "second"}
    first_bytes = json.dumps(first_payload, ensure_ascii=False, indent=2).encode("utf-8")
    second_bytes = json.dumps(second_payload, ensure_ascii=False, indent=2).encode("utf-8")
    file_path.write_bytes(first_bytes)

    with SessionLocal() as db:
        attempt = db.query(CaseGenerationV2Attempt).filter_by(job_id=job_id).one()
        artifact = CaseGenerationV2Artifact(
            job_id=job_id,
            attempt_id=attempt.id,
            artifact_type="scope_index",
            file_name=file_path.name,
            file_path=str(file_path),
            content_json=first_payload,
            revision=artifact_revision(content_json=first_payload),
        )
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id
        first_revision = artifact.revision

    detail_url = f"/case-generation-v2/jobs/{job_id}"
    artifact_url = f"{detail_url}/artifacts/{artifact_id}"
    download_url = f"{artifact_url}/download"
    initial_detail = client.get(detail_url).json()
    assert initial_detail["artifacts"][0]["revision"] == first_revision
    assert client.get(f"{artifact_url}?revision={first_revision}").json()["content_json"] == first_payload
    assert client.get(f"{download_url}?revision={first_revision}").content == first_bytes

    file_path.write_bytes(second_bytes)
    stale_download = client.get(f"{download_url}?revision={first_revision}")
    assert stale_download.status_code == 409

    with SessionLocal() as db:
        artifact = db.get(CaseGenerationV2Artifact, artifact_id)
        artifact.content_json = second_payload
        artifact.revision = artifact_revision(content_json=second_payload)
        db.commit()
        second_revision = artifact.revision

    assert second_revision != first_revision
    assert client.get(f"{artifact_url}?revision={first_revision}").status_code == 409
    refreshed_detail = client.get(detail_url).json()
    assert refreshed_detail["artifacts"][0]["revision"] == second_revision
    assert client.get(f"{artifact_url}?revision={second_revision}").json()["content_json"] == second_payload
    assert client.get(f"{download_url}?revision={second_revision}").content == second_bytes
