"""用例执行、批量执行、SSE 实时流与执行记录路由。"""

import asyncio
import json
import os

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models import (
    APICase,
    Environment,
    ExecutionArtifact,
    ExecutionLog,
    ExecutionStep,
    PerformanceCase,
    Project,
    TestRun,
    UIBatchRun,
    UICase,
    User,
)
from app.execution_runtime import build_variable_context
from app.tasks.executions import (
    run_api_case,
    run_performance_case,
    run_ui_batch,
    run_ui_case,
    select_queue_for_case_types,
)
from app.timeutil import utc_now_naive
from app.deps import auth as auth_deps
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_project_member,
    get_current_user,
    require_tester,
)
from app.domain.precheck import (
    _build_execution_precheck_result,
    _raise_precheck_failure,
    _validation_issues_for_api_case,
    _validation_issues_for_environment_runtime,
    _validation_issues_for_performance_case,
    _validation_issues_for_ui_case,
)
from app.domain import precheck as precheck_domain

router = APIRouter(tags=["executions"])


def _trigger_batch_run(
    case_type: str,
    payload: schemas.UIBatchRunCreate,
    db: Session,
    current_user: User,
) -> UIBatchRun:
    if case_type == "API":
        case_model = APICase
        precheck_fn = precheck_domain.precheck_api_case
    elif case_type == "PERF":
        case_model = PerformanceCase
        precheck_fn = precheck_domain.precheck_performance_case
    else:
        case_model = UICase
        precheck_fn = precheck_domain.precheck_ui_case
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(case_model).where(case_model.id.in_(case_ids))).all())
    case_map = {case.id: case for case in cases}
    missing = [case_id for case_id in case_ids if case_id not in case_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"用例不存在: {', '.join(str(item) for item in missing)}")
    project_ids = {case.project_id for case in cases}
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="批量执行的用例必须属于同一项目")
    project = _require_project_member(db, current_user, db.get(Project, project_ids.pop()))
    inactive = [case.name for case in cases if (case.status or "ACTIVE").upper() != "ACTIVE"]
    if inactive:
        raise HTTPException(status_code=400, detail=f"以下用例未启用：{', '.join(inactive)}")
    if payload.environment_id is not None:
        env = db.get(Environment, payload.environment_id)
        if env is None or env.project_id != project.id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    for case_id in case_ids:
        _raise_precheck_failure(
            precheck_fn(
                case_id,
                environment_id=payload.environment_id,
                db=db,
                current_user=current_user,
            )
        )

    batch_run = UIBatchRun(
        project_id=project.id,
        environment_id=payload.environment_id,
        case_type=case_type,
        status="PENDING",
        summary="任务已提交，等待执行",
        total_count=len(case_ids),
        created_by=current_user.id,
    )
    db.add(batch_run)
    db.commit()
    db.refresh(batch_run)

    for case_id in case_ids:
        case = case_map[case_id]
        services.create_test_run(
            db,
            project_id=project.id,
            environment_id=payload.environment_id,
            batch_run_id=batch_run.id,
            case_type=case_type,
            case_id=case.id,
            case_name=case.name,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )

    target_queue = select_queue_for_case_types([case_type])
    dispatch_kwargs = {"queue": target_queue} if target_queue else {}
    task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
        run_ui_batch, batch_run.id, **dispatch_kwargs
    )
    if ran_inline:
        db.refresh(batch_run)
    else:
        batch_run.summary = f"任务已提交，执行中（task_id={task_id}）"
        db.commit()
        db.refresh(batch_run)
    return batch_run


@router.post(
    "/executions/ui/batch-run",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="触发 UI 用例批量执行",
)
def trigger_ui_batch_run(
    payload: schemas.UIBatchRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _trigger_batch_run("UI", payload, db, current_user)


@router.post(
    "/executions/api/batch-run",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="触发 API 用例批量执行",
)
def trigger_api_batch_run(
    payload: schemas.UIBatchRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _trigger_batch_run("API", payload, db, current_user)


def _list_batch_runs(
    case_type: str,
    project_id: int | None,
    limit: int,
    db: Session,
    current_user: User,
) -> list[UIBatchRun]:
    stmt = select(UIBatchRun)
    if case_type == "UI":
        stmt = stmt.where(or_(UIBatchRun.case_type == "UI", UIBatchRun.case_type.is_(None)))
    else:
        stmt = stmt.where(UIBatchRun.case_type == case_type)
    if project_id is not None:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(UIBatchRun.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(UIBatchRun.project_id.in_(project_ids))
    stmt = stmt.order_by(UIBatchRun.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


@router.get("/executions/ui/batch-runs", response_model=list[schemas.UIBatchRunRead], summary="获取 UI 批量执行记录")
def list_ui_batch_runs(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UIBatchRun]:
    return _list_batch_runs("UI", project_id, limit, db, current_user)


@router.get("/executions/api/batch-runs", response_model=list[schemas.UIBatchRunRead], summary="获取 API 批量执行记录")
def list_api_batch_runs(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UIBatchRun]:
    return _list_batch_runs("API", project_id, limit, db, current_user)


def _get_batch_run_detail(
    batch_id: int,
    db: Session,
    current_user: User,
) -> schemas.UIBatchRunDetail:
    batch_run = db.get(UIBatchRun, batch_id)
    if batch_run is None:
        raise HTTPException(status_code=404, detail="批量执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, batch_run.project_id))
    runs = list(
        db.scalars(
            select(TestRun).where(TestRun.batch_run_id == batch_run.id).order_by(TestRun.id.asc())
        ).all()
    )
    detail = schemas.UIBatchRunDetail.model_validate(batch_run)
    detail.runs = [schemas.TestRunRead.model_validate(run) for run in runs]
    return detail


@router.get("/executions/ui/batch-runs/{batch_id}", response_model=schemas.UIBatchRunDetail, summary="获取 UI 批量执行详情")
def get_ui_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UIBatchRunDetail:
    return _get_batch_run_detail(batch_id, db, current_user)


@router.get("/executions/api/batch-runs/{batch_id}", response_model=schemas.UIBatchRunDetail, summary="获取 API 批量执行详情")
def get_api_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UIBatchRunDetail:
    return _get_batch_run_detail(batch_id, db, current_user)


def _rerun_failed_batch_run(
    batch_id: int,
    db: Session,
    current_user: User,
) -> UIBatchRun:
    batch_run = db.get(UIBatchRun, batch_id)
    if batch_run is None:
        raise HTTPException(status_code=404, detail="批量执行记录不存在")
    _require_project_member(db, current_user, db.get(Project, batch_run.project_id))
    if batch_run.status in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="批量执行尚未结束")
    failed_runs = list(
        db.scalars(
            select(TestRun)
            .where(TestRun.batch_run_id == batch_run.id, TestRun.status != "SUCCESS")
            .order_by(TestRun.id.asc())
        ).all()
    )
    failed_case_ids = list(dict.fromkeys(run.case_id for run in failed_runs))
    if not failed_case_ids:
        raise HTTPException(status_code=400, detail="没有失败的用例可重跑")
    return _trigger_batch_run(
        (batch_run.case_type or "UI").upper(),
        schemas.UIBatchRunCreate(
            case_ids=failed_case_ids,
            environment_id=batch_run.environment_id,
            timeout_seconds=failed_runs[0].timeout_seconds,
            max_retries=failed_runs[0].max_retries or 0,
        ),
        db=db,
        current_user=current_user,
    )


@router.post(
    "/executions/ui/batch-runs/{batch_id}/rerun-failed",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="重跑 UI 批量执行中的失败用例",
)
def rerun_failed_ui_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _rerun_failed_batch_run(batch_id, db, current_user)


@router.post(
    "/executions/api/batch-runs/{batch_id}/rerun-failed",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="重跑 API 批量执行中的失败用例",
)
def rerun_failed_api_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _rerun_failed_batch_run(batch_id, db, current_user)


@router.post(
    "/executions/perf/batch-run",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="触发性能用例批量执行",
)
def trigger_perf_batch_run(
    payload: schemas.UIBatchRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _trigger_batch_run("PERF", payload, db, current_user)


@router.get("/executions/perf/batch-runs", response_model=list[schemas.UIBatchRunRead], summary="获取性能批量执行记录")
def list_perf_batch_runs(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UIBatchRun]:
    return _list_batch_runs("PERF", project_id, limit, db, current_user)


@router.get("/executions/perf/batch-runs/{batch_id}", response_model=schemas.UIBatchRunDetail, summary="获取性能批量执行详情")
def get_perf_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UIBatchRunDetail:
    return _get_batch_run_detail(batch_id, db, current_user)


@router.post(
    "/executions/perf/batch-runs/{batch_id}/rerun-failed",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="重跑性能批量执行中的失败用例",
)
def rerun_failed_perf_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _rerun_failed_batch_run(batch_id, db, current_user)


@router.get("/executions/runs", response_model=schemas.TestRunPage | list[schemas.TestRunRead], summary="分页/过滤查询执行记录")
def list_runs(
    project_id: int | None = None,
    case_type: str | None = None,
    case_id: int | None = None,
    status: str | None = None,
    error_type: str | None = None,
    keyword: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.TestRunPage | list[TestRun]:
    normalized_case_type = (case_type or "").strip().upper()
    if normalized_case_type and normalized_case_type not in {"API", "UI", "PERF"}:
        raise HTTPException(status_code=400, detail="不支持的用例类型")
    normalized_status = (status or "").strip().upper()
    if normalized_status and normalized_status not in {
        "PENDING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
        "ERROR",
        "TIMEOUT",
        "CANCELLED",
    }:
        raise HTTPException(status_code=400, detail="不支持的执行状态")

    base_conditions = []
    if project_id is not None:
        _require_project_access(db, current_user, db.get(Project, project_id))
        base_conditions.append(TestRun.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.TestRunPage(items=[], total=0) if page is not None else []
        base_conditions.append(TestRun.project_id.in_(project_ids))
    if normalized_case_type:
        base_conditions.append(TestRun.case_type == normalized_case_type)
    if case_id is not None:
        base_conditions.append(TestRun.case_id == case_id)

    filter_conditions = list(base_conditions)
    if normalized_status:
        filter_conditions.append(TestRun.status == normalized_status)
    if error_type and error_type.strip():
        filter_conditions.append(TestRun.error_type == error_type.strip().upper())
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filter_conditions.append(or_(TestRun.case_name.like(pattern), TestRun.summary.like(pattern)))

    stmt = select(TestRun).where(*filter_conditions).order_by(TestRun.id.desc())
    if page is None:
        return list(db.scalars(stmt.limit(limit)).all())

    total = db.scalar(select(func.count()).select_from(TestRun).where(*filter_conditions)) or 0
    items = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
    status_counts = dict(
        db.execute(
            select(TestRun.status, func.count()).where(*base_conditions).group_by(TestRun.status)
        ).all()
    )
    failed = sum(status_counts.get(key, 0) for key in ("FAILED", "ERROR", "TIMEOUT"))
    return schemas.TestRunPage(
        items=[schemas.TestRunRead.model_validate(item) for item in items],
        total=total,
        running=status_counts.get("RUNNING", 0) + status_counts.get("PENDING", 0),
        failed=failed,
        retryable=failed + status_counts.get("CANCELLED", 0),
    )


@router.get("/executions/runs/latest", response_model=list[schemas.TestRunRead], summary="批量查询各用例最新执行记录")
def list_latest_runs(
    case_type: str = Query(...),
    case_ids: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestRun]:
    normalized_case_type = case_type.strip().upper()
    if normalized_case_type not in {"API", "UI", "PERF"}:
        raise HTTPException(status_code=400, detail="不支持的用例类型")
    try:
        ids = [int(item) for item in case_ids.split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="case_ids 格式不正确") from exc
    ids = list(dict.fromkeys(ids))[:200]
    if not ids:
        return []
    conditions = [TestRun.case_type == normalized_case_type, TestRun.case_id.in_(ids)]
    if current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        conditions.append(TestRun.project_id.in_(project_ids))
    latest_ids = select(func.max(TestRun.id)).where(*conditions).group_by(TestRun.case_id)
    return list(db.scalars(select(TestRun).where(TestRun.id.in_(latest_ids))).all())


@router.get("/executions/runs/{run_id}", response_model=schemas.TestRunRead, summary="获取单条执行记录详情")
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    return run


@router.get("/executions/runs/{run_id}/logs", response_model=schemas.ExecutionLogRead, summary="获取执行标准输出与错误日志")
def get_run_logs(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionLogRead:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    logs = list(db.scalars(select(ExecutionLog).where(ExecutionLog.run_id == run.id)).all())
    steps = list(
        db.scalars(
            select(ExecutionStep)
            .where(ExecutionStep.run_id == run.id)
            .order_by(ExecutionStep.step_index)
        ).all()
    )
    stdout_text = next((item.content for item in logs if item.stream == "stdout"), run.stdout_text)
    stderr_text = next((item.content for item in logs if item.stream == "stderr"), run.stderr_text)
    step_results = [step.raw_json for step in steps if step.raw_json] or run.step_results_json
    return schemas.ExecutionLogRead(
        run_id=run.id,
        status=run.status,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        exit_code=run.exit_code,
        error_type=run.error_type,
        timeout_seconds=run.timeout_seconds,
        step_results_json=step_results,
    )


@router.get("/executions/runs/{run_id}/steps", response_model=list[schemas.ExecutionStepRead], summary="获取执行步骤明细")
def get_run_steps(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExecutionStep]:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    return list(
        db.scalars(
            select(ExecutionStep)
            .where(ExecutionStep.run_id == run.id)
            .order_by(ExecutionStep.step_index.asc(), ExecutionStep.id.asc())
        ).all()
    )


@router.get("/executions/runs/{run_id}/artifacts", response_model=schemas.ExecutionArtifactsRead, summary="获取执行产物列表")
def get_run_artifacts(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionArtifactsRead:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    artifacts = list(
        db.scalars(
            select(ExecutionArtifact)
            .where(ExecutionArtifact.run_id == run.id)
            .order_by(ExecutionArtifact.id)
        ).all()
    )
    payload = [
        artifact.meta_json
        or {
            "name": artifact.name,
            "path": artifact.path,
            "type": artifact.artifact_type,
        }
        for artifact in artifacts
    ] or (run.artifacts_json or [])
    return schemas.ExecutionArtifactsRead(run_id=run.id, artifacts=payload)


@router.get("/executions/runs/{run_id}/artifacts/{artifact_index}/download", summary="下载执行产物文件")
def download_run_artifact(
    run_id: int,
    artifact_index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))

    artifact_rows = list(
        db.scalars(
            select(ExecutionArtifact)
            .where(ExecutionArtifact.run_id == run.id)
            .order_by(ExecutionArtifact.id)
        ).all()
    )
    artifacts = [
        artifact.meta_json
        or {
            "name": artifact.name,
            "path": artifact.path,
            "type": artifact.artifact_type,
        }
        for artifact in artifact_rows
    ] or (run.artifacts_json or [])
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="执行产物不存在")

    artifact = artifacts[artifact_index]
    file_path = artifact.get("path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="执行产物文件不存在")

    media_type = "application/octet-stream"
    artifact_type = (artifact.get("type") or "").lower()
    if artifact_type == "json":
        media_type = "application/json"
    elif artifact_type in {"txt", "log"}:
        media_type = "text/plain; charset=utf-8"
    elif artifact_type == "png":
        media_type = "image/png"
    elif artifact_type in {"jpg", "jpeg"}:
        media_type = "image/jpeg"
    elif artifact_type == "html":
        media_type = "text/html; charset=utf-8"

    return FileResponse(path=file_path, media_type=media_type, filename=artifact.get("name") or os.path.basename(file_path))


@router.post(
    "/executions/runs/{run_id}/rerun",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
    summary="重跑单条执行记录",
)
def rerun_execution(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    project = _require_project_member(db, current_user, db.get(Project, run.project_id))
    environment = db.get(Environment, run.environment_id) if run.environment_id else None
    if environment is not None and environment.project_id != run.project_id:
        raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    variables = build_variable_context(project, environment)
    if run.case_type == "API":
        case = db.get(APICase, run.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="接口用例不存在")
        _raise_precheck_failure(
            _build_execution_precheck_result(
                target_type="API",
                target_id=case.id,
                project=project,
                environment=environment,
                issues=_validation_issues_for_environment_runtime(environment, project)
                + _validation_issues_for_api_case(case, variables),
            )
        )
    elif run.case_type == "UI":
        case = db.get(UICase, run.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="UI 用例不存在")
        _raise_precheck_failure(
            _build_execution_precheck_result(
                target_type="UI",
                target_id=case.id,
                project=project,
                environment=environment,
                issues=_validation_issues_for_environment_runtime(environment, project)
                + _validation_issues_for_ui_case(case, variables),
            )
        )
    elif run.case_type == "PERF":
        case = db.get(PerformanceCase, run.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="性能用例不存在")
        _raise_precheck_failure(
            _build_execution_precheck_result(
                target_type="PERF",
                target_id=case.id,
                project=project,
                environment=environment,
                issues=_validation_issues_for_environment_runtime(environment, project)
                + _validation_issues_for_performance_case(case, variables),
            )
        )

    rerun = services.create_test_run(
        db,
        project_id=run.project_id,
        environment_id=run.environment_id,
        plan_run_id=run.plan_run_id,
        case_type=run.case_type,
        case_id=run.case_id,
        case_name=run.case_name,
    )
    rerun.retry_count = (run.retry_count or 0) + 1
    rerun.max_retries = max(run.max_retries or 0, rerun.retry_count)
    db.commit()
    db.refresh(rerun)

    if rerun.case_type == "API":
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(run_api_case, rerun.id)
    elif rerun.case_type == "PERF":
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(run_performance_case, rerun.id)
    else:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(run_ui_case, rerun.id)
    if ran_inline:
        db.refresh(rerun)
    else:
        rerun.task_id = task_id
        rerun.summary = f"重跑任务已提交（来源执行 {run.id}）"
        db.commit()
        db.refresh(rerun)
    return rerun


@router.get("/executions/runs/{run_id}/stream", summary="SSE 实时订阅执行状态流")
async def stream_execution_run(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 实时推送执行状态与步骤进度，直到执行到达终态或客户端断开。"""
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))

    async def event_generator():
        from app.core.database import SessionLocal

        last_sig = None
        for _ in range(180):
            if await request.is_disconnected():
                break
            poll_db = SessionLocal()
            try:
                current = poll_db.get(TestRun, run_id)
                if current is None:
                    break
                payload = {
                    "id": current.id,
                    "status": current.status,
                    "summary": current.summary,
                    "error_type": current.error_type,
                    "duration_ms": current.duration_ms,
                    "step_count": len(current.step_results_json or []),
                    "finished_at": current.finished_at.isoformat() if current.finished_at else None,
                }
                sig = (payload["status"], payload["summary"], payload["step_count"])
                if sig != last_sig:
                    last_sig = sig
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if current.status in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"}:
                    break
            finally:
                poll_db.close()
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/executions/runs/{run_id}/cancel",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
    summary="取消进行中的执行任务",
)
def cancel_execution(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    if run.status in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="当前状态不允许取消")

    if run.task_id:
        celery_app.control.revoke(run.task_id, terminate=True)

    run.status = "CANCELLED"
    run.summary = "执行已取消"
    run.error_type = "CANCELLED"
    run.finished_at = utc_now_naive()
    db.commit()
    db.refresh(run)
    return run


@router.post(
    "/executions/runs/batch-cancel",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量取消执行任务",
)
def batch_cancel_executions(
    payload: schemas.ExecutionBatchActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    run_ids = list(dict.fromkeys(payload.run_ids))
    runs = list(db.scalars(select(TestRun).where(TestRun.id.in_(run_ids))).all())
    cancelled_count = 0
    for run in runs:
        _require_project_access(db, current_user, db.get(Project, run.project_id))
        if run.status in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"}:
            continue
        if run.task_id:
            celery_app.control.revoke(run.task_id, terminate=True)
        run.status = "CANCELLED"
        run.summary = "执行已批量取消"
        run.error_type = "CANCELLED"
        run.finished_at = utc_now_naive()
        cancelled_count += 1
    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=cancelled_count,
        message=f"已批量取消 {cancelled_count} 条进行中的执行记录",
    )


@router.post(
    "/executions/runs/batch-rerun",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量重跑执行记录",
)
def batch_rerun_executions(
    payload: schemas.ExecutionBatchActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    run_ids = list(dict.fromkeys(payload.run_ids))
    rerun_count = 0
    for rid in run_ids:
        try:
            rerun_execution(rid, db=db, current_user=current_user)
            rerun_count += 1
        except HTTPException:
            continue
    return schemas.BatchActionResult(
        success=True,
        affected_count=rerun_count,
        message=f"已批量重跑 {rerun_count} 条执行记录",
    )


@router.post(
    "/executions/api/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
    summary="触发单条 API 用例执行",
)
def trigger_api_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    _require_project_member(db, current_user, db.get(Project, api_case.project_id))

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != api_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_domain.precheck_api_case(
            api_case.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    run = services.create_test_run(
        db,
        project_id=api_case.project_id,
        environment_id=environment_id,
        case_type="API",
        case_id=api_case.id,
        case_name=api_case.name,
        timeout_seconds=payload.timeout_seconds if payload else None,
        max_retries=payload.max_retries if payload else 0,
    )
    db.commit()
    db.refresh(run)
    task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(run_api_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@router.post(
    "/executions/ui/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
    summary="触发单条 UI 用例执行",
)
def trigger_ui_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    _require_project_member(db, current_user, db.get(Project, ui_case.project_id))

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != ui_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_domain.precheck_ui_case(
            ui_case.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    run = services.create_test_run(
        db,
        project_id=ui_case.project_id,
        environment_id=environment_id,
        case_type="UI",
        case_id=ui_case.id,
        case_name=ui_case.name,
        timeout_seconds=payload.timeout_seconds if payload else None,
        max_retries=payload.max_retries if payload else 0,
    )
    db.commit()
    db.refresh(run)
    task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(run_ui_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@router.post(
    "/executions/perf/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
    summary="触发单条性能用例执行",
)
def trigger_performance_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    _require_project_member(db, current_user, db.get(Project, perf_case.project_id))

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != perf_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_domain.precheck_performance_case(
            perf_case.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    run = services.create_test_run(
        db,
        project_id=perf_case.project_id,
        environment_id=environment_id,
        case_type="PERF",
        case_id=perf_case.id,
        case_name=perf_case.name,
        timeout_seconds=payload.timeout_seconds if payload else None,
        max_retries=payload.max_retries if payload else 0,
    )
    db.commit()
    db.refresh(run)
    task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(run_performance_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run
