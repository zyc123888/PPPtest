"""测试环境管理与执行前变量预检路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import schemas
from app.core.database import get_db
from app.models import (
    Environment,
    Project,
    TestPlan,
    TestPlanRun,
    TestRun,
    User,
)
from app.permissions import project_role_allows
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_project_member,
    _resolve_project_role,
    get_current_user,
    require_admin,
    require_tester,
)
from app.domain.precheck import (
    _build_validation_result_for_environment,
    _serialize_environment_variables,
    precheck_api_case,
    precheck_performance_case,
    precheck_plan,
    precheck_ui_case,
)

router = APIRouter(tags=["environments"])


@router.get("/environments", response_model=list[schemas.EnvironmentRead], summary="获取项目测试环境列表")
def list_environments(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.EnvironmentRead]:
    stmt = select(Environment).order_by(Environment.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(Environment.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(Environment.project_id.in_(project_ids))
    result = []
    roles = {}
    for env in db.scalars(stmt):
        if env.project_id not in roles:
            roles[env.project_id] = _resolve_project_role(db, current_user, db.get(Project, env.project_id))
        if project_role_allows(roles[env.project_id], "manager"):
            result.append(schemas.EnvironmentRead.model_validate(env))
        else:
            result.append(schemas.EnvironmentRead(
                id=env.id, project_id=env.project_id, name=env.name, base_url=env.base_url,
                created_by=env.created_by, updated_by=env.updated_by,
                created_at=env.created_at, updated_at=env.updated_at,
            ))
    return result


@router.post(
    "/environments",
    response_model=schemas.EnvironmentRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建测试环境",
)
def create_environment(
    payload: schemas.EnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Environment:
    _require_project_member(db, current_user, db.get(Project, payload.project_id), "manager")

    env = Environment(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(env)
    db.commit()
    db.refresh(env)
    return env


@router.put(
    "/environments/{environment_id}",
    response_model=schemas.EnvironmentRead,
    dependencies=[Depends(require_tester)],
    summary="更新测试环境",
)
def update_environment(
    environment_id: int,
    payload: schemas.EnvironmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Environment:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_member(db, current_user, db.get(Project, env.project_id), "manager")

    env.name = payload.name
    env.base_url = payload.base_url
    env.headers_json = payload.headers_json
    env.variables_json = payload.variables_json
    env.auth_config_json = payload.auth_config_json
    env.updated_by = current_user.id
    db.commit()
    db.refresh(env)
    return env


@router.delete("/environments/{environment_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除测试环境")
def delete_environment(environment_id: int, db: Session = Depends(get_db)) -> None:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    scheduled_plan = db.scalar(select(TestPlan.id).where(TestPlan.schedule_environment_id == environment_id).limit(1))
    if scheduled_plan is not None:
        raise HTTPException(status_code=409, detail="请先修改引用该环境的定时计划")

    db.execute(update(TestRun).where(TestRun.environment_id == environment_id).values(environment_id=None))
    db.execute(
        update(TestPlanRun).where(TestPlanRun.environment_id == environment_id).values(environment_id=None)
    )
    db.delete(env)
    db.commit()


@router.get("/environments/{environment_id}/variables", response_model=schemas.EnvironmentVariablesUpdate, summary="获取环境变量与鉴权配置")
def get_environment_variables(
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentVariablesUpdate:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_member(db, current_user, db.get(Project, env.project_id), "manager")
    return _serialize_environment_variables(env)


@router.get("/environments/{environment_id}/validate", response_model=schemas.EnvironmentValidationResult, summary="校验环境对项目用例的变量覆盖")
def validate_environment(
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentValidationResult:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_access(db, current_user, db.get(Project, env.project_id))
    return _build_validation_result_for_environment(db, env)


@router.get("/executions/api/{case_id}/precheck", response_model=schemas.ExecutionPrecheckResult, summary="API 用例执行前变量预检")
def precheck_api_case_execution(
    case_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    return precheck_api_case(case_id, db=db, current_user=current_user, environment_id=environment_id)


@router.get("/executions/ui/{case_id}/precheck", response_model=schemas.ExecutionPrecheckResult, summary="UI 用例执行前变量预检")
def precheck_ui_case_execution(
    case_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    return precheck_ui_case(case_id, db=db, current_user=current_user, environment_id=environment_id)


@router.get("/executions/perf/{case_id}/precheck", response_model=schemas.ExecutionPrecheckResult, summary="性能用例执行前变量预检")
def precheck_performance_case_execution(
    case_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    return precheck_performance_case(case_id, db=db, current_user=current_user, environment_id=environment_id)


@router.get("/test-plans/{plan_id}/precheck", response_model=schemas.ExecutionPrecheckResult, summary="测试计划执行前变量预检")
def precheck_plan_execution(
    plan_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    return precheck_plan(plan_id, db=db, current_user=current_user, environment_id=environment_id)


@router.post(
    "/environments/validate-draft",
    response_model=schemas.EnvironmentValidationResult,
    dependencies=[Depends(require_tester)],
    summary="校验未保存的环境草稿配置",
)
def validate_environment_draft(
    payload: schemas.EnvironmentValidationDraft,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentValidationResult:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    draft_env = Environment(
        id=0,
        project_id=payload.project_id,
        name=payload.name,
        base_url=payload.base_url,
        headers_json=payload.headers_json,
        variables_json=payload.variables_json,
        auth_config_json=payload.auth_config_json,
    )
    return _build_validation_result_for_environment(db, draft_env)


@router.put(
    "/environments/{environment_id}/variables",
    response_model=schemas.EnvironmentVariablesUpdate,
    dependencies=[Depends(require_tester)],
    summary="更新环境变量与鉴权配置",
)
def update_environment_variables(
    environment_id: int,
    payload: schemas.EnvironmentVariablesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentVariablesUpdate:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_member(db, current_user, db.get(Project, env.project_id), "manager")
    env.variables_json = payload.variables_json
    env.headers_json = payload.headers_json
    env.auth_config_json = payload.auth_config_json
    env.updated_by = current_user.id
    db.commit()
    db.refresh(env)
    return _serialize_environment_variables(env)
