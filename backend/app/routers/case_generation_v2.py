"""AI 用例生成 V2（可信流水线）路由。"""

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.artifact_revision import artifact_revision, revision_from_bytes
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models import (
    AIModelConfig,
    CaseGenerationJob,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
    CaseGenerationV2Job,
    Project,
    User,
)
from app.tasks.case_generation import (
    _normalize_model_base_url,
    normalize_model_api_key,
    sanitize_case_generation_payload,
    validate_model_connection_config,
)
from app.tasks.case_generation_v2 import (
    _normalize_pipeline_mode,
    rerun_case_generation_v2_source_shard,
    run_case_generation_v2_job,
)
from app.tasks.case_generation_runtime import create_attempt, set_attempt_task_id
from app.tasks.case_generation_v2_support.metrics import compare_generation_metrics
from app.timeutil import utc_now_naive
from app.deps import auth as auth_deps
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    get_current_user,
    require_tester,
)
from app.domain.case_generation import (
    _case_generation_artifact_media_type,
    _case_generation_v2_parent_attempt_id,
    _case_generation_v2_recovery_actions,
    _find_active_case_generation_v2_job_for_user,
    _generation_metrics_for_job,
    _import_generated_artifacts_to_project,
    _inherit_case_generation_v2_artifacts,
    _serialize_case_generation_v2_artifact,
    _serialize_case_generation_v2_job,
)

router = APIRouter(tags=["case-generation-v2"])


@router.get("/case-generation-v2/jobs", response_model=list[schemas.CaseGenerationV2JobRead], summary="获取 V2 用例生成任务列表")
def list_case_generation_v2_jobs(
    project_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    pipeline_mode: str | None = Query(default=None, pattern="^(clone|trusted_v2|lite|trusted)$"),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseGenerationV2JobRead]:
    stmt = select(CaseGenerationV2Job).order_by(CaseGenerationV2Job.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(CaseGenerationV2Job.status == status.strip().upper())
    if mode:
        stmt = stmt.where(CaseGenerationV2Job.mode == mode.strip().upper())
    if pipeline_mode:
        normalized_pipeline_mode = _normalize_pipeline_mode(pipeline_mode)
        accepted_modes = ["lite", "clone"] if normalized_pipeline_mode == "lite" else ["trusted", "trusted_v2"]
        stmt = stmt.where(
            CaseGenerationV2Job.input_payload_json["pipeline_mode"].as_string().in_(accepted_modes)
        )
    if created_after:
        stmt = stmt.where(CaseGenerationV2Job.created_at >= created_after)
    if created_before:
        stmt = stmt.where(CaseGenerationV2Job.created_at < created_before)
    if before_id:
        stmt = stmt.where(CaseGenerationV2Job.id < before_id)
    if project_id is not None:
        project = db.get(Project, project_id)
        _require_project_access(db, current_user, project)
        stmt = stmt.where(CaseGenerationV2Job.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(CaseGenerationV2Job.project_id.in_(project_ids))
    return [_serialize_case_generation_v2_job(item) for item in db.scalars(stmt).all()]


@router.post(
    "/case-generation-v2/jobs",
    response_model=schemas.CaseGenerationV2JobRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建 V2 用例生成任务",
)
def create_case_generation_v2_job(
    payload: schemas.CaseGenerationV2JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    project = _require_project_access(db, current_user, db.get(Project, payload.project_id))
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    if active_job is not None:
        raise HTTPException(status_code=400, detail=f"你已有进行中的 V2 生成任务 #{active_job.id}，请先等待结束或手动停止")
    source_url = (payload.source_url or "").strip() or None
    markdown_text = (payload.markdown_text or "").strip() or None
    if not markdown_text and not source_url:
        raise HTTPException(status_code=400, detail="请提供需求文本、上传文件或需求文档链接")
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == project.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    direct_api_key = normalize_model_api_key(payload.openai_api_key)
    if (model_config is None or not model_config.api_key) and direct_api_key:
        normalized_base_url, normalized_model = validate_model_connection_config("gpt-5.5", None, direct_api_key)
        model_config = AIModelConfig(
            workspace_id=project.workspace_id,
            provider="OPENAI",
            name="V2 任务提交临时模型配置",
            base_url=normalized_base_url,
            model=normalized_model,
            api_key=direct_api_key,
            is_active=1,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(model_config)
        db.commit()
        db.refresh(model_config)
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="请先配置该工作空间的模型连接信息")
    effective_model = (payload.openai_model or model_config.model or "").strip()
    try:
        effective_base_url, effective_model = validate_model_connection_config(
            effective_model, payload.openai_base_url or model_config.base_url, model_config.api_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    input_payload = sanitize_case_generation_payload(payload.model_dump()) | {
        "source_url": source_url,
        "markdown_text": markdown_text,
        "workspace_id": project.workspace_id,
        "pipeline": "case-generation-v2",
        "pipeline_mode": payload.pipeline_mode or "lite",
        "model_config_id": model_config.id,
        "model_provider": payload.model_provider or model_config.provider,
        "openai_model": effective_model,
        "openai_base_url": effective_base_url,
        "model_config_snapshot": {
            "provider": payload.model_provider or model_config.provider,
            "model": effective_model,
            "base_url": effective_base_url,
            "model_config_id": model_config.id,
        },
    }
    job = CaseGenerationV2Job(
        workspace_id=project.workspace_id,
        project_id=project.id,
        name=payload.name,
        mode=payload.mode,
        status="PENDING",
        source_document_name=payload.source_document_name,
        progress_json={"stages": []},
        input_payload_json=input_payload,
        summary="V2 任务已提交，等待生成",
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v2")

    try:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
            run_case_generation_v2_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "V2 任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "V2 任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"V2 任务已提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@router.get("/case-generation-v2/jobs/{job_id}", response_model=schemas.CaseGenerationV2JobDetail, summary="获取 V2 用例生成任务详情")
def get_case_generation_v2_job(
    job_id: int,
    include_content: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobDetail:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact_stmt = select(CaseGenerationV2Artifact).where(CaseGenerationV2Artifact.job_id == job.id)
    if job.active_attempt_id is not None:
        artifact_stmt = artifact_stmt.where(CaseGenerationV2Artifact.attempt_id == job.active_attempt_id)
    artifacts = list(db.scalars(artifact_stmt.order_by(CaseGenerationV2Artifact.id.asc())).all())
    attempts = list(
        db.scalars(
            select(CaseGenerationV2Attempt)
            .where(CaseGenerationV2Attempt.job_id == job.id)
            .order_by(CaseGenerationV2Attempt.id.desc())
            .limit(20)
        ).all()
    )
    return schemas.CaseGenerationV2JobDetail(
        job=_serialize_case_generation_v2_job(job),
        artifacts=[_serialize_case_generation_v2_artifact(item, include_content=include_content) for item in artifacts],
        attempts=[schemas.CaseGenerationV2AttemptRead.model_validate(item) for item in attempts],
        recovery_actions=_case_generation_v2_recovery_actions(db, job, current_user),
    )


@router.get(
    "/case-generation-v2/jobs/{job_id}/metrics-comparison",
    response_model=schemas.CaseGenerationMetricsComparison,
    summary="对比 V2 任务运行指标",
)
def compare_case_generation_v2_metrics(
    job_id: int,
    baseline_job_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationMetricsComparison:
    candidate_job = db.get(CaseGenerationV2Job, job_id)
    if candidate_job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, candidate_job.project_id))
    if baseline_job_id is not None:
        baseline_job = db.get(CaseGenerationJob, baseline_job_id)
        if baseline_job is None:
            raise HTTPException(status_code=404, detail="V1 基线任务不存在")
        _require_project_access(db, current_user, db.get(Project, baseline_job.project_id))
    else:
        baseline_stmt = (
            select(CaseGenerationJob)
            .where(
                CaseGenerationJob.project_id == candidate_job.project_id,
                CaseGenerationJob.status.in_(["SUCCESS", "CONDITIONAL"]),
            )
            .order_by(CaseGenerationJob.id.desc())
        )
        if candidate_job.source_document_name:
            same_document = db.scalar(
                baseline_stmt.where(CaseGenerationJob.source_document_name == candidate_job.source_document_name)
            )
            baseline_job = same_document or db.scalar(baseline_stmt)
        else:
            baseline_job = db.scalar(baseline_stmt)
    comparison = compare_generation_metrics(
        _generation_metrics_for_job(db, baseline_job, pipeline_version="v1") if baseline_job else None,
        _generation_metrics_for_job(db, candidate_job, pipeline_version="v2"),
    )
    return schemas.CaseGenerationMetricsComparison(
        baseline_job_id=baseline_job.id if baseline_job else None,
        candidate_job_id=candidate_job.id,
        **comparison,
    )


@router.post(
    "/case-generation-v2/jobs/{job_id}/rerun",
    response_model=schemas.CaseGenerationV2JobRead,
    dependencies=[Depends(require_tester)],
    summary="重跑 V2 用例生成任务",
)
def rerun_case_generation_v2_job_api(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    if active_job is not None and active_job.id != job.id:
        raise HTTPException(status_code=400, detail=f"你已有进行中的 V2 生成任务 #{active_job.id}，请先等待结束或手动停止")
    if job.status in {"PENDING", "RUNNING"}:
        return _serialize_case_generation_v2_job(job)
    previous_progress = dict(job.progress_json or {})
    parent_attempt_id = _case_generation_v2_parent_attempt_id(db, job)
    failed_stage = next(
        (
            str(stage.get("key") or "").strip()
            for stage in reversed(previous_progress.get("stages") or [])
            if isinstance(stage, dict) and stage.get("status") == "failed"
        ),
        "",
    )
    payload = dict(job.input_payload_json or {})
    try:
        normalized_pipeline_mode = _normalize_pipeline_mode(payload.get("pipeline_mode"))
    except ValueError:
        normalized_pipeline_mode = "lite"
    parent_artifact_filter = (
        CaseGenerationV2Artifact.attempt_id.is_(None)
        if parent_attempt_id is None
        else CaseGenerationV2Artifact.attempt_id == parent_attempt_id
    )
    available_artifact_types = set(
        db.scalars(
            select(CaseGenerationV2Artifact.artifact_type).where(
                CaseGenerationV2Artifact.job_id == job.id,
                parent_artifact_filter,
                CaseGenerationV2Artifact.expired_at.is_(None),
            )
        ).all()
    )
    latest_testcase_artifact = db.scalar(
        select(CaseGenerationV2Artifact)
        .where(
            CaseGenerationV2Artifact.job_id == job.id,
            parent_artifact_filter,
            CaseGenerationV2Artifact.artifact_type == "testcase_package",
            CaseGenerationV2Artifact.expired_at.is_(None),
        )
        .order_by(CaseGenerationV2Artifact.id.desc())
    )
    testcase_shards = (
        (latest_testcase_artifact.content_json or {}).get("testcase_shards") or []
        if latest_testcase_artifact is not None and isinstance(latest_testcase_artifact.content_json, dict)
        else []
    )
    has_reusable_trusted_package = bool(
        testcase_shards
        and all(
            isinstance(item, dict)
            and item.get("status") == "success"
            and item.get("testcases")
            for item in testcase_shards
        )
    )
    resume_from_testcase_gate = (
        normalized_pipeline_mode == "trusted"
        and (
            (
                failed_stage == "testcase_gate"
                and {"scope_index", "requirement_handoff", "testcase_base_package"}.issubset(available_artifact_types)
            )
            or (
                failed_stage == "testcase_by_source_shard"
                and has_reusable_trusted_package
                and {"scope_index", "requirement_handoff", "testcase_package"}.issubset(available_artifact_types)
            )
        )
    )
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="当前工作空间未配置可用模型，无法重跑")
    payload["pipeline_mode"] = payload.get("pipeline_mode") or "lite"
    if resume_from_testcase_gate:
        payload["trusted_resume_from_stage"] = "testcase_gate"
    else:
        payload.pop("trusted_resume_from_stage", None)
    payload["model_config_id"] = model_config.id
    payload["openai_model"] = model_config.model
    payload["openai_base_url"] = _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key)
    payload["model_config_snapshot"] = {
        "provider": model_config.provider,
        "model": model_config.model,
        "base_url": payload["openai_base_url"],
        "model_config_id": model_config.id,
    }
    job.input_payload_json = payload
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v2")
    if resume_from_testcase_gate:
        _inherit_case_generation_v2_artifacts(
            db,
            job_id=job.id,
            attempt_id=attempt.id,
            parent_attempt_id=parent_attempt_id,
        )
    job.summary = "V2 任务将复用已有基线，从用例门禁继续" if resume_from_testcase_gate else "V2 任务重新提交，等待生成"
    attempt.summary = job.summary
    if resume_from_testcase_gate:
        attempt.progress_json = previous_progress
        job.progress_json = previous_progress
    db.commit()

    try:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
            run_case_generation_v2_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "V2 任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "V2 任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"V2 任务重新提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@router.post(
    "/case-generation-v2/jobs/{job_id}/cancel",
    response_model=schemas.CaseGenerationV2JobRead,
    dependencies=[Depends(require_tester)],
    summary="取消 V2 用例生成任务",
)
def cancel_case_generation_v2_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    if job.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="只能停止自己创建的 V2 生成任务")
    if job.status not in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="当前状态不允许停止")
    if job.task_id:
        celery_app.control.revoke(job.task_id, terminate=True, signal="SIGTERM")
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    if stages:
        stages[-1]["status"] = "failed"
        stages[-1]["summary"] = "V2 任务已手动停止"
        progress["stages"] = stages
        job.progress_json = progress
    job.status = "CANCELLED"
    job.task_id = None
    job.summary = "V2 生成已取消"
    job.error_message = "任务已手动停止"
    job.finished_at = utc_now_naive()
    if job.active_attempt_id:
        attempt = db.get(CaseGenerationV2Attempt, job.active_attempt_id)
        if attempt is not None:
            attempt.status = "CANCELLED"
            attempt.task_id = None
            attempt.summary = job.summary
            attempt.error_message = job.error_message
            attempt.progress_json = progress
            attempt.finished_at = job.finished_at
    db.commit()
    db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@router.post(
    "/case-generation-v2/jobs/{job_id}/shards/{source_id}/rerun",
    response_model=schemas.CaseGenerationV2JobRead,
    dependencies=[Depends(require_tester)],
    summary="重跑 V2 指定 Source 分片",
)
def rerun_case_generation_v2_source_shard_api(
    job_id: int,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    payload = dict(job.input_payload_json or {})
    try:
        normalized_pipeline_mode = _normalize_pipeline_mode(payload.get("pipeline_mode"))
    except ValueError:
        normalized_pipeline_mode = "lite"
    if normalized_pipeline_mode != "trusted":
        raise HTTPException(status_code=400, detail="只有可信模式任务支持 source shard 重跑")
    if job.status in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="任务正在执行中，不能重跑单个 source shard")
    parent_attempt_id = _case_generation_v2_parent_attempt_id(db, job)
    parent_artifact_filter = (
        CaseGenerationV2Artifact.attempt_id.is_(None)
        if parent_attempt_id is None
        else CaseGenerationV2Artifact.attempt_id == parent_attempt_id
    )
    artifact = db.scalar(
        select(CaseGenerationV2Artifact).where(
            CaseGenerationV2Artifact.job_id == job.id,
            parent_artifact_filter,
            CaseGenerationV2Artifact.artifact_type == "testcase_package",
            CaseGenerationV2Artifact.expired_at.is_(None),
        ).order_by(CaseGenerationV2Artifact.id.desc()).limit(1)
    )
    if artifact is None or not isinstance(artifact.content_json, dict):
        raise HTTPException(status_code=400, detail="缺少 testcase_package，无法重跑 source shard")
    shard_ids = {
        str(item.get("source_id") or "").strip()
        for item in artifact.content_json.get("testcase_shards") or []
        if isinstance(item, dict)
    }
    if source_id not in shard_ids:
        raise HTTPException(status_code=404, detail=f"未找到 source shard：{source_id}")
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    if active_job is not None and active_job.id != job.id:
        raise HTTPException(status_code=400, detail=f"你已有进行中的 V2 生成任务 #{active_job.id}，请先等待结束或手动停止")

    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="当前工作空间未配置可用模型，无法重跑 source shard")
    payload["pipeline_mode"] = payload.get("pipeline_mode") or "trusted"
    payload["model_config_id"] = model_config.id
    payload["openai_model"] = model_config.model
    payload["openai_base_url"] = _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key)
    job.input_payload_json = payload
    db.commit()
    db.refresh(job)
    attempt = create_attempt(
        db,
        job,
        pipeline_version="v2",
        kind="source_shard",
        source_id=source_id,
    )
    _inherit_case_generation_v2_artifacts(
        db,
        job_id=job.id,
        attempt_id=attempt.id,
        parent_attempt_id=parent_attempt_id,
    )
    job.summary = f"{source_id} source shard 重跑已提交"
    attempt.summary = job.summary
    db.commit()

    try:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
            rerun_case_generation_v2_source_shard,
            job.id,
            source_id,
            attempt.id,
            background_inline=True,
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = f"{source_id} source shard 派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = attempt.summary
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"{source_id} source shard 重跑已提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@router.get("/case-generation-v2/jobs/{job_id}/artifacts/{artifact_id}/download", summary="下载 V2 生成产物文件")
def download_case_generation_v2_artifact(
    job_id: int,
    artifact_id: int,
    revision: str | None = Query(default=None, min_length=64, max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationV2Artifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="V2 生成产物不存在")
    if not artifact.file_path or not os.path.exists(artifact.file_path):
        raise HTTPException(status_code=404, detail="V2 生成产物文件不存在")
    try:
        artifact_bytes = Path(artifact.file_path).read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="V2 生成产物文件无法读取") from exc
    file_name = artifact.file_name or os.path.basename(artifact.file_path)
    file_revision = revision_from_bytes(file_name, artifact_bytes)
    current_revision = artifact.revision or artifact_revision(
        content_json=artifact.content_json,
        file_name=file_name,
        file_path=artifact.file_path,
    )
    if revision and (revision != current_revision or revision != file_revision):
        raise HTTPException(status_code=409, detail="产物内容已更新，请刷新详情后重新下载")

    return Response(
        content=artifact_bytes,
        media_type=_case_generation_artifact_media_type(artifact.artifact_type),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get(
    "/case-generation-v2/jobs/{job_id}/artifacts/{artifact_id}",
    response_model=schemas.CaseGenerationV2ArtifactRead,
    summary="查看 V2 生成产物内容",
)
def get_case_generation_v2_artifact_content(
    job_id: int,
    artifact_id: int,
    revision: str | None = Query(default=None, min_length=64, max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2ArtifactRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationV2Artifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="V2 生成产物不存在")
    current_revision = artifact.revision or artifact_revision(
        content_json=artifact.content_json,
        file_name=artifact.file_name,
        file_path=artifact.file_path,
    )
    if revision and revision != current_revision:
        raise HTTPException(status_code=409, detail="产物内容已更新，请刷新详情后重新加载")
    return _serialize_case_generation_v2_artifact(artifact, include_content=True)


@router.post(
    "/case-generation-v2/jobs/{job_id}/import-cases",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="将 V2 生成结果导入平台用例库",
)
def import_case_generation_v2_job_to_cases(
    job_id: int,
    payload: schemas.CaseGenerationImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    project = _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifacts = list(
        db.scalars(
            select(CaseGenerationV2Artifact)
            .where(CaseGenerationV2Artifact.job_id == job.id)
            .order_by(CaseGenerationV2Artifact.id.desc())
        ).all()
    )
    tc_pkg = next(
        (
            a.content_json
            for a in artifacts
            if a.artifact_type in {"testcase_package", "testcase_base_package"} and a.content_json
        ),
        None,
    )
    fp_pkg = next(
        (
            a.content_json
            for a in artifacts
            if a.artifact_type in {"function_points", "requirement_handoff"} and a.content_json
        ),
        None,
    )
    return _import_generated_artifacts_to_project(
        db,
        project=project,
        current_user=current_user,
        testcase_package=tc_pkg if isinstance(tc_pkg, dict) else None,
        function_points=fp_pkg,
        payload=payload,
    )
