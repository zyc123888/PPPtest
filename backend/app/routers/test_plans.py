"""测试计划管理、用例编排与定时调度路由。"""

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.database import get_db
from app.models import (
    APICase,
    Environment,
    PerformanceCase,
    Project,
    TestPlan,
    TestPlanCase,
    TestPlanRun,
    TestRun,
    UICase,
    User,
)
from app.tasks.executions import run_test_plan, select_queue_for_case_types
from app.timeutil import utc_now_naive
from app.deps import auth as auth_deps
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_project_member,
    get_current_user,
    require_admin,
    require_tester,
)
from app.domain import cases as cases_domain
from app.domain.cases import _load_case_entity, _validate_plan_case_review_gate
from app.domain.precheck import _raise_precheck_failure
from app.domain import precheck as precheck_domain

router = APIRouter(tags=["test-plans"])


@router.get("/test-plans", response_model=list[schemas.TestPlanRead], summary="获取测试计划列表")
def list_test_plans(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestPlan]:
    stmt = select(TestPlan).order_by(TestPlan.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(TestPlan.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(TestPlan.project_id.in_(project_ids))
    return list(db.scalars(stmt).all())


@router.post(
    "/test-plans",
    response_model=schemas.TestPlanRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建测试计划",
)
def create_test_plan(
    payload: schemas.TestPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    plan = TestPlan(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.put(
    "/test-plans/{plan_id}",
    response_model=schemas.TestPlanRead,
    dependencies=[Depends(require_tester)],
    summary="更新测试计划",
)
def update_test_plan(
    plan_id: int,
    payload: schemas.TestPlanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    plan.name = payload.name
    plan.description = payload.description
    plan.updated_by = current_user.id
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/test-plans/{plan_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除测试计划")
def delete_test_plan(plan_id: int, db: Session = Depends(get_db)) -> None:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    plan_run_ids = list(db.scalars(select(TestPlanRun.id).where(TestPlanRun.plan_id == plan_id)).all())
    if plan_run_ids:
        db.execute(delete(TestRun).where(TestRun.plan_run_id.in_(plan_run_ids)))
        db.execute(delete(TestPlanRun).where(TestPlanRun.id.in_(plan_run_ids)))

    db.execute(delete(TestPlanCase).where(TestPlanCase.plan_id == plan_id))
    db.delete(plan)
    db.commit()


@router.get("/test-plans/{plan_id}", response_model=schemas.TestPlanRead, summary="获取测试计划详情")
def get_test_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    return plan


@router.get("/test-plans/{plan_id}/cases", response_model=list[schemas.TestPlanCaseRead], summary="获取测试计划关联用例列表")
def list_test_plan_cases(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestPlanCase]:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    return list(
        db.scalars(
            select(TestPlanCase).where(TestPlanCase.plan_id == plan_id).order_by(TestPlanCase.order_index.asc())
        ).all()
    )


@router.post(
    "/test-plans/{plan_id}/cases",
    response_model=schemas.TestPlanCaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="向测试计划添加单个用例",
)
def add_test_plan_case(
    plan_id: int,
    payload: schemas.TestPlanCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlanCase:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))

    if payload.case_type == "API":
        case = db.get(APICase, payload.case_id)
    elif payload.case_type == "PERF":
        case = db.get(PerformanceCase, payload.case_id)
    else:
        case = db.get(UICase, payload.case_id)

    if case is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    if case.project_id != plan.project_id:
        raise HTTPException(status_code=400, detail="用例不属于该测试计划项目")
    _require_project_access(db, current_user, db.get(Project, case.project_id))
    _validate_plan_case_review_gate(case, current_user, payload.allow_unapproved)

    plan_case = TestPlanCase(
        plan_id=plan.id,
        case_type=payload.case_type,
        case_id=payload.case_id,
        case_name=case.name,
        case_snapshot_json=cases_domain._case_snapshot(case),
        order_index=payload.order_index,
        created_by=current_user.id,
    )
    db.add(plan_case)
    db.commit()
    db.refresh(plan_case)
    return plan_case


@router.post(
    "/test-plans/{plan_id}/cases/copy-to-review",
    response_model=schemas.TestPlanRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="复制计划中待评审风险用例到新计划",
)
def copy_plan_cases_to_review(
    plan_id: int,
    payload: schemas.PlanCopyToReviewPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    source = db.get(TestPlan, plan_id)
    if source is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, source.project_id))
    if len(set(payload.item_ids)) != len(payload.item_ids):
        raise HTTPException(status_code=400, detail="计划用例存在重复")
    entries = list(db.scalars(select(TestPlanCase).where(TestPlanCase.plan_id == plan_id, TestPlanCase.id.in_(payload.item_ids))).all())
    if len(entries) != len(payload.item_ids):
        raise HTTPException(status_code=404, detail="部分计划用例不存在或不属于来源计划")
    by_id = {entry.id: entry for entry in entries}
    cases = []
    seen = set()
    for item_id in payload.item_ids:
        entry = by_id[item_id]
        key = (entry.case_type.upper(), entry.case_id)
        if key in seen:
            raise HTTPException(status_code=400, detail="来源计划包含重复用例")
        seen.add(key)
        case = _load_case_entity(db, *key)
        if case is None or case.project_id != source.project_id:
            raise HTTPException(status_code=404, detail="部分来源用例不存在或项目不匹配")
        _validate_plan_case_review_gate(case, current_user, True)
        cases.append((key, case))
    plan = TestPlan(project_id=source.project_id, name=f"{source.name[:95]}-待评审-{utc_now_naive():%Y-%m-%d}",
                    description=f"从计划「{source.name}」复制的待评审风险用例，使用当前用例版本快照",
                    created_by=current_user.id, updated_by=current_user.id)
    db.add(plan)
    db.flush()
    for index, ((case_type, case_id), case) in enumerate(cases, start=1):
        db.add(TestPlanCase(plan_id=plan.id, case_type=case_type, case_id=case_id, case_name=case.name,
                            case_snapshot_json=cases_domain._case_snapshot(case), order_index=index, created_by=current_user.id))
    db.commit()
    db.refresh(plan)
    return plan


@router.post(
    "/test-plans/{plan_id}/cases/batch",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量向测试计划添加用例",
)
def add_plan_cases_batch(
    plan_id: int,
    payload: schemas.CaseBatchPlanPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))

    existing_cases = list(
        db.scalars(select(TestPlanCase).where(TestPlanCase.plan_id == plan_id).order_by(TestPlanCase.order_index.asc(), TestPlanCase.id.asc())).all()
    )
    next_order = max([item.order_index for item in existing_cases], default=0)
    affected_count = 0

    for offset, item in enumerate(payload.items):
        case = _load_case_entity(db, item.case_type, item.case_id)
        if case is None or case.project_id != plan.project_id:
            continue
        _validate_plan_case_review_gate(case, current_user, payload.allow_unapproved)
        existing = db.scalar(
            select(TestPlanCase).where(
                TestPlanCase.plan_id == plan_id,
                TestPlanCase.case_type == item.case_type.upper(),
                TestPlanCase.case_id == item.case_id,
            )
        )
        if existing is not None:
            continue
        order_index = max(payload.order_start + offset, next_order + 1)
        next_order = order_index
        db.add(
            TestPlanCase(
                plan_id=plan_id,
                case_type=item.case_type.upper(),
                case_id=item.case_id,
                case_name=case.name,
                case_snapshot_json=cases_domain._case_snapshot(case),
                order_index=order_index,
                created_by=current_user.id,
            )
        )
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已加入 {affected_count} 条计划用例",
    )


@router.delete(
    "/test-plans/{plan_id}/cases/{plan_case_id}",
    status_code=204,
    dependencies=[Depends(require_tester)],
    summary="从测试计划移除单个用例",
)
def delete_test_plan_case(
    plan_id: int,
    plan_case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    plan_case = db.get(TestPlanCase, plan_case_id)
    if plan_case is None or plan_case.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="计划用例不存在")
    db.delete(plan_case)
    db.commit()


@router.post(
    "/test-plans/{plan_id}/cases/batch-delete",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量从测试计划移除用例",
)
def batch_delete_test_plan_cases(
    plan_id: int,
    payload: schemas.TestPlanCaseBatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    ids = list(dict.fromkeys(payload.plan_case_ids))
    result = db.execute(
        delete(TestPlanCase).where(TestPlanCase.plan_id == plan_id, TestPlanCase.id.in_(ids))
    )
    db.commit()
    affected = result.rowcount or 0
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected,
        message=f"已从计划移除 {affected} 条用例",
    )


@router.post(
    "/test-plans/{plan_id}/cases/reorder",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="调整测试计划用例执行顺序",
)
def reorder_test_plan_cases(
    plan_id: int,
    payload: schemas.TestPlanCaseReorderPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    if not payload.items:
        raise HTTPException(status_code=400, detail="排序项不能为空")

    requested_ids = [item.id for item in payload.items]
    unique_ids = set(requested_ids)
    if len(unique_ids) != len(requested_ids):
        raise HTTPException(status_code=400, detail="排序项存在重复")

    plan_cases = list(
        db.scalars(select(TestPlanCase).where(TestPlanCase.plan_id == plan_id)).all()
    )
    plan_case_map = {item.id: item for item in plan_cases}

    if not unique_ids.issubset(plan_case_map.keys()):
        raise HTTPException(status_code=400, detail="排序项包含无效计划用例")

    affected_count = 0
    for item in payload.items:
        plan_case = plan_case_map[item.id]
        if plan_case.order_index != item.order_index:
            plan_case.order_index = item.order_index
            affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已更新 {affected_count} 条计划用例顺序",
    )


@router.post(
    "/test-plans/{plan_id}/run",
    response_model=schemas.TestPlanRunRead,
    dependencies=[Depends(require_tester)],
    summary="触发执行测试计划",
)
def trigger_test_plan(
    plan_id: int,
    payload: schemas.TestPlanRunCreate | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlanRun:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_member(db, current_user, db.get(Project, plan.project_id))

    cases = list(
        db.scalars(
            select(TestPlanCase)
            .where(TestPlanCase.plan_id == plan_id)
            .order_by(TestPlanCase.order_index.asc(), TestPlanCase.id.asc())
        ).all()
    )
    if not cases:
        raise HTTPException(status_code=400, detail="测试计划未配置用例")

    environment_id = payload.environment_id if payload else None
    timeout_seconds = payload.timeout_seconds if payload else None
    max_retries = payload.max_retries if payload else 0
    concurrency = payload.concurrency if payload else 1
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != plan.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_domain.precheck_plan(
            plan.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    plan_run = services.create_plan_run_with_cases(
        db,
        plan,
        environment_id=environment_id,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )

    target_queue = select_queue_for_case_types(item.case_type for item in cases)
    dispatch_kwargs = {"queue": target_queue} if target_queue else {}
    try:
        task_id, ran_inline = auth_deps._dispatch_task_or_run_inline(
            run_test_plan, plan_run.id, concurrency, context_user_id=current_user.id, **dispatch_kwargs
        )
    except HTTPException as exc:
        now = utc_now_naive()
        plan_run.status = "FAILED"
        plan_run.error_type = "SYSTEM"
        plan_run.summary = f"任务派发失败：{exc.detail}"[:255]
        plan_run.finished_at = now
        db.execute(
            update(TestRun)
            .where(TestRun.plan_run_id == plan_run.id, TestRun.status == "PENDING")
            .values(status="FAILED", error_type="SYSTEM", summary="测试计划派发失败", finished_at=now)
        )
        db.commit()
        raise
    if ran_inline:
        db.refresh(plan_run)
    else:
        plan_run.summary = f"任务已提交，执行中（task_id={task_id}）"
        db.commit()
        db.refresh(plan_run)
    return plan_run


@router.put(
    "/test-plans/{plan_id}/schedule",
    response_model=schemas.TestPlanRead,
    dependencies=[Depends(require_tester)],
    summary="配置测试计划定时 Cron 调度",
)
def update_test_plan_schedule(
    plan_id: int,
    payload: schemas.TestPlanScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_member(db, current_user, db.get(Project, plan.project_id))

    if payload.schedule_enabled:
        if payload.schedule_environment_id is not None:
            env = db.get(Environment, payload.schedule_environment_id)
            if env is None or env.project_id != plan.project_id:
                raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
        plan.schedule_enabled = True
        plan.schedule_cron = payload.schedule_cron
        plan.schedule_environment_id = payload.schedule_environment_id
        plan.schedule_timeout_seconds = payload.schedule_timeout_seconds
        plan.schedule_max_retries = payload.schedule_max_retries
        plan.next_run_at = services.compute_next_run_at(payload.schedule_cron)
    else:
        plan.schedule_enabled = False
        plan.schedule_cron = None
        plan.schedule_environment_id = None
        plan.schedule_timeout_seconds = None
        plan.schedule_max_retries = 0
        plan.next_run_at = None
    plan.updated_by = current_user.id
    db.commit()
    db.refresh(plan)
    return plan
