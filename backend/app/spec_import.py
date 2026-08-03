"""OpenAPI/Swagger 与 Postman Collection 导入解析器。

将外部接口定义文件解析为平台内部的 API 用例草稿列表，供 /api-cases/import-spec 端点落库。
解析结果为纯字典结构，不依赖数据库，便于单元测试。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

try:  # PyYAML 为可选依赖（OpenAPI 常见 YAML 格式）
    import yaml  # type: ignore
except Exception:  # pragma: no cover - 环境缺失时降级为仅支持 JSON
    yaml = None  # type: ignore


_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}


class SpecParseError(ValueError):
    """规范内容无法解析或结构不符合预期。"""


def _load_document(content: str) -> Any:
    """解析 JSON 或 YAML 文本为 Python 对象。"""
    text = (content or "").strip()
    if not text:
        raise SpecParseError("导入内容为空")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            raise SpecParseError(f"无法解析为 JSON 或 YAML：{exc}") from exc
    raise SpecParseError("无法解析导入内容，请提供合法的 JSON（或安装 PyYAML 以支持 YAML）")


def _clean_name(value: str | None, fallback: str) -> str:
    name = (value or "").strip()
    if not name:
        name = fallback
    return name[:120] if len(name) > 120 else name


def parse_openapi(document: Any) -> tuple[list[dict], list[str]]:
    """解析 OpenAPI 3.x / Swagger 2.0 文档，返回 (用例列表, 警告列表)。"""
    warnings: list[str] = []
    if not isinstance(document, dict):
        raise SpecParseError("OpenAPI 文档根节点必须为对象")

    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise SpecParseError("未在文档中找到 paths 定义")

    # base path：OpenAPI3 用 servers[0].url，Swagger2 用 basePath
    base_path = ""
    servers = document.get("servers")
    if isinstance(servers, list) and servers:
        server_url = servers[0].get("url") if isinstance(servers[0], dict) else None
        if server_url:
            parsed = urlsplit(str(server_url))
            base_path = parsed.path or ""
    elif isinstance(document.get("basePath"), str):
        base_path = document["basePath"]
    base_path = base_path.rstrip("/")

    cases: list[dict] = []
    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            method_lower = str(method).lower()
            if method_lower not in _HTTP_METHODS:
                continue
            operation = operation if isinstance(operation, dict) else {}
            full_path = f"{base_path}{raw_path}" if base_path else str(raw_path)
            summary = operation.get("summary") or operation.get("operationId")
            name = _clean_name(summary, f"{method_lower.upper()} {raw_path}")
            tags = operation.get("tags")
            folder_path = None
            if isinstance(tags, list) and tags:
                folder_path = str(tags[0])[:255]
            headers = _openapi_headers(operation)
            body = _openapi_request_body(operation)
            cases.append(
                {
                    "name": name,
                    "method": method_lower.upper(),
                    "path": full_path or "/",
                    "folder_path": folder_path,
                    "headers_json": headers or None,
                    "body_json": body,
                }
            )
    if not cases:
        raise SpecParseError("未从 paths 中解析出任何接口")
    return cases, warnings


def _openapi_headers(operation: dict) -> dict:
    headers: dict[str, str] = {}
    params = operation.get("parameters")
    if isinstance(params, list):
        for param in params:
            if isinstance(param, dict) and param.get("in") == "header" and param.get("name"):
                headers[str(param["name"])] = ""
    return headers


def _openapi_request_body(operation: dict) -> dict | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content")
    if not isinstance(content, dict):
        return None
    json_content = content.get("application/json")
    if not isinstance(json_content, dict):
        return None
    example = json_content.get("example")
    if isinstance(example, dict):
        return example
    schema = json_content.get("schema")
    if isinstance(schema, dict) and isinstance(schema.get("example"), dict):
        return schema["example"]
    return None


def parse_postman(document: Any) -> tuple[list[dict], list[str]]:
    """解析 Postman Collection v2.x 文档，返回 (用例列表, 警告列表)。"""
    warnings: list[str] = []
    if not isinstance(document, dict):
        raise SpecParseError("Postman Collection 根节点必须为对象")
    items = document.get("item")
    if not isinstance(items, list) or not items:
        raise SpecParseError("未在 Collection 中找到 item")

    cases: list[dict] = []
    _walk_postman_items(items, [], cases, warnings)
    if not cases:
        raise SpecParseError("未从 Collection 中解析出任何请求")
    return cases, warnings


def _walk_postman_items(items: list, folder_stack: list[str], cases: list[dict], warnings: list[str]) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        sub_items = item.get("item")
        if isinstance(sub_items, list):
            # 文件夹节点
            folder_name = str(item.get("name") or "").strip()
            next_stack = folder_stack + [folder_name] if folder_name else folder_stack
            _walk_postman_items(sub_items, next_stack, cases, warnings)
            continue
        request = item.get("request")
        if not isinstance(request, dict):
            continue
        method = str(request.get("method") or "GET").upper()
        url = request.get("url")
        path, query_str = _postman_url(url)
        name = _clean_name(item.get("name"), f"{method} {path}")
        headers = _postman_headers(request.get("header"))
        body = _postman_body(request.get("body"), warnings)
        folder_path = "/".join(folder_stack)[:255] if folder_stack else None
        cases.append(
            {
                "name": name,
                "method": method,
                "path": path or "/",
                "folder_path": folder_path,
                "headers_json": headers or None,
                "body_json": body,
            }
        )


def _postman_url(url: Any) -> tuple[str, str]:
    if isinstance(url, str):
        parsed = urlsplit(url)
        return (parsed.path or "/", parsed.query or "")
    if isinstance(url, dict):
        raw = url.get("raw")
        if isinstance(raw, str) and raw:
            parsed = urlsplit(raw)
            if parsed.path:
                return (parsed.path, parsed.query or "")
        segments = url.get("path")
        if isinstance(segments, list):
            joined = "/".join(str(s) for s in segments if s is not None)
            return ("/" + joined.lstrip("/"), "")
    return ("/", "")


def _postman_headers(header: Any) -> dict:
    headers: dict[str, str] = {}
    if isinstance(header, list):
        for entry in header:
            if isinstance(entry, dict) and entry.get("key") and not entry.get("disabled"):
                headers[str(entry["key"])] = str(entry.get("value") or "")
    return headers


def _postman_body(body: Any, warnings: list[str]) -> dict | None:
    if not isinstance(body, dict):
        return None
    mode = body.get("mode")
    if mode == "raw":
        raw = body.get("raw")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                warnings.append("部分 raw body 非 JSON，已跳过")
    elif mode in {"urlencoded", "formdata"}:
        entries = body.get(mode)
        if isinstance(entries, list):
            result: dict[str, str] = {}
            for entry in entries:
                if isinstance(entry, dict) and entry.get("key") and not entry.get("disabled"):
                    result[str(entry["key"])] = str(entry.get("value") or "")
            return result or None
    return None


def parse_spec(source_type: str, content: str) -> tuple[list[dict], list[str]]:
    """按 source_type 解析规范内容，返回 (用例草稿列表, 警告列表)。"""
    document = _load_document(content)
    if source_type == "openapi":
        return parse_openapi(document)
    if source_type == "postman":
        return parse_postman(document)
    raise SpecParseError(f"不支持的导入类型：{source_type}")
