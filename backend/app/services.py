import base64
import hashlib
import json
import secrets
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
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
    UserToken,
    Workspace,
)

DEFAULT_ADMIN_PASSWORD = "admin123"
DEFAULT_USER_PASSWORD = "tester123"
TOKEN_TTL_HOURS = 12


def _is_host_reachable(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False
        socket.getaddrinfo(host, parsed.port or 80)
        return True
    except Exception:
        return False


def _runtime_url(preferred: str, fallback: str) -> str:
    return preferred if _is_host_reachable(preferred) else fallback


def seed_demo_data(db: Session) -> None:
    workspace = ensure_default_workspace(db)
    backend_url = _runtime_url(settings.backend_internal_url, settings.backend_public_url)
    frontend_url = _runtime_url(settings.frontend_internal_url, settings.frontend_public_url)

    db.execute(
        text("UPDATE projects SET workspace_id = :workspace_id WHERE workspace_id IS NULL"),
        {"workspace_id": workspace.id},
    )
    db.commit()

    project = db.scalar(select(Project).where(Project.name == "平台自检项目"))
    if project is None:
        project = Project(
            workspace_id=workspace.id,
            name="平台自检项目",
            description="系统初始化时自动创建的演示项目，用于验证 API 与 UI 测试链路。",
            base_url=backend_url,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    elif project.workspace_id is None:
        project.workspace_id = workspace.id
        db.commit()
    if project.base_url != backend_url:
        project.base_url = backend_url
        db.commit()

    api_case = db.scalar(select(APICase).where(APICase.name == "示例健康检查接口"))
    if api_case is None:
        db.add(
            APICase(
                project_id=project.id,
                name="示例健康检查接口",
                method="GET",
                path="/api/v1/system/health",
                headers_json={"accept": "application/json"},
                expected_status=200,
            )
        )

    ui_case = db.scalar(select(UICase).where(UICase.name == "示例前端首页巡检"))
    if ui_case is None:
        db.add(
            UICase(
                project_id=project.id,
                name="示例前端首页巡检",
                target_url=frontend_url,
                steps_json=[
                    {"action": "goto", "value": frontend_url},
                    {"action": "goto", "value": f"{frontend_url}/tools/index"},
                    {"action": "wait_for_text", "value": "常用工具"},
                ],
                expect_text="常用工具",
            )
        )
    else:
        ui_case.target_url = frontend_url
        ui_case.steps_json = [
            {"action": "goto", "value": frontend_url},
            {"action": "goto", "value": f"{frontend_url}/tools/index"},
            {"action": "wait_for_text", "value": "常用工具"},
        ]

    env = db.scalar(
        select(Environment).where(Environment.project_id == project.id, Environment.name == "本地环境")
    )
    if env is None:
        db.add(
            Environment(
                project_id=project.id,
                name="本地环境",
                base_url=backend_url,
                headers_json={"accept": "application/json"},
                variables_json={"frontend_url": frontend_url},
            )
        )
    else:
        env.base_url = backend_url
        env.variables_json = {"frontend_url": frontend_url}

    plan = db.scalar(select(TestPlan).where(TestPlan.name == "演示回归计划"))
    if plan is None:
        plan = TestPlan(
            project_id=project.id,
            name="演示回归计划",
            description="包含 API 健康检查与 UI 巡检的回归验证。",
            status="ACTIVE",
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        api_case = db.scalar(select(APICase).where(APICase.name == "示例健康检查接口"))
        ui_case = db.scalar(select(UICase).where(UICase.name == "示例前端首页巡检"))
        if api_case is not None:
            db.add(
                TestPlanCase(
                    plan_id=plan.id,
                    case_type="API",
                    case_id=api_case.id,
                    case_name=api_case.name,
                    order_index=1,
                )
            )
        if ui_case is not None:
            db.add(
                TestPlanCase(
                    plan_id=plan.id,
                    case_type="UI",
                    case_id=ui_case.id,
                    case_name=ui_case.name,
                    order_index=2,
                )
            )

    user = db.scalar(select(User).where(User.username == "admin"))
    if user is None:
        db.add(
            User(
                username="admin",
                display_name="管理员",
                role="admin",
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            )
        )
    elif not user.password_hash:
        user.password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)

    db.commit()


def ensure_default_workspace(db: Session) -> Workspace:
    workspace = db.scalar(select(Workspace).order_by(Workspace.id.asc()))
    if workspace is None:
        workspace = Workspace(
            name="默认空间",
            description="系统初始化时自动创建的默认工作空间。",
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
    return workspace


def collect_system_health() -> dict:
    database_status = "healthy"
    redis_status = "healthy"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database_status = "unhealthy"

    try:
        redis.Redis.from_url(settings.redis_url, decode_responses=True).ping()
    except Exception:
        redis_status = "unhealthy"

    return {
        "app_status": "healthy" if database_status == "healthy" and redis_status == "healthy" else "degraded",
        "database": database_status,
        "redis": redis_status,
        "checked_at": datetime.now(timezone.utc),
    }


def build_dashboard_summary(db: Session) -> dict:
    workspace_count = db.scalar(select(func.count(Workspace.id))) or 0
    project_count = db.scalar(select(func.count(Project.id))) or 0
    api_case_count = db.scalar(select(func.count(APICase.id))) or 0
    ui_case_count = db.scalar(select(func.count(UICase.id))) or 0
    environment_count = db.scalar(select(func.count(Environment.id))) or 0
    plan_count = db.scalar(select(func.count(TestPlan.id))) or 0
    run_count = db.scalar(select(func.count(TestRun.id))) or 0
    plan_run_count = db.scalar(select(func.count(TestPlanRun.id))) or 0
    recent_runs = list(db.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(8)).all())

    return {
        "workspace_count": workspace_count,
        "project_count": project_count,
        "api_case_count": api_case_count,
        "ui_case_count": ui_case_count,
        "environment_count": environment_count,
        "plan_count": plan_count,
        "run_count": run_count,
        "plan_run_count": plan_run_count,
        "recent_runs": recent_runs,
    }


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return hash_password(password) == password_hash


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or user.status != "ACTIVE":
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return user


def issue_user_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=TOKEN_TTL_HOURS)
    db.add(UserToken(user_id=user.id, token=token, expires_at=expires_at))
    db.commit()
    return token


def revoke_user_token(db: Session, token: str) -> None:
    record = db.scalar(select(UserToken).where(UserToken.token == token))
    if record:
        db.delete(record)
        db.commit()


def get_user_by_token(db: Session, token: str) -> User | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    token_record = db.scalar(select(UserToken).where(UserToken.token == token, UserToken.expires_at > now))
    if token_record is None:
        return None
    return token_record.user


def create_test_run(
    db: Session,
    *,
    project_id: int,
    environment_id: int | None = None,
    plan_run_id: int | None = None,
    case_type: str,
    case_id: int,
    case_name: str,
) -> TestRun:
    run = TestRun(
        project_id=project_id,
        environment_id=environment_id,
        plan_run_id=plan_run_id,
        case_type=case_type,
        case_id=case_id,
        case_name=case_name,
        status="PENDING",
        summary="任务已提交，等待执行",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_run_started(db: Session, run: TestRun) -> None:
    run.status = "RUNNING"
    run.summary = "任务执行中"
    run.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)


def finalize_run(
    db: Session,
    run: TestRun,
    *,
    status: str,
    summary: str,
    duration_ms: int | None = None,
    request_payload: dict | None = None,
    response_payload: dict | None = None,
) -> None:
    run.status = status
    run.summary = summary
    run.duration_ms = duration_ms
    run.request_payload = request_payload
    run.response_payload = response_payload
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)


def format_json_payload(payload: str) -> str:
    parsed = json.loads(payload)
    return json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)


def encode_base64(payload: str) -> str:
    return base64.b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_base64(payload: str) -> str:
    return base64.b64decode(payload.encode("utf-8")).decode("utf-8")


def convert_timestamp(payload: str) -> str:
    normalized = payload.strip()
    if normalized.isdigit():
        dt = datetime.fromtimestamp(int(normalized), tz=timezone.utc).astimezone()
        return f"日期时间: {dt.isoformat()}\n时间戳: {int(dt.timestamp())}"

    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_time = parsed.astimezone()
    return f"日期时间: {local_time.isoformat()}\n时间戳: {int(local_time.timestamp())}"
