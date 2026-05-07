import json
import os
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    APICase,
    Environment,
    Project,
    TestPlan,
    TestPlanCase,
    TestPlanRun,
    TestRun,
    UICase,
    User,
    Workspace,
)
from app.tasks.executions import run_api_case, run_test_plan, run_ui_case
from app.timeutil import utc_now_naive


auth_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    user = services.get_user_by_token(db, credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def require_tester(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {"admin", "tester"}:
        raise HTTPException(status_code=403, detail="需要测试执行权限")
    return current_user


public_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])


def _dispatch_task_or_run_inline(task_func, record_id: int) -> tuple[str | None, bool]:
    try:
        task = task_func.delay(record_id)
        return task.id, False
    except Exception:
        task_func(record_id)
        return None, True


@public_router.get("/system/health", response_model=schemas.SystemHealth)
def system_health() -> schemas.SystemHealth:
    return schemas.SystemHealth(**services.collect_system_health())


@protected_router.get("/system/info", response_model=schemas.SystemInfo)
def system_info() -> schemas.SystemInfo:
    return schemas.SystemInfo(**services.collect_system_info())


@protected_router.post(
    "/system/bootstrap",
    response_model=schemas.SystemBootstrapResult,
    dependencies=[Depends(require_admin)],
)
def system_bootstrap(
    payload: schemas.SystemBootstrapRequest | None = Body(None),
) -> schemas.SystemBootstrapResult:
    should_seed = payload.seed_demo_data if payload is not None else settings.seed_demo_data_on_bootstrap
    return schemas.SystemBootstrapResult(**services.bootstrap_runtime(seed_demo_data_enabled=should_seed))


@public_router.post("/auth/login", response_model=schemas.AuthLoginResponse)
def login(payload: schemas.AuthLoginRequest, db: Session = Depends(get_db)) -> schemas.AuthLoginResponse:
    user = services.authenticate_user(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = services.issue_user_token(db, user)
    return schemas.AuthLoginResponse(token=token, user=user)


@protected_router.post("/auth/logout", status_code=204)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> None:
    if credentials and credentials.credentials:
        services.revoke_user_token(db, credentials.credentials)


@protected_router.get("/auth/me", response_model=schemas.UserRead)
def get_profile(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@protected_router.get("/dashboard/summary", response_model=schemas.DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)) -> schemas.DashboardSummary:
    return schemas.DashboardSummary(**services.build_dashboard_summary(db))


@protected_router.get("/workspaces", response_model=list[schemas.WorkspaceRead])
def list_workspaces(db: Session = Depends(get_db)) -> list[Workspace]:
    return list(db.scalars(select(Workspace).order_by(Workspace.id.asc())).all())


@protected_router.post(
    "/workspaces",
    response_model=schemas.WorkspaceRead,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def create_workspace(payload: schemas.WorkspaceCreate, db: Session = Depends(get_db)) -> Workspace:
    workspace = Workspace(**payload.model_dump())
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


@protected_router.get("/projects", response_model=list[schemas.ProjectRead])
def list_projects(workspace_id: int | None = None, db: Session = Depends(get_db)) -> list[Project]:
    stmt = select(Project).order_by(Project.id.asc())
    if workspace_id:
        stmt = stmt.where(Project.workspace_id == workspace_id)
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/projects",
    response_model=schemas.ProjectRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)) -> Project:
    data = payload.model_dump()
    if data.get("workspace_id") is None:
        workspace = services.ensure_default_workspace(db)
        data["workspace_id"] = workspace.id
    else:
        workspace = db.get(Workspace, data["workspace_id"])
        if workspace is None:
            raise HTTPException(status_code=404, detail="工作空间不存在")
    project = Project(**data)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@protected_router.delete("/projects/{project_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    plan_ids = list(db.scalars(select(TestPlan.id).where(TestPlan.project_id == project_id)).all())
    if plan_ids:
        db.execute(delete(TestPlanCase).where(TestPlanCase.plan_id.in_(plan_ids)))

    db.execute(delete(TestRun).where(TestRun.project_id == project_id))
    db.execute(delete(TestPlanRun).where(TestPlanRun.project_id == project_id))
    db.execute(delete(TestPlan).where(TestPlan.project_id == project_id))
    db.execute(delete(APICase).where(APICase.project_id == project_id))
    db.execute(delete(UICase).where(UICase.project_id == project_id))
    db.execute(delete(Environment).where(Environment.project_id == project_id))
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()


@protected_router.get("/api-cases", response_model=list[schemas.APICaseRead])
def list_api_cases(project_id: int | None = None, db: Session = Depends(get_db)) -> list[APICase]:
    stmt = select(APICase).order_by(APICase.id.asc())
    if project_id:
        stmt = stmt.where(APICase.project_id == project_id)
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/api-cases",
    response_model=schemas.APICaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_api_case(payload: schemas.APICaseCreate, db: Session = Depends(get_db)) -> APICase:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    data = payload.model_dump()
    data["method"] = data["method"].upper()
    api_case = APICase(**data)
    db.add(api_case)
    db.commit()
    db.refresh(api_case)
    return api_case


@protected_router.delete("/api-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_api_case(case_id: int, db: Session = Depends(get_db)) -> None:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")

    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "API", TestPlanCase.case_id == case_id)
    )
    db.delete(api_case)
    db.commit()



@protected_router.get("/ui-cases", response_model=list[schemas.UICaseRead])
def list_ui_cases(project_id: int | None = None, db: Session = Depends(get_db)) -> list[UICase]:
    stmt = select(UICase).order_by(UICase.id.asc())
    if project_id:
        stmt = stmt.where(UICase.project_id == project_id)
    return list(db.scalars(stmt).all())


@protected_router.delete("/ui-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_ui_case(case_id: int, db: Session = Depends(get_db)) -> None:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")

    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "UI", TestPlanCase.case_id == case_id)
    )
    db.delete(ui_case)
    db.commit()


@protected_router.get("/environments", response_model=list[schemas.EnvironmentRead])
def list_environments(project_id: int | None = None, db: Session = Depends(get_db)) -> list[Environment]:
    stmt = select(Environment).order_by(Environment.id.asc())
    if project_id:
        stmt = stmt.where(Environment.project_id == project_id)
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/environments",
    response_model=schemas.EnvironmentRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_environment(payload: schemas.EnvironmentCreate, db: Session = Depends(get_db)) -> Environment:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    env = Environment(**payload.model_dump())
    db.add(env)
    db.commit()
    db.refresh(env)
    return env


@protected_router.delete("/environments/{environment_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_environment(environment_id: int, db: Session = Depends(get_db)) -> None:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")

    db.execute(update(TestRun).where(TestRun.environment_id == environment_id).values(environment_id=None))
    db.execute(
        update(TestPlanRun).where(TestPlanRun.environment_id == environment_id).values(environment_id=None)
    )
    db.delete(env)
    db.commit()


@protected_router.get("/test-plans", response_model=list[schemas.TestPlanRead])
def list_test_plans(project_id: int | None = None, db: Session = Depends(get_db)) -> list[TestPlan]:
    stmt = select(TestPlan).order_by(TestPlan.id.asc())
    if project_id:
        stmt = stmt.where(TestPlan.project_id == project_id)
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/test-plans",
    response_model=schemas.TestPlanRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_test_plan(payload: schemas.TestPlanCreate, db: Session = Depends(get_db)) -> TestPlan:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    plan = TestPlan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@protected_router.delete("/test-plans/{plan_id}", status_code=204, dependencies=[Depends(require_admin)])
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


@protected_router.get("/test-plans/{plan_id}", response_model=schemas.TestPlanRead)
def get_test_plan(plan_id: int, db: Session = Depends(get_db)) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    return plan


@protected_router.get("/test-plans/{plan_id}/cases", response_model=list[schemas.TestPlanCaseRead])
def list_test_plan_cases(plan_id: int, db: Session = Depends(get_db)) -> list[TestPlanCase]:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    return list(
        db.scalars(
            select(TestPlanCase).where(TestPlanCase.plan_id == plan_id).order_by(TestPlanCase.order_index.asc())
        ).all()
    )


@protected_router.post(
    "/test-plans/{plan_id}/cases",
    response_model=schemas.TestPlanCaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def add_test_plan_case(
    plan_id: int, payload: schemas.TestPlanCaseCreate, db: Session = Depends(get_db)
) -> TestPlanCase:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    if payload.case_type == "API":
        case = db.get(APICase, payload.case_id)
    else:
        case = db.get(UICase, payload.case_id)

    if case is None:
        raise HTTPException(status_code=404, detail="用例不存在")

    plan_case = TestPlanCase(
        plan_id=plan.id,
        case_type=payload.case_type,
        case_id=payload.case_id,
        case_name=case.name,
        order_index=payload.order_index,
    )
    db.add(plan_case)
    db.commit()
    db.refresh(plan_case)
    return plan_case


@protected_router.delete(
    "/test-plans/{plan_id}/cases/{plan_case_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_test_plan_case(plan_id: int, plan_case_id: int, db: Session = Depends(get_db)) -> None:
    plan_case = db.get(TestPlanCase, plan_case_id)
    if plan_case is None or plan_case.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="计划用例不存在")
    db.delete(plan_case)
    db.commit()


@protected_router.post(
    "/test-plans/{plan_id}/run",
    response_model=schemas.TestPlanRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_test_plan(
    plan_id: int,
    payload: schemas.TestPlanRunCreate | None = Body(None),
    db: Session = Depends(get_db),
) -> TestPlanRun:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")

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
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != plan.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")

    plan_run = TestPlanRun(
        plan_id=plan.id,
        project_id=plan.project_id,
        environment_id=environment_id,
        status="PENDING",
        summary="任务已提交，等待执行",
        total_count=len(cases),
    )
    db.add(plan_run)
    db.commit()
    db.refresh(plan_run)

    for plan_case in cases:
        services.create_test_run(
            db,
            project_id=plan.project_id,
            environment_id=environment_id,
            plan_run_id=plan_run.id,
            case_type=plan_case.case_type,
            case_id=plan_case.case_id,
            case_name=plan_case.case_name,
        )

    task_id, ran_inline = _dispatch_task_or_run_inline(run_test_plan, plan_run.id)
    if ran_inline:
        db.refresh(plan_run)
    else:
        plan_run.summary = f"任务已提交，执行中（task_id={task_id}）"
        db.commit()
        db.refresh(plan_run)
    return plan_run


@protected_router.post(
    "/ui-cases",
    response_model=schemas.UICaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_ui_case(payload: schemas.UICaseCreate, db: Session = Depends(get_db)) -> UICase:
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    ui_case = UICase(**payload.model_dump())
    db.add(ui_case)
    db.commit()
    db.refresh(ui_case)
    return ui_case


@protected_router.get("/executions/runs", response_model=list[schemas.TestRunRead])
def list_runs(db: Session = Depends(get_db)) -> list[TestRun]:
    return list(db.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(30)).all())


@protected_router.get("/executions/runs/{run_id}", response_model=schemas.TestRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return run


@protected_router.post(
    "/executions/api/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_api_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
) -> TestRun:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != api_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")

    run = services.create_test_run(
        db,
        project_id=api_case.project_id,
        environment_id=environment_id,
        case_type="API",
        case_id=api_case.id,
        case_name=api_case.name,
    )
    task_id, ran_inline = _dispatch_task_or_run_inline(run_api_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@protected_router.post(
    "/executions/ui/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_ui_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
) -> TestRun:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != ui_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")

    run = services.create_test_run(
        db,
        project_id=ui_case.project_id,
        environment_id=environment_id,
        case_type="UI",
        case_id=ui_case.id,
        case_name=ui_case.name,
    )
    task_id, ran_inline = _dispatch_task_or_run_inline(run_ui_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@protected_router.post("/tools/json/format", response_model=schemas.ToolResult)
def json_formatter(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.format_json_payload(payload.payload))


@protected_router.post("/tools/base64/encode", response_model=schemas.ToolResult)
def base64_encode(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.encode_base64(payload.payload))


@protected_router.post("/tools/base64/decode", response_model=schemas.ToolResult)
def base64_decode(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.decode_base64(payload.payload))


@protected_router.post("/tools/timestamp/convert", response_model=schemas.ToolResult)
def timestamp_convert(payload: schemas.TimestampPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.convert_timestamp(payload.payload))


@protected_router.get("/reports", response_model=list[schemas.TestPlanRunView])
def list_reports(db: Session = Depends(get_db)) -> list[schemas.TestPlanRunView]:
    runs = list(db.scalars(select(TestPlanRun).order_by(TestPlanRun.id.desc()).limit(50)).all())
    result = []
    for run in runs:
        plan = db.get(TestPlan, run.plan_id)
        project = db.get(Project, run.project_id)
        environment = db.get(Environment, run.environment_id) if run.environment_id else None
        base_payload = schemas.TestPlanRunRead.model_validate(run).model_dump()
        result.append(
            schemas.TestPlanRunView(
                **base_payload,
                plan_name=plan.name if plan else "-",
                project_name=project.name if project else "-",
                environment_name=environment.name if environment else None,
            )
        )
    return result


@protected_router.get("/reports/{plan_run_id}", response_model=schemas.ReportDetail)
def get_report(plan_run_id: int, db: Session = Depends(get_db)) -> schemas.ReportDetail:
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")

    test_runs = list(
        db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id).order_by(TestRun.id.asc())).all()
    )
    return schemas.ReportDetail(plan_run=plan_run, test_runs=test_runs)


@protected_router.get("/reports/{plan_run_id}/download")
def download_report_file(
    plan_run_id: int,
    format: str = Query(default="json", pattern="^(json|junit)$"),
    db: Session = Depends(get_db),
):
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    file_path = plan_run.report_json_path if format == "json" else plan_run.report_junit_path

    if not file_path or not os.path.exists(file_path):
        runs = list(
            db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id).order_by(TestRun.id.asc())).all()
        )
        root_dir = settings.report_output_dir
        if not os.path.isabs(root_dir):
            root_dir = os.path.abspath(root_dir)
        plan_dir = os.path.join(root_dir, f"plan_run_{plan_run.id}")
        os.makedirs(plan_dir, exist_ok=True)

        summary_path = os.path.join(plan_dir, "summary.json")
        junit_path = os.path.join(plan_dir, "junit.xml")

        summary_payload = {
            "plan_run": schemas.TestPlanRunRead.model_validate(plan_run).model_dump(),
            "test_runs": [schemas.TestRunRead.model_validate(run).model_dump() for run in runs],
        }
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(summary_payload, handle, ensure_ascii=False, indent=2)

        testcases = []
        total_seconds = 0.0
        failures = 0
        for run in runs:
            case_time = float((run.duration_ms or 0) / 1000)
            total_seconds += case_time
            testcases.append((run, case_time))
            if run.status != "SUCCESS":
                failures += 1

        suite_name = f"test-plan-{plan_run.id}"
        root = ET.Element(
            "testsuite",
            {
                "name": suite_name,
                "tests": str(len(runs)),
                "failures": str(failures),
                "errors": "0",
                "skipped": "0",
                "time": f"{total_seconds:.3f}",
            },
        )

        for run, case_time in testcases:
            case_name = run.case_name or f"{run.case_type}-{run.case_id}"
            class_name = run.case_type or "CASE"
            tc = ET.SubElement(
                root,
                "testcase",
                {
                    "classname": class_name,
                    "name": case_name,
                    "time": f"{case_time:.3f}",
                },
            )
            if run.status != "SUCCESS":
                message = run.summary or "执行失败"
                failure = ET.SubElement(tc, "failure", {"message": message})
                failure.text = message

        ET.ElementTree(root).write(junit_path, encoding="utf-8", xml_declaration=True)

        plan_run.report_json_path = summary_path
        plan_run.report_junit_path = junit_path
        plan_run.report_generated_at = utc_now_naive()
        db.commit()
        db.refresh(plan_run)

        file_path = plan_run.report_json_path if format == "json" else plan_run.report_junit_path

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="报告文件不存在")
    media_type = "application/json" if format == "json" else "application/xml"
    filename = f"plan_run_{plan_run.id}.{format if format == 'json' else 'xml'}"
    return FileResponse(path=file_path, media_type=media_type, filename=filename)


@protected_router.get("/users", response_model=list[schemas.UserRead], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id.asc())).all())


@protected_router.post("/users", response_model=schemas.UserRead, status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)) -> User:
    data = payload.model_dump()
    password = data.pop("password", None) or services.DEFAULT_USER_PASSWORD
    user = User(**data, password_hash=services.hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@protected_router.put("/users/{user_id}", response_model=schemas.UserRead, dependencies=[Depends(require_admin)])
def update_user(user_id: int, payload: schemas.UserUpdate, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if password:
        user.password_hash = services.hash_password(password)
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "role" in data:
        user.role = data["role"]
    if "status" in data:
        user.status = data["status"]
    db.commit()
    db.refresh(user)
    return user
