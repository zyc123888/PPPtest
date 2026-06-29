from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import ssl
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm.attributes import flag_modified

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import AIModelConfig, CaseGenerationArtifact, CaseGenerationJob
from app.timeutil import utc_now_naive


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_HTML_BLOCK_PATTERN = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_SAFE_FILENAME_PATTERN = re.compile(r"[\\/:*?\"<>|]+")
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_MARKDOWN_LINK_ONLY_PATTERN = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")

_DEFAULT_MODEL = settings.case_gen_default_model
_OPENAI_BASE_URL = settings.case_gen_openai_base_url
_BAILIAN_BASE_URL = settings.case_gen_bailian_base_url
_QWEN_COMPATIBLE_BASE_URL = settings.case_gen_qwen_compatible_base_url
_QWEN_CODING_INTL_BASE_URL = settings.case_gen_qwen_coding_intl_base_url
_SECRET_SENTINEL = "***已提供***"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_IMAGE_ANALYSIS_BATCH_SIZE = settings.case_gen_image_analysis_batch_size
_REQUIREMENT_SECTION_TEXT_LIMIT = settings.case_gen_requirement_section_text_limit
_REQUIREMENT_TOTAL_TEXT_LIMIT = settings.case_gen_requirement_total_text_limit
_REQUIREMENT_BATCH_TEXT_LIMIT = settings.case_gen_requirement_batch_text_limit
_REQUIREMENT_MAX_TOKENS = settings.case_gen_requirement_max_tokens
_PENDING_CONFIRMATION_LIMIT = settings.case_gen_pending_confirmation_limit
_PENDING_CONFIRMATION_TEXT_LIMIT = settings.case_gen_pending_confirmation_text_limit
_FUNCTION_POINT_TEXT_LIMIT = settings.case_gen_function_point_text_limit
_TESTCASE_FP_BATCH_SIZE = settings.case_gen_testcase_fp_batch_size
_MIN_CASES_PER_FUNCTION_POINT = settings.case_gen_min_cases_per_function_point
_TESTCASE_REPAIR_MAX_ROUNDS = settings.case_gen_testcase_repair_max_rounds
_CASE_GENERATION_MAX_CONCURRENCY = settings.case_gen_max_concurrency
_MAX_AI_RETRIES = settings.case_gen_max_ai_retries
_DEFAULT_CHAT_TIMEOUT_SECONDS = settings.case_gen_default_chat_timeout_seconds
_LONG_CHAT_TIMEOUT_SECONDS = settings.case_gen_long_chat_timeout_seconds
_MAX_JSON_RETRY_TOKENS = 24000
_GENERIC_CASE_TITLE_PATTERNS = (
    "正常流程验证",
    "边界条件验证",
    "异常流程验证",
    "功能正常流程",
    "功能正常执行",
    "主流程验证",
    "异常验证",
    "边界验证",
)
_GENERIC_EXPECTATION_PATTERNS = (
    "系统正常",
    "结果正确",
    "功能正常",
    "符合预期",
    "操作成功",
    "结果符合需求",
    "符合需求",
    "满足需求",
    "按预期",
    "正确显示",
    "正常显示",
    "校验通过",
    "验证通过",
    "观察页面、接口和数据结果",
    "观察结果",
)
_GENERIC_STEP_PATTERNS = (
    "进入对应页面",
    "进入 ",
    "执行 正常流程验证",
    "执行 边界条件验证",
    "执行 异常流程验证",
    "执行 主流程验证",
    "观察页面、接口和数据结果",
    "观察结果",
)
_EXPECTED_OBSERVABLE_ANCHORS = (
    "页面",
    "字段",
    "状态",
    "提示",
    "接口",
    "返回",
    "数据",
    "记录",
    "列表",
    "详情",
    "日志",
    "筛选",
    "排序",
    "展开",
    "收起",
    "标签",
    "按钮",
    "弹窗",
    "菜单",
    "数据库",
    "预算",
    "任务",
    "报表",
    "表",
)


class ModelJSONParseError(ValueError):
    def __init__(self, message: str, *, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


def _is_incomplete_json_error(error: Exception | str) -> bool:
    text = str(error).lower()
    markers = (
        "json 对象不完整",
        "max_tokens",
        "被截断",
        "unexpected end of stream",
        "unexpected end of document",
        "while scanning a quoted scalar",
        "eof",
        "unterminated",
        "未闭合",
    )
    return any(marker in text for marker in markers)


def _compact_case_text(value) -> str:
    if isinstance(value, list):
        return "；".join(_compact_case_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("title", "module", "scene", "description", "atomicity_check"):
            if value.get(key):
                parts.append(str(value.get(key)))
        for key in ("rules", "test_hints", "source_refs"):
            if value.get(key):
                parts.append(_compact_case_text(value.get(key)))
        return "；".join(part for part in parts if part)
    return str(value or "").strip()






def _expected_has_observable_anchor(expected_results) -> bool:
    if isinstance(expected_results, str):
        expected_text = expected_results
    elif isinstance(expected_results, list):
        expected_text = " ".join(str(item) for item in expected_results)
    else:
        expected_text = ""
    return _text_contains_any(expected_text, _EXPECTED_OBSERVABLE_ANCHORS)




_CATEGORY_LABELS = {
    "functional": "功能",
    "ui": "UI",
    "boundary": "边界",
    "negative": "异常",
    "regression": "回归",
    "compatibility": "兼容",
    "performance": "性能",
    "security": "安全",
}
_CATEGORY_ALIASES = {
    "function": "functional",
    "功能": "functional",
    "功能测试": "functional",
    "主流程": "functional",
    "ui测试": "ui",
    "ui": "ui",
    "交互": "ui",
    "交互测试": "ui",
    "ui与边界测试": "ui",
    "boundary": "boundary",
    "边界": "boundary",
    "边界测试": "boundary",
    "边界条件": "boundary",
    "边界与异常测试": "boundary",
    "异常与边界测试": "negative",
    "negative": "negative",
    "exception": "negative",
    "异常": "negative",
    "异常测试": "negative",
    "异常处理": "negative",
    "regression": "regression",
    "回归": "regression",
    "回归测试": "regression",
    "compatibility": "compatibility",
    "兼容": "compatibility",
    "兼容测试": "compatibility",
    "performance": "performance",
    "性能": "performance",
    "性能测试": "performance",
    "security": "security",
    "安全": "security",
    "权限": "security",
    "权限测试": "security",
}
_RISK_PRIORITY_TERMS = (
    "删除",
    "覆盖",
    "权限",
    "数据丢失",
    "丢失",
    "预算",
    "状态变更",
    "状态流转",
    "保存",
    "提交",
    "支付",
    "金额",
    "结算",
    "投放",
    "任务",
    "接口",
    "数据库",
)


def _normalize_priority(value, *, fp: dict | None = None, case: dict | None = None, category: str | None = None) -> str:
    raw = str(value or "").strip().lower()
    raw = raw.replace("优先级", "").replace("：", "").replace(":", "").strip()
    priority = {
        "p0": "P0",
        "0": "P0",
        "critical": "P0",
        "blocker": "P0",
        "最高": "P0",
        "紧急": "P0",
        "p1": "P1",
        "1": "P1",
        "high": "P1",
        "高": "P1",
        "高优先级": "P1",
        "p2": "P2",
        "2": "P2",
        "medium": "P1",
        "中": "P1",
        "中优先级": "P1",
        "p3": "P3",
        "3": "P3",
        "low": "P3",
        "低": "P3",
        "低优先级": "P3",
    }.get(raw, "")
    if not priority:
        priority = "P1"

    risk_text = " ".join(
        [
            _compact_case_text(fp or {}),
            _compact_case_text(case or {}),
            str(category or ""),
        ]
    )
    has_risk = _text_contains_any(risk_text, _RISK_PRIORITY_TERMS)
    normalized_category = _normalize_category(category)
    if raw in {"medium", "中", "中优先级"} and normalized_category in {"ui", "compatibility", "performance", "regression"} and not has_risk:
        priority = "P2"
    if has_risk and priority == "P1":
        return "P0"
    if has_risk and priority == "P2":
        return "P1"
    return priority


def _normalize_category(value) -> str:
    raw = str(value or "").strip().lower().replace(" ", "")
    return _CATEGORY_ALIASES.get(raw, _CATEGORY_ALIASES.get(str(value or "").strip(), "functional"))


def _category_label(category: str | None) -> str:
    return _CATEGORY_LABELS.get(_normalize_category(category), "功能")


# 总纲展示层中文化：测试方法名（generation_basis.method / method_coverage 键）
_METHOD_LABELS = {
    "equivalence": "等价类",
    "boundary": "边界值",
    "decision_table": "决策表",
    "state_transition": "状态转换",
    "role_matrix": "角色权限",
    "entry_consistency": "多入口一致性",
    "default_or_empty": "空值默认",
    "error_tolerance": "异常容错",
    "time_or_sequence": "时间时序",
    "ui_interaction": "UI交互",
}


def _method_label(method: str | None) -> str:
    key = str(method or "").strip().lower()
    return _METHOD_LABELS.get(key, str(method or "").strip() or "其他")


def _short_text(value, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _case_evidence_refs(case: dict, fp: dict | None = None) -> list[str]:
    refs: list[str] = []
    traceability = case.get("traceability") or {}
    sources = traceability.get("sources") if isinstance(traceability, dict) else []
    for value in list(sources or []) + list((fp or {}).get("source_refs") or []):
        text = str(value or "").strip()
        if text and text not in refs:
            refs.append(text)
    return refs[:4]


def _assign_requirement_groups(function_points: dict) -> None:
    groups_by_module: dict[str, tuple[str, str]] = {}
    next_index = 1
    for fp in sorted(function_points.get("function_points", []), key=lambda item: item.get("source_order", 0)):
        if not isinstance(fp, dict):
            continue
        module = str(fp.get("module") or "默认模块").strip()
        if fp.get("requirement_group_id") and fp.get("requirement_group_title"):
            groups_by_module.setdefault(module, (str(fp["requirement_group_id"]), str(fp["requirement_group_title"])))
            continue
        if module not in groups_by_module:
            groups_by_module[module] = (f"REQ-{next_index:02d}", f"需求 {next_index}：{module}")
            next_index += 1
        group_id, group_title = groups_by_module[module]
        fp["requirement_group_id"] = group_id
        fp["requirement_group_title"] = group_title












def _step_to_text(step) -> str:
    if isinstance(step, dict):
        action = str(step.get("action") or "").strip()
        expected = str(step.get("expected") or "").strip()
        if action and expected:
            return f"{action}；期望：{expected}"
        return action or expected or json.dumps(step, ensure_ascii=False)
    return str(step or "").strip()






@dataclass
class GenerationContext:
    """用例生成流水线统一上下文，替代散落的参数传递"""
    job: CaseGenerationJob
    db: object
    api_key: str
    model: str
    base_url: str
    markdown_text: str
    audit_log: list[dict] = field(default_factory=list)
    downloaded_images: list[dict] = field(default_factory=list)
    image_analysis: list[dict] = field(default_factory=list)
    evidence_trace: dict = field(default_factory=dict)
    function_points: dict = field(default_factory=dict)
    pending_confirmations: list = field(default_factory=list)
    testcase_package: dict = field(default_factory=dict)
    review_report: dict = field(default_factory=dict)
    image_links: list[str] = field(default_factory=list)
    output_dir: str = ""
    output_stem: str = ""
    payload: dict = field(default_factory=dict)


def _job_output_dir(job_id: int) -> str:
    root_dir = settings.report_output_dir
    if not os.path.isabs(root_dir):
        root_dir = os.path.abspath(root_dir)
    output_dir = os.path.join(root_dir, "case_generation", f"job_{job_id}")
    _ensure_writable_dir(output_dir)
    return output_dir


def _ensure_writable_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o777)
    except PermissionError:
        # 如果当前用户没有权限修改目录权限，尝试以当前用户权限创建
        pass
    except OSError as e:
        # 记录警告但不中断流程
        import logging
        logging.warning(f"无法设置目录权限 {path}: {e}")
    return path


def _ensure_output_dir_writable(output_dir: str) -> str:
    _ensure_writable_dir(output_dir)
    if not os.access(output_dir, os.W_OK):
        raise PermissionError(f"输出目录不可写：{output_dir}")
    return output_dir


def _make_writable_file(path: str) -> str:
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    return path


def _atomic_replace_file(file_path: str, write_callback) -> str:
    output_dir = _ensure_output_dir_writable(os.path.dirname(file_path))
    base_name = os.path.basename(file_path)
    temp_path = os.path.join(output_dir, f".{base_name}.tmp.{os.getpid()}")
    try:
        write_callback(temp_path)
        _make_writable_file(temp_path)
        os.replace(temp_path, file_path)
        return _make_writable_file(file_path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _write_text_file(output_dir: str, file_name: str, content: str) -> str:
    file_path = os.path.join(output_dir, file_name)

    def _write(path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

    return _atomic_replace_file(file_path, _write)


def _write_json_file(output_dir: str, file_name: str, payload: dict | list) -> str:
    file_path = os.path.join(output_dir, file_name)

    def _write(path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    return _atomic_replace_file(file_path, _write)


def _read_text_if_exists(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _resolve_claw_rules_dir() -> Path:
    raw_value = (settings.case_generation_rules_dir or "").strip()
    if not raw_value:
        return Path()
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = (_BACKEND_ROOT / path).resolve()
    return path


def _load_skill_template(skill_name: str) -> str:
    rules_dir = _resolve_claw_rules_dir()
    if not rules_dir.exists():
        return ""
    schema_map = {
        "requirement-analyzer": ["evidence_trace.template.yaml", "function_points.template.yaml"],
        "testcase-designer": ["testcase_package.template.yaml"],
        "quality-reviewer": ["review_report.template.yaml"],
        "artifact-exporter": ["xmindmark.template.md"],
    }
    parts = []
    for schema_name in schema_map.get(skill_name, []):
        text = _read_text_if_exists(rules_dir / "schemas" / schema_name)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _load_claw_skill_context(skill_name: str) -> str:
    rules_dir = _resolve_claw_rules_dir()
    if not rules_dir.exists():
        return ""
    parts = [
        _read_text_if_exists(rules_dir / "README.md", 18000),
        _read_text_if_exists(rules_dir / "skills" / skill_name / "SKILL.md", 16000),
    ]
    return "\n\n---\n\n".join(part for part in parts if part)


def _gate(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text_contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _significant_requirement_terms(function_points: dict) -> set[str]:
    terms: set[str] = set()
    for fp in function_points.get("function_points", []):
        for field in ("module", "scene", "title", "description"):
            value = str(fp.get(field) or "")
            for term in re.findall(r"[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9_-]{2,}", value):
                if term not in {"功能点", "默认模块", "默认场景", "测试用例", "正常流程", "异常流程", "边界条件"}:
                    terms.add(term)
        for item in fp.get("rules") or []:
            for term in re.findall(r"[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9_-]{2,}", str(item)):
                if len(term) >= 3:
                    terms.add(term)
    return terms


def _persist_stage_artifact(output_dir: str, file_name: str, payload: dict | list) -> None:
    try:
        _write_json_file(output_dir, file_name, payload)
    except Exception:
        pass


# --- Phase 3：schema 字段形态强转（以 claw_5skill_final 模板为准，兼容旧字符串形态） ---

def _coerce_test_data(value) -> list[dict]:
    """test_data 统一为 [{name, value}] 对象数组（兼容旧字符串数组）。"""
    if not value:
        return []
    items: list[dict] = []
    for entry in (value if isinstance(value, list) else [value]):
        if isinstance(entry, dict):
            name = str(entry.get("name") or entry.get("field") or "数据").strip()
            raw_val = entry.get("value")
            val = "" if raw_val is None else (raw_val if isinstance(raw_val, str) else json.dumps(raw_val, ensure_ascii=False))
            items.append({"name": name or "数据", "value": val})
        else:
            text = str(entry)
            sep = "：" if "：" in text else (":" if ":" in text else "")
            if sep:
                name, _, val = text.partition(sep)
                items.append({"name": name.strip() or "数据", "value": val.strip()})
            else:
                items.append({"name": "数据", "value": text})
    return items


def _coerce_source_refs(value) -> list[dict]:
    """source_refs 统一为 [{source_type, doc, section, quote}]（兼容旧字符串数组）。"""
    if not value:
        return []
    items: list[dict] = []
    for entry in (value if isinstance(value, list) else [value]):
        if isinstance(entry, dict):
            serialized = json.dumps(entry, ensure_ascii=False)
            items.append({
                "source_type": str(entry.get("source_type") or ("image" if "IMG-" in serialized else "text")),
                "doc": str(entry.get("doc") or ""),
                "section": str(entry.get("section") or ""),
                "quote": str(entry.get("quote") or entry.get("text") or ""),
            })
        else:
            text = str(entry)
            is_img = "IMG-" in text
            items.append({
                "source_type": "image" if is_img else "text",
                "doc": text if is_img else "",
                "section": "",
                "quote": "" if is_img else text,
            })
    return items


def _coerce_atomicity_check(value) -> dict:
    """atomicity_check 统一为 {passed, issues}（兼容旧字符串）。"""
    if isinstance(value, dict):
        passed = value.get("passed")
        issues = value.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        return {"passed": True if passed is None else bool(passed), "issues": [str(i) for i in issues]}
    return {"passed": True, "issues": []}


def _coerce_review_flags(value) -> dict:
    """review_flags 统一为 {executable_risk, ambiguity_risk}，取值 low/medium/high。"""
    allowed = {"low", "medium", "high"}
    out = {"executable_risk": "low", "ambiguity_risk": "low"}
    if isinstance(value, dict):
        for key in out:
            candidate = str(value.get(key) or "").strip().lower()
            if candidate in allowed:
                out[key] = candidate
    return out


def _sources_from_refs(source_refs) -> list[str]:
    """从 source_refs 派生 traceability.sources 字符串数组。"""
    out: list[str] = []
    for ref in source_refs or []:
        if isinstance(ref, dict):
            source_type = ref.get("source_type")
            if source_type and source_type not in out:
                out.append(source_type)
        elif ref:
            source_type = "image" if "IMG-" in str(ref) else "text"
            if source_type not in out:
                out.append(source_type)
    return out or ["text"]


def _sanitize_file_stem(value: str | None, fallback: str = "testcases") -> str:
    raw = (value or fallback).strip() or fallback
    stem = Path(raw).stem if Path(raw).suffix else raw
    stem = _SAFE_FILENAME_PATTERN.sub("_", stem).strip(" ._")
    return stem[:120] or fallback


def _base_url_for_model(model: str | None) -> str:
    model_id = (model or "").lower()
    if model_id.startswith("qwen"):
        return _QWEN_COMPATIBLE_BASE_URL
    return _OPENAI_BASE_URL


def _extract_raw_url(value: str | None) -> str:
    raw = (value or "").strip()
    match = _MARKDOWN_LINK_ONLY_PATTERN.match(raw)
    if match:
        return match.group(2).strip()
    return raw


def _is_qwen_coding_key(api_key: str | None) -> bool:
    return normalize_model_api_key(api_key).startswith("sk-sp-")


def normalize_model_api_key(api_key: str | None) -> str:
    value = (api_key or "").strip()
    while len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        value = value[1:-1].strip()
    return value.strip("'\" \t\r\n")


def _normalize_model_base_url(model: str | None, base_url: str | None, api_key: str | None = None) -> str:
    raw = _extract_raw_url(base_url)
    model_id = (model or "").lower()
    if not model_id.startswith("qwen"):
        return raw or _OPENAI_BASE_URL
    if not raw:
        return _BAILIAN_BASE_URL if _is_qwen_coding_key(api_key) else _QWEN_COMPATIBLE_BASE_URL
    normalized = raw.rstrip("/")
    if "coding.dashscope.aliyuncs.com" in normalized:
        return _BAILIAN_BASE_URL
    if "coding-intl.dashscope.aliyuncs.com" in normalized:
        return _QWEN_CODING_INTL_BASE_URL
    if "dashscope.aliyuncs.com" in normalized and "/compatible-mode/v1" not in normalized:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if "dashscope-intl.aliyuncs.com" in normalized and "/compatible-mode/v1" not in normalized:
        return "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    if "dashscope-us.aliyuncs.com" in normalized and "/compatible-mode/v1" not in normalized:
        return "https://dashscope-us.aliyuncs.com/compatible-mode/v1"
    return normalized


def validate_model_connection_config(model: str | None, base_url: str | None, api_key: str | None) -> tuple[str, str]:
    normalized_key = normalize_model_api_key(api_key)
    normalized_base_url = _normalize_model_base_url(model, base_url, normalized_key)
    model_id = (model or "").strip() or _DEFAULT_MODEL
    if not normalized_key or normalized_key == _SECRET_SENTINEL:
        return normalized_base_url, model_id

    if model_id.lower().startswith("qwen"):
        if _is_qwen_coding_key(normalized_key):
            if "coding.dashscope.aliyuncs.com/v1" not in normalized_base_url and "coding-intl.dashscope.aliyuncs.com/v1" not in normalized_base_url:
                raise ValueError("以 sk-sp- 开头的阿里云 Coding Plan Key 必须配合 coding.dashscope.aliyuncs.com/v1 或 coding-intl.dashscope.aliyuncs.com/v1 使用")
        else:
            if "/compatible-mode/v1" not in normalized_base_url:
                raise ValueError("Qwen 通用 API Key 需要配合 dashscope 的 compatible-mode/v1 地址使用")
    elif normalized_key.startswith("sk-sp-"):
        raise ValueError("sk-sp- 开头的阿里云 Coding Plan Key 仅支持 Qwen / DashScope 配置，不能用于当前模型")
    elif normalized_base_url.startswith(_BAILIAN_BASE_URL) or normalized_base_url.startswith(_QWEN_CODING_INTL_BASE_URL):
        raise ValueError("coding.dashscope.aliyuncs.com/v1 仅适用于阿里云 Coding Plan 的 Qwen 模型")
    return normalized_base_url, model_id


def sanitize_case_generation_payload(payload: dict | None, *, cleanup_secret: bool = False) -> dict:
    sanitized = dict(payload or {})
    if "openai_api_key" in sanitized:
        if cleanup_secret:
            sanitized["openai_api_key"] = None
        else:
            sanitized["openai_api_key"] = "***已提供***"
    return sanitized


def _update_stage(job: CaseGenerationJob, db, key: str, title: str, status: str, summary: str) -> None:
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    now_iso = utc_now_naive().isoformat()
    updated = False
    for item in stages:
        if item.get("key") == key:
            started_at = item.get("started_at") or now_iso
            item.update({"title": title, "status": status, "summary": summary, "started_at": started_at, "updated_at": now_iso})
            if status == "running":
                item["duration_ms"] = item.get("duration_ms") or 0
            else:
                item["duration_ms"] = _duration_ms_from_iso(started_at, now_iso)
            updated = True
            break
    if not updated:
        stage = {"key": key, "title": title, "status": status, "summary": summary, "started_at": now_iso, "updated_at": now_iso}
        stage["duration_ms"] = 0 if status == "running" else _duration_ms_from_iso(now_iso, now_iso)
        stages.append(stage)
    progress["stages"] = stages
    job.progress_json = progress
    flag_modified(job, "progress_json")
    job.summary = summary
    db.commit()


def _duration_ms_from_iso(started_at: str | None, ended_at: str | None) -> int:
    if not started_at or not ended_at:
        return 0
    try:
        started = datetime.fromisoformat(started_at)
        ended = datetime.fromisoformat(ended_at)
    except ValueError:
        return 0
    return max(int((ended - started).total_seconds() * 1000), 0)


def _mark_last_stage_failed(job: CaseGenerationJob, *, summary: str) -> None:
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    if not stages:
        return
    now_iso = utc_now_naive().isoformat()
    current = stages[-1]
    started_at = current.get("started_at") or now_iso
    current["status"] = "failed"
    current["summary"] = summary
    current["updated_at"] = now_iso
    current["duration_ms"] = _duration_ms_from_iso(started_at, now_iso)
    progress["stages"] = stages
    job.progress_json = progress
    flag_modified(job, "progress_json")


def _raise_if_job_cancelled(db, job_id: int) -> None:
    current = db.get(CaseGenerationJob, job_id)
    if current is not None and current.status == "CANCELLED":
        raise RuntimeError("任务已取消")


def _remove_file_if_exists(path: str | None) -> None:
    if path and os.path.exists(path):
        os.remove(path)


def _cleanup_case_generation_output_dir(output_dir: str, *, keep_paths: set[str] | None = None) -> None:
    if not output_dir or not os.path.isdir(output_dir):
        return
    normalized_keep_paths = {os.path.abspath(path) for path in (keep_paths or set()) if path}
    for entry in os.listdir(output_dir):
        entry_path = os.path.join(output_dir, entry)
        if os.path.abspath(entry_path) in normalized_keep_paths:
            continue
        try:
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
        except OSError:
            pass


def _collect_final_artifact_paths(db, job_id: int) -> set[str]:
    final_artifacts = list(
        db.scalars(
            select(CaseGenerationArtifact).where(
                CaseGenerationArtifact.job_id == job_id,
                CaseGenerationArtifact.artifact_type == "xmind",
            )
        ).all()
    )
    return {artifact.file_path for artifact in final_artifacts if artifact.file_path}


def _delete_case_generation_artifact(db, artifact: CaseGenerationArtifact) -> None:
    _remove_file_if_exists(artifact.file_path)
    db.delete(artifact)


def _cleanup_previous_success_xmind_for_project(db, current_job: CaseGenerationJob) -> None:
    if current_job.project_id is None:
        return
    keep_job_id = current_job.id
    success_jobs = list(
        db.scalars(
            select(CaseGenerationJob)
            .where(
                CaseGenerationJob.project_id == current_job.project_id,
                CaseGenerationJob.status == "SUCCESS",
                CaseGenerationJob.id != keep_job_id,
            )
            .order_by(CaseGenerationJob.finished_at.desc(), CaseGenerationJob.id.desc())
        ).all()
    )
    for job in success_jobs:
        artifacts = list(
            db.scalars(
                select(CaseGenerationArtifact)
                .where(
                    CaseGenerationArtifact.job_id == job.id,
                    CaseGenerationArtifact.artifact_type == "xmind",
                )
                .order_by(CaseGenerationArtifact.id.asc())
            ).all()
        )
        for artifact in artifacts:
            _delete_case_generation_artifact(db, artifact)


def _cleanup_expired_success_xmind(db, *, retention_days: int = 3) -> None:
    cutoff = utc_now_naive() - timedelta(days=retention_days)
    expired_jobs = list(
        db.scalars(
            select(CaseGenerationJob)
            .where(
                CaseGenerationJob.status == "SUCCESS",
                CaseGenerationJob.finished_at.is_not(None),
                CaseGenerationJob.finished_at < cutoff,
            )
            .order_by(CaseGenerationJob.finished_at.asc(), CaseGenerationJob.id.asc())
        ).all()
    )
    for job in expired_jobs:
        artifacts = list(
            db.scalars(
                select(CaseGenerationArtifact)
                .where(
                    CaseGenerationArtifact.job_id == job.id,
                    CaseGenerationArtifact.artifact_type == "xmind",
                )
                .order_by(CaseGenerationArtifact.id.asc())
            ).all()
        )
        for artifact in artifacts:
            _delete_case_generation_artifact(db, artifact)


def _extract_sections(markdown_text: str) -> list[dict]:
    matches = list(_HEADING_PATTERN.finditer(markdown_text))
    if not matches:
        return [{"title": "默认模块", "level": 1, "source_order": 1, "body": markdown_text.strip()}]

    sections: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        sections.append(
            {
                "title": match.group(2).strip(),
                "level": len(match.group(1)),
                "source_order": index + 1,
                "body": markdown_text[start:end].strip(),
            }
        )
    return sections


def _strip_markdown_noise(text: str) -> str:
    value = _HTML_COMMENT_PATTERN.sub("", text or "")
    value = _MARKDOWN_IMAGE_PATTERN.sub("", value)
    value = _HTML_IMAGE_PATTERN.sub("", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _truncate_text(value: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _compact_sections_for_ai(sections: list[dict], *, per_section_limit: int = 2400, total_limit: int = 24000) -> list[dict]:
    compacted: list[dict] = []
    total = 0
    
    # 关键段落优先策略：L1/L2 标题及其首段必须保留
    for item in sections:
        level = item.get("level", 3)
        body = _strip_markdown_noise(item.get("body") or "")
        
        # L1/L2 章节保留更多文本（关键架构信息）
        if level <= 2:
            body = _truncate_text(body, per_section_limit)
        else:
            # L3+ 章节仅保留首段和关键规则（节省 Token）
            first_para = body.split("\n\n")[0] if body else ""
            body = _truncate_text(first_para, per_section_limit // 2)
        
        payload = {
            "title": item["title"],
            "level": item["level"],
            "source_order": item["source_order"],
            "body": body,
        }
        total += len(body)
        compacted.append(payload)
        if total >= total_limit:
            break
    return compacted


def _compact_image_analysis_for_ai(image_analysis: list[dict], *, limit: int = 12) -> list[dict]:
    compacted = []
    for item in image_analysis[:limit]:
        compacted.append(
            {
                "image_id": item.get("image_id"),
                "summary": _truncate_text(str(item.get("summary") or ""), 500),
                "requirement_hints": list(item.get("requirement_hints") or [])[:8],
                "risk_or_unclear": list(item.get("risk_or_unclear") or [])[:5],
            }
        )
    return compacted


def _build_requirement_section_batches(compact_sections: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_size = 0
    first_non_empty_reserved = False
    for section in compact_sections:
        body_size = len(section.get("body") or "")
        if body_size == 0:
            continue
        if not first_non_empty_reserved:
            batches.append([section])
            first_non_empty_reserved = True
            continue
        section_size = body_size + len(section.get("title") or "")
        if section_size >= _REQUIREMENT_BATCH_TEXT_LIMIT:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_size = 0
            batches.append([section])
            continue
        if current_batch and current_size + section_size > _REQUIREMENT_BATCH_TEXT_LIMIT:
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append(section)
        current_size += section_size
    if current_batch:
        batches.append(current_batch)
    return batches or [[]]


def _compact_downloaded_images_for_ai(downloaded_images: list[dict], *, limit: int = 20) -> list[dict]:
    compacted = []
    for item in downloaded_images[:limit]:
        compacted.append(
            {
                "image_id": item.get("image_id"),
                "url": item.get("url"),
                "file_name": item.get("file_name"),
                "download_status": item.get("download_status"),
                "error": _truncate_text(str(item.get("error") or ""), 300) or None,
            }
        )
    return compacted


def _html_to_text(content: str) -> str:
    sanitized = _HTML_BLOCK_PATTERN.sub("", content)
    sanitized = re.sub(r"</(p|div|section|article|li|ul|ol|h[1-6]|br)>", "\n", sanitized, flags=re.IGNORECASE)
    sanitized = _HTML_TAG_PATTERN.sub(" ", sanitized)
    sanitized = (
        sanitized.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    lines = [line.strip() for line in sanitized.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _fetch_source_url(source_url: str) -> str:
    response = httpx.get(
        source_url,
        follow_redirects=True,
        timeout=30.0,
        headers={"User-Agent": "PPPTest-CaseGenerator/1.0"},
    )
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    text = response.text
    if "text/html" in content_type:
        image_links = [urljoin(source_url, item) for item in _HTML_IMAGE_PATTERN.findall(text)]
        image_markdown = "\n".join(f"![页面图片]({item})" for item in sorted(set(image_links)))
        body_text = _html_to_text(text)
        return f"{body_text}\n\n{image_markdown}".strip()
    return text.strip()


def _resolve_markdown_text(payload: dict) -> str:
    markdown_text = (payload.get("markdown_text") or "").strip()
    if markdown_text:
        return markdown_text
    source_url = (payload.get("source_url") or "").strip()
    if source_url:
        return _fetch_source_url(source_url)
    return ""


def _extract_image_links(markdown_text: str) -> list[str]:
    links = [item.strip() for item in _MARKDOWN_IMAGE_PATTERN.findall(markdown_text)]
    links.extend(item.strip() for item in _HTML_IMAGE_PATTERN.findall(markdown_text))
    return sorted({item for item in links if item and not item.startswith("data:")})


async def _download_single_image_async(client: httpx.AsyncClient, *, index: int, url: str, image_dir: str) -> dict:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        suffix = ".png"
    file_name = f"image_{index:02d}{suffix}"
    file_path = os.path.join(image_dir, file_name)
    record = {"image_id": f"IMG-{index:03d}", "url": url, "file_name": file_name, "file_path": file_path}
    try:
        response = await client.get(
            url,
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": "PPPTest-CaseGenerator/1.0"},
        )
        response.raise_for_status()

        def _write_image(path: str, content: bytes = response.content) -> None:
            with open(path, "wb") as handle:
                handle.write(content)

        _atomic_replace_file(file_path, _write_image)
        record.update({"download_status": "success", "size_bytes": os.path.getsize(file_path)})
    except Exception as exc:
        record.update({"download_status": "failed", "error": str(exc), "file_path": None})
    return record


async def _download_image_links_async(image_links: list[str], output_dir: str) -> list[dict]:
    image_dir = os.path.join(output_dir, "images")
    _ensure_writable_dir(image_dir)
    async with httpx.AsyncClient() as client:
        return await _gather_limited(
            [
                _download_single_image_async(client, index=index, url=url, image_dir=image_dir)
                for index, url in enumerate(image_links, start=1)
            ]
        )


def _download_image_links(image_links: list[str], output_dir: str) -> list[dict]:
    return asyncio.run(_download_image_links_async(image_links, output_dir))


def _image_to_data_url(file_path: str) -> str:
    media_type = mimetypes.guess_type(file_path)[0] or "image/png"
    with open(file_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def _json_from_model_text(text: str) -> dict:
    stripped = (text or "").strip()
    match = _JSON_FENCE_PATTERN.search(stripped)
    if match:
        stripped = match.group(1).strip()
    stripped = _extract_complete_json_object(stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as json_exc:
        try:
            parsed = yaml.safe_load(stripped)
        except yaml.YAMLError as yaml_exc:
            raise ValueError(
                f"模型输出不是合法 JSON/YAML 对象，可能被截断或存在未闭合引号：{yaml_exc}"
            ) from json_exc
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("模型输出不是 JSON/YAML 对象，请只返回一个合法 JSON 对象") from json_exc


def _extract_complete_json_object(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("模型输出为空")
    start = stripped.find("{")
    if start < 0:
        raise ValueError("模型输出缺少 JSON 对象起始符 `{`")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    raise ValueError("模型输出 JSON 对象不完整，可能因 max_tokens 或模型响应中断被截断")


async def _gather_limited(coros, *, limit: int = _CASE_GENERATION_MAX_CONCURRENCY):
    semaphore = asyncio.Semaphore(limit)

    async def run_one(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run_one(coro) for coro in coros))


def _is_non_retryable_model_error(error: Exception | str) -> bool:
    text = str(error).lower()
    permanent_markers = (
        "请提供有效的 openai api key",
        "invalid_api_key",
        "incorrect api key",
        "invalid access token",
        "token expired",
        "http 400",
        "http 401",
        "http 403",
        "model not found",
        "does not exist",
        "仅支持",
        "must be used",
        "需要配合",
    )
    return any(marker in text for marker in permanent_markers)


def _compact_pending_confirmations_for_ai(items: list | None, *, limit: int = _PENDING_CONFIRMATION_LIMIT) -> list[dict]:
    compacted: list[dict] = []
    for item in (items or [])[:limit]:
        if not isinstance(item, dict):
            compacted.append({"item": _truncate_text(str(item), _PENDING_CONFIRMATION_TEXT_LIMIT)})
            continue
        compacted.append(
            {
                "item": _truncate_text(str(item.get("item") or item.get("focus") or item.get("message") or item.get("reason") or ""), _PENDING_CONFIRMATION_TEXT_LIMIT),
                "reason": _truncate_text(str(item.get("reason") or item.get("message") or ""), _PENDING_CONFIRMATION_TEXT_LIMIT),
                "status": item.get("status") or "pending",
                "source": item.get("source") or "",
            }
        )
    return compacted


def _compact_function_points_for_ai(function_points: list[dict]) -> list[dict]:
    compacted: list[dict] = []
    for item in function_points:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "fp_id": item.get("fp_id"),
                "module": _truncate_text(str(item.get("module") or ""), 80),
                "scene": _truncate_text(str(item.get("scene") or ""), 80),
                "requirement_group_id": item.get("requirement_group_id"),
                "requirement_group_title": _truncate_text(str(item.get("requirement_group_title") or ""), 80),
                "title": _truncate_text(str(item.get("title") or ""), 120),
                "type": item.get("type"),
                "description": _truncate_text(str(item.get("description") or ""), _FUNCTION_POINT_TEXT_LIMIT),
                "source_refs": list(item.get("source_refs") or [])[:6],
                "rules": [_truncate_text(str(rule), 140) for rule in list(item.get("rules") or [])[:6]],
                "test_hints": {
                    "positive": [_truncate_text(str(text), 140) for text in list((item.get("test_hints") or {}).get("positive") or [])[:3]],
                    "boundary": [_truncate_text(str(text), 140) for text in list((item.get("test_hints") or {}).get("boundary") or [])[:3]],
                    "negative": [_truncate_text(str(text), 140) for text in list((item.get("test_hints") or {}).get("negative") or [])[:3]],
                },
                "priority_hint": item.get("priority_hint"),
                "source_order": item.get("source_order"),
            }
        )
    return compacted


async def _call_openai_text_async(
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    system_prompt: str,
    user_content: str | list,
    max_tokens: int = 12000,
    timeout_seconds: float = _DEFAULT_CHAT_TIMEOUT_SECONDS,
) -> dict:
    if not api_key or api_key == _SECRET_SENTINEL:
        raise ValueError("请提供有效的 OpenAI API Key")
    payload = {
        "model": model or _DEFAULT_MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
    }
    endpoint = f"{(base_url or _OPENAI_BASE_URL).rstrip('/')}/chat/completions"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except httpx.ReadTimeout as exc:
        raise RuntimeError(f"模型响应超时（>{int(timeout_seconds)}s），请重试或缩小需求范围") from exc
    except httpx.HTTPStatusError as exc:
        try:
            error_payload = exc.response.json().get("error", {})
            message = error_payload.get("message") or str(exc)
        except Exception:
            message = exc.response.text[:500] or str(exc)
        raise RuntimeError(f"OpenAI 请求失败，HTTP {exc.response.status_code}：{message}") from exc
    except Exception as exc:
        raise RuntimeError(f"模型请求过程中发生未知错误：{str(exc)}") from exc


async def _call_openai_json_async(
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    system_prompt: str,
    user_content: str | list,
    max_tokens: int = 12000,
    timeout_seconds: float = _DEFAULT_CHAT_TIMEOUT_SECONDS,
) -> dict:
    content = await _call_openai_text_async(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )
    try:
        return _json_from_model_text(content)
    except ValueError as exc:
        raise ModelJSONParseError(str(exc), raw_text=content) from exc


def _call_openai_json(**kwargs) -> dict:
    return asyncio.run(_call_openai_json_async(**kwargs))


async def _repair_model_json_async(
    *,
    api_key: str,
    model: str,
    base_url: str | None,
    skill_name: str,
    raw_text: str,
    parse_error: str,
    output_contract: str,
    timeout_seconds: float,
) -> dict:
    system_prompt = (
        "你是 JSON 修复器，只能修复格式错误，不能新增、删除或改写业务语义。\n"
        "忽略 <thinking>、Markdown 包裹和多余解释，只返回一个合法 JSON 对象。"
    )
    user_content = json.dumps(
        {
            "skill_name": skill_name,
            "parse_error": parse_error,
            "target_schema": output_contract,
            "bad_output": _truncate_text(raw_text, 20000),
            "rules": [
                "只修复 JSON/YAML 结构、引号、逗号、括号、转义和顶级对象包裹问题",
                "不得重新生成业务内容",
                "不得输出 Markdown 或解释文字",
            ],
        },
        ensure_ascii=False,
    )
    repaired_text = await _call_openai_text_async(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=8000,
        timeout_seconds=timeout_seconds,
    )
    try:
        return _json_from_model_text(repaired_text)
    except ValueError as exc:
        raise ModelJSONParseError(str(exc), raw_text=repaired_text) from exc


async def _call_skill_with_gate_async(
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    skill_name: str,
    task_payload: dict | list,
    output_contract: str | None = None,
    validator,
    max_tokens: int,
    timeout_seconds: float = _DEFAULT_CHAT_TIMEOUT_SECONDS,
    max_attempts: int | None = None,
    audit_log: list[dict] | None = None,
    progress_callback=None,
) -> dict:
    if not output_contract:
        output_contract = _load_skill_template(skill_name)
        if not output_contract:
            output_contract = "合法 JSON，必须包含所需的核心字段"

    skill_context = _load_claw_skill_context(skill_name)
    last_error = ""
    attempt_count = max_attempts or (_MAX_AI_RETRIES + 1)
    for attempt in range(1, attempt_count + 1):
        started = time.perf_counter()
        effective_max_tokens = min(_MAX_JSON_RETRY_TOKENS, int(max_tokens * (1 + 0.5 * (attempt - 1))))
        compression_note = (
            "\n\n【本次重试要求】上一次输出疑似被截断。请保留所有必需字段，但压缩描述性文字，"
            "优先保证 JSON 结构闭合、顶级键完整、数组元素完整。"
            if last_error and _is_incomplete_json_error(last_error)
            else ""
        )
        retry_note = (
            f"\n\n【上一次尝试失败】\n错误详情：{last_error}\n"
            "请在最终 JSON 前使用 <thinking> 标签分析错误原因，然后严格对照 Schema 修正后重新输出。"
            if last_error else ""
        )
        top_level_keys = []
        try:
            if output_contract:
                contract_dict = json.loads(output_contract)
                top_level_keys = list(contract_dict.keys())
        except Exception:
            pass
        
        structure_hint = ""
        if top_level_keys:
            key_lines = "\n".join(f"- `{key}`" for key in top_level_keys)
            example_lines = "\n".join(f'  "{key}": {json.dumps(contract_dict.get(key, {}), ensure_ascii=False)}' for key in top_level_keys)
            structure_hint = (
                "【强制输出结构】你必须返回一个 JSON 对象，且必须包含以下顶级键：\n"
                f"{key_lines}\n\n"
                "【输出示例】\n"
                "{\n"
                f"{example_lines}\n"
                "}\n\n"
            )
        
        system_prompt = (
            f"你正在执行 claw_5skill_final 的 {skill_name}。\n\n"
            f"{structure_hint}"
            f"【强制 JSON 结构】\n{output_contract}\n\n"
            "必须严格遵守以上 schema。为了确保质量，建议你在输出 JSON 之前先在 <thinking> 标签中进行深度分析。\n"
            "只输出合法 JSON，不输出 Markdown（除非在 <thinking> 中），不输出解释文字。\n\n"
            f"{skill_context}\n\n"
            f"{retry_note}"
            f"{compression_note}"
        )
        
        if isinstance(task_payload, dict):
            task_payload = dict(task_payload)
            task_payload["required_output_format"] = output_contract
            task_payload["output_format_note"] = "你必须返回一个包含以下顶级键的 JSON 对象：" + ", ".join(top_level_keys)
        
        if progress_callback:
            progress_callback(f"正在调用 {skill_name} (第 {attempt}/{attempt_count} 次)...")
        
        try:
            result = await _call_openai_json_async(
                api_key=api_key,
                model=model,
                base_url=base_url,
                system_prompt=system_prompt,
                user_content=json.dumps(task_payload, ensure_ascii=False),
                max_tokens=effective_max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except ModelJSONParseError as exc:
            if _is_incomplete_json_error(exc):
                duration_ms = int((time.perf_counter() - started) * 1000)
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": skill_name,
                            "attempt": attempt,
                            "status": "json_incomplete",
                            "duration_ms": duration_ms,
                            "error": str(exc),
                            "max_tokens": effective_max_tokens,
                        }
                    )
                last_error = str(exc)
                if progress_callback and attempt < attempt_count:
                    progress_callback(f"{skill_name} 输出疑似被截断，正在自动放大输出预算重试")
                continue
            repair_started = time.perf_counter()
            try:
                result = await _repair_model_json_async(
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    skill_name=skill_name,
                    raw_text=exc.raw_text,
                    parse_error=str(exc),
                    output_contract=output_contract,
                    timeout_seconds=timeout_seconds,
                )
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": skill_name,
                            "attempt": attempt,
                            "status": "json_repaired",
                            "duration_ms": int((time.perf_counter() - repair_started) * 1000),
                            "error": str(exc),
                        }
                    )
                if progress_callback:
                    progress_callback(f"{skill_name} JSON 修复通过")
            except Exception as repair_exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": skill_name,
                            "attempt": attempt,
                            "status": "json_repair_failed",
                            "duration_ms": duration_ms,
                            "error": str(repair_exc),
                        }
                    )
                last_error = str(repair_exc)
                if _is_non_retryable_model_error(repair_exc):
                    raise ValueError(f"{skill_name} 遇到不可重试错误：{last_error}") from repair_exc
                continue
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if audit_log is not None:
                audit_log.append(
                    {
                        "skill": skill_name,
                        "attempt": attempt,
                        "status": "api_failed",
                        "duration_ms": duration_ms,
                        "error": str(exc),
                    }
                )
            last_error = str(exc)
            if _is_non_retryable_model_error(exc):
                raise ValueError(f"{skill_name} 遇到不可重试错误：{last_error}") from exc
            continue
        
        if progress_callback:
            progress_callback(f"正在校验 {skill_name} 输出格式...")
        
        try:
            validator(result)
            duration_ms = int((time.perf_counter() - started) * 1000)
            if audit_log is not None:
                audit_log.append(
                    {
                        "skill": skill_name,
                        "attempt": attempt,
                        "status": "passed",
                        "duration_ms": duration_ms,
                        "error": None,
                    }
                )
            if progress_callback:
                progress_callback(f"{skill_name} 校验通过")
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if audit_log is not None:
                audit_log.append(
                    {
                        "skill": skill_name,
                        "attempt": attempt,
                        "status": "gate_failed",
                        "duration_ms": duration_ms,
                        "error": str(exc),
                    }
                )
            last_error = str(exc)
            if progress_callback:
                progress_callback(f"{skill_name} 校验失败：{str(exc)[:100]}...")
    raise ValueError(f"{skill_name} 多次重试后仍未通过门禁：{last_error}")


def _call_skill_with_gate(
    *,
    api_key: str,
    model: str,
    base_url: str | None = None,
    skill_name: str,
    task_payload: dict | list,
    output_contract: str | None = None,
    validator,
    max_tokens: int,
    timeout_seconds: float = _DEFAULT_CHAT_TIMEOUT_SECONDS,
    max_attempts: int | None = None,
    audit_log: list[dict] | None = None,
    progress_callback=None,
) -> dict:
    if not output_contract:
        output_contract = _load_skill_template(skill_name)
        if not output_contract:
            output_contract = "合法 JSON，必须包含所需的核心字段"

    skill_context = _load_claw_skill_context(skill_name)
    last_error = ""
    attempt_count = max_attempts or (_MAX_AI_RETRIES + 1)
    for attempt in range(1, attempt_count + 1):
        started = time.perf_counter()
        effective_max_tokens = min(_MAX_JSON_RETRY_TOKENS, int(max_tokens * (1 + 0.5 * (attempt - 1))))
        compression_note = (
            "\n\n【本次重试要求】上一次输出疑似被截断。请保留所有必需字段，但压缩描述性文字，"
            "优先保证 JSON 结构闭合、顶级键完整、数组元素完整。"
            if last_error and _is_incomplete_json_error(last_error)
            else ""
        )
        retry_note = f"\n\n上一次输出未通过门禁，错误原因：{last_error}\n请对照 Schema 严格修正后重新输出。" if last_error else ""
        top_level_keys = []
        try:
            if output_contract:
                contract_dict = json.loads(output_contract)
                top_level_keys = list(contract_dict.keys())
        except Exception:
            pass
        
        structure_hint = ""
        if top_level_keys:
            key_lines = "\n".join(f"- `{key}`" for key in top_level_keys)
            example_lines = "\n".join(f'  "{key}": {json.dumps(contract_dict.get(key, {}), ensure_ascii=False)}' for key in top_level_keys)
            structure_hint = (
                "【强制输出结构】你必须返回一个 JSON 对象，且必须包含以下顶级键：\n"
                f"{key_lines}\n\n"
                "【输出示例】\n"
                "{\n"
                f"{example_lines}\n"
                "}\n\n"
            )
        
        system_prompt = (
            f"你正在执行 claw_5skill_final 的 {skill_name}。\n\n"
            f"{structure_hint}"
            f"【强制 JSON 结构】\n{output_contract}\n\n"
            "必须严格遵守以上 schema。只输出合法 JSON，不输出 Markdown，不输出解释文字。\n\n"
            f"{skill_context}\n\n"
            f"{retry_note}"
            f"{compression_note}"
        )
        
        if isinstance(task_payload, dict):
            task_payload = dict(task_payload)
            task_payload["required_output_format"] = output_contract
            task_payload["output_format_note"] = "你必须返回一个包含以下顶级键的 JSON 对象：" + ", ".join(top_level_keys)
        
        if progress_callback:
            progress_callback(f"正在调用 {skill_name} (第 {attempt}/{attempt_count} 次)...")
        
        try:
            result = _call_openai_json(
                api_key=api_key,
                model=model,
                base_url=base_url,
                system_prompt=system_prompt,
                user_content=json.dumps(task_payload, ensure_ascii=False),
                max_tokens=effective_max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except ModelJSONParseError as exc:
            if _is_incomplete_json_error(exc):
                duration_ms = int((time.perf_counter() - started) * 1000)
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": skill_name,
                            "attempt": attempt,
                            "status": "json_incomplete",
                            "duration_ms": duration_ms,
                            "error": str(exc),
                            "max_tokens": effective_max_tokens,
                        }
                    )
                last_error = str(exc)
                if progress_callback and attempt < attempt_count:
                    progress_callback(f"{skill_name} 输出疑似被截断，正在自动放大输出预算重试")
                continue
            repair_started = time.perf_counter()
            try:
                result = asyncio.run(_repair_model_json_async(
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    skill_name=skill_name,
                    raw_text=exc.raw_text,
                    parse_error=str(exc),
                    output_contract=output_contract,
                    timeout_seconds=timeout_seconds,
                ))
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": skill_name,
                            "attempt": attempt,
                            "status": "json_repaired",
                            "duration_ms": int((time.perf_counter() - repair_started) * 1000),
                            "error": str(exc),
                        }
                    )
                if progress_callback:
                    progress_callback(f"{skill_name} JSON 修复通过")
            except Exception as repair_exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": skill_name,
                            "attempt": attempt,
                            "status": "json_repair_failed",
                            "duration_ms": duration_ms,
                            "error": str(repair_exc),
                        }
                    )
                last_error = str(repair_exc)
                if _is_non_retryable_model_error(repair_exc):
                    raise ValueError(f"{skill_name} 遇到不可重试错误：{last_error}") from repair_exc
                continue
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if audit_log is not None:
                audit_log.append(
                    {
                        "skill": skill_name,
                        "attempt": attempt,
                        "status": "api_failed",
                        "duration_ms": duration_ms,
                        "error": str(exc),
                    }
                )
            last_error = str(exc)
            if _is_non_retryable_model_error(exc):
                raise ValueError(f"{skill_name} 遇到不可重试错误：{last_error}") from exc
            continue
        
        if progress_callback:
            progress_callback(f"正在校验 {skill_name} 输出格式...")
        
        try:
            validator(result)
            duration_ms = int((time.perf_counter() - started) * 1000)
            if audit_log is not None:
                audit_log.append(
                    {
                        "skill": skill_name,
                        "attempt": attempt,
                        "status": "passed",
                        "duration_ms": duration_ms,
                        "error": None,
                    }
                )
            if progress_callback:
                progress_callback(f"{skill_name} 校验通过")
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            if audit_log is not None:
                audit_log.append(
                    {
                        "skill": skill_name,
                        "attempt": attempt,
                        "status": "gate_failed",
                        "duration_ms": duration_ms,
                        "error": str(exc),
                    }
                )
            last_error = str(exc)
            if progress_callback:
                progress_callback(f"{skill_name} 校验失败：{str(exc)[:100]}...")
    raise ValueError(f"{skill_name} 多次重试后仍未通过门禁：{last_error}")


def _build_orchestration_plan(job: CaseGenerationJob, payload: dict, markdown_text: str, image_links: list[str]) -> dict:
    sections = _extract_sections(markdown_text)
    return {
        "job_id": job.id,
        "job_name": job.name,
        "source_document_name": job.source_document_name,
        "source_type": payload.get("source_type") or "PASTE",
        "output_stem": _sanitize_file_stem(job.source_document_name or job.name),
        "mode": "full",
        "skill_flow": [
            "requirement-analyzer",
            "testcase-designer",
            "quality-reviewer",
            "deterministic-xmind-exporter",
        ],
        "section_count": len(sections),
        "image_link_count": len(image_links),
        "sections": [{"title": item["title"], "level": item["level"], "source_order": item["source_order"]} for item in sections],
        "constraints": [
            "模块顺序必须遵循需求文档原始章节顺序",
            "图片链接必须先下载并分析，再做正文理解",
            "最终只突出同名 XMind 文件",
            "XMind 必须由后端根据 TestcasePackage 确定性展开，并由 xmindmark CLI 转换生成",
        ],
    }


async def _analyze_image_batch_async(
    *,
    api_key: str,
    model: str,
    base_url: str,
    batch: list[dict],
) -> list[dict]:
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "你现在处于 claw_5skill_final 的 【阶段 1：Image-First Scan】。\n"
                "目标：建立界面结构视图，识别所有真实可见的界面元素。\n"
                "输出格式：必须是合法 JSON，结构如下：\n"
                '{"images":[{"image_id":"IMG-001","summary":"...","ui_elements":["..."],"requirement_hints":["..."],"risk_or_unclear":["..."]}]}\n'
                "注意：只描述真实可见信息，严禁脑补。每张图片必须有对应记录。"
            ),
        }
    ]
    for item in batch:
        content.append({"type": "text", "text": f"图片 ID: {item['image_id']}，来源 URL: {item['url']}"})
        content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(item["file_path"])}})
    result = await _call_openai_json_async(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=(
            "你正在执行 claw_5skill_final 的 requirement-analyzer 识图阶段。\n"
            "必须输出合法 JSON，且每张成功下载的图片都要有识别结论；绝不能用链接或正文描述替代实际识图。"
        ),
        user_content=content,
        max_tokens=4200,
        timeout_seconds=_DEFAULT_CHAT_TIMEOUT_SECONDS,
    )
    return result.get("images") or []


async def _analyze_images_async(api_key: str, model: str, base_url: str, downloaded_images: list[dict]) -> list[dict]:
    successful = [item for item in downloaded_images if item.get("download_status") == "success" and item.get("file_path")]
    if not successful:
        return []

    batches = [
        successful[offset : offset + _IMAGE_ANALYSIS_BATCH_SIZE]
        for offset in range(0, len(successful), _IMAGE_ANALYSIS_BATCH_SIZE)
    ]
    batch_results = await _gather_limited(
        [
            _analyze_image_batch_async(api_key=api_key, model=model, base_url=base_url, batch=batch)
            for batch in batches
        ]
    )
    images = [image for batch_images in batch_results for image in batch_images]

    observed_ids = {item.get("image_id") for item in images}
    missing = [item["image_id"] for item in successful if item["image_id"] not in observed_ids]
    _gate(not missing, f"图片识别结果缺少：{', '.join(missing)}")
    return images


def _analyze_images(api_key: str, model: str, base_url: str, downloaded_images: list[dict]) -> list[dict]:
    return asyncio.run(_analyze_images_async(api_key, model, base_url, downloaded_images))


def _build_requirement_analysis(
    *,
    job: CaseGenerationJob,
    db=None,
    markdown_text: str,
    downloaded_images: list[dict],
    image_analysis: list[dict],
    api_key: str,
    model: str,
    base_url: str | None = None,
    audit_log: list[dict] | None = None,
) -> dict:
    sections = _extract_sections(markdown_text)
    failed_images = [item for item in downloaded_images if item.get("download_status") == "failed"]
    compact_sections = _compact_sections_for_ai(
        sections,
        per_section_limit=_REQUIREMENT_SECTION_TEXT_LIMIT,
        total_limit=_REQUIREMENT_TOTAL_TEXT_LIMIT,
    )
    compact_downloaded_images = _compact_downloaded_images_for_ai(downloaded_images)
    compact_image_analysis = _compact_image_analysis_for_ai(image_analysis)
    image_analysis_by_id = {
        item.get("image_id"): item
        for item in compact_image_analysis
        if isinstance(item, dict) and item.get("image_id")
    }

    def validate(result: dict, expected_images: list[dict], *, require_function_points: bool = True) -> None:
        _gate(isinstance(result, dict), f"AI 返回了非字典类型：{type(result).__name__}，请确保输出为 JSON 对象")
        evidence = result.get("evidence_trace") or {}
        fp_payload = result.get("function_points")
        if isinstance(fp_payload, dict):
            fps = fp_payload.get("function_points") or []
        elif isinstance(fp_payload, list):
            fps = fp_payload
        else:
            fps = []
        _gate(isinstance(evidence, dict), "缺少 evidence_trace")
        _gate("image_summary" in evidence, "EvidenceTrace 缺少 image_summary")
        _gate("images" in evidence, "EvidenceTrace 缺少 images")
        _gate("pending_confirmations" in evidence, "EvidenceTrace 缺少 pending_confirmations")
        successful_expected_images = [item for item in expected_images if item.get("download_status") == "success"]
        failed_expected_images = [item for item in expected_images if item.get("download_status") == "failed"]
        if successful_expected_images:
            image_records = evidence.get("images") or []
            _gate(all(isinstance(item, dict) for item in image_records), "EvidenceTrace images 必须是对象数组")
            recorded_ids = {item.get("image_id") for item in image_records}
            expected_ids = {item.get("image_id") for item in successful_expected_images}
            _gate(expected_ids.issubset(recorded_ids), "EvidenceTrace 未记录全部图片下载与识图结果")
        if failed_expected_images:
            pending_text = json.dumps(evidence.get("pending_confirmations") or [], ensure_ascii=False)
            for image in failed_expected_images:
                _gate(image.get("image_id") in pending_text or image.get("url") in pending_text, "下载失败图片未进入待确认清单")
        _gate(isinstance(fps, list), "FunctionPoints function_points 必须是数组")
        if require_function_points:
            _gate(len(fps) > 0, "FunctionPoints 为空")
        required = {"fp_id", "module", "scene", "title", "type", "description", "source_refs", "rules", "test_hints", "priority_hint", "atomicity_check", "source_distribution", "source_order"}
        valid_dist_values = {"text_only", "text_and_image", "image_or_inferred"}
        for fp in fps:
            _gate(isinstance(fp, dict), "FunctionPoints function_points 必须是对象数组")
            missing = sorted(key for key in required if key not in fp)
            _gate(not missing, f"功能点 {fp.get('fp_id')} 缺少字段：{', '.join(missing)}")
            dist = fp.get("source_distribution") or {}
            dist_val = dist if isinstance(dist, str) else (list(dist.values())[0] if dist else "")
            _gate(dist_val in valid_dist_values, f"功能点 {fp.get('fp_id')} source_distribution 必须为 text_only/text_and_image/image_or_inferred 之一")
            if "image" in str(dist_val):
                refs = fp.get("source_refs") or []
                has_img_ref = "IMG-" in json.dumps(refs, ensure_ascii=False)
                _gate(has_img_ref, f"功能点 {fp.get('fp_id')} 标记了图片来源但 source_refs 未引用 IMG-XXX")
            hints = fp.get("test_hints") or {}
            _gate(all(hints.get(key) for key in ("positive", "boundary", "negative")), f"功能点 {fp.get('fp_id')} test_hints 不完整")

    def normalize_batch_result(result: dict, expected_images: list[dict]) -> dict:
        evidence = result.get("evidence_trace") or {}
        evidence.setdefault("image_summary", "无图片证据")
        evidence.setdefault("images", [])
        evidence.setdefault("pending_confirmations", [])
        image_records = evidence.get("images") or []
        successful_expected_images = [item for item in expected_images if item.get("download_status") == "success"]
        failed_expected_images = [item for item in expected_images if item.get("download_status") == "failed"]
        if successful_expected_images and image_records and not all(isinstance(item, dict) for item in image_records):
            normalized_images = []
            for index, item in enumerate(image_records):
                expected = successful_expected_images[min(index, len(successful_expected_images) - 1)]
                normalized_images.append(
                    {
                        "image_id": expected.get("image_id"),
                        "summary": str(item),
                        "source_url": expected.get("url"),
                    }
                )
            evidence["images"] = normalized_images
            result["evidence_trace"] = evidence
        image_records = evidence.get("images") or []
        if not isinstance(image_records, list):
            image_records = []
        normalized_image_records = [item for item in image_records if isinstance(item, dict)]
        recorded_ids = {item.get("image_id") for item in normalized_image_records if item.get("image_id")}
        for image in successful_expected_images:
            image_id = image.get("image_id")
            if not image_id or image_id in recorded_ids:
                continue
            analyzed = image_analysis_by_id.get(image_id) or {}
            normalized_image_records.append(
                {
                    "image_id": image_id,
                    "summary": analyzed.get("summary") or f"{image_id} 已在图片识别阶段完成分析",
                    "source_url": image.get("url") or analyzed.get("source_url") or "",
                }
            )
            recorded_ids.add(image_id)
        evidence["images"] = normalized_image_records
        result["evidence_trace"] = evidence
        pending_confirmations = evidence.get("pending_confirmations")
        if not isinstance(pending_confirmations, list):
            pending_confirmations = []
        pending_text = json.dumps(pending_confirmations, ensure_ascii=False)
        for image in failed_expected_images:
            image_id = image.get("image_id")
            url = image.get("url")
            if (image_id and image_id in pending_text) or (url and url in pending_text):
                continue
            pending_confirmations.append(
                {
                    "item": image_id or url or "下载失败图片",
                    "reason": f"图片下载失败，无法进入识图阶段：{url or image_id}",
                    "status": "pending",
                }
            )
        evidence["pending_confirmations"] = pending_confirmations
        result["evidence_trace"] = evidence
        fp_payload = result.get("function_points") or {}
        batch_fps = fp_payload.get("function_points") if isinstance(fp_payload, dict) else fp_payload
        if isinstance(batch_fps, list):
            for index, fp in enumerate(batch_fps, start=1):
                if not isinstance(fp, dict):
                    continue
                fp.setdefault("fp_id", f"FP-TEMP-{index:03d}")
                fp.setdefault("module", fp.get("scene") or "需求模块")
                fp.setdefault("scene", fp.get("module") or "需求场景")
                fp.setdefault("title", fp.get("description") or fp.get("scene") or "未命名功能点")
                fp.setdefault("type", "functional")
                fp.setdefault("description", fp.get("title") or "从需求章节提取的功能点")
                fp["source_refs"] = _coerce_source_refs(fp.get("source_refs"))
                fp.setdefault("rules", [])
                fp.setdefault("priority_hint", "P1")
                fp["priority_hint"] = _normalize_priority(fp.get("priority_hint"), fp=fp)
                fp.setdefault("requirement_group_id", "")
                fp.setdefault("requirement_group_title", "")
                fp["atomicity_check"] = _coerce_atomicity_check(fp.get("atomicity_check"))
                fp.setdefault("source_distribution", {})
                fp.setdefault("source_order", index)
                for _list_field in ("actors", "entries", "preconditions", "outputs", "exceptions", "dependencies", "inputs", "states"):
                    fp.setdefault(_list_field, [])
                hints = fp.get("test_hints")
                if not isinstance(hints, dict):
                    hints = {}
                title = fp.get("title") or fp.get("description") or "当前功能点"
                if not hints.get("positive"):
                    hints["positive"] = [f"验证{title}的主流程是否符合需求"]
                if not hints.get("boundary"):
                    hints["boundary"] = [f"验证{title}相关输入、枚举或组合条件的边界情况"]
                if not hints.get("negative"):
                    hints["negative"] = [f"验证{title}在缺失、非法或异常条件下的处理"]
                fp["test_hints"] = hints
            if isinstance(fp_payload, dict):
                fp_payload["function_points"] = batch_fps
                result["function_points"] = fp_payload
            else:
                result["function_points"] = {"function_points": batch_fps}
            _assign_requirement_groups(result["function_points"])
        return result

    async def call_batch_async(batch_sections: list[dict], batch_index: int, batch_count: int) -> dict:
        if db is not None:
            _update_stage(
                job,
                db,
                "requirement",
                "需求分析",
                "running",
                f"正在生成证据链和功能点（第 {batch_index}/{batch_count} 批）",
            )
        include_images = batch_index == 1
        prompt = {
            "task": "按 claw_5skill_final 的 requirement-analyzer 规则，执行【阶段 2：Text Parse】、【阶段 3：Cross-Source Alignment】和【阶段 4：Function Point Synthesis】。仅分析本批章节，生成 EvidenceTrace 与 FunctionPoints。",
            "batch": {"index": batch_index, "count": batch_count},
            "source_document_name": job.source_document_name,
            "sections": batch_sections,
            "downloaded_images": compact_downloaded_images if include_images else [],
            "image_analysis": compact_image_analysis if include_images else [],
            "constraints": [
                "必须执行交叉对齐：正文明确且图片支持的内容标记为 text_and_image；仅正文标记 text_only；仅图片推断标记 image_or_inferred。",
                "只输出本批章节能直接追溯到的功能点，不要为其他章节补内容。",
                "source_refs 必须引用本批章节标题或图片 image_id (如 IMG-001)。",
                "source_order 必须沿用章节 source_order。",
                "每批最多输出 6 个功能点，优先保留高价值规则和交互。",
                "如果图片与正文冲突，以正文为主，并在 pending_confirmations 中记录冲突。",
            ],
        }

        expected_images = compact_downloaded_images if include_images else []
        last_error = ""
        for attempt in range(1, 3):
            started = time.perf_counter()
            retry_note = f"上一次失败原因：{last_error}。本次请减少功能点数量但保证字段完整。" if last_error else ""
            def batch_validator(candidate: dict) -> None:
                normalize_batch_result(candidate, expected_images)
                validate(candidate, expected_images, require_function_points=False)

            try:
                result = await _call_skill_with_gate_async(
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    skill_name="requirement-analyzer",
                    task_payload=prompt,
                    output_contract=(
                        '{"evidence_trace": {"image_summary": {"image_link_count": 0, "download_success_count": 0, "download_failed_count": 0, "image_observation_count": 0, "pending_confirmation_count": 0}, "images": [{"image_id": "string", "image_url": "string", "local_path": "string", "download_status": "success|failed", "source_type": "image", "observed_elements": ["string"], "mapped_function_points": ["string"], "notes": ["string"]}], "pending_confirmations": [{"pending_id": "string", "source": "string", "ref_id": "string", "message": "string", "status": "pending"}]}, '
                        '"function_points": {"function_points": [{"fp_id": "string", "module": "string", "scene": "string", "requirement_group_id": "string", "requirement_group_title": "string", "title": "string", "type": "string", "description": "string", "source_refs": [{"source_type": "text|image", "doc": "string", "section": "string", "quote": "string"}], "actors": ["string"], "entries": ["string"], "preconditions": ["string"], "inputs": [{"name": "string", "type": "string", "required": true, "constraints": ["string"]}], "outputs": ["string"], "rules": ["string"], "states": [{"from": "string", "event": "string", "to": "string"}], "exceptions": ["string"], "dependencies": ["string"], "test_hints": {"positive": ["string"], "boundary": ["string"], "negative": ["string"]}, "priority_hint": "string", "source_distribution": "text_only|text_and_image|image_or_inferred", "atomicity_check": {"passed": true, "issues": ["string"]}, "source_order": 1}]}}'
                    ),
                    validator=batch_validator,
                    max_tokens=_REQUIREMENT_MAX_TOKENS,
                    timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
                    max_attempts=2,
                    audit_log=audit_log,
                )
                result = normalize_batch_result(result, expected_images)
                validate(result, expected_images, require_function_points=False)
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": "requirement-analyzer",
                            "attempt": f"{batch_index}.{attempt}",
                            "status": "passed",
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                        }
                    )
                return result
            except Exception as exc:
                last_error = str(exc)
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": "requirement-analyzer",
                            "attempt": f"{batch_index}.{attempt}",
                            "status": "api_failed",
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                            "error": str(exc),
                        }
                    )
        if last_error:
            if len(batch_sections) > 1:
                if audit_log is not None:
                    audit_log.append(
                        {
                            "skill": "requirement-analyzer",
                            "attempt": batch_index,
                            "status": "fallback_split",
                            "error": last_error,
                            "section_count": len(batch_sections),
                        }
                    )
                split_results = await _gather_limited(
                    [
                        call_batch_async([section], batch_index=batch_index * 100 + offset, batch_count=batch_count)
                        for offset, section in enumerate(batch_sections, start=1)
                    ]
                )
                merged_images: list[dict] = []
                merged_pending: list = []
                merged_fps: list[dict] = []
                image_summary_parts: list[str] = []
                seen_image_ids: set[str] = set()
                for item in split_results:
                    evidence = item.get("evidence_trace") or {}
                    if evidence.get("image_summary"):
                        image_summary_parts.append(str(evidence.get("image_summary")))
                    for image in evidence.get("images") or []:
                        image_id = image.get("image_id")
                        if image_id and image_id not in seen_image_ids:
                            merged_images.append(image)
                            seen_image_ids.add(image_id)
                    merged_pending.extend(evidence.get("pending_confirmations") or [])
                    fp_payload = item.get("function_points") or {}
                    split_fps = fp_payload.get("function_points") if isinstance(fp_payload, dict) else fp_payload
                    merged_fps.extend(split_fps or [])
                return {
                    "evidence_trace": {
                        "image_summary": "\n".join(image_summary_parts) or "无图片证据",
                        "images": merged_images,
                        "pending_confirmations": merged_pending,
                    },
                    "function_points": {"function_points": merged_fps},
                    "pending_confirmations": merged_pending,
                }
            if audit_log is not None:
                audit_log.append({"skill": "requirement-analyzer", "attempt": batch_index, "status": "failed", "error": last_error})
            raise ValueError(f"requirement-analyzer 多次重试后仍未通过门禁：{last_error}")
        raise ValueError("requirement-analyzer 未返回有效结果")

    section_batches = _build_requirement_section_batches(compact_sections)
    batch_results = asyncio.run(
        _gather_limited(
            [
                call_batch_async(batch, batch_index=index, batch_count=len(section_batches))
                for index, batch in enumerate(section_batches, start=1)
            ]
        )
    )

    function_points: list[dict] = []
    pending_confirmations: list = []
    evidence_images: list[dict] = []
    image_summary_parts: list[str] = []
    evidence_pending: list = []
    seen_image_ids: set[str] = set()
    for result in batch_results:
        evidence = result.get("evidence_trace") or {}
        if evidence.get("image_summary"):
            image_summary_parts.append(str(evidence.get("image_summary")))
        for image in evidence.get("images") or []:
            image_id = image.get("image_id")
            if image_id and image_id not in seen_image_ids:
                evidence_images.append(image)
                seen_image_ids.add(image_id)
        evidence_pending.extend(evidence.get("pending_confirmations") or [])
        pending_confirmations.extend(result.get("pending_confirmations") or [])
        fp_payload = result.get("function_points") or {}
        batch_fps = fp_payload.get("function_points") if isinstance(fp_payload, dict) else fp_payload
        function_points.extend(batch_fps or [])

    for index, item in enumerate(function_points, start=1):
        item.setdefault("fp_id", f"FP-{index:03d}")
        item.setdefault("source_order", index)
        item.setdefault("module", item.get("module") or "默认模块")
        item.setdefault("scene", item.get("scene") or item.get("module") or "默认场景")
        item["priority_hint"] = _normalize_priority(item.get("priority_hint"), fp=item)
        item["fp_id"] = f"FP-{index:03d}"
    _gate(function_points, "需求分析完成但未提取到任何功能点，请确认需求正文包含明确的功能变更或验收规则")

    # 证据链权威化：以实际下载+识图结果为准，修复分批时“无图批次”污染 image_summary 的幻觉
    successful_images = [item for item in downloaded_images if item.get("download_status") == "success"]
    failed_images = [item for item in downloaded_images if item.get("download_status") == "failed"]
    if successful_images:
        hint_bits = []
        for item in image_analysis[:8]:
            summary_text = str(item.get("summary") or "").strip()
            if summary_text:
                hint_bits.append(f"{item.get('image_id')}：{summary_text[:60]}")
        image_summary = f"共发现 {len(downloaded_images)} 张图片，成功下载并完成多模态识图 {len(successful_images)} 张"
        if failed_images:
            image_summary += f"，下载失败 {len(failed_images)} 张"
        if hint_bits:
            image_summary += "；识图要点：" + "；".join(hint_bits)
        # 剔除与事实冲突的“无图片/缺少图片证据”类待确认项（真实下载失败项保留）
        absence_markers = ("未提供图片", "无图片", "缺少图片", "没有图片", "缺失图片", "未包含图片", "无图片证据", "未提供图片链接")

        def _is_false_image_absence(entry) -> bool:
            text = entry if isinstance(entry, str) else json.dumps(entry, ensure_ascii=False)
            return any(marker in text for marker in absence_markers) and "下载失败" not in text

        evidence_pending = [p for p in evidence_pending if not _is_false_image_absence(p)]
        pending_confirmations = [p for p in pending_confirmations if not _is_false_image_absence(p)]
    else:
        image_summary = "\n".join(image_summary_parts) or "无图片证据"

    analysis_by_id = {item.get("image_id"): item for item in image_analysis if isinstance(item, dict) and item.get("image_id")}

    def _mapped_fps_for_image(image_id: str) -> list[str]:
        if not image_id:
            return []
        mapped: list[str] = []
        for fp in function_points:
            if image_id in json.dumps(fp.get("source_refs") or [], ensure_ascii=False):
                mapped.append(fp.get("fp_id"))
        return mapped

    canonical_images: list[dict] = []
    for item in downloaded_images:
        image_id = item.get("image_id")
        analysis = analysis_by_id.get(image_id) or {}
        canonical_images.append({
            "image_id": image_id,
            "image_url": item.get("url") or "",
            "local_path": item.get("file_path"),
            "download_status": item.get("download_status") or "success",
            "source_type": "image",
            "observed_elements": list(analysis.get("ui_elements") or analysis.get("requirement_hints") or []),
            "mapped_function_points": _mapped_fps_for_image(image_id),
            "notes": list(analysis.get("risk_or_unclear") or []),
        })
    if not canonical_images:
        canonical_images = [img for img in evidence_images if isinstance(img, dict)]

    def _canonical_pending(entries) -> list[dict]:
        out: list[dict] = []
        for idx, entry in enumerate(entries or [], start=1):
            if isinstance(entry, dict):
                serialized = json.dumps(entry, ensure_ascii=False)
                out.append({
                    "pending_id": entry.get("pending_id") or f"PENDING-{idx:03d}",
                    "source": entry.get("source") or ("image" if "IMG-" in serialized else "text"),
                    "ref_id": entry.get("ref_id") or entry.get("item") or "",
                    "message": entry.get("message") or entry.get("reason") or "",
                    "status": entry.get("status") or "pending",
                })
            elif entry:
                out.append({"pending_id": f"PENDING-{idx:03d}", "source": "text", "ref_id": "", "message": str(entry), "status": "pending"})
        return out

    canonical_pending = _canonical_pending(pending_confirmations or evidence_pending)
    _project_name = _sanitize_file_stem(job.source_document_name or job.name)
    _today_iso = utc_now_naive().date().isoformat()

    evidence_trace = {
        "project": _project_name,
        "generated_at": _today_iso,
        "source_document": job.source_document_name or job.name or "",
        "image_summary": {
            "image_link_count": len(downloaded_images),
            "download_success_count": len(successful_images),
            "download_failed_count": len(failed_images),
            "image_observation_count": len(image_analysis),
            "pending_confirmation_count": len(canonical_pending),
        },
        "images": canonical_images,
        "pending_confirmations": canonical_pending,
    }
    function_points_payload = {
        "version": "3.2-skill-only",
        "project": _project_name,
        "analyzed_at": _today_iso,
        "source_documents": [job.source_document_name or job.name or ""],
        "function_points": sorted(function_points, key=lambda item: item.get("source_order", 0)),
    }
    _assign_requirement_groups(function_points_payload)
    return {
        "evidence_trace": evidence_trace,
        "function_points": function_points_payload,
        "pending_confirmations": canonical_pending,
    }


def _build_testcase_package(
    function_points: dict,
    pending_confirmations: list,
    api_key: str,
    model: str,
    base_url: str | None = None,
    audit_log: list[dict] | None = None,
    progress_callback=None,
) -> dict:
    fps = [item for item in function_points.get("function_points", []) if isinstance(item, dict) and item.get("fp_id")]
    fp_ids = {item.get("fp_id") for item in fps}
    fp_by_id = {item.get("fp_id"): item for item in fps}
    compact_pending_confirmations = _compact_pending_confirmations_for_ai(pending_confirmations)

    def normalize_case(case: dict, index: int, allowed_fp_ids: set[str]) -> dict:
        fp_id = case.get("fp_id")
        fp = fp_by_id.get(fp_id) or {}
        case.setdefault("case_id", f"TC-TEMP-{index:03d}")
        case.setdefault("module", fp.get("module") or "需求模块")
        case.setdefault("scene", fp.get("scene") or "需求场景")
        case.setdefault("source_order", fp.get("source_order") or index)
        case.setdefault("title", f"{fp.get('title') or fp_id}")
        case.setdefault("category", "functional")
        case["category"] = _normalize_category(case.get("category"))

        fp_priority = _normalize_priority(fp.get("priority_hint"), fp=fp, case=case, category=case["category"])
        raw_case_priority = str(case.get("priority") or "").strip()
        priority_source = fp_priority if raw_case_priority in {"", "P1", "p1", "1"} and fp_priority != "P1" else raw_case_priority
        case["priority"] = _normalize_priority(priority_source or fp_priority, fp=fp, case=case, category=case["category"])

        case.setdefault("tags", ["AI-GEN"])
        case.setdefault("preconditions", [])
        case["test_data"] = _coerce_test_data(case.get("test_data"))
        case.setdefault("steps", [])
        case.setdefault("expected_results", [])
        derived_sources = _sources_from_refs(fp.get("source_refs"))
        case.setdefault("traceability", {"function_points": [fp_id], "sources": derived_sources})
        if isinstance(case.get("traceability"), dict):
            case["traceability"].setdefault("function_points", [fp_id])
            case["traceability"].setdefault("sources", derived_sources)
        case.setdefault("generation_basis", {"method": "functional", "rationale": "基于功能点生成"})
        case.setdefault("scenario_dimensions", [case["category"]])
        case.setdefault("baseline_candidate", case.get("category") == "functional")
        case["review_flags"] = _coerce_review_flags(case.get("review_flags"))
        if isinstance(case.get("steps"), list):
            normalized_steps = []
            for step_index, step in enumerate(case["steps"], start=1):
                if isinstance(step, dict):
                    step.setdefault("step_no", step_index)
                    normalized_steps.append(step)
                else:
                    normalized_steps.append({"step_no": step_index, "action": str(step)})
            case["steps"] = normalized_steps
        else:
            case["steps"] = []
        if not isinstance(case.get("expected_results"), list):
            case["expected_results"] = [str(case["expected_results"])] if case.get("expected_results") else []
        return case





    def validate(result: dict, allowed_fp_ids: set[str], require_all_allowed: bool = True) -> None:
        cases = result.get("testcases") or []
        _gate(isinstance(cases, list) and cases, "TestcasePackage 缺少 testcases")
        if require_all_allowed:
            covered = {case.get("fp_id") for case in cases}
            missing_fp = sorted(fp_id for fp_id in allowed_fp_ids if fp_id not in covered)
            _gate(not missing_fp, f"以下功能点未被用例覆盖：{', '.join(missing_fp)}")
        required = {"case_id", "fp_id", "title", "category", "priority", "preconditions", "test_data", "steps", "expected_results", "traceability", "generation_basis", "scenario_dimensions", "baseline_candidate"}
        for case in cases:
            missing = sorted(key for key in required if key not in case)
            _gate(not missing, f"用例 {case.get('case_id')} 缺少字段：{', '.join(missing)}")
            _gate(case.get("fp_id") in allowed_fp_ids, f"用例 {case.get('case_id')} 关联了不在当前批次的 fp_id")
            fp = fp_by_id.get(case.get("fp_id")) or {}
            case["category"] = _normalize_category(case.get("category"))

            fp_priority = _normalize_priority(fp.get("priority_hint"), fp=fp, case=case, category=case.get("category"))
            raw_case_priority = str(case.get("priority") or "").strip()
            priority_source = fp_priority if raw_case_priority in {"", "P1", "p1", "1"} and fp_priority != "P1" else raw_case_priority
            priority = _normalize_priority(priority_source or fp_priority, fp=fp, case=case, category=case.get("category"))
            case["priority"] = priority
            _gate(priority in {"P0", "P1", "P2", "P3"}, f"用例 {case.get('case_id')} 优先级非法")

            _gate(isinstance(case.get("steps"), list) and len(case["steps"]) >= 2, f"用例 {case.get('case_id')} 步骤不足")
            _gate(isinstance(case.get("expected_results"), list) and case["expected_results"], f"用例 {case.get('case_id')} 缺少可验证预期")

    async def generate_for_fps_async(batch_fps: list[dict], batch_label: str, require_all_allowed: bool = True) -> list[dict]:
        allowed_fp_ids = {item.get("fp_id") for item in batch_fps}
        compact_batch_fps = _compact_function_points_for_ai(batch_fps)
        prompt = {
            "task": "按 claw_5skill_final 的 testcase-designer 规则，仅基于本批 FunctionPoints 生成中文执行级测试用例。必须覆盖正交维度与异常路径。",
            "batch_label": batch_label,
            "function_points": compact_batch_fps,
            "pending_confirmations": compact_pending_confirmations,
            "constraints": [
                "只能覆盖本批 function_points 中的 fp_id，不要生成其他 fp_id。",
                "每个 fp_id 至少生成 1 条主流程用例；再按测试设计方法库（等价类/边界值/决策表/状态转换/角色权限矩阵/多入口一致性/空值默认值/异常容错/时间时序）选择适用方法补充用例。",
                "按场景价值决定用例数量：不堆数量、不为追求覆盖制造大量同质用例，也不要机械凑数。",
                "category 只能使用 functional/ui/boundary/negative/regression/compatibility/performance/security。",
                "priority 只能使用 P0/P1/P2/P3，并参考 function_points.priority_hint；无明确业务优先级时不要过度使用 P0。",
                "标题必须包含具体业务对象、场景或规则，不得使用正常流程验证/主流程验证/边界验证/异常验证等模板标题。",
                "steps 必须让新人可照着执行：包含入口/前置数据、具体操作对象、触发动作、页面或接口或数据层核验；禁止写“进入对应页面/执行正常流程验证/观察结果”等空泛步骤。",
                "expected_results 必须可观察、可判定、可复核（状态变化、记录落库、接口字段、提示文案、预算或任务状态等），不能只写系统正常/结果正确/符合预期。",
                "generation_basis 必须写明 method（取自方法库，如 equivalence/boundary/decision_table/state_transition/role_matrix/entry_consistency）与 rationale（这条用例为何需要存在）。",
                "traceability 必须准确引用 fp_id 和 source_refs。",
                "test_data 必须是对象数组，每项 {name, value}；review_flags 给出 executable_risk 与 ambiguity_risk（low/medium/high）。",
                "不要回读原始需求文档，不要自由发明业务规则。",
            ],
        }

        def batch_validator(result: dict) -> None:
            for index, case in enumerate(result.get("testcases") or [], start=1):
                if isinstance(case, dict):
                    normalize_case(case, index, allowed_fp_ids)
            validate(result, allowed_fp_ids, require_all_allowed=require_all_allowed)

        result = await _call_skill_with_gate_async(
            api_key=api_key,
            model=model,
            base_url=base_url,
            skill_name="testcase-designer",
            task_payload=prompt,
            output_contract=(
                '{"testcases": [{"case_id": "string", "fp_id": "string", "title": "string", "category": "functional|ui|boundary|negative|regression|compatibility|performance|security", "priority": "P0|P1|P2|P3", "preconditions": ["string"], "test_data": [{"name": "string", "value": "string"}], "steps": [{"step_no": 1, "action": "string"}], "expected_results": ["string"], "traceability": {"function_points": ["string"], "sources": ["string"]}, "generation_basis": {"method": "string", "rationale": "string"}, "scenario_dimensions": ["string"], "baseline_candidate": true, "review_flags": {"executable_risk": "low|medium|high", "ambiguity_risk": "low|medium|high"}}]}'
            ),
            validator=batch_validator,
            max_tokens=8000,
            timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
            audit_log=audit_log,
        )
        return [case for case in result.get("testcases") or [] if isinstance(case, dict) and case.get("fp_id") in allowed_fp_ids]

    def covered_fp_ids(cases: list[dict]) -> set[str]:
        return {case.get("fp_id") for case in cases if case.get("fp_id") in fp_ids}

    def renumber_cases(cases: list[dict]) -> list[dict]:
        sorted_cases = sorted(
            cases,
            key=lambda item: (
                str(fp_by_id.get(item.get("fp_id"), {}).get("source_order", "")),
                item.get("fp_id") or "",
                item.get("category") or "",
                item.get("title") or "",
            ),
        )
        fp_case_counts: dict[str, int] = {}
        for global_index, case in enumerate(sorted_cases, start=1):
            fp_id = case.get("fp_id") or f"FP-{global_index:03d}"
            fp_number = re.sub(r"\D", "", fp_id)[-3:] or f"{global_index:03d}"
            fp_case_counts[fp_id] = fp_case_counts.get(fp_id, 0) + 1
            case["case_id"] = f"TC-{fp_number}-{fp_case_counts[fp_id]:03d}"
            fp = fp_by_id.get(fp_id) or {}
            case.setdefault("module", fp.get("module") or "需求模块")
            case.setdefault("scene", fp.get("scene") or "需求场景")
            case.setdefault("source_order", fp.get("source_order") or global_index)
            case["category"] = _normalize_category(case.get("category"))
            fp_priority = _normalize_priority(fp.get("priority_hint"), fp=fp, case=case, category=case.get("category"))
            raw_case_priority = str(case.get("priority") or "").strip()
            priority_source = fp_priority if raw_case_priority in {"", "P1", "p1", "1"} and fp_priority != "P1" else raw_case_priority
            case["priority"] = _normalize_priority(priority_source or fp_priority, fp=fp, case=case, category=case.get("category"))
        return sorted_cases

    def dedupe_cases(cases: list[dict]) -> list[dict]:
        seen: set[tuple[str, str]] = set()
        unique: list[dict] = []
        for case in cases:
            key = (case.get("fp_id") or "", re.sub(r"\s+", "", str(case.get("title") or "")))
            if key in seen:
                continue
            seen.add(key)
            unique.append(case)
        return unique

    all_cases: list[dict] = []
    batches = [fps[index : index + _TESTCASE_FP_BATCH_SIZE] for index in range(0, len(fps), _TESTCASE_FP_BATCH_SIZE)]
    
    # Phase 1: 并行生成所有批次的用例
    batch_results = asyncio.run(
        _gather_limited(
            [
                generate_for_fps_async(batch, f"batch-{index}", require_all_allowed=False)
                for index, batch in enumerate(batches, start=1)
            ]
        )
    )
    for batch_result in batch_results:
        all_cases.extend(batch_result)

    for repair_round in range(1, _TESTCASE_REPAIR_MAX_ROUNDS + 1):
        missing_ids = sorted(fp_id for fp_id in fp_ids if fp_id not in covered_fp_ids(all_cases))
        if not missing_ids:
            break
        if progress_callback:
            progress_callback(f"正在补齐缺失功能点（第 {repair_round}/{_TESTCASE_REPAIR_MAX_ROUNDS} 轮，剩余 {len(missing_ids)} 个）")
        repair_batches = [missing_ids[offset : offset + _TESTCASE_FP_BATCH_SIZE] for offset in range(0, len(missing_ids), _TESTCASE_FP_BATCH_SIZE)]
        repair_batch_results = asyncio.run(
            _gather_limited(
                [
                    generate_for_fps_async(
                        [fp_by_id[fp_id] for fp_id in batch if fp_id in fp_by_id],
                        f"repair-{repair_round}",
                        require_all_allowed=True,
                    )
                    for batch in repair_batches
                ]
            )
        )
        for repair_result in repair_batch_results:
            all_cases.extend(repair_result)

    all_cases = renumber_cases(dedupe_cases(all_cases))
    for index, case in enumerate(all_cases, start=1):
        if isinstance(case, dict):
            normalize_case(case, index, fp_ids)
    missing_ids = sorted(fp_id for fp_id in fp_ids if fp_id not in covered_fp_ids(all_cases))
    _gate(not missing_ids, f"仍有功能点未被用例覆盖：{', '.join(missing_ids)}")
    validate({"testcases": all_cases}, fp_ids, require_all_allowed=True)
    if audit_log is not None:
        audit_log.append(
            {
                "skill": "testcase-designer",
                "attempt": "coverage-merge",
                "status": "passed",
                "testcase_count": len(all_cases),
                "covered_fp_count": len(covered_fp_ids(all_cases)),
            }
        )
    return {"testcases": all_cases}


def _build_review_report(
    evidence_trace: dict,
    function_points: dict,
    testcase_package: dict,
    pending_confirmations: list,
    api_key: str,
    model: str,
    base_url: str | None = None,
    audit_log: list[dict] | None = None,
    block_on_fail: bool = True,
) -> dict:
    prompt = {
        "task": "按 claw_5skill_final 的 quality-reviewer 规则审查 FunctionPoints、EvidenceTrace、TestcasePackage。",
        "function_points": function_points,
        "evidence_trace": evidence_trace,
        "testcase_package": testcase_package,
        "pending_confirmations": pending_confirmations,
        "constraints": [
            "覆盖率检查：每个 FunctionPoint 至少被 1 条用例覆盖；列出未覆盖 fp_id，存在未覆盖时结论不得为 pass。",
            "维度完整性：核对 functional/entry/role/data/time/environment/consistency 七个维度是否被覆盖，缺失维度在 dimension_matrix 标 missing。",
            "方法覆盖：核对等价类/边界值/决策表/状态转换/角色权限/多入口一致性/空值默认/异常容错/时间时序/UI 交互十类方法；方法名出现过 ≠ 真正覆盖，需看用例是否真的体现该方法。",
            "去重：识别重复或高度同质用例并计入 summary.duplicate_count；数量多 ≠ 覆盖好。",
            "可执行性：步骤是否新人可照做，含入口/前置/操作对象/触发动作/核验点；空泛步骤计入 ambiguous_step_count。",
            "可验证性：预期是否可观察可判定（状态/记录/接口字段/提示文案）；不可验证预期计入 unverifiable_expectation_count。",
            "优先级合理性：P0 是否被滥用、是否与业务风险匹配。",
            "基线候选合理性：baseline_candidate 是否落在主流程成功/核心校验/关键状态流转等真正回归基线上。",
            "需求顺序一致性：module 是否沿用原文章节、source_order 是否被继承；若被按优先级/方法/字母重排，结论不得为 pass。",
            "结论为 fail 时必须给出 repair_tasks（fp_ids/reason/focus），且为可执行修复指令而非泛泛建议。",
        ],
        "output_contract": "ReviewReport.yaml 等价 JSON，必须包含 summary（含 testcase_count/duplicate_count/uncovered_fp_count/ambiguous_step_count/unverifiable_expectation_count/overall_score/release_readiness）、coverage、method_coverage、dimension_matrix、evidence_trace、execution_proof、findings；当 release_readiness 为 fail 时必须同时提供 repair_tasks 数组，每项包含 fp_ids、reason、focus",
    }

    def validate(result: dict) -> None:
        summary = result.get("summary") or {}
        _gate(summary.get("release_readiness") in {"pass", "conditional_pass", "fail"}, "ReviewReport 缺少合法 summary.release_readiness")
        for key in ("coverage", "method_coverage", "dimension_matrix", "evidence_trace", "execution_proof", "findings"):
            _gate(key in result, f"ReviewReport 缺少 {key}")
        if result.get("coverage", {}).get("uncovered_fp_ids"):
            _gate(summary.get("release_readiness") != "pass", "存在未覆盖功能点时审查结论不能为 pass")
        if summary.get("release_readiness") == "fail":
            has_repair_tasks = bool(result.get("repair_tasks"))
            has_findings = bool(result.get("findings"))
            _gate(has_repair_tasks or has_findings, "审查结论为 fail 时必须提供 repair_tasks 或 findings")

    ai_review = asyncio.run(_call_skill_with_gate_async(
        api_key=api_key,
        model=model,
        base_url=base_url,
        skill_name="quality-reviewer",
        task_payload=prompt,
        output_contract=(
            '{"summary": {"testcase_count": 0, "duplicate_count": 0, "uncovered_fp_count": 0, "ambiguous_step_count": 0, "unverifiable_expectation_count": 0, "overall_score": 0, "release_readiness": "pass|conditional_pass|fail"}, '
            '"coverage": {"fp_covered": 0, "fp_total": 0, "uncovered_fp_ids": []}, '
            '"method_coverage": {"equivalence": "covered|partial|missing", "boundary": "covered|partial|missing", "decision_table": "covered|partial|missing", "state_transition": "covered|partial|missing", "role_matrix": "covered|partial|missing", "entry_consistency": "covered|partial|missing", "default_or_empty": "covered|partial|missing", "error_tolerance": "covered|partial|missing", "time_or_sequence": "covered|partial|missing", "ui_interaction": "covered|partial|missing"}, '
            '"dimension_matrix": {"functional": "covered|partial|missing", "entry": "covered|partial|missing", "role": "covered|partial|missing", "data": "covered|partial|missing", "time": "covered|partial|missing", "environment": "covered|partial|missing", "consistency": "covered|partial|missing"}, '
            '"evidence_trace": {"image_link_count": 0, "download_success_count": 0, "download_failed_count": 0, "pending_confirmation_count": 0, "status": "complete|incomplete"}, '
            '"execution_proof": {"text_fp_count": 0, "text_and_image_fp_count": 0, "image_or_inferred_fp_count": 0, "image_observation_count": 0, "summary_lines": ["string"]}, '
            '"findings": [{"finding_id": "string", "severity": "low|medium|high|critical", "type": "string", "case_id": "string", "fp_id": "string", "message": "string", "suggestion": "string"}], '
            '"repair_tasks": [{"fp_ids": ["string"], "reason": "string", "focus": "string"}]}'
        ),
        validator=validate,
        max_tokens=10000,
        timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
        audit_log=audit_log,
    ))

    cases = testcase_package.get("testcases", [])
    priority_counts = Counter(case.get("priority") or "P1" for case in cases)
    downloaded_images = evidence_trace.get("downloaded_images") or []
    failed_images = [item for item in downloaded_images if item.get("download_status") == "failed"]
    readiness = ai_review.get("summary", {}).get("release_readiness") or "conditional_pass"
    review_summary = ai_review.get("summary") or {}
    uncovered_ids = (ai_review.get("coverage") or {}).get("uncovered_fp_ids") or []
    review_summary.setdefault("release_readiness", readiness)
    review_summary.setdefault("testcase_count", len(cases))
    review_summary.setdefault("duplicate_count", 0)
    review_summary.setdefault("uncovered_fp_count", len(uncovered_ids))
    review_summary.setdefault("ambiguous_step_count", 0)
    review_summary.setdefault("unverifiable_expectation_count", 0)
    review_summary.setdefault("overall_score", 0)
    ai_review["summary"] = review_summary
    conclusion_map = {"pass": "通过", "conditional_pass": "有条件通过", "fail": "不通过"}
    ai_review.update({
        "review_conclusion": conclusion_map.get(readiness, "有条件通过"),
        "function_point_count": len(function_points.get("function_points", [])),
        "case_count": len(cases),
        "priority_counts": {level: priority_counts.get(level, 0) for level in ("P0", "P1", "P2", "P3")},
        "image_link_count": len(evidence_trace.get("image_links") or downloaded_images),
        "image_download_success_count": sum(1 for item in downloaded_images if item.get("download_status") == "success"),
        "image_download_failed_count": len(failed_images),
        "pending_confirmations": pending_confirmations,
    })
    if block_on_fail:
        _gate(readiness != "fail", "quality-reviewer 审查结论为 fail，禁止导出 XMind")
    return ai_review






def _clean_node_text(value) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:260] or "-"


def _append_node(lines: list[str], depth: int, text: str) -> None:
    lines.append(f"{'  ' * depth}- {_clean_node_text(text)}")


def _validate_xmindmark(text: str) -> None:
    lines = text.splitlines()
    if not lines:
        raise ValueError("XMindMark 内容为空")
    if lines[0].startswith("- "):
        raise ValueError("XMindMark 第一行必须是根节点纯文本")
    for index, line in enumerate(lines[1:], start=2):
        if not line.strip():
            raise ValueError(f"XMindMark 第 {index} 行为空行")
        if not line.startswith("- ") and not re.match(r"^(  )+- ", line):
            raise ValueError(f"XMindMark 第 {index} 行不是标准列表节点")
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"XMindMark 第 {index} 行缩进不是 2 空格倍数")
        if line.lstrip().startswith("#"):
            raise ValueError(f"XMindMark 第 {index} 行不能使用 Markdown 标题")


def _build_delivery_summary(
    job: CaseGenerationJob,
    function_points: dict,
    testcase_package: dict,
    review_report: dict,
) -> str:
    """Phase 3：按 claw_5skill_final delivery_summary 模板生成交付摘要（内部产物）。"""
    project = _sanitize_file_stem(job.source_document_name or job.name)
    stem = project
    fp_count = len(function_points.get("function_points", []))
    case_count = len(testcase_package.get("testcases", []))
    conclusion = review_report.get("review_conclusion") or "有条件通过"
    findings = review_report.get("findings") or []
    pending = review_report.get("pending_confirmations") or []
    risk_lines: list[str] = []
    for finding in findings[:10]:
        if isinstance(finding, dict):
            msg = str(finding.get("message") or finding.get("suggestion") or "").strip()
            if msg:
                risk_lines.append(f"- {finding.get('severity') or 'medium'}：{_short_text(msg, 120)}")
    if not risk_lines and pending:
        risk_lines.append(f"- 存在 {len(pending)} 项待确认事项，需人工复核")
    if not risk_lines:
        risk_lines.append("- 无")
    lines = [
        "# 交付摘要",
        "",
        f"- 项目：{project}",
        f"- 功能点数：{fp_count}",
        f"- 用例数：{case_count}",
        f"- 审查结论：{conclusion}",
        "",
        "## 内部文件",
        "",
        "- FunctionPoints.yaml",
        "- TestcasePackage.yaml",
        "- ReviewReport.yaml",
        f"- {stem}.xmind",
        "",
        "## 风险提示",
        "",
        *risk_lines,
        "",
    ]
    return "\n".join(lines)


def _build_xmindmark(
    job: CaseGenerationJob,
    function_points: dict,
    testcase_package: dict,
    review_report: dict,
) -> str:
    root = f"{_sanitize_file_stem(job.source_document_name or job.name)}测试用例"
    lines = [root]
    cases = [case for case in testcase_package.get("testcases", []) if isinstance(case, dict)]
    priority_counts = Counter(case.get("priority") or "P1" for case in cases)
    category_counts = Counter(_normalize_category(case.get("category")) for case in cases)
    review_counts = review_report.get("priority_counts") or {}
    counts = {level: priority_counts.get(level, review_counts.get(level, 0)) for level in ("P0", "P1", "P2", "P3")}
    _append_node(lines, 0, "统计信息")
    _append_node(lines, 1, f"功能点总数：{review_report.get('function_point_count', 0)}")
    _append_node(lines, 1, f"用例总数：{len(cases) or review_report.get('case_count', 0)}")
    for level in ("P0", "P1", "P2", "P3"):
        _append_node(lines, 1, f"{level} 数量：{counts.get(level, 0)}")
    _append_node(lines, 1, f"图片链接数量：{review_report.get('image_link_count', 0)}")
    _append_node(lines, 1, f"图片下载成功数量：{review_report.get('image_download_success_count', 0)}")
    _append_node(lines, 1, f"图片下载失败数量：{review_report.get('image_download_failed_count', 0)}")
    _append_node(lines, 1, f"审查结论：{review_report.get('review_conclusion', '有条件通过')}")
    _append_node(lines, 1, f"待确认项数量：{len(review_report.get('pending_confirmations') or [])}")
    if category_counts:
        _append_node(lines, 1, "类型分布：" + " / ".join(f"{_category_label(key)} {value}" for key, value in category_counts.items()))
    method_counts = Counter(
        _method_label((case.get("generation_basis") or {}).get("method"))
        for case in cases
        if isinstance(case.get("generation_basis"), dict) and (case.get("generation_basis") or {}).get("method")
    )
    if method_counts:
        _append_node(lines, 1, "方法分布：" + " / ".join(f"{name} {value}" for name, value in method_counts.items()))
    quality_summary = review_report.get("quality_summary") or {}
    if quality_summary:
        _append_node(lines, 1, f"证据覆盖率：{quality_summary.get('evidence_coverage_rate', 0):.0%}")
        _append_node(lines, 1, f"弱预期数量：{quality_summary.get('weak_expected_count', 0)}")

    fp_by_id = {item.get("fp_id"): item for item in function_points.get("function_points", [])}
    cases_by_fp: dict[str, list[dict]] = {}
    for case in cases:
        cases_by_fp.setdefault(case.get("fp_id") or "UNMAPPED", []).append(case)

    # 总纲固定结构：根 → 模块 → 场景 → 功能点 → CaseID-标题 → 字段节点 → 步骤
    # 按 source_order 保原文顺序，在原文顺序内按 module、再按 scene 分组（不跳过 scene 层）
    ordered_fps = sorted(function_points.get("function_points", []), key=lambda item: item.get("source_order", 0))
    modules: dict[str, dict[str, list[dict]]] = {}
    for fp in ordered_fps:
        module = fp.get("module") or "默认模块"
        scene = fp.get("scene") or module
        modules.setdefault(module, {}).setdefault(scene, []).append(fp)

    for module, scenes in modules.items():
        _append_node(lines, 0, f"模块：{module}")
        for scene, scene_fps in scenes.items():
            _append_node(lines, 1, f"场景：{scene}")
            for fp in scene_fps:
                fp_id = fp.get("fp_id") or "FP-000"
                fp_title = fp.get("title") or fp.get("name") or fp.get("description") or "功能点"
                _append_node(lines, 2, f"{fp_id}：{fp_title}")
                if fp.get("description"):
                    _append_node(lines, 3, f"说明：{_short_text(fp.get('description'), 120)}")
                rules = fp.get("rules") or []
                if rules:
                    _append_node(lines, 3, f"规则摘要：{_short_text('；'.join(str(item) for item in rules[:3]), 160)}")
                for case in cases_by_fp.get(fp_id, []):
                    case_id = case.get("case_id") or "TC-000"
                    category = _normalize_category(case.get("category"))
                    title = _short_text(case.get("title") or "测试用例", 90)
                    _append_node(lines, 3, f"{case_id}-{title}")
                    _append_node(lines, 4, f"优先级：{case.get('priority') or 'P1'}｜类型：{_category_label(category)}")
                    expected = case.get("expected_results") or []
                    expected_items = expected if isinstance(expected, list) else [expected]
                    if expected_items:
                        _append_node(lines, 4, f"预期摘要：{_short_text('；'.join(str(item) for item in expected_items[:2]), 160)}")
                    steps = case.get("steps") or []
                    if not isinstance(steps, list):
                        steps = [str(steps)]
                    if steps:
                        _append_node(lines, 4, "操作步骤")
                        for step_index, step in enumerate(steps[:6], start=1):
                            _append_node(lines, 5, f"步骤{step_index}：{_short_text(_step_to_text(step), 120)}")
                    refs = _case_evidence_refs(case, fp)
                    if refs:
                        _append_node(lines, 4, "图片/证据：" + "，".join(refs))

    unmapped_cases = [case for case in cases if case.get("fp_id") not in fp_by_id]
    if unmapped_cases:
        _append_node(lines, 0, "模块：未映射用例")
        _append_node(lines, 1, "场景：待人工确认")
        _append_node(lines, 2, "FP-UNMAPPED：未映射功能点")
        for case in unmapped_cases:
            _append_node(lines, 3, f"{case.get('case_id')}-{case.get('title')}")
            _append_node(lines, 4, f"优先级：{case.get('priority') or 'P1'}｜类型：{_category_label(_normalize_category(case.get('category')))}")

    text = "\n".join(lines) + "\n"
    _validate_xmindmark(text)
    return text


def _upsert_artifact(
    db,
    *,
    job_id: int,
    artifact_type: str,
    file_name: str | None = None,
    file_path: str | None = None,
    content_json: dict | list | None = None,
) -> None:
    artifact = db.scalar(
        select(CaseGenerationArtifact).where(
            CaseGenerationArtifact.job_id == job_id,
            CaseGenerationArtifact.artifact_type == artifact_type,
        )
    )
    if artifact is None:
        artifact = CaseGenerationArtifact(
            job_id=job_id,
            artifact_type=artifact_type,
            file_name=file_name,
            file_path=file_path,
            content_json=content_json,
        )
        db.add(artifact)
        return
    artifact.file_name = file_name
    artifact.file_path = file_path
    artifact.content_json = content_json


def _convert_xmindmark(output_dir: str, xmindmark_file_path: str, output_stem: str) -> str:
    if not shutil.which("xmindmark"):
        raise RuntimeError("缺少 xmindmark 命令，请先在后端运行环境安装 xmindmark")
    _ensure_output_dir_writable(output_dir)
    generated_path = os.path.join(output_dir, f"{Path(xmindmark_file_path).stem}.xmind")
    final_path = os.path.join(output_dir, f"{output_stem}.xmind")
    for path in {generated_path, final_path}:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                _make_writable_file(path)
                os.remove(path)
    subprocess.run(
        ["xmindmark", "-f", "xmind", "-o", output_dir, xmindmark_file_path],
        check=True,
        capture_output=True,
        text=True,
    )
    if not os.path.exists(generated_path):
        raise RuntimeError("xmindmark 转换完成但未生成 .xmind 文件")
    if generated_path != final_path:
        os.replace(generated_path, final_path)
    return _make_writable_file(final_path)


def _assert_required_skill_execution(audit_log: list[dict]) -> None:
    passed_skills = {item.get("skill") for item in audit_log if item.get("status") == "passed"}
    required = {"requirement-analyzer", "testcase-designer", "quality-reviewer"}
    missing = sorted(required - passed_skills)
    _gate(not missing, f"AI Skill 执行证明不完整，缺少：{', '.join(missing)}")


def _build_execution_proof(
    *,
    audit_log: list[dict],
    image_links: list[str],
    downloaded_images: list[dict],
    image_analysis: list[dict],
    function_points: dict,
    testcase_package: dict,
    pending_confirmations: list,
    started_at: float,
) -> dict:
    _assert_required_skill_execution(audit_log)
    return {
        "required_skills": ["requirement-analyzer", "testcase-designer", "quality-reviewer"],
        "skill_audit_log": audit_log,
        "total_duration_ms": int((time.perf_counter() - started_at) * 1000),
        "image_link_count": len(image_links),
        "image_download_success_count": sum(1 for item in downloaded_images if item.get("download_status") == "success"),
        "image_download_failed_count": sum(1 for item in downloaded_images if item.get("download_status") == "failed"),
        "image_observation_count": len(image_analysis),
        "function_point_count": len(function_points.get("function_points", [])),
        "testcase_count": len(testcase_package.get("testcases", [])),
        "pending_confirmation_count": len(pending_confirmations),
    }


def _build_case_generation_quality_summary(function_points: dict, testcase_package: dict) -> dict:
    fps = [item for item in function_points.get("function_points", []) if isinstance(item, dict)]
    cases = [item for item in testcase_package.get("testcases", []) if isinstance(item, dict)]
    fp_ids = {item.get("fp_id") for item in fps if item.get("fp_id")}
    covered_fp_ids = {item.get("fp_id") for item in cases if item.get("fp_id")}
    fp_case_counts = Counter(item.get("fp_id") for item in cases if item.get("fp_id"))
    weak_expected_count = 0
    weak_step_count = 0
    template_title_count = 0
    evidence_case_count = 0
    for case in cases:
        fp = next((item for item in fps if item.get("fp_id") == case.get("fp_id")), {})
        expected_text = " ".join(str(item) for item in case.get("expected_results") or [])
        steps_text = " ".join(_step_to_text(item) for item in case.get("steps") or [])
        if len(expected_text) < 60 or not _expected_has_observable_anchor(case.get("expected_results")):
            weak_expected_count += 1
        if len(steps_text) < 80:
            weak_step_count += 1
        if _text_contains_any(str(case.get("title") or ""), _GENERIC_CASE_TITLE_PATTERNS):
            template_title_count += 1
        if _case_evidence_refs(case, fp):
            evidence_case_count += 1
    return {
        "case_count": len(cases),
        "function_point_count": len(fp_ids),
        "covered_function_point_count": len(fp_ids & covered_fp_ids),
        "fp_coverage_rate": (len(fp_ids & covered_fp_ids) / len(fp_ids)) if fp_ids else 0,
        "priority_counts": dict(Counter(case.get("priority") or "P1" for case in cases)),
        "category_counts": dict(Counter(_normalize_category(case.get("category")) for case in cases)),
        "fp_case_counts": dict(sorted(fp_case_counts.items())),
        "weak_expected_count": weak_expected_count,
        "weak_step_count": weak_step_count,
        "template_title_count": template_title_count,
        "evidence_case_count": evidence_case_count,
        "evidence_coverage_rate": (evidence_case_count / len(cases)) if cases else 0,
    }


def _dedupe_cases_global(cases: list[dict]) -> list[dict]:
    """跨补齐轮次的全局去重：按 (fp_id, 规整化标题) 唯一。"""
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        key = (case.get("fp_id") or "", re.sub(r"\s+", "", str(case.get("title") or "")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique


def _renumber_cases_global(cases: list[dict], function_points: dict) -> list[dict]:
    """补齐合并后全局重排并重写 case_id，消除重复/跳跃的编号。"""
    fp_by_id = {item.get("fp_id"): item for item in function_points.get("function_points", []) if isinstance(item, dict)}
    sorted_cases = sorted(
        cases,
        key=lambda item: (
            str(fp_by_id.get(item.get("fp_id"), {}).get("source_order", "")),
            item.get("fp_id") or "",
            item.get("category") or "",
            item.get("title") or "",
        ),
    )
    fp_case_counts: dict[str, int] = {}
    for global_index, case in enumerate(sorted_cases, start=1):
        fp_id = case.get("fp_id") or f"FP-{global_index:03d}"
        fp_number = re.sub(r"\D", "", fp_id)[-3:] or f"{global_index:03d}"
        fp_case_counts[fp_id] = fp_case_counts.get(fp_id, 0) + 1
        case["case_id"] = f"TC-{fp_number}-{fp_case_counts[fp_id]:03d}"
    return sorted_cases


@celery_app.task(name="app.tasks.case_generation.run_case_generation_job")
def run_case_generation_job(job_id: int) -> None:
    db = SessionLocal()
    run_started_at = time.perf_counter()
    audit_log: list[dict] = []
    try:
        job = db.get(CaseGenerationJob, job_id)
        if job is None:
            return
        if job.status == "CANCELLED":
            return

        payload = dict(job.input_payload_json or {})
        markdown_text = _resolve_markdown_text(payload)
        if not markdown_text:
            job.status = "FAILED"
            job.task_id = None
            job.summary = "输入内容为空"
            job.error_message = "请提供需求文本、上传文件内容或有效的需求文档链接"
            job.finished_at = utc_now_naive()
            db.commit()
            return

        model_config_id = payload.get("model_config_id")
        model_config = db.get(AIModelConfig, model_config_id) if model_config_id else None
        api_key = (model_config.api_key or "").strip() if model_config and model_config.api_key else ""
        model = ((model_config.model if model_config else None) or payload.get("openai_model") or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        base_url, model = validate_model_connection_config(
            model,
            (model_config.base_url if model_config else None) or payload.get("openai_base_url"),
            api_key,
        )
        if not api_key:
            job.status = "FAILED"
            job.task_id = None
            job.summary = "缺少模型配置"
            job.error_message = "当前工作空间未配置可用模型或 API Key"
            job.finished_at = utc_now_naive()
            db.commit()
            return

        job.status = "RUNNING"
        job.summary = "正在按 claw_5skill_final 生成 XMind 用例"
        job.started_at = utc_now_naive()
        job.progress_json = {"stages": []}
        db.execute(delete(CaseGenerationArtifact).where(CaseGenerationArtifact.job_id == job.id))
        db.commit()
        _raise_if_job_cancelled(db, job.id)

        output_dir = _job_output_dir(job.id)
        output_stem = _sanitize_file_stem(job.source_document_name or job.name)
        image_links = _extract_image_links(markdown_text)
        _update_stage(job, db, "orchestrate", "任务编排", "running", "正在生成确定性执行计划")
        orchestration_plan = _build_orchestration_plan(job, payload, markdown_text, image_links)
        _update_stage(job, db, "orchestrate", "任务编排", "success", f"执行模式：{orchestration_plan.get('mode', 'full')}")

        _update_stage(job, db, "collect", "收集输入", "running", "正在收集需求正文与图片链接")
        downloaded_images = _download_image_links(image_links, output_dir)
        _raise_if_job_cancelled(db, job.id)
        _update_stage(
            job,
            db,
            "collect",
            "收集输入",
            "success",
            f"已收集 {len(_extract_sections(markdown_text))} 个章节，发现 {len(image_links)} 张图片链接",
        )
        _update_stage(job, db, "image_analysis", "图片识别", "running", "正在进行图片优先识别")
        image_analysis = _analyze_images(api_key, model, base_url, downloaded_images)
        _raise_if_job_cancelled(db, job.id)
        _update_stage(
            job,
            db,
            "image_analysis",
            "图片识别",
            "success",
            f"已识别 {len(image_analysis)} 张图片，下载失败 {sum(1 for item in downloaded_images if item.get('download_status') == 'failed')} 张",
        )

        _update_stage(job, db, "requirement", "需求分析", "running", "正在生成证据链和功能点")
        analysis = _build_requirement_analysis(
            job=job,
            db=db,
            markdown_text=markdown_text,
            downloaded_images=downloaded_images,
            image_analysis=image_analysis,
            api_key=api_key,
            model=model,
            base_url=base_url,
            audit_log=audit_log,
        )
        _raise_if_job_cancelled(db, job.id)

        evidence_trace = analysis["evidence_trace"]
        evidence_trace["image_links"] = image_links
        evidence_trace["downloaded_images"] = downloaded_images
        evidence_trace["image_analysis"] = image_analysis
        function_points = analysis["function_points"]
        pending_confirmations = analysis.get("pending_confirmations") or []
        _persist_stage_artifact(output_dir, "evidence_trace.json", evidence_trace)
        _persist_stage_artifact(output_dir, "function_points.json", function_points)
        _update_stage(
            job,
            db,
            "requirement",
            "需求分析",
            "success",
            f"已提取 {len(function_points.get('function_points', []))} 个功能点，待确认 {len(pending_confirmations)} 项",
        )

        _update_stage(job, db, "testcase", "用例设计", "running", "正在生成执行级测试用例")
        def update_testcase_progress(summary: str) -> None:
            _update_stage(job, db, "testcase", "用例设计", "running", summary)
            _raise_if_job_cancelled(db, job.id)

        testcase_package = _build_testcase_package(
            function_points,
            pending_confirmations,
            api_key,
            model,
            base_url,
            audit_log,
            progress_callback=update_testcase_progress,
        )
        _raise_if_job_cancelled(db, job.id)
        _persist_stage_artifact(output_dir, "testcase_package.json", testcase_package)
        _update_stage(
            job,
            db,
            "testcase",
            "用例设计",
            "success",
            f"已生成 {len(testcase_package.get('testcases', []))} 条测试用例",
        )

        _update_stage(job, db, "review", "质量审查", "running", "正在审查覆盖率和可执行性")
        review_report = _build_review_report(
            evidence_trace,
            function_points,
            testcase_package,
            pending_confirmations,
            api_key,
            model,
            base_url,
            audit_log,
            block_on_fail=False,
        )
        _raise_if_job_cancelled(db, job.id)
        review_report["quality_summary"] = _build_case_generation_quality_summary(function_points, testcase_package)
        _persist_stage_artifact(output_dir, "review_report.json", review_report)
        # 单次审查即定稿：审查只产出报告与结论，不再驱动返工循环（对齐 claw_5skill_final）
        testcase_package = {
            "testcases": _renumber_cases_global(
                _dedupe_cases_global(testcase_package.get("testcases") or []),
                function_points,
            )
        }
        _persist_stage_artifact(output_dir, "testcase_package.json", testcase_package)
        review_report["case_count"] = len(testcase_package.get("testcases") or [])

        final_readiness = (review_report.get("summary") or {}).get("release_readiness")
        conditional_export = final_readiness == "fail"
        attach_review_report = final_readiness in {"conditional_pass", "fail"}
        review_findings = review_report.get("findings") or []
        if final_readiness == "fail":
            _update_stage(
                job,
                db,
                "review",
                "质量审查",
                "success",
                f"审查未通过（有条件导出），保留 {len(review_findings)} 项待人工复核问题",
            )
        elif final_readiness == "conditional_pass":
            _update_stage(
                job,
                db,
                "review",
                "质量审查",
                "success",
                f"审查有条件通过，保留 {len(review_findings)} 项改进建议",
            )
        else:
            _update_stage(job, db, "review", "质量审查", "success", "审查通过")
        execution_proof = _build_execution_proof(
            audit_log=audit_log,
            image_links=image_links,
            downloaded_images=downloaded_images,
            image_analysis=image_analysis,
            function_points=function_points,
            testcase_package=testcase_package,
            pending_confirmations=pending_confirmations,
            started_at=run_started_at,
        )
        review_report["execution_proof_runtime"] = execution_proof
        review_report["quality_summary"] = _build_case_generation_quality_summary(function_points, testcase_package)
        _persist_stage_artifact(output_dir, "review_report.json", review_report)
        _update_stage(
            job,
            db,
            "review",
            "质量审查",
            "success",
            f"审查结论：{review_report.get('review_conclusion', '有条件通过')}",
        )

        _update_stage(job, db, "export", "导出 XMind", "running", "正在按完整用例结构生成 XMind 文件")
        if audit_log is not None:
            audit_log.append(
                {
                    "skill": "deterministic-xmind-exporter",
                    "attempt": "python",
                    "status": "passed",
                    "case_count": len(testcase_package.get("testcases") or []),
                    "policy": "artifact-exporter disabled; export from TestcasePackage",
                }
            )
        xmindmark_text = _build_xmindmark(job, function_points, testcase_package, review_report)

        try:
            _write_text_file(output_dir, "delivery_summary.md", _build_delivery_summary(job, function_points, testcase_package, review_report))
        except Exception:
            pass

        xmindmark_file_name = f"{output_stem}.xmindmark"
        xmindmark_file_path = _write_text_file(output_dir, xmindmark_file_name, xmindmark_text)

        if payload.get("export_xmind", True):
            try:
                xmind_file_path = _convert_xmindmark(output_dir, xmindmark_file_path, output_stem)
                _upsert_artifact(
                    db,
                    job_id=job.id,
                    artifact_type="xmind",
                    file_name=os.path.basename(xmind_file_path),
                    file_path=xmind_file_path,
                    content_json=None,
                )
            except Exception as exc:
                log_payload = {"error": str(exc)}
                _upsert_artifact(
                    db,
                    job_id=job.id,
                    artifact_type="xmind_export_log",
                    file_name="xmind_export_log.json",
                    file_path=_write_json_file(output_dir, "xmind_export_log.json", log_payload),
                    content_json=log_payload,
                )
                raise
        _raise_if_job_cancelled(db, job.id)
        _remove_file_if_exists(xmindmark_file_path)
        _update_stage(job, db, "export", "导出 XMind", "success", "已完成 XMind 导出")
        review_report_path = None
        if attach_review_report:
            review_report_path = _write_json_file(output_dir, "review_report.json", review_report)
            _upsert_artifact(
                db,
                job_id=job.id,
                artifact_type="review_report",
                file_name="review_report.json",
                file_path=review_report_path,
                content_json=review_report,
            )
        job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
        job.status = "SUCCESS"
        job.task_id = None
        if final_readiness == "fail":
            job.summary = f"已导出 XMind（质量审查未通过，{len(review_findings)} 项问题待人工复核），共 {review_report['case_count']} 条用例"
        elif final_readiness == "conditional_pass":
            job.summary = f"已生成 {review_report['case_count']} 条用例并导出 XMind（有条件通过，{len(review_findings)} 项改进建议）"
        else:
            job.summary = f"已生成 {review_report['case_count']} 条用例，并导出 XMind"
        job.error_message = None
        job.finished_at = utc_now_naive()
        db.commit()
        db.refresh(job)
        _cleanup_previous_success_xmind_for_project(db, job)
        _cleanup_expired_success_xmind(db, retention_days=3)
        db.commit()
        keep_paths = _collect_final_artifact_paths(db, job.id)
        if review_report_path:
            keep_paths.add(review_report_path)
        _cleanup_case_generation_output_dir(output_dir, keep_paths=keep_paths)
    except Exception as exc:
        job = db.get(CaseGenerationJob, job_id)
        if job is not None:
            if job.status == "CANCELLED":
                job.summary = "生成已取消"
                job.error_message = "任务已手动停止"
                job.task_id = None
                job.finished_at = utc_now_naive()
                db.commit()
                return
            payload = dict(job.input_payload_json or {})
            job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
            _mark_last_stage_failed(job, summary=str(exc))
            job.status = "FAILED"
            job.task_id = None
            job.summary = "生成失败"
            job.error_message = str(exc)
            job.finished_at = utc_now_naive()
            db.commit()
    finally:
        db.close()
