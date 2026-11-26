import asyncio
import time
from contextlib import suppress
from contextlib import asynccontextmanager
from pathlib import Path

import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import protected_router, public_router
from app.project_workspace_api import workspace_router
from app.core.config import settings
from app.core.observability import (
    configure_observability_logging,
    get_logger,
    request_id_var,
    setup_metrics,
    user_id_var,
)
from app.services import bootstrap_runtime
from app.tasks.case_generation_runtime import expire_old_artifacts, reconcile_stale_attempts


configure_observability_logging()
logger = get_logger(__name__)


def bootstrap_application(app: FastAPI) -> None:
    if not settings.auto_bootstrap_on_startup:
        return

    last_error = None
    for _ in range(settings.bootstrap_max_retries):
        try:
            app.state.bootstrap_result = bootstrap_runtime()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(settings.bootstrap_retry_interval_seconds)
    raise RuntimeError(f"数据库初始化失败: {last_error}") from last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap_application(app)
    if not settings.case_gen_watchdog_enabled:
        yield
        return
    stop_event = asyncio.Event()

    async def maintenance_loop() -> None:
        retention_tick = 0
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(reconcile_stale_attempts)
                retention_tick += 1
                if retention_tick >= max(
                    1,
                    int(3600 / max(settings.case_gen_watchdog_interval_seconds, 1)),
                ):
                    await asyncio.to_thread(expire_old_artifacts)
                    retention_tick = 0
            except Exception:
                logger.exception("case generation watchdog failed; retrying on next tick")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=max(settings.case_gen_watchdog_interval_seconds, 5),
                )
            except TimeoutError:
                continue

    maintenance_task = asyncio.create_task(maintenance_loop(), name="case-generation-watchdog")
    try:
        yield
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(maintenance_task, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            maintenance_task.cancel()
            with suppress(BaseException):
                await maintenance_task


OPENAPI_TAGS = [
    {"name": "auth", "description": "用户登录、登出、个人信息与 API Token 管理"},
    {"name": "users", "description": "平台用户与角色管理（管理员）"},
    {"name": "workspaces", "description": "工作空间与工作台聚合指标"},
    {"name": "projects", "description": "项目管理、成员权限、全局变量与通知配置"},
    {"name": "workspace-collaboration", "description": "项目协同：需求、迭代、任务看板、缺陷、追溯与富文本附件"},
    {"name": "cases", "description": "统一用例中心：跨类型检索、导入导出、查重、目录与批量治理"},
    {"name": "api-cases", "description": "接口测试用例管理与即时调试"},
    {"name": "ui-cases", "description": "UI 自动化用例管理与 AI 草稿生成"},
    {"name": "performance-cases", "description": "性能压测用例管理"},
    {"name": "case-generation", "description": "AI 用例生成 V1 任务与模型配置"},
    {"name": "case-generation-v2", "description": "AI 用例生成 V2（可信流水线、门禁与分片重跑）"},
    {"name": "environments", "description": "测试环境配置与执行前变量预检"},
    {"name": "test-plans", "description": "测试计划编排、执行与 Cron 定时调度"},
    {"name": "executions", "description": "用例执行、批量执行、SSE 实时流与产物下载"},
    {"name": "reports", "description": "测试计划报告、质量洞察与公开分享"},
    {"name": "defects", "description": "执行缺陷记录管理"},
    {"name": "system", "description": "系统健康检查、引导初始化与轻量 Mock 服务"},
    {"name": "tools", "description": "测试工程常用小工具"},
]

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="OmniTest 全链路自动化测试平台 RESTful API：覆盖项目协同、AI 用例生成、接口/UI/性能测试、测试计划与质量报告。",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_tracing_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    req_token = request_id_var.set(request_id)
    uid_token = user_id_var.set(None)
    try:
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            uid = getattr(request.state, "user_id", None)
            logger.exception(
                "request_error",
                request_id=request_id,
                user_id=uid,
                method=request.method,
                path=request.url.path,
                duration_ms=elapsed_ms,
            )
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        uid = getattr(request.state, "user_id", None)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
        if response.status_code >= 500 or elapsed_ms >= 1500:
            logger.warning(
                "request_slow_or_error",
                request_id=request_id,
                user_id=uid,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=elapsed_ms,
            )
        return response
    finally:
        user_id_var.reset(uid_token)
        request_id_var.reset(req_token)


app.include_router(public_router, prefix=settings.api_v1_prefix)
app.include_router(protected_router, prefix=settings.api_v1_prefix)
app.include_router(workspace_router, prefix=settings.api_v1_prefix)
setup_metrics(app)

_upload_dir = Path(settings.upload_dir)
_upload_dir.mkdir(parents=True, exist_ok=True)


@app.get("/")
def root() -> dict:
    return {"message": "自动化测试平台后端服务已启动"}
