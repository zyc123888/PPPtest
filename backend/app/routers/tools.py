"""辅助工具箱路由：JSON 格式化、Base64 编解码、时间戳转换、Cron 预览与哈希摘要。"""

from fastapi import APIRouter, HTTPException

from app import schemas, services

tools_router = APIRouter(tags=["tools"])


@tools_router.post("/tools/json/format", response_model=schemas.ToolResult)
def json_formatter(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.format_json_payload(payload.payload))


@tools_router.post("/tools/base64/encode", response_model=schemas.ToolResult)
def base64_encode(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.encode_base64(payload.payload))


@tools_router.post("/tools/base64/decode", response_model=schemas.ToolResult)
def base64_decode(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.decode_base64(payload.payload))


@tools_router.post("/tools/timestamp/convert", response_model=schemas.ToolResult)
def timestamp_convert(payload: schemas.TimestampPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.convert_timestamp(payload.payload))


@tools_router.post("/tools/cron/preview", response_model=schemas.ToolResult)
def cron_preview(payload: schemas.TextPayload) -> schemas.ToolResult:
    try:
        return schemas.ToolResult(result=services.preview_cron(payload.payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@tools_router.post("/tools/hash/digest", response_model=schemas.ToolResult)
def hash_digest(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.digest_text(payload.payload))
