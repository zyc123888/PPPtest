"""AI 用例生成 V1 与模型配置路由。"""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models import (
    AIModelConfig,
    CaseGenerationArtifact,
    CaseGenerationAttempt,
    CaseGenerationJob,
    Project,
    User,
)
from app.model_registry import case_generation_model_options
from app.tasks.case_generation import (
    _normalize_model_base_url,
    normalize_model_api_key,
    run_case_generation_job,
    sanitize_case_generation_payload,
    validate_model_connection_config,
)
from app.tasks.case_generation_runtime import create_attempt, set_attempt_task_id
from app.timeutil import utc_now_naive
from app.deps import auth as auth_deps
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_workspace_access,
    get_current_user,
    require_tester,
)
from app.domain.case_generation import (
    _case_generation_artifact_media_type,
    _find_active_case_generation_job_for_user,
    _import_generated_artifacts_to_project,
    _serialize_ai_model_config,
    _serialize_case_generation_artifact,
    _serialize_case_generation_job,
)

router = APIRouter(tags=["case-generation"])


@router.get("/case-generation/jobs", response_model=list[schemas.CaseGenerationJobRead], summary="获取 V1 用例生成任务列表")
def list_case_generation_jobs(
    project_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseGenerationJobRead]:
    stmt = select(CaseGenerationJob).order_by(CaseGenerationJob.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(CaseGenerationJob.status == status.strip().upper())
    if mode:
        stmt = stmt.where(CaseGenerationJob.mode == mode.strip().upper())
    if created_after:
        stmt = stmt.where(CaseGenerationJob.created_at >= created_after)
    if created_before:
        stmt = stmt.where(CaseGenerationJob.created_at < created_before)
    if before_id:
        stmt = stmt.where(CaseGenerationJob.id < before_id)
    if project_id is not None:
        project = db.get(Project, project_id)
        _require_project_access(db, current_user, project)
        stmt = stmt.where(CaseGenerationJob.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(CaseGenerationJob.project_id.in_(project_ids))
    return [_serialize_case_generation_job(item) for item in db.scalars(stmt).all()]


@router.get("/case-generation/model-config", response_model=schemas.AIModelConfigRead | None, summary="获取工作空间 AI 模型配置")
def get_case_generation_model_config(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_workspace_access(db, current_user, workspace_id)
    config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if config is None:
        return None
    return _serialize_ai_model_config(config)


@router.get(
    "/case-generation/model-options",
    response_model=list[schemas.AIModelOptionRead],
    summary="获取内置支持的模型选项",
)
def list_case_generation_model_options(
    current_user: User = Depends(get_current_user),
) -> list[schemas.AIModelOptionRead]:
    del current_user
    return [schemas.AIModelOptionRead(**item) for item in case_generation_model_options()]


@router.post(
    "/case-generation/model-config",
    response_model=schemas.AIModelConfigRead,
    dependencies=[Depends(require_tester)],
    summary="保存或更新 AI 模型配置",
)
def upsert_case_generation_model_config(
    payload: schemas.AIModelConfigUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.AIModelConfigRead:
    _require_workspace_access(db, current_user, payload.workspace_id)
    try:
        normalized_base_url, normalized_model = validate_model_connection_config(payload.model, payload.base_url, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_api_key = normalize_model_api_key(payload.api_key)
    config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == payload.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if config is None:
        config = AIModelConfig(
            workspace_id=payload.workspace_id,
            provider=payload.provider,
            name=payload.name,
            base_url=normalized_base_url,
            model=normalized_model,
            api_key=normalized_api_key,
            is_active=1,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(config)
    else:
        config.provider = payload.provider
        config.name = payload.name
        config.base_url = normalized_base_url
        config.model = normalized_model
        config.api_key = normalized_api_key
        config.updated_by = current_user.id
    db.commit()
    db.refresh(config)
    return _serialize_ai_model_config(config)


@router.post(
    "/case-generation/jobs",
    response_model=schemas.CaseGenerationJobRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建 V1 用例生成任务",
)
def create_case_generation_job(
    payload: schemas.CaseGenerationJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobRead:
    project = _require_project_access(db, current_user, db.get(Project, payload.project_id))
    active_job = _find_active_case_generation_job_for_user(db, current_user.id)
    if active_job is not None:
        raise HTTPException(status_code=400, detail=f"你已有进行中的生成任务 #{active_job.id}，请先等待结束或手动停止")
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
            name="任务提交临时模型配置",
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
    input_payload = sanitize_case_generation_payload(payload.model_dump()) | {
        "source_url": source_url,
        "markdown_text": markdown_text,
        "workspace_id": project.workspace_id,
        "model_config_id": model_config.id,
        "openai_model": model_config.model,
        "openai_base_url": _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key),
        "model_config_snapshot": {
            "provider": model_config.provider,
            "model": model_config.model,
            "base_url": _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key),
            "model_config_id": model_config.id,
        },
    }
    job = CaseGenerationJob(
        workspace_id=project.workspace_id,
        project_id=project.id,
        name=payload.name,
        mode=payload.mode,
        status="PENDING",
        source_document_name=payload.source_document_name,
        progress_json={"stages": []},
        input_payload_json=input_payload,
        summary="任务已提交，等待生成",
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v1")

    try:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
            run_case_generation_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"任务已提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_job(job)


@router.get("/case-generation/jobs/{job_id}", response_model=schemas.CaseGenerationJobDetail, summary="获取 V1 用例生成任务详情")
def get_case_generation_job(
    job_id: int,
    include_content: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobDetail:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact_stmt = select(CaseGenerationArtifact).where(CaseGenerationArtifact.job_id == job.id)
    if job.active_attempt_id is not None:
        artifact_stmt = artifact_stmt.where(CaseGenerationArtifact.attempt_id == job.active_attempt_id)
    artifacts = list(db.scalars(artifact_stmt.order_by(CaseGenerationArtifact.id.asc())).all())
    attempts = list(
        db.scalars(
            select(CaseGenerationAttempt)
            .where(CaseGenerationAttempt.job_id == job.id)
            .order_by(CaseGenerationAttempt.id.desc())
            .limit(20)
        ).all()
    )
    return schemas.CaseGenerationJobDetail(
        job=_serialize_case_generation_job(job),
        artifacts=[_serialize_case_generation_artifact(item, include_content=include_content) for item in artifacts],
        attempts=[schemas.CaseGenerationAttemptRead.model_validate(item) for item in attempts],
    )


@router.post(
    "/case-generation/jobs/{job_id}/rerun",
    response_model=schemas.CaseGenerationJobRead,
    dependencies=[Depends(require_tester)],
    summary="重跑 V1 用例生成任务",
)
def rerun_case_generation_job_api(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobRead:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    active_job = _find_active_case_generation_job_for_user(db, current_user.id)
    if active_job is not None and active_job.id != job.id:
        raise HTTPException(status_code=400, detail=f"你已有进行中的生成任务 #{active_job.id}，请先等待结束或手动停止")

    if job.status in {"PENDING", "RUNNING"}:
        return _serialize_case_generation_job(job)
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="当前工作空间未配置可用模型，无法重跑")
    payload = dict(job.input_payload_json or {})
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
    attempt = create_attempt(db, job, pipeline_version="v1")
    job.summary = "任务重新提交，等待生成"
    attempt.summary = job.summary
    db.commit()

    try:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
            run_case_generation_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"任务重新提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_job(job)


@router.post(
    "/case-generation/jobs/{job_id}/cancel",
    response_model=schemas.CaseGenerationJobRead,
    dependencies=[Depends(require_tester)],
    summary="取消 V1 用例生成任务",
)
def cancel_case_generation_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobRead:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    if job.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="只能停止自己创建的生成任务")
    if job.status not in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="当前状态不允许停止")
    if job.task_id:
        celery_app.control.revoke(job.task_id, terminate=True, signal="SIGTERM")
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    if stages:
        stages[-1]["status"] = "failed"
        stages[-1]["summary"] = "任务已手动停止"
        progress["stages"] = stages
        job.progress_json = progress
    job.status = "CANCELLED"
    job.task_id = None
    job.summary = "生成已取消"
    job.error_message = "任务已手动停止"
    job.finished_at = utc_now_naive()
    if job.active_attempt_id:
        attempt = db.get(CaseGenerationAttempt, job.active_attempt_id)
        if attempt is not None:
            attempt.status = "CANCELLED"
            attempt.task_id = None
            attempt.summary = job.summary
            attempt.error_message = job.error_message
            attempt.progress_json = progress
            attempt.finished_at = job.finished_at
    db.commit()
    db.refresh(job)
    return _serialize_case_generation_job(job)


@router.get("/case-generation/jobs/{job_id}/artifacts/{artifact_id}/download", summary="下载 V1 生成产物文件")
def download_case_generation_artifact(
    job_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationArtifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="生成产物不存在")
    if not artifact.file_path or not os.path.exists(artifact.file_path):
        raise HTTPException(status_code=404, detail="生成产物文件不存在")

    return FileResponse(
        path=artifact.file_path,
        media_type=_case_generation_artifact_media_type(artifact.artifact_type),
        filename=artifact.file_name or os.path.basename(artifact.file_path),
    )


@router.get(
    "/case-generation/jobs/{job_id}/artifacts/{artifact_id}",
    response_model=schemas.CaseGenerationArtifactRead,
    summary="查看 V1 生成产物内容",
)
def get_case_generation_artifact_content(
    job_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationArtifactRead:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationArtifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="生成产物不存在")
    return _serialize_case_generation_artifact(artifact, include_content=True)


@router.post(
    "/case-generation/jobs/{job_id}/import-cases",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="将 V1 生成结果导入平台用例库",
)
def import_case_generation_job_to_cases(
    job_id: int,
    payload: schemas.CaseGenerationImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    project = _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifacts = list(
        db.scalars(
            select(CaseGenerationArtifact)
            .where(CaseGenerationArtifact.job_id == job.id)
            .order_by(CaseGenerationArtifact.id.desc())
        ).all()
    )
    tc_pkg = next((a.content_json for a in artifacts if a.artifact_type == "testcase_package" and a.content_json), None)
    fp_pkg = next((a.content_json for a in artifacts if a.artifact_type == "function_points" and a.content_json), None)
    return _import_generated_artifacts_to_project(
        db,
        project=project,
        current_user=current_user,
        testcase_package=tc_pkg if isinstance(tc_pkg, dict) else None,
        function_points=fp_pkg,
        payload=payload,
    )
