"""系统健康检查、引导初始化与轻量 Mock 服务路由。"""

import asyncio
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.config import settings
from app.core.database import get_db
from app.core.observability import get_logger, record_frontend_error
from app.models import APICase

logger = get_logger(__name__)
_ALLOWED_CLIENT_ERROR_SOURCES = {"vue", "promise", "window", "other"}

system_public_router = APIRouter(tags=["system"])
system_protected_router = APIRouter(tags=["system"])


def _normalize_mock_path(value: str | None) -> str:
    """去除查询串并规范化为以 / 开头的路径。"""
    raw = (value or "").split("?", 1)[0].strip()
    if not raw:
        return "/"
    return "/" + raw.strip("/")


def _mock_path_matches(pattern_path: str, target_path: str) -> bool:
    norm_pattern = _normalize_mock_path(pattern_path)
    if norm_pattern == target_path:
        return True
    if "{" not in norm_pattern and ":" not in norm_pattern:
        return False
    regex_parts = []
    for segment in norm_pattern.strip("/").split("/"):
        if (segment.startswith("{") and segment.endswith("}")) or segment.startswith(":"):
            regex_parts.append(r"[^/]+")
        else:
            regex_parts.append(re.escape(segment))
    regex_str = "^/" + "/".join(regex_parts) + "$"
    return bool(re.match(regex_str, target_path))


async def mock_service(
    project_id: int,
    mock_path: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """轻量 Mock 服务：按 method+path 匹配已启用 Mock 的接口用例，返回其预设响应。"""
    method = request.method.upper()
    target = _normalize_mock_path(mock_path)
    candidates = db.scalars(
        select(APICase).where(
            APICase.project_id == project_id,
            APICase.mock_enabled.is_(True),
            APICase.status == "ACTIVE",
            func.upper(APICase.method) == method,
        )
    ).all()
    matched = next((c for c in candidates if _normalize_mock_path(c.path) == target), None)
    if matched is None:
        matched = next((c for c in candidates if _mock_path_matches(c.path, target)), None)
    if matched is None:
        raise HTTPException(status_code=404, detail="未找到匹配的 Mock 用例")

    config = matched.mock_config_json or {}
    status_code = int(config.get("status_code") or 200)
    headers = {str(k): str(v) for k, v in (config.get("headers") or {}).items()}
    delay_ms = int(config.get("delay_ms") or 0)
    if delay_ms > 0:
        await asyncio.sleep(min(delay_ms, 10000) / 1000)
    body = config.get("body")
    if isinstance(body, (dict, list)):
        return JSONResponse(content=body, status_code=status_code, headers=headers)
    return Response(content="" if body is None else str(body), status_code=status_code, headers=headers)


for _mock_method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
    system_public_router.add_api_route(
        "/mock/{project_id}/{mock_path:path}",
        mock_service,
        methods=[_mock_method],
        operation_id=f"mock_service_{_mock_method.lower()}",
        summary=f"轻量 Mock 服务（{_mock_method}）",
    )


def _health_response() -> schemas.SystemHealth | Response:
    payload = schemas.SystemHealth(**services.collect_system_health())
    if payload.app_status != "healthy":
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
    return payload


@system_public_router.get("/system/health", response_model=schemas.SystemHealth, summary="系统综合健康检查")
def system_health() -> schemas.SystemHealth | Response:
    return _health_response()


@system_public_router.get("/system/health/live", summary="进程存活探针（Liveness）")
def system_health_live() -> dict:
    return {"status": "alive"}


@system_public_router.get("/system/health/ready", response_model=schemas.SystemHealth, summary="依赖就绪探针（Readiness）")
def system_health_ready() -> schemas.SystemHealth | Response:
    return _health_response()


def _sanitize_log_text(value: str | None, limit: int = 300) -> str | None:
    if not value:
        return None
    cleaned = value.replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:limit] if cleaned else None


@system_public_router.post(
    "/system/client-errors",
    response_model=schemas.ClientErrorResult,
    summary="上报前端运行时未捕获异常",
)
def report_client_error(payload: schemas.ClientErrorReport) -> schemas.ClientErrorResult:
    normalized_source = payload.source.strip().lower()
    metric_source = normalized_source if normalized_source in _ALLOWED_CLIENT_ERROR_SOURCES else "other"
    record_frontend_error(source=metric_source)
    logger.warning(
        "frontend_runtime_error",
        source=metric_source,
        component=_sanitize_log_text(payload.component, 120),
        route=_sanitize_log_text(payload.route, 240),
        message=_sanitize_log_text(payload.message, 300),
        has_stack=bool(payload.stack),
    )
    return schemas.ClientErrorResult(recorded=True)


@system_protected_router.get("/system/info", response_model=schemas.SystemInfo, summary="获取平台运行信息")
def system_info() -> schemas.SystemInfo:
    return schemas.SystemInfo(**services.collect_system_info())


def register_admin_system_routes(protected_router: APIRouter, require_admin_dep) -> None:
    @protected_router.post(
        "/system/bootstrap",
        response_model=schemas.SystemBootstrapResult,
        dependencies=[Depends(require_admin_dep)],
        tags=["system"],
        summary="触发系统初始化与演示数据引导",
    )
    def system_bootstrap(
        payload: schemas.SystemBootstrapRequest | None = Body(None),
    ) -> schemas.SystemBootstrapResult:
        should_seed = payload.seed_demo_data if payload is not None else settings.seed_demo_data_on_bootstrap
        return schemas.SystemBootstrapResult(**services.bootstrap_runtime(seed_demo_data_enabled=should_seed))
