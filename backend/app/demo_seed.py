"""全模块演示数据初始化（幂等）。

由 ``services.seed_demo_data`` 调用，覆盖：
- 工作空间、团队成员与演示项目
- 多环境配置（本地联调 / 测试环境 / Mock 仿真）
- 接口用例（单接口、变量模板、多步骤场景、Mock 服务、数据驱动）
- UI 用例（Playwright 原生巡检 + Midscene AI 示例）
- 性能压测用例（系统探针压测 + Mock 吞吐压测）
- 测试计划与定时调度配置
- 历史执行记录与测试报告（含连续两次计划执行，支持报告历史 Diff 对比 + 日志终端着色 + 压测分位指标）
- 敏捷项目工作台（迭代与燃尽图、需求与用例追溯矩阵、任务看板、缺陷管理、活动流、评论）
- AI 用例生成 V1 / V2 示例任务与产物（无需外部 LLM Key 即可浏览与导入体验）
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    APICase,
    Activity,
    CaseGenerationArtifact,
    CaseGenerationAttempt,
    CaseGenerationJob,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
    CaseGenerationV2Job,
    Comment,
    Defect,
    DefectCaseLink,
    DefectRecord,
    DefectRunLink,
    Environment,
    ExecutionLog,
    ExecutionStep,
    Iteration,
    PerformanceCase,
    Project,
    ProjectMember,
    ProjectNotificationSetting,
    ProjectTask,
    Requirement,
    RequirementCaseLink,
    TestPlan,
    TestPlanCase,
    TestPlanRun,
    TestRun,
    UIBatchRun,
    UICase,
    User,
    Workspace,
)
from app.timeutil import utc_now_naive


def _ensure_user(db: Session, *, username: str, display_name: str, role: str, password_hash: str) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        return user, False
    user = User(
        username=username,
        display_name=display_name,
        role=role,
        status="ACTIVE",
        password_hash=password_hash,
    )
    db.add(user)
    db.flush()
    return user, True


def _ensure_project_member(db: Session, project_id: int, user_id: int, role: str) -> None:
    existing = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    if existing is None:
        db.add(ProjectMember(project_id=project_id, user_id=user_id, role=role))


def seed_rich_demo_workspace(
    db: Session,
    *,
    admin_user: User,
    backend_url: str,
    frontend_url: str,
    hash_password_fn,
    ensure_workspace_member_fn,
) -> list[str]:
    """幂等创建全功能演示项目与各模块示例数据。"""
    seeded: list[str] = []
    now = utc_now_naive()
    demo_pw_hash = hash_password_fn(settings.initial_admin_password)

    # 1. 演示团队成员
    qa_user, qa_created = _ensure_user(
        db,
        username="qa_lead",
        display_name="林测试",
        role="tester",
        password_hash=demo_pw_hash,
    )
    dev_user, dev_created = _ensure_user(
        db,
        username="dev_wang",
        display_name="王研发",
        role="tester",
        password_hash=demo_pw_hash,
    )
    if qa_created:
        seeded.append("user:qa_lead")
    if dev_created:
        seeded.append("user:dev_wang")

    # 2. 演示工作空间
    ecom_ws = db.scalar(select(Workspace).where(Workspace.name == "电商核心业务空间"))
    if ecom_ws is None:
        ecom_ws = Workspace(
            name="电商核心业务空间",
            description="覆盖订单、支付、压测与敏捷协作全链路的演示工作空间。",
        )
        db.add(ecom_ws)
        db.flush()
        seeded.append("workspace:电商核心业务空间")
    ensure_workspace_member_fn(db, ecom_ws.id, admin_user.id, "owner")
    ensure_workspace_member_fn(db, ecom_ws.id, qa_user.id, "member")
    ensure_workspace_member_fn(db, ecom_ws.id, dev_user.id, "member")

    # 3. 演示项目
    project = db.scalar(select(Project).where(Project.name == "电商核心业务演示项目"))
    if project is None:
        project = Project(
            workspace_id=ecom_ws.id,
            name="电商核心业务演示项目",
            code="ECOM-DEMO",
            description="包含接口/UI/性能/Mock/测试计划/报告对比/敏捷迭代与 AI 用例生成的全功能示例项目。",
            base_url=backend_url,
            status="ACTIVE",
            start_date=now - timedelta(days=14),
            end_date=now + timedelta(days=45),
            created_by=admin_user.id,
            updated_by=admin_user.id,
        )
        project.variables_json = {
            "api_version": "v1",
            "demo_env": "local",
            "order_id": "ORD-20261119-001",
            "merchant_code": "MCH-8801",
        }
        db.add(project)
        db.flush()
        seeded.append("project:电商核心业务演示项目")
    elif not project.variables_json:
        project.variables_json = {
            "api_version": "v1",
            "demo_env": "local",
            "order_id": "ORD-20261119-001",
            "merchant_code": "MCH-8801",
        }

    _ensure_project_member(db, project.id, admin_user.id, "owner")
    _ensure_project_member(db, project.id, qa_user.id, "manager")
    _ensure_project_member(db, project.id, dev_user.id, "member")

    # 4. 多环境配置
    env_specs = [
        (
            "本地联调环境",
            backend_url,
            {"accept": "application/json", "X-Demo-Env": "local"},
            {
                "api_version": "v1",
                "frontend_url": frontend_url,
                "order_id": "ORD-20261119-001",
                "demo_env": "local",
            },
        ),
        (
            "测试环境 (Staging)",
            backend_url,
            {"accept": "application/json", "X-Demo-Env": "staging"},
            {
                "api_version": "v1",
                "frontend_url": frontend_url,
                "order_id": "ORD-20261119-002",
                "demo_env": "staging",
            },
        ),
        (
            "Mock 仿真环境",
            f"{backend_url.rstrip('/')}/api/v1/mock/{project.id}",
            {"accept": "application/json", "X-Mock-Client": "OminiTest"},
            {
                "api_version": "v1",
                "order_id": "ORD-20261119-001",
                "demo_env": "mock",
            },
        ),
    ]
    envs: dict[str, Environment] = {}
    for env_name, base_url, headers, variables in env_specs:
        env = db.scalar(
            select(Environment).where(Environment.project_id == project.id, Environment.name == env_name)
        )
        if env is None:
            env = Environment(
                project_id=project.id,
                name=env_name,
                base_url=base_url,
                headers_json=headers,
                created_by=admin_user.id,
                updated_by=admin_user.id,
            )
            env.variables_json = variables
            db.add(env)
            db.flush()
            seeded.append(f"environment:{env_name}")
        envs[env_name] = env
    local_env = envs["本地联调环境"]

    # 5. 接口用例
    api_specs = [
        {
            "name": "系统健康状态巡检",
            "folder_path": "系统巡检/基础探针",
            "method": "GET",
            "path": "/api/v1/system/health",
            "priority": "P0",
            "review_status": "APPROVED",
            "tags_json": ["冒烟", "系统巡检"],
            "headers_json": {"accept": "application/json"},
            "assertions_json": [
                {"type": "status_code", "operator": "eq", "expected": 200},
                {"type": "json_path", "expression": "$.app_status", "operator": "eq", "expected": "healthy"},
            ],
            "expected_status": 200,
        },
        {
            "name": "变量模板存活探针",
            "folder_path": "系统巡检/基础探针",
            "method": "GET",
            "path": "/api/{{api_version}}/system/health/live",
            "priority": "P1",
            "review_status": "APPROVED",
            "tags_json": ["变量模板", "冒烟"],
            "headers_json": {"accept": "application/json", "X-Env": "{{demo_env}}"},
            "assertions_json": [
                {"type": "status_code", "operator": "eq", "expected": 200},
                {"type": "json_path", "expression": "$.status", "operator": "eq", "expected": "alive"},
            ],
            "expected_status": 200,
        },
        {
            "name": "多步骤场景：探针提取与健康校验",
            "folder_path": "订单核心/场景编排",
            "method": "GET",
            "path": "/api/v1/system/health/live",
            "priority": "P0",
            "review_status": "APPROVED",
            "tags_json": ["场景编排", "回归"],
            "steps_json": [
                {
                    "name": "步骤1：获取服务存活状态",
                    "method": "GET",
                    "path": "/api/{{api_version}}/system/health/live",
                    "expected_status": 200,
                    "assertions": [{"type": "json_path", "expression": "$.status", "operator": "eq", "expected": "alive"}],
                    "extractors": [{"name": "live_status", "source": "json_path", "expression": "$.status"}],
                },
                {
                    "name": "步骤2：携带提取变量校验整体健康",
                    "method": "GET",
                    "path": "/api/{{api_version}}/system/health",
                    "headers_json": {"X-Prev-Live-Status": "{{live_status}}"},
                    "expected_status": 200,
                    "assertions": [{"type": "status_code", "operator": "eq", "expected": 200}],
                },
            ],
            "expected_status": 200,
        },
        {
            "name": "Mock 订单详情查询服务",
            "folder_path": "订单核心/Mock服务",
            "method": "GET",
            "path": "/mock-orders/{id}",
            "priority": "P1",
            "review_status": "APPROVED",
            "tags_json": ["Mock", "订单"],
            "mock_enabled": True,
            "mock_config_json": {
                "status_code": 200,
                "delay_ms": 60,
                "headers": {"X-Mock-Source": "OminiTest", "X-Order-Service": "demo"},
                "body": {
                    "order_id": "ORD-20261119-001",
                    "status": "PAID",
                    "amount": 299.0,
                    "currency": "CNY",
                    "merchant_code": "MCH-8801",
                    "items": [{"sku": "SKU-1001", "name": "无线降噪耳机", "qty": 1, "price": 299.0}],
                },
            },
            "expected_status": 200,
        },
        {
            "name": "数据驱动：多批次存活探针校验",
            "folder_path": "订单核心/数据驱动",
            "method": "GET",
            "path": "/api/{{api_version}}/system/health/live",
            "priority": "P2",
            "review_status": "IN_REVIEW",
            "tags_json": ["数据驱动", "回归"],
            "datasets_json": [
                {"__name__": "默认环境探针", "expected_state": "alive"},
                {"__name__": "灰度环境探针", "expected_state": "alive"},
            ],
            "assertions_json": [
                {"type": "status_code", "operator": "eq", "expected": 200},
                {"type": "jsonpath", "target": "$.status", "operator": "eq", "expected": "alive"},
            ],
            "expected_status": 200,
        },
    ]
    api_cases: dict[str, APICase] = {}
    for spec in api_specs:
        case = db.scalar(
            select(APICase).where(APICase.project_id == project.id, APICase.name == spec["name"])
        )
        if case is None:
            case = APICase(
                project_id=project.id,
                status="ACTIVE",
                created_by=qa_user.id,
                updated_by=qa_user.id,
                **spec,
            )
            db.add(case)
            db.flush()
            seeded.append(f"api_case:{spec['name']}")
        api_cases[spec["name"]] = case

    # 6. UI 用例
    ui_specs = [
        {
            "name": "登录页与核心入口巡检",
            "folder_path": "核心链路/登录鉴权",
            "target_url": frontend_url,
            "priority": "P0",
            "review_status": "APPROVED",
            "tags_json": ["Playwright", "冒烟"],
            "steps_json": [
                {"action": "goto", "value": frontend_url},
                {"action": "wait_for_text", "value": "登录"},
            ],
            "assertions_json": [{"type": "text_present", "expected": "登录"}],
            "expect_text": "登录",
            "engine": "native",
            "generation_mode": "manual",
            "execution_mode": "stable",
        },
        {
            "name": "工作台导航与总览巡检（Midscene AI 示例）",
            "folder_path": "AI探索/视觉巡检",
            "target_url": frontend_url,
            "priority": "P1",
            "review_status": "APPROVED",
            "tags_json": ["Midscene", "AI视觉"],
            "steps_json": [
                {"action": "goto", "value": frontend_url},
                {"action": "wait_for_text", "value": "登录"},
            ],
            "assertions_json": [{"type": "text_present", "expected": "登录"}],
            "expect_text": "登录",
            "engine": "midscene",
            "generation_mode": "ai_skill",
            "execution_mode": "adaptive",
            "self_heal_enabled": 1,
            "max_agent_steps": 8,
            "ai_goal": "打开工作台页面并确认核心登录入口和系统标题正常渲染",
        },
    ]
    ui_cases: dict[str, UICase] = {}
    for spec in ui_specs:
        case = db.scalar(
            select(UICase).where(UICase.project_id == project.id, UICase.name == spec["name"])
        )
        if case is None:
            case = UICase(
                project_id=project.id,
                status="ACTIVE",
                created_by=qa_user.id,
                updated_by=qa_user.id,
                **spec,
            )
            db.add(case)
            db.flush()
            seeded.append(f"ui_case:{spec['name']}")
        ui_cases[spec["name"]] = case

    # 7. 性能压测用例
    perf_specs = [
        {
            "name": "健康探针基准压测",
            "folder_path": "基准压测/系统接口",
            "method": "GET",
            "path": "/api/v1/system/health/live",
            "priority": "P1",
            "review_status": "APPROVED",
            "tags_json": ["基准压测", "P95"],
            "headers_json": {"accept": "application/json"},
            "expected_status": 200,
            "concurrency": 4,
            "total_requests": 20,
            "max_avg_response_ms": 500,
            "max_p95_response_ms": 1000,
            "max_error_rate": 0.05,
        },
        {
            "name": "Mock 订单详情并发吞吐压测",
            "folder_path": "基准压测/订单接口",
            "method": "GET",
            "path": f"/api/v1/mock/{project.id}/mock-orders/ORD-20261119-001",
            "priority": "P1",
            "review_status": "APPROVED",
            "tags_json": ["Mock压测", "订单"],
            "headers_json": {"accept": "application/json"},
            "expected_status": 200,
            "concurrency": 6,
            "total_requests": 24,
            "max_avg_response_ms": 800,
            "max_p95_response_ms": 1500,
            "max_error_rate": 0.05,
        },
    ]
    perf_cases: dict[str, PerformanceCase] = {}
    for spec in perf_specs:
        case = db.scalar(
            select(PerformanceCase).where(
                PerformanceCase.project_id == project.id,
                PerformanceCase.name == spec["name"],
            )
        )
        if case is None:
            case = PerformanceCase(
                project_id=project.id,
                status="ACTIVE",
                created_by=qa_user.id,
                updated_by=qa_user.id,
                **spec,
            )
            db.add(case)
            db.flush()
            seeded.append(f"performance_case:{spec['name']}")
        perf_cases[spec["name"]] = case

    # 8. 测试计划
    reg_plan = db.scalar(
        select(TestPlan).where(TestPlan.project_id == project.id, TestPlan.name == "核心回归测试计划")
    )
    if reg_plan is None:
        reg_plan = TestPlan(
            project_id=project.id,
            name="核心回归测试计划",
            description="覆盖接口探针、场景编排、基准压测与 UI 巡检的发版前回归计划。",
            status="ACTIVE",
            created_by=qa_user.id,
            updated_by=qa_user.id,
        )
        db.add(reg_plan)
        db.flush()
        seeded.append("plan:核心回归测试计划")
        plan_items = [
            ("API", api_cases["系统健康状态巡检"], 1),
            ("API", api_cases["变量模板存活探针"], 2),
            ("API", api_cases["多步骤场景：探针提取与健康校验"], 3),
            ("PERF", perf_cases["健康探针基准压测"], 4),
        ]
        for case_type, case_obj, order_idx in plan_items:
            db.add(
                TestPlanCase(
                    plan_id=reg_plan.id,
                    case_type=case_type,
                    case_id=case_obj.id,
                    case_name=case_obj.name,
                    order_index=order_idx,
                    created_by=qa_user.id,
                )
            )

    smoke_plan = db.scalar(
        select(TestPlan).where(TestPlan.project_id == project.id, TestPlan.name == "每日冒烟定时巡检")
    )
    if smoke_plan is None:
        smoke_plan = TestPlan(
            project_id=project.id,
            name="每日冒烟定时巡检",
            description="工作日早 9 点自动执行的轻量接口冒烟巡检（示例默认关闭调度，可按需开启）。",
            status="ACTIVE",
            schedule_enabled=False,
            schedule_cron="0 9 * * 1-5",
            schedule_environment_id=local_env.id,
            created_by=qa_user.id,
            updated_by=qa_user.id,
        )
        db.add(smoke_plan)
        db.flush()
        seeded.append("plan:每日冒烟定时巡检")
        for idx, name in enumerate(["系统健康状态巡检", "变量模板存活探针"], start=1):
            c = api_cases[name]
            db.add(
                TestPlanCase(
                    plan_id=smoke_plan.id,
                    case_type="API",
                    case_id=c.id,
                    case_name=c.name,
                    order_index=idx,
                    created_by=qa_user.id,
                )
            )

    # 9. 历史执行与测试报告（连续 2 次 TestPlanRun）
    existing_plan_runs = list(
        db.scalars(select(TestPlanRun).where(TestPlanRun.plan_id == reg_plan.id).order_by(TestPlanRun.id.asc())).all()
    )
    failed_sample_run: TestRun | None = None
    first_plan_run: TestPlanRun | None = existing_plan_runs[0] if existing_plan_runs else None
    if not existing_plan_runs:
        t1_start = now - timedelta(hours=3, minutes=10)
        t1_end = t1_start + timedelta(seconds=4)
        pr1 = TestPlanRun(
            plan_id=reg_plan.id,
            project_id=project.id,
            environment_id=local_env.id,
            status="FAILED",
            summary="计划执行完成：通过 3 / 4，失败 1（变量模板存活探针断言异常）",
            error_type="ASSERTION",
            retry_count=0,
            total_count=4,
            pass_count=3,
            fail_count=1,
            started_at=t1_start,
            finished_at=t1_end,
            duration_ms=4120,
            created_at=t1_start,
        )
        db.add(pr1)
        db.flush()
        first_plan_run = pr1

        r1_specs = [
            ("API", api_cases["系统健康状态巡检"], "SUCCESS", None, 48, "状态码 200，所有断言通过"),
            ("API", api_cases["变量模板存活探针"], "FAILED", "ASSERTION", 132, "断言失败：期望 $.status == alive，实际为 degraded"),
            ("API", api_cases["多步骤场景：探针提取与健康校验"], "SUCCESS", None, 95, "2 个场景步骤全部通过"),
            ("PERF", perf_cases["健康探针基准压测"], "SUCCESS", None, 1840, "并发 4 / 请求 20：P95=42ms，QPS=64.2，错误率 0%"),
        ]
        for ctype, cobj, st, err, dur, summary in r1_specs:
            run = TestRun(
                project_id=project.id,
                environment_id=local_env.id,
                plan_run_id=pr1.id,
                case_type=ctype,
                case_id=cobj.id,
                case_name=cobj.name,
                status=st,
                summary=summary,
                error_type=err,
                duration_ms=dur,
                exit_code=0 if st == "SUCCESS" else 1,
                stdout_text=(
                    f"[INFO] 开始执行用例: {cobj.name}\n"
                    f"[INFO] 目标环境: 本地联调环境 ({backend_url})\n"
                    + (
                        f"[PASS] HTTP 200 OK ({dur}ms)\n[PASS] 所有断言均已通过"
                        if st == "SUCCESS"
                        else "[WARN] 响应体字段 $.status 返回 degraded\n[FAIL] AssertionError: expected 'alive', got 'degraded'"
                    )
                ),
                stderr_text=None if st == "SUCCESS" else "AssertionError: $.status expected 'alive' but got 'degraded'",
                response_payload=(
                    {
                        "concurrency": 4,
                        "total_requests": 20,
                        "success_count": 20,
                        "fail_count": 0,
                        "error_rate": 0.0,
                        "avg_ms": 26.4,
                        "p50_ms": 24.0,
                        "p90_ms": 38.5,
                        "p95_ms": 42.0,
                        "p99_ms": 49.2,
                        "qps": 64.2,
                        "tps": 64.2,
                    }
                    if ctype == "PERF"
                    else {"status_code": 200, "body": {"status": "alive" if st == "SUCCESS" else "degraded"}}
                ),
                started_at=t1_start,
                finished_at=t1_start + timedelta(milliseconds=dur),
                created_at=t1_start,
            )
            db.add(run)
            db.flush()
            db.add(ExecutionLog(run_id=run.id, stream="stdout", content=run.stdout_text))
            if run.stderr_text:
                db.add(ExecutionLog(run_id=run.id, stream="stderr", content=run.stderr_text))
            db.add(
                ExecutionStep(
                    run_id=run.id,
                    step_index=1,
                    name=f"执行 {cobj.name}",
                    status=st,
                    detail=summary,
                    duration_ms=dur,
                )
            )
            if st == "FAILED":
                failed_sample_run = run

        t2_start = now - timedelta(minutes=25)
        t2_end = t2_start + timedelta(seconds=3)
        pr2 = TestPlanRun(
            plan_id=reg_plan.id,
            project_id=project.id,
            environment_id=local_env.id,
            status="SUCCESS",
            summary="计划执行完成：全部 4 条用例通过（较上次修复 1 条失败）",
            retry_count=0,
            total_count=4,
            pass_count=4,
            fail_count=0,
            started_at=t2_start,
            finished_at=t2_end,
            duration_ms=2980,
            created_at=t2_start,
        )
        db.add(pr2)
        db.flush()

        r2_specs = [
            ("API", api_cases["系统健康状态巡检"], 41, "状态码 200，app_status=healthy"),
            ("API", api_cases["变量模板存活探针"], 36, "状态码 200，status=alive（已修复）"),
            ("API", api_cases["多步骤场景：探针提取与健康校验"], 82, "2 个场景步骤全部通过"),
            ("PERF", perf_cases["健康探针基准压测"], 1520, "并发 4 / 请求 20：P95=36ms，QPS=78.5，错误率 0%"),
        ]
        for ctype, cobj, dur, summary in r2_specs:
            run = TestRun(
                project_id=project.id,
                environment_id=local_env.id,
                plan_run_id=pr2.id,
                case_type=ctype,
                case_id=cobj.id,
                case_name=cobj.name,
                status="SUCCESS",
                summary=summary,
                duration_ms=dur,
                exit_code=0,
                stdout_text=f"[INFO] 开始执行用例: {cobj.name}\n[PASS] HTTP 200 OK ({dur}ms)\n[PASS] {summary}",
                response_payload=(
                    {
                        "concurrency": 4,
                        "total_requests": 20,
                        "success_count": 20,
                        "fail_count": 0,
                        "error_rate": 0.0,
                        "avg_ms": 21.8,
                        "p50_ms": 20.1,
                        "p90_ms": 31.4,
                        "p95_ms": 36.0,
                        "p99_ms": 44.0,
                        "qps": 78.5,
                        "tps": 78.5,
                    }
                    if ctype == "PERF"
                    else {"status_code": 200, "body": {"status": "alive"}}
                ),
                started_at=t2_start,
                finished_at=t2_start + timedelta(milliseconds=dur),
                created_at=t2_start,
            )
            db.add(run)
            db.flush()
            db.add(ExecutionLog(run_id=run.id, stream="stdout", content=run.stdout_text))
            db.add(
                ExecutionStep(
                    run_id=run.id,
                    step_index=1,
                    name=f"执行 {cobj.name}",
                    status="SUCCESS",
                    detail=summary,
                    duration_ms=dur,
                )
            )

        batch = UIBatchRun(
            project_id=project.id,
            environment_id=local_env.id,
            case_type="API",
            status="SUCCESS",
            summary="批量执行完成：通过 3 / 3",
            total_count=3,
            pass_count=3,
            fail_count=0,
            started_at=now - timedelta(hours=1),
            finished_at=now - timedelta(hours=1) + timedelta(seconds=1),
            duration_ms=1120,
            created_by=qa_user.id,
        )
        db.add(batch)
        seeded.append("plan_runs:核心回归测试计划(x2)")

    # 10. 敏捷协作工作台
    sprint12 = db.scalar(
        select(Iteration).where(Iteration.project_id == project.id, Iteration.name == "Sprint 12 - 订单支付与自动化基线")
    )
    if sprint12 is None:
        sprint12 = Iteration(
            project_id=project.id,
            name="Sprint 12 - 订单支付与自动化基线",
            goal="完成 Mock 订单仿真、接口变量预览、异步压测引擎与报告历史 Diff 交付。",
            status="ACTIVE",
            start_date=now - timedelta(days=7),
            end_date=now + timedelta(days=7),
            capacity_points=30.0,
            sort_order=1000.0,
            created_by=admin_user.id,
            updated_by=admin_user.id,
        )
        db.add(sprint12)
        db.flush()
        seeded.append("iteration:Sprint 12")

    sprint13 = db.scalar(
        select(Iteration).where(Iteration.project_id == project.id, Iteration.name == "Sprint 13 - AI 用例生成与视觉自愈")
    )
    if sprint13 is None:
        sprint13 = Iteration(
            project_id=project.id,
            name="Sprint 13 - AI 用例生成与视觉自愈",
            goal="推进 Midscene AI 视觉巡检自愈与多源 PRD 可信分片用例生成。",
            status="PLANNING",
            start_date=now + timedelta(days=8),
            end_date=now + timedelta(days=21),
            capacity_points=28.0,
            sort_order=2000.0,
            created_by=admin_user.id,
            updated_by=admin_user.id,
        )
        db.add(sprint13)
        db.flush()
        seeded.append("iteration:Sprint 13")

    req_specs = [
        (
            "支持订单详情 Mock 仿真与动态延时配置",
            sprint12.id,
            "DONE",
            "P0",
            5.0,
            "订单模块",
            now - timedelta(days=5),
            [("API", api_cases["Mock 订单详情查询服务"])],
        ),
        (
            "接口场景编排支持变量提取与悬停预览",
            sprint12.id,
            "DONE",
            "P1",
            8.0,
            "自动化平台",
            now - timedelta(days=2),
            [("API", api_cases["变量模板存活探针"]), ("API", api_cases["多步骤场景：探针提取与健康校验"])],
        ),
        (
            "性能压测引擎支持 P50/P90/P95/P99 与 QPS 统计",
            sprint12.id,
            "TESTING",
            "P0",
            8.0,
            "性能压测",
            now - timedelta(days=1),
            [("PERF", perf_cases["健康探针基准压测"]), ("PERF", perf_cases["Mock 订单详情并发吞吐压测"])],
        ),
        (
            "测试报告支持与上次执行结果 Diff 对比",
            sprint12.id,
            "IN_PROGRESS",
            "P1",
            5.0,
            "报告中心",
            now,
            [("API", api_cases["系统健康状态巡检"])],
        ),
        (
            "Midscene AI 视觉定位与自愈巡检接入",
            sprint13.id,
            "PLANNING",
            "P2",
            8.0,
            "UI自动化",
            now,
            [("UI", ui_cases["工作台导航与总览巡检（Midscene AI 示例）"])],
        ),
    ]
    reqs: dict[str, Requirement] = {}
    for idx, (title, iter_id, st, prio, pts, folder, upd_at, links) in enumerate(req_specs, start=1):
        req = db.scalar(
            select(Requirement).where(Requirement.project_id == project.id, Requirement.title == title)
        )
        if req is None:
            req = Requirement(
                project_id=project.id,
                iteration_id=iter_id,
                title=title,
                description=f"<p><strong>业务目标：</strong>{title}，确保核心链路具备可观测、可回归的质量保障能力。</p>",
                status=st,
                priority=prio,
                type="FEATURE",
                owner_id=qa_user.id if idx % 2 else dev_user.id,
                reporter_id=admin_user.id,
                story_points=pts,
                folder_path=folder,
                tags_json=[folder, prio],
                order_index=float(idx * 1000),
                created_by=admin_user.id,
                updated_by=admin_user.id,
                updated_at=upd_at,
            )
            db.add(req)
            db.flush()
            seeded.append(f"requirement:{title[:16]}")
            for ctype, cobj in links:
                existing_link = db.scalar(
                    select(RequirementCaseLink).where(
                        RequirementCaseLink.requirement_id == req.id,
                        RequirementCaseLink.case_type == ctype,
                        RequirementCaseLink.case_id == cobj.id,
                    )
                )
                if existing_link is None:
                    db.add(
                        RequirementCaseLink(
                            requirement_id=req.id,
                            case_type=ctype,
                            case_id=cobj.id,
                            created_by=qa_user.id,
                        )
                    )
        reqs[title] = req

    task_specs = [
        ("编写 Mock 订单接口契约与延时压测用例", "DONE", "P1", 4.0, 4.0, qa_user.id, "支持订单详情 Mock 仿真与动态延时配置"),
        ("接入 SSE 实时执行日志流与终端着色", "DONE", "P0", 6.0, 5.5, dev_user.id, "测试报告支持与上次执行结果 Diff 对比"),
        ("验证异步压测引擎高并发 P95/P99 误差范围", "REVIEW", "P0", 5.0, 4.0, qa_user.id, "性能压测引擎支持 P50/P90/P95/P99 与 QPS 统计"),
        ("完善测试报告历史 Diff 卡片与耗时趋势展示", "DOING", "P1", 6.0, 3.0, dev_user.id, "测试报告支持与上次执行结果 Diff 对比"),
        ("梳理 Midscene AI 视觉自愈提示词模板", "TODO", "P2", 4.0, 0.0, qa_user.id, "Midscene AI 视觉定位与自愈巡检接入"),
    ]
    for idx, (title, st, prio, est, spent, assignee_id, req_title) in enumerate(task_specs, start=1):
        existing = db.scalar(
            select(ProjectTask).where(ProjectTask.project_id == project.id, ProjectTask.title == title)
        )
        if existing is None:
            db.add(
                ProjectTask(
                    project_id=project.id,
                    iteration_id=sprint12.id if st != "TODO" else sprint13.id,
                    requirement_id=reqs[req_title].id,
                    title=title,
                    description=f"围绕「{req_title}」拆解的执行子任务。",
                    status=st,
                    priority=prio,
                    assignee_id=assignee_id,
                    reporter_id=admin_user.id,
                    estimate_hours=est,
                    spent_hours=spent,
                    order_index=float(idx * 1000),
                    created_by=admin_user.id,
                    updated_by=admin_user.id,
                )
            )
            seeded.append(f"task:{title[:16]}")

    defect_specs = [
        (
            "高并发压测下偶发连接池超时导致错误率上升",
            "NEW",
            "CRITICAL",
            "P0",
            "PERFORMANCE",
            "压测引擎",
            "性能压测引擎支持 P50/P90/P95/P99 与 QPS 统计",
            "PERF",
            perf_cases["健康探针基准压测"].id,
        ),
        (
            "接口变量模板包含嵌套空格时悬停预览未命中",
            "CONFIRMED",
            "MAJOR",
            "P1",
            "FUNCTION",
            "接口用例",
            "接口场景编排支持变量提取与悬停预览",
            "API",
            api_cases["变量模板存活探针"].id,
        ),
        (
            "测试报告 Diff 在首次执行时应隐藏对比徽标",
            "IN_PROGRESS",
            "MINOR",
            "P2",
            "UI",
            "报告中心",
            "测试报告支持与上次执行结果 Diff 对比",
            "API",
            api_cases["系统健康状态巡检"].id,
        ),
        (
            "Mock 订单路径参数含连字符时正则匹配失败",
            "RESOLVED",
            "MAJOR",
            "P1",
            "FUNCTION",
            "Mock服务",
            "支持订单详情 Mock 仿真与动态延时配置",
            "API",
            api_cases["Mock 订单详情查询服务"].id,
        ),
    ]
    first_defect: Defect | None = None
    for idx, (title, st, sev, prio, dtype, mod, req_title, ctype, cid) in enumerate(defect_specs, start=1):
        defect = db.scalar(
            select(Defect).where(Defect.project_id == project.id, Defect.title == title)
        )
        if defect is None:
            defect = Defect(
                project_id=project.id,
                iteration_id=sprint12.id,
                requirement_id=reqs[req_title].id,
                title=title,
                description=f"<p>在 <strong>{mod}</strong> 模块回归验证过程中发现：{title}。</p>",
                reproduce_steps="<ol><li>切换至「本地联调环境」</li><li>触发对应自动化用例或计划执行</li><li>观察响应结果与执行日志</li></ol>",
                severity=sev,
                priority=prio,
                status=st,
                defect_type=dtype,
                module=mod,
                found_version="v1.8.0",
                fixed_version="v1.8.1" if st == "RESOLVED" else None,
                resolution="<p>已调整路径参数正则并补充单元测试覆盖。</p>" if st == "RESOLVED" else None,
                assignee_id=dev_user.id,
                reporter_id=qa_user.id,
                tags_json=[mod, sev],
                order_index=float(idx * 1000),
                resolved_at=now - timedelta(hours=2) if st == "RESOLVED" else None,
                created_by=qa_user.id,
                updated_by=dev_user.id,
            )
            db.add(defect)
            db.flush()
            db.add(DefectCaseLink(defect_id=defect.id, case_type=ctype, case_id=cid))
            if failed_sample_run is not None and idx == 2:
                db.add(DefectRunLink(defect_id=defect.id, test_run_id=failed_sample_run.id))
            seeded.append(f"defect:{title[:16]}")
        if first_defect is None:
            first_defect = defect

    existing_rec = db.scalar(
        select(DefectRecord).where(
            DefectRecord.project_id == project.id,
            DefectRecord.title == "[变量模板存活探针] 回归执行断言异常",
        )
    )
    if existing_rec is None:
        db.add(
            DefectRecord(
                project_id=project.id,
                run_id=failed_sample_run.id if failed_sample_run else None,
                plan_run_id=first_plan_run.id if first_plan_run else None,
                title="[变量模板存活探针] 回归执行断言异常",
                platform="GENERIC",
                external_key="BUG-2026-101",
                status="RESOLVED",
                severity="P1",
                summary="健康探针返回 degraded，已修复并在最新一次回归计划中验证通过。",
                created_by=qa_user.id,
                updated_by=dev_user.id,
            )
        )
        seeded.append("defect_record:BUG-2026-101")

    has_activity = db.scalar(select(Activity.id).where(Activity.project_id == project.id).limit(1))
    if has_activity is None and first_defect is not None:
        db.add_all(
            [
                Activity(
                    project_id=project.id,
                    entity_type="iteration",
                    entity_id=sprint12.id,
                    action="create",
                    actor_id=admin_user.id,
                    payload_json={"name": sprint12.name},
                ),
                Activity(
                    project_id=project.id,
                    entity_type="defect",
                    entity_id=first_defect.id,
                    action="create",
                    actor_id=qa_user.id,
                    payload_json={"title": first_defect.title},
                ),
            ]
        )
        db.add(
            Comment(
                project_id=project.id,
                entity_type="defect",
                entity_id=first_defect.id,
                author_id=dev_user.id,
                content="已复现，正在调优 httpx 连接池 limits 配置并补充压测验证。",
            )
        )

    notif = db.scalar(
        select(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == project.id)
    )
    if notif is None:
        db.add(
            ProjectNotificationSetting(
                project_id=project.id,
                enabled=False,
                channel_type="FEISHU",
                webhook_url=None,
                notify_on="FAIL_ONLY",
            )
        )
        seeded.append("notification_setting:电商核心业务演示项目")

    # 11. AI 用例生成 V1 / V2 示例任务
    sample_cases_payload = {
        "modules": [
            {
                "name": "订单结算与支付",
                "testcases": [
                    {
                        "title": "正常下单并完成支付回调",
                        "module": "订单结算与支付",
                        "priority": "P0",
                        "method": "POST",
                        "path": "/api/v1/orders",
                        "steps": ["选择商品并提交订单", "调用支付网关完成扣款", "校验订单状态变更为 PAID"],
                        "expected_result": "返回 200，订单状态更新为 PAID 且库存扣减准确",
                    },
                    {
                        "title": "重复提交同一幂等键订单应拦截",
                        "module": "订单结算与支付",
                        "priority": "P1",
                        "method": "POST",
                        "path": "/api/v1/orders",
                        "steps": ["携带相同 Idempotency-Key 连续请求两次下单接口"],
                        "expected_result": "第二次请求返回幂等结果，不产生重复订单",
                    },
                    {
                        "title": "超时未支付订单自动关闭并释放库存",
                        "module": "订单结算与支付",
                        "priority": "P1",
                        "steps": ["创建待支付订单", "等待超过 15 分钟支付窗口", "检查订单状态与商品库存"],
                        "expected_result": "订单状态变为 CANCELLED，锁定库存全额回滚",
                    },
                ],
            }
        ]
    }
    sample_fp_payload = {
        "function_points": [
            {"title": "订单创建与幂等防重", "priority": "P0", "description": "保障高并发下不产生重复订单"},
            {"title": "支付异步回调状态机校验", "priority": "P0", "description": "校验签名与合法状态流转"},
            {"title": "超时订单自动关单与库存回滚", "priority": "P1", "description": "释放锁定库存避免超卖"},
        ]
    }

    v1_job = db.scalar(
        select(CaseGenerationJob).where(
            CaseGenerationJob.project_id == project.id,
            CaseGenerationJob.name == "示例：电商订单结算 PRD 用例生成（V1）",
        )
    )
    if v1_job is None:
        v1_job = CaseGenerationJob(
            workspace_id=ecom_ws.id,
            project_id=project.id,
            name="示例：电商订单结算 PRD 用例生成（V1）",
            mode="MARKDOWN",
            status="SUCCESS",
            source_document_name="ecommerce_order_checkout_prd_v1.md",
            progress_json={
                "stages": [
                    {"key": "parse", "label": "需求解析", "status": "success", "summary": "提取 3 个核心功能点"},
                    {"key": "generate", "label": "用例生成", "status": "success", "summary": "生成 3 条结构化测试用例"},
                ]
            },
            input_payload_json={"mode": "MARKDOWN", "markdown_text": "# 电商订单结算需求\n1. 下单幂等\n2. 支付回调\n3. 超时关单"},
            summary="示例生成完成：共提取 3 个功能点、生成 3 条用例（支持一键导入资产库）",
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2) + timedelta(seconds=18),
            created_by=qa_user.id,
        )
        db.add(v1_job)
        db.flush()
        v1_attempt = CaseGenerationAttempt(
            job_id=v1_job.id,
            run_id=f"demo-v1-{v1_job.id}",
            execution_token=f"demo-v1-tok-{v1_job.id}",
            kind="full",
            status="SUCCESS",
            summary=v1_job.summary,
            started_at=v1_job.started_at,
            finished_at=v1_job.finished_at,
        )
        db.add(v1_attempt)
        db.flush()
        v1_job.active_attempt_id = v1_attempt.id
        db.add_all(
            [
                CaseGenerationArtifact(
                    job_id=v1_job.id,
                    attempt_id=v1_attempt.id,
                    artifact_type="function_points",
                    file_name="function_points.json",
                    content_json=sample_fp_payload,
                ),
                CaseGenerationArtifact(
                    job_id=v1_job.id,
                    attempt_id=v1_attempt.id,
                    artifact_type="testcase_package",
                    file_name="testcase_package.json",
                    content_json=sample_cases_payload,
                ),
            ]
        )
        seeded.append("case_generation_v1:示例任务")

    v2_job = db.scalar(
        select(CaseGenerationV2Job).where(
            CaseGenerationV2Job.project_id == project.id,
            CaseGenerationV2Job.name == "示例：订单支付可信分片用例生成（V2）",
        )
    )
    if v2_job is None:
        v2_job = CaseGenerationV2Job(
            workspace_id=ecom_ws.id,
            project_id=project.id,
            name="示例：订单支付可信分片用例生成（V2）",
            mode="MARKDOWN",
            status="SUCCESS",
            source_document_name="ecommerce_order_checkout_prd_v2.md",
            progress_json={
                "stages": [
                    {"key": "scope_index", "label": "范围索引", "status": "success", "summary": "识别 1 个核心业务域"},
                    {"key": "requirement", "label": "需求拆解", "status": "success", "summary": "提取 3 个必测功能点"},
                    {"key": "testcase", "label": "分片生成与门禁复核", "status": "success", "summary": "通过门禁复核，产出 3 条高质量用例"},
                ]
            },
            input_payload_json={"mode": "MARKDOWN", "pipeline_mode": "trusted"},
            summary="V2 可信生成示例完成：覆盖率 100%，产出 3 条结构化用例",
            started_at=now - timedelta(hours=1, minutes=30),
            finished_at=now - timedelta(hours=1, minutes=29),
            created_by=qa_user.id,
        )
        db.add(v2_job)
        db.flush()
        v2_attempt = CaseGenerationV2Attempt(
            job_id=v2_job.id,
            run_id=f"demo-v2-{v2_job.id}",
            execution_token=f"demo-v2-tok-{v2_job.id}",
            kind="full",
            status="SUCCESS",
            summary=v2_job.summary,
            started_at=v2_job.started_at,
            finished_at=v2_job.finished_at,
        )
        db.add(v2_attempt)
        db.flush()
        v2_job.active_attempt_id = v2_attempt.id
        db.add_all(
            [
                CaseGenerationV2Artifact(
                    job_id=v2_job.id,
                    attempt_id=v2_attempt.id,
                    artifact_type="function_points",
                    file_name="function_points.json",
                    content_json=sample_fp_payload,
                ),
                CaseGenerationV2Artifact(
                    job_id=v2_job.id,
                    attempt_id=v2_attempt.id,
                    artifact_type="testcase_package",
                    file_name="testcase_package.json",
                    content_json=sample_cases_payload,
                ),
                CaseGenerationV2Artifact(
                    job_id=v2_job.id,
                    attempt_id=v2_attempt.id,
                    artifact_type="trusted_review_report",
                    file_name="trusted_review_report.json",
                    content_json={
                        "overall_status": "PASS",
                        "must_cover_rate": 1.0,
                        "total_cases": 3,
                        "summary": "所有必测功能点均已被正向与异常用例覆盖。",
                    },
                ),
            ]
        )
        seeded.append("case_generation_v2:示例任务")

    db.commit()
    return seeded
