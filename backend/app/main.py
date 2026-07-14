import asyncio
import logging
import time
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import protected_router, public_router
from app.core.config import settings
from app.services import bootstrap_runtime
from app.tasks.case_generation_runtime import expire_old_artifacts, reconcile_stale_attempts


logger = logging.getLogger(__name__)


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


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public_router, prefix=settings.api_v1_prefix)
app.include_router(protected_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict:
    return {"message": "自动化测试平台后端服务已启动"}
