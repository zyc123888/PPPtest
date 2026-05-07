import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import protected_router, public_router
from app.core.config import settings
from app.services import bootstrap_runtime


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
    yield


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
