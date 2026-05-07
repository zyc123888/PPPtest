import base64
import binascii
import hmac
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
from app.core.database import SessionLocal, engine, init_db
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
from app.timeutil import utc_now_naive, to_utc_naive

DEFAULT_USER_PASSWORD = "tester123"
TOKEN_TTL_HOURS = 12
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"


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


def ensure_default_admin(db: Session) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.username == "admin"))
    created_or_updated = False
    if user is None:
        user = User(
            username="admin",
            display_name="管理员",
            role="admin",
            password_hash=hash_password(settings.initial_admin_password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        created_or_updated = True
    elif not user.password_hash:
        user.password_hash = hash_password(settings.initial_admin_password)
        db.commit()
        created_or_updated = True
    return user, created_or_updated


def ensure_core_runtime_data(db: Session) -> list[str]:
    seeded_resources: list[str] = []
    existing_workspace = db.scalar(select(Workspace).order_by(Workspace.id.asc()))
    ensure_default_workspace(db)
    if existing_workspace is None:
        seeded_resources.append("workspace:默认空间")

    _, admin_changed = ensure_default_admin(db)
    if admin_changed:
        seeded_resources.append("user:admin")

    return seeded_resources


def seed_demo_data(db: Session) -> list[str]:
    seeded_resources: list[str] = []
    seeded_resources.extend(ensure_core_runtime_data(db))
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
        seeded_resources.append("project:平台自检项目")
    elif project.workspace_id is None:
        project.workspace_id = workspace.id
        db.commit()
        seeded_resources.append("project.workspace_id:平台自检项目")
    if project.base_url != backend_url:
        project.base_url = backend_url
        db.commit()
        seeded_resources.append("project.base_url:平台自检项目")

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
        seeded_resources.append("api_case:示例健康检查接口")

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
        seeded_resources.append("ui_case:示例前端首页巡检")
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
        seeded_resources.append("environment:本地环境")
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
        seeded_resources.append("plan:演示回归计划")

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
            seeded_resources.append("plan_case:演示回归计划/API")
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
            seeded_resources.append("plan_case:演示回归计划/UI")

    db.commit()
    return seeded_resources


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


def _mask_url_secret(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or parsed.password is None:
        return url

    hostname = parsed.hostname or ""
    credentials = f"{parsed.username}:***@" if parsed.username else ""
    netloc = f"{credentials}{hostname}"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


def bootstrap_runtime(seed_demo_data_enabled: bool | None = None) -> dict:
    db_summary = init_db()
    should_seed = settings.seed_demo_data_on_bootstrap if seed_demo_data_enabled is None else seed_demo_data_enabled

    with SessionLocal() as db:
        seeded_resources = ensure_core_runtime_data(db)
        if should_seed:
            for resource in seed_demo_data(db):
                if resource not in seeded_resources:
                    seeded_resources.append(resource)

    return {
        "success": True,
        "database_backend": db_summary["database_backend"],
        "database_name": db_summary["database_name"],
        "created_tables": db_summary["created_tables"],
        "schema_changes": db_summary["schema_changes"],
        "seeded_resources": seeded_resources,
        "bootstrapped_at": datetime.now(timezone.utc),
    }


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


def collect_system_info() -> dict:
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "app_env": settings.app_env,
        "api_v1_prefix": settings.api_v1_prefix,
        "database_backend": settings.database_backend,
        "database_name": settings.database_name,
        "database_url": _mask_url_secret(settings.database_url),
        "redis_url": _mask_url_secret(settings.redis_url),
        "backend_public_url": settings.backend_public_url,
        "frontend_public_url": settings.frontend_public_url,
        "execution_engine": settings.execution_engine,
        "report_output_dir": settings.report_output_dir,
        "auto_bootstrap_on_startup": settings.auto_bootstrap_on_startup,
        "seed_demo_data_on_bootstrap": settings.seed_demo_data_on_bootstrap,
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
    salt = secrets.token_hex(16)
    iterations = settings.password_hash_iterations
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    encoded_digest = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_HASH_ALGORITHM}${iterations}${salt}${encoded_digest}"


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False

    if password_hash.startswith(f"{PASSWORD_HASH_ALGORITHM}$"):
        try:
            algorithm, iterations_raw, salt, encoded_digest = password_hash.split("$", 3)
            if algorithm != PASSWORD_HASH_ALGORITHM:
                return False
            expected = base64.b64decode(encoded_digest.encode("ascii"), validate=True)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations_raw),
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, binascii.Error):
            return False

    legacy_sha256 = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_sha256, password_hash)


def password_hash_needs_upgrade(password_hash: str | None) -> bool:
    if not password_hash:
        return True
    if not password_hash.startswith(f"{PASSWORD_HASH_ALGORITHM}$"):
        return True
    try:
        _, iterations_raw, _, _ = password_hash.split("$", 3)
        return int(iterations_raw) < settings.password_hash_iterations
    except (ValueError, TypeError):
        return True


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or user.status != "ACTIVE":
        return None
    if not verify_password(password, user.password_hash):
        return None
    if password_hash_needs_upgrade(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utc_now_naive()
    db.commit()
    return user


def issue_user_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = utc_now_naive() + timedelta(hours=TOKEN_TTL_HOURS)
    db.add(UserToken(user_id=user.id, token=token, expires_at=expires_at))
    db.commit()
    return token


def revoke_user_token(db: Session, token: str) -> None:
    record = db.scalar(select(UserToken).where(UserToken.token == token))
    if record:
        db.delete(record)
        db.commit()


def get_user_by_token(db: Session, token: str) -> User | None:
    now = utc_now_naive()
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
    run.started_at = utc_now_naive()
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
    run.finished_at = utc_now_naive()
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
