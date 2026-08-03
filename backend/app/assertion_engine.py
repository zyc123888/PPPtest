"""
统一断言与变量提取引擎

API 调试、httpx 执行、pytest 执行、多步骤场景执行共用同一套断言求值与
变量提取规则，确保「调试通过 == 执行通过」。

断言条目格式（assertions_json 中的元素）：
    {"type": "status_code", "expected": 200}
    {"type": "json_path", "expression": "$.data.id", "operator": "eq", "expected": 1}
    {"type": "body_contains", "expected": "success"}
    {"type": "body_regex", "expected": "order_\\d+"}
    {"type": "header", "name": "content-type", "operator": "contains", "expected": "json"}
    {"type": "response_time_ms", "operator": "lte", "expected": 3000}

提取器条目格式（extractors_json 中的元素）：
    {"name": "token", "source": "json_path", "expression": "$.data.token"}
    {"name": "trace_id", "source": "header", "expression": "x-trace-id"}
    {"name": "order_no", "source": "regex", "expression": "order_no=(\\w+)"}
    {"name": "code", "source": "status_code"}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ASSERTION_TYPES = {
    "status_code",
    "json_path",
    "body_contains",
    "body_regex",
    "header",
    "response_time_ms",
}

EXTRACTOR_SOURCES = {"json_path", "header", "regex", "status_code"}

_JSON_PATH_TOKEN = re.compile(
    r"""
    \.(?P<dot>[a-zA-Z_][a-zA-Z0-9_\-]*)      # .key
    | \[\s*(?P<index>-?\d+)\s*\]              # [0] / [-1]
    | \[\s*'(?P<squote>[^']*)'\s*\]           # ['key']
    | \[\s*"(?P<dquote>[^"]*)"\s*\]           # ["key"]
    """,
    re.VERBOSE,
)


class JsonPathError(ValueError):
    """JSONPath 表达式非法或取值失败"""


@dataclass
class ResponseFacts:
    """一次 HTTP 响应的断言输入事实"""

    status_code: int
    headers: dict
    body_text: str = ""
    body_json: object | None = None
    duration_ms: int | None = None


@dataclass
class AssertionOutcome:
    passed: bool
    results: list[dict] = field(default_factory=list)

    @property
    def failed_results(self) -> list[dict]:
        return [item for item in self.results if not item.get("ok")]

    def summary_text(self) -> str:
        total = len(self.results)
        ok_count = total - len(self.failed_results)
        if self.passed:
            return f"断言全部通过（{ok_count}/{total}）"
        first_failed = self.failed_results[0]
        return f"断言未通过（{ok_count}/{total}）：{first_failed.get('message', '未知原因')}"


def resolve_json_path(data: object, expression: str) -> object:
    """解析简化版 JSONPath 并取值

    支持：$、$.a.b、$.items[0].id、$['中文键']、a.b[0]（可省略 $ 前缀）。
    不支持通配符与过滤器，取值失败抛 JsonPathError。
    """
    text = (expression or "").strip()
    if not text:
        raise JsonPathError("JSONPath 表达式不能为空")
    if text.startswith("$"):
        text = text[1:]
    elif not text.startswith((".", "[")):
        text = "." + text

    current = data
    position = 0
    while position < len(text):
        match = _JSON_PATH_TOKEN.match(text, position)
        if match is None:
            raise JsonPathError(f"JSONPath 语法错误（位置 {position}）: {expression}")
        position = match.end()
        key = match.group("dot") or match.group("squote") or match.group("dquote")
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                raise JsonPathError(f"路径不存在: {expression}（缺少键 {key}）")
            current = current[key]
            continue
        index = int(match.group("index"))
        if not isinstance(current, list):
            raise JsonPathError(f"路径不存在: {expression}（[{index}] 处不是数组）")
        if index >= len(current) or index < -len(current):
            raise JsonPathError(f"路径不存在: {expression}（下标 {index} 越界，长度 {len(current)}）")
        current = current[index]
    return current


def _coerce_number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _loose_equal(actual: object, expected: object) -> bool:
    if actual == expected:
        return True
    actual_num, expected_num = _coerce_number(actual), _coerce_number(expected)
    if actual_num is not None and expected_num is not None:
        return actual_num == expected_num
    return str(actual) == str(expected)


def _compare(actual: object, operator: str, expected: object) -> tuple[bool, str | None]:
    """通用比较器，返回 (是否通过, 错误说明)"""
    if operator == "eq":
        return _loose_equal(actual, expected), None
    if operator == "ne":
        return not _loose_equal(actual, expected), None
    if operator == "contains":
        return str(expected) in str(actual), None
    if operator == "not_contains":
        return str(expected) not in str(actual), None
    if operator == "regex":
        try:
            return re.search(str(expected), str(actual)) is not None, None
        except re.error as exc:
            return False, f"正则无效: {exc}"
    if operator == "in":
        options = expected if isinstance(expected, list) else [expected]
        return any(_loose_equal(actual, option) for option in options), None
    if operator in {"gt", "gte", "lt", "lte"}:
        actual_num, expected_num = _coerce_number(actual), _coerce_number(expected)
        if actual_num is None or expected_num is None:
            return False, "比较双方必须是数值"
        if operator == "gt":
            return actual_num > expected_num, None
        if operator == "gte":
            return actual_num >= expected_num, None
        if operator == "lt":
            return actual_num < expected_num, None
        return actual_num <= expected_num, None
    if operator in {"length_eq", "length_gt", "length_lt"}:
        try:
            length = len(actual)  # type: ignore[arg-type]
        except TypeError:
            return False, "目标值不支持取长度"
        expected_num = _coerce_number(expected)
        if expected_num is None:
            return False, "期望长度必须是数值"
        if operator == "length_eq":
            return length == expected_num, None
        if operator == "length_gt":
            return length > expected_num, None
        return length < expected_num, None
    return False, f"不支持的操作符: {operator}"


_OPERATOR_LABELS = {
    "eq": "等于",
    "ne": "不等于",
    "contains": "包含",
    "not_contains": "不包含",
    "regex": "匹配正则",
    "in": "属于",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "exists": "存在",
    "not_exists": "不存在",
    "length_eq": "长度等于",
    "length_gt": "长度大于",
    "length_lt": "长度小于",
}


def _preview(value: object, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _header_lookup(headers: dict, name: str) -> str | None:
    target = (name or "").strip().lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == target:
            return str(value)
    return None


def _evaluate_single(spec: dict, facts: ResponseFacts) -> dict:
    kind = str(spec.get("type") or "").strip()
    operator = str(spec.get("operator") or "").strip() or None
    expected = spec.get("expected")
    result = {
        "type": kind,
        "ok": False,
        "expected": expected,
        "actual": None,
        "message": "",
    }
    op_label = _OPERATOR_LABELS.get(operator or "eq", operator or "eq")

    if kind == "status_code":
        operator = operator or "eq"
        result["actual"] = facts.status_code
        ok, error = _compare(facts.status_code, operator, expected)
        result["ok"] = ok
        result["message"] = (
            f"状态码 {facts.status_code} {op_label} {expected}"
            if ok
            else error or f"状态码断言失败：实际 {facts.status_code}，期望{op_label} {expected}"
        )
        if spec.get("implicit"):
            result["implicit"] = True
        return result

    if kind == "json_path":
        expression = str(spec.get("expression") or "")
        result["target"] = expression
        operator = operator or "eq"
        if facts.body_json is None:
            result["message"] = "响应体不是合法 JSON，无法执行 JSONPath 断言"
            return result
        if operator in {"exists", "not_exists"}:
            try:
                value = resolve_json_path(facts.body_json, expression)
                result["actual"] = _preview(value)
                result["ok"] = operator == "exists"
            except JsonPathError:
                result["ok"] = operator == "not_exists"
            result["message"] = (
                f"{expression} {op_label}断言{'通过' if result['ok'] else '失败'}"
            )
            return result
        try:
            value = resolve_json_path(facts.body_json, expression)
        except JsonPathError as exc:
            result["message"] = str(exc)
            return result
        result["actual"] = _preview(value)
        ok, error = _compare(value, operator, expected)
        result["ok"] = ok
        result["message"] = (
            f"{expression} {op_label} {_preview(expected)}"
            if ok
            else error or f"{expression} 断言失败：实际 {_preview(value)}，期望{op_label} {_preview(expected)}"
        )
        return result

    if kind == "body_contains":
        needle = str(expected if expected is not None else "")
        negate = bool(spec.get("negate"))
        found = needle in (facts.body_text or "")
        result["ok"] = (not found) if negate else found
        result["actual"] = _preview(facts.body_text, 120)
        verb = "不包含" if negate else "包含"
        result["message"] = (
            f"响应体{verb}“{_preview(needle, 80)}”"
            if result["ok"]
            else f"响应体断言失败：期望{verb}“{_preview(needle, 80)}”"
        )
        return result

    if kind == "body_regex":
        pattern = str(expected if expected is not None else "")
        try:
            match = re.search(pattern, facts.body_text or "")
        except re.error as exc:
            result["message"] = f"正则无效: {exc}"
            return result
        result["ok"] = match is not None
        result["actual"] = _preview(match.group(0)) if match else None
        result["message"] = (
            f"响应体匹配正则 {pattern}"
            if result["ok"]
            else f"响应体断言失败：未匹配到正则 {pattern}"
        )
        return result

    if kind == "header":
        name = str(spec.get("name") or spec.get("expression") or "")
        result["target"] = name
        operator = operator or "eq"
        value = _header_lookup(facts.headers, name)
        result["actual"] = value
        if operator in {"exists", "not_exists"}:
            present = value is not None
            result["ok"] = present if operator == "exists" else not present
            result["message"] = f"响应头 {name} {op_label}断言{'通过' if result['ok'] else '失败'}"
            return result
        if value is None:
            result["message"] = f"响应头 {name} 不存在"
            return result
        ok, error = _compare(value, operator, expected)
        result["ok"] = ok
        result["message"] = (
            f"响应头 {name} {op_label} {_preview(expected)}"
            if ok
            else error or f"响应头 {name} 断言失败：实际 {_preview(value)}，期望{op_label} {_preview(expected)}"
        )
        return result

    if kind == "response_time_ms":
        operator = operator or "lte"
        result["actual"] = facts.duration_ms
        if facts.duration_ms is None:
            result["message"] = "本次执行未采集响应耗时"
            return result
        ok, error = _compare(facts.duration_ms, operator, expected)
        result["ok"] = ok
        result["message"] = (
            f"响应耗时 {facts.duration_ms}ms {op_label} {expected}ms"
            if ok
            else error or f"响应耗时断言失败：实际 {facts.duration_ms}ms，期望{op_label} {expected}ms"
        )
        return result

    result["message"] = f"不支持的断言类型: {kind or '(空)'}"
    return result


def evaluate_assertions(
    assertions: list[dict] | None,
    facts: ResponseFacts,
    *,
    expected_status: int | None = None,
) -> AssertionOutcome:
    """求值断言列表

    当列表中没有显式的 status_code 断言且提供 expected_status 时，
    自动追加一条隐式状态码断言，保持与历史行为兼容。
    """
    specs = [item for item in (assertions or []) if isinstance(item, dict)]
    has_status = any(str(item.get("type")) == "status_code" for item in specs)
    if not has_status and expected_status is not None:
        specs = [{"type": "status_code", "expected": expected_status, "implicit": True}, *specs]

    results = [_evaluate_single(spec, facts) for spec in specs]
    return AssertionOutcome(passed=all(item["ok"] for item in results), results=results)


def run_extractors(
    extractors: list[dict] | None, facts: ResponseFacts
) -> tuple[dict, list[dict]]:
    """执行变量提取，返回 (变量字典, 提取结果明细)"""
    variables: dict = {}
    results: list[dict] = []
    for spec in extractors or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "").strip()
        source = str(spec.get("source") or "json_path").strip()
        expression = str(spec.get("expression") or "").strip()
        entry = {"name": name, "source": source, "expression": expression, "ok": False, "value": None}
        if not name:
            entry["message"] = "提取变量名不能为空"
            results.append(entry)
            continue
        try:
            if source == "json_path":
                if facts.body_json is None:
                    raise JsonPathError("响应体不是合法 JSON")
                value = resolve_json_path(facts.body_json, expression)
            elif source == "header":
                value = _header_lookup(facts.headers, expression)
                if value is None:
                    raise LookupError(f"响应头 {expression} 不存在")
            elif source == "regex":
                match = re.search(expression, facts.body_text or "")
                if match is None:
                    raise LookupError(f"响应体未匹配到正则 {expression}")
                value = match.group(1) if match.groups() else match.group(0)
            elif source == "status_code":
                value = facts.status_code
            else:
                raise ValueError(f"不支持的提取来源: {source}")
        except (JsonPathError, LookupError, ValueError, re.error) as exc:
            entry["message"] = str(exc)
            results.append(entry)
            continue
        variables[name] = value
        entry["ok"] = True
        entry["value"] = _preview(value)
        entry["message"] = f"已提取 {name} = {_preview(value, 80)}"
        results.append(entry)
    return variables, results
