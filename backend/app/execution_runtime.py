"""
统一请求运行时构造器

将 API 调试、API 执行、性能执行中的请求渲染规则（模板渲染、header 合并、body 编码）
收敛到单一模块，确保调试结果与真实执行结果使用同一套规则。
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from app.models import Environment, Project


_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class MissingTemplateVariableError(ValueError):
    """环境变量模板变量缺失异常"""

    def __init__(self, field_name: str, missing_keys: list[str]):
        joined = ", ".join(missing_keys)
        super().__init__(f"环境变量缺失: {joined}（字段: {field_name}）")
        self.field_name = field_name
        self.missing_keys = missing_keys


@dataclass
class PreparedRequest:
    """预构建的 HTTP 请求对象

    包含方法、URL、请求头和请求体，可由不同传输方式（httpx/TestClient/并发）使用。
    """

    method: str
    url: str
    headers: dict
    body: object | None

    def kwargs(self) -> dict:
        """生成 httpx.Client.request() 的 body 相关参数"""
        return build_request_kwargs(self.body)


def render_template(value: str, variables: dict | None, field_name: str = "value") -> str:
    """渲染模板字符串，替换 {{variable}} 占位符

    Args:
        value: 包含模板变量的字符串
        variables: 变量字典
        field_name: 字段名称，用于错误提示

    Returns:
        渲染后的字符串

    Raises:
        MissingTemplateVariableError: 当模板变量在 variables 中不存在时
    """
    missing_keys = sorted({key for key in _TEMPLATE_VAR_PATTERN.findall(value) if not variables or key not in variables})
    if missing_keys:
        raise MissingTemplateVariableError(field_name, missing_keys)
    if not variables:
        return value
    rendered = value
    for key, val in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(val))
    return rendered


def render_data(value, variables: dict | None, field_name: str = "value"):
    """递归渲染数据结构中的模板变量

    Args:
        value: 要渲染的值（str/dict/list/其他）
        variables: 变量字典
        field_name: 字段名称，用于错误提示

    Returns:
        渲染后的值
    """
    if isinstance(value, str):
        return render_template(value, variables, field_name)
    if isinstance(value, dict):
        return {key: render_data(val, variables, f"{field_name}.{key}") for key, val in value.items()}
    if isinstance(value, list):
        return [render_data(item, variables, f"{field_name}[{index}]") for index, item in enumerate(value)]
    return value


def build_runtime_headers(
    environment: Environment | None,
    case_headers: dict | None,
    variables: dict | None,
) -> dict:
    """构建运行时请求头

    合并顺序：环境默认头 -> 认证头 -> 用例自定义头（优先级最高）

    Args:
        environment: 环境对象
        case_headers: 用例自定义请求头
        variables: 环境变量字典

    Returns:
        合并后的请求头字典
    """
    headers = {}
    if environment and environment.headers_json:
        headers.update(render_data(environment.headers_json, variables, "environment.headers_json"))
    if environment and environment.auth_config_json and isinstance(environment.auth_config_json, dict):
        auth_config = render_data(environment.auth_config_json, variables, "environment.auth_config_json")
        token = auth_config.get("token")
        if token:
            header_name = auth_config.get("header_name", "Authorization")
            token_prefix = auth_config.get("token_prefix", "Bearer")
            headers[header_name] = f"{token_prefix} {token}".strip()
    if case_headers:
        headers.update(render_data(case_headers, variables, "case.headers_json"))
    return headers


def _enabled_body_pairs(rows: list[dict] | None) -> dict:
    """从 form-data 行中提取启用的键值对"""
    return {
        str(item.get("key")): item.get("value", "")
        for item in rows or []
        if item.get("enabled", True) and str(item.get("key", "")).strip()
    }


def build_request_kwargs(body: object) -> dict:
    """将 body 对象转换为 httpx.Client.request() 的参数

    支持的 body 模式：
    - None/空: 无 body
    - dict with mode:
        - none: 无 body
        - form-data: multipart/form-data
        - x-www-form-urlencoded: application/x-www-form-urlencoded
        - graphql: JSON with query/variables
        - binary: 二进制内容
        - raw: 原始内容（支持 JSON 解析）
    - 其他 dict/list: 自动作为 JSON body

    Args:
        body: 请求体对象

    Returns:
        httpx.Client.request() 的 body 相关参数
    """
    if not body:
        return {}
    if not isinstance(body, dict) or "mode" not in body:
        return {"json": body}

    mode = body.get("mode")
    if mode == "none":
        return {}
    if mode == "form-data":
        return {"files": {key: (None, value) for key, value in _enabled_body_pairs(body.get("form_data")).items()}}
    if mode == "x-www-form-urlencoded":
        return {"data": _enabled_body_pairs(body.get("urlencoded"))}
    if mode == "graphql":
        graphql = body.get("graphql") or {}
        return {"json": {"query": graphql.get("query", ""), "variables": graphql.get("variables") or {}}}
    if mode == "binary":
        binary = body.get("binary") or {}
        content = binary.get("content") or binary.get("content_base64") or ""
        if binary.get("encoding") == "base64":
            return {"content": base64.b64decode(content) if content else b""}
        return {"content": str(content).encode("utf-8")}
    if mode == "raw":
        raw = body.get("raw", "")
        if body.get("raw_type", "json") == "json":
            try:
                return {"json": json.loads(raw) if isinstance(raw, str) else raw}
            except Exception:
                return {"content": raw}
        return {"content": raw}

    return {"json": body}


def build_target_url(
    environment: Environment | None,
    project: Project,
    case_path: str,
    variables: dict | None,
) -> str:
    """构建完整的目标 URL

    Args:
        environment: 环境对象（可为 None）
        project: 项目对象
        case_path: 用例路径
        variables: 环境变量字典

    Returns:
        完整的 URL

    Raises:
        MissingTemplateVariableError: 当模板变量缺失时
    """
    base_url = render_template(
        environment.base_url if environment else project.base_url,
        variables,
        "base_url",
    )
    rendered_path = render_template(case_path, variables, "case.path")
    return urljoin(base_url.rstrip("/") + "/", rendered_path.lstrip("/"))


def prepare_http_request(
    *,
    method: str,
    project: Project,
    environment: Environment | None,
    case_path: str,
    case_headers: dict | None,
    case_body: object,
    variables: dict | None,
) -> PreparedRequest:
    """统一构建 HTTP 请求对象

    这是 API 调试、API 执行、性能执行的统一入口。所有需要构造 HTTP 请求的场景
    都应该使用此函数，确保调试结果与真实执行结果一致。

    Args:
        method: HTTP 方法（GET/POST/PUT/DELETE 等）
        project: 项目对象
        environment: 环境对象（可为 None）
        case_path: 用例路径
        case_headers: 用例自定义请求头
        case_body: 用例请求体
        variables: 环境变量字典（可为 None）

    Returns:
        PreparedRequest 对象，包含 method、url、headers、body

    Raises:
        MissingTemplateVariableError: 当模板变量缺失时
    """
    variables = variables or {}

    url = build_target_url(environment, project, case_path, variables)
    headers = build_runtime_headers(environment, case_headers, variables)
    rendered_body = render_data(case_body, variables, "case.body_json")

    return PreparedRequest(
        method=method.upper(),
        url=url,
        headers=headers,
        body=rendered_body,
    )
