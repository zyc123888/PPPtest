"""AI 用例生成 V1/V2 序列化、产物恢复与入库领域逻辑。"""

import json
import os
import shutil
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.artifact_revision import artifact_revision
from app.models import (
    AIModelConfig,
    APICase,
    CaseGenerationArtifact,
    CaseGenerationAttempt,
    CaseGenerationJob,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
    CaseGenerationV2Job,
    Project,
    Requirement,
    UICase,
    User,
)
from app.tasks.case_generation import sanitize_case_generation_payload
from app.tasks.case_generation_v2 import _normalize_pipeline_mode
from app.tasks.case_generation_runtime import attempt_output_dir
from app.tasks.case_generation_v2_support.metrics import build_generation_metrics
from app.domain import cases as cases_domain


_JSON_CASE_GENERATION_ARTIFACT_TYPES = {
    "orchestration_plan",
    "source_manifest",
    "evidence_trace",
    "evidence_trace_gate",
    "scope_index",
    "scope_index_gate",
    "function_points",
    "requirement_handoff",
    "testcase_base_package",
    "testcase_package",
    "testcase_handoff",
    "review_report",
    "trusted_review_report",
    "execution_proof",
    "model_call_trace",
    "generation_metrics",
    "final_delivery_gate",
    "xmind_export_log",
}


_INHERITABLE_CASE_GENERATION_V2_ARTIFACT_TYPES = {
    "source_manifest",
    "evidence_trace",
    "scope_index",
    "function_points",
    "requirement_handoff",
    "testcase_base_package",
    "testcase_package",
}


def _serialize_case_generation_job(job: CaseGenerationJob) -> schemas.CaseGenerationJobRead:
    payload = {
        field: getattr(job, field)
        for field in schemas.CaseGenerationJobRead.model_fields.keys()
    }
    payload["input_payload_json"] = sanitize_case_generation_payload(payload.get("input_payload_json"))
    return schemas.CaseGenerationJobRead(**payload)


def _sanitize_case_generation_v2_payload(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    cleaned = dict(payload)
    cleaned.pop("openai_api_key", None)
    return cleaned


def _serialize_case_generation_v2_job(job: CaseGenerationV2Job) -> schemas.CaseGenerationV2JobRead:
    payload = {
        field: getattr(job, field)
        for field in schemas.CaseGenerationV2JobRead.model_fields.keys()
    }
    payload["input_payload_json"] = _sanitize_case_generation_v2_payload(payload.get("input_payload_json"))
    return schemas.CaseGenerationV2JobRead(**payload)


def _serialize_case_generation_artifact(
    artifact: CaseGenerationArtifact,
    *,
    include_content: bool,
) -> schemas.CaseGenerationArtifactRead:
    payload = {
        field: getattr(artifact, field)
        for field in schemas.CaseGenerationArtifactRead.model_fields.keys()
    }
    if not include_content:
        payload["content_json"] = None
    return schemas.CaseGenerationArtifactRead(**payload)


def _serialize_case_generation_v2_artifact(
    artifact: CaseGenerationV2Artifact,
    *,
    include_content: bool,
) -> schemas.CaseGenerationV2ArtifactRead:
    payload = {
        field: getattr(artifact, field)
        for field in schemas.CaseGenerationV2ArtifactRead.model_fields.keys()
    }
    payload["revision"] = artifact.revision or artifact_revision(
        content_json=artifact.content_json,
        file_name=artifact.file_name,
        file_path=artifact.file_path,
    )
    if not include_content:
        payload["content_json"] = None
    return schemas.CaseGenerationV2ArtifactRead(**payload)


def _case_generation_artifact_media_type(artifact_type: str) -> str:
    normalized = artifact_type.lower()
    if normalized in _JSON_CASE_GENERATION_ARTIFACT_TYPES:
        return "application/json"
    if normalized in {"markdown", "xmindmark"}:
        return "text/markdown; charset=utf-8"
    if normalized == "xmind":
        return "application/vnd.xmind.workbook"
    return "application/octet-stream"


def _case_generation_v2_parent_attempt_id(db: Session, job: CaseGenerationV2Job) -> int | None:
    if job.active_attempt_id is not None:
        return job.active_attempt_id
    return db.scalar(
        select(CaseGenerationV2Attempt.id)
        .where(CaseGenerationV2Attempt.job_id == job.id)
        .order_by(CaseGenerationV2Attempt.id.desc())
        .limit(1)
    )


def _case_generation_v2_recovery_actions(
    db: Session,
    job: CaseGenerationV2Job,
    current_user: User,
) -> list[schemas.CaseGenerationV2RecoveryAction]:
    parent_attempt_id = _case_generation_v2_parent_attempt_id(db, job)
    attempt_filter = (
        CaseGenerationV2Artifact.attempt_id.is_(None)
        if parent_attempt_id is None
        else CaseGenerationV2Artifact.attempt_id == parent_attempt_id
    )
    artifacts = list(
        db.scalars(
            select(CaseGenerationV2Artifact)
            .where(
                CaseGenerationV2Artifact.job_id == job.id,
                attempt_filter,
                CaseGenerationV2Artifact.expired_at.is_(None),
            )
            .order_by(CaseGenerationV2Artifact.id.asc())
        ).all()
    )
    artifacts_by_type = {artifact.artifact_type: artifact for artifact in artifacts}

    source_gate: dict[str, str] = {}
    gate_payload_keys = {
        "scope_index_gate": "scope_index_gate",
        "requirement_handoff": "requirement_gate",
        "testcase_handoff": "testcase_gate",
        "final_delivery_gate": "final_delivery_gate",
    }
    for artifact_type, payload_key in gate_payload_keys.items():
        artifact = artifacts_by_type.get(artifact_type)
        content = artifact.content_json if artifact is not None else None
        if not isinstance(content, dict):
            continue
        gate_payload = content.get(payload_key, content)
        if not isinstance(gate_payload, dict):
            continue
        recovery_plan = gate_payload.get("recovery_plan")
        rerun_scope = recovery_plan.get("rerun_scope") if isinstance(recovery_plan, dict) else None
        source_ids = rerun_scope.get("source_ids") if isinstance(rerun_scope, dict) else None
        valid_source_ids = source_ids if isinstance(source_ids, list) else []
        for source_id in valid_source_ids:
            normalized_id = str(source_id or "").strip()
            if normalized_id:
                source_gate.setdefault(normalized_id, artifact_type)

    review_artifact = artifacts_by_type.get("trusted_review_report")
    review_content = review_artifact.content_json if review_artifact is not None else None
    review_sources = review_content.get("sources_detail") if isinstance(review_content, dict) else None
    if isinstance(review_sources, list):
        for source in review_sources:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("source_id") or "").strip()
            has_issues = bool(
                source.get("shard_error")
                or source.get("gate_issues")
                or source.get("shard_status") == "failed"
                or source.get("must_cover_status") in {"gap", "missing", "blocked"}
                or source.get("method_consumption_status") in {"gap", "missing", "blocked"}
            )
            if source_id and has_issues:
                source_gate.setdefault(source_id, "trusted_review_report")

    testcase_artifact = artifacts_by_type.get("testcase_package")
    testcase_content = testcase_artifact.content_json if testcase_artifact is not None else None
    testcase_shards = testcase_content.get("testcase_shards") if isinstance(testcase_content, dict) else None
    testcase_shards = testcase_shards if isinstance(testcase_shards, list) else []
    package_source_ids = {
        str(item.get("source_id") or "").strip()
        for item in (testcase_shards or [])
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    }

    try:
        trusted_mode = _normalize_pipeline_mode((job.input_payload_json or {}).get("pipeline_mode")) == "trusted"
    except (AttributeError, TypeError, ValueError):
        trusted_mode = False

    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    reason = None
    if current_user.role not in {"admin", "tester"}:
        reason = "需要测试执行权限"
    elif job.status in {"PENDING", "RUNNING"}:
        reason = "任务正在执行，暂不可重跑"
    elif active_job is not None and active_job.id != job.id:
        reason = f"当前已有进行中的 V2 任务 #{active_job.id}"
    elif model_config is None or not model_config.api_key:
        reason = "当前工作空间未配置可用模型"

    available_types = set(artifacts_by_type)
    progress = job.progress_json if isinstance(job.progress_json, dict) else {}
    failed_stage = next(
        (
            str(stage.get("key") or "").strip()
            for stage in reversed(progress.get("stages") or [])
            if isinstance(stage, dict) and stage.get("status") == "failed"
        ),
        "",
    )
    reusable_shards = bool(
        testcase_shards
        and all(
            isinstance(item, dict)
            and item.get("status") == "success"
            and item.get("testcases")
            for item in testcase_shards
        )
    )
    can_resume_at_testcase_gate = trusted_mode and (
        (
            failed_stage == "testcase_gate"
            and {"scope_index", "requirement_handoff", "testcase_base_package"}.issubset(available_types)
        )
        or (
            failed_stage == "testcase_by_source_shard"
            and reusable_shards
            and {"scope_index", "requirement_handoff", "testcase_package"}.issubset(available_types)
        )
    )
    inherited_types = sorted(available_types & _INHERITABLE_CASE_GENERATION_V2_ARTIFACT_TYPES)
    failed_gate_artifact = {
        "scope_index": "scope_index_gate",
        "scope_index_gate": "scope_index_gate",
        "requirement": "requirement_handoff",
        "requirement_gate": "requirement_handoff",
        "testcase": "testcase_handoff",
        "testcase_gate": "testcase_handoff",
        "testcase_by_source_shard": "testcase_handoff",
        "final_delivery_gate": "final_delivery_gate",
        "export": "final_delivery_gate",
    }.get(failed_stage)
    actions = [
        schemas.CaseGenerationV2RecoveryAction(
            action="rerun_job",
            label="重跑任务",
            enabled=reason is None,
            reason=reason,
            preserves=inherited_types if can_resume_at_testcase_gate else [],
            regenerates=(
                ["testcase_package", "testcase_handoff", "trusted_review_report", "markdown", "xmindmark", "xmind"]
                if can_resume_at_testcase_gate
                else ["全流程产物"]
            ),
            calls_model=True,
            gate_artifact_type=failed_gate_artifact,
        )
    ]

    if trusted_mode and package_source_ids:
        for source_id in sorted(source_gate.keys() & package_source_ids):
            actions.append(
                schemas.CaseGenerationV2RecoveryAction(
                    action="rerun_source",
                    label=f"重跑 {source_id}",
                    enabled=reason is None,
                    reason=reason,
                    preserves=[
                        artifact_type
                        for artifact_type in ("source_manifest", "evidence_trace", "scope_index", "requirement_handoff")
                        if artifact_type in available_types
                    ],
                    regenerates=["该 source 的 testcase shard", "testcase_package", "门禁、复核与导出产物"],
                    calls_model=True,
                    source_id=source_id,
                    gate_artifact_type=source_gate[source_id],
                )
            )
    return actions


def _inherit_case_generation_v2_artifacts(
    db: Session,
    *,
    job_id: int,
    attempt_id: int,
    parent_attempt_id: int | None,
) -> None:
    """Copy only data artifacts from the explicitly selected parent attempt."""
    inherited_dir = Path(attempt_output_dir(job_id, "v2", attempt_id)) / "inherited"
    artifact_stmt = select(CaseGenerationV2Artifact).where(
        CaseGenerationV2Artifact.job_id == job_id,
        CaseGenerationV2Artifact.artifact_type.in_(_INHERITABLE_CASE_GENERATION_V2_ARTIFACT_TYPES),
        CaseGenerationV2Artifact.expired_at.is_(None),
    )
    if parent_attempt_id is None:
        artifact_stmt = artifact_stmt.where(CaseGenerationV2Artifact.attempt_id.is_(None))
    else:
        artifact_stmt = artifact_stmt.where(CaseGenerationV2Artifact.attempt_id == parent_attempt_id)
    prior_artifacts = list(db.scalars(artifact_stmt.order_by(CaseGenerationV2Artifact.id.desc())).all())
    seen_types: set[str] = set()
    for artifact in prior_artifacts:
        if artifact.artifact_type in seen_types:
            continue
        seen_types.add(artifact.artifact_type)
        inherited_path = artifact.file_path
        if inherited_path and os.path.isfile(inherited_path) and not os.path.islink(inherited_path):
            inherited_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(artifact.file_name or inherited_path).name
            target_path = inherited_dir / f"{artifact.id}_{safe_name}"
            # Bind mounts on Docker Desktop can map file ownership to the host
            # user. Copying metadata with copy2 then fails at copystat even
            # though the container can create and write the target file.
            shutil.copyfile(inherited_path, target_path)
            inherited_path = str(target_path)
        db.add(
            CaseGenerationV2Artifact(
                job_id=job_id,
                attempt_id=attempt_id,
                parent_attempt_id=artifact.attempt_id,
                artifact_type=artifact.artifact_type,
                file_name=artifact.file_name,
                file_path=inherited_path,
                content_json=artifact.content_json,
                revision=artifact.revision or artifact_revision(
                    content_json=artifact.content_json,
                    file_name=artifact.file_name,
                    file_path=inherited_path,
                ),
            )
        )
    db.commit()


def _find_active_case_generation_job_for_user(db: Session, user_id: int) -> CaseGenerationJob | None:
    jobs = list(
        db.scalars(
            select(CaseGenerationJob)
            .where(CaseGenerationJob.created_by == user_id, CaseGenerationJob.status.in_(["PENDING", "RUNNING"]))
            .order_by(CaseGenerationJob.id.desc())
        ).all()
    )
    return jobs[0] if jobs else None


def _find_active_case_generation_v2_job_for_user(db: Session, user_id: int) -> CaseGenerationV2Job | None:
    jobs = list(
        db.scalars(
            select(CaseGenerationV2Job)
            .where(CaseGenerationV2Job.created_by == user_id, CaseGenerationV2Job.status.in_(["PENDING", "RUNNING"]))
            .order_by(CaseGenerationV2Job.id.desc())
        ).all()
    )
    return jobs[0] if jobs else None


def _serialize_ai_model_config(config: AIModelConfig) -> schemas.AIModelConfigRead:
    payload = schemas.AIModelConfigRead.model_validate(config).model_dump()
    payload["api_key"] = "***已配置***" if config.api_key else None
    return schemas.AIModelConfigRead(**payload)


def _generation_metrics_for_job(db: Session, job, *, pipeline_version: str) -> dict | None:
    attempt_cls = CaseGenerationV2Attempt if pipeline_version == "v2" else CaseGenerationAttempt
    artifact_cls = CaseGenerationV2Artifact if pipeline_version == "v2" else CaseGenerationArtifact
    attempt = db.get(attempt_cls, job.active_attempt_id) if job.active_attempt_id else None
    if attempt is None:
        attempt = db.scalar(
            select(attempt_cls)
            .where(attempt_cls.job_id == job.id)
            .order_by(attempt_cls.id.desc())
        )
    artifact_stmt = select(artifact_cls).where(artifact_cls.job_id == job.id)
    if attempt is not None:
        artifact_stmt = artifact_stmt.where(artifact_cls.attempt_id == attempt.id)
    artifacts = list(db.scalars(artifact_stmt.order_by(artifact_cls.id.asc())).all())
    if not artifacts and attempt is not None:
        artifacts = list(
            db.scalars(
                select(artifact_cls)
                .where(artifact_cls.job_id == job.id)
                .order_by(artifact_cls.id.asc())
            ).all()
        )
    metrics_artifact = next(
        (
            item
            for item in reversed(artifacts)
            if item.artifact_type == "generation_metrics" and isinstance(item.content_json, dict)
        ),
        None,
    )
    if metrics_artifact is not None:
        return dict(metrics_artifact.content_json)
    if attempt is None:
        return None
    trace = next(
        (
            item.content_json
            for item in reversed(artifacts)
            if item.artifact_type == "model_call_trace" and isinstance(item.content_json, dict)
        ),
        {},
    )
    return build_generation_metrics(
        job=job,
        attempt=attempt,
        artifacts=artifacts,
        model_calls=list((trace or {}).get("calls") or []),
        pipeline_version=pipeline_version,
        status=attempt.status or job.status,
    )


def _import_generated_artifacts_to_project(
    db: Session,
    *,
    project: Project,
    current_user: User,
    testcase_package: dict | None,
    function_points: dict | list | None,
    payload: schemas.CaseGenerationImportRequest,
) -> schemas.BatchActionResult:
    folder_base = (payload.folder_path or "/AI生成").strip()
    if not folder_base.startswith("/"):
        folder_base = "/" + folder_base
    import_type = (payload.import_type or "AUTO").upper()
    created_count = 0

    if import_type == "REQUIREMENT":
        fp_items = []
        if isinstance(function_points, dict):
            fp_items = function_points.get("function_points") or function_points.get("items") or []
        elif isinstance(function_points, list):
            fp_items = function_points
        selected = set(payload.selected_indices) if payload.selected_indices is not None else None
        for idx, fp in enumerate(fp_items):
            if selected is not None and idx not in selected:
                continue
            if not isinstance(fp, dict):
                continue
            title = str(fp.get("title") or fp.get("name") or fp.get("point_name") or f"AI提取功能点-{idx + 1}")[:200]
            desc = str(fp.get("description") or fp.get("summary") or fp.get("rules") or "")
            req = Requirement(
                project_id=project.id,
                title=title,
                description=desc or None,
                status="PLANNING",
                priority=str(fp.get("priority") or "P1") if str(fp.get("priority") or "P1") in {"P0", "P1", "P2", "P3"} else "P1",
                type="FEATURE",
                folder_path=folder_base,
                created_by=current_user.id,
                updated_by=current_user.id,
                reporter_id=current_user.id,
            )
            db.add(req)
            created_count += 1
        db.commit()
        return schemas.BatchActionResult(
            success=True,
            affected_count=created_count,
            message=f"已成功导入 {created_count} 条需求功能点至需求池",
        )

    raw_cases: list[dict] = []
    if isinstance(testcase_package, dict):
        if isinstance(testcase_package.get("testcases"), list):
            raw_cases.extend(testcase_package["testcases"])
        elif isinstance(testcase_package.get("cases"), list):
            raw_cases.extend(testcase_package["cases"])
        if isinstance(testcase_package.get("testcase_shards"), list):
            for shard in testcase_package["testcase_shards"]:
                if isinstance(shard, dict) and isinstance(shard.get("testcases"), list):
                    raw_cases.extend(shard["testcases"])
        if not raw_cases and isinstance(testcase_package.get("modules"), list):
            for mod in testcase_package["modules"]:
                if isinstance(mod, dict) and isinstance(mod.get("testcases"), list):
                    for tc in mod["testcases"]:
                        if isinstance(tc, dict):
                            raw_cases.append({**tc, "module": tc.get("module") or mod.get("name")})

    if not raw_cases:
        raise HTTPException(status_code=400, detail="当前生成任务未包含可导入的结构化用例数据")

    selected = set(payload.selected_indices) if payload.selected_indices is not None else None
    target_base_url = (payload.base_url or project.base_url or "http://testserver").strip()

    for idx, tc in enumerate(raw_cases):
        if selected is not None and idx not in selected:
            continue
        if not isinstance(tc, dict):
            continue
        title = str(tc.get("title") or tc.get("name") or tc.get("case_title") or f"AI生成用例-{idx + 1}")[:120]
        module_name = str(tc.get("module") or tc.get("category") or tc.get("feature") or "").strip().strip("/")
        folder = f"{folder_base.rstrip('/')}/{module_name}" if module_name else folder_base
        priority_raw = str(tc.get("priority") or "P2").upper()
        priority = priority_raw if priority_raw in {"P0", "P1", "P2", "P3"} else "P2"
        steps_raw = tc.get("steps") or tc.get("test_steps") or []
        expected_raw = tc.get("expected_result") or tc.get("expected") or tc.get("expectation") or "验证通过"
        if isinstance(expected_raw, list):
            expected_text = "；".join(str(x) for x in expected_raw if x)[:255] or "验证通过"
        else:
            expected_text = str(expected_raw)[:255] or "验证通过"

        effective_type = import_type
        if effective_type == "AUTO":
            text_blob = f"{title} {module_name} {json.dumps(steps_raw, ensure_ascii=False)}".lower()
            if any(k in text_blob for k in ("api", "接口", "http", "post ", "get ", "put ", "delete ", "/api/")):
                effective_type = "API"
            else:
                effective_type = "UI"

        if effective_type == "API":
            method = str(tc.get("method") or "GET").upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                method = "GET"
            path = str(tc.get("path") or tc.get("url") or "/api/v1/system/health")
            if not path.startswith("/") and not path.startswith("http"):
                path = "/" + path
            case = APICase(
                project_id=project.id,
                name=title,
                folder_path=folder[:255],
                method=method,
                path=path,
                priority=priority,
                status="ACTIVE",
                review_status="DRAFT",
                version_no="1.0.0",
                tags_json=["AI生成"],
                expected_status=200,
                assertions_json=[{"type": "status_code", "operator": "eq", "expected": 200}],
                created_by=current_user.id,
                updated_by=current_user.id,
            )
            db.add(case)
            db.flush()
            cases_domain._record_case_history(db, case_type="API", case=case, action="IMPORT", changed_by=current_user.id, summary="从 AI 用例生成任务导入")
        else:
            ui_steps = [{"action": "goto", "value": target_url if (target_url := str(tc.get("target_url") or target_base_url)).startswith("http") else target_base_url, "name": "打开目标页面"}]
            if isinstance(steps_raw, list):
                for s_idx, step_item in enumerate(steps_raw[:15]):
                    step_desc = step_item.get("action") or step_item.get("step") or step_item.get("description") if isinstance(step_item, dict) else str(step_item)
                    step_desc = str(step_desc or f"步骤 {s_idx + 1}").strip()
                    if step_desc:
                        ui_steps.append({"action": "wait", "duration_ms": 500, "name": step_desc[:120]})
            case = UICase(
                project_id=project.id,
                name=title,
                folder_path=folder[:255],
                target_url=target_base_url,
                priority=priority,
                status="ACTIVE",
                review_status="DRAFT",
                version_no="1.0.0",
                tags_json=["AI生成"],
                steps_json=ui_steps,
                expect_text=expected_text,
                generation_mode="ai_skill",
                execution_mode="adaptive",
                engine="native",
                ai_goal=f"{title}：{expected_text}",
                created_by=current_user.id,
                updated_by=current_user.id,
            )
            db.add(case)
            db.flush()
            cases_domain._record_case_history(db, case_type="UI", case=case, action="IMPORT", changed_by=current_user.id, summary="从 AI 用例生成任务导入")
        created_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=created_count,
        message=f"已成功将 {created_count} 条 AI 生成用例导入项目资产库",
    )
