import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import protected_router, public_router
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.services import seed_demo_data


app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(public_router, prefix=settings.api_v1_prefix)
app.include_router(protected_router, prefix=settings.api_v1_prefix)


@app.on_event("startup")
def bootstrap() -> None:
    last_error = None
    for _ in range(30):
        try:
            init_db()
            with SessionLocal() as db:
                seed_demo_data(db)
            return
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"数据库初始化失败: {last_error}") from last_error


@app.get("/")
def root() -> dict:
    return {"message": "自动化测试平台后端服务已启动"}
