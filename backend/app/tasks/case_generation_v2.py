from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import contextvars
import hashlib
import json
import logging
import mimetypes
import os
import re
import subprocess
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import inspect
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
from app.models import AIModelConfig, CaseGenerationV2Artifact, CaseGenerationV2Job
from app.tasks import case_generation as original_case_generation
from app.tasks.case_generation_common import (
    convert_xmindmark_to_xmind,
    inspect_xmind_archive,
    write_xmind_archive,
)
from app.tasks.case_generation_runtime import (
    AttemptHeartbeat,
    SupersededAttemptError,
    assert_active_attempt,
    attempt_output_dir,
    bind_attempt,
    current_attempt_id,
    current_run_id,
    ensure_attempt,
    finish_attempt,
    mark_last_job_stage_failed,
    mark_attempt_running,
    raise_if_job_cancelled,
    sync_attempt_from_job,
    update_job_stage,
)
from app.tasks.secure_fetch import fetch_resource, fetch_resource_async
from app.tasks.model_client import call_json_chat_completion
from app.timeutil import utc_now_naive


logger = logging.getLogger(__name__)


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
_REQUIREMENT_BATCH_MAX_SECTIONS = settings.case_gen_requirement_batch_max_sections
_REQUIREMENT_BATCH_CONCURRENCY = max(1, settings.case_gen_requirement_batch_concurrency)
_REQUIREMENT_MAX_TOKENS = settings.case_gen_requirement_max_tokens
_PENDING_CONFIRMATION_LIMIT = settings.case_gen_pending_confirmation_limit
_PENDING_CONFIRMATION_TEXT_LIMIT = settings.case_gen_pending_confirmation_text_limit
_FUNCTION_POINT_TEXT_LIMIT = settings.case_gen_function_point_text_limit
_TESTCASE_FP_BATCH_SIZE = settings.case_gen_testcase_fp_batch_size
_TESTCASE_REPAIR_MAX_ROUNDS = settings.case_gen_testcase_repair_max_rounds
_CASE_GENERATION_MAX_CONCURRENCY = settings.case_gen_max_concurrency
_TRUSTED_SHARD_CONCURRENCY = max(1, settings.case_gen_trusted_shard_concurrency)
_SCOPE_INDEX_CONCURRENCY = max(1, settings.case_gen_scope_index_concurrency)
_SCOPE_INDEX_TWO_PHASE_TRIGGER_SECTIONS = max(1, settings.case_gen_scope_index_two_phase_trigger_sections)
_SCOPE_INDEX_TWO_PHASE_TRIGGER_TEXT = max(1, settings.case_gen_scope_index_two_phase_trigger_text)
_TRUSTED_MODEL_GATE_ENABLED = bool(settings.case_gen_trusted_model_gate_enabled)
_TRUSTED_SHARD_MAX_ATTEMPTS = max(1, settings.case_gen_trusted_shard_max_attempts)
_MAX_AI_RETRIES = settings.case_gen_max_ai_retries
_DEFAULT_CHAT_TIMEOUT_SECONDS = settings.case_gen_default_chat_timeout_seconds
_LONG_CHAT_TIMEOUT_SECONDS = settings.case_gen_long_chat_timeout_seconds
_MAX_JSON_RETRY_TOKENS = 24000
_TRUSTED_GENERATION_CONTRACT_VERSION = "trusted-state-v3"
_CURRENT_STATE_MARKERS = (
    "现有效果",
    "当前效果",
    "当前状态",
    "现状",
    "问题场景",
    "问题现象",
    "优化前",
    "修改前",
    "变更前",
    "旧版",
    "原效果",
)
_TARGET_STATE_MARKERS = (
    "优化效果",
    "优化期望",
    "期望效果",
    "目标效果",
    "正确场景",
    "解决方案",
    "优化后",
    "修改后",
    "变更后",
    "新版",
)
_CURRENT_STATE_NEGATION_PATTERN = re.compile(
    r"不再|不应|不得|不可|不显示|未显示|移除|隐藏|消失|改为|变更为|调整为|"
    r"由.+?(?:改|变|调整).+|区别于|不同于|不位于"
)
_STATE_ATTRIBUTE_PATTERNS = {
    "position": (
        ("bottom_left", re.compile(r"底部靠左|底部左侧|左下(?:角|方)?|bottom\s*[-_ ]?left", re.IGNORECASE)),
        ("bottom_center", re.compile(r"底部(?:中央|居中|中间)|底端(?:中央|居中)|bottom\s*[-_ ]?center", re.IGNORECASE)),
        ("bottom_right", re.compile(r"底部靠右|底部右侧|右下(?:角|方)?|bottom\s*[-_ ]?right", re.IGNORECASE)),
        ("top_left", re.compile(r"顶部靠左|顶部左侧|左上(?:角|方)?|top\s*[-_ ]?left", re.IGNORECASE)),
        ("top_center", re.compile(r"顶部(?:中央|居中|中间)|顶端(?:中央|居中)|top\s*[-_ ]?center", re.IGNORECASE)),
        ("top_right", re.compile(r"顶部靠右|顶部右侧|右上(?:角|方)?|top\s*[-_ ]?right", re.IGNORECASE)),
    ),
    "border": (
        ("no_border", re.compile(r"无(?:按钮)?边框|不显示边框|去掉边框|borderless|no\s+border", re.IGNORECASE)),
        ("with_border", re.compile(r"有(?:按钮)?边框|显示边框|增加边框|with\s+border", re.IGNORECASE)),
    ),
}
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
_PIPELINE_MODE_ALIASES = {
    "clone": "lite",
    "lite": "lite",
    "trusted_v2": "trusted",
    "trusted": "trusted",
}
_SUPPORTED_PIPELINE_MODES = {"lite", "trusted"}
_SCOPE_INDEX_BATCH_MAX_SECTIONS = 4
_SCOPE_INDEX_BATCH_TEXT_LIMIT = 10000
_SCOPE_INDEX_BATCH_TRIGGER_SECTIONS = 8
_SCOPE_INDEX_BATCH_TRIGGER_TEXT = 24000


class ModelJSONParseError(ValueError):
    def __init__(self, message: str, *, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


class ModelContractError(ValueError):
    pass


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


def _trusted_source_order_key(value, fallback: int = 0) -> tuple:
    text = str(value if value is not None else "").strip()
    if not text:
        return (fallback,)
    parts = re.split(r"[._\-]", text)
    parsed: list[int | str] = []
    for part in parts:
        if not part:
            continue
        parsed.append(int(part) if part.isdigit() else part)
    return tuple(parsed or [fallback])


def _trusted_source_sort_key(source: dict, fallback: int = 0) -> tuple:
    return _trusted_source_order_key(source.get("source_order"), fallback)


def _default_test_design_profile(source: dict | None = None) -> dict:
    source = source or {}
    risk_signals = source.get("risk_signals") if isinstance(source.get("risk_signals"), list) else []
    title = str(source.get("title") or source.get("title_path") or "").strip()
    return {
        "applicable_methods": ["equivalence"],
        "risk_signals": risk_signals,
        "must_cover": [title] if title else [],
        "merge_allowed": [],
        "not_applicable": [],
        "coverage_budget": {
            "guidance": "按 must_cover 和适用方法生成可观察用例；低风险重复字段可合并，不以固定条数为目标。"
        },
    }


def _normalize_test_design_profile(value, source: dict | None = None) -> dict:
    profile = dict(value) if isinstance(value, dict) else _default_test_design_profile(source)
    for key in ("applicable_methods", "risk_signals", "must_cover", "merge_allowed", "not_applicable"):
        if not isinstance(profile.get(key), list):
            profile[key] = [] if profile.get(key) in (None, "") else [str(profile.get(key))]
    coverage_budget = profile.get("coverage_budget")
    if not isinstance(coverage_budget, dict):
        coverage_budget = {"guidance": str(coverage_budget or "").strip()}
    for forbidden in ("min", "target", "max"):
        coverage_budget.pop(forbidden, None)
    coverage_budget.setdefault("guidance", "按 must_cover 和适用方法生成可观察用例；低风险重复字段可合并，不以固定条数为目标。")
    profile["coverage_budget"] = coverage_budget
    return profile


def _coverage_budget_forbidden_keys(profile_value) -> list[str]:
    if not isinstance(profile_value, dict):
        return []
    coverage_budget = profile_value.get("coverage_budget")
    if not isinstance(coverage_budget, dict):
        return []
    return [key for key in ("min", "target", "max") if key in coverage_budget]


def _trusted_scope_source_items(scope_index: dict) -> list[dict]:
    if not isinstance(scope_index, dict):
        return []
    blocks = scope_index.get("source_blocks") if isinstance(scope_index.get("source_blocks"), list) else []
    shards = scope_index.get("shards") if isinstance(scope_index.get("shards"), list) else []
    shard_by_source = {
        str(item.get("direct_testcase_source") or item.get("source_id") or "").strip(): item
        for item in shards
        if isinstance(item, dict) and str(item.get("direct_testcase_source") or item.get("source_id") or "").strip()
    }
    items: list[dict] = []
    if blocks:
        for index, block in enumerate(blocks, start=1):
            if not isinstance(block, dict):
                continue
            source_id = str(block.get("block_id") or block.get("source_id") or f"SRC-{index:03d}").strip()
            shard = shard_by_source.get(source_id) or {}
            title_path = str(shard.get("title_path") or block.get("title_path") or block.get("title") or source_id).strip()
            title = str(block.get("title") or shard.get("title") or title_path or source_id).strip()
            raw_profile = shard.get("test_design_profile") if isinstance(shard.get("test_design_profile"), dict) else {}
            forbidden_budget_keys = _coverage_budget_forbidden_keys(raw_profile)
            item = {
                "source_id": source_id,
                "shard_id": str(shard.get("shard_id") or f"SHARD-{index:03d}").strip(),
                "title": title,
                "title_path": title_path,
                "module": str(shard.get("module") or block.get("module") or title or "可信范围").strip(),
                "scene": str(shard.get("scene") or block.get("scene") or title or "可信场景").strip(),
                "source_order": shard.get("source_order", block.get("source_order", index)),
                "source_order_index": index,
                "xmind_source_node": str(shard.get("xmind_source_node") or block.get("xmind_source_node") or f"{source_id}｜{title_path}").strip(),
                "primary_sections": shard.get("assigned_primary_sources") if isinstance(shard.get("assigned_primary_sources"), list) else [source_id],
                "dependency_sections": shard.get("assigned_dependency_sources") if isinstance(shard.get("assigned_dependency_sources"), list) else [],
                "rule_clusters": shard.get("rule_clusters") if isinstance(shard.get("rule_clusters"), list) else [],
                "complexity": str(shard.get("complexity") or block.get("complexity") or "medium").strip().lower(),
                "complexity_score": shard.get("complexity_score"),
                "test_design_profile": _normalize_test_design_profile(raw_profile, shard or block),
                "coverage_budget_forbidden_keys": forbidden_budget_keys,
                "smoking_scope_note": str(shard.get("smoke_test_scope_note") or shard.get("smoking_scope_note") or "").strip(),
                "source_doc_id": str(shard.get("source_doc_id") or block.get("source_doc_id") or "").strip(),
                "source_excerpt": str(shard.get("source_excerpt") or block.get("source_excerpt") or "").strip(),
                "source_content_sha256": str(shard.get("source_content_sha256") or block.get("source_content_sha256") or "").strip(),
                "image_refs": list(shard.get("image_refs") or block.get("image_refs") or []),
                "image_evidence": list(shard.get("image_evidence") or block.get("image_evidence") or []),
                "source_state_semantics": (
                    dict(shard.get("source_state_semantics") or block.get("source_state_semantics") or {})
                    if isinstance(shard.get("source_state_semantics") or block.get("source_state_semantics") or {}, dict)
                    else {}
                ),
                "evidence_refs": list(shard.get("evidence_refs") or block.get("evidence_refs") or []),
            }
            items.append(item)
        return items
    legacy = scope_index.get("direct_testcase_sources") if isinstance(scope_index.get("direct_testcase_sources"), list) else []
    for index, source in enumerate(legacy, start=1):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or f"SRC-{index:03d}").strip()
        title_path = str(source.get("title_path") or source.get("source_path") or source.get("title") or source_id).strip()
        title = str(source.get("title") or title_path or source_id).strip()
        raw_profile = source.get("test_design_profile") if isinstance(source.get("test_design_profile"), dict) else {}
        forbidden_budget_keys = _coverage_budget_forbidden_keys(raw_profile)
        item = {
            "source_id": source_id,
            "shard_id": str(source.get("shard_id") or f"SHARD-{index:03d}").strip(),
            "title": title,
            "title_path": title_path,
            "module": str(source.get("module") or title or "可信范围").strip(),
            "scene": str(source.get("scene") or title or "可信场景").strip(),
            "source_order": source.get("source_order", index),
            "source_order_index": index,
            "xmind_source_node": str(source.get("xmind_source_node") or f"{source_id}｜{title_path}").strip(),
            "primary_sections": source.get("primary_sections") if isinstance(source.get("primary_sections"), list) else [],
            "dependency_sections": source.get("dependency_sections") if isinstance(source.get("dependency_sections"), list) else [],
            "rule_clusters": source.get("rule_clusters") if isinstance(source.get("rule_clusters"), list) else [],
            "complexity": str(source.get("complexity") or "medium").strip().lower(),
            "complexity_score": source.get("complexity_score"),
            "test_design_profile": _normalize_test_design_profile(raw_profile, source),
            "coverage_budget_forbidden_keys": forbidden_budget_keys,
            "smoking_scope_note": str(source.get("smoking_scope_note") or "").strip(),
            "source_doc_id": str(source.get("source_doc_id") or "").strip(),
            "source_excerpt": str(source.get("source_excerpt") or "").strip(),
            "source_content_sha256": str(source.get("source_content_sha256") or "").strip(),
            "image_refs": list(source.get("image_refs") or []),
            "image_evidence": list(source.get("image_evidence") or []),
            "source_state_semantics": dict(source.get("source_state_semantics") or {}) if isinstance(source.get("source_state_semantics"), dict) else {},
            "evidence_refs": list(source.get("evidence_refs") or []),
        }
        items.append(item)
    return items


def _trusted_scope_shards(scope_index: dict) -> list[dict]:
    sources = _trusted_scope_source_items(scope_index)
    return [
        {
            "shard_id": item.get("shard_id"),
            "direct_testcase_source": item.get("source_id"),
            "source_order": item.get("source_order"),
            "source_order_index": item.get("source_order_index"),
            "title_path": item.get("title_path"),
            "module": item.get("module"),
            "scene": item.get("scene"),
            "xmind_source_node": item.get("xmind_source_node"),
            "assigned_primary_sources": item.get("primary_sections") or [item.get("source_id")],
            "assigned_dependency_sources": item.get("dependency_sections") or [],
            "rule_clusters": item.get("rule_clusters") or [],
            "smoke_test_scope_note": item.get("smoking_scope_note") or "",
            "risk_signals": (item.get("test_design_profile") or {}).get("risk_signals") or [],
            "complexity_score": item.get("complexity_score") or 3,
            "test_design_profile": item.get("test_design_profile") or _default_test_design_profile(item),
        }
        for item in sources
    ]


def _trusted_source_by_id(scope_index: dict) -> dict[str, dict]:
    return {item["source_id"]: item for item in _trusted_scope_source_items(scope_index) if item.get("source_id")}


def _format_duration_zh(seconds: float | int | None) -> str:
    try:
        total_seconds = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        total_seconds = 0
    minutes, secs = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _is_json_truncation_error(error: Exception | str) -> bool:
    text = str(error)
    return "JSON 对象不完整" in text or "模型输出为空" in text or "未闭合" in text


def _case_evidence_refs(case: dict, fp: dict | None = None) -> list[str]:
    refs: list[str] = []
    evidence_refs = case.get("evidence_refs") if isinstance(case.get("evidence_refs"), list) else []
    traceability = case.get("traceability") or {}
    sources = traceability.get("sources") if isinstance(traceability, dict) else []
    for value in list(evidence_refs or []) + list(sources or []) + list((fp or {}).get("source_refs") or []):
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
    job: CaseGenerationV2Job
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
    output_dir = attempt_output_dir(job_id, "v2")
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
    except OSError as exc:
        logger.debug("unable to chmod generated file %s: %s", path, exc)
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
            except OSError as exc:
                logger.warning("unable to remove temporary file %s: %s", temp_path, exc)


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


def _write_yaml_file(output_dir: str, file_name: str, payload: dict | list) -> str:
    file_path = os.path.join(output_dir, file_name)

    def _write(path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)

    return _atomic_replace_file(file_path, _write)


def _read_text_if_exists(path: Path, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _normalize_pipeline_mode(mode: str | None) -> str:
    raw_mode = str(mode or "lite").strip() or "lite"
    normalized = _PIPELINE_MODE_ALIASES.get(raw_mode, raw_mode)
    if normalized not in _SUPPORTED_PIPELINE_MODES:
        raise ValueError(f"不支持的 V2 生成模式：{raw_mode}")
    return normalized


def _is_trusted_pipeline_mode(mode: str | None) -> bool:
    return _normalize_pipeline_mode(mode) == "trusted"


def _resolve_rules_dir(raw_value: str | None) -> Path:
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return Path()
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = (_BACKEND_ROOT / path).resolve()
    return path


def _resolve_claw_rules_dir() -> Path:
    return _resolve_rules_dir(settings.case_generation_rules_dir)


def _resolve_unified_rules_dir() -> Path:
    configured = _resolve_rules_dir(settings.case_generation_unified_rules_dir)
    if configured.exists():
        return configured
    return _resolve_claw_rules_dir()


def _skill_schema_names(skill_name: str) -> list[str]:
    schema_map = {
        "testcase-orchestrator": ["source_manifest.template.yaml"],
        "scope-indexer": ["scope_index.template.yaml"],
        "evidence-builder": ["evidence_trace.template.yaml"],
        "requirement-analyzer": ["evidence_trace.template.yaml", "function_points.template.yaml"],
        "testcase-designer": ["testcase_package.template.yaml"],
        "quality-reviewer": ["review_report.template.yaml"],
        "artifact-exporter": ["xmindmark.template.md", "delivery_summary.template.md"],
        "trusted-gate": ["gate_report.template.yaml"],
        "review-pipeline-handoff": ["gate_report.template.yaml"],
    }
    return schema_map.get(skill_name, [])


def _read_skill_templates_from_dir(schema_dir: Path, skill_name: str) -> str:
    parts = []
    for schema_name in _skill_schema_names(skill_name):
        text = _read_text_if_exists(schema_dir / schema_name)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _load_skill_template(skill_name: str, mode: str | None = None) -> str:
    normalized_mode = _normalize_pipeline_mode(mode)
    unified_dir = _resolve_unified_rules_dir()
    if unified_dir.exists():
        text = _read_skill_templates_from_dir(unified_dir / "schemas" / normalized_mode, skill_name)
        if text:
            return text
    rules_dir = _resolve_claw_rules_dir()
    if not rules_dir.exists():
        return ""
    return _read_skill_templates_from_dir(rules_dir / "schemas", skill_name)


def _load_claw_skill_context(skill_name: str, mode: str | None = None) -> str:
    _normalize_pipeline_mode(mode)
    unified_dir = _resolve_unified_rules_dir()
    if unified_dir.exists():
        parts = [
            _read_text_if_exists(unified_dir / "README.md", 18000),
            _read_text_if_exists(unified_dir / "skills" / skill_name / "SKILL.md", 16000),
        ]
        text = "\n\n---\n\n".join(part for part in parts if part)
        if text:
            return text
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


def _is_empty_or_generic_only(values, patterns: tuple[str, ...], *, formatter=str) -> bool:
    items = values if isinstance(values, list) else [values]
    texts = [formatter(item).strip() for item in items if formatter(item).strip()]
    if not texts:
        return True

    def normalized(value: str) -> str:
        return re.sub(r"[\s，。；：、,.!?！？:;\-]+", "", value).lower()

    normalized_patterns = {normalized(pattern) for pattern in patterns}
    return all(normalized(text) in normalized_patterns for text in texts)


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
    _write_json_file(output_dir, file_name, payload)


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


def _update_stage(job: CaseGenerationV2Job, db, key: str, title: str, status: str, summary: str) -> None:
    update_job_stage(db, job, key, title, status, summary)


def _mark_last_stage_failed(job: CaseGenerationV2Job, *, summary: str) -> None:
    mark_last_job_stage_failed(job, summary=summary)


def _raise_if_job_cancelled(db, job_id: int) -> None:
    raise_if_job_cancelled(db, CaseGenerationV2Job, job_id)


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


# —— 背景/概述类章节：明确不分析、不生成、不审查 ——
# 这类章节只是需求文档的引言/环境说明/术语，本身不构成可测需求；
# 强制为其生成用例会产生“环境URL可访问性”之类的虚高用例。这里在分析入口处
# 直接剔除，使后续的功能点提取、用例设计、质量审查全程都看不到它们。
_BACKGROUND_SECTION_TITLE_PATTERNS = (
    "需求背景",
    "背景",
    "概述",
    "前言",
    "引言",
    "修订记录",
    "修改记录",
    "版本记录",
    "术语",
    "名词解释",
    "文档说明",
    "需求概览",
    "overview",
    "background",
    "introduction",
    "revision history",
)


def _is_background_section(section: dict) -> bool:
    title_key = _normalize_title_key(section.get("title"))
    if not title_key:
        return False
    # 去掉中文序号前缀（如“一、需求背景”→“需求背景”）后再匹配，避免漏判
    stripped = re.sub(r"^[一二三四五六七八九十0-9]+[、.．\s]*", "", title_key)
    for pattern in _BACKGROUND_SECTION_TITLE_PATTERNS:
        key = re.sub(r"\s+", "", pattern.lower())
        if title_key == key or stripped == key:
            return True
    return False


def _filter_out_background_sections(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    """剔除背景/概述类章节，返回 (保留章节, 被剔除章节)。

    仅对“顶层背景章节”及其子章节生效：若一个被判定为背景的章节下还有子章节，
    这些子章节也一并剔除（背景章节内部通常不含独立可测需求）。
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    skip_until_level: int | None = None
    for section in sections:
        level = section.get("level", 1)
        if skip_until_level is not None:
            if level > skip_until_level:
                dropped.append(section)
                continue
            skip_until_level = None
        if _is_background_section(section):
            dropped.append(section)
            skip_until_level = level
            continue
        kept.append(section)
    return kept, dropped

# claw_5skill_final/skills/requirement-analyzer/SKILL.md 规定 module/scene 必须
# 继承需求文档原始章节标题，但 LLM 经常自创/翻译/归并模块名。这里在代码侧把
# 功能点的 module/scene 确定性回填为真实章节标题，不再依赖模型自觉。
_MODULE_LEVEL_THRESHOLD = 2  # level<=该阈值的最近祖先章节作为 module，更深章节作为 scene
_HEADING_INLINE_TAG_PATTERN = re.compile(r"<[^>]+>")
_HEADING_STATUS_PATTERN = re.compile(r"【[^】]*】")


def _clean_heading_text(title) -> str:
    """清洗章节标题：剥离内联 HTML/font 标签与【已完成】等状态标记。"""
    text = _HEADING_INLINE_TAG_PATTERN.sub("", str(title or ""))
    text = _HEADING_STATUS_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_title_key(value) -> str:
    """标题归一化键，用于功能点与章节标题的鲁棒匹配。"""
    return re.sub(r"\s+", "", _clean_heading_text(value)).lower()


def _build_section_lineage(sections: list[dict]) -> dict[int, dict]:
    """为每个章节 source_order 计算确定性的 (module, scene) 归属。

    module = 该章节 level<=_MODULE_LEVEL_THRESHOLD 的最近祖先标题；
    scene  = 章节自身标题。这样 L2 章节成为 module、其下 L3 章节成为 scene，
    既符合 SKILL 规则（module 一级分组、scene 二级分组），又严格跟随原文。
    """
    lineage: dict[int, dict] = {}
    ancestors: list[dict] = []  # 祖先栈：[{level, title}]
    for sec in sections:
        level = sec.get("level", 1)
        title = _clean_heading_text(sec.get("title")) or str(sec.get("title") or "").strip()
        while ancestors and ancestors[-1]["level"] >= level:
            ancestors.pop()
        chain = ancestors + [{"level": level, "title": title}]
        module_candidates = [a["title"] for a in chain if a["level"] <= _MODULE_LEVEL_THRESHOLD and a["title"]]
        module = module_candidates[-1] if module_candidates else (chain[0]["title"] or "默认模块")
        lineage[sec.get("source_order")] = {
            "module": module or "默认模块",
            "scene": title or module or "默认场景",
            "title": title,
            "level": level,
        }
        ancestors.append({"level": level, "title": title})
    return lineage


def _realign_function_point_modules(
    function_points: list[dict], lineage: dict[int, dict]
) -> int:
    """把功能点的 module/scene 确定性回填为真实章节标题。

    锚定优先级：1) source_order 命中章节序号；2) source_refs 引用的章节标题；
    3) 模型已填 module/scene/title 与章节标题匹配。无法锚定时保留原值，不破坏数据。
    返回被修正的功能点数量。
    """
    if not lineage:
        return 0
    titles_norm: dict[str, dict] = {}
    for info in lineage.values():
        key = _normalize_title_key(info.get("title"))
        if key:
            titles_norm.setdefault(key, info)
    realigned = 0
    for fp in function_points:
        if not isinstance(fp, dict):
            continue
        info = None
        source_order = fp.get("source_order")
        if isinstance(source_order, int) and source_order in lineage:
            info = lineage[source_order]
        if info is None:
            for ref in fp.get("source_refs") or []:
                if not isinstance(ref, dict):
                    continue
                for key in ("section", "doc", "quote"):
                    candidate = _normalize_title_key(ref.get(key))
                    if candidate and candidate in titles_norm:
                        info = titles_norm[candidate]
                        break
                if info:
                    break
        if info is None:
            for key in ("title", "module", "scene"):
                candidate = _normalize_title_key(fp.get(key))
                if candidate and candidate in titles_norm:
                    info = titles_norm[candidate]
                    break
        if info is None:
            continue
        new_module = info["module"]
        new_scene = info["scene"] or new_module
        if fp.get("module") != new_module or fp.get("scene") != new_scene:
            realigned += 1
        fp["module"] = new_module
        fp["scene"] = new_scene
    return realigned


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


def _truncate_keep_key_paragraphs(body: str, limit: int) -> str:
    """在长度上限内尽量保留正文，超长时优先保留含测试价值关键词的段落。

    与简单截断不同：先按段落切分，保证保留首段（通常是功能描述），
    再优先纳入包含“规则/限制/必须/禁止/异常/边界/默认/校验/否则”等
    关键词的段落，确保大章节里真正可测的规则不被截掉。
    """
    text = (body or "").strip()
    if len(text) <= limit:
        return text
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return _truncate_text(text, limit)
    key_markers = ("规则", "限制", "必须", "禁止", "不允许", "异常", "边界", "默认", "校验", "否则", "当", "如果", "需", "支持", "约束")
    selected: list[str] = []
    used = 0
    # 首段优先保留
    first = paragraphs[0]
    selected.append(first)
    used += len(first)
    # 其余段落：含关键词的优先
    rest = paragraphs[1:]
    key_paras = [p for p in rest if _text_contains_any(p, key_markers)]
    other_paras = [p for p in rest if not _text_contains_any(p, key_markers)]
    for para in key_paras + other_paras:
        if used + len(para) + 2 > limit:
            continue
        selected.append(para)
        used += len(para) + 2
    result = "\n\n".join(selected)
    return result if result else _truncate_text(text, limit)


def _compact_sections_for_ai(sections: list[dict], *, per_section_limit: int = 2400, total_limit: int = 24000) -> list[dict]:
    compacted: list[dict] = []
    total = 0

    for item in sections:
        level = item.get("level", 3)
        body = _strip_markdown_noise(item.get("body") or "")

        # 大上下文模型下尽量保留完整章节正文，避免丢失同章节的规则与上下文：
        # 所有层级都保留完整正文，仅在超过 per_section_limit 时才按
        # “关键段落优先”策略压缩，而不再像旧逻辑那样把 L3+ 章节砍到只剩第一段。
        body = _truncate_keep_key_paragraphs(body, per_section_limit)

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
        # 同时受「文本大小」与「章节数」双重上限约束：任一超出即开新批，
        # 避免大量短章节挤进同一批后被「每批功能点上限」截断而丢失章节。
        exceeds_text = current_batch and current_size + section_size > _REQUIREMENT_BATCH_TEXT_LIMIT
        exceeds_count = current_batch and len(current_batch) >= _REQUIREMENT_BATCH_MAX_SECTIONS
        if exceeds_text or exceeds_count:
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
    resource = fetch_resource(
        source_url,
        max_bytes=settings.case_gen_max_source_download_bytes,
        accepted_prefixes=("text/", "application/json", "application/markdown", "application/octet-stream"),
        timeout_seconds=30.0,
    )
    content_type = resource.content_type.lower()
    text = resource.content.decode("utf-8", errors="replace")
    if "text/html" in content_type:
        image_links = [urljoin(resource.url, item) for item in _HTML_IMAGE_PATTERN.findall(text)]
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


def _extract_image_links(markdown_text: str, base_url: str | None = None) -> list[str]:
    links = [item.strip() for item in _MARKDOWN_IMAGE_PATTERN.findall(markdown_text)]
    links.extend(item.strip() for item in _HTML_IMAGE_PATTERN.findall(markdown_text))
    resolved = [urljoin(base_url, item) if base_url else item for item in links]
    return sorted({item for item in resolved if item and not item.startswith("data:")})


async def _download_single_image_async(client: httpx.AsyncClient, *, index: int, url: str, image_dir: str) -> dict:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        suffix = ".png"
    file_name = f"image_{index:02d}{suffix}"
    file_path = os.path.join(image_dir, file_name)
    record = {"image_id": f"IMG-{index:03d}", "url": url, "file_name": file_name, "file_path": file_path}
    try:
        resource = await fetch_resource_async(
            client,
            url,
            max_bytes=settings.case_gen_max_image_download_bytes,
            accepted_prefixes=("image/",),
        )

        def _write_image(path: str, content: bytes = resource.content) -> None:
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
    async with httpx.AsyncClient(timeout=30.0) as client:
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
        raw_test_hints = item.get("test_hints")
        if isinstance(raw_test_hints, dict):
            test_hints = {
                "positive": [_truncate_text(str(text), 140) for text in list(raw_test_hints.get("positive") or [])[:3]],
                "boundary": [_truncate_text(str(text), 140) for text in list(raw_test_hints.get("boundary") or [])[:3]],
                "negative": [_truncate_text(str(text), 140) for text in list(raw_test_hints.get("negative") or [])[:3]],
            }
        elif isinstance(raw_test_hints, list):
            hint_values = [_truncate_text(str(text), 140) for text in raw_test_hints[:6]]
            test_hints = {"positive": hint_values[:3], "boundary": hint_values[3:5], "negative": hint_values[5:6]}
        elif raw_test_hints:
            test_hints = {"positive": [_truncate_text(str(raw_test_hints), 140)], "boundary": [], "negative": []}
        else:
            test_hints = {"positive": [], "boundary": [], "negative": []}
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
                "test_hints": test_hints,
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
) -> str:
    if not api_key or api_key == _SECRET_SENTINEL:
        raise ValueError("请提供有效的 OpenAI API Key")
    return await call_json_chat_completion(
        api_key=api_key,
        model=model or _DEFAULT_MODEL,
        base_url=base_url or _OPENAI_BASE_URL,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
    )


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
    mode: str | None = None,
    task_payload: dict | list,
    output_contract: str | None = None,
    validator,
    max_tokens: int,
    timeout_seconds: float = _DEFAULT_CHAT_TIMEOUT_SECONDS,
    max_attempts: int | None = None,
    audit_log: list[dict] | None = None,
    progress_callback=None,
    retry_timeouts: bool = True,
) -> dict:
    normalized_mode = _normalize_pipeline_mode(mode)
    if not output_contract:
        output_contract = _load_skill_template(skill_name, normalized_mode)
        if not output_contract:
            output_contract = "合法 JSON，必须包含所需的核心字段"

    skill_context = _load_claw_skill_context(skill_name, normalized_mode)
    skill_context_sha256 = hashlib.sha256(skill_context.encode("utf-8")).hexdigest()
    output_contract_sha256 = hashlib.sha256(output_contract.encode("utf-8")).hexdigest()
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
        except (json.JSONDecodeError, TypeError):
            top_level_keys = []

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
            f"你正在执行 claw_5skill_unified/{normalized_mode} 的 {skill_name}。\n\n"
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
            if not retry_timeouts and ("模型响应超时" in last_error or "timeout" in last_error.lower()):
                raise
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
            if isinstance(result, dict):
                execution_meta = result.setdefault("_execution_meta", {})
                execution_meta["skill_attempt_count"] = attempt
                execution_meta["pipeline_mode"] = normalized_mode
                execution_meta["skill_name"] = skill_name
                execution_meta["skill_context_sha256"] = skill_context_sha256
                execution_meta["output_contract_sha256"] = output_contract_sha256
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
    mode: str | None = None,
    task_payload: dict | list,
    output_contract: str | None = None,
    validator,
    max_tokens: int,
    timeout_seconds: float = _DEFAULT_CHAT_TIMEOUT_SECONDS,
    max_attempts: int | None = None,
    audit_log: list[dict] | None = None,
    progress_callback=None,
    retry_timeouts: bool = True,
) -> dict:
    normalized_mode = _normalize_pipeline_mode(mode)
    if not output_contract:
        output_contract = _load_skill_template(skill_name, normalized_mode)
        if not output_contract:
            output_contract = "合法 JSON，必须包含所需的核心字段"

    skill_context = _load_claw_skill_context(skill_name, normalized_mode)
    skill_context_sha256 = hashlib.sha256(skill_context.encode("utf-8")).hexdigest()
    output_contract_sha256 = hashlib.sha256(output_contract.encode("utf-8")).hexdigest()
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
        except (json.JSONDecodeError, TypeError):
            top_level_keys = []

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
            f"你正在执行 claw_5skill_unified/{normalized_mode} 的 {skill_name}。\n\n"
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
            if not retry_timeouts and ("模型响应超时" in last_error or "timeout" in last_error.lower()):
                raise
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
            if isinstance(result, dict):
                execution_meta = result.setdefault("_execution_meta", {})
                execution_meta["skill_attempt_count"] = attempt
                execution_meta["pipeline_mode"] = normalized_mode
                execution_meta["skill_name"] = skill_name
                execution_meta["skill_context_sha256"] = skill_context_sha256
                execution_meta["output_contract_sha256"] = output_contract_sha256
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


def _trusted_payload_contract(payload: dict) -> str:
    schema = payload.get("schema") if isinstance(payload, dict) else None
    return json.dumps(schema or {"result": {}}, ensure_ascii=False)


def _trusted_payload_validator(payload: dict):
    schema = payload.get("schema") if isinstance(payload, dict) else {}
    required_keys = set(schema.keys()) if isinstance(schema, dict) else set()

    def validate(result: dict) -> None:
        if not isinstance(result, dict):
            raise ValueError("模型输出必须是 JSON 对象")
        missing = sorted(required_keys - set(result.keys()))
        if missing:
            raise ValueError(f"模型输出缺少顶级字段：{', '.join(missing)}")

    return validate


def _call_trusted_skill_json(
    *,
    skill_name: str,
    payload: dict,
    api_key: str,
    model: str,
    base_url: str,
    max_tokens: int,
    timeout_seconds: float,
    max_attempts: int = 2,
    retry_timeouts: bool = True,
) -> dict:
    return _call_skill_with_gate(
        api_key=api_key,
        model=model,
        base_url=base_url,
        skill_name=skill_name,
        mode="trusted",
        task_payload=payload,
        output_contract=_trusted_payload_contract(payload),
        validator=_trusted_payload_validator(payload),
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        retry_timeouts=retry_timeouts,
    )


async def _call_trusted_skill_json_async(
    *,
    skill_name: str,
    payload: dict,
    api_key: str,
    model: str,
    base_url: str,
    max_tokens: int,
    timeout_seconds: float,
    max_attempts: int = 2,
    retry_timeouts: bool = True,
) -> dict:
    return await _call_skill_with_gate_async(
        api_key=api_key,
        model=model,
        base_url=base_url,
        skill_name=skill_name,
        mode="trusted",
        task_payload=payload,
        output_contract=_trusted_payload_contract(payload),
        validator=_trusted_payload_validator(payload),
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        retry_timeouts=retry_timeouts,
    )


def _build_orchestration_plan(job: CaseGenerationV2Job, payload: dict, markdown_text: str, image_links: list[str]) -> dict:
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
            "XMind 必须由后端根据 TestcasePackage 确定性展开，并由项目 exporter 转换后解析实际归档校验",
        ],
    }


async def _analyze_image_batch_async(
    *,
    api_key: str,
    model: str,
    base_url: str,
    batch: list[dict],
    max_attempts: int = 3,
) -> dict:
    """识别单批图片。

    返回 {"images": [...], "failed_batch": [...]}：
    - 成功时 failed_batch 为空；
    - 空响应/异常时自动重试 max_attempts 次；
    - 全部重试仍失败则降级：images 为空、failed_batch 记录该批图片与原因，
      由上层写入 pending_confirmations，任务继续而非整体失败。
    """
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "你现在处于 claw_5skill_unified/lite 的 【阶段 1：Image-First Scan】。\n"
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

    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            result = await _call_openai_json_async(
                api_key=api_key,
                model=model,
                base_url=base_url,
                system_prompt=(
                    "你正在执行 claw_5skill_unified/lite 的 requirement-analyzer 识图阶段。\n"
                    "必须输出合法 JSON，且每张成功下载的图片都要有识别结论；绝不能用链接或正文描述替代实际识图。"
                ),
                user_content=content,
                max_tokens=4200,
                timeout_seconds=_DEFAULT_CHAT_TIMEOUT_SECONDS,
            )
            images = result.get("images") or []
            if images:
                return {"images": images, "failed_batch": []}
            # 模型返回了合法 JSON 但 images 为空 —— 视为空响应，触发重试
            last_error = "模型未返回任何图片识别结果（images 为空）"
        except Exception as exc:
            last_error = str(exc)
            # 不可重试错误（如鉴权失败、模型不存在）直接停止重试，进入降级
            if _is_non_retryable_model_error(exc):
                break
        # 非最后一次尝试则继续重试
    # 降级：跳过该批，记录失败信息
    failed_batch = [
        {
            "image_id": item.get("image_id"),
            "url": item.get("url"),
            "reason": last_error or "图片识别返回空响应",
        }
        for item in batch
    ]
    return {"images": [], "failed_batch": failed_batch}


async def _analyze_images_async(api_key: str, model: str, base_url: str, downloaded_images: list[dict]) -> dict:
    """识别全部已下载图片，返回 {"images": [...], "skipped": [...]}。

    单批失败不再使整个任务失败：失败批次被跳过并记入 skipped，供上层写入
    pending_confirmations。仅当“所有”批次都失败时才判定识图阶段整体失败。
    """
    successful = [item for item in downloaded_images if item.get("download_status") == "success" and item.get("file_path")]
    if not successful:
        return {"images": [], "skipped": []}

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
    images: list[dict] = []
    skipped: list[dict] = []
    for result in batch_results:
        images.extend(result.get("images") or [])
        skipped.extend(result.get("failed_batch") or [])

    # 全部批次都失败才整体报错；否则部分成功即放行，缺失图片降级为待确认
    if not images and skipped:
        raise ValueError(f"图片识别全部失败：{skipped[0].get('reason') if skipped else '模型输出为空'}")

    observed_ids = {item.get("image_id") for item in images}
    skipped_ids = {entry.get("image_id") for entry in skipped}
    for item in successful:
        image_id = item.get("image_id")
        if image_id not in observed_ids and image_id not in skipped_ids:
            # 模型既没识别、批次也没标记失败（理论上少见）—— 同样降级为待确认
            skipped.append(
                {
                    "image_id": image_id,
                    "url": item.get("url"),
                    "reason": "图片识别结果缺失",
                }
            )
    return {"images": images, "skipped": skipped}


def _analyze_images(api_key: str, model: str, base_url: str, downloaded_images: list[dict]) -> dict:
    return asyncio.run(_analyze_images_async(api_key, model, base_url, downloaded_images))


def _build_requirement_analysis(
    *,
    job: CaseGenerationV2Job,
    db=None,
    markdown_text: str,
    downloaded_images: list[dict],
    image_analysis: list[dict],
    image_skip_notes: list[dict] | None = None,
    api_key: str,
    model: str,
    base_url: str | None = None,
    audit_log: list[dict] | None = None,
) -> dict:
    sections = _extract_sections(markdown_text)
    # 背景/概述类章节明确不参与分析/生成/审查，在源头剔除
    sections, dropped_background = _filter_out_background_sections(sections)
    if dropped_background and audit_log is not None:
        audit_log.append(
            {
                "skill": "requirement-analyzer",
                "attempt": "background-filter",
                "status": "passed",
                "dropped_background_sections": [s.get("title") for s in dropped_background],
            }
        )
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
        # 本批有正文的章节数：用于约束“每个章节至少各产出 1 个功能点”，避免丢章节
        batch_section_titles = [
            (sec.get("title") or "").strip()
            for sec in batch_sections
            if (sec.get("body") or "").strip()
        ]
        batch_section_count = len(batch_section_titles) or len(batch_sections)
        prompt = {
            "task": "按 claw_5skill_unified/lite 的 requirement-analyzer 规则，执行【阶段 2：Text Parse】、【阶段 3：Cross-Source Alignment】和【阶段 4：Function Point Synthesis】。仅分析本批章节，生成 EvidenceTrace 与 FunctionPoints。",
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
                "module 必须逐字复制功能点所属章节的标题原文（如『筛选栏优化』『新建阶段字段优化』），严禁改写、翻译成英文、概括或把多个章节合并成一个自创模块名。",
                "scene 必须使用功能点所属的更细一级章节标题；若该章节没有子章节，则 scene 复用 module 标题。",
                "禁止依据你对业务/产品的理解自创模块名（例如不得把『筛选栏优化』改成『Ad Manager 筛选器』）；模块名只能来自需求文档真实出现的章节标题。",
                f"本批共有 {batch_section_count} 个有正文的章节，必须为每一个章节至少提取 1 个功能点，禁止遗漏任何章节；同一章节可按需拆分多个功能点。",
                f"本批功能点总数不得少于章节数（≥{batch_section_count} 个）；若某章节确实无可测内容，必须在 pending_confirmations 中说明原因，而不是直接跳过。",
                "【章节内合并优先原则】同一章节内的多条规则，默认应合并进同一个 FP 的 rules 字段，而不是拆成多个 FP。"
                "仅在以下情况才允许拆分为独立 FP：(1) 不同操作入口或页面（如筛选栏 vs 新建页面）；"
                "(2) 互斥的开关状态且各自有完整独立流程（如按钮开/关各自触发不同保存逻辑）；"
                "(3) 不同业务对象且规则有实质差异（如 CPI 出价 vs ROI 出价的字段逻辑不同）。"
                "以下情况禁止拆分：同一字段在不同 Tab（Campaign/Ad Set/Ad Creative）下展示逻辑完全相同；"
                "同一操作的正常/边界/异常分支（这些属于测试维度，由 testcase-designer 处理，不应在此拆 FP）；"
                "纯枚举的改名映射列表（多个字段改名合并为 1 个 FP，rules 逐条列出每个映射）。",
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

    # —— 模块拆分确定性回填：把 module/scene 强制对齐到需求文档真实章节标题 ——
    section_lineage = _build_section_lineage(sections)
    realigned_count = _realign_function_point_modules(function_points, section_lineage)
    if audit_log is not None:
        audit_log.append(
            {
                "skill": "requirement-analyzer",
                "attempt": "module-realign",
                "status": "passed",
                "realigned_function_points": realigned_count,
                "total_function_points": len(function_points),
            }
        )

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
    # 识图降级：把被跳过的图片批次记入待确认，确保信息不丢失且任务可继续
    existing_pending_text = json.dumps(canonical_pending, ensure_ascii=False)
    for note in image_skip_notes or []:
        image_id = note.get("image_id") or ""
        url = note.get("url") or ""
        if (image_id and image_id in existing_pending_text) or (url and url in existing_pending_text):
            continue
        canonical_pending.append(
            {
                "pending_id": f"PENDING-IMG-{len(canonical_pending) + 1:03d}",
                "source": "image",
                "ref_id": image_id or url,
                "message": f"图片识别降级跳过（{note.get('reason') or '模型返回空响应'}），未参与功能点提取，请人工复核：{url or image_id}",
                "status": "pending",
            }
        )
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
            "task": "按 claw_5skill_unified/lite 的 testcase-designer 规则，仅基于本批 FunctionPoints 生成中文执行级测试用例。先判断测试设计方法是否适用，再生成可观察、非重复、与证据相关的用例。",
            "batch_label": batch_label,
            "function_points": compact_batch_fps,
            "pending_confirmations": compact_pending_confirmations,
            "constraints": [
                "只能覆盖本批 function_points 中的 fp_id，不要生成其他 fp_id。",
                "按测试设计方法库（等价类/边界值/决策表/状态转换/角色权限矩阵/多入口一致性/空值默认值/异常容错/时间时序）逐项判断适用性；适用时补充能体现该方法价值的用例，不适用时不要机械套用。",
                "若某功能点的 rules/description 中包含并列列举的多个独立子规则（例如三种占位图：图片出错/未上传/JS代码不支持预览；或多个字段改名映射：A→B、C→D；或多条互斥的保存逻辑分支），必须逐项判断覆盖方式；能合并则合并，不能合并则拆分，合并后的标题、步骤、预期必须看得出覆盖点。",
                "【跨模块同构禁令】若某功能点同时覆盖多个同构模块（如 Campaign/Ad Set/Ad Creative/Product），且各模块的操作步骤和预期结果完全相同、仅模块名不同，禁止为每个模块单独生成一条用例；应将多个模块合并为 1 条参数化用例（标题点明全部模块，test_data 枚举各模块入参），或选取 1 个代表性模块写主流程、其余模块用 1 条多入口一致性用例覆盖。仅当各模块存在实质性差异（不同字段、不同交互逻辑、不同权限）时，才允许分开生成。",
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
        seen_fp_title: set[tuple[str, str]] = set()
        seen_title_only: set[str] = set()
        unique: list[dict] = []
        for case in cases:
            fp_id = case.get("fp_id") or ""
            norm_title = re.sub(r"\s+", "", str(case.get("title") or ""))
            # 同一 FP 内完全相同标题去重
            fp_key = (fp_id, norm_title)
            if fp_key in seen_fp_title:
                continue
            seen_fp_title.add(fp_key)
            # 跨 FP 标题完全相同去重（捕获不同 FP 间的同质用例）
            if norm_title in seen_title_only:
                continue
            seen_title_only.add(norm_title)
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
        "task": "按 claw_5skill_unified/lite 的 quality-reviewer 规则审查 FunctionPoints、EvidenceTrace、TestcasePackage。",
        "function_points": function_points,
        "evidence_trace": evidence_trace,
        "testcase_package": testcase_package,
        "pending_confirmations": pending_confirmations,
        "constraints": [
            "覆盖率检查：每个 FunctionPoint 必须被用例覆盖、合并覆盖、阻塞或不适用说明；列出未消除缺口的 fp_id，存在未消除缺口时结论不得为 pass。",
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
    review_summary["testcase_count"] = len(cases)  # 强制用后端实际数，不信任模型自报
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
    job: CaseGenerationV2Job,
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
    job: CaseGenerationV2Job,
    function_points: dict,
    testcase_package: dict,
    review_report: dict,
) -> str:
    root = f"{_sanitize_file_stem(job.source_document_name or job.name)}测试用例"
    lines = [root]
    cases = [case for case in testcase_package.get("testcases", []) if isinstance(case, dict)]
    priority_counts = Counter(case.get("priority") or "P1" for case in cases)
    category_counts = Counter(_normalize_category(case.get("category")) for case in cases)
    trusted_summary = review_report.get("summary") or {}
    review_counts = review_report.get("priority_counts") or {}
    counts = {level: priority_counts.get(level, review_counts.get(level, 0)) for level in ("P0", "P1", "P2", "P3")}
    _append_node(lines, 0, "统计信息")
    if trusted_summary.get("source_count") is not None:
        _append_node(lines, 1, f"直接测试对象数：{trusted_summary.get('source_count', 0)}")
    _append_node(lines, 1, f"功能点总数：{trusted_summary.get('function_point_count', review_report.get('function_point_count', 0))}")
    _append_node(lines, 1, f"用例总数：{len(cases) or trusted_summary.get('testcase_count', review_report.get('case_count', 0))}")
    for level in ("P0", "P1", "P2", "P3"):
        _append_node(lines, 1, f"{level} 数量：{counts.get(level, 0)}")
    if review_report.get("image_link_count"):
        _append_node(lines, 1, f"图片链接数量：{review_report.get('image_link_count', 0)}")
        _append_node(lines, 1, f"图片下载成功数量：{review_report.get('image_download_success_count', 0)}")
        _append_node(lines, 1, f"图片下载失败数量：{review_report.get('image_download_failed_count', 0)}")
    _append_node(
        lines,
        1,
        f"审查结论：{review_report.get('review_conclusion') or trusted_summary.get('semantic_release_readiness') or trusted_summary.get('release_readiness') or '有条件通过'}",
    )
    pending_confirmations = review_report.get("pending_confirmations") or []
    _append_node(lines, 1, f"待确认项数量：{len(pending_confirmations)}")
    for pc in pending_confirmations:
        pc_id = pc.get("pending_id") or ""
        pc_msg = _short_text(pc.get("message") or "", 100)
        _append_node(lines, 2, f"{pc_id}：{pc_msg}" if pc_id else pc_msg)
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
        if not trusted_summary.get("source_count"):
            _append_node(lines, 1, f"证据覆盖率：{quality_summary.get('evidence_coverage_rate', 0):.0%}")
        _append_node(lines, 1, f"弱预期数量：{quality_summary.get('weak_expected_count', 0)}")
    elif trusted_summary:
        _append_node(lines, 1, f"Source 有用例率：{trusted_summary.get('source_with_testcase_rate', trusted_summary.get('source_coverage_rate', 0)):.0%}")
        _append_node(lines, 1, f"FP 回执完整率：{trusted_summary.get('function_point_receipt_rate', trusted_summary.get('function_point_consumption_rate', 0)):.0%}")
        _append_node(lines, 1, f"弱预期数量：{trusted_summary.get('weak_expected_count', 0)}")

    fp_by_id = {item.get("fp_id"): item for item in function_points.get("function_points", [])}
    cases_by_fp: dict[str, list[dict]] = {}
    for case in cases:
        fp_ids = case.get("fp_ids") if isinstance(case.get("fp_ids"), list) else []
        if not fp_ids and case.get("fp_id"):
            fp_ids = [case.get("fp_id")]
        for fp_id in [str(item).strip() for item in fp_ids if str(item).strip()] or ["UNMAPPED"]:
            cases_by_fp.setdefault(fp_id, []).append(case)

    trusted_mode = any(str(fp.get("source_id") or "").startswith("SRC-") for fp in function_points.get("function_points", []) if isinstance(fp, dict))
    if trusted_mode:
        ordered_fps = sorted(
            function_points.get("function_points", []),
            key=lambda item: (_trusted_source_order_key(item.get("source_order"), item.get("source_order_index", 0)), item.get("fp_id") or ""),
        )
        modules: dict[str, dict[str, dict[str, list[dict]]]] = {}
        for fp in ordered_fps:
            module = fp.get("module") or "默认模块"
            scene = fp.get("scene") or module
            source_node = fp.get("source_node_title") or fp.get("title_path") or fp.get("source_title") or fp.get("source_id") or "SRC-UNKNOWN"
            modules.setdefault(module, {}).setdefault(scene, {}).setdefault(source_node, []).append(fp)

        rendered_case_ids: set[str] = set()
        for module, scenes in modules.items():
            _append_node(lines, 0, f"模块：{module}")
            for scene, sources in scenes.items():
                _append_node(lines, 1, f"场景：{scene}")
                for source_node, source_fps in sources.items():
                    _append_node(lines, 2, source_node)
                    for fp in source_fps:
                        fp_id = fp.get("fp_id") or "FP-000"
                        fp_title = fp.get("title") or fp.get("name") or fp.get("description") or "功能点"
                        _append_node(lines, 3, f"{fp_id}：{fp_title}")
                        if fp.get("description"):
                            _append_node(lines, 4, f"说明：{_short_text(fp.get('description'), 120)}")
                        rules = fp.get("rules") or []
                        if rules:
                            _append_node(lines, 4, f"规则摘要：{_short_text('；'.join(str(item) for item in rules[:3]), 160)}")
                        for case in cases_by_fp.get(fp_id, []):
                            case_id = case.get("case_id") or "TC-000"
                            if case_id in rendered_case_ids:
                                _append_node(lines, 4, "合并覆盖：该功能点由同源已展开用例覆盖")
                                continue
                            rendered_case_ids.add(case_id)
                            category = _normalize_category(case.get("category"))
                            title = _short_text(case.get("title") or "测试用例", 90)
                            _append_node(lines, 4, f"{case_id}-{title}")
                            _append_node(lines, 5, f"优先级：{case.get('priority') or 'P1'}｜类型：{_category_label(category)}")
                            expected = case.get("expected_results") or []
                            expected_items = expected if isinstance(expected, list) else [expected]
                            if expected_items:
                                _append_node(lines, 5, f"预期摘要：{_short_text('；'.join(str(item) for item in expected_items[:2]), 160)}")
                            steps = case.get("steps") or []
                            if not isinstance(steps, list):
                                steps = [str(steps)]
                            if steps:
                                _append_node(lines, 5, "操作步骤")
                                for step_index, step in enumerate(steps[:6], start=1):
                                    _append_node(lines, 6, f"步骤{step_index}：{_short_text(_step_to_text(step), 120)}")
                            refs = _case_evidence_refs(case, fp)
                            if refs:
                                _append_node(lines, 5, "图片/证据：" + "，".join(refs))

        text = "\n".join(lines) + "\n"
        _validate_xmindmark(text)
        return text

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
    attempt_id = current_attempt_id()
    filters = [
        CaseGenerationV2Artifact.job_id == job_id,
        CaseGenerationV2Artifact.artifact_type == artifact_type,
    ]
    if attempt_id is not None:
        filters.append(CaseGenerationV2Artifact.attempt_id == attempt_id)
    artifact = db.scalar(
        select(CaseGenerationV2Artifact).where(*filters)
    )
    if artifact is None:
        artifact = CaseGenerationV2Artifact(
            job_id=job_id,
            attempt_id=attempt_id,
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
    artifact.expired_at = None


def _topic_id(seed: str) -> str:
    return str(uuid.uuid4())


def _xmind_topic(title: str, topic_id: str) -> dict:
    return {
        "id": topic_id,
        "class": "topic",
        "title": title,
        "structureClass": "org.xmind.ui.logic.right" if topic_id == "root" else None,
        "titleUnedited": True,
        "boundaries": [],
        "summaries": [],
    }


def _xmindmark_to_content(text: str) -> list[dict]:
    _validate_xmindmark(text)
    lines = text.splitlines()
    root = _xmind_topic(lines[0].strip(), str(uuid.uuid4()))
    root["structureClass"] = "org.xmind.ui.logic.right"
    stack: list[tuple[int, dict]] = [(-1, root)]
    counters: dict[int, int] = {}

    for line in lines[1:]:
        indent = len(line) - len(line.lstrip(" "))
        level = indent // 2
        title = line.lstrip()[2:].strip()
        counters[level] = counters.get(level, 0) + 1
        for stale_level in [key for key in counters if key > level]:
            counters.pop(stale_level, None)
        topic = _xmind_topic(title, _topic_id(f"l{level}_{counters[level]}_{title}"))
        topic.pop("structureClass", None)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1]
        parent.setdefault("children", {}).setdefault("attached", []).append(topic)
        stack.append((level, topic))

    if not root.get("children", {}).get("attached"):
        raise RuntimeError("XMind 内容生成失败：根节点没有子节点")
    return [
        {
            "id": str(uuid.uuid4()),
            "class": "sheet",
            "title": root["title"],
            "rootTopic": root,
            "topicPositioning": "fixed",
            "relationships": [],
            "theme": _default_xmind_theme(),
            "extensions": [
                {
                    "provider": "org.xmind.ui.skeleton.structure.style",
                    "content": {
                        "centralTopic": "org.xmind.ui.map.clockwise",
                        "mainTopic": "org.xmind.ui.logic.right",
                    },
                }
            ],
        }
    ]


def _default_xmind_theme() -> dict:
    return json.loads(
        """{"id":"f8c8e44f-4a4d-43a7-8381-11a152eaf8a3","centralTopic":{"id":"c5069014-b642-4cf5-bb50-1d29bd0df2a1","properties":{"svg:fill":"#000229","line-color":"#000229","shape-class":"org.xmind.topicShape.roundedRect","line-class":"org.xmind.branchConnection.curve","line-width":"3pt","line-pattern":"solid","fill-pattern":"solid","border-line-width":"0pt","arrow-end-class":"org.xmind.arrowShape.none","alignment-by-level":"inactived","fo:font-family":"NeverMind","fo:font-style":"normal","fo:font-weight":500,"fo:font-size":"30pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"center"}},"mainTopic":{"id":"70cef26a-bf8a-4a75-a3ba-c39b54a6401d","properties":{"shape-class":"org.xmind.topicShape.roundedRect","line-class":"org.xmind.branchConnection.roundedElbow","line-width":"2pt","fill-pattern":"solid","border-line-width":"0pt","fo:font-family":"NeverMind","fo:font-style":"normal","fo:font-weight":500,"fo:font-size":"18pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"left"}},"subTopic":{"id":"d5c7d9c0-e954-4c99-9e01-91cccd629c22","properties":{"shape-class":"org.xmind.topicShape.roundedRect","line-class":"org.xmind.branchConnection.roundedElbow","line-width":"2pt","fill-pattern":"solid","border-line-width":"0pt","fo:font-family":"NeverMind","fo:font-style":"normal","fo:font-weight":400,"fo:font-size":"14pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"left"}},"summaryTopic":{"id":"dc5d147f-2c2a-423f-8d4f-26c6e4cdc4ec","properties":{"svg:fill":"none","border-line-color":"#000229","shape-class":"org.xmind.topicShape.roundedRect","line-class":"org.xmind.branchConnection.roundedElbow","fill-pattern":"solid","fo:font-family":"NeverMind","fo:font-style":"normal","fo:font-weight":"400","fo:font-size":"14pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"left"}},"calloutTopic":{"id":"b2ccd2cb-e4d0-4c1d-8615-fea7a1b98854","properties":{"svg:fill":"#000229","border-line-color":"#000229","callout-shape-class":"org.xmind.calloutTopicShape.balloon.roundedRect","fill-pattern":"solid","fo:font-family":"NeverMind","fo:font-style":"normal","fo:font-weight":400,"fo:font-size":"14pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"left"}},"floatingTopic":{"id":"1db99452-2bb0-4de8-87f5-cdeb8a591d7b","properties":{"svg:fill":"#EEEBEE","border-line-color":"#EEEBEE","shape-class":"org.xmind.topicShape.roundedRect","line-class":"org.xmind.branchConnection.roundedElbow","line-width":"2pt","line-pattern":"solid","fill-pattern":"solid","border-line-width":"0pt","arrow-end-class":"org.xmind.arrowShape.none","fo:font-family":"NeverMind","fo:font-style":"normal","fo:font-weight":500,"fo:font-size":"14pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"left"}},"boundary":{"id":"beaff7ce-691f-481d-847c-c5f43d125660","properties":{"svg:fill":"#000229","line-color":"#000229","shape-class":"org.xmind.boundaryShape.roundedRect","shape-corner":"20pt","line-width":"2","line-pattern":"dash","fill-pattern":"solid","fo:font-family":"'NeverMind','Microsoft YaHei','PingFang SC','Microsoft JhengHei','sans-serif',sans-serif","fo:font-style":"normal","fo:font-weight":400,"fo:font-size":"14pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"center"}},"summary":{"id":"7e7d8704-9339-4a37-a8dc-f3a3aa2f4cf2","properties":{"line-color":"#000229","shape-class":"org.xmind.summaryShape.round","line-width":"2pt","line-pattern":"solid","line-corner":"8pt"}},"relationship":{"id":"81c8d0be-6082-4a1c-b88c-23b1445e0647","properties":{"line-color":"#000229","shape-class":"org.xmind.relationshipShape.curved","line-width":"2","line-pattern":"dash","arrow-begin-class":"org.xmind.arrowShape.none","arrow-end-class":"org.xmind.arrowShape.triangle","fo:font-family":"'NeverMind','Microsoft YaHei','PingFang SC','Microsoft JhengHei','sans-serif',sans-serif","fo:font-style":"normal","fo:font-weight":400,"fo:font-size":"13pt","fo:text-transform":"manual","fo:text-decoration":"none","fo:text-align":"center"}},"map":{"id":"ea5bbe08-7b7a-4b13-a4ee-49b20dcc4de2","properties":{"svg:fill":"#ffffff","multi-line-colors":"#F9423A #F6A04D #F3D321 #00BC7B #486AFF #4D49BE","color-list":"#000229 #1F2766 #52CC83 #4D86DB #99142F #245570","line-tapered":"none"}},"importantTopic":{"id":"6c4e5a0a-db82-4dc6-9816-213ad1a38238","properties":{"svg:fill":"#460400","fill-pattern":"solid","border-line-color":"#460400"}},"minorTopic":{"id":"febf0c47-d75e-4149-a07f-a44cf847e7ab","properties":{"svg:fill":"#703D00","fill-pattern":"solid","border-line-color":"#703D00"}},"colorThemeId":"Rainbow-#000229-MULTI_LINE_COLORS","expiredTopic":{"id":"c2afd293-7843-4ca4-b01f-4353768628ea","properties":{"fo:text-decoration":"line-through","svg:fill":"none"}},"global":{"id":"53109c3b-6577-4e2d-bd2e-b768723f6436","properties":{}},"skeletonThemeId":"db4a5df4db39a8cd1310ea55ea"}"""
    )


def _write_xmind_archive(xmind_path: str, xmindmark_text: str) -> str:
    return write_xmind_archive(xmind_path, xmindmark_text)


def _convert_xmindmark(output_dir: str, xmindmark_file_path: str, output_stem: str) -> str:
    _ensure_output_dir_writable(output_dir)
    output_stem = _sanitize_file_stem(output_stem, fallback="trusted_v2_testcases")
    return convert_xmindmark_to_xmind(output_dir, xmindmark_file_path, output_stem)


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
    covered_fp_ids: set[str] = set()
    fp_case_counts: Counter[str] = Counter()
    for case in cases:
        case_fp_ids = case.get("fp_ids") if isinstance(case.get("fp_ids"), list) else []
        if not case_fp_ids and case.get("fp_id"):
            case_fp_ids = [case.get("fp_id")]
        for fp_id in [str(item).strip() for item in case_fp_ids if str(item).strip()]:
            covered_fp_ids.add(fp_id)
            fp_case_counts[fp_id] += 1
    weak_expected_count = 0
    weak_step_count = 0
    template_title_count = 0
    evidence_case_count = 0
    concrete_image_evidence_case_count = 0
    assertion_basis_case_count = 0
    for case in cases:
        case_fp_ids = case.get("fp_ids") if isinstance(case.get("fp_ids"), list) else []
        fp = next((item for item in fps if item.get("fp_id") in (case_fp_ids or [case.get("fp_id")])), {})
        # Concise does not mean unverifiable. Only empty expectations or pure
        # boilerplate are deterministically weak; semantic review handles the
        # broader question of whether a concrete outcome is observable.
        if _is_empty_or_generic_only(case.get("expected_results"), _GENERIC_EXPECTATION_PATTERNS):
            weak_expected_count += 1
        if _is_empty_or_generic_only(case.get("steps"), _GENERIC_STEP_PATTERNS, formatter=_step_to_text):
            weak_step_count += 1
        if _text_contains_any(str(case.get("title") or ""), _GENERIC_CASE_TITLE_PATTERNS):
            template_title_count += 1
        if _case_evidence_refs(case, fp):
            evidence_case_count += 1
        if any(str(value or "").startswith("IMG-") for value in case.get("evidence_refs") or []):
            concrete_image_evidence_case_count += 1
        expected_results = {str(value).strip() for value in case.get("expected_results") or [] if str(value).strip()}
        based_results = {
            str(item.get("expected_result") or "").strip()
            for item in case.get("assertion_basis") or []
            if isinstance(item, dict) and str(item.get("expected_result") or "").strip()
        }
        if expected_results and expected_results.issubset(based_results):
            assertion_basis_case_count += 1
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
        "source_traceability_count": evidence_case_count,
        "source_traceability_rate": (evidence_case_count / len(cases)) if cases else 0,
        "concrete_image_evidence_case_count": concrete_image_evidence_case_count,
        "concrete_image_evidence_rate": (concrete_image_evidence_case_count / len(cases)) if cases else 0,
        "assertion_basis_case_count": assertion_basis_case_count,
        "assertion_basis_rate": (assertion_basis_case_count / len(cases)) if cases else 0,
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


def _reuse_original_generation_core() -> None:
    """Bind V2 common generation steps to the original generator implementation."""

    reusable_names = [
        "_extract_sections",
        "_filter_out_background_sections",
        "_compact_sections_for_ai",
        "_compact_downloaded_images_for_ai",
        "_compact_image_analysis_for_ai",
        "_build_requirement_section_batches",
        "_download_image_links",
        "_analyze_images",
        "_json_from_model_text",
        "_extract_complete_json_object",
        "_call_openai_json",
        "_build_orchestration_plan",
        "_build_requirement_analysis",
        "_build_testcase_package",
        "_build_review_report",
        "_dedupe_cases_global",
        "_renumber_cases_global",
    ]
    for name in reusable_names:
        globals()[name] = getattr(original_case_generation, name)


_reuse_original_generation_core()


_TRUSTED_COMPLEXITIES = {"simple", "medium", "complex"}
_TRUSTED_REQUIREMENT_RESULTS = {
    "converted_to_function_points",
    "blocked_by_pending_confirmation",
    "not_applicable",
    "merged",
}
_TRUSTED_TESTCASE_RESULTS = {
    "covered_by_case",
    "merged_into_case",
    "blocked_by_pending_confirmation",
    "not_applicable",
}


def _trusted_v2_source_ids(scope_index: dict) -> set[str]:
    return {
        str(item.get("source_id") or "").strip()
        for item in _trusted_scope_source_items(scope_index)
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    }


def _requirement_text_excerpt(value: str, *, limit: int = 6000) -> str:
    text = _HTML_COMMENT_PATTERN.sub("", str(value or ""))
    text = _MARKDOWN_IMAGE_PATTERN.sub("", text)
    text = _HTML_IMAGE_PATTERN.sub("", text)
    text = _HTML_TAG_PATTERN.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


_REQUIREMENT_QUOTE_CHAR_MAP = str.maketrans({
    "“": '"',
    "”": '"',
    "„": '"',
    "＂": '"',
    "‘": "'",
    "’": "'",
    "‚": "'",
    "＇": "'",
})


def _normalize_requirement_quote(value: str) -> str:
    text = str(value or "").translate(_REQUIREMENT_QUOTE_CHAR_MAP)
    text = re.sub(r"[*_~`]", "", text)
    return re.sub(r"\s+", "", text).strip()


def _requirement_state_marker_role(value: str) -> str | None:
    text = _HTML_COMMENT_PATTERN.sub("", str(value or ""))
    text = _HTML_TAG_PATTERN.sub("", text)
    text = re.sub(r"[*_~`]", "", text)
    if re.search(r"(?:更新|替换|修改|调整|优化)旧版(?:内容|文案|规则|效果)?", text):
        return "target"
    matches: list[tuple[int, str]] = []
    for marker in _CURRENT_STATE_MARKERS:
        position = text.find(marker)
        if position >= 0:
            matches.append((position, "current"))
    for marker in _TARGET_STATE_MARKERS:
        position = text.find(marker)
        if position >= 0:
            matches.append((position, "target"))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]


def _image_urls_in_text_order(value: str) -> list[str]:
    matches: list[tuple[int, str]] = []
    for match in _MARKDOWN_IMAGE_PATTERN.finditer(str(value or "")):
        matches.append((match.start(), match.group(1).strip()))
    for match in _HTML_IMAGE_PATTERN.finditer(str(value or "")):
        matches.append((match.start(), match.group(1).strip()))
    return [url for _, url in sorted(matches, key=lambda item: item[0])]


def _requirement_state_semantics(
    body: str,
    image_id_by_url: dict[str, str] | None = None,
    *,
    base_url: str | None = None,
) -> dict:
    image_id_by_url = image_id_by_url or {}
    active_role = "unspecified"
    detected_roles: set[str] = set()
    text_by_role: dict[str, list[str]] = {"current": [], "target": [], "unspecified": []}
    image_refs_by_role: dict[str, list[str]] = {"current": [], "target": [], "unspecified": []}
    image_role_by_id: dict[str, str] = {}

    for raw_line in str(body or "").splitlines():
        marker_role = _requirement_state_marker_role(raw_line)
        if marker_role:
            active_role = marker_role
            detected_roles.add(marker_role)
        for raw_url in _image_urls_in_text_order(raw_line):
            resolved_url = urljoin(base_url, raw_url) if base_url else raw_url
            image_id = image_id_by_url.get(resolved_url)
            if not image_id:
                continue
            image_role_by_id[image_id] = active_role
            image_refs_by_role[active_role].append(image_id)
        line_text = _requirement_text_excerpt(raw_line, limit=2000)
        if line_text:
            text_by_role[active_role].append(line_text)

    return {
        "has_state_transition": {"current", "target"}.issubset(detected_roles),
        "current_text": "\n".join(text_by_role["current"]).strip(),
        "target_text": "\n".join(text_by_role["target"]).strip(),
        "unspecified_text": "\n".join(text_by_role["unspecified"]).strip(),
        "current_image_refs": list(dict.fromkeys(image_refs_by_role["current"])),
        "target_image_refs": list(dict.fromkeys(image_refs_by_role["target"])),
        "unspecified_image_refs": list(dict.fromkeys(image_refs_by_role["unspecified"])),
        "image_role_by_id": image_role_by_id,
    }


def _is_state_label_only(value: str) -> bool:
    text = _normalize_requirement_quote(value)
    if not text:
        return True
    labels = {*_CURRENT_STATE_MARKERS, *_TARGET_STATE_MARKERS}
    return any(text.strip("：:+-（）()[]【】") == _normalize_requirement_quote(label) for label in labels)


def _source_evidence_role(source: dict, *, basis_type: str, basis_ref: str = "", source_quote: str = "") -> str:
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    if basis_type == "image":
        image_roles = semantics.get("image_role_by_id") if isinstance(semantics.get("image_role_by_id"), dict) else {}
        return str(image_roles.get(str(basis_ref or "").strip()) or "unspecified")
    if basis_type != "text":
        return "unspecified"
    quote = _normalize_requirement_quote(source_quote)
    if not quote or _is_state_label_only(source_quote):
        return "unspecified"
    current_text = _normalize_requirement_quote(semantics.get("current_text") or "")
    target_text = _normalize_requirement_quote(semantics.get("target_text") or "")
    in_current = bool(current_text and quote in current_text)
    in_target = bool(target_text and quote in target_text)
    if in_target and not in_current:
        return "target"
    if in_current and not in_target:
        return "current"
    return "unspecified"


def _current_state_basis_is_allowed(expected_result: str) -> bool:
    return bool(_CURRENT_STATE_NEGATION_PATTERN.search(str(expected_result or "")))


def _current_state_positive_expectation_is_retained(
    source: dict,
    expected_result: str,
    source_quote: str = "",
) -> bool:
    """Allow a current-state fact only when the target changes another explicit branch."""
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    if not semantics.get("has_state_transition"):
        return False
    expected = _normalize_requirement_quote(expected_result)
    quote = _normalize_requirement_quote(source_quote)
    current = _normalize_requirement_quote(_source_state_evidence_text(source, "current"))
    target = _normalize_requirement_quote(_source_state_evidence_text(source, "target"))
    expected_is_partial = any(marker in expected for marker in ("非全选", "未全选", "部分选择"))
    current_covers_both = any(marker in quote or marker in current for marker in ("无论是否全选", "不论是否全选"))
    target_changes_full_only = "全选时" in target and not any(marker in target for marker in ("非全选", "未全选", "部分选择"))
    return expected_is_partial and current_covers_both and target_changes_full_only


def _current_state_expectation_is_allowed(source: dict, expected_result: str, source_quote: str = "") -> bool:
    return _current_state_basis_is_allowed(expected_result) or _current_state_positive_expectation_is_retained(
        source,
        expected_result,
        source_quote,
    )


def _state_attribute_values(value: str) -> dict[str, set[str]]:
    text = str(value or "")
    result: dict[str, set[str]] = defaultdict(set)
    for attribute, patterns in _STATE_ATTRIBUTE_PATTERNS.items():
        for normalized_value, pattern in patterns:
            if pattern.search(text):
                result[attribute].add(normalized_value)
    return dict(result)


def _source_state_evidence_text(source: dict, role: str) -> str:
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    parts = [str(semantics.get(f"{role}_text") or "")]
    for evidence in source.get("image_evidence") or []:
        if not isinstance(evidence, dict) or str(evidence.get("evidence_role") or "") != role:
            continue
        parts.append(str(evidence.get("summary") or ""))
        parts.extend(str(value or "") for value in evidence.get("requirement_hints") or [])
    return "\n".join(part for part in parts if part)


def _state_target_conflicts(source: dict, candidate_text: str) -> list[dict]:
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    if not semantics.get("has_state_transition"):
        return []
    current_values = _state_attribute_values(_source_state_evidence_text(source, "current"))
    target_values = _state_attribute_values(_source_state_evidence_text(source, "target"))
    candidate_values = _state_attribute_values(candidate_text)
    conflicts: list[dict] = []
    for attribute, current_set in current_values.items():
        target_set = target_values.get(attribute) or set()
        claimed_set = candidate_values.get(attribute) or set()
        if not target_set or not claimed_set:
            continue
        obsolete = current_set - target_set
        wrong_values = sorted(claimed_set & obsolete)
        if wrong_values and not claimed_set.intersection(target_set):
            conflicts.append({
                "attribute": attribute,
                "current_values": sorted(current_set),
                "target_values": sorted(target_set),
                "claimed_values": wrong_values,
            })
    return conflicts


def _resolve_requirement_source_quote(source_excerpt: str, quote: str) -> str:
    """Return the exact source spelling for an equivalent model quote."""
    source_text = str(source_excerpt or "")
    normalized_quote = _normalize_requirement_quote(quote)
    if not source_text or not normalized_quote:
        return str(quote or "").strip()

    normalized_chars: list[str] = []
    source_positions: list[int] = []
    for index, char in enumerate(source_text):
        if char in "*_~`" or char.isspace():
            continue
        normalized_chars.append(char.translate(_REQUIREMENT_QUOTE_CHAR_MAP))
        source_positions.append(index)
    normalized_source = "".join(normalized_chars)
    start = normalized_source.find(normalized_quote)
    if start < 0:
        return str(quote or "").strip()
    end = start + len(normalized_quote) - 1
    return source_text[source_positions[start] : source_positions[end] + 1].strip()


def _section_evidence_catalog(
    markdown_text: str,
    image_links: list[str],
    image_analysis: list[dict] | None = None,
    *,
    base_url: str | None = None,
) -> list[dict]:
    image_id_by_url = {url: f"IMG-{index:03d}" for index, url in enumerate(image_links, start=1)}
    analysis_by_id = {
        str(item.get("image_id") or "").strip(): item
        for item in image_analysis or []
        if isinstance(item, dict) and str(item.get("image_id") or "").strip()
    }
    ancestors: list[dict] = []
    catalog: list[dict] = []
    for index, section in enumerate(_extract_sections(markdown_text), start=1):
        level = int(section.get("level") or 1)
        title = _clean_heading_text(section.get("title")) or f"章节 {index}"
        while ancestors and int(ancestors[-1]["level"]) >= level:
            ancestors.pop()
        title_path = "/".join([item["title"] for item in ancestors] + [title])
        body = str(section.get("body") or "")
        raw_urls = _image_urls_in_text_order(body)
        resolved_urls = [urljoin(base_url, url) if base_url else url for url in raw_urls]
        image_refs = [image_id_by_url[url] for url in resolved_urls if url in image_id_by_url]
        state_semantics = _requirement_state_semantics(
            body,
            image_id_by_url,
            base_url=base_url,
        )
        image_role_by_id = state_semantics.get("image_role_by_id") or {}
        image_evidence = []
        for image_id in image_refs:
            analysis = analysis_by_id.get(image_id) or {}
            image_evidence.append(
                {
                    "image_id": image_id,
                    "evidence_role": image_role_by_id.get(image_id) or "unspecified",
                    "summary": str(analysis.get("summary") or "").strip(),
                    "requirement_hints": analysis.get("requirement_hints") if isinstance(analysis.get("requirement_hints"), list) else [],
                    "risk_or_unclear": analysis.get("risk_or_unclear") if isinstance(analysis.get("risk_or_unclear"), list) else [],
                }
            )
        excerpt = _requirement_text_excerpt(body)
        catalog.append(
            {
                "doc_source_id": f"DOC-{index:03d}",
                "source_order": index,
                "title": title,
                "title_path": title_path,
                "level": level,
                "source_excerpt": excerpt,
                "content_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                "image_refs": list(dict.fromkeys(image_refs)),
                "image_evidence": image_evidence,
                "source_state_semantics": state_semantics,
            }
        )
        ancestors.append({"level": level, "title": title})
    return catalog


def _scope_evidence_match(source: dict, catalog: list[dict]) -> dict | None:
    source_path = _normalize_title_key(source.get("title_path"))
    source_title = _normalize_title_key(source.get("title") or source.get("scene"))
    ranked: list[tuple[int, int, dict]] = []
    for item in catalog:
        item_path = _normalize_title_key(item.get("title_path"))
        item_title = _normalize_title_key(item.get("title"))
        score = 0
        if source_path and item_path and source_path == item_path:
            score = 100
        elif source_path and item_path and (source_path.endswith(item_path) or item_path.endswith(source_path)):
            score = 80
        elif source_title and item_title and source_title == item_title:
            score = 60
        if score:
            ranked.append((score, -int(item.get("source_order") or 0), item))
    if not ranked:
        return None
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return ranked[0][2]


def _attach_scope_evidence(
    scope_index: dict,
    markdown_text: str,
    image_links: list[str],
    image_analysis: list[dict],
    *,
    base_url: str | None = None,
) -> dict:
    catalog = _section_evidence_catalog(
        markdown_text,
        image_links,
        image_analysis,
        base_url=base_url,
    )
    attached = json.loads(json.dumps(scope_index, ensure_ascii=False))
    evidence_by_source: dict[str, dict] = {}
    for block in attached.get("source_blocks") or []:
        if not isinstance(block, dict):
            continue
        source_id = str(block.get("block_id") or block.get("source_id") or "").strip()
        evidence = _scope_evidence_match(block, catalog)
        if not source_id or not evidence:
            continue
        payload = {
            "source_doc_id": evidence["doc_source_id"],
            "source_excerpt": evidence["source_excerpt"],
            "source_content_sha256": evidence["content_sha256"],
            "image_refs": evidence["image_refs"],
            "image_evidence": evidence["image_evidence"],
            "source_state_semantics": evidence["source_state_semantics"],
            "evidence_refs": [evidence["doc_source_id"], *evidence["image_refs"]],
        }
        block.update(payload)
        evidence_by_source[source_id] = payload
    for shard in attached.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        source_id = str(shard.get("direct_testcase_source") or shard.get("source_id") or "").strip()
        if source_id in evidence_by_source:
            shard.update(evidence_by_source[source_id])
    for source in attached.get("direct_testcase_sources") or []:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "").strip()
        if source_id in evidence_by_source:
            source.update(evidence_by_source[source_id])
    attached["section_evidence_catalog"] = catalog
    attached["generation_contract_version"] = _TRUSTED_GENERATION_CONTRACT_VERSION
    return attached


def _trusted_scope_fingerprint(scope_index: dict) -> str:
    payload = []
    for source in _trusted_scope_source_items(scope_index):
        profile = source.get("test_design_profile") if isinstance(source.get("test_design_profile"), dict) else {}
        payload.append(
            {
                "source_id": source.get("source_id"),
                "title_path": source.get("title_path"),
                "source_content_sha256": source.get("source_content_sha256"),
                "applicable_methods": profile.get("applicable_methods") or [],
                "must_cover": profile.get("must_cover") or [],
            }
        )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _unified_rules_sha256() -> str | None:
    root = _resolve_unified_rules_dir()
    if not root.exists():
        return None
    digest = hashlib.sha256()
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and "outputs" not in path.parts
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
    ]
    for path in sorted(files, key=lambda value: str(value.relative_to(root))):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _can_reuse_trusted_scope_index(
    previous_scope_index: dict | None,
    previous_source_manifest: dict | None,
    current_source_manifest: dict,
    previous_scope_gate: dict | None,
) -> bool:
    return bool(
        previous_scope_index
        and previous_scope_index.get("generation_contract_version") == _TRUSTED_GENERATION_CONTRACT_VERSION
        and previous_source_manifest
        and previous_source_manifest.get("content_sha256") == current_source_manifest.get("content_sha256")
        and previous_source_manifest.get("unified_rules_sha256") == current_source_manifest.get("unified_rules_sha256")
        and (previous_scope_gate or {}).get("passed")
    )


def _can_reuse_trusted_requirement(
    previous_requirement_handoff: dict | None,
    scope_index: dict,
    previous_requirement_gate: dict | None,
) -> bool:
    return bool(
        previous_requirement_handoff
        and previous_requirement_handoff.get("generation_contract_version") == _TRUSTED_GENERATION_CONTRACT_VERSION
        and previous_requirement_handoff.get("scope_fingerprint") == _trusted_scope_fingerprint(scope_index)
        and (previous_requirement_gate or {}).get("passed")
    )


def _build_trusted_source_manifest(
    markdown_text: str,
    image_links: list[str],
    *,
    source_url: str | None = None,
    model: str | None = None,
) -> dict:
    sections = _section_evidence_catalog(
        markdown_text,
        image_links,
        base_url=source_url,
    )
    sources = []
    for index, section in enumerate(sections, start=1):
        title = str(section.get("title") or f"章节 {index}").strip()
        body = str(section.get("source_excerpt") or "").strip()
        sources.append(
            {
                "source_id": f"DOC-{index:03d}",
                "source_order": index,
                "title": title,
                "title_path": section.get("title_path") or title,
                "classification": "candidate_source",
                "scope_status": "pending_scope_index",
                "text_length": len(body),
                "text_excerpt": body,
                "content_sha256": section.get("content_sha256"),
                "image_refs": section.get("image_refs") or [],
                "source_state_semantics": section.get("source_state_semantics") or {},
            }
        )
    return {
        "manifest_version": "trusted-source-v2",
        "run_id": current_run_id(),
        "attempt_id": current_attempt_id(),
        "captured_at": utc_now_naive().isoformat(),
        "source_url": source_url,
        "content_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        "content_bytes": len(markdown_text.encode("utf-8")),
        "parser_version": "markdown-sections-v2",
        "model": model,
        "unified_rules_sha256": _unified_rules_sha256(),
        "source_count": len(sources),
        "image_link_count": len(image_links),
        "sources": sources,
        "image_links": [{"image_id": f"IMG-{index:03d}", "url": url} for index, url in enumerate(image_links, start=1)],
    }


def _build_trusted_evidence_artifact(
    markdown_text: str,
    image_links: list[str],
    downloaded_images: list[dict],
    image_analysis: list[dict],
    *,
    base_url: str | None = None,
) -> dict:
    analyzed_ids = {
        str(item.get("image_id") or "").strip()
        for item in image_analysis
        if isinstance(item, dict) and str(item.get("image_id") or "").strip()
    }
    images: list[dict] = []
    failed_images: list[dict] = []
    pending_confirmations = []
    for raw_item in downloaded_images:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        image_id = str(item.get("image_id") or "").strip() or "IMG-UNKNOWN"
        download_status = str(item.get("download_status") or "").strip()
        item["download_tool"] = item.get("download_tool") or "httpx"
        item["vision_tool"] = item.get("vision_tool") or "model_vision"
        if download_status == "success" and image_id in analyzed_ids:
            item["vision_status"] = "success"
        elif download_status == "success":
            item["vision_status"] = "failed"
            item["failure_reason"] = item.get("failure_reason") or "图片已下载但未产生视觉识别结果"
            failed_images.append(item)
            pending_confirmations.append(
                {
                    "pending_id": f"PENDING-{image_id}",
                    "source": "image",
                    "ref_id": image_id,
                    "message": "图片已下载但视觉识别失败，无法作为确定证据，需要人工确认",
                    "status": "pending",
                }
            )
        else:
            item["vision_status"] = "skipped"
            item["failure_reason"] = item.get("failure_reason") or "图片下载失败"
            failed_images.append(item)
            pending_confirmations.append(
                {
                    "pending_id": f"PENDING-{image_id}",
                    "source": "image",
                    "ref_id": image_id,
                    "message": "图片下载失败，无法作为确定证据，需要人工确认",
                    "status": "pending",
                }
            )
        images.append(item)
    return {
        "evidence_version": "trusted-evidence-minimal-v1",
        "section_count": len(_extract_sections(markdown_text)),
        "image_link_count": len(image_links),
        "download_success_count": sum(1 for item in downloaded_images if item.get("download_status") == "success"),
        "download_failed_count": sum(1 for item in images if item.get("download_status") != "success"),
        "vision_success_count": len(analyzed_ids),
        "vision_failed_count": len([item for item in images if item.get("vision_status") == "failed"]),
        "section_evidence": _section_evidence_catalog(
            markdown_text,
            image_links,
            image_analysis,
            base_url=base_url,
        ),
        "images": images,
        "image_analysis": image_analysis,
        "failed_images": failed_images,
        "pending_confirmations": pending_confirmations,
    }


def _validate_trusted_evidence_trace(evidence_trace: dict) -> dict:
    issues: list[dict] = []
    images = evidence_trace.get("images") if isinstance(evidence_trace, dict) else None
    failed_images = evidence_trace.get("failed_images") if isinstance(evidence_trace, dict) else None
    pending_confirmations = evidence_trace.get("pending_confirmations") if isinstance(evidence_trace, dict) else None
    section_evidence_value = evidence_trace.get("section_evidence") if isinstance(evidence_trace, dict) else None
    section_evidence_present = section_evidence_value is not None
    section_evidence = section_evidence_value
    if not isinstance(images, list):
        issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGES_BAD_TYPE", "message": "EvidenceTrace.images 必须是数组"})
        images = []
    if not isinstance(failed_images, list):
        issues.append({"severity": "blocker", "code": "EVIDENCE_FAILED_IMAGES_BAD_TYPE", "message": "EvidenceTrace.failed_images 必须是数组"})
        failed_images = []
    if not isinstance(pending_confirmations, list):
        issues.append({"severity": "blocker", "code": "EVIDENCE_PENDING_BAD_TYPE", "message": "EvidenceTrace.pending_confirmations 必须是数组"})
        pending_confirmations = []
    if section_evidence is None:
        section_evidence = []
    elif not isinstance(section_evidence, list):
        issues.append({"severity": "blocker", "code": "EVIDENCE_SECTION_BINDINGS_BAD_TYPE", "message": "EvidenceTrace.section_evidence 必须是数组"})
        section_evidence = []
    image_link_count = int(evidence_trace.get("image_link_count") or 0) if isinstance(evidence_trace, dict) else 0
    if image_link_count != len(images):
        issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGE_COUNT_MISMATCH", "message": f"图片链接数 {image_link_count} 与 EvidenceTrace.images 数 {len(images)} 不一致"})
    pending_text = json.dumps(pending_confirmations, ensure_ascii=False)
    failed_ids = {
        str(item.get("image_id") or "").strip()
        for item in failed_images
        if isinstance(item, dict) and str(item.get("image_id") or "").strip()
    }
    known_image_ids = {
        str(item.get("image_id") or "").strip()
        for item in images
        if isinstance(item, dict) and str(item.get("image_id") or "").strip()
    }
    bound_image_ids: set[str] = set()
    for section in section_evidence:
        if not isinstance(section, dict):
            issues.append({"severity": "blocker", "code": "EVIDENCE_SECTION_BAD_ITEM", "message": "section_evidence 包含非对象项"})
            continue
        for image_id in section.get("image_refs") or []:
            image_id_text = str(image_id or "").strip()
            if image_id_text not in known_image_ids:
                issues.append({"severity": "blocker", "code": "EVIDENCE_SECTION_UNKNOWN_IMAGE", "message": f"{section.get('doc_source_id') or '章节'} 引用了未知图片 {image_id_text}"})
            elif image_id_text:
                bound_image_ids.add(image_id_text)
    if section_evidence_present:
        for image_id in sorted(known_image_ids - bound_image_ids):
            issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGE_WITHOUT_SECTION", "message": f"{image_id} 未绑定到需求章节"})
    for item in images:
        if not isinstance(item, dict):
            issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGE_BAD_ITEM", "message": "EvidenceTrace.images 包含非对象项"})
            continue
        image_id = str(item.get("image_id") or "").strip()
        download_status = str(item.get("download_status") or "").strip()
        vision_status = str(item.get("vision_status") or "").strip()
        if not image_id:
            issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGE_MISSING_ID", "message": "图片记录缺少 image_id"})
        if not item.get("download_tool"):
            issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGE_MISSING_DOWNLOAD_TOOL", "message": f"{image_id or '图片'} 缺少 download_tool"})
        if not item.get("vision_tool"):
            issues.append({"severity": "blocker", "code": "EVIDENCE_IMAGE_MISSING_VISION_TOOL", "message": f"{image_id or '图片'} 缺少 vision_tool"})
        if download_status not in {"success", "failed"}:
            issues.append({"severity": "blocker", "code": "EVIDENCE_BAD_DOWNLOAD_STATUS", "message": f"{image_id} download_status 非法：{download_status or '空'}"})
        if vision_status not in {"success", "failed", "skipped"}:
            issues.append({"severity": "blocker", "code": "EVIDENCE_BAD_VISION_STATUS", "message": f"{image_id} vision_status 非法：{vision_status or '空'}"})
        if download_status == "success" and vision_status == "skipped":
            issues.append({"severity": "blocker", "code": "EVIDENCE_SUCCESS_DOWNLOAD_SKIPPED_VISION", "message": f"{image_id} 下载成功但识图状态为 skipped"})
        if vision_status in {"failed", "skipped"}:
            if image_id and image_id not in failed_ids:
                issues.append({"severity": "blocker", "code": "EVIDENCE_FAILED_IMAGE_NOT_LISTED", "message": f"{image_id} 识图/下载失败但未进入 failed_images"})
            if image_id and image_id not in pending_text:
                issues.append({"severity": "blocker", "code": "EVIDENCE_FAILED_IMAGE_NOT_PENDING", "message": f"{image_id} 识图/下载失败但未进入待确认"})
    return {
        "gate": "evidence_trace_gate",
        "passed": not any(item["severity"] == "blocker" for item in issues),
        "issues": issues,
        "image_count": len(images),
        "failed_image_count": len(failed_images),
        "pending_confirmation_count": len(pending_confirmations),
    }


def _merge_evidence_risks_into_scope_index(scope_index: dict, evidence_trace: dict) -> dict:
    pending = [item for item in evidence_trace.get("pending_confirmations") or [] if isinstance(item, dict)]
    if not pending:
        return scope_index
    merged = dict(scope_index)
    risks = [item for item in merged.get("index_risks") or [] if isinstance(item, dict)]
    existing_keys = {
        (str(item.get("code") or ""), str(item.get("ref_id") or ""))
        for item in risks
    }
    for item in pending:
        risk = {
            "severity": "medium",
            "code": "IMAGE_EVIDENCE_PENDING",
            "ref_id": item.get("ref_id"),
            "message": item.get("message") or "图片证据未完成识别，需要人工确认",
        }
        key = (risk["code"], str(risk.get("ref_id") or ""))
        if key not in existing_keys:
            risks.append(risk)
            existing_keys.add(key)
    merged["index_risks"] = risks
    return merged


def _scope_index_should_use_section_batches(sections: list[dict]) -> bool:
    return bool(_choose_scope_index_strategy(sections)["uses_batches"])


def _scope_index_document_stats(sections: list[dict]) -> dict:
    valid_sections = [item for item in sections if isinstance(item, dict)]
    section_sizes = [
        len(str(item.get("body") or "")) + len(str(item.get("title") or ""))
        for item in valid_sections
    ]
    total_text = sum(section_sizes)
    return {
        "section_count": len(valid_sections),
        "text_size": total_text,
        "max_section_size": max(section_sizes, default=0),
        "average_section_size": round(total_text / len(valid_sections), 1) if valid_sections else 0,
        "estimated_input_tokens": max(1, int(total_text / 1.8)) if total_text else 0,
        "heading_density_per_10k": round(len(valid_sections) * 10000 / max(total_text, 1), 2),
    }


def _build_scope_index_section_batches(sections: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_size = 0
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_size = len(str(section.get("title") or "")) + len(str(section.get("body") or ""))
        if current and (
            len(current) >= _SCOPE_INDEX_BATCH_MAX_SECTIONS
            or current_size + section_size > _SCOPE_INDEX_BATCH_TEXT_LIMIT
        ):
            batches.append(current)
            current = []
            current_size = 0
        current.append(section)
        current_size += section_size
    if current:
        batches.append(current)
    return batches


def _choose_scope_index_strategy(sections: list[dict]) -> dict:
    stats = _scope_index_document_stats(sections)
    use_batches = bool(
        stats["text_size"] > max(_SCOPE_INDEX_BATCH_TRIGGER_TEXT, 24000)
        or stats["max_section_size"] > 12000
        or (stats["section_count"] > 24 and stats["text_size"] > 12000)
        or stats["estimated_input_tokens"] > 18000
    )
    batches = _build_scope_index_section_batches(sections) if use_batches else [sections]
    use_lightweight = bool(
        use_batches
        and (
            stats["text_size"] > _SCOPE_INDEX_TWO_PHASE_TRIGGER_TEXT
            or stats["estimated_input_tokens"] > 30000
            or (stats["section_count"] > max(_SCOPE_INDEX_TWO_PHASE_TRIGGER_SECTIONS, 32) and stats["text_size"] > 24000)
        )
    )
    mode = "single_full"
    if use_batches:
        mode = "section_batches_lightweight" if use_lightweight else "section_batches_full"
    return {
        **stats,
        "mode": mode,
        "uses_batches": use_batches,
        "uses_lightweight_discovery": use_lightweight,
        "batch_count": len(batches),
        "batch_max_sections": _SCOPE_INDEX_BATCH_MAX_SECTIONS,
        "batch_text_limit": _SCOPE_INDEX_BATCH_TEXT_LIMIT,
        "concurrency": min(_SCOPE_INDEX_CONCURRENCY, max(len(batches), 1)) if use_batches else 1,
    }


def _replace_trusted_scope_refs(value, old_to_new: dict[str, str]):
    if isinstance(value, str):
        return old_to_new.get(value, value)
    if isinstance(value, list):
        return [_replace_trusted_scope_refs(item, old_to_new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_trusted_scope_refs(item, old_to_new) for key, item in value.items()}
    return value


def _flatten_scope_object_items(value) -> tuple[list[dict], int, bool]:
    objects: list[dict] = []
    invalid_count = 0
    nested = False

    def _visit(item, depth: int) -> None:
        nonlocal invalid_count, nested
        if isinstance(item, dict):
            objects.append(item)
            return
        if isinstance(item, list):
            if depth > 0:
                nested = True
            for child in item:
                _visit(child, depth + 1)
            return
        if item not in (None, ""):
            invalid_count += 1

    _visit(value, 0)
    return objects, invalid_count, nested


def _default_scope_shard_for_block(block: dict, index: int) -> dict:
    source_id = str(block.get("block_id") or block.get("source_id") or f"SRC-{index:03d}").strip()
    title_path = str(block.get("title_path") or block.get("title") or source_id).strip()
    return {
        "shard_id": f"SHARD-{index:03d}",
        "direct_testcase_source": source_id,
        "source_order": block.get("source_order", index),
        "title_path": title_path,
        "module": block.get("module") or block.get("title") or title_path,
        "scene": block.get("scene") or block.get("title") or title_path,
        "xmind_source_node": block.get("xmind_source_node") or f"{source_id}｜{title_path}",
        "assigned_primary_sources": [source_id],
        "assigned_dependency_sources": [],
        "rule_clusters": [],
        "smoke_test_scope_note": "",
        "risk_signals": [],
        "complexity_score": 3,
        "test_design_profile": _default_test_design_profile(block),
    }


def _merge_trusted_scope_index_batches(batch_indexes: list[dict], *, reason: str, strategy: dict | None = None) -> dict:
    merged = {
        "version": "trusted-skill-v2",
        "source_blocks": [],
        "scope_classification": [],
        "shards": [],
        "dependency_bindings": [],
        "coverage_check": {
            "all_source_blocks_classified": True,
            "all_direct_sources_have_shards": True,
            "all_dependency_sources_bound": True,
            "unassigned_sources": [],
            "index_warnings": [],
            "index_risks": [],
        },
        "expected_source_list": [],
        "index_risks": [],
    }
    source_counter = 0
    shard_counter = 0
    for batch_number, scope_index in enumerate(batch_indexes, start=1):
        old_to_new: dict[str, str] = {}
        for block in scope_index.get("source_blocks") or []:
            if not isinstance(block, dict):
                continue
            source_counter += 1
            old_id = str(block.get("block_id") or block.get("source_id") or f"SRC-{source_counter:03d}").strip()
            new_id = f"SRC-{source_counter:03d}"
            old_to_new[old_id] = new_id
            normalized_block = dict(block)
            title_path = str(normalized_block.get("title_path") or normalized_block.get("title") or new_id).strip()
            normalized_block["block_id"] = new_id
            normalized_block["xmind_source_node"] = f"{new_id}｜{title_path}"
            merged["source_blocks"].append(normalized_block)
            merged["expected_source_list"].append(new_id)
        for shard in scope_index.get("shards") or []:
            if not isinstance(shard, dict):
                continue
            shard_counter += 1
            normalized_shard = _replace_trusted_scope_refs(dict(shard), old_to_new)
            source_id = str(normalized_shard.get("direct_testcase_source") or normalized_shard.get("source_id") or "").strip()
            title_path = str(normalized_shard.get("title_path") or source_id or f"SHARD-{shard_counter:03d}").strip()
            normalized_shard["shard_id"] = f"SHARD-{shard_counter:03d}"
            if source_id:
                normalized_shard["direct_testcase_source"] = source_id
                normalized_shard["xmind_source_node"] = f"{source_id}｜{title_path}"
            merged["shards"].append(normalized_shard)
        for item in scope_index.get("scope_classification") or []:
            if isinstance(item, dict):
                merged["scope_classification"].append(_replace_trusted_scope_refs(dict(item), old_to_new))
        for item in scope_index.get("dependency_bindings") or []:
            if isinstance(item, dict):
                merged["dependency_bindings"].append(_replace_trusted_scope_refs(dict(item), old_to_new))
        for item in scope_index.get("index_risks") or []:
            if isinstance(item, dict):
                risk = _replace_trusted_scope_refs(dict(item), old_to_new)
                risk.setdefault("batch", batch_number)
                merged["index_risks"].append(risk)
        for item in scope_index.get("normalization_notes") or []:
            if isinstance(item, dict):
                note = _replace_trusted_scope_refs(dict(item), old_to_new)
                if strategy and strategy.get("uses_lightweight_discovery") and note.get("code") == "MISSING_SHARDS_REBUILT":
                    note["severity"] = "info"
                note.setdefault("batch", batch_number)
                merged.setdefault("normalization_notes", []).append(note)
    normalized = _normalize_trusted_scope_index(merged)
    notes = []
    for item in merged.get("normalization_notes") or []:
        if isinstance(item, dict):
            notes.append(item)
    if isinstance(normalized.get("normalization_notes"), list):
        notes.extend(item for item in normalized["normalization_notes"] if isinstance(item, dict))
    notes.append(
        {
            "severity": "info",
            "code": "SCOPE_INDEX_SECTION_BATCH_USED",
            "message": f"scope_index 使用章节分批生成后合并：{reason}",
        }
    )
    if strategy and strategy.get("uses_lightweight_discovery"):
        notes.append(
            {
                "severity": "info",
                "code": "SCOPE_INDEX_LIGHTWEIGHT_DISCOVERY_USED",
                "message": "长文档范围索引使用轻量 source 识别，并由后端补齐 shard/profile 结构",
            }
        )
    normalized["normalization_notes"] = notes
    if strategy:
        normalized["execution_strategy"] = strategy
    return normalized


def _normalize_trusted_scope_index(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("scope_index 模型输出必须是 JSON 对象")
    raw_blocks = raw.get("source_blocks") if isinstance(raw.get("source_blocks"), list) else []
    raw_shards, invalid_shard_count, nested_shards = _flatten_scope_object_items(raw.get("shards"))
    legacy_sources = raw.get("direct_testcase_sources") if isinstance(raw.get("direct_testcase_sources"), list) else []
    if not raw_blocks and not legacy_sources:
        raise ValueError("scope_index 缺少 source_blocks/shards")
    normalization_notes: list[dict] = []
    if nested_shards:
        normalization_notes.append({
            "severity": "warning",
            "code": "SHARDS_NESTED_LIST_FLATTENED",
            "message": "模型将 shards 输出为嵌套数组，后端已展开为对象数组",
        })
    if invalid_shard_count:
        normalization_notes.append({
            "severity": "warning",
            "code": "SHARDS_INVALID_ITEMS_IGNORED",
            "message": f"shards 中 {invalid_shard_count} 个非对象项已忽略",
        })
    if not raw_blocks:
        raw_blocks = []
        raw_shards = []
        for index, item in enumerate(legacy_sources, start=1):
            if not isinstance(item, dict):
                raise ValueError("direct_testcase_sources 每项必须是对象")
            source_id = str(item.get("source_id") or f"SRC-{index:03d}").strip()
            title_path = str(item.get("title_path") or item.get("source_path") or item.get("title") or source_id).strip()
            title = str(item.get("title") or title_path or source_id).strip()
            raw_blocks.append(
                {
                    "block_id": source_id,
                    "title_path": title_path,
                    "source_order": item.get("source_order", index),
                    "module": item.get("module") or title,
                    "scene": item.get("scene") or title,
                    "title": title,
                    "source_location": item.get("source_location") or title_path,
                    "source_type": item.get("source_type") or "prd_text",
                    "xmind_source_node": item.get("xmind_source_node") or f"{source_id}｜{title_path}",
                }
            )
            raw_shards.append(
                {
                    "shard_id": item.get("shard_id") or f"SHARD-{index:03d}",
                    "direct_testcase_source": source_id,
                    "source_order": item.get("source_order", index),
                    "title_path": title_path,
                    "module": item.get("module") or title,
                    "scene": item.get("scene") or title,
                    "xmind_source_node": item.get("xmind_source_node") or f"{source_id}｜{title_path}",
                    "assigned_primary_sources": item.get("primary_sections") or [source_id],
                    "assigned_dependency_sources": item.get("dependency_sections") or [],
                    "rule_clusters": item.get("rule_clusters") or [],
                    "smoke_test_scope_note": item.get("smoking_scope_note") or item.get("smoke_test_scope_note") or "",
                    "risk_signals": item.get("risk_signals") if isinstance(item.get("risk_signals"), list) else [],
                    "complexity_score": item.get("complexity_score") or 3,
                    "test_design_profile": item.get("test_design_profile") or _default_test_design_profile(item),
                }
            )
    normalized_blocks: list[dict] = []
    normalized_shards: list[dict] = []
    seen: set[str] = set()
    block_by_id: dict[str, dict] = {}
    for index, block in enumerate(raw_blocks, start=1):
        if not isinstance(block, dict):
            raise ValueError("source_blocks 每项必须是对象")
        source_id = str(block.get("block_id") or block.get("source_id") or f"SRC-{index:03d}").strip()
        if not str(block.get("block_id") or block.get("source_id") or "").strip():
            normalization_notes.append({"severity": "blocker", "code": "SOURCE_ID_DEFAULTED", "message": f"第 {index} 个 source block 缺少 block_id，已临时补为 {source_id}"})
        if source_id in seen:
            raise ValueError(f"scope_index source_id 重复：{source_id}")
        seen.add(source_id)
        title_path = str(block.get("title_path") or block.get("title") or source_id).strip()
        title = str(block.get("title") or title_path or source_id).strip()
        if not str(block.get("title") or "").strip():
            normalization_notes.append({"severity": "blocker", "code": "SOURCE_TITLE_MISSING", "message": f"{source_id} 缺少 title"})
        module = str(block.get("module") or "").strip()
        scene = str(block.get("scene") or "").strip()
        if not module:
            normalization_notes.append({"severity": "blocker", "code": "SOURCE_MODULE_MISSING", "message": f"{source_id} 缺少 module"})
            module = title
        if not scene:
            normalization_notes.append({"severity": "blocker", "code": "SOURCE_SCENE_MISSING", "message": f"{source_id} 缺少 scene"})
            scene = title
        if not title_path:
            normalization_notes.append({"severity": "blocker", "code": "SOURCE_TITLE_PATH_MISSING", "message": f"{source_id} 缺少 title_path"})
            title_path = title
        raw_source_order = block.get("source_order") if block.get("source_order") not in (None, "") else index
        xmind_source_node = str(block.get("xmind_source_node") or f"{source_id}｜{title_path}").strip()
        normalized_block = {
            "block_id": source_id,
            "title_path": title_path,
            "source_order": raw_source_order,
            "module": module,
            "scene": scene,
            "title": title,
            "source_location": block.get("source_location") or title_path,
            "source_type": block.get("source_type") or "prd_text",
            "xmind_source_node": xmind_source_node,
        }
        normalized_blocks.append(normalized_block)
        block_by_id[source_id] = normalized_block
    shard_source_ids = {
        str(shard.get("direct_testcase_source") or shard.get("source_id") or "").strip()
        for shard in raw_shards
        if isinstance(shard, dict)
    }
    missing_shard_blocks = [
        block for block in normalized_blocks
        if str(block.get("block_id") or "").strip() not in shard_source_ids
    ]
    if missing_shard_blocks:
        for block in missing_shard_blocks:
            raw_shards.append(_default_scope_shard_for_block(block, len(raw_shards) + 1))
        normalization_notes.append({
            "severity": "warning",
            "code": "MISSING_SHARDS_REBUILT",
            "message": f"后端已根据 source_blocks 补齐 {len(missing_shard_blocks)} 个缺失 shard",
        })
    for index, shard in enumerate(raw_shards, start=1):
        source_id = str(shard.get("direct_testcase_source") or shard.get("source_id") or f"SRC-{index:03d}").strip()
        block = block_by_id.get(source_id) or {}
        title_path = str(shard.get("title_path") or block.get("title_path") or block.get("title") or source_id).strip()
        module = str(shard.get("module") or block.get("module") or block.get("title") or title_path).strip()
        scene = str(shard.get("scene") or block.get("scene") or block.get("title") or title_path).strip()
        forbidden_budget_keys = _coverage_budget_forbidden_keys(shard.get("test_design_profile"))
        if forbidden_budget_keys:
            normalization_notes.append({
                "severity": "blocker",
                "code": "COVERAGE_BUDGET_HAS_FIXED_COUNT",
                "message": f"{source_id} coverage_budget 禁止包含 {', '.join(forbidden_budget_keys)}",
            })
        profile = _normalize_test_design_profile(shard.get("test_design_profile"), shard)
        normalized_shards.append(
            {
                "shard_id": str(shard.get("shard_id") or f"SHARD-{index:03d}").strip(),
                "direct_testcase_source": source_id,
                "source_order": shard.get("source_order", block.get("source_order", index)),
                "source_order_index": index,
                "title_path": title_path,
                "module": module,
                "scene": scene,
                "xmind_source_node": str(shard.get("xmind_source_node") or block.get("xmind_source_node") or f"{source_id}｜{title_path}").strip(),
                "assigned_primary_sources": shard.get("assigned_primary_sources") if isinstance(shard.get("assigned_primary_sources"), list) else [source_id],
                "assigned_dependency_sources": shard.get("assigned_dependency_sources") if isinstance(shard.get("assigned_dependency_sources"), list) else [],
                "rule_clusters": shard.get("rule_clusters") if isinstance(shard.get("rule_clusters"), list) else [],
                "dependency_reason": str(shard.get("dependency_reason") or "").strip(),
                "backcheck_sources": shard.get("backcheck_sources") if isinstance(shard.get("backcheck_sources"), list) else [],
                "excluded_sources": shard.get("excluded_sources") if isinstance(shard.get("excluded_sources"), list) else [],
                "smoke_test_scope_note": str(shard.get("smoke_test_scope_note") or shard.get("smoking_scope_note") or "").strip(),
                "risk_signals": profile.get("risk_signals") or [],
                "complexity_score": shard.get("complexity_score") or 3,
                "complexity_reasons": shard.get("complexity_reasons") if isinstance(shard.get("complexity_reasons"), list) else [],
                "test_design_profile": profile,
                "recommended_shard_group": shard.get("recommended_shard_group") or "standalone",
            }
        )
    legacy_sources = []
    for item in _trusted_scope_source_items({"source_blocks": normalized_blocks, "shards": normalized_shards}):
        legacy_sources.append(
            {
                "source_id": item["source_id"],
                "shard_id": item["shard_id"],
                "title": item["title"],
                "title_path": item["title_path"],
                "module": item["module"],
                "scene": item["scene"],
                "source_order": item["source_order"],
                "source_order_index": item["source_order_index"],
                "xmind_source_node": item["xmind_source_node"],
                "primary_sections": item.get("primary_sections") or [item["source_id"]],
                "dependency_sections": item.get("dependency_sections") or [],
                "rule_clusters": item.get("rule_clusters") or [],
                "complexity": item.get("complexity") or "medium",
                "test_design_profile": item.get("test_design_profile") or _default_test_design_profile(item),
                "smoking_scope_note": item.get("smoking_scope_note") or "",
            }
        )
    return {
        "version": raw.get("version") or "trusted-skill-v2",
        "source_blocks": normalized_blocks,
        "scope_classification": raw.get("scope_classification") if isinstance(raw.get("scope_classification"), list) else [],
        "shards": normalized_shards,
        "dependency_bindings": raw.get("dependency_bindings") if isinstance(raw.get("dependency_bindings"), list) else [],
        "coverage_check": raw.get("coverage_check") if isinstance(raw.get("coverage_check"), dict) else {
            "all_source_blocks_classified": True,
            "all_direct_sources_have_shards": True,
            "all_dependency_sources_bound": True,
            "unassigned_sources": [],
            "index_warnings": [],
            "index_risks": [],
        },
        "expected_source_list": raw.get("expected_source_list") if isinstance(raw.get("expected_source_list"), list) else [item["block_id"] for item in normalized_blocks],
        "index_risks": raw.get("index_risks") if isinstance(raw.get("index_risks"), list) else [],
        "normalization_notes": normalization_notes,
        "direct_testcase_sources": legacy_sources,
    }


def _build_trusted_scope_index(
    markdown_text: str,
    image_analysis: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    progress_callback=None,
) -> dict:
    sections, dropped_sections = _filter_out_background_sections(_extract_sections(markdown_text))
    strategy = _choose_scope_index_strategy(sections)
    state_transition_evidence = [
        {
            "title_path": item.get("title_path"),
            "source_excerpt": item.get("source_excerpt"),
            "image_evidence": item.get("image_evidence") or [],
            "source_state_semantics": item.get("source_state_semantics") or {},
        }
        for item in _section_evidence_catalog(
            markdown_text,
            _extract_image_links(markdown_text, base_url),
            image_analysis,
            base_url=base_url,
        )
        if (item.get("source_state_semantics") or {}).get("has_state_transition")
    ]
    base_payload = {
        "task": "把需求文档拆成直接测试对象范围索引。只输出 JSON。",
        "schema": {
            "source_blocks": [
                {
                    "block_id": "SRC-001",
                    "title_path": "2.1 原需求章节/段落标题",
                    "source_order": "2.1",
                    "module": "业务模块",
                    "scene": "业务场景",
                    "title": "可测试对象名称",
                    "source_location": "requirement.md#2.1",
                    "source_type": "prd_text",
                    "xmind_source_node": "SRC-001｜2.1 原需求章节/段落标题",
                }
            ],
            "scope_classification": [
                {
                    "source_id": "SRC-001",
                    "title": "可测试对象名称",
                    "classification": "direct_testcase_source",
                    "scope_status": "in_scope",
                    "reason": "该章节描述独立可操作功能",
                    "related_sources": [],
                    "risk_signals": [],
                    "evidence": [],
                }
            ],
            "shards": [
                {
                    "shard_id": "SHARD-001",
                    "direct_testcase_source": "SRC-001",
                    "source_order": "2.1",
                    "title_path": "2.1 原需求章节/段落标题",
                    "module": "业务模块",
                    "scene": "业务场景",
                    "xmind_source_node": "SRC-001｜2.1 原需求章节/段落标题",
                    "assigned_primary_sources": ["SRC-001"],
                    "assigned_dependency_sources": [],
                    "rule_clusters": [],
                    "smoke_test_scope_note": "为什么它是直接测试对象，以及不展开哪些依赖",
                    "risk_signals": [],
                    "complexity_score": 3,
                    "test_design_profile": {
                        "applicable_methods": ["equivalence"],
                        "risk_signals": [],
                        "must_cover": ["该 source 的核心业务义务"],
                        "merge_allowed": [],
                        "not_applicable": [],
                        "coverage_budget": {"guidance": "按 must_cover 和适用方法生成可观察用例；低风险重复字段可合并，不以固定条数为目标。"},
                    },
                    "recommended_shard_group": "standalone",
                }
            ],
            "dependency_bindings": [],
            "coverage_check": {
                "all_source_blocks_classified": True,
                "all_direct_sources_have_shards": True,
                "all_dependency_sources_bound": True,
                "unassigned_sources": [],
                "index_warnings": [],
                "index_risks": [],
            },
            "expected_source_list": ["SRC-001"],
        },
        "rules": [
            "source_blocks 只放能直接生成测试用例的对象，背景、术语、环境说明不要放入",
            "source_blocks.block_id 使用 SRC-001 递增且唯一；shards.direct_testcase_source 必须引用对应 block_id",
            "source_order 使用原需求章节顺序（如 2.1、3.4、4.7），不是优先级或模型重排序号",
            "module、scene、title_path 必须来自原需求层级；xmind_source_node 必须等于 source_id + '｜' + title_path",
            "每个 shard 必须给出 test_design_profile，包含 applicable_methods、risk_signals、must_cover、merge_allowed、not_applicable、coverage_budget",
            "coverage_budget 只能写覆盖倾向和精简原则，禁止出现 min、target、max 或固定用例条数",
            "assigned_dependency_sources 只能作为上下文依赖，不应单独驱动用例数量",
            "遇到现有效果/问题场景与优化效果/正确场景时，current 只表示改造前状态，must_cover 和 smoke_test_scope_note 必须描述 target；不得把旧位置、旧样式或旧行为写成目标验收项",
            "target 只有图片时，必须依据 source_state_semantics.target_image_refs 和对应 target image_evidence 提取目标，不得反向复用 current 文本",
        ],
        "dropped_background_sections": [item.get("title") for item in dropped_sections],
        "state_transition_evidence": state_transition_evidence,
    }
    if progress_callback:
        progress_callback(
            "范围索引策略："
            f"{strategy['mode']}，章节 {strategy['section_count']} 个，"
            f"文本 {strategy['text_size']} 字符，批次 {strategy['batch_count']}，并发 {strategy['concurrency']}"
        )
    if strategy["uses_batches"]:
        return _build_trusted_scope_index_by_section_batches(
            sections,
            dropped_sections,
            image_analysis,
            base_payload,
            api_key=api_key,
            model=model,
            base_url=base_url,
            reason="文档章节或文本规模超过单次索引阈值",
            strategy=strategy,
            progress_callback=progress_callback,
        )
    attempts = [
        {"name": "full", "total_limit": 36000, "per_section_limit": 2400, "image_limit": 12, "max_tokens": 9000, "task_suffix": ""},
        {"name": "full_more_output", "total_limit": 36000, "per_section_limit": 2400, "image_limit": 12, "max_tokens": 13500, "task_suffix": "如输出较长，优先压缩 note 和 dependency_sections 文本，保证 JSON 完整闭合。"},
        {"name": "compact", "total_limit": 18000, "per_section_limit": 1400, "image_limit": 8, "max_tokens": 9000, "task_suffix": "本次使用压缩输入重试。只保留直接测试对象必要字段，dependency_sections/rule_clusters 用短字符串，必须返回完整 JSON。"},
    ]
    last_error: Exception | None = None
    for attempt in attempts:
        payload = dict(base_payload)
        payload["task"] = f"{base_payload['task']} {attempt['task_suffix']}".strip()
        payload["retry_policy"] = {
            "attempt": attempt["name"],
            "json_must_be_complete": True,
            "prefer_short_values": attempt["name"] == "compact",
        }
        payload["sections"] = _compact_sections_for_ai(
            sections,
            per_section_limit=attempt["per_section_limit"],
            total_limit=attempt["total_limit"],
        )
        payload["image_analysis"] = _compact_image_analysis_for_ai(image_analysis, limit=attempt["image_limit"])
        try:
            raw = _call_trusted_skill_json(
                skill_name="scope-indexer",
                payload=payload,
                api_key=api_key,
                model=model,
                base_url=base_url,
                max_tokens=attempt["max_tokens"],
                timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
                max_attempts=2,
                retry_timeouts=False,
            )
            skill_attempt_count = int((raw.pop("_execution_meta", {}) or {}).get("skill_attempt_count") or 1)
            scope_index = _normalize_trusted_scope_index(raw)
            scope_index["execution_strategy"] = strategy
            if attempt["name"] != "full" or skill_attempt_count > 1:
                notes = scope_index.get("normalization_notes") if isinstance(scope_index.get("normalization_notes"), list) else []
                notes.append(
                    {
                        "severity": "info",
                        "code": "SCOPE_INDEX_RETRY_USED",
                        "message": f"scope_index 首次输出不完整，已在第 {skill_attempt_count} 次 Skill 调用中使用 {attempt['name']} 策略成功",
                    }
                )
                scope_index["normalization_notes"] = notes
            return scope_index
        except ModelJSONParseError as exc:
            last_error = exc
            if not _is_json_truncation_error(exc):
                break
            continue
        except RuntimeError as exc:
            last_error = exc
            if "模型响应超时" in str(exc) or "timeout" in str(exc).lower():
                return _build_trusted_scope_index_by_section_batches(
                    sections,
                    dropped_sections,
                    image_analysis,
                    base_payload,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    reason=f"单次 scope_index 调用超时：{exc}",
                    strategy={**_choose_scope_index_strategy(sections), "mode": "section_batches_full_after_timeout", "uses_batches": True},
                    progress_callback=progress_callback,
                )
            raise
    if last_error:
        raise last_error
    raise ValueError("scope_index 生成失败")


def _build_trusted_scope_index_by_section_batches(
    sections: list[dict],
    dropped_sections: list[dict],
    image_analysis: list[dict],
    base_payload: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    reason: str,
    strategy: dict | None = None,
    progress_callback=None,
) -> dict:
    batches = _build_scope_index_section_batches(sections)
    if not batches:
        raise ValueError("scope_index 分批生成失败：无有效章节")
    effective_strategy = dict(strategy or _choose_scope_index_strategy(sections))
    use_lightweight = bool(effective_strategy.get("uses_lightweight_discovery"))
    concurrency = min(max(int(effective_strategy.get("concurrency") or 1), 1), len(batches))
    batch_indexes_by_number: dict[int, dict] = {}
    started_at = time.perf_counter()
    if progress_callback:
        progress_callback(
            f"范围索引分批准备：共 {len(batches)} 批，"
            f"并发 {concurrency}，策略 {effective_strategy.get('mode') or 'section_batches_full'}"
        )

    def run_batch(batch_index: int, batch_sections: list[dict]) -> dict:
        payload = dict(base_payload)
        if use_lightweight:
            payload["task"] = (
                "长文档轻量范围索引第一阶段：只识别当前 sections 中可直接测试的 source_blocks。"
                "输出 source_blocks、scope_classification、expected_source_list；shards 可省略，后端会补齐。只输出 JSON。"
            )
            payload["schema"] = {
                "source_blocks": base_payload["schema"]["source_blocks"],
                "scope_classification": base_payload["schema"]["scope_classification"],
                "expected_source_list": ["SRC-001"],
                "dependency_bindings": [],
                "coverage_check": {
                    "all_source_blocks_classified": True,
                    "all_direct_sources_have_shards": True,
                    "all_dependency_sources_bound": True,
                    "unassigned_sources": [],
                    "index_warnings": [],
                    "index_risks": [],
                },
            }
            payload["rules"] = [
                "只输出可直接生成测试用例的 source_blocks，背景、术语、环境说明不要放入",
                "block_id 使用 SRC-001 递增且在本批唯一，后端会重编号",
                "module、scene、title_path 必须来自当前批次原需求层级",
                "每个 source_block 的 title 必须是可测试对象名称，不要写泛化标题",
                "不要输出冗长解释；优先保证 JSON 完整闭合",
            ]
            per_section_limit = 1200
            total_limit = 6500
            max_tokens = 3600
            image_limit = 2
        else:
            payload["task"] = (
                "把当前 sections 分批拆成直接测试对象范围索引。"
                "只处理本批 sections，不要推断其他批次内容。只输出 JSON。"
            )
            per_section_limit = 1800
            total_limit = 10000
            max_tokens = 6500
            image_limit = 4
        payload["batch_policy"] = {
            "batch_index": batch_index,
            "batch_count": len(batches),
            "ids_may_start_from_src_001": True,
            "backend_will_renumber_global_ids": True,
            "json_must_be_complete": True,
            "prefer_short_values": True,
            "lightweight_discovery": use_lightweight,
        }
        payload["sections"] = _compact_sections_for_ai(
            batch_sections,
            per_section_limit=per_section_limit,
            total_limit=total_limit,
        )
        payload["image_analysis"] = _compact_image_analysis_for_ai(image_analysis, limit=image_limit)
        payload["dropped_background_sections"] = [item.get("title") for item in dropped_sections]
        raw = _call_trusted_skill_json(
            skill_name="scope-indexer",
            payload=payload,
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=max_tokens,
            timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
        )
        return _normalize_trusted_scope_index(raw)

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        if progress_callback:
            for batch_index, batch_sections in enumerate(batches, start=1):
                progress_callback(
                    f"范围索引分批 {batch_index}/{len(batches)} 已提交，"
                    f"本批 {len(batch_sections)} 个章节"
                )
        future_to_batch = {
            executor.submit(contextvars.copy_context().run, run_batch, batch_index, batch_sections): batch_index
            for batch_index, batch_sections in enumerate(batches, start=1)
        }
        for completed_count, future in enumerate(concurrent.futures.as_completed(future_to_batch), start=1):
            batch_index = future_to_batch[future]
            batch_indexes_by_number[batch_index] = future.result()
            completed_sources = sum(len(item.get("source_blocks") or []) for item in batch_indexes_by_number.values())
            elapsed = time.perf_counter() - started_at
            avg = elapsed / completed_count
            remaining = max(len(batches) - completed_count, 0)
            if progress_callback:
                progress_callback(
                    f"范围索引分批 {completed_count}/{len(batches)} 已完成"
                    f"（刚完成第 {batch_index} 批），累计 {completed_sources} 个候选 source，"
                    f"预计剩余 {_format_duration_zh(avg * remaining)}"
                )

    batch_indexes = [batch_indexes_by_number[index] for index in range(1, len(batches) + 1)]
    effective_strategy["concurrency"] = concurrency
    effective_strategy["batch_count"] = len(batches)
    effective_strategy["uses_lightweight_discovery"] = use_lightweight
    effective_strategy["mode"] = effective_strategy.get("mode") or ("section_batches_lightweight" if use_lightweight else "section_batches_full")
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    effective_strategy["duration_ms"] = elapsed_ms
    if progress_callback:
        progress_callback(
            f"范围索引分批合并中：{len(batches)} 批全部完成，耗时 {_format_duration_zh(elapsed_ms / 1000)}"
        )
    return _merge_trusted_scope_index_batches(batch_indexes, reason=reason, strategy=effective_strategy)


def _validate_trusted_scope_index(scope_index: dict) -> dict:
    sources = _trusted_scope_source_items(scope_index)
    shards = _trusted_scope_shards(scope_index)
    dependency_bindings = scope_index.get("dependency_bindings") or []
    evidence_contract_required = isinstance(scope_index.get("section_evidence_catalog"), list)
    issues: list[dict] = []
    for note in scope_index.get("normalization_notes") or []:
        if isinstance(note, dict):
            issues.append({
                "severity": note.get("severity") or "blocker",
                "code": note.get("code") or "NORMALIZATION_NOTE",
                "message": note.get("message") or "scope_index 字段被后端规范化",
            })
    if not sources:
        issues.append({"severity": "blocker", "code": "NO_DIRECT_TESTCASE_SOURCE", "message": "source_blocks/shards 为空"})
    seen_ids: set[str] = set()
    source_ids: set[str] = set()
    dependency_orphans: list[str] = []
    for item in sources:
        if not isinstance(item, dict):
            issues.append({"severity": "blocker", "code": "BAD_SOURCE_ITEM", "message": "source_blocks 包含非对象项"})
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            issues.append({"severity": "blocker", "code": "SOURCE_ID_MISSING", "message": "source 缺少 source_id"})
            continue
        if source_id in seen_ids:
            issues.append({"severity": "blocker", "code": "SOURCE_ID_DUPLICATED", "message": f"{source_id} 重复"})
        seen_ids.add(source_id)
        source_ids.add(source_id)
        if not str(item.get("title") or "").strip():
            issues.append({"severity": "blocker", "code": "SOURCE_TITLE_MISSING", "message": f"{source_id} 缺少 title"})
        title_path = str(item.get("title_path") or "").strip()
        module = str(item.get("module") or "").strip()
        scene = str(item.get("scene") or "").strip()
        xmind_source_node = str(item.get("xmind_source_node") or "").strip()
        shard_id = str(item.get("shard_id") or "").strip()
        if not title_path:
            issues.append({"severity": "blocker", "code": "SOURCE_TITLE_PATH_MISSING", "message": f"{source_id} 缺少 title_path"})
        if not module:
            issues.append({"severity": "blocker", "code": "SOURCE_MODULE_MISSING", "message": f"{source_id} 缺少 module"})
        if not scene:
            issues.append({"severity": "blocker", "code": "SOURCE_SCENE_MISSING", "message": f"{source_id} 缺少 scene"})
        if not shard_id:
            issues.append({"severity": "blocker", "code": "SOURCE_SHARD_ID_MISSING", "message": f"{source_id} 缺少 shard_id"})
        if xmind_source_node != f"{source_id}｜{title_path}":
            issues.append({"severity": "blocker", "code": "SOURCE_XMIND_NODE_MISMATCH", "message": f"{source_id} xmind_source_node 必须等于 source_id + ｜ + title_path"})
        if not str(item.get("source_order") or "").strip():
            issues.append({"severity": "blocker", "code": "SOURCE_ORDER_MISSING", "message": f"{source_id} 缺少 source_order"})
        if not isinstance(item.get("primary_sections"), list) or not item.get("primary_sections"):
            issues.append({"severity": "blocker", "code": "PRIMARY_SECTIONS_MISSING", "message": f"{source_id} 缺少 primary_sections"})
        if not isinstance(item.get("dependency_sections"), list):
            issues.append({"severity": "blocker", "code": "DEPENDENCY_SECTIONS_BAD_TYPE", "message": f"{source_id} dependency_sections 必须是数组"})
        if not isinstance(item.get("rule_clusters"), list):
            issues.append({"severity": "blocker", "code": "RULE_CLUSTERS_BAD_TYPE", "message": f"{source_id} rule_clusters 必须是数组"})
        if evidence_contract_required and not str(item.get("source_doc_id") or "").strip():
            issues.append({"severity": "blocker", "code": "SOURCE_EVIDENCE_NOT_BOUND", "message": f"{source_id} 未绑定原需求章节"})
        if evidence_contract_required and not str(item.get("source_excerpt") or "").strip() and not item.get("image_refs"):
            issues.append({"severity": "blocker", "code": "SOURCE_EVIDENCE_EMPTY", "message": f"{source_id} 缺少需求原文和图片证据"})
        if evidence_contract_required and not isinstance(item.get("image_refs"), list):
            issues.append({"severity": "blocker", "code": "SOURCE_IMAGE_REFS_BAD_TYPE", "message": f"{source_id} image_refs 必须是数组"})
        profile = item.get("test_design_profile") if isinstance(item.get("test_design_profile"), dict) else {}
        if not isinstance(profile.get("applicable_methods"), list) or not profile.get("applicable_methods"):
            issues.append({"severity": "blocker", "code": "TEST_DESIGN_METHODS_MISSING", "message": f"{source_id} test_design_profile.applicable_methods 为空"})
        if not isinstance(profile.get("must_cover"), list) or not profile.get("must_cover"):
            issues.append({"severity": "blocker", "code": "MUST_COVER_MISSING", "message": f"{source_id} test_design_profile.must_cover 为空"})
        state_conflicts = _state_target_conflicts(
            item,
            "\n".join([
                str(item.get("smoking_scope_note") or ""),
                *[str(value or "") for value in profile.get("must_cover") or []],
            ]),
        )
        if state_conflicts:
            issues.append({
                "severity": "blocker",
                "code": "CURRENT_STATE_MUST_COVER_CONTRADICTS_TARGET",
                "source_id": source_id,
                "message": f"{source_id} must_cover 仍使用 current 旧状态，和 target 证据冲突：{state_conflicts[0]['attribute']}",
            })
        coverage_budget = profile.get("coverage_budget") if isinstance(profile.get("coverage_budget"), dict) else {}
        if item.get("coverage_budget_forbidden_keys") or any(key in coverage_budget for key in ("min", "target", "max")):
            issues.append({"severity": "blocker", "code": "COVERAGE_BUDGET_HAS_FIXED_COUNT", "message": f"{source_id} coverage_budget 禁止包含 min/target/max"})
    shard_source_ids = {
        str(item.get("direct_testcase_source") or "").strip()
        for item in shards
        if isinstance(item, dict) and str(item.get("direct_testcase_source") or "").strip()
    }
    for source_id in sorted(source_ids - shard_source_ids):
        issues.append({"severity": "blocker", "code": "SOURCE_WITHOUT_SHARD", "message": f"{source_id} 没有对应 shard"})
    for source_id in sorted(shard_source_ids - source_ids):
        issues.append({"severity": "blocker", "code": "SHARD_UNKNOWN_SOURCE", "message": f"shard 引用了未知 source：{source_id}"})
    if isinstance(dependency_bindings, list):
        for binding in dependency_bindings:
            if not isinstance(binding, dict):
                issues.append({"severity": "blocker", "code": "BAD_DEPENDENCY_BINDING", "message": "dependency_bindings 包含非对象项"})
                continue
            bound_source_id = str(binding.get("source_id") or binding.get("target_source_id") or "").strip()
            if bound_source_id and bound_source_id not in source_ids:
                dependency_orphans.append(bound_source_id)
    else:
        issues.append({"severity": "blocker", "code": "DEPENDENCY_BINDINGS_BAD_TYPE", "message": "dependency_bindings 必须是数组"})
    for source_id in sorted(set(dependency_orphans)):
        issues.append({"severity": "blocker", "code": "ORPHAN_DEPENDENCY_BINDING", "message": f"dependency_bindings 引用了不存在的 source：{source_id}"})
    return {
        "gate": "scope_index_gate",
        "passed": not any(item["severity"] == "blocker" for item in issues),
        "issues": issues,
        "source_count": len(source_ids),
        "dependency_binding_count": len(dependency_bindings) if isinstance(dependency_bindings, list) else 0,
    }


def _build_trusted_requirement_handoff(
    scope_index: dict,
    markdown_text: str,
    image_analysis: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    progress_callback=None,
) -> dict:
    sections, _ = _filter_out_background_sections(_extract_sections(markdown_text))
    sources = _trusted_scope_source_items(scope_index)
    requirement_input_size = sum(
        len(str(item.get("body") or "")) + len(str(item.get("title") or ""))
        for item in sections
        if isinstance(item, dict)
    )
    if len(sources) > 10 or requirement_input_size > 30000:
        return _build_trusted_requirement_handoff_by_source_batches(
            scope_index,
            sections,
            image_analysis,
            api_key=api_key,
            model=model,
            base_url=base_url,
            progress_callback=progress_callback,
        )
    payload = {
        "task": "基于 scope_index 生成功能点，并记录每个 source 是否被消费。只输出 JSON。",
        "schema": {
            "scope_index_consumption": [
                {"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"], "note": ""}
            ],
            "function_points": [
                {
                    "fp_id": "FP-001",
                    "source_id": "SRC-001",
                    "shard_id": "SHARD-SRC-001",
                    "source_order": "1",
                    "title_path": "一级标题 > 二级标题",
                    "source_title": "",
                    "title": "",
                    "description": "",
                    "rules": [],
                    "test_hints": [],
                    "priority_hint": "P0|P1|P2|P3",
                    "coverage_intent": "positive|boundary|negative|ui|state|permission",
                    "merge_allowed": False,
                    "source_refs": [],
                    "source_quotes": ["从 source.source_excerpt 逐字复制的需求原文"],
                    "target_evidence_refs": ["IMG-001"],
                }
            ],
            "pending_confirmations": [],
        },
        "rules": [
            "每个 function_point 必须有 source_id，且必须来自 scope_index.source_blocks",
            "每个 function_point 必须继承对应 source 的 shard_id、source_order、title_path，不允许自行改写归属",
            "每个 direct source 必须在 scope_index_consumption 中出现一次",
            "如果 source 被合并或阻塞，必须在 note 中说明原因",
            "控制功能点颗粒度：同一 source 下的正常、边界、异常、权限等规则优先合并为同一功能点的 rules/test_hints，不要拆成多个同构 FP",
            "除非 source 本身包含多个独立用户目标，否则不要按测试类型机械拆分功能点",
            "每个 function_point.source_quotes 必须逐字复制对应 source.source_excerpt 中直接支持该功能点的原文；禁止改写或概括",
            "rules、description 只能表达 source_excerpt 或 image_evidence 明确支持的要求；禁止把目标性描述自行推断为位置、样式、边框、文案或交互验收标准",
            "需求未明确具体结果时写入 pending_confirmations，不得自行补全",
            "source_state_semantics.has_state_transition=true 时，current_text/current_image_refs 只描述改造前状态，不得写成目标功能点；目标功能点必须由 target_text 或 target_image_refs 支撑",
            "目标仅存在于图片时，function_point.target_evidence_refs 必须逐项列出使用的 target_image_refs；source_quotes 不得用 current 文本冒充优化结果",
        ],
        "scope_index": scope_index,
        "sections": _compact_sections_for_ai(sections, total_limit=36000),
        "image_analysis": _compact_image_analysis_for_ai(image_analysis),
    }
    raw = _call_trusted_skill_json(
        skill_name="requirement-analyzer",
        payload=payload,
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tokens=14000,
        timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
    )
    if not isinstance(raw, dict):
        raise ValueError("requirement_handoff 模型输出必须是 JSON 对象")
    raw.setdefault("scope_index_consumption", [])
    raw.setdefault("function_points", [])
    raw.setdefault("pending_confirmations", [])
    return _repair_converted_requirement_consumption(
        _renumber_trusted_requirement_handoff(_normalize_trusted_requirement_handoff(scope_index, raw))
    )


def _source_batch_scope_index(scope_index: dict, sources: list[dict]) -> dict:
    source_ids = {str(item.get("source_id") or "").strip() for item in sources if isinstance(item, dict)}
    subset = {
        "direct_testcase_sources": sources,
        "dependency_bindings": [
            item for item in scope_index.get("dependency_bindings") or []
            if isinstance(item, dict)
            and str(item.get("source_id") or item.get("target_source_id") or "").strip() in source_ids
        ],
        "index_risks": [
            item for item in scope_index.get("index_risks") or []
            if not isinstance(item, dict) or str(item.get("source_id") or "").strip() in source_ids
        ],
    }
    if isinstance(scope_index.get("source_blocks"), list):
        subset["source_blocks"] = [
            item for item in scope_index.get("source_blocks") or []
            if isinstance(item, dict) and str(item.get("source_id") or "").strip() in source_ids
        ]
    if isinstance(scope_index.get("shards"), list):
        subset["shards"] = [
            item for item in scope_index.get("shards") or []
            if isinstance(item, dict)
            and str(item.get("direct_testcase_source") or item.get("source_id") or "").strip() in source_ids
        ]
    return subset


def _source_batch_sections(sources: list[dict], sections: list[dict]) -> list[dict]:
    needles: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("title", "title_path", "module", "scene"):
            value = str(source.get(key) or "").strip()
            if value:
                needles.add(value)
                needles.update(part.strip() for part in re.split(r"[/>\n]", value) if part.strip())
        for key in ("primary_sections", "dependency_sections"):
            for value in source.get(key) or []:
                value = str(value or "").strip()
                if value:
                    needles.add(value)
                    needles.update(part.strip() for part in re.split(r"[/>\n]", value) if part.strip())

    selected: list[dict] = []
    for section in sections:
        title = str(section.get("title") or "").strip()
        body = str(section.get("body") or "")
        if any(needle and (needle == title or needle in title or needle in body) for needle in needles):
            selected.append(section)
    return selected or sections[:4]


def _renumber_trusted_requirement_handoff(requirement_handoff: dict) -> dict:
    function_points = [item for item in requirement_handoff.get("function_points") or [] if isinstance(item, dict)]
    source_old_to_new: dict[tuple[str, str], str] = {}
    old_id_matches: dict[str, list[str]] = {}
    for index, fp in enumerate(function_points, start=1):
        old_id = str(fp.get("fp_id") or "").strip()
        source_id = str(fp.get("source_id") or "").strip()
        new_id = f"FP-{index:03d}"
        if old_id:
            source_old_to_new[(source_id, old_id)] = new_id
            old_id_matches.setdefault(old_id, []).append(new_id)
        fp["fp_id"] = new_id

    for item in requirement_handoff.get("scope_index_consumption") or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        fp_ids = []
        for fp_id in item.get("fp_ids") or []:
            fp_id = str(fp_id or "").strip()
            source_match = source_old_to_new.get((source_id, fp_id))
            global_matches = old_id_matches.get(fp_id) or []
            fp_ids.append(source_match or (global_matches[0] if len(global_matches) == 1 else fp_id))
        item["fp_ids"] = [fp_id for fp_id in fp_ids if fp_id]
    pending_items = [
        item
        for item in requirement_handoff.get("pending_confirmations") or []
        if isinstance(item, dict)
    ]
    for index, item in enumerate(pending_items, start=1):
        item["id"] = f"PC-{index:03d}"
        item.setdefault("blocking", False)
        source_id = str(item.get("source_id") or "").strip()
        related_fp_ids = []
        for fp_id in item.get("related_fp_ids") or []:
            fp_id = str(fp_id or "").strip()
            source_match = source_old_to_new.get((source_id, fp_id))
            global_matches = old_id_matches.get(fp_id) or []
            related_fp_ids.append(source_match or (global_matches[0] if len(global_matches) == 1 else fp_id))
        item["related_fp_ids"] = [fp_id for fp_id in related_fp_ids if fp_id]
    return requirement_handoff


def _repair_pending_confirmation_fp_refs(requirement_handoff: dict) -> dict:
    fp_ids_by_source: dict[str, list[str]] = defaultdict(list)
    known_fp_ids: set[str] = set()
    for fp in requirement_handoff.get("function_points") or []:
        if not isinstance(fp, dict):
            continue
        source_id = str(fp.get("source_id") or "").strip()
        fp_id = str(fp.get("fp_id") or "").strip()
        if source_id and fp_id:
            fp_ids_by_source[source_id].append(fp_id)
            known_fp_ids.add(fp_id)
    for item in requirement_handoff.get("pending_confirmations") or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        source_fp_ids = fp_ids_by_source.get(source_id) or []
        repaired_ids: list[str] = []
        for value in item.get("related_fp_ids") or []:
            fp_id = str(value or "").strip()
            repaired = fp_id
            legacy_match = re.fullmatch(r"FP-(\d+)-(\d+)", fp_id)
            if fp_id not in known_fp_ids and legacy_match:
                source_number = re.sub(r"\D", "", source_id)
                local_index = int(legacy_match.group(2))
                if (
                    source_number
                    and int(legacy_match.group(1)) == int(source_number)
                    and 1 <= local_index <= len(source_fp_ids)
                ):
                    repaired = source_fp_ids[local_index - 1]
            if repaired and repaired not in repaired_ids:
                repaired_ids.append(repaired)
        item["related_fp_ids"] = repaired_ids
    return requirement_handoff


def _repair_converted_requirement_consumption(requirement_handoff: dict) -> dict:
    fp_ids_by_source: dict[str, list[str]] = defaultdict(list)
    for fp in requirement_handoff.get("function_points") or []:
        if not isinstance(fp, dict):
            continue
        source_id = str(fp.get("source_id") or "").strip()
        fp_id = str(fp.get("fp_id") or "").strip()
        if source_id and fp_id:
            fp_ids_by_source[source_id].append(fp_id)

    repair_notes: list[dict] = []
    for item in requirement_handoff.get("scope_index_consumption") or []:
        if not isinstance(item, dict) or str(item.get("result") or "").strip() != "converted_to_function_points":
            continue
        source_id = str(item.get("source_id") or "").strip()
        expected_fp_ids = fp_ids_by_source.get(source_id) or []
        current_fp_ids = [str(fp_id or "").strip() for fp_id in item.get("fp_ids") or [] if str(fp_id or "").strip()]
        valid_fp_ids = [fp_id for fp_id in current_fp_ids if fp_id in expected_fp_ids]
        if valid_fp_ids == current_fp_ids and valid_fp_ids:
            continue
        item["fp_ids"] = list(expected_fp_ids)
        repair_notes.append({
            "severity": "warning",
            "code": "CONSUMPTION_FP_REFS_REPAIRED",
            "source_id": source_id,
            "message": f"{source_id} 的功能点消费回执已按实际 source 归属修复",
        })
    if repair_notes:
        requirement_handoff.setdefault("normalization_notes", []).extend(repair_notes)
    return _repair_pending_confirmation_fp_refs(requirement_handoff)


def _build_trusted_requirement_handoff_by_source_batches(
    scope_index: dict,
    sections: list[dict],
    image_analysis: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
    progress_callback=None,
) -> dict:
    sources = _trusted_scope_source_items(scope_index)
    batch_size = 4
    batch_count = max((len(sources) + batch_size - 1) // batch_size, 1)
    concurrency = min(_REQUIREMENT_BATCH_CONCURRENCY, batch_count)
    started_at = time.perf_counter()
    merged = {
        "scope_index_consumption": [],
        "function_points": [],
        "pending_confirmations": [],
    }

    if progress_callback:
        progress_callback(
            f"需求分析策略：source_batches_full，source {len(sources)} 个，"
            f"批次 {batch_count}，并发 {concurrency}"
        )

    source_batches = [
        (index, sources[start:start + batch_size])
        for index, start in enumerate(range(0, len(sources), batch_size), start=1)
    ]

    def run_batch(batch_index: int, batch_sources: list[dict]) -> dict:
        batch_source_ids = [str(item.get("source_id") or "").strip() for item in batch_sources if isinstance(item, dict)]
        batch_scope_index = _source_batch_scope_index(scope_index, batch_sources)
        batch_sections = _source_batch_sections(batch_sources, sections)
        payload = {
            "task": "基于当前 source 批次生成功能点，并记录每个 source 是否被消费。只输出 JSON。",
            "schema": {
                "scope_index_consumption": [
                    {"source_id": "SRC-001", "result": "converted_to_function_points", "fp_ids": ["FP-001"], "note": ""}
                ],
                "function_points": [
                    {
                        "fp_id": "FP-001",
                        "source_id": "SRC-001",
                        "shard_id": "SHARD-SRC-001",
                        "source_order": "1",
                        "title_path": "一级标题 > 二级标题",
                        "source_title": "",
                        "title": "",
                        "description": "",
                        "rules": [],
                        "test_hints": [],
                        "priority_hint": "P0|P1|P2|P3",
                        "coverage_intent": "positive|boundary|negative|ui|state|permission",
                        "merge_allowed": False,
                        "source_refs": [],
                        "source_quotes": ["从 source.source_excerpt 逐字复制的需求原文"],
                        "target_evidence_refs": ["IMG-001"],
                    }
                ],
                "pending_confirmations": [],
            },
            "rules": [
                "只能处理 scope_index.direct_testcase_sources 中的 source_id，不要生成批次外 source",
                "每个 direct source 必须在 scope_index_consumption 中出现一次",
                "每个 function_point 必须有 source_id，且必须继承对应 source 的 shard_id、source_order、title_path",
                "同一 source 下的正常、边界、异常、权限等规则优先合并为同一功能点的 rules/test_hints，不要按测试类型机械拆分",
                "如果 source 被合并或阻塞，必须在 note 中说明原因",
                "每个 function_point.source_quotes 必须逐字复制对应 source.source_excerpt 中直接支持该功能点的原文；禁止改写或概括",
                "只允许使用当前 source.source_excerpt 和 image_evidence；不要引用其他 source 的图片或自行推断具体验收标准",
                "需求未明确具体结果时写入 pending_confirmations，不得自行补全",
                "source_state_semantics.has_state_transition=true 时，current 只表示改造前状态；功能点必须由 target_text 或 target_image_refs 支撑",
                "目标仅在图片中时必须填写 target_evidence_refs，禁止把 current 的旧位置、旧样式或旧行为写成目标规则",
            ],
            "scope_index": batch_scope_index,
            "sections": _compact_sections_for_ai(batch_sections, per_section_limit=1400, total_limit=9000),
            "image_analysis": [
                evidence
                for source in batch_sources
                for evidence in source.get("image_evidence") or []
            ],
        }
        raw = _call_trusted_skill_json(
            skill_name="requirement-analyzer",
            payload=payload,
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=6500,
            timeout_seconds=_DEFAULT_CHAT_TIMEOUT_SECONDS,
        )
        if not isinstance(raw, dict):
            raise ValueError("requirement_handoff 模型输出必须是 JSON 对象")
        return _normalize_trusted_requirement_handoff(batch_scope_index, raw)

    batch_results_by_index: dict[int, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        if progress_callback:
            for batch_index, batch_sources in source_batches:
                batch_source_ids = [str(item.get("source_id") or "").strip() for item in batch_sources if isinstance(item, dict)]
                progress_callback(
                    f"需求分析 source 批次 {batch_index}/{batch_count} 已提交："
                    f"{', '.join(batch_source_ids) or '-'}"
                )
        future_to_index = {
            executor.submit(contextvars.copy_context().run, run_batch, batch_index, batch_sources): batch_index
            for batch_index, batch_sources in source_batches
        }
        for completed_count, future in enumerate(concurrent.futures.as_completed(future_to_index), start=1):
            batch_index = future_to_index[future]
            batch_results_by_index[batch_index] = future.result()
            completed_fp_count = sum(len(item.get("function_points") or []) for item in batch_results_by_index.values())
            elapsed = time.perf_counter() - started_at
            avg = elapsed / completed_count
            remaining = max(batch_count - completed_count, 0)
            if progress_callback:
                progress_callback(
                    f"需求分析批次 {completed_count}/{batch_count} 已完成"
                    f"（刚完成第 {batch_index} 批），累计 {completed_fp_count} 个功能点，"
                    f"预计剩余 {_format_duration_zh(avg * remaining)}"
                )

    for batch_index in range(1, batch_count + 1):
        normalized = batch_results_by_index[batch_index]
        merged["scope_index_consumption"].extend(normalized.get("scope_index_consumption") or [])
        merged["function_points"].extend(normalized.get("function_points") or [])
        merged["pending_confirmations"].extend(normalized.get("pending_confirmations") or [])

    if progress_callback:
        progress_callback(
            f"需求分析批次合并中：{batch_count} 批全部完成，耗时 {_format_duration_zh(time.perf_counter() - started_at)}"
        )

    return _repair_converted_requirement_consumption(
        _renumber_trusted_requirement_handoff(_normalize_trusted_requirement_handoff(scope_index, merged))
    )


def _normalize_trusted_requirement_handoff(scope_index: dict, raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("requirement_handoff 必须是 JSON 对象")
    raw.setdefault("scope_index_consumption", [])
    raw.setdefault("function_points", [])
    raw.setdefault("pending_confirmations", [])
    source_by_id = _trusted_source_by_id(scope_index)
    normalized_fps: list[dict] = []
    for index, fp in enumerate(raw.get("function_points") or [], start=1):
        if not isinstance(fp, dict):
            normalized_fps.append(fp)
            continue
        item = dict(fp)
        source_id = str(item.get("source_id") or "").strip()
        source = source_by_id.get(source_id)
        if source:
            item["source_id"] = source_id
            item["shard_id"] = source.get("shard_id") or item.get("shard_id") or f"SHARD-{source_id}"
            item["source_order"] = source.get("source_order", item.get("source_order", index))
            item["source_order_index"] = source.get("source_order_index", item.get("source_order_index", index))
            item["title_path"] = source.get("title_path") or item.get("title_path") or source.get("title") or ""
            item["source_title"] = source.get("title") or item.get("source_title") or item.get("title") or ""
            item["module"] = source.get("module") or item.get("module") or item["source_title"]
            item["scene"] = source.get("scene") or item.get("scene") or item["source_title"]
            item["xmind_source_node"] = source.get("xmind_source_node") or item.get("xmind_source_node") or f"{source_id}｜{item['title_path']}"
            item["source_doc_id"] = source.get("source_doc_id") or ""
            item["source_excerpt"] = source.get("source_excerpt") or ""
            item["source_content_sha256"] = source.get("source_content_sha256") or ""
            item["image_refs"] = list(source.get("image_refs") or [])
            item["image_evidence"] = list(source.get("image_evidence") or [])
            item["source_state_semantics"] = dict(source.get("source_state_semantics") or {}) if isinstance(source.get("source_state_semantics"), dict) else {}
            item["source_refs"] = list(source.get("evidence_refs") or ([source.get("source_doc_id")] if source.get("source_doc_id") else []))
        for key in ("rules", "test_hints", "source_refs", "source_quotes", "target_evidence_refs"):
            if not isinstance(item.get(key), list):
                item[key] = [] if item.get(key) in (None, "") else [str(item.get(key))]
        if source and item.get("source_quotes"):
            item["source_quotes"] = [
                _resolve_requirement_source_quote(item.get("source_excerpt") or "", value)
                for value in item["source_quotes"]
                if str(value or "").strip()
            ]
        if source:
            target_refs = {
                str(value).strip()
                for value in (source.get("source_state_semantics") or {}).get("target_image_refs") or []
                if str(value).strip()
            }
            item["target_evidence_refs"] = [
                str(value).strip()
                for value in item.get("target_evidence_refs") or []
                if str(value).strip() in target_refs
            ]
            item["source_quote_roles"] = [
                {
                    "source_quote": quote,
                    "evidence_role": _source_evidence_role(
                        source,
                        basis_type="text",
                        source_quote=quote,
                    ),
                }
                for quote in item.get("source_quotes") or []
            ]
        normalized_fps.append(item)
    raw["function_points"] = normalized_fps
    _repair_pending_confirmation_fp_refs(raw)
    raw["generation_contract_version"] = _TRUSTED_GENERATION_CONTRACT_VERSION
    raw["scope_fingerprint"] = _trusted_scope_fingerprint(scope_index)
    return raw


def _validate_trusted_requirement_handoff(scope_index: dict, requirement_handoff: dict) -> dict:
    source_ids = _trusted_v2_source_ids(scope_index)
    source_by_id = _trusted_source_by_id(scope_index)
    consumptions = requirement_handoff.get("scope_index_consumption") or []
    function_points = requirement_handoff.get("function_points") or []
    issues: list[dict] = []
    consumed_ids = {
        str(item.get("source_id") or "").strip()
        for item in consumptions
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    }
    for source_id in sorted(source_ids - consumed_ids):
        issues.append({"severity": "blocker", "code": "SOURCE_NOT_CONSUMED", "message": f"{source_id} 未出现在 scope_index_consumption"})
    for item in consumptions:
        if not isinstance(item, dict):
            issues.append({"severity": "blocker", "code": "BAD_CONSUMPTION_ITEM", "message": "scope_index_consumption 包含非对象项"})
            continue
        source_id = str(item.get("source_id") or "").strip()
        result = str(item.get("result") or "").strip()
        if source_id not in source_ids:
            issues.append({"severity": "blocker", "code": "UNKNOWN_SOURCE_CONSUMED", "message": f"{source_id} 不在 scope_index 中"})
        if result not in _TRUSTED_REQUIREMENT_RESULTS:
            issues.append({"severity": "blocker", "code": "BAD_CONSUMPTION_RESULT", "message": f"{source_id} result 非法：{result}"})
        if result in {"blocked_by_pending_confirmation", "not_applicable", "merged"} and not str(item.get("note") or "").strip():
            issues.append({"severity": "blocker", "code": "MISSING_CONSUMPTION_NOTE", "message": f"{source_id} 未覆盖/合并但缺少说明"})
    known_fp_ids: set[str] = set()
    fp_source_by_id: dict[str, str] = {}
    for fp in function_points:
        if not isinstance(fp, dict):
            issues.append({"severity": "blocker", "code": "BAD_FP_ITEM", "message": "function_points 包含非对象项"})
            continue
        fp_id = str(fp.get("fp_id") or "").strip()
        source_id = str(fp.get("source_id") or "").strip()
        if not fp_id:
            issues.append({"severity": "blocker", "code": "FP_MISSING_ID", "message": "功能点缺少 fp_id"})
        elif fp_id in known_fp_ids:
            issues.append({"severity": "blocker", "code": "FP_DUPLICATE_ID", "message": f"功能点重复：{fp_id}"})
        if fp_id:
            known_fp_ids.add(fp_id)
            fp_source_by_id[fp_id] = source_id
        if not source_id:
            issues.append({"severity": "blocker", "code": "FP_MISSING_SOURCE", "message": f"{fp_id or '未知 FP'} 缺少 source_id"})
        elif source_id not in source_ids:
            issues.append({"severity": "blocker", "code": "FP_UNKNOWN_SOURCE", "message": f"{fp_id} 引用了未知 source_id：{source_id}"})
        else:
            source = source_by_id.get(source_id) or {}
            expected_shard_id = str(source.get("shard_id") or f"SHARD-{source_id}").strip()
            actual_shard_id = str(fp.get("shard_id") or "").strip()
            if not actual_shard_id:
                issues.append({"severity": "blocker", "code": "FP_MISSING_SHARD", "message": f"{fp_id} 缺少 shard_id"})
            elif actual_shard_id != expected_shard_id:
                issues.append({"severity": "blocker", "code": "FP_SHARD_MISMATCH", "message": f"{fp_id} shard_id 应为 {expected_shard_id}，实际为 {actual_shard_id}"})
            expected_title_path = str(source.get("title_path") or source.get("title") or "").strip()
            actual_title_path = str(fp.get("title_path") or "").strip()
            if not actual_title_path:
                issues.append({"severity": "blocker", "code": "FP_MISSING_TITLE_PATH", "message": f"{fp_id} 缺少 title_path"})
            elif expected_title_path and actual_title_path != expected_title_path:
                issues.append({"severity": "blocker", "code": "FP_TITLE_PATH_MISMATCH", "message": f"{fp_id} title_path 与 source 不一致"})
            expected_order = str(source.get("source_order") or "").strip()
            actual_order = str(fp.get("source_order") or "").strip()
            if not actual_order:
                issues.append({"severity": "blocker", "code": "FP_MISSING_SOURCE_ORDER", "message": f"{fp_id} 缺少 source_order"})
            elif expected_order and actual_order != expected_order:
                issues.append({"severity": "blocker", "code": "FP_SOURCE_ORDER_MISMATCH", "message": f"{fp_id} source_order 与 source 不一致"})
            source_excerpt = _normalize_requirement_quote(source.get("source_excerpt") or "")
            if source_excerpt:
                source_quotes = [
                    str(value or "").strip()
                    for value in fp.get("source_quotes") or []
                    if str(value or "").strip()
                ]
                if not source_quotes:
                    issues.append({"severity": "blocker", "code": "FP_SOURCE_QUOTES_MISSING", "message": f"{fp_id} 缺少逐字需求原文引用"})
                for quote in source_quotes:
                    normalized_quote = _normalize_requirement_quote(quote)
                    if normalized_quote not in source_excerpt:
                        issues.append({"severity": "blocker", "code": "FP_SOURCE_QUOTE_NOT_FOUND", "message": f"{fp_id} 的原文引用不在 {source_id} 需求正文中"})
                state_semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
                if state_semantics.get("has_state_transition"):
                    target_image_refs = {
                        str(value).strip()
                        for value in state_semantics.get("target_image_refs") or []
                        if str(value).strip()
                    }
                    claimed_target_refs = {
                        str(value).strip()
                        for value in fp.get("target_evidence_refs") or []
                        if str(value).strip()
                    }
                    unknown_target_refs = sorted(claimed_target_refs - target_image_refs)
                    if unknown_target_refs:
                        issues.append({
                            "severity": "blocker",
                            "code": "FP_TARGET_EVIDENCE_INVALID",
                            "message": f"{fp_id} target_evidence_refs 不属于 {source_id} 的优化后证据：{', '.join(unknown_target_refs)}",
                        })
                    target_text_quotes = [
                        quote
                        for quote in source_quotes
                        if not _is_state_label_only(quote)
                        and _source_evidence_role(source, basis_type="text", source_quote=quote) == "target"
                    ]
                    if not target_text_quotes and not claimed_target_refs:
                        issues.append({
                            "severity": "blocker",
                            "code": "FP_TARGET_EVIDENCE_MISSING",
                            "message": f"{fp_id} 只描述改造前状态或目标证据未绑定，必须引用 target 文本/图片或转待确认",
                        })
                    state_conflicts = _state_target_conflicts(
                        source,
                        "\n".join([
                            str(fp.get("title") or ""),
                            str(fp.get("description") or ""),
                            *[str(value or "") for value in fp.get("rules") or []],
                            *[str(value or "") for value in fp.get("test_hints") or []],
                        ]),
                    )
                    if state_conflicts:
                        issues.append({
                            "severity": "blocker",
                            "code": "FP_CURRENT_STATE_CONTRADICTS_TARGET",
                            "source_id": source_id,
                            "message": f"{fp_id} 仍使用 current 旧状态，和 target 证据冲突：{state_conflicts[0]['attribute']}",
                        })
    for item in consumptions:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        result = str(item.get("result") or "").strip()
        referenced_fp_ids = item.get("fp_ids") or []
        if result == "converted_to_function_points" and not referenced_fp_ids:
            issues.append({"severity": "blocker", "code": "CONSUMPTION_MISSING_FP_IDS", "message": f"{source_id} 标记为已转功能点但 fp_ids 为空"})
        if referenced_fp_ids and not isinstance(referenced_fp_ids, list):
            issues.append({"severity": "blocker", "code": "CONSUMPTION_FP_IDS_BAD_TYPE", "message": f"{source_id} fp_ids 必须是数组"})
            continue
        for fp_id in referenced_fp_ids:
            fp_id_text = str(fp_id).strip()
            if fp_id_text and fp_id_text not in known_fp_ids:
                issues.append({"severity": "blocker", "code": "CONSUMPTION_UNKNOWN_FP_ID", "message": f"{source_id} 回执引用了不存在的功能点：{fp_id_text}"})
            elif fp_id_text and result == "converted_to_function_points" and fp_source_by_id.get(fp_id_text) != source_id:
                issues.append({
                    "severity": "blocker",
                    "code": "CONSUMPTION_FP_SOURCE_MISMATCH",
                    "message": f"{source_id} 回执引用了其他 source 的功能点：{fp_id_text}",
                })
    for item in requirement_handoff.get("pending_confirmations") or []:
        if not isinstance(item, dict):
            issues.append({"severity": "blocker", "code": "BAD_PENDING_CONFIRMATION", "message": "pending_confirmations 包含非对象项"})
            continue
        source_id = str(item.get("source_id") or "").strip()
        related_fp_ids = item.get("related_fp_ids") or []
        if not isinstance(related_fp_ids, list):
            issues.append({"severity": "blocker", "code": "PENDING_FP_IDS_BAD_TYPE", "message": f"{source_id or '未知 source'} related_fp_ids 必须是数组"})
            continue
        for fp_id in related_fp_ids:
            fp_id_text = str(fp_id or "").strip()
            if fp_id_text not in known_fp_ids:
                issues.append({
                    "severity": "blocker",
                    "code": "PENDING_UNKNOWN_FP_ID",
                    "message": f"{source_id or '未知 source'} 待确认项引用了不存在的功能点：{fp_id_text or '空'}",
                })
            elif source_id and fp_source_by_id.get(fp_id_text) != source_id:
                issues.append({
                    "severity": "blocker",
                    "code": "PENDING_FP_SOURCE_MISMATCH",
                    "message": f"{source_id} 待确认项引用了其他 source 的功能点：{fp_id_text}",
                })
    return {
        "gate": "requirement_gate",
        "passed": not any(item["severity"] == "blocker" for item in issues),
        "issues": issues,
        "source_count": len(source_ids),
        "function_point_count": len([item for item in function_points if isinstance(item, dict)]),
    }


def _source_requirement_needs_state_repair(source: dict, function_points: list[dict]) -> bool:
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    if not semantics.get("has_state_transition"):
        return False
    profile = source.get("test_design_profile") if isinstance(source.get("test_design_profile"), dict) else {}
    source_candidate_text = "\n".join([
        str(source.get("smoking_scope_note") or source.get("smoke_test_scope_note") or ""),
        *[str(value or "") for value in profile.get("must_cover") or []],
    ])
    if _state_target_conflicts(source, source_candidate_text):
        return True
    valid_target_refs = {
        str(value).strip()
        for value in semantics.get("target_image_refs") or []
        if str(value).strip()
    }
    for fp in function_points:
        if not isinstance(fp, dict):
            continue
        target_text_quotes = [
            quote
            for quote in fp.get("source_quotes") or []
            if not _is_state_label_only(quote)
            and _source_evidence_role(source, basis_type="text", source_quote=quote) == "target"
        ]
        target_refs = {
            str(value).strip()
            for value in fp.get("target_evidence_refs") or []
            if str(value).strip() in valid_target_refs
        }
        if not target_text_quotes and not target_refs:
            return True
        fp_candidate_text = "\n".join([
            str(fp.get("title") or ""),
            str(fp.get("description") or ""),
            *[str(value or "") for value in fp.get("rules") or []],
            *[str(value or "") for value in fp.get("test_hints") or []],
        ])
        if _state_target_conflicts(source, fp_candidate_text):
            return True
    return False


def _replace_trusted_scope_source(scope_index: dict, source: dict) -> dict:
    updated = json.loads(json.dumps(scope_index, ensure_ascii=False))
    source_id = str(source.get("source_id") or "").strip()
    evidence_keys = (
        "source_doc_id",
        "source_excerpt",
        "source_content_sha256",
        "image_refs",
        "image_evidence",
        "source_state_semantics",
        "evidence_refs",
    )
    for block in updated.get("source_blocks") or []:
        if not isinstance(block, dict) or str(block.get("block_id") or block.get("source_id") or "").strip() != source_id:
            continue
        for key in evidence_keys:
            block[key] = source.get(key)
    for shard in updated.get("shards") or []:
        if not isinstance(shard, dict) or str(shard.get("direct_testcase_source") or shard.get("source_id") or "").strip() != source_id:
            continue
        for key in evidence_keys:
            shard[key] = source.get(key)
        shard["test_design_profile"] = source.get("test_design_profile") or shard.get("test_design_profile") or {}
        shard["smoke_test_scope_note"] = source.get("smoking_scope_note") or shard.get("smoke_test_scope_note") or ""
    for item in updated.get("direct_testcase_sources") or []:
        if not isinstance(item, dict) or str(item.get("source_id") or "").strip() != source_id:
            continue
        item.update(source)
    updated["generation_contract_version"] = _TRUSTED_GENERATION_CONTRACT_VERSION
    return updated


def _replace_trusted_requirement_source(
    scope_index: dict,
    requirement_handoff: dict,
    source_id: str,
    function_points: list[dict],
    pending_confirmations: list[dict] | None = None,
) -> dict:
    updated = json.loads(json.dumps(requirement_handoff, ensure_ascii=False))
    all_fps = [item for item in updated.get("function_points") or [] if isinstance(item, dict)]
    first_index = next(
        (index for index, item in enumerate(all_fps) if str(item.get("source_id") or "").strip() == source_id),
        len(all_fps),
    )
    retained = [item for item in all_fps if str(item.get("source_id") or "").strip() != source_id]
    updated["function_points"] = retained[:first_index] + function_points + retained[first_index:]
    fp_ids = [str(item.get("fp_id") or "").strip() for item in function_points if str(item.get("fp_id") or "").strip()]
    for receipt in updated.get("scope_index_consumption") or []:
        if isinstance(receipt, dict) and str(receipt.get("source_id") or "").strip() == source_id:
            receipt["result"] = "converted_to_function_points"
            receipt["fp_ids"] = fp_ids
            receipt["note"] = "current/target 证据角色修复后重新生成"
    retained_pending = [
        item
        for item in updated.get("pending_confirmations") or []
        if not isinstance(item, dict) or str(item.get("source_id") or item.get("ref_id") or "").strip() != source_id
    ]
    updated["pending_confirmations"] = retained_pending + [
        item for item in pending_confirmations or [] if isinstance(item, dict)
    ]
    return _normalize_trusted_requirement_handoff(scope_index, updated)


def _repair_trusted_state_transition_source_bundle(
    scope_index: dict,
    requirement_handoff: dict,
    source_id: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> tuple[dict, dict, dict, list[dict]]:
    source = _source_by_id(scope_index, source_id)
    existing_fps = [
        item
        for item in requirement_handoff.get("function_points") or []
        if isinstance(item, dict) and str(item.get("source_id") or "").strip() == source_id
    ]
    if not _source_requirement_needs_state_repair(source, existing_fps):
        return scope_index, requirement_handoff, source, existing_fps
    payload = {
        "task": "修复当前 source 的 current/target 语义，只输出 JSON。保持功能点数量和 fp_id 不变。",
        "schema": {
            "smoke_test_scope_note": "只描述 target 的核心回归目标",
            "test_design_profile": {
                "applicable_methods": ["ui_display"],
                "risk_signals": [],
                "must_cover": ["target 中可直接观察的义务"],
                "merge_allowed": [],
                "not_applicable": [],
                "coverage_budget": {"guidance": "按 target 义务生成最小可解释用例集"},
            },
            "function_points": [{
                "fp_id": "FP-001",
                "source_id": source_id,
                "title": "target 功能点",
                "description": "只描述优化后状态",
                "rules": [],
                "test_hints": [],
                "priority_hint": "P1|P2",
                "coverage_intent": "ui|positive|negative|state",
                "merge_allowed": False,
                "source_refs": [],
                "source_quotes": ["逐字 target 原文；目标仅在图片时可只引用状态标签"],
                "target_evidence_refs": ["IMG-001"],
            }],
            "pending_confirmations": [],
        },
        "rules": [
            "current_text/current_image_refs 是改造前状态，只能作为对比或不再出现的回归依据",
            "所有 must_cover、description、rules、test_hints 必须描述 target，禁止把 current 的旧位置、旧样式、旧行为写成优化结果",
            "target 只有图片时，必须逐项引用 target_image_refs，并依据对应 image_evidence 写出可观察目标",
            "source_quotes 必须逐字来自 source_excerpt；纯图片目标允许引用‘优化效果/正确场景’标签，同时 target_evidence_refs 必须非空",
            "保持 function_points 数量与 existing_function_points 一致；不得新增或删除 FP",
        ],
        "source": source,
        "existing_function_points": existing_fps,
    }
    raw = _call_trusted_skill_json(
        skill_name="requirement-analyzer",
        payload=payload,
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tokens=5000,
        timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
    )
    if isinstance(raw, dict):
        candidate_text = "\n".join([
            str(raw.get("smoke_test_scope_note") or ""),
            *[str(value or "") for value in (raw.get("test_design_profile") or {}).get("must_cover") or []],
            *[
                str(value or "")
                for fp in raw.get("function_points") or []
                if isinstance(fp, dict)
                for value in [fp.get("title"), fp.get("description"), *(fp.get("rules") or []), *(fp.get("test_hints") or [])]
            ],
        ])
        conflicts = _state_target_conflicts(source, candidate_text)
        if conflicts:
            repair_payload = dict(payload)
            repair_payload["task"] = "上一次 current/target 修复仍复用了旧状态。根据冲突清单重新输出完整 JSON。"
            repair_payload["previous_invalid_output"] = raw
            repair_payload["deterministic_conflicts"] = conflicts
            repair_payload["rules"] = [
                *payload["rules"],
                "deterministic_conflicts 中 current_values 是禁止继续作为目标的旧值，必须改为 target_values",
                "重写 smoke_test_scope_note、must_cover、description、rules、test_hints，确保不再包含冲突旧值",
            ]
            raw = _call_trusted_skill_json(
                skill_name="requirement-analyzer",
                payload=repair_payload,
                api_key=api_key,
                model=model,
                base_url=base_url,
                max_tokens=5000,
                timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
            )
    repaired_fps = [item for item in raw.get("function_points") or [] if isinstance(item, dict)] if isinstance(raw, dict) else []
    if not existing_fps or len(repaired_fps) != len(existing_fps):
        raise ModelContractError(
            f"{source_id} current/target 局部修复必须保持 {len(existing_fps)} 个功能点，模型返回 {len(repaired_fps)} 个"
        )
    repaired_source = dict(source)
    repaired_source["smoking_scope_note"] = str(raw.get("smoke_test_scope_note") or "").strip()
    repaired_source["test_design_profile"] = _normalize_test_design_profile(raw.get("test_design_profile"), source)
    updated_scope = _replace_trusted_scope_source(scope_index, repaired_source)
    scope_gate = _validate_trusted_scope_index(updated_scope)
    if not scope_gate.get("passed"):
        source_messages = [
            str(item.get("message") or "")
            for item in scope_gate.get("issues") or []
            if item.get("severity") == "blocker" and (item.get("source_id") == source_id or source_id in str(item.get("message") or ""))
        ]
        if source_messages:
            raise ModelContractError(f"{source_id} current/target 范围义务修复未通过：{'；'.join(source_messages[:3])}")
    for index, fp in enumerate(repaired_fps):
        fp["fp_id"] = existing_fps[index].get("fp_id")
        fp["source_id"] = source_id
    updated_requirement = _replace_trusted_requirement_source(
        updated_scope,
        requirement_handoff,
        source_id,
        repaired_fps,
        raw.get("pending_confirmations") if isinstance(raw.get("pending_confirmations"), list) else [],
    )
    requirement_gate = _validate_trusted_requirement_handoff(updated_scope, updated_requirement)
    if not requirement_gate.get("passed"):
        messages = [
            str(item.get("message") or "")
            for item in requirement_gate.get("issues") or []
            if item.get("severity") == "blocker" and (source_id in str(item.get("message") or "") or str(item.get("message") or "").startswith("FP-"))
        ]
        raise ModelContractError(f"{source_id} current/target 功能点修复未通过需求门禁：{'；'.join(messages[:3]) or '字段不完整'}")
    return updated_scope, updated_requirement, _source_by_id(updated_scope, source_id), [
        item
        for item in updated_requirement.get("function_points") or []
        if isinstance(item, dict) and str(item.get("source_id") or "").strip() == source_id
    ]


def _normalize_trusted_testcase_handoff(raw: dict, source_id: str, *, source: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"{source_id} testcase_handoff 模型输出必须是 JSON 对象")
    raw.setdefault("requirements_input_consumption", [])
    raw.setdefault("feature_point_consumption", [])
    raw.setdefault("method_consumption", [])
    raw.setdefault("testcases", [])
    if not isinstance(raw.get("feature_point_consumption"), list):
        raise ValueError(f"{source_id} feature_point_consumption 必须是数组")
    if not isinstance(raw.get("method_consumption"), list):
        raise ValueError(f"{source_id} method_consumption 必须是数组")
    if not isinstance(raw.get("testcases"), list):
        raise ValueError(f"{source_id} testcases 必须是数组")
    source_number = source_id.removeprefix("SRC-").zfill(3) if source_id else ""
    authoritative_shard_id = str(
        (source or {}).get("shard_id")
        or raw.get("shard_id")
        or (f"SHARD-{source_number}" if source_number else "")
    ).strip()
    if authoritative_shard_id:
        raw["shard_id"] = authoritative_shard_id
    for item in raw.get("feature_point_consumption") or []:
        if isinstance(item, dict):
            item["source_id"] = str(item.get("source_id") or source_id).strip()
            if authoritative_shard_id:
                item["shard_id"] = authoritative_shard_id
            result = str(item.get("consumption_result") or item.get("result") or "").strip()
            item["consumption_result"] = result
            item["result"] = result
            refs = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids")
            refs = refs if isinstance(refs, list) else []
            item["case_refs"] = refs
            item["case_ids"] = refs
            item.setdefault("reason", item.get("merge_reason") or item.get("note") or "")
            item.setdefault("merge_reason", item.get("reason") or "")
    for item in raw.get("method_consumption") or []:
        if isinstance(item, dict):
            item["source_id"] = str(item.get("source_id") or source_id).strip()
            item["shard_id"] = authoritative_shard_id or str(item.get("shard_id") or "").strip()
            result = str(item.get("consumption_result") or item.get("result") or "").strip()
            item["consumption_result"] = result
            item["result"] = result
            refs = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids")
            refs = refs if isinstance(refs, list) else []
            item["case_refs"] = refs
            item["case_ids"] = refs
            item.setdefault("reason", item.get("merge_reason") or item.get("note") or "")
    for item in raw.get("testcases") or []:
        if isinstance(item, dict):
            item["source_id"] = str(item.get("source_id") or source_id).strip()
            if authoritative_shard_id:
                item["shard_id"] = authoritative_shard_id
            if item.get("design_method") and not isinstance(item.get("generation_basis"), dict):
                item["generation_basis"] = {"method": item.get("design_method")}
            primary_method = str(
                item.get("design_method")
                or (item.get("generation_basis") or {}).get("method")
                or ""
            ).strip()
            design_methods = item.get("design_methods") if isinstance(item.get("design_methods"), list) else []
            item["design_methods"] = list(dict.fromkeys([
                *([primary_method] if primary_method else []),
                *[str(value).strip() for value in design_methods if str(value).strip()],
            ]))
            if primary_method:
                item["design_method"] = primary_method
            traceability = item.get("traceability") if isinstance(item.get("traceability"), dict) else {}
            traceability["source_id"] = item["source_id"]
            item["traceability"] = traceability
            must_cover_refs = item.get("must_cover_refs")
            item["must_cover_refs"] = (
                [str(value).strip() for value in must_cover_refs if str(value).strip()]
                if isinstance(must_cover_refs, list)
                else []
            )
            item["test_data"] = _coerce_test_data(item.get("test_data"))
            item["assertion_basis"] = [
                dict(value)
                for value in item.get("assertion_basis") or []
                if isinstance(value, dict)
            ]
            if source:
                for basis in item["assertion_basis"]:
                    basis["evidence_role"] = _source_evidence_role(
                        source,
                        basis_type=str(basis.get("basis_type") or "").strip(),
                        basis_ref=str(basis.get("basis_ref") or "").strip(),
                        source_quote=str(basis.get("source_quote") or "").strip(),
                    )
                authoritative_refs = [str(value).strip() for value in source.get("evidence_refs") or [] if str(value).strip()]
                claimed_refs = [str(value).strip() for value in item.get("evidence_refs") or [] if str(value).strip()]
                item["invalid_evidence_refs"] = sorted(set(claimed_refs) - set(authoritative_refs))
                item["evidence_refs"] = list(dict.fromkeys([
                    *([source.get("source_doc_id")] if source.get("source_doc_id") else []),
                    *[value for value in claimed_refs if value in authoritative_refs],
                ]))
    case_by_id = {
        str(item.get("case_id") or "").strip(): item
        for item in raw.get("testcases") or []
        if isinstance(item, dict) and str(item.get("case_id") or "").strip()
    }
    # Preserve the explicit many-to-many method receipts instead of losing all
    # but the legacy primary design_method value.
    for receipt in raw.get("method_consumption") or []:
        if not isinstance(receipt, dict):
            continue
        result = str(receipt.get("consumption_result") or receipt.get("result") or "").strip()
        method = str(receipt.get("method") or "").strip()
        refs = receipt.get("case_refs") if isinstance(receipt.get("case_refs"), list) else receipt.get("case_ids")
        if result != "covered_by_case" or not method or not isinstance(refs, list):
            continue
        for case_id in refs:
            case = case_by_id.get(str(case_id).strip())
            if case is not None:
                case["design_methods"] = list(dict.fromkeys([*(case.get("design_methods") or []), method]))
    return raw


_TEST_DATA_REQUIRED_METHODS = {"boundary", "boundary_value", "decision_table", "state_transition"}
_NAVIGATION_SELECTION_PATTERN = re.compile(
    r"选择[^，。,；;]*(?:tab|页签|页面|模块|菜单|按钮)(?=[，。,；;]|后|并|展开|收起|查看|检查|$)",
    re.IGNORECASE,
)


def _case_requires_executable_test_data(case: dict) -> bool:
    methods = {
        str(value).strip()
        for value in case.get("design_methods") or []
        if str(value).strip()
    }
    primary_method = str(
        case.get("design_method")
        or (case.get("generation_basis") or {}).get("method")
        or ""
    ).strip()
    if primary_method:
        methods.add(primary_method)
    if methods & _TEST_DATA_REQUIRED_METHODS:
        return True
    actions = " ".join(_step_to_text(step) for step in case.get("steps") or [])
    if _text_contains_any(actions, ("输入", "填写", "上传", "搜索", "导出", "保存")):
        return True
    business_selection_text = _NAVIGATION_SELECTION_PATTERN.sub("", actions)
    return "选择" in business_selection_text


def _build_trusted_testcase_source_shard(
    source: dict,
    function_points: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    return asyncio.run(_build_trusted_testcase_source_shard_async(source, function_points, api_key=api_key, model=model, base_url=base_url))


def _validate_trusted_source_shard_contract(source: dict, function_points: list[dict], shard: dict) -> None:
    source_id = str(source.get("source_id") or "").strip()
    expected_shard_id = str(source.get("shard_id") or f"SHARD-{source_id.removeprefix('SRC-').zfill(3)}").strip()
    strict_evidence_contract = bool(str(source.get("source_doc_id") or "").strip() or str(source.get("source_excerpt") or "").strip())
    source_fp_ids = {
        str(item.get("fp_id") or "").strip()
        for item in function_points
        if isinstance(item, dict) and str(item.get("fp_id") or "").strip()
    }
    testcases = [item for item in shard.get("testcases") or [] if isinstance(item, dict)]
    local_case_ids = {str(item.get("case_id") or "").strip() for item in testcases if str(item.get("case_id") or "").strip()}
    local_case_methods = {
        str(item.get("case_id") or "").strip(): {
            *[str(value).strip() for value in item.get("design_methods") or [] if str(value).strip()],
            *([str(item.get("design_method") or "").strip()] if str(item.get("design_method") or "").strip() else []),
        }
        for item in testcases
        if str(item.get("case_id") or "").strip()
    }
    if source_fp_ids and not testcases:
        raise ModelContractError(f"{source_id} 分片模型输出没有 testcases，但存在 {len(source_fp_ids)} 个待覆盖功能点")
    for case in testcases:
        case_id = str(case.get("case_id") or "").strip()
        case_source_id = str(case.get("source_id") or source_id).strip()
        if case_source_id != source_id:
            raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 引用了其他 source：{case_source_id}")
        if str(case.get("shard_id") or "").strip() != expected_shard_id:
            raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} shard_id 未继承权威值 {expected_shard_id}")
        case_fp_ids = case.get("fp_ids") if isinstance(case.get("fp_ids"), list) else []
        if case.get("fp_id"):
            case_fp_ids = list(case_fp_ids) + [case.get("fp_id")]
        unknown_fp_ids = sorted({str(item).strip() for item in case_fp_ids if str(item).strip()} - source_fp_ids)
        if unknown_fp_ids:
            raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 引用了非本 source 功能点：{', '.join(unknown_fp_ids)}")
        if strict_evidence_contract and case.get("invalid_evidence_refs"):
            raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 引用了非本 source 证据：{', '.join(case['invalid_evidence_refs'])}")
        expected_results = [str(value).strip() for value in case.get("expected_results") or [] if str(value).strip()]
        assertion_basis = [item for item in case.get("assertion_basis") or [] if isinstance(item, dict)]
        based_results = {str(item.get("expected_result") or "").strip() for item in assertion_basis if str(item.get("expected_result") or "").strip()}
        missing_basis = [expected for expected in expected_results if expected not in based_results]
        if strict_evidence_contract and missing_basis:
            raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 有预期结果缺少 assertion_basis")
        source_excerpt = _normalize_requirement_quote(source.get("source_excerpt") or "")
        source_image_refs = {str(value).strip() for value in source.get("image_refs") or [] if str(value).strip()}
        for basis in assertion_basis if strict_evidence_contract else []:
            basis_type = str(basis.get("basis_type") or "").strip()
            basis_ref = str(basis.get("basis_ref") or "").strip()
            source_quote = _normalize_requirement_quote(basis.get("source_quote") or "")
            expected_result = str(basis.get("expected_result") or "").strip()
            if basis_type == "text":
                if basis_ref != str(source.get("source_doc_id") or "").strip():
                    raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 的文本依据未引用当前 source_doc_id")
                if not source_quote or source_quote not in source_excerpt:
                    raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 的文本依据不在需求原文中")
            elif basis_type == "image":
                if basis_ref not in source_image_refs:
                    raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 的图片依据 {basis_ref or '为空'} 不属于当前 source")
            else:
                raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} assertion_basis.basis_type 非法")
            evidence_role = _source_evidence_role(
                source,
                basis_type=basis_type,
                basis_ref=basis_ref,
                source_quote=str(basis.get("source_quote") or "").strip(),
            )
            if (
                (source.get("source_state_semantics") or {}).get("has_state_transition")
                and basis_type == "text"
                and _is_state_label_only(basis.get("source_quote") or "")
            ):
                raise ModelContractError(
                    f"{source_id} 分片用例 {case_id or '未命名'} 使用状态标签代替具体 target 验收证据"
                )
            if evidence_role == "current" and not _current_state_expectation_is_allowed(
                source,
                expected_result,
                str(basis.get("source_quote") or "").strip(),
            ):
                raise ModelContractError(
                    f"{source_id} 分片用例 {case_id or '未命名'} 把 current 旧状态写成正向预期：{expected_result}"
                )
            state_conflicts = _state_target_conflicts(source, expected_result)
            if state_conflicts and not _current_state_basis_is_allowed(expected_result):
                raise ModelContractError(
                    f"{source_id} 分片用例 {case_id or '未命名'} 的预期与 target 证据冲突：{expected_result}"
                )
        data_required = _case_requires_executable_test_data(case)
        if strict_evidence_contract and data_required and not case.get("test_data"):
            raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 缺少可执行 test_data")
    if strict_evidence_contract and testcases and not any(bool(case.get("baseline_candidate")) for case in testcases):
        raise ModelContractError(f"{source_id} 分片缺少 baseline_candidate 核心回归用例")
    for item in shard.get("feature_point_consumption") or []:
        if not isinstance(item, dict):
            raise ModelContractError(f"{source_id} feature_point_consumption 包含非对象项")
        fp_id = str(item.get("fp_id") or "").strip()
        result = str(item.get("consumption_result") or item.get("result") or "").strip()
        if fp_id not in source_fp_ids:
            raise ModelContractError(f"{source_id} feature_point_consumption 引用了非本 source 功能点：{fp_id or '空'}")
        refs = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids")
        refs = [str(ref).strip() for ref in (refs or []) if str(ref).strip()]
        if result == "covered_by_case" and not refs:
            raise ModelContractError(f"{source_id}/{fp_id} 标记为已覆盖但 case_refs 为空")
        missing_refs = [ref for ref in refs if ref not in local_case_ids]
        if missing_refs:
            raise ModelContractError(f"{source_id}/{fp_id} 回执引用了非本分片用例：{', '.join(missing_refs)}")
    profile = source.get("test_design_profile") if isinstance(source.get("test_design_profile"), dict) else {}
    allowed_must_cover = {
        str(value).strip() for value in profile.get("must_cover") or [] if str(value).strip()
    }
    claimed_must_cover = {
        str(value).strip()
        for case in testcases
        for value in case.get("must_cover_refs") or []
        if str(value).strip()
    }
    unknown_must_cover = sorted(claimed_must_cover - allowed_must_cover)
    if unknown_must_cover:
        raise ModelContractError(
            f"{source_id} 用例声明了未知 must_cover：{', '.join(unknown_must_cover)}"
        )
    missing_must_cover = sorted(allowed_must_cover - claimed_must_cover)
    if missing_must_cover:
        raise ModelContractError(
            f"{source_id} 缺少 must_cover 可观察回执：{', '.join(missing_must_cover)}"
        )
    method_items = [item for item in shard.get("method_consumption") or [] if isinstance(item, dict)]
    method_keys = {
        str(item.get("method") or "").strip()
        for item in method_items
        if str(item.get("source_id") or source_id).strip() == source_id and str(item.get("method") or "").strip()
    }
    for method in profile.get("applicable_methods") or []:
        method_text = str(method or "").strip()
        if method_text and method_text not in method_keys:
            raise ModelContractError(f"{source_id} 缺少适用方法消费回执：{method_text}")
    for item in method_items:
        method = str(item.get("method") or "").strip()
        result = str(item.get("consumption_result") or item.get("result") or "").strip()
        item_source_id = str(item.get("source_id") or source_id).strip()
        if item_source_id != source_id:
            raise ModelContractError(f"{source_id} method_consumption 引用了其他 source：{item_source_id}")
        refs = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids")
        refs = [str(ref).strip() for ref in (refs or []) if str(ref).strip()]
        if result == "covered_by_case" and not refs:
            raise ModelContractError(f"{source_id}/{method} 标记为已覆盖但 case_refs 为空")
        if result == "covered_by_case" and refs and not any(method in local_case_methods.get(ref, set()) for ref in refs):
            raise ModelContractError(f"{source_id}/{method} 声明已覆盖，但引用用例未记录该设计方法")
        missing_refs = [ref for ref in refs if ref not in local_case_ids]
        if missing_refs:
            raise ModelContractError(f"{source_id}/{method} 回执引用了非本分片用例：{', '.join(missing_refs)}")


async def _build_trusted_testcase_source_shard_async(
    source: dict,
    function_points: list[dict],
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    source_id = str(source.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("source shard 缺少 source_id")
    profile = _normalize_test_design_profile(source.get("test_design_profile"), source)
    payload = {
        "task": "只为当前 source 生成执行级测试用例，并记录功能点消费情况。只输出 JSON。",
        "schema": {
            "requirements_input_consumption": [],
            "feature_point_consumption": [
                {"fp_id": "FP-001", "source_id": "SRC-001", "shard_id": "SHARD-001", "consumption_result": "covered_by_case", "case_refs": ["TC-001"], "reason": ""}
            ],
            "method_consumption": [
                {"source_id": "SRC-001", "shard_id": "SHARD-001", "method": "equivalence", "consumption_result": "covered_by_case", "case_refs": ["TC-001"], "reason": ""}
            ],
            "testcases": [
                {
                    "case_id": "TC-001",
                    "source_id": "SRC-001",
                    "shard_id": "SHARD-001",
                    "fp_id": "FP-001",
                    "fp_ids": ["FP-001"],
                    "title": "",
                    "priority": "P0|P1|P2|P3",
                    "category": "functional|ui|boundary|negative|regression|compatibility|performance|security",
                    "preconditions": [],
                    "test_data": [{"name": "输入或环境数据", "value": "明确值"}],
                    "steps": [{"step_no": 1, "action": ""}],
                    "expected_results": [],
                    "evidence_refs": [],
                    "assertion_basis": [
                        {"expected_result": "与 expected_results 中一项逐字一致", "basis_type": "text|image", "basis_ref": "DOC-001|IMG-001", "source_quote": "text 时逐字复制 source_excerpt 原文", "evidence_role": "由后端写入 current|target|unspecified"}
                    ],
                    "design_method": "equivalence",
                    "design_methods": ["equivalence", "ui_display"],
                    "scenario_dimensions": [],
                    "must_cover_refs": ["复制 source.test_design_profile.must_cover 中被本用例覆盖的原始文本"],
                    "baseline_candidate": True,
                }
            ],
        },
        "rules": [
            f"只能生成 source_id={source_id} 的用例，不得生成其他 source 的内容",
            "按当前 source.test_design_profile 的 must_cover、applicable_methods 和 risk_signals 生成可观察用例",
            "每个输入 function_point 必须在 feature_point_consumption 中出现",
            "每个 applicable_methods 方法必须在 method_consumption 中出现，结果只能是 covered_by_case、merged_into_case、blocked_by_pending_confirmation 或 not_applicable",
            "一条用例可同时使用多种设计方法：design_method 写主要方法，design_methods 列出全部方法；method_consumption 标记 covered_by_case 时，引用用例的 design_methods 必须包含该方法",
            "must_cover 必须由用例标题、步骤、预期、feature_point_consumption 或 method_consumption 可观察覆盖；无法覆盖时必须写阻塞或不适用原因",
            "每条用例必须用 must_cover_refs 精确列出其覆盖的 must_cover 原始文本；所有 must_cover 至少被一条用例引用",
            "优先设计最小可解释用例集：同一 source 下同一用户路径、同一页面观察、同一导出/保存动作可用一条用例覆盖多个 FP",
            "可以用一条用例覆盖多个同源 FP，testcase.fp_ids 必须列出全部覆盖 FP，feature_point_consumption.case_ids 复用同一 case_id",
            "合并覆盖时必须在 feature_point_consumption.merge_reason 中说明为什么可由同一条用例观察",
            "不要为了凑数生成泛化用例；覆盖范围由 must_cover、适用方法、风险信号和可合并性共同决定",
            "P0 只用于阻断核心主流程或高风险数据破坏；普通 UI、改名、提示、排序、导出检查优先使用 P1/P2",
            "每条 expected_results 必须在 assertion_basis 有一条逐字对应记录；文本依据必须逐字引用 source_excerpt，图片依据只能引用 source.image_refs",
            "禁止根据‘优化、提升、合理、正常’等目标性措辞自行发明位置、边框、颜色、文案或交互；依据不明确时不要写成确定预期",
            "source_state_semantics.has_state_transition=true 时，expected_results 必须描述 target；current_text/current_image_refs 只能用于前置条件或‘不再出现/改为’等负向回归断言，禁止把 current 旧状态写成正向预期",
            "目标效果仅在图片中时，assertion_basis.basis_type=image 且 basis_ref 必须引用 target_image_refs；不得用 current 文本为目标位置或样式背书",
            "需求中出现精确文案、字段顺序、尺寸、状态组合、错误提示时，expected_results 和 test_data 必须保留这些精确值，不得改写为‘内容正确’或‘符合表格’",
            "涉及业务输入、业务值选择、搜索、筛选、上传、保存、导出或等价类/边界值/决策表/状态转换时，test_data 必须给出可直接执行的具体值；仅进入 Tab/页面后检查字段展示、改名或隐藏时允许为空",
            "当前 source 至少选择一条核心用例标记 baseline_candidate=true",
            "case_id 可先使用当前 shard 内唯一编号，后端会统一重排",
        ],
        "source": source,
        "test_design_profile": profile,
        "function_points": function_points,
    }
    raw = await _call_trusted_skill_json_async(
        skill_name="testcase-designer",
        payload=payload,
        api_key=api_key,
        model=model,
        base_url=base_url,
        max_tokens=10000,
        timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
    )
    normalized = _normalize_trusted_testcase_handoff(raw, source_id, source=source)
    try:
        _validate_trusted_source_shard_contract(source, function_points, normalized)
    except ModelContractError as exc:
        repair_payload = dict(payload)
        repair_payload["task"] = "上一次 source shard 输出未通过确定性契约。根据错误修复后重新输出完整 JSON。"
        repair_payload["previous_invalid_output"] = raw
        repair_payload["deterministic_contract_error"] = str(exc)
        repair_payload["rules"] = [
            *payload["rules"],
            "必须逐字处理 deterministic_contract_error 指出的错误，不得仅改写措辞绕过门禁",
            "若正向预期描述 target 图片中仍保留的属性，assertion_basis 必须改为对应 target_image_refs 的 image 依据；不得继续用 current 文本背书",
            "若 target 文本或 target 图片无法支持该正向预期，删除该预期，不得猜测",
            "保留已经正确的 target 位置、样式和行为，不得在修复其他依据时退回 current 旧状态",
        ]
        raw = await _call_trusted_skill_json_async(
            skill_name="testcase-designer",
            payload=repair_payload,
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_tokens=10000,
            timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
        )
        normalized = _normalize_trusted_testcase_handoff(raw, source_id, source=source)
    return normalized


def _is_transient_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    transient_markers = (
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "server disconnected",
        "connection reset",
        "readtimeout",
        "模型响应超时",
        "concurrency allocated quota exceeded",
        "internalerror",
        "stop_from_engine",
    )
    return any(marker in text for marker in transient_markers)


def _renumber_trusted_shard_cases(shards: list[dict]) -> dict:
    all_requirements_consumption: list[dict] = []
    all_consumptions: list[dict] = []
    all_method_consumptions: list[dict] = []
    all_cases: list[dict] = []
    case_id_map: dict[str, str] = {}
    case_index = 1
    for shard in shards:
        source_id = shard.get("source_id")
        for case in shard.get("testcases") or []:
            if not isinstance(case, dict):
                continue
            old_case_id = str(case.get("case_id") or f"{source_id}-TC-{case_index}").strip()
            new_case_id = f"TC-{case_index:03d}"
            case_id_map[f"{source_id}:{old_case_id}"] = new_case_id
            case_source_id = str(case.get("source_id") or source_id or "").strip()
            if case_source_id:
                case["source_id"] = case_source_id
            if not str(case.get("shard_id") or "").strip():
                case["shard_id"] = f"SHARD-{case_source_id or source_id or 'UNKNOWN'}"
            fp_ids = case.get("fp_ids")
            fp_id_values = [str(item).strip() for item in fp_ids if str(item).strip()] if isinstance(fp_ids, list) else []
            traceability = case.get("traceability") if isinstance(case.get("traceability"), dict) else {}
            trace_fp_ids = traceability.get("function_points") if isinstance(traceability.get("function_points"), list) else []
            fp_id_values.extend(str(item).strip() for item in trace_fp_ids if str(item).strip())
            if case.get("fp_id"):
                fp_id_values.append(str(case.get("fp_id")).strip())
            case["fp_ids"] = sorted(set(item for item in fp_id_values if item))
            case["case_id"] = new_case_id
            all_cases.append(case)
            case_index += 1
        for item in shard.get("feature_point_consumption") or []:
            if not isinstance(item, dict):
                continue
            rewritten = dict(item)
            rewritten_case_ids: list[str] = []
            for old_case_id in item.get("case_ids") or []:
                mapped = case_id_map.get(f"{source_id}:{str(old_case_id).strip()}")
                if mapped:
                    rewritten_case_ids.append(mapped)
            rewritten["case_ids"] = rewritten_case_ids
            rewritten["case_refs"] = rewritten_case_ids
            all_consumptions.append(rewritten)
        for item in shard.get("method_consumption") or []:
            if not isinstance(item, dict):
                continue
            rewritten = dict(item)
            rewritten_case_ids: list[str] = []
            refs = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids")
            for old_case_id in refs or []:
                mapped = case_id_map.get(f"{source_id}:{str(old_case_id).strip()}")
                if mapped:
                    rewritten_case_ids.append(mapped)
            rewritten["case_refs"] = rewritten_case_ids
            rewritten["case_ids"] = rewritten_case_ids
            all_method_consumptions.append(rewritten)
        for item in shard.get("requirements_input_consumption") or []:
            if isinstance(item, dict):
                all_requirements_consumption.append(dict(item))
    case_ids_by_source: dict[str, list[str]] = defaultdict(list)
    case_ids_by_fp: dict[str, list[str]] = defaultdict(list)
    for case in all_cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "").strip()
        source_id = str(case.get("source_id") or "").strip()
        if case_id and source_id:
            case_ids_by_source[source_id].append(case_id)
        for fp_id in case.get("fp_ids") or []:
            fp_id_text = str(fp_id or "").strip()
            if case_id and fp_id_text:
                case_ids_by_fp[fp_id_text].append(case_id)
    for item in all_consumptions:
        if not isinstance(item, dict):
            continue
        result = str(item.get("consumption_result") or item.get("result") or "").strip()
        if result != "covered_by_case" or item.get("case_ids"):
            continue
        fp_id = str(item.get("fp_id") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        fallback_refs = case_ids_by_fp.get(fp_id) or case_ids_by_source.get(source_id) or []
        item["case_ids"] = list(fallback_refs)
        item["case_refs"] = list(fallback_refs)
        if fallback_refs:
            item["merge_reason"] = item.get("merge_reason") or item.get("reason") or "后端根据同 source/FP 的真实用例回填消费回执"
    for item in all_method_consumptions:
        if not isinstance(item, dict):
            continue
        result = str(item.get("consumption_result") or item.get("result") or "").strip()
        if result != "covered_by_case" or item.get("case_refs"):
            continue
        source_id = str(item.get("source_id") or "").strip()
        fallback_refs = case_ids_by_source.get(source_id) or []
        item["case_refs"] = list(fallback_refs)
        item["case_ids"] = list(fallback_refs)
        if fallback_refs:
            item["reason"] = item.get("reason") or "后端根据同 source 的真实用例回填方法消费回执"
    return {
        "generation_strategy": "source_shard",
        "testcase_shards": shards,
        "requirements_input_consumption": all_requirements_consumption,
        "feature_point_consumption": all_consumptions,
        "method_consumption": all_method_consumptions,
        "source_case_summary": [
            {
                "source_id": shard.get("source_id"),
                "shard_id": shard.get("shard_id") or f"SHARD-{str(shard.get('source_id') or '').replace('SRC-', '').zfill(3)}",
                "actual_case_count": len([case for case in shard.get("testcases") or [] if isinstance(case, dict)]),
                "coverage_status": "covered" if shard.get("status") == "success" else str(shard.get("status") or "unknown"),
                "reason": shard.get("error") or shard.get("skip_reason") or "",
            }
            for shard in shards
            if isinstance(shard, dict)
        ],
        "testcases": all_cases,
        "xmind_grouping_contract": _trusted_xmind_grouping_contract(),
    }


def _finalize_trusted_testcase_shards(shards: list[dict]) -> dict:
    testcase_handoff = _merge_trusted_duplicate_cases(_renumber_trusted_shard_cases(list(shards)))
    failed = [s for s in shards if isinstance(s, dict) and s.get("status") == "failed"]
    skipped = [s for s in shards if isinstance(s, dict) and s.get("status") == "skipped"]
    testcase_handoff["shard_failures"] = [
        {"source_id": s.get("source_id"), "error": s.get("error") or s.get("skip_reason") or "source shard 生成失败"}
        for s in failed
    ]
    testcase_handoff["shard_skips"] = [
        {"source_id": s.get("source_id"), "reason": s.get("skip_reason") or "未生成用例"}
        for s in skipped
    ]
    return testcase_handoff


def _trusted_shard_failure_message(testcase_handoff: dict) -> str:
    failures = testcase_handoff.get("shard_failures") or []
    if not failures:
        return ""
    ids = ", ".join(str(item.get("source_id") or "").strip() for item in failures if isinstance(item, dict))
    first_error = ""
    for item in failures:
        if isinstance(item, dict) and item.get("error"):
            first_error = str(item.get("error"))
            break
    if "concurrency allocated quota exceeded" in first_error.lower() or "http 429" in first_error.lower():
        first_error = f"模型并发配额不足：{first_error}"
    return f"以下 source shard 生成失败：{ids}；错误：{first_error}"


def _build_trusted_testcase_handoff_from_lite_package(
    scope_index: dict,
    requirement_handoff: dict,
    lite_testcase_package: dict,
) -> dict:
    fp_by_id = {
        str(item.get("fp_id") or "").strip(): item
        for item in requirement_handoff.get("function_points") or []
        if isinstance(item, dict) and str(item.get("fp_id") or "").strip()
    }
    source_by_id = _trusted_source_by_id(scope_index)
    cases_by_source: dict[str, list[dict]] = defaultdict(list)
    for case in lite_testcase_package.get("testcases") or []:
        if not isinstance(case, dict):
            continue
        fp_id = str(case.get("fp_id") or "").strip()
        fp = fp_by_id.get(fp_id)
        if not fp:
            continue
        source_id = str(fp.get("source_id") or "").strip()
        if not source_id or source_id not in source_by_id:
            continue
        trusted_case = dict(case)
        trusted_case["source_id"] = source_id
        trusted_case["shard_id"] = fp.get("shard_id") or f"SHARD-{source_id}"
        trusted_case["fp_id"] = fp_id
        candidate_fp_ids = list(dict.fromkeys(
            [fp_id] + [str(item).strip() for item in trusted_case.get("fp_ids") or [] if str(item).strip()]
        ))
        trusted_case["fp_ids"] = [
            linked_fp_id for linked_fp_id in candidate_fp_ids
            if str((fp_by_id.get(linked_fp_id) or {}).get("source_id") or "").strip() == source_id
        ]
        removed_fp_ids = [linked_fp_id for linked_fp_id in candidate_fp_ids if linked_fp_id not in trusted_case["fp_ids"]]
        if removed_fp_ids:
            trusted_case.setdefault("normalization_notes", []).append({
                "code": "CROSS_SOURCE_FP_IDS_REMOVED",
                "message": f"按单 source 分组契约移除跨 source 功能点：{', '.join(removed_fp_ids)}",
            })
        trusted_case["design_method"] = trusted_case.get("design_method") or (trusted_case.get("generation_basis") or {}).get("method") or _trusted_method_for_case(trusted_case, fp)
        traceability = trusted_case.get("traceability") if isinstance(trusted_case.get("traceability"), dict) else {}
        traceability["function_points"] = list(trusted_case["fp_ids"])
        traceability["sources"] = list(dict.fromkeys(
            [str(item).strip() for item in traceability.get("sources") or [] if str(item).strip()] + [source_id]
        ))
        trusted_case["traceability"] = traceability
        cases_by_source[source_id].append(trusted_case)

    shards: list[dict] = []
    for source in _trusted_scope_source_items(scope_index):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "").strip()
        source_fps = [
            fp for fp in requirement_handoff.get("function_points") or []
            if isinstance(fp, dict) and str(fp.get("source_id") or "").strip() == source_id
        ]
        source_cases = cases_by_source.get(source_id) or []
        case_ids_by_fp: dict[str, list[str]] = defaultdict(list)
        for case in source_cases:
            case_id = str(case.get("case_id") or "").strip()
            for fp_id in case.get("fp_ids") or [case.get("fp_id")]:
                fp_id_text = str(fp_id or "").strip()
                if case_id and fp_id_text:
                    case_ids_by_fp[fp_id_text].append(case_id)

        fp_consumption = []
        for fp in source_fps:
            fp_id = str(fp.get("fp_id") or "").strip()
            refs = list(dict.fromkeys(case_ids_by_fp.get(fp_id) or []))
            if refs:
                fp_consumption.append({
                    "fp_id": fp_id,
                    "source_id": source_id,
                    "result": "covered_by_case",
                    "case_ids": refs,
                    "case_refs": refs,
                    "merge_reason": "",
                })
            else:
                fp_consumption.append({
                    "fp_id": fp_id,
                    "source_id": source_id,
                    "result": "blocked_by_pending_confirmation",
                    "case_ids": [],
                    "case_refs": [],
                    "merge_reason": "轻量基线用例未覆盖该功能点，保留为可信审查风险",
                })

        method_consumption = []
        source_case_ids = [str(case.get("case_id") or "").strip() for case in source_cases if str(case.get("case_id") or "").strip()]
        source_cases_by_method: dict[str, list[str]] = defaultdict(list)
        for case in source_cases:
            case_id = str(case.get("case_id") or "").strip()
            if not case_id:
                continue
            fp = fp_by_id.get(str(case.get("fp_id") or "").strip())
            source_cases_by_method[_trusted_method_for_case(case, fp)].append(case_id)
        profile = source.get("test_design_profile") if isinstance(source.get("test_design_profile"), dict) else {}
        methods = [str(item or "").strip() for item in profile.get("applicable_methods") or [] if str(item or "").strip()]
        if not methods:
            methods = ["equivalence"]
        for method in methods:
            refs = list(dict.fromkeys(source_cases_by_method.get(method) or []))
            if refs:
                method_consumption.append({
                    "source_id": source_id,
                    "method": method,
                    "consumption_result": "covered_by_case",
                    "case_refs": refs,
                    "case_ids": refs,
                    "reason": "轻量基线用例直接体现该方法",
                })
            else:
                method_consumption.append({
                    "source_id": source_id,
                    "method": method,
                    "consumption_result": "merged_into_case" if source_case_ids else "blocked_by_pending_confirmation",
                    "case_refs": source_case_ids,
                    "case_ids": source_case_ids,
                    "reason": "轻量基线链路未显式生成该方法的独立用例，作为可信审查风险保留",
                })

        shards.append({
            "source_id": source_id,
            "status": "success" if source_cases else "skipped",
            "skip_reason": "" if source_cases else "轻量基线未产出该 source 的用例",
            "test_design_profile": source.get("test_design_profile") or _default_test_design_profile(source),
            "function_point_count": len(source_fps),
            "testcase_count": len(source_cases),
            "feature_point_consumption": fp_consumption,
            "method_consumption": method_consumption,
            "testcases": source_cases,
            "generation_strategy": "lite_review_base",
        })

    testcase_handoff = _finalize_trusted_testcase_shards(shards)
    testcase_handoff["generation_strategy"] = "lite_review"
    testcase_handoff["base_testcase_count"] = len([item for item in lite_testcase_package.get("testcases") or [] if isinstance(item, dict)])
    testcase_handoff["shard_progress_summary"] = {
        "total_source_count": len(shards),
        "success_count": len([item for item in shards if item.get("status") == "success"]),
        "failed_count": 0,
        "skipped_count": len([item for item in shards if item.get("status") == "skipped"]),
        "reused_count": 0,
        "concurrency": 0,
        "duration_ms": 0,
        "strategy": "lite_review",
    }
    return testcase_handoff


def _trusted_xmind_grouping_contract() -> dict:
    return {
        "required_tree": "模块 -> 场景 -> SRC -> FP -> TC",
        "required_case_fields": ["source_id", "shard_id", "fp_ids"],
        "join_sources": {
            "module": "ScopeIndex.yaml.source_blocks[source_id].module",
            "scene": "ScopeIndex.yaml.source_blocks[source_id].scene",
            "source_order": "ScopeIndex.yaml.source_blocks[source_id].source_order",
            "title_path": "ScopeIndex.yaml.source_blocks[source_id].title_path",
            "fp_title": "function_points.function_points[fp_id].title",
        },
        "no_duplicate_long_fields": [
            "module",
            "scene",
            "source_order",
            "title_path",
            "description",
            "rules",
            "traceability",
            "generation_basis.rationale",
        ],
        "forbidden_shapes": ["root -> TC", "SRC -> TC", "root -> SRC -> TC", "模块 -> TC"],
    }


def _trusted_case_fingerprint(case: dict) -> str:
    source_id = str(case.get("source_id") or "").strip()
    category = str(case.get("category") or "").strip().lower()
    title = re.sub(r"\s+", "", str(case.get("title") or "").strip().lower())
    steps = re.sub(r"\s+", "", "；".join(_step_to_text(step) for step in (case.get("steps") or [])))
    expected = re.sub(r"\s+", "", _compact_case_text(case.get("expected_results") or ""))
    return "|".join([source_id, category, title, steps[:400], expected[:400]])


def _merge_trusted_duplicate_cases(testcase_handoff: dict) -> dict:
    cases = [item for item in testcase_handoff.get("testcases") or [] if isinstance(item, dict)]
    consumptions = [item for item in testcase_handoff.get("feature_point_consumption") or [] if isinstance(item, dict)]
    kept_cases: list[dict] = []
    fingerprint_to_case: dict[str, dict] = {}
    old_to_new_case_id: dict[str, str] = {}
    duplicate_groups: list[dict] = []
    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        fingerprint = _trusted_case_fingerprint(case)
        if fingerprint and fingerprint in fingerprint_to_case:
            kept = fingerprint_to_case[fingerprint]
            kept_case_id = str(kept.get("case_id") or "").strip()
            old_to_new_case_id[case_id] = kept_case_id
            duplicate_groups.append(
                {
                    "source_id": case.get("source_id"),
                    "kept_case_id": kept_case_id,
                    "merged_case_id": case_id,
                    "reason": "same_source_category_title_steps_expected",
                }
            )
            traceability = kept.get("traceability") if isinstance(kept.get("traceability"), dict) else {}
            fp_ids = set(traceability.get("function_points") or [])
            if case.get("fp_id"):
                fp_ids.add(str(case.get("fp_id")))
            case_traceability = case.get("traceability") if isinstance(case.get("traceability"), dict) else {}
            for fp_id in case_traceability.get("function_points") or []:
                fp_ids.add(str(fp_id))
            traceability["function_points"] = sorted(fp_ids)
            kept["traceability"] = traceability
            kept["fp_ids"] = sorted(set([str(item).strip() for item in (kept.get("fp_ids") or []) if str(item).strip()]) | fp_ids)
            continue
        fingerprint_to_case[fingerprint] = case
        kept_cases.append(case)
        old_to_new_case_id[case_id] = case_id

    for consumption in consumptions:
        case_ids = []
        for case_id in consumption.get("case_ids") or []:
            mapped = old_to_new_case_id.get(str(case_id).strip(), str(case_id).strip())
            if mapped and mapped not in case_ids:
                case_ids.append(mapped)
        original_case_ids = [str(item).strip() for item in consumption.get("case_ids") or [] if str(item).strip()]
        consumption["case_ids"] = case_ids
        if original_case_ids and case_ids != original_case_ids:
            consumption["result"] = "merged_into_case"
            consumption["merge_reason"] = consumption.get("merge_reason") or "同 source 下存在标题、步骤和预期一致的重复用例，已合并覆盖"

    testcase_handoff["testcases"] = kept_cases
    testcase_handoff["feature_point_consumption"] = consumptions
    testcase_handoff["duplicate_case_groups"] = duplicate_groups
    testcase_handoff["duplicate_case_count"] = len(duplicate_groups)
    return testcase_handoff


def _build_trusted_testcase_handoff(
    scope_index: dict,
    requirement_handoff: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    progress_callback=None,
    existing_testcase_handoff: dict | None = None,
) -> dict:
    return asyncio.run(_build_trusted_testcase_handoff_async(
        scope_index, requirement_handoff,
        api_key=api_key, model=model, base_url=base_url,
        progress_callback=progress_callback,
        existing_testcase_handoff=existing_testcase_handoff,
    ))


async def _build_trusted_testcase_handoff_async(
    scope_index: dict,
    requirement_handoff: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    progress_callback=None,
    existing_testcase_handoff: dict | None = None,
) -> dict:
    function_points = [item for item in requirement_handoff.get("function_points") or [] if isinstance(item, dict)]
    fp_by_source: dict[str, list[dict]] = {}
    for fp in function_points:
        source_id = str(fp.get("source_id") or "").strip()
        fp_by_source.setdefault(source_id, []).append(fp)

    sources = [item for item in _trusted_scope_source_items(scope_index) if isinstance(item, dict)]
    total_sources = len(sources)
    source_position = {
        str(source.get("source_id") or "").strip(): index
        for index, source in enumerate(sources, start=1)
    }
    started_at = time.perf_counter()
    progress_state = {"completed": 0, "succeeded": 0, "failed": 0, "skipped": 0, "reused": 0}
    progress_lock = asyncio.Lock()
    reusable_shards = _trusted_reusable_source_shards(existing_testcase_handoff)

    def _progress_message(
        *,
        verb: str,
        source_id: str,
        source_fps: list[dict],
        source: dict,
        attempt: int | None = None,
        elapsed_seconds: float | None = None,
    ) -> str:
        completed = int(progress_state["completed"])
        avg_seconds = (time.perf_counter() - started_at) / completed if completed else 0
        remaining = max(total_sources - completed, 0)
        eta = _format_duration_zh(avg_seconds * remaining) if completed else "计算中"
        bits = [
            f"{verb} {source_id}",
            f"第 {source_position.get(source_id, '?')}/{total_sources}",
            f"已完成 {completed}/{total_sources}",
            f"并发 {_TRUSTED_SHARD_CONCURRENCY}",
            f"{len(source_fps)} 个功能点",
            f"{len((source.get('test_design_profile') or {}).get('must_cover') or [])} 个 must_cover",
        ]
        if attempt is not None and _TRUSTED_SHARD_MAX_ATTEMPTS > 1:
            bits.append(f"第 {attempt}/{_TRUSTED_SHARD_MAX_ATTEMPTS} 次")
        if elapsed_seconds is not None:
            bits.append(f"本分片耗时 {_format_duration_zh(elapsed_seconds)}")
        if completed:
            bits.append(f"预计剩余 {eta}")
        return "，".join(bits)

    async def _build_one(source: dict) -> dict:
        source_id = str(source.get("source_id") or "").strip()
        source_fps = fp_by_source.get(source_id) or []
        if not source_fps:
            async with progress_lock:
                progress_state["completed"] += 1
                progress_state["skipped"] += 1
                if progress_callback:
                    progress_callback(_progress_message(verb="跳过", source_id=source_id, source_fps=source_fps, source=source, elapsed_seconds=0))
            return {
                "source_id": source_id,
                "status": "skipped",
                "skip_reason": "未找到绑定到该 source 的功能点",
                "feature_point_consumption": [],
                "testcases": [],
            }
        cached_shard = reusable_shards.get(source_id)
        if cached_shard:
            try:
                cached_shard = _localize_trusted_shard_case_ids(cached_shard)
                cached_shard = _normalize_trusted_testcase_handoff(cached_shard, source_id, source=source)
                _validate_trusted_source_shard_contract(source, source_fps, cached_shard)
                cached_shard["status"] = "success"
                cached_shard["reused_from_previous_run"] = True
                cached_shard["test_design_profile"] = cached_shard.get("test_design_profile") or source.get("test_design_profile") or _default_test_design_profile(source)
                cached_shard["function_point_count"] = len(source_fps)
                cached_shard["testcase_count"] = len(cached_shard.get("testcases") or [])
                async with progress_lock:
                    progress_state["completed"] += 1
                    progress_state["succeeded"] += 1
                    progress_state["reused"] += 1
                    if progress_callback:
                        progress_callback(_progress_message(verb="复用", source_id=source_id, source_fps=source_fps, source=source, elapsed_seconds=0))
                return cached_shard
            except Exception as exc:
                logger.warning("cached source shard %s is invalid and will be regenerated: %s", source_id, exc)
        shard_started_at = time.perf_counter()
        async with progress_lock:
            if progress_callback:
                progress_callback(_progress_message(verb="正在生成", source_id=source_id, source_fps=source_fps, source=source))
        try:
            last_error: Exception | None = None
            for attempt in range(1, _TRUSTED_SHARD_MAX_ATTEMPTS + 1):
                try:
                    if attempt > 1:
                        async with progress_lock:
                            if progress_callback:
                                progress_callback(_progress_message(
                                    verb="正在重试",
                                    source_id=source_id,
                                    source_fps=source_fps,
                                    source=source,
                                    attempt=attempt,
                                ))
                    shard = await _build_trusted_testcase_source_shard_async(
                        source, source_fps,
                        api_key=api_key, model=model, base_url=base_url,
                    )
                    _validate_trusted_source_shard_contract(source, source_fps, shard)
                    if attempt > 1:
                        shard.setdefault("retry_notes", []).append({
                            "attempt": attempt,
                            "reason": str(last_error) if last_error else "transient_model_error",
                        })
                    break
                except Exception as exc:
                    last_error = exc
                    retryable_contract_error = isinstance(exc, ModelContractError)
                    if attempt >= _TRUSTED_SHARD_MAX_ATTEMPTS or (not retryable_contract_error and not _is_transient_model_error(exc)):
                        raise
                    await asyncio.sleep(min(2 * attempt, 6))
            shard["source_id"] = source_id
            shard["status"] = "success"
            shard["test_design_profile"] = source.get("test_design_profile") or _default_test_design_profile(source)
            shard["function_point_count"] = len(source_fps)
            shard["testcase_count"] = len(shard.get("testcases") or [])
            shard["duration_ms"] = int((time.perf_counter() - shard_started_at) * 1000)
            async with progress_lock:
                progress_state["completed"] += 1
                progress_state["succeeded"] += 1
                if progress_callback:
                    progress_callback(_progress_message(verb="已完成", source_id=source_id, source_fps=source_fps, source=source, elapsed_seconds=shard["duration_ms"] / 1000))
            return shard
        except Exception as exc:
            duration_ms = int((time.perf_counter() - shard_started_at) * 1000)
            async with progress_lock:
                progress_state["completed"] += 1
                progress_state["failed"] += 1
                if progress_callback:
                    progress_callback(_progress_message(verb="生成失败", source_id=source_id, source_fps=source_fps, source=source, elapsed_seconds=duration_ms / 1000))
            return {
                "source_id": source_id,
                "status": "failed",
                "error": str(exc),
                "duration_ms": duration_ms,
                "feature_point_consumption": [],
                "testcases": [],
            }

    shards = await _gather_limited((_build_one(src) for src in sources), limit=_TRUSTED_SHARD_CONCURRENCY)
    testcase_handoff = _finalize_trusted_testcase_shards(list(shards))
    testcase_handoff["shard_progress_summary"] = {
        "total_source_count": total_sources,
        "success_count": progress_state["succeeded"],
        "failed_count": progress_state["failed"],
        "skipped_count": progress_state["skipped"],
        "reused_count": progress_state["reused"],
        "concurrency": _TRUSTED_SHARD_CONCURRENCY,
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
    }
    return testcase_handoff


def _validate_trusted_testcase_handoff(scope_index: dict, requirement_handoff: dict, testcase_handoff: dict) -> dict:
    source_by_id = _trusted_source_by_id(scope_index)
    source_ids = set(source_by_id.keys())
    function_points = [item for item in requirement_handoff.get("function_points") or [] if isinstance(item, dict)]
    fp_source = {str(item.get("fp_id") or "").strip(): str(item.get("source_id") or "").strip() for item in function_points}
    consumptions = testcase_handoff.get("feature_point_consumption") or []
    method_consumptions = testcase_handoff.get("method_consumption") or []
    testcases = testcase_handoff.get("testcases") or []
    issues: list[dict] = []
    failed_source_ids: set[str] = set()
    failed_fp_ids: set[str] = set()
    for shard in testcase_handoff.get("testcase_shards") or []:
        if not isinstance(shard, dict) or shard.get("status") != "failed":
            continue
        source_id = str(shard.get("source_id") or "").strip()
        if not source_id:
            continue
        failed_source_ids.add(source_id)
        shard_fp_ids = sorted(fp_id for fp_id, fp_source_id in fp_source.items() if fp_source_id == source_id)
        failed_fp_ids.update(shard_fp_ids)
        issues.append(
            {
                "severity": "blocker",
                "code": "SOURCE_SHARD_FAILED",
                "source_id": source_id,
                "shard_id": f"SHARD-{source_id}",
                "fp_ids": shard_fp_ids,
                "message": f"{source_id} 分片生成失败，影响功能点 {', '.join(shard_fp_ids) or '未知'}：{shard.get('error') or 'source shard 生成失败'}",
            }
        )
    for failure in testcase_handoff.get("shard_failures") or []:
        if not isinstance(failure, dict):
            continue
        source_id = str(failure.get("source_id") or "").strip()
        if not source_id or source_id in failed_source_ids:
            continue
        failed_source_ids.add(source_id)
        shard_fp_ids = sorted(fp_id for fp_id, fp_source_id in fp_source.items() if fp_source_id == source_id)
        failed_fp_ids.update(shard_fp_ids)
        issues.append(
            {
                "severity": "blocker",
                "code": "SOURCE_SHARD_FAILED",
                "source_id": source_id,
                "shard_id": f"SHARD-{source_id}",
                "fp_ids": shard_fp_ids,
                "message": f"{source_id} 分片生成失败，影响功能点 {', '.join(shard_fp_ids) or '未知'}：{failure.get('error') or 'source shard 生成失败'}",
            }
        )
    contract = testcase_handoff.get("xmind_grouping_contract")
    if not isinstance(contract, dict):
        issues.append({"severity": "blocker", "code": "XMIND_GROUPING_CONTRACT_MISSING", "message": "TestcasePackage 缺少 xmind_grouping_contract"})
    elif contract.get("required_tree") != "模块 -> 场景 -> SRC -> FP -> TC":
        issues.append({"severity": "blocker", "code": "XMIND_GROUPING_CONTRACT_BAD_TREE", "message": "xmind_grouping_contract.required_tree 不符合 trusted 导图结构"})
    consumed_fp_ids = {
        str(item.get("fp_id") or "").strip()
        for item in consumptions
        if isinstance(item, dict) and str(item.get("fp_id") or "").strip()
    }
    for fp_id in sorted(set(fp_source.keys()) - consumed_fp_ids):
        if fp_id in failed_fp_ids:
            continue
        issues.append({"severity": "blocker", "code": "FP_NOT_CONSUMED", "message": f"{fp_id} 未出现在 feature_point_consumption"})
    for item in consumptions:
        if not isinstance(item, dict):
            issues.append({"severity": "blocker", "code": "BAD_FP_CONSUMPTION_ITEM", "message": "feature_point_consumption 包含非对象项"})
            continue
        fp_id = str(item.get("fp_id") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        result = str(item.get("consumption_result") or item.get("result") or "").strip()
        if fp_id not in fp_source:
            issues.append({"severity": "blocker", "code": "UNKNOWN_FP_CONSUMED", "message": f"{fp_id} 不在功能点中"})
        if source_id not in source_ids:
            issues.append({"severity": "blocker", "code": "UNKNOWN_SOURCE_IN_FP_CONSUMPTION", "message": f"{fp_id} 引用了未知 source_id：{source_id}"})
        if result not in _TRUSTED_TESTCASE_RESULTS:
            issues.append({"severity": "blocker", "code": "BAD_FP_CONSUMPTION_RESULT", "message": f"{fp_id} result 非法：{result}"})
        if result in {"merged_into_case", "blocked_by_pending_confirmation", "not_applicable"} and not str(item.get("merge_reason") or item.get("note") or "").strip():
            issues.append({"severity": "blocker", "code": "MISSING_FP_CONSUMPTION_REASON", "message": f"{fp_id} 未独立覆盖但缺少说明"})
    case_ids: set[str] = set()
    case_source_by_id: dict[str, str] = {}
    source_case_count: Counter[str] = Counter()
    covered_sources: set[str] = set()
    case_text_by_source: dict[str, list[str]] = defaultdict(list)
    must_cover_refs_by_source: dict[str, set[str]] = defaultdict(set)
    baseline_sources: set[str] = set()
    case_methods_by_id: dict[str, set[str]] = {}
    for case in testcases:
        if not isinstance(case, dict):
            issues.append({"severity": "blocker", "code": "BAD_CASE_ITEM", "message": "testcases 包含非对象项"})
            continue
        case_id = str(case.get("case_id") or "").strip()
        fp_id = str(case.get("fp_id") or "").strip()
        source_id = str(case.get("source_id") or "").strip()
        if not case_id:
            issues.append({"severity": "blocker", "code": "CASE_MISSING_ID", "message": "用例缺少 case_id"})
        elif case_id in case_ids:
            issues.append({"severity": "blocker", "code": "CASE_DUPLICATE_ID", "message": f"用例重复：{case_id}"})
        case_ids.add(case_id)
        if case_id:
            case_source_by_id[case_id] = source_id
            methods = {
                str(value).strip()
                for value in case.get("design_methods") or []
                if str(value).strip()
            }
            primary_method = str(case.get("design_method") or (case.get("generation_basis") or {}).get("method") or "").strip()
            if primary_method:
                methods.add(primary_method)
            case_methods_by_id[case_id] = methods
        if source_id not in source_ids:
            issues.append({"severity": "blocker", "code": "CASE_UNKNOWN_SOURCE", "message": f"{case_id} 引用了未知 source_id：{source_id}"})
        else:
            source_case_count[source_id] += 1
            covered_sources.add(source_id)
            case_text_by_source[source_id].append(_compact_case_text([case.get("title"), case.get("steps"), case.get("expected_results"), case.get("design_method"), case.get("scenario_dimensions")]))
            for value in case.get("must_cover_refs") or []:
                if str(value).strip():
                    must_cover_refs_by_source[source_id].add(str(value).strip())
            if case.get("baseline_candidate"):
                baseline_sources.add(source_id)
        if not str(case.get("shard_id") or "").strip():
            issues.append({"severity": "blocker", "code": "CASE_MISSING_SHARD_ID", "message": f"{case_id} 缺少 shard_id"})
        fp_ids = case.get("fp_ids")
        fp_id_values = [str(item).strip() for item in fp_ids if str(item).strip()] if isinstance(fp_ids, list) else []
        if not fp_id_values:
            issues.append({"severity": "blocker", "code": "CASE_MISSING_FP_IDS", "message": f"{case_id} 缺少 fp_ids"})
        for linked_fp_id in fp_id_values:
            if linked_fp_id not in fp_source:
                issues.append({"severity": "blocker", "code": "CASE_FP_IDS_UNKNOWN_FP", "message": f"{case_id} fp_ids 引用了未知功能点：{linked_fp_id}"})
            elif source_id and fp_source.get(linked_fp_id) and source_id != fp_source[linked_fp_id]:
                issues.append({"severity": "blocker", "code": "CASE_FP_IDS_SOURCE_MISMATCH", "message": f"{case_id} 的 fp_ids 与 source_id 归属不一致"})
        if fp_id not in fp_source:
            issues.append({"severity": "blocker", "code": "CASE_UNKNOWN_FP", "message": f"{case_id} 引用了未知 fp_id：{fp_id}"})
        elif source_id and fp_source.get(fp_id) and source_id != fp_source[fp_id]:
            issues.append({"severity": "blocker", "code": "CASE_SOURCE_FP_MISMATCH", "message": f"{case_id} 的 source_id 与 fp_id 归属不一致"})
        source = source_by_id.get(source_id) or {}
        if source.get("source_excerpt"):
            authoritative_refs = {str(value).strip() for value in source.get("evidence_refs") or [] if str(value).strip()}
            invalid_evidence_refs = [
                str(value).strip()
                for value in case.get("evidence_refs") or []
                if str(value).strip() and str(value).strip() not in authoritative_refs
            ]
            invalid_evidence_refs.extend(str(value).strip() for value in case.get("invalid_evidence_refs") or [] if str(value).strip())
            if invalid_evidence_refs:
                issues.append({"severity": "blocker", "code": "CASE_EVIDENCE_SOURCE_MISMATCH", "message": f"{case_id} 引用了非本 source 证据：{', '.join(sorted(set(invalid_evidence_refs)))}"})
            expected_results = [str(value).strip() for value in case.get("expected_results") or [] if str(value).strip()]
            assertion_basis = [item for item in case.get("assertion_basis") or [] if isinstance(item, dict)]
            based_results = {str(item.get("expected_result") or "").strip() for item in assertion_basis if str(item.get("expected_result") or "").strip()}
            if any(expected not in based_results for expected in expected_results):
                issues.append({"severity": "blocker", "code": "CASE_ASSERTION_BASIS_MISSING", "message": f"{case_id} 有预期结果未绑定原文或图片证据"})
            normalized_excerpt = _normalize_requirement_quote(source.get("source_excerpt") or "")
            source_doc_id = str(source.get("source_doc_id") or "").strip()
            source_image_refs = {str(value).strip() for value in source.get("image_refs") or [] if str(value).strip()}
            for basis in assertion_basis:
                basis_type = str(basis.get("basis_type") or "").strip()
                basis_ref = str(basis.get("basis_ref") or "").strip()
                expected_result = str(basis.get("expected_result") or "").strip()
                if basis_type == "text" and (
                    basis_ref != source_doc_id
                    or not _normalize_requirement_quote(basis.get("source_quote") or "")
                    or _normalize_requirement_quote(basis.get("source_quote") or "") not in normalized_excerpt
                ):
                    issues.append({"severity": "blocker", "code": "CASE_TEXT_BASIS_INVALID", "message": f"{case_id} 的文本预期依据不在当前 source 原文中"})
                elif basis_type == "image" and basis_ref not in source_image_refs:
                    issues.append({"severity": "blocker", "code": "CASE_IMAGE_BASIS_INVALID", "message": f"{case_id} 的图片预期依据不属于当前 source"})
                evidence_role = _source_evidence_role(
                    source,
                    basis_type=basis_type,
                    basis_ref=basis_ref,
                    source_quote=str(basis.get("source_quote") or "").strip(),
                )
                if (
                    (source.get("source_state_semantics") or {}).get("has_state_transition")
                    and basis_type == "text"
                    and _is_state_label_only(basis.get("source_quote") or "")
                ):
                    issues.append({
                        "severity": "blocker",
                        "code": "CASE_TARGET_EVIDENCE_EMPTY",
                        "source_id": source_id,
                        "case_id": case_id,
                        "message": f"{case_id} 使用状态标签代替具体 target 验收证据",
                    })
                if evidence_role == "current" and not _current_state_expectation_is_allowed(
                    source,
                    expected_result,
                    str(basis.get("source_quote") or "").strip(),
                ):
                    issues.append({
                        "severity": "blocker",
                        "code": "CASE_CURRENT_STATE_AS_EXPECTED",
                        "source_id": source_id,
                        "case_id": case_id,
                        "message": f"{case_id} 把 current 旧状态写成正向预期：{expected_result}",
                    })
                state_conflicts = _state_target_conflicts(source, expected_result)
                if state_conflicts and not _current_state_basis_is_allowed(expected_result):
                    issues.append({
                        "severity": "blocker",
                        "code": "CASE_EXPECTED_CONTRADICTS_TARGET",
                        "source_id": source_id,
                        "case_id": case_id,
                        "message": f"{case_id} 的预期与 target 证据冲突：{expected_result}",
                    })
            if _case_requires_executable_test_data(case) and not case.get("test_data"):
                issues.append({"severity": "blocker", "code": "CASE_TEST_DATA_REQUIRED", "message": f"{case_id} 涉及输入或规则组合但缺少具体 test_data"})
    for source_id in sorted(covered_sources - baseline_sources):
        if (source_by_id.get(source_id) or {}).get("source_excerpt"):
            issues.append({"severity": "blocker", "code": "SOURCE_BASELINE_CANDIDATE_MISSING", "message": f"{source_id} 缺少核心回归基线候选用例"})
    for item in consumptions:
        if not isinstance(item, dict):
            continue
        fp_id = str(item.get("fp_id") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        result = str(item.get("result") or "").strip()
        referenced_case_ids = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids") or []
        if result == "covered_by_case" and not referenced_case_ids:
            issues.append({"severity": "blocker", "code": "FP_CONSUMPTION_MISSING_CASE_IDS", "message": f"{fp_id} 标记为已覆盖但 case_ids 为空"})
        if referenced_case_ids and not isinstance(referenced_case_ids, list):
            issues.append({"severity": "blocker", "code": "FP_CONSUMPTION_CASE_IDS_BAD_TYPE", "message": f"{fp_id} case_ids 必须是数组"})
            continue
        for case_id in referenced_case_ids:
            case_id_text = str(case_id).strip()
            if case_id_text and case_id_text not in case_ids:
                issues.append({"severity": "blocker", "code": "FP_CONSUMPTION_UNKNOWN_CASE_ID", "message": f"{fp_id} 回执引用了不存在的用例：{case_id_text}"})
            elif case_id_text and source_id and case_source_by_id.get(case_id_text) != source_id:
                issues.append({"severity": "blocker", "code": "FP_CONSUMPTION_CASE_SOURCE_MISMATCH", "message": f"{fp_id} 回执引用了其他 source 的用例：{case_id_text}"})
    if not isinstance(method_consumptions, list):
        issues.append({"severity": "blocker", "code": "METHOD_CONSUMPTION_BAD_TYPE", "message": "method_consumption 必须是数组"})
        method_consumptions = []
    method_keys: set[tuple[str, str]] = set()
    for item in method_consumptions:
        if not isinstance(item, dict):
            issues.append({"severity": "blocker", "code": "BAD_METHOD_CONSUMPTION_ITEM", "message": "method_consumption 包含非对象项"})
            continue
        source_id = str(item.get("source_id") or "").strip()
        method = str(item.get("method") or "").strip()
        result = str(item.get("consumption_result") or item.get("result") or "").strip()
        method_keys.add((source_id, method))
        if source_id not in source_ids:
            issues.append({"severity": "blocker", "code": "METHOD_UNKNOWN_SOURCE", "message": f"method_consumption 引用了未知 source_id：{source_id}"})
        if not method:
            issues.append({"severity": "blocker", "code": "METHOD_CONSUMPTION_MISSING_METHOD", "message": f"{source_id} method_consumption 缺少 method"})
        if result not in _TRUSTED_TESTCASE_RESULTS:
            issues.append({"severity": "blocker", "code": "BAD_METHOD_CONSUMPTION_RESULT", "message": f"{source_id}/{method} result 非法：{result}"})
        refs = item.get("case_refs") if isinstance(item.get("case_refs"), list) else item.get("case_ids")
        refs = refs if isinstance(refs, list) else []
        if result == "covered_by_case" and not refs:
            issues.append({"severity": "blocker", "code": "METHOD_CONSUMPTION_MISSING_CASE_REFS", "message": f"{source_id}/{method} 标记为已覆盖但 case_refs 为空"})
        if result == "covered_by_case" and refs and not any(method in case_methods_by_id.get(str(case_id).strip(), set()) for case_id in refs):
            issues.append({"severity": "blocker", "code": "METHOD_CLAIM_NOT_DEMONSTRATED", "message": f"{source_id}/{method} 声明已覆盖，但引用用例未使用该设计方法"})
        if result in {"merged_into_case", "blocked_by_pending_confirmation", "not_applicable"} and not str(item.get("reason") or item.get("merge_reason") or item.get("note") or "").strip():
            issues.append({"severity": "blocker", "code": "METHOD_CONSUMPTION_MISSING_REASON", "message": f"{source_id}/{method} 未直接覆盖但缺少说明"})
        for case_id in refs:
            case_id_text = str(case_id).strip()
            if case_id_text and case_id_text not in case_ids:
                issues.append({"severity": "blocker", "code": "METHOD_CONSUMPTION_UNKNOWN_CASE_ID", "message": f"{source_id}/{method} 引用了不存在的用例：{case_id_text}"})
            elif case_id_text and source_id and case_source_by_id.get(case_id_text) != source_id:
                issues.append({"severity": "blocker", "code": "METHOD_CONSUMPTION_CASE_SOURCE_MISMATCH", "message": f"{source_id}/{method} 引用了其他 source 的用例：{case_id_text}"})
    must_cover_gaps: list[dict] = []
    method_gaps: list[dict] = []
    for source_id, source in source_by_id.items():
        profile = source.get("test_design_profile") if isinstance(source.get("test_design_profile"), dict) else {}
        source_text = "；".join(case_text_by_source.get(source_id) or [])
        for obligation in profile.get("must_cover") or []:
            obligation_text = str(obligation or "").strip()
            if not obligation_text:
                continue
            if obligation_text in must_cover_refs_by_source.get(source_id, set()):
                continue
            if not source_case_count.get(source_id):
                gap = {"source_id": source_id, "must_cover": obligation_text, "reason": "source 没有用例覆盖"}
                must_cover_gaps.append(gap)
                issues.append({"severity": "blocker", "code": "MUST_COVER_NOT_COVERED", "message": f"{source_id} must_cover 未覆盖：{obligation_text}"})
            elif obligation_text not in source_text:
                gap = {"source_id": source_id, "must_cover": obligation_text, "reason": "用例未声明 must_cover_refs，且步骤/预期中无可复算覆盖文本"}
                must_cover_gaps.append(gap)
                issues.append({"severity": "blocker", "code": "MUST_COVER_NOT_COVERED", "message": f"{source_id} must_cover 未覆盖：{obligation_text}"})
        for method in profile.get("applicable_methods") or []:
            method_text = str(method or "").strip()
            if method_text and (source_id, method_text) not in method_keys:
                gap = {"source_id": source_id, "method": method_text, "reason": "method_consumption 未声明"}
                method_gaps.append(gap)
                issues.append({"severity": "blocker", "code": "METHOD_NOT_CONSUMED", "message": f"{source_id} 适用方法未消费：{method_text}"})
    covered_fp_count = len(
        [
            item for item in consumptions
            if isinstance(item, dict) and str(item.get("consumption_result") or item.get("result") or "") in {"covered_by_case", "merged_into_case"}
        ]
    )
    return {
        "gate": "testcase_gate",
        "passed": not any(item["severity"] == "blocker" for item in issues),
        "issues": issues,
        "recovery_plan": _trusted_gate_recovery_plan("testcase_gate", issues),
        "source_case_count": dict(source_case_count),
        "must_cover_gaps": must_cover_gaps,
        "method_gaps": method_gaps,
        "covered_source_count": len(covered_sources),
        "covered_fp_count": covered_fp_count,
        "testcase_count": len([item for item in testcases if isinstance(item, dict)]),
    }


_TRUSTED_HANDOFF_GATE_CONTRACT = json.dumps(
    {
        "metadata": {"reviewer": "review-pipeline-handoff", "version": "trusted-v2"},
        "review_stage": "scope_index_gate|requirement_gate|testcase_gate",
        "passed": True,
        "decision": "pass|return",
        "expected_sources": ["SRC-001"],
        "completed_sources": ["SRC-001"],
        "missing_sources": [],
        "duplicate_sources": [],
        "checked_items": [{"item": "source consumption", "result": "pass", "note": ""}],
        "blocking_issues": [{"source_id": "SRC-001", "severity": "blocker", "message": ""}],
        "return_to": "",
        "return_reason": "",
    },
    ensure_ascii=False,
)

_TRUSTED_ADVISORY_ISSUE_CODES = {
    "NORMALIZATION_NOTE",
}


def _normalize_trusted_gate_issues(gate_name: str, issues: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        item = dict(issue)
        code = str(item.get("code") or "").strip()
        original_severity = str(item.get("severity") or "blocker").strip() or "blocker"
        item["original_severity"] = original_severity
        if code in _TRUSTED_ADVISORY_ISSUE_CODES:
            item["severity"] = "warning"
            item.setdefault("risk_type", "coverage_or_review_warning")
        else:
            item["severity"] = original_severity
        item.setdefault("gate", gate_name)
        normalized.append(item)
    return normalized


def _trusted_source_ids_list(scope_index: dict) -> list[str]:
    return sorted(_trusted_v2_source_ids(scope_index))


def _trusted_completed_requirement_sources(requirement_handoff: dict) -> list[str]:
    completed: set[str] = set()
    for item in requirement_handoff.get("scope_index_consumption") or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        result = str(item.get("result") or "").strip()
        if source_id and result:
            completed.add(source_id)
    return sorted(completed)


def _trusted_completed_testcase_sources(testcase_handoff: dict) -> list[str]:
    completed: set[str] = set()
    for case in testcase_handoff.get("testcases") or []:
        if isinstance(case, dict) and str(case.get("source_id") or "").strip():
            completed.add(str(case.get("source_id") or "").strip())
    for item in testcase_handoff.get("feature_point_consumption") or []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        result = str(item.get("result") or "").strip()
        if source_id and result in {"covered_by_case", "merged_into_case", "blocked_by_pending_confirmation", "not_applicable"}:
            completed.add(source_id)
    return sorted(completed)


def _validate_trusted_model_handoff_gate(result: dict, expected_stage: str) -> dict:
    if not isinstance(result, dict):
        raise ValueError("模型 handoff gate 输出必须是 JSON 对象")
    review_stage = str(result.get("review_stage") or "").strip()
    if review_stage != expected_stage:
        raise ValueError(f"模型 handoff gate review_stage 应为 {expected_stage}，实际为 {review_stage or '空'}")
    if not isinstance(result.get("passed"), bool):
        raise ValueError("模型 handoff gate 必须包含布尔 passed")
    decision = str(result.get("decision") or "").strip()
    if decision not in {"pass", "return"}:
        raise ValueError("模型 handoff gate decision 必须是 pass 或 return")
    for key in ("expected_sources", "completed_sources", "missing_sources", "duplicate_sources", "checked_items", "blocking_issues"):
        if not isinstance(result.get(key), list):
            raise ValueError(f"模型 handoff gate {key} 必须是数组")
    if result["passed"] and decision != "pass":
        raise ValueError("模型 handoff gate passed=true 时 decision 必须为 pass")
    if not result["passed"] and decision != "return":
        raise ValueError("模型 handoff gate passed=false 时 decision 必须为 return")
    result.setdefault("metadata", {"reviewer": "review-pipeline-handoff", "version": "trusted-v2"})
    result.setdefault("return_to", "")
    result.setdefault("return_reason", "")
    return result


def _trusted_gate_recovery_plan(gate_name: str, issues: list[dict]) -> dict:
    source_ids: set[str] = set()
    fp_ids: set[str] = set()
    case_ids: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        text = " ".join(str(issue.get(key) or "") for key in ("message", "source_id", "fp_id", "case_id"))
        source_ids.update(re.findall(r"SRC-[A-Za-z0-9_-]+", text))
        fp_ids.update(re.findall(r"FP-[A-Za-z0-9_-]+", text))
        case_ids.update(re.findall(r"TC-[A-Za-z0-9_-]+", text))
        if issue.get("source_id"):
            source_ids.add(str(issue.get("source_id")).strip())
        if issue.get("shard_id"):
            shard_source = re.sub(r"^SHARD-", "", str(issue.get("shard_id")).strip())
            if shard_source.startswith("SRC-"):
                source_ids.add(shard_source)
        if issue.get("fp_id"):
            fp_ids.add(str(issue.get("fp_id")).strip())
        for fp_id in issue.get("fp_ids") or []:
            if str(fp_id).strip():
                fp_ids.add(str(fp_id).strip())
        if issue.get("case_id"):
            case_ids.add(str(issue.get("case_id")).strip())

    return_to_by_gate = {
        "scope_index_gate": "scope_index",
        "requirement_gate": "requirement",
        "testcase_gate": "testcase_by_source_shard",
        "final_delivery_gate": "export",
    }
    regenerate_by_gate = {
        "scope_index_gate": ["scope_index", "requirement_handoff", "testcase_package", "trusted_review_report", "xmindmark", "xmind"],
        "requirement_gate": ["requirement_handoff", "testcase_package", "trusted_review_report", "xmindmark", "xmind"],
        "testcase_gate": ["testcase_package", "trusted_review_report", "xmindmark", "xmind"],
        "final_delivery_gate": ["xmindmark", "xmind", "final_delivery_gate"],
    }
    if not issues:
        return {
            "strategy": "none",
            "return_to": "",
            "rerun_scope": {"source_ids": [], "shard_ids": [], "fp_ids": [], "case_ids": []},
            "preserve_artifacts": ["source_manifest", "evidence_trace", "scope_index", "function_points", "testcase_package"],
            "regenerate_artifacts": [],
        }
    scoped = bool(source_ids or fp_ids or case_ids)
    return {
        "strategy": "local_rerun" if scoped and gate_name in {"requirement_gate", "testcase_gate"} else "stage_rerun",
        "return_to": return_to_by_gate.get(gate_name, gate_name),
        "rerun_scope": {
            "source_ids": sorted(source_ids),
            "shard_ids": [f"SHARD-{source_id}" for source_id in sorted(source_ids)],
            "fp_ids": sorted(fp_ids),
            "case_ids": sorted(case_ids),
        },
        "preserve_artifacts": ["source_manifest", "evidence_trace"],
        "regenerate_artifacts": regenerate_by_gate.get(gate_name, []),
    }


def _build_trusted_model_handoff_gate(
    *,
    review_stage: str,
    deterministic_gate: dict,
    scope_index: dict,
    requirement_handoff: dict | None = None,
    testcase_handoff: dict | None = None,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    requirement_handoff = requirement_handoff or {}
    testcase_handoff = testcase_handoff or {}
    expected_sources = _trusted_source_ids_list(scope_index)
    completed_sources = expected_sources
    gate_focus = [
        "判断上游交接产物是否真的足够支撑下一阶段，不只检查字段存在。",
        "发现遗漏、伪覆盖、伪疑问、明显重复或无法观察的覆盖时必须返回 return。",
        "不要因为后端结构校验通过就自动通过；请独立审查语义完整性。",
    ]
    if review_stage == "requirement_gate":
        completed_sources = _trusted_completed_requirement_sources(requirement_handoff)
        gate_focus.extend(
            [
                "每个 direct source 必须被转为功能点、合并、阻塞或判定不适用，且说明可审计。",
                "功能点必须能追溯到 source，不能把依赖材料误当直接测试对象。",
            ]
        )
    elif review_stage == "testcase_gate":
        completed_sources = _trusted_completed_testcase_sources(testcase_handoff)
        gate_focus.extend(
            [
                "每个功能点必须被用例覆盖、合并覆盖、阻塞或判定不适用，且回执不能空泛。",
                "每个 source 的 must_cover 和 applicable_methods 必须被消费、合并或说明不适用。",
                "用例步骤和预期必须能观察，不允许把待确认问题写成确定预期。",
                "明显同构重复、方法未消费或 must_cover 缺口必须作为 blocking_issues 返回。",
            ]
        )
    else:
        gate_focus.extend(
            [
                "scope_index 必须覆盖文档中的直接可测功能，而不是背景章节或纯依赖说明。",
                "图片、字段表、AC、规则说明应绑定到对应 source，并形成 test_design_profile。",
            ]
        )

    payload = {
        "task": "执行 trusted_v2 handoff review gate。只输出 JSON，不输出 Markdown。",
        "review_stage": review_stage,
        "expected_sources": expected_sources,
        "completed_sources": completed_sources,
        "deterministic_gate": deterministic_gate,
        "gate_focus": gate_focus,
        "scope_index": scope_index,
        "requirement_handoff": requirement_handoff,
        "testcase_handoff": testcase_handoff,
        "decision_rules": [
            "passed=true 仅当当前阶段产物足够交给下一阶段。",
            "存在遗漏、不可追溯、无法执行、方法未消费、伪疑问或伪覆盖时 passed=false。",
            "blocking_issues 必须写清 source_id 或 fp_id、问题、应退回的阶段。",
        ],
    }

    call_kwargs = {
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "skill_name": "review-pipeline-handoff",
        "task_payload": payload,
        "output_contract": _TRUSTED_HANDOFF_GATE_CONTRACT,
        "validator": lambda result: _validate_trusted_model_handoff_gate(result, review_stage),
        "max_tokens": 6000,
        "timeout_seconds": _LONG_CHAT_TIMEOUT_SECONDS,
        "max_attempts": 2,
    }
    if "mode" in inspect.signature(_call_skill_with_gate).parameters:
        call_kwargs["mode"] = "trusted"
    return _call_skill_with_gate(**call_kwargs)


def _combine_trusted_gate(deterministic_gate: dict, model_gate: dict | None = None) -> dict:
    combined = dict(deterministic_gate or {})
    deterministic_issues = [item for item in (deterministic_gate or {}).get("issues") or [] if isinstance(item, dict)]
    model_issues: list[dict] = []
    if model_gate:
        for item in model_gate.get("blocking_issues") or []:
            if not isinstance(item, dict):
                continue
            message = str(item.get("message") or item.get("note") or item).strip()
            model_issues.append(
                {
                    "severity": "blocker",
                    "model_severity": item.get("severity") or "blocker",
                    "code": "MODEL_HANDOFF_REVIEW_BLOCKER",
                    "message": message,
                    "source_id": item.get("source_id"),
                    "fp_id": item.get("fp_id"),
                }
            )
    deterministic_passed = bool((deterministic_gate or {}).get("passed"))
    model_passed = True if model_gate is None else bool(model_gate.get("passed"))
    gate_name = str(combined.get("gate") or "")
    combined["issues"] = _normalize_trusted_gate_issues(gate_name, deterministic_issues + model_issues)
    combined["blocking_issues"] = [item for item in combined["issues"] if item.get("severity") == "blocker"]
    combined["warning_issues"] = [item for item in combined["issues"] if item.get("severity") == "warning"]
    combined["passed"] = deterministic_passed and model_passed and not combined["blocking_issues"]
    combined["status"] = "pass" if combined["passed"] and not combined["warning_issues"] else ("warning" if combined["passed"] else "fail")
    combined["issue_counts"] = {
        "blocker": len(combined["blocking_issues"]),
        "warning": len(combined["warning_issues"]),
        "total": len(combined["issues"]),
    }
    combined["recovery_plan"] = _trusted_gate_recovery_plan(str(combined.get("gate") or ""), combined["issues"])
    combined["deterministic_passed"] = deterministic_passed
    combined["model_passed"] = model_passed
    combined["model_gate_applied"] = model_gate is not None
    if model_gate:
        combined["model_decision"] = model_gate.get("decision")
        combined["model_return_to"] = model_gate.get("return_to")
        combined["model_return_reason"] = model_gate.get("return_reason")
        combined["model_checked_item_count"] = len(model_gate.get("checked_items") or [])
    return combined


def _run_trusted_combined_gate(
    *,
    review_stage: str,
    deterministic_gate: dict,
    scope_index: dict,
    requirement_handoff: dict | None = None,
    testcase_handoff: dict | None = None,
    api_key: str,
    model: str,
    base_url: str,
) -> tuple[dict, dict | None]:
    if not deterministic_gate.get("passed"):
        return _combine_trusted_gate(deterministic_gate, None), None
    if not _TRUSTED_MODEL_GATE_ENABLED:
        return _combine_trusted_gate(deterministic_gate, None), None
    model_gate = _build_trusted_model_handoff_gate(
        review_stage=review_stage,
        deterministic_gate=deterministic_gate,
        scope_index=scope_index,
        requirement_handoff=requirement_handoff,
        testcase_handoff=testcase_handoff,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    return _combine_trusted_gate(deterministic_gate, model_gate), model_gate


def _trusted_gate_success_summary(label: str, gate: dict) -> str:
    counts = gate.get("issue_counts") or {}
    warning_count = int(counts.get("warning") or 0)
    summary = f"{label}通过：后端确定性校验通过"
    if gate.get("model_gate_applied"):
        if gate.get("model_passed"):
            summary += "，模型交接审查通过"
        else:
            summary += "，模型交接审查提出风险"
    if warning_count:
        summary += f"，保留 {warning_count} 项风险提示"
    return summary


def _build_trusted_review_report(
    scope_index: dict,
    requirement_handoff: dict,
    testcase_handoff: dict,
    scope_index_gate: dict,
    requirement_gate: dict,
    testcase_gate: dict,
    *,
    semantic_review: dict | None = None,
    standard_review_report: dict | None = None,
    quality_summary: dict | None = None,
) -> dict:
    standard_review_report = standard_review_report or semantic_review or {}
    source_items = _trusted_scope_source_items(scope_index)
    source_count = len(source_items)
    fp_count = len(requirement_handoff.get("function_points") or [])
    case_count = len(testcase_handoff.get("testcases") or [])
    fp_consumed = testcase_gate.get("covered_fp_count") or 0
    covered_sources = testcase_gate.get("covered_source_count") or 0
    merged_count = len(
        [
            item for item in testcase_handoff.get("feature_point_consumption") or []
            if isinstance(item, dict) and item.get("result") == "merged_into_case"
        ]
    )
    pending_count = len(requirement_handoff.get("pending_confirmations") or [])
    gate_passed = bool(scope_index_gate.get("passed") and requirement_gate.get("passed") and testcase_gate.get("passed"))
    combined_gates = [scope_index_gate, requirement_gate, testcase_gate]
    gate_warning_count = sum(len(gate.get("warning_issues") or []) for gate in combined_gates)
    gate_blocker_count = sum(len(gate.get("blocking_issues") or []) for gate in combined_gates)
    model_gate_applied_count = len([gate for gate in combined_gates if gate.get("model_gate_applied")])
    model_gate_failed_count = len([gate for gate in combined_gates if gate.get("model_gate_applied") and not gate.get("model_passed")])
    # per-source breakdown
    source_case_count: dict = testcase_gate.get("source_case_count") or {}
    fp_by_source: dict[str, list] = {}
    for fp in requirement_handoff.get("function_points") or []:
        if not isinstance(fp, dict):
            continue
        sid = str(fp.get("source_id") or "").strip()
        fp_by_source.setdefault(sid, []).append(fp.get("fp_id") or "")
    consumptions_by_source: dict[str, list] = {}
    for item in testcase_handoff.get("feature_point_consumption") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("source_id") or "").strip()
        consumptions_by_source.setdefault(sid, []).append(item)
    gate_issues_by_source: dict[str, list] = {}
    for gate in [scope_index_gate, requirement_gate, testcase_gate]:
        for issue in gate.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            msg = str(issue.get("message") or "")
            # try to match a SRC-xxx prefix in the message
            match = re.search(r"SRC-[A-Za-z0-9_-]+", msg)
            if match:
                sid = match.group()
                gate_issues_by_source.setdefault(sid, []).append({"severity": issue.get("severity"), "message": msg})
    shard_by_source: dict[str, dict] = {}
    for shard in testcase_handoff.get("testcase_shards") or []:
        if not isinstance(shard, dict):
            continue
        sid = str(shard.get("source_id") or "").strip()
        if sid:
            shard_by_source[sid] = shard
    sources_detail = []
    must_cover_gaps = [item for item in testcase_gate.get("must_cover_gaps") or [] if isinstance(item, dict)]
    method_gaps = [item for item in testcase_gate.get("method_gaps") or [] if isinstance(item, dict)]
    must_cover_gap_sources = {str(item.get("source_id") or "").strip() for item in must_cover_gaps}
    method_gap_sources = {str(item.get("source_id") or "").strip() for item in method_gaps}
    for src in source_items:
        if not isinstance(src, dict):
            continue
        sid = str(src.get("source_id") or "").strip()
        src_fps = fp_by_source.get(sid, [])
        src_consumptions = consumptions_by_source.get(sid, [])
        merge_count = len([c for c in src_consumptions if str(c.get("result") or "") == "merged_into_case"])
        shard = shard_by_source.get(sid) or {}
        sources_detail.append({
            "source_id": sid,
            "title": str(src.get("title") or "").strip(),
            "title_path": str(src.get("title_path") or "").strip(),
            "fp_count": len(src_fps),
            "actual_case_count": source_case_count.get(sid, 0),
            "must_cover_status": "gap" if sid in must_cover_gap_sources else "covered",
            "method_consumption_status": "gap" if sid in method_gap_sources else "covered",
            "merge_count": merge_count,
            "shard_status": shard.get("status") or "unknown",
            "shard_error": shard.get("error") or shard.get("skip_reason") or "",
            "gate_issues": gate_issues_by_source.get(sid, []),
        })
    summary_payload = {
        "source_count": source_count,
        "function_point_count": fp_count,
        "testcase_count": case_count,
        "function_point_receipt_rate": round(fp_consumed / fp_count, 4) if fp_count else 0,
        "source_with_testcase_rate": round(covered_sources / source_count, 4) if source_count else 0,
        # Legacy aliases remain for historical clients; their labels must not claim semantic coverage.
        "function_point_consumption_rate": round(fp_consumed / fp_count, 4) if fp_count else 0,
        "source_coverage_rate": round(covered_sources / source_count, 4) if source_count else 0,
        "merged_coverage_count": merged_count,
        "duplicate_case_count": testcase_handoff.get("duplicate_case_count") or 0,
        "must_cover_gap_count": len(must_cover_gaps),
        "method_gap_count": len(method_gaps),
        "pending_confirmation_count": pending_count,
        "gate_passed": gate_passed,
        "gate_warning_count": gate_warning_count,
        "gate_blocker_count": gate_blocker_count,
        "model_gate_applied_count": model_gate_applied_count,
        "model_gate_failed_count": model_gate_failed_count,
        "combined_gate_passed": gate_passed,
        "release_readiness": "pass" if gate_passed and pending_count == 0 and gate_warning_count == 0 else ("conditional_pass" if gate_passed else "fail"),
    }
    if standard_review_report:
        semantic_summary = standard_review_report.get("summary") or {}
        summary_payload.update(
            {
                "semantic_release_readiness": semantic_summary.get("release_readiness"),
                "ambiguous_step_count": semantic_summary.get("ambiguous_step_count", 0),
                "unverifiable_expectation_count": semantic_summary.get("unverifiable_expectation_count", 0),
                "semantic_duplicate_count": semantic_summary.get("duplicate_count", 0),
                "overall_score": semantic_summary.get("overall_score", 0),
            }
        )
    if quality_summary:
        summary_payload.update(
            {
                "weak_expected_count": quality_summary.get("weak_expected_count", 0),
                "weak_step_count": quality_summary.get("weak_step_count", 0),
                "template_title_count": quality_summary.get("template_title_count", 0),
                "evidence_coverage_rate": quality_summary.get("evidence_coverage_rate", 0),
                "source_traceability_rate": quality_summary.get("source_traceability_rate", quality_summary.get("evidence_coverage_rate", 0)),
                "assertion_basis_rate": quality_summary.get("assertion_basis_rate", 0),
                "concrete_image_evidence_rate": quality_summary.get("concrete_image_evidence_rate", 0),
            }
        )
    if standard_review_report:
        semantic_summary = standard_review_report.get("summary") or {}
        summary_payload.update(
            {
                "unsupported_assertion_count": semantic_summary.get("unsupported_assertion_count", 0),
                "evidence_mismatch_count": semantic_summary.get("evidence_mismatch_count", 0),
                "current_state_as_expected_count": semantic_summary.get("current_state_as_expected_count", 0),
                "exact_value_loss_count": semantic_summary.get("exact_value_loss_count", 0),
            }
        )
    must_cover_total = sum(
        len((item.get("test_design_profile") or {}).get("must_cover") or [])
        for item in source_items
        if isinstance(item, dict)
    )
    summary_payload["must_cover_total_count"] = must_cover_total
    summary_payload["semantic_must_cover_rate"] = (
        round(max(must_cover_total - len(must_cover_gaps), 0) / must_cover_total, 4)
        if must_cover_total
        else None
    )
    semantic_readiness = str(summary_payload.get("semantic_release_readiness") or "conditional_pass")
    if not gate_passed:
        summary_payload["release_readiness"] = "fail"
    elif (
        semantic_readiness != "pass"
        or pending_count > 0
        or must_cover_gaps
        or method_gaps
        or gate_warning_count > 0
    ):
        summary_payload["release_readiness"] = "conditional_pass"
    else:
        summary_payload["release_readiness"] = "pass"
    return {
        "summary": summary_payload,
        "gates": [scope_index_gate, requirement_gate, testcase_gate],
        "scope_index_risks": scope_index.get("index_risks") or [],
        "pending_confirmations": requirement_handoff.get("pending_confirmations") or [],
        "duplicate_case_groups": testcase_handoff.get("duplicate_case_groups") or [],
        "quality_summary": quality_summary or {},
        "standard_review_report": standard_review_report,
        "semantic_review": standard_review_report,
        "method_coverage": standard_review_report.get("method_coverage") or {},
        "dimension_matrix": standard_review_report.get("dimension_matrix") or {},
        "semantic_findings": standard_review_report.get("findings") or [],
        "sources_detail": sources_detail,
    }


def _build_trusted_delivery_markdown(job: CaseGenerationV2Job, review_report: dict, testcase_handoff: dict) -> str:
    summary = review_report.get("summary") or {}
    cases = [item for item in testcase_handoff.get("testcases") or [] if isinstance(item, dict)]
    priority_counts = Counter(str(case.get("priority") or "P1").strip().upper() for case in cases)
    lines = [
        f"# {job.name} - 可信改进模式交付摘要",
        "",
        f"- 直接测试对象数：{summary.get('source_count', 0)}",
        f"- 功能点总数：{summary.get('function_point_count', 0)}",
        f"- 用例总数：{summary.get('testcase_count', 0)}",
        f"- P0 数量：{priority_counts.get('P0', 0)}",
        f"- P1 数量：{priority_counts.get('P1', 0)}",
        f"- P2 数量：{priority_counts.get('P2', 0)}",
        f"- P3 数量：{priority_counts.get('P3', 0)}",
        f"- FP 回执完整率：{summary.get('function_point_receipt_rate', summary.get('function_point_consumption_rate', 0)):.0%}",
        f"- Source 有用例率：{summary.get('source_with_testcase_rate', summary.get('source_coverage_rate', 0)):.0%}",
        f"- 结构追溯完整率：{summary.get('source_traceability_rate', 0):.0%}",
        f"- 预期依据完整率：{summary.get('assertion_basis_rate', 0):.0%}",
        f"- 图片证据用例率：{summary.get('concrete_image_evidence_rate', 0):.0%}",
        f"- 合并覆盖数：{summary.get('merged_coverage_count', 0)}",
        f"- must_cover 缺口数：{summary.get('must_cover_gap_count', 0)}",
        f"- 方法消费缺口数：{summary.get('method_gap_count', 0)}",
        f"- 待确认数量：{summary.get('pending_confirmation_count', 0)}",
        f"- 门禁阻断数：{summary.get('gate_blocker_count', 0)}",
        f"- 门禁风险提示数：{summary.get('gate_warning_count', 0)}",
        f"- 无依据断言数：{summary.get('unsupported_assertion_count', 0)}",
        f"- 证据错绑数：{summary.get('evidence_mismatch_count', 0)}",
        f"- 旧状态误作目标预期数：{summary.get('current_state_as_expected_count', 0)}",
        f"- 精确验收值丢失数：{summary.get('exact_value_loss_count', 0)}",
        f"- 结构门禁：{'通过' if summary.get('gate_passed') else '未通过'}",
        f"- 语义结论：{summary.get('release_readiness') or '待确认'}",
        "",
        "## 测试用例",
        "",
    ]
    for case in cases:
        if not isinstance(case, dict):
            continue
        lines.append(f"### {case.get('case_id')} {case.get('title')}")
        lines.append(f"- source_id：{case.get('source_id')}")
        lines.append(f"- fp_id：{case.get('fp_id')}")
        lines.append(f"- 优先级：{case.get('priority') or 'P2'}")
        steps = case.get("steps") or []
        if steps:
            lines.append("- 步骤：")
            for step in steps:
                if isinstance(step, dict):
                    lines.append(f"  {step.get('step_no') or '-'}：{step.get('action') or ''}")
                else:
                    lines.append(f"  - {step}")
        expected = case.get("expected_results") or []
        if expected:
            lines.append("- 预期：")
            for item in expected:
                lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _trusted_method_for_case(case: dict, fp: dict | None = None) -> str:
    category = _normalize_category(case.get("category"))
    title_text = _compact_case_text([case.get("title"), case.get("expected_results"), case.get("steps")]).lower()
    intent = str((fp or {}).get("coverage_intent") or "").lower()
    if category == "boundary" or "边界" in title_text:
        return "boundary"
    if category == "negative" or intent in {"negative", "error"} or _text_contains_any(title_text, ("异常", "错误", "失败", "无效")):
        return "error_tolerance"
    if category == "ui":
        return "ui_interaction"
    if category == "regression":
        return "regression"
    if _text_contains_any(title_text, ("状态", "切换", "开关", "打开", "关闭")):
        return "state_transition"
    if _text_contains_any(title_text, ("入口", "模块", "campaign", "ad set", "creative", "product", "report")):
        return "entry_consistency"
    return "equivalence"


def _trusted_standard_function_points(scope_index: dict, requirement_handoff: dict) -> dict:
    source_order = {
        str(item.get("source_id") or "").strip(): item.get("source_order", index)
        for index, item in enumerate(_trusted_scope_source_items(scope_index), start=1)
        if isinstance(item, dict)
    }
    source_by_id = _trusted_source_by_id(scope_index)
    fps: list[dict] = []
    for index, fp in enumerate(requirement_handoff.get("function_points") or [], start=1):
        if not isinstance(fp, dict):
            continue
        item = dict(fp)
        sid = str(item.get("source_id") or "").strip()
        source = source_by_id.get(sid) or {}
        source_title = str(source.get("title") or item.get("source_title") or "可信范围").strip()
        title_path = str(source.get("title_path") or source_title).strip()
        item["module"] = source.get("module") or item.get("module") or source_title or "可信范围"
        item["scene"] = source.get("scene") or item.get("scene") or source_title or item.get("title") or "可信场景"
        item["title_path"] = title_path
        item["source_title"] = source_title
        item["shard_id"] = source.get("shard_id") or item.get("shard_id") or (f"SHARD-{sid}" if sid else "")
        item["source_node_title"] = source.get("xmind_source_node") or (f"{sid}｜{title_path}" if sid else title_path)
        item["source_order"] = source_order.get(sid, index)
        item["source_order_index"] = source.get("source_order_index") or index
        item.setdefault("source_refs", [])
        fps.append(item)
    return {
        "version": "trusted-v2",
        "project": "trusted_v2",
        "source_documents": [],
        "function_points": sorted(fps, key=lambda item: (_trusted_source_order_key(item.get("source_order"), item.get("source_order_index", 0)), item.get("fp_id") or "")),
    }


def _trusted_standard_testcase_package(requirement_handoff: dict, testcase_handoff: dict) -> dict:
    fp_by_id = {
        str(item.get("fp_id") or "").strip(): item
        for item in requirement_handoff.get("function_points") or []
        if isinstance(item, dict)
    }
    cases: list[dict] = []
    for case in testcase_handoff.get("testcases") or []:
        if not isinstance(case, dict):
            continue
        item = dict(case)
        fp = fp_by_id.get(str(item.get("fp_id") or "").strip()) or {}
        fp_ids = item.get("fp_ids")
        if not isinstance(fp_ids, list) or not fp_ids:
            traceability = item.get("traceability") if isinstance(item.get("traceability"), dict) else {}
            fp_ids = traceability.get("function_points") if isinstance(traceability.get("function_points"), list) else []
            if not fp_ids and item.get("fp_id"):
                fp_ids = [item.get("fp_id")]
            item["fp_ids"] = [str(fp_id).strip() for fp_id in fp_ids if str(fp_id).strip()]
        item.setdefault("shard_id", fp.get("shard_id") or f"SHARD-{str(item.get('source_id') or 'UNKNOWN').replace('SRC-', '').zfill(3)}")
        for forbidden_key in ("module", "scene", "source_order", "source_order_index", "title_path", "description", "rules"):
            item.pop(forbidden_key, None)
        item["category"] = _normalize_category(item.get("category"))
        item.setdefault("test_data", [])
        item.setdefault("scenario_dimensions", [item["category"]])
        item.setdefault("baseline_candidate", item["category"] in {"functional", "regression"})
        item.pop("traceability", None)
        basis = item.get("generation_basis") if isinstance(item.get("generation_basis"), dict) else {}
        basis.setdefault("method", _trusted_method_for_case(item, fp))
        basis.pop("rationale", None)
        item["generation_basis"] = basis
        cases.append(item)
    return {
        "requirements_input_consumption": testcase_handoff.get("requirements_input_consumption") or [],
        "feature_point_consumption": testcase_handoff.get("feature_point_consumption") or [],
        "source_case_summary": testcase_handoff.get("source_case_summary") or [],
        "method_consumption": testcase_handoff.get("method_consumption") or [],
        "testcases": cases,
        "xmind_grouping_contract": _trusted_xmind_grouping_contract(),
    }


def _trusted_evidence_trace(
    *,
    image_links: list[str] | None = None,
    downloaded_images: list[dict] | None = None,
    image_analysis: list[dict] | None = None,
    pending_confirmations: list | None = None,
) -> dict:
    downloaded_images = downloaded_images or []
    return {
        "image_link_count": len(image_links or []),
        "download_success_count": sum(1 for item in downloaded_images if item.get("download_status") == "success"),
        "download_failed_count": sum(1 for item in downloaded_images if item.get("download_status") == "failed"),
        "pending_confirmation_count": len(pending_confirmations or []),
        "status": "complete",
        "image_analysis": image_analysis or [],
    }


def _build_trusted_semantic_review(
    evidence_trace: dict,
    function_points: dict,
    testcase_package: dict,
    pending_confirmations: list,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict:
    source_bundles: dict[str, dict] = {}
    for fp in function_points.get("function_points") or []:
        if not isinstance(fp, dict):
            continue
        source_id = str(fp.get("source_id") or "").strip()
        if not source_id:
            continue
        bundle = source_bundles.setdefault(
            source_id,
            {
                "source_id": source_id,
                "title_path": fp.get("title_path") or "",
                "source_excerpt": fp.get("source_excerpt") or "",
                "image_refs": fp.get("image_refs") or [],
                "image_evidence": fp.get("image_evidence") or [],
                "source_state_semantics": fp.get("source_state_semantics") or {},
                "function_points": [],
            },
        )
        bundle["function_points"].append(
            {
                "fp_id": fp.get("fp_id"),
                "title": fp.get("title"),
                "description": fp.get("description"),
                "rules": fp.get("rules") or [],
                "source_quotes": fp.get("source_quotes") or [],
                "source_quote_roles": fp.get("source_quote_roles") or [],
                "target_evidence_refs": fp.get("target_evidence_refs") or [],
            }
        )
    prompt = {
        "task": "按 trusted quality-reviewer 规则审查用例，并逐条核对需求原文和图片证据。只输出 JSON。",
        "source_evidence_bundles": list(source_bundles.values()),
        "testcase_package": testcase_package,
        "evidence_trace_summary": {
            key: evidence_trace.get(key)
            for key in ("image_link_count", "download_success_count", "download_failed_count", "pending_confirmation_count", "status")
        },
        "pending_confirmations": pending_confirmations,
        "constraints": [
            "逐条审查 expected_results：位置、边框、颜色、字段名、精确文案、尺寸、顺序、状态流转等具体断言，必须能由同 source 的 source_excerpt 或 image_evidence 直接支持。",
            "目标性措辞如‘优化、提高可见性、合理、正常’不能自动推导出具体实现；自行推导必须记录 type=unsupported_assertion，severity=high。",
            "source_state_semantics 标为 current 的文本/图片是改造前状态。若用例把 current 旧位置、旧样式或旧行为写成正向 expected_result，记录 type=current_state_as_expected，severity=critical；只有‘不再出现/改为’等负向回归断言可引用 current。",
            "有 current/target 对照时必须逐项比较 target_text/target_image_refs；禁止因为 current 文本更清晰就忽略 target 图片。",
            "evidence_refs 引用不属于该 source 的图片时记录 type=evidence_mismatch，severity=high。",
            "需求提供精确文案、字段顺序、数值边界或状态矩阵，而用例退化为‘文案正确、符合表格、功能正常、一致’时，记录 type=exact_value_loss，severity=medium。",
            "验证 method_coverage 时只检查 source 的 applicable method 是否真实落到步骤、数据和预期；与需求无关的方法缺失不得扣分。",
            "角色、环境、性能等维度只有需求或风险信号明确适用时才可判 missing，否则标 not_applicable。",
            "存在 high/critical unsupported_assertion、evidence_mismatch 或 current_state_as_expected 时 release_readiness 必须为 fail；只有 medium 问题时最多 conditional_pass。",
            "findings 必须定位 case_id/fp_id/source_id，禁止泛泛建议。",
        ],
    }

    def validate(result: dict) -> None:
        summary = result.get("summary") or {}
        _gate(summary.get("release_readiness") in {"pass", "conditional_pass", "fail"}, "可信语义审查缺少合法 release_readiness")
        for key in ("coverage", "method_coverage", "dimension_matrix", "findings", "semantic_consistency"):
            _gate(key in result, f"可信语义审查缺少 {key}")

    review = asyncio.run(
        _call_skill_with_gate_async(
            api_key=api_key,
            model=model,
            base_url=base_url,
            skill_name="quality-reviewer",
            task_payload=prompt,
            output_contract=(
                '{"summary":{"testcase_count":0,"duplicate_count":0,"uncovered_fp_count":0,"ambiguous_step_count":0,'
                '"unverifiable_expectation_count":0,"unsupported_assertion_count":0,"evidence_mismatch_count":0,"current_state_as_expected_count":0,'
                '"exact_value_loss_count":0,"overall_score":0,"release_readiness":"pass|conditional_pass|fail"},'
                '"coverage":{"fp_covered":0,"fp_total":0,"uncovered_fp_ids":[]},'
                '"method_coverage":{"method":"covered|partial|missing|not_applicable"},'
                '"dimension_matrix":{"functional":"covered|partial|missing|not_applicable"},'
                '"evidence_trace":{"status":"complete|incomplete"},"execution_proof":{"summary_lines":["string"]},'
                '"semantic_consistency":[{"case_id":"TC-001","source_id":"SRC-001","status":"supported|partial|unsupported",'
                '"unsupported_assertions":["string"],"evidence_issues":["string"],"exact_value_losses":["string"]}],'
                '"findings":[{"finding_id":"F-001","severity":"low|medium|high|critical","type":"unsupported_assertion|evidence_mismatch|current_state_as_expected|exact_value_loss|missing_method|other",'
                '"source_id":"SRC-001","case_id":"TC-001","fp_id":"FP-001","message":"string","suggestion":"string"}],'
                '"repair_tasks":[{"fp_ids":["FP-001"],"case_ids":["TC-001"],"reason":"string","focus":"string"}]}'
            ),
            validator=validate,
            max_tokens=12000,
            timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
            audit_log=None,
        )
    )
    cases = [item for item in testcase_package.get("testcases") or [] if isinstance(item, dict)]
    findings = [item for item in review.get("findings") or [] if isinstance(item, dict)]
    case_by_id = {
        str(item.get("case_id") or "").strip(): item
        for item in cases
        if str(item.get("case_id") or "").strip()
    }
    filtered_findings: list[dict] = []
    for finding in findings:
        if finding.get("type") != "current_state_as_expected":
            filtered_findings.append(finding)
            continue
        case = case_by_id.get(str(finding.get("case_id") or "").strip())
        source = source_bundles.get(str((case or {}).get("source_id") or finding.get("source_id") or "").strip()) or {}
        current_bases = []
        for basis in (case or {}).get("assertion_basis") or []:
            if not isinstance(basis, dict):
                continue
            if _source_evidence_role(
                source,
                basis_type=str(basis.get("basis_type") or "").strip(),
                basis_ref=str(basis.get("basis_ref") or "").strip(),
                source_quote=str(basis.get("source_quote") or "").strip(),
            ) == "current":
                current_bases.append(basis)
        if current_bases and all(
            _current_state_expectation_is_allowed(
                source,
                str(basis.get("expected_result") or "").strip(),
                str(basis.get("source_quote") or "").strip(),
            )
            for basis in current_bases
        ):
            continue
        filtered_findings.append(finding)
    findings = filtered_findings
    existing_current_state_cases = {
        str(item.get("case_id") or "").strip()
        for item in findings
        if item.get("type") == "current_state_as_expected"
    }
    for case in cases:
        case_id = str(case.get("case_id") or "").strip()
        source_id = str(case.get("source_id") or "").strip()
        source = source_bundles.get(source_id) or {}
        if not (source.get("source_state_semantics") or {}).get("has_state_transition"):
            continue
        for basis in case.get("assertion_basis") or []:
            if not isinstance(basis, dict):
                continue
            expected_result = str(basis.get("expected_result") or "").strip()
            evidence_role = _source_evidence_role(
                source,
                basis_type=str(basis.get("basis_type") or "").strip(),
                basis_ref=str(basis.get("basis_ref") or "").strip(),
                source_quote=str(basis.get("source_quote") or "").strip(),
            )
            if evidence_role != "current" or _current_state_expectation_is_allowed(
                source,
                expected_result,
                str(basis.get("source_quote") or "").strip(),
            ):
                continue
            if case_id not in existing_current_state_cases:
                findings.append({
                    "finding_id": f"DET-CURRENT-{len(existing_current_state_cases) + 1:03d}",
                    "severity": "critical",
                    "type": "current_state_as_expected",
                    "source_id": source_id,
                    "case_id": case_id,
                    "fp_id": case.get("fp_id") or "",
                    "message": f"改造前状态被写成正向预期：{expected_result}",
                    "suggestion": "改用 target 文本/图片作为验收依据；旧状态仅用于不再出现或变更回归断言",
                })
                existing_current_state_cases.add(case_id)
            break
    review["findings"] = findings
    unsupported_findings = [item for item in findings if item.get("type") == "unsupported_assertion"]
    evidence_findings = [item for item in findings if item.get("type") == "evidence_mismatch"]
    current_state_findings = [item for item in findings if item.get("type") == "current_state_as_expected"]
    exact_value_findings = [item for item in findings if item.get("type") == "exact_value_loss"]
    severe_semantic_findings = [
        item
        for item in unsupported_findings + evidence_findings + current_state_findings
        if str(item.get("severity") or "").lower() in {"high", "critical"}
    ]
    summary = review.setdefault("summary", {})
    summary["testcase_count"] = len(cases)
    summary["unsupported_assertion_count"] = max(int(summary.get("unsupported_assertion_count") or 0), len(unsupported_findings))
    summary["evidence_mismatch_count"] = max(int(summary.get("evidence_mismatch_count") or 0), len(evidence_findings))
    summary["current_state_as_expected_count"] = len(current_state_findings)
    summary["exact_value_loss_count"] = max(int(summary.get("exact_value_loss_count") or 0), len(exact_value_findings))
    if severe_semantic_findings:
        summary["release_readiness"] = "fail"
    elif unsupported_findings or evidence_findings or current_state_findings or exact_value_findings:
        summary["release_readiness"] = "conditional_pass"
    review["review_conclusion"] = {"pass": "通过", "conditional_pass": "有条件通过", "fail": "不通过"}.get(summary.get("release_readiness"), "有条件通过")
    review["function_point_count"] = len(function_points.get("function_points") or [])
    review["case_count"] = len(cases)
    review["priority_counts"] = dict(Counter(str(item.get("priority") or "P1") for item in cases))
    review["pending_confirmations"] = pending_confirmations
    return review


def _export_trusted_xmind(
    db,
    job: CaseGenerationV2Job,
    output_dir: str,
    function_points: dict,
    testcase_package: dict,
    review_report: dict,
) -> str:
    output_stem = _sanitize_file_stem(job.source_document_name or job.name)
    xmindmark_text = _build_xmindmark(job, function_points, testcase_package, review_report)
    xmindmark_file_path = _write_text_file(output_dir, f"{output_stem}.xmindmark", xmindmark_text)
    _upsert_artifact(
        db,
        job_id=job.id,
        artifact_type="xmindmark",
        file_name=os.path.basename(xmindmark_file_path),
        file_path=xmindmark_file_path,
        content_json={"text": xmindmark_text},
    )
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
        db.commit()
        return xmind_file_path
    except Exception as exc:
        log_payload = {"error": str(exc)}
        _persist_trusted_artifact(db, job.id, output_dir, "xmind_export_log", "xmind_export_log.json", log_payload)
        db.commit()
        return ""


def _persist_trusted_artifact(db, job_id: int, output_dir: str, artifact_type: str, file_name: str, payload: dict | list | str) -> str:
    if isinstance(payload, str):
        file_path = _write_text_file(output_dir, file_name, payload)
        content_json = None
    else:
        file_path = _write_json_file(output_dir, file_name, payload)
        content_json = payload
    _upsert_artifact(
        db,
        job_id=job_id,
        artifact_type=artifact_type,
        file_name=file_name,
        file_path=file_path,
        content_json=content_json,
    )
    db.commit()
    return file_path


def _trusted_artifact_content(db, job_id: int, artifact_type: str, *, allow_previous: bool = False) -> dict:
    artifact = _trusted_artifact_record(db, job_id, artifact_type, allow_previous=allow_previous)
    if artifact is None or not isinstance(artifact.content_json, dict):
        raise ValueError(f"缺少可信模式产物：{artifact_type}")
    return artifact.content_json


def _optional_trusted_artifact_content(db, job_id: int, artifact_type: str, *, allow_previous: bool = False) -> dict | None:
    artifact = _trusted_artifact_record(db, job_id, artifact_type, allow_previous=allow_previous)
    if artifact is None or not isinstance(artifact.content_json, dict):
        return None
    return artifact.content_json


def _trusted_artifact_record(
    db,
    job_id: int,
    artifact_type: str,
    *,
    allow_previous: bool = False,
) -> CaseGenerationV2Artifact | None:
    attempt_id = current_attempt_id()
    stmt = select(CaseGenerationV2Artifact).where(
        CaseGenerationV2Artifact.job_id == job_id,
        CaseGenerationV2Artifact.artifact_type == artifact_type,
    )
    if attempt_id is not None and not allow_previous:
        stmt = stmt.where(CaseGenerationV2Artifact.attempt_id == attempt_id)
    return db.scalar(stmt.order_by(CaseGenerationV2Artifact.id.desc()))


def _trusted_artifact_text(db, job_id: int, artifact_type: str) -> str:
    artifact = _trusted_artifact_record(db, job_id, artifact_type)
    if artifact is None:
        return ""
    if isinstance(artifact.content_json, dict) and isinstance(artifact.content_json.get("text"), str):
        return artifact.content_json["text"]
    if artifact.file_path and os.path.exists(artifact.file_path):
        return Path(artifact.file_path).read_text(encoding="utf-8", errors="replace")
    return ""


def _count_xmindmark_testcase_nodes(xmindmark_text: str) -> int:
    return len(
        {
            match.group(1)
            for line in xmindmark_text.splitlines()
            for match in [re.match(r"^\s*-\s+(TC-[A-Za-z0-9_-]+)", line)]
            if match
        }
    )


def _count_xmindmark_source_nodes(xmindmark_text: str) -> int:
    return len(
        {
            match.group(1)
            for line in xmindmark_text.splitlines()
            for match in [re.match(r"^\s*-\s+(SRC-[A-Za-z0-9_-]+)(?:[：:｜\s]|$)", line)]
            if match
        }
    )


def _count_xmindmark_function_point_nodes(xmindmark_text: str) -> int:
    return len(
        {
            match.group(1)
            for line in xmindmark_text.splitlines()
            for match in [re.match(r"^\s*-\s+(FP-[A-Za-z0-9_-]+)(?:[：:\s]|$)", line)]
            if match
        }
    )


def _artifact_json_payload(db, job_id: int, artifact_type: str) -> dict:
    artifact = _trusted_artifact_record(db, job_id, artifact_type)
    if artifact is None:
        return {}
    if isinstance(artifact.content_json, dict):
        return artifact.content_json
    if artifact.file_path and os.path.exists(artifact.file_path):
        try:
            loaded = json.loads(Path(artifact.file_path).read_text(encoding="utf-8", errors="replace"))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}
    return {}


def _build_final_delivery_gate(
    db,
    job_id: int,
    testcase_package: dict,
    review_report: dict,
) -> dict:
    issues: list[dict] = []
    xmindmark_artifact = _trusted_artifact_record(db, job_id, "xmindmark")
    xmind_artifact = _trusted_artifact_record(db, job_id, "xmind")
    xmindmark_text = _trusted_artifact_text(db, job_id, "xmindmark")
    scope_index = _artifact_json_payload(db, job_id, "scope_index")
    function_points_payload = _artifact_json_payload(db, job_id, "function_points")
    scope_sources = _trusted_scope_source_items(scope_index)
    source_ids = {
        str(item.get("source_id") or "").strip()
        for item in scope_sources
        if str(item.get("source_id") or "").strip()
    }
    function_points = [
        item for item in function_points_payload.get("function_points") or []
        if isinstance(item, dict)
    ]
    fp_source = {
        str(item.get("fp_id") or "").strip(): str(item.get("source_id") or "").strip()
        for item in function_points
        if str(item.get("fp_id") or "").strip()
    }

    if xmindmark_artifact is None or not xmindmark_text.strip():
        issues.append({"severity": "blocker", "code": "XMINDMARK_MISSING", "message": "缺少 xmindmark artifact"})
    if xmind_artifact is None:
        issues.append({"severity": "blocker", "code": "XMIND_MISSING", "message": "缺少 xmind artifact"})
    elif xmind_artifact.file_path and not os.path.exists(xmind_artifact.file_path):
        issues.append({"severity": "blocker", "code": "XMIND_FILE_MISSING", "message": "xmind artifact 文件不存在"})
    xmind_inspection: dict = {}
    if xmind_artifact is not None and xmind_artifact.file_path and os.path.exists(xmind_artifact.file_path):
        try:
            xmind_inspection = inspect_xmind_archive(xmind_artifact.file_path)
        except ValueError as exc:
            issues.append({"severity": "blocker", "code": "XMIND_INVALID", "message": str(exc)})

    lines = xmindmark_text.splitlines()
    if lines:
        if lines[0].lstrip().startswith("-"):
            issues.append({"severity": "blocker", "code": "XMINDMARK_ROOT_IS_LIST", "message": "XMindMark 第一行不能是列表节点"})
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                issues.append({"severity": "blocker", "code": "XMINDMARK_BLANK_LINE", "message": f"XMindMark 第 {index} 行为空行"})
                continue
            if index > 1:
                indent = len(line) - len(line.lstrip(" "))
                if indent % 2 != 0:
                    issues.append({"severity": "blocker", "code": "XMINDMARK_BAD_INDENT", "message": f"XMindMark 第 {index} 行缩进不是 2 空格倍数"})
    if xmindmark_text and "SRC-" not in xmindmark_text:
        issues.append({"severity": "blocker", "code": "TRUSTED_SOURCE_NODE_MISSING", "message": "可信模式 XMindMark 缺少 SRC- source 节点"})

    contract = testcase_package.get("xmind_grouping_contract")
    if not isinstance(contract, dict):
        issues.append({"severity": "blocker", "code": "XMIND_GROUPING_CONTRACT_MISSING", "message": "testcase_package 缺少 xmind_grouping_contract"})
    elif contract.get("required_tree") != "模块 -> 场景 -> SRC -> FP -> TC":
        issues.append({"severity": "blocker", "code": "XMIND_GROUPING_CONTRACT_BAD_TREE", "message": "xmind_grouping_contract.required_tree 不符合 trusted 导图结构"})

    testcases = [item for item in testcase_package.get("testcases") or [] if isinstance(item, dict)]
    testcase_count = len(testcases)
    testcase_source_ids: set[str] = set()
    testcase_fp_ids: set[str] = set()
    for case in testcases:
        case_id = str(case.get("case_id") or "").strip()
        source_id = str(case.get("source_id") or "").strip()
        if not case_id:
            issues.append({"severity": "blocker", "code": "CASE_MISSING_ID", "message": "交付用例缺少 case_id"})
        if not source_id:
            issues.append({"severity": "blocker", "code": "CASE_MISSING_SOURCE_ID", "message": f"{case_id or 'UNKNOWN'} 缺少 source_id"})
        elif source_ids and source_id not in source_ids:
            issues.append({"severity": "blocker", "code": "CASE_UNKNOWN_SOURCE_ID", "message": f"{case_id} 引用了未知 source_id：{source_id}"})
        else:
            testcase_source_ids.add(source_id)
        if not str(case.get("shard_id") or "").strip():
            issues.append({"severity": "blocker", "code": "CASE_MISSING_SHARD_ID", "message": f"{case_id} 缺少 shard_id"})
        fp_ids = case.get("fp_ids")
        fp_id_values = [str(item).strip() for item in fp_ids if str(item).strip()] if isinstance(fp_ids, list) else []
        if not fp_id_values:
            fallback_fp_id = str(case.get("fp_id") or "").strip()
            fp_id_values = [fallback_fp_id] if fallback_fp_id else []
        if not fp_id_values:
            issues.append({"severity": "blocker", "code": "CASE_MISSING_FP_IDS", "message": f"{case_id} 缺少 fp_ids"})
        for fp_id in fp_id_values:
            testcase_fp_ids.add(fp_id)
            if fp_source and fp_id not in fp_source:
                issues.append({"severity": "blocker", "code": "CASE_UNKNOWN_FP_ID", "message": f"{case_id} 引用了未知 fp_id：{fp_id}"})
            elif source_id and fp_source.get(fp_id) and source_id != fp_source[fp_id]:
                issues.append({"severity": "blocker", "code": "CASE_FP_SOURCE_MISMATCH", "message": f"{case_id} 的 fp_id {fp_id} 与 source_id 归属不一致"})

    xmindmark_testcase_count = _count_xmindmark_testcase_nodes(xmindmark_text)
    xmindmark_source_count = _count_xmindmark_source_nodes(xmindmark_text)
    xmindmark_fp_count = _count_xmindmark_function_point_nodes(xmindmark_text)
    if xmindmark_text and testcase_count != xmindmark_testcase_count:
        issues.append(
            {
                "severity": "blocker",
                "code": "TESTCASE_COUNT_MISMATCH",
                "message": f"testcase_package 用例数 {testcase_count} 与 XMindMark TC 节点数 {xmindmark_testcase_count} 不一致",
            }
        )
    if xmindmark_text and source_ids and len(source_ids) != xmindmark_source_count:
        issues.append(
            {
                "severity": "blocker",
                "code": "SOURCE_NODE_COUNT_MISMATCH",
                "message": f"scope_index source 数 {len(source_ids)} 与 XMindMark SRC 节点数 {xmindmark_source_count} 不一致",
            }
        )
    if xmindmark_text and fp_source and len(fp_source) != xmindmark_fp_count:
        issues.append(
            {
                "severity": "blocker",
                "code": "FP_NODE_COUNT_MISMATCH",
                "message": f"function_points 数 {len(fp_source)} 与 XMindMark FP 节点数 {xmindmark_fp_count} 不一致",
            }
        )

    review_summary = review_report.get("summary") or {}
    review_count = review_summary.get("testcase_count")
    if review_count != testcase_count:
        issues.append(
            {
                "severity": "blocker",
                "code": "REVIEW_TESTCASE_COUNT_MISMATCH",
                "message": f"review summary testcase_count {review_count} 与 testcase_package 用例数 {testcase_count} 不一致",
            }
        )
    review_source_count = review_summary.get("source_count")
    if source_ids and review_source_count != len(source_ids):
        issues.append(
            {
                "severity": "blocker",
                "code": "REVIEW_SOURCE_COUNT_MISMATCH",
                "message": f"review summary source_count {review_source_count} 与 scope_index source 数 {len(source_ids)} 不一致",
            }
        )
    review_fp_count = review_summary.get("function_point_count")
    if fp_source and review_fp_count != len(fp_source):
        issues.append(
            {
                "severity": "blocker",
                "code": "REVIEW_FP_COUNT_MISMATCH",
                "message": f"review summary function_point_count {review_fp_count} 与 function_points 数 {len(fp_source)} 不一致",
            }
        )
    if xmind_inspection:
        actual_xmind_counts = {
            "testcase_count": testcase_count,
            "source_count": len(source_ids),
            "function_point_count": len(fp_source),
        }
        for key, expected in actual_xmind_counts.items():
            actual = xmind_inspection.get(key)
            if actual != expected:
                issues.append(
                    {
                        "severity": "blocker",
                        "code": "XMIND_CONTENT_COUNT_MISMATCH",
                        "message": f"实际 XMind {key}={actual}，预期 {expected}",
                    }
                )

    semantic_readiness = str(
        review_summary.get("semantic_release_readiness")
        or review_summary.get("release_readiness")
        or ""
    )
    if semantic_readiness in {"", "fail"}:
        issues.append(
            {
                "severity": "blocker",
                "code": "SEMANTIC_REVIEW_NOT_PASS",
                "message": f"语义审查结论为 {semantic_readiness or 'missing'}，可信交付要求 pass",
            }
        )
    elif semantic_readiness == "conditional_pass":
        issues.append(
            {
                "severity": "warning",
                "code": "SEMANTIC_REVIEW_CONDITIONAL",
                "message": "语义审查为有条件通过，交付物可下载但必须人工复核建议项",
            }
        )
    must_cover_gap_count = int(review_summary.get("must_cover_gap_count") or 0)
    if must_cover_gap_count:
        issues.append(
            {
                "severity": "blocker",
                "code": "MUST_COVER_GAPS_REMAIN",
                "message": f"仍有 {must_cover_gap_count} 个 must_cover 缺口",
            }
        )
    source_traceability_rate = float(
        review_summary.get("source_traceability_rate")
        if review_summary.get("source_traceability_rate") is not None
        else review_summary.get("evidence_coverage_rate") or 0
    )
    if testcase_count and source_traceability_rate < settings.case_gen_trusted_min_evidence_coverage_rate:
        issues.append(
            {
                "severity": "blocker",
                "code": "SOURCE_TRACEABILITY_BELOW_THRESHOLD",
                "message": f"Source 追溯完整率 {source_traceability_rate:.1%} 低于可信阈值 {settings.case_gen_trusted_min_evidence_coverage_rate:.1%}",
            }
        )
    assertion_basis_rate = float(review_summary.get("assertion_basis_rate") or 0)
    if testcase_count and "assertion_basis_rate" in review_summary and assertion_basis_rate < 1:
        issues.append(
            {
                "severity": "blocker",
                "code": "ASSERTION_BASIS_INCOMPLETE",
                "message": f"预期依据完整率 {assertion_basis_rate:.1%}，可信交付要求每条预期均绑定需求原文或图片证据",
            }
        )
    for metric_key, code, label in (
        ("unsupported_assertion_count", "UNSUPPORTED_ASSERTIONS_REMAIN", "无依据断言"),
        ("evidence_mismatch_count", "EVIDENCE_MISMATCHES_REMAIN", "证据错绑"),
        ("current_state_as_expected_count", "CURRENT_STATE_AS_EXPECTED_REMAINS", "旧状态误作目标预期"),
        ("exact_value_loss_count", "EXACT_VALUE_LOSSES_REMAIN", "精确验收值丢失"),
    ):
        metric_count = int(review_summary.get(metric_key) or 0)
        if metric_count:
            issues.append(
                {
                    "severity": "blocker",
                    "code": code,
                    "message": f"仍有 {metric_count} 项{label}，禁止作为可信交付物",
                }
            )
    weak_expected_rate = (int(review_summary.get("weak_expected_count") or 0) / testcase_count) if testcase_count else 0
    weak_step_rate = (int(review_summary.get("weak_step_count") or 0) / testcase_count) if testcase_count else 0
    if weak_expected_rate > settings.case_gen_trusted_max_weak_expected_rate:
        issues.append(
            {
                "severity": "warning",
                "code": "WEAK_EXPECTED_RATE_TOO_HIGH",
                "message": f"弱预期占比 {weak_expected_rate:.1%} 超过提醒阈值 {settings.case_gen_trusted_max_weak_expected_rate:.1%}，建议人工复核",
            }
        )
    if weak_step_rate > settings.case_gen_trusted_max_weak_step_rate:
        issues.append(
            {
                "severity": "warning",
                "code": "WEAK_STEP_RATE_TOO_HIGH",
                "message": f"弱步骤占比 {weak_step_rate:.1%} 超过提醒阈值 {settings.case_gen_trusted_max_weak_step_rate:.1%}，建议人工复核",
            }
        )

    blocking_issues = [item for item in issues if item.get("severity") == "blocker"]
    return {
        "passed": not blocking_issues,
        "status": "fail" if blocking_issues else ("warning" if issues else "pass"),
        "issues": issues,
        "blocking_issues": blocking_issues,
        "recovery_plan": _trusted_gate_recovery_plan("final_delivery_gate", issues),
        "testcase_count": testcase_count,
        "xmindmark_testcase_count": xmindmark_testcase_count,
        "source_count": len(source_ids),
        "xmindmark_source_count": xmindmark_source_count,
        "function_point_count": len(fp_source),
        "xmindmark_function_point_count": xmindmark_fp_count,
        "review_testcase_count": review_count,
        "review_source_count": review_source_count,
        "review_function_point_count": review_fp_count,
        "xmind_inspection": xmind_inspection,
        "semantic_release_readiness": semantic_readiness,
        "evidence_coverage_rate": source_traceability_rate,
        "source_traceability_rate": source_traceability_rate,
        "assertion_basis_rate": assertion_basis_rate,
        "weak_expected_rate": round(weak_expected_rate, 4),
        "weak_step_rate": round(weak_step_rate, 4),
        "checked_at": utc_now_naive().isoformat(),
    }


def _canonical_gate_report_for_validator(gate: dict) -> dict:
    report = dict(gate or {})
    explicit_blockers = [item for item in report.get("blocking_issues") or [] if isinstance(item, dict)]
    issue_blockers = [
        item
        for item in report.get("issues") or []
        if isinstance(item, dict) and str(item.get("severity") or "").lower() == "blocker"
    ]
    blocking_issues = explicit_blockers + [item for item in issue_blockers if item not in explicit_blockers]
    report["blocking_issues"] = blocking_issues
    # The external trusted validator consumes a delivery contract, while the
    # runtime gate also exposes non-blocking warnings. Canonical output must
    # reflect the blocking decision, otherwise an informational warning (for
    # example, section-batched indexing) is incorrectly treated as a failure.
    if bool(report.get("passed")) and not blocking_issues:
        report["status"] = "pass"
        report["passed"] = True
    else:
        report["status"] = "fail"
        report["passed"] = False
    return report


def _write_trusted_canonical_files(
    db,
    job: CaseGenerationV2Job,
    output_dir: str,
    testcase_package: dict,
    review_report: dict,
    final_delivery_gate: dict,
) -> None:
    source_manifest = _trusted_artifact_content(db, job.id, "source_manifest")
    evidence_trace = _trusted_artifact_content(db, job.id, "evidence_trace")
    scope_index = _trusted_artifact_content(db, job.id, "scope_index")
    requirement_payload = _trusted_artifact_content(db, job.id, "requirement_handoff")
    requirement_handoff = requirement_payload.get("requirement_handoff") or requirement_payload
    scope_gate_payload = _trusted_artifact_content(db, job.id, "scope_index_gate")
    testcase_gate_payload = _trusted_artifact_content(db, job.id, "testcase_handoff")

    output_basename = _sanitize_file_stem(job.source_document_name or job.name)
    source_manifest = dict(source_manifest or {})
    source_manifest.setdefault("project", job.name)
    source_manifest["output_basename"] = output_basename

    scope_gate = scope_gate_payload.get("scope_index_gate") or scope_gate_payload
    requirement_gate = requirement_payload.get("requirement_gate") or {}
    testcase_gate = testcase_gate_payload.get("testcase_gate") or {}
    function_points = _trusted_standard_function_points(scope_index, requirement_handoff)

    _write_yaml_file(output_dir, "SourceManifest.yaml", source_manifest)
    _write_yaml_file(output_dir, "EvidenceTrace.yaml", evidence_trace)
    _write_yaml_file(output_dir, "ScopeIndex.yaml", scope_index)
    _write_yaml_file(output_dir, "ScopeIndexGateReport.yaml", _canonical_gate_report_for_validator(scope_gate))
    _write_yaml_file(output_dir, "FunctionPoints.yaml", function_points)
    _write_yaml_file(output_dir, "RequirementGateReport.yaml", _canonical_gate_report_for_validator(requirement_gate))
    _write_yaml_file(output_dir, "TestcasePackage.yaml", testcase_package)
    _write_yaml_file(output_dir, "TestcaseGateReport.yaml", _canonical_gate_report_for_validator(testcase_gate))
    _write_yaml_file(output_dir, "ReviewReport.yaml", review_report)
    _write_text_file(output_dir, "DeliverySummary.md", _build_trusted_delivery_markdown(job, review_report, testcase_package))
    _write_yaml_file(
        output_dir,
        "FinalDeliveryGateReport.yaml",
        _canonical_gate_report_for_validator(final_delivery_gate),
    )


def _run_unified_trusted_validator(output_dir: str) -> dict:
    script_path = _resolve_unified_rules_dir() / "tools" / "validate_trusted_output.py"
    if not script_path.exists():
        return {
            "passed": False,
            "issues": [{"severity": "blocker", "code": "TRUSTED_VALIDATOR_MISSING", "message": f"缺少 trusted 硬校验器：{script_path}"}],
            "raw": "",
        }
    completed = subprocess.run(
        ["python3", str(script_path), output_dir, "--format", "json"],
        text=True,
        capture_output=True,
        timeout=120,
    )
    raw = completed.stdout.strip() or completed.stderr.strip()
    payload: dict = {}
    try:
        payload = json.loads(completed.stdout or "{}")
    except Exception:
        payload = {"errors": [{"code": "VALIDATOR_OUTPUT_PARSE_FAILED", "message": raw or "validator 未输出 JSON"}]}
    issues = []
    for item in payload.get("errors") or []:
        if isinstance(item, dict):
            issues.append({"severity": "blocker", "code": item.get("code") or "TRUSTED_VALIDATOR_ERROR", "message": item.get("message") or str(item)})
    return {
        "passed": completed.returncode == 0 and not issues,
        "issues": issues,
        "metrics": payload.get("metrics") or {},
        "raw": raw,
        "returncode": completed.returncode,
    }


def _run_final_delivery_gate(
    db,
    job: CaseGenerationV2Job,
    output_dir: str,
    testcase_package: dict,
    review_report: dict,
) -> dict:
    gate_payload = _build_final_delivery_gate(db, job.id, testcase_package, review_report)
    _write_trusted_canonical_files(db, job, output_dir, testcase_package, review_report, gate_payload)
    validator_result = _run_unified_trusted_validator(output_dir)
    gate_payload["validator"] = validator_result
    if not validator_result.get("passed"):
        for issue in validator_result.get("issues") or []:
            if isinstance(issue, dict):
                gate_payload.setdefault("issues", []).append(issue)
        gate_payload["passed"] = False
        gate_payload["status"] = "fail"
        gate_payload["blocking_issues"] = [item for item in gate_payload.get("issues") or [] if item.get("severity") == "blocker"]
        gate_payload["recovery_plan"] = _trusted_gate_recovery_plan("final_delivery_gate", gate_payload.get("issues") or [])
    if not gate_payload.get("passed"):
        blocking_issues = gate_payload.get("blocking_issues") or gate_payload.get("issues") or []
        first_issue = blocking_issues[0] if blocking_issues else {}
        gate_payload["failure_code"] = first_issue.get("code") or "FINAL_DELIVERY_GATE_FAILED"
        gate_payload["failure_message"] = first_issue.get("message") or "final_delivery_gate 未通过"
        gate_payload["return_to"] = (gate_payload.get("recovery_plan") or {}).get("return_to") or "export"
    _write_trusted_canonical_files(db, job, output_dir, testcase_package, review_report, gate_payload)
    _persist_trusted_artifact(db, job.id, output_dir, "final_delivery_gate", "final_delivery_gate.json", gate_payload)
    if not gate_payload.get("passed"):
        raise ValueError(f"final_delivery_gate 未通过：{gate_payload.get('failure_message')}")
    return gate_payload


def _rebuild_trusted_delivery_artifacts(
    db,
    job: CaseGenerationV2Job,
    output_dir: str,
    scope_index: dict,
    requirement_handoff: dict,
    testcase_handoff: dict,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    image_links: list[str] | None = None,
    downloaded_images: list[dict] | None = None,
    image_analysis: list[dict] | None = None,
) -> tuple[dict, dict]:
    scope_index_gate_payload = _trusted_artifact_content(db, job.id, "scope_index_gate")
    requirement_handoff_payload = _trusted_artifact_content(db, job.id, "requirement_handoff")
    scope_index_gate = scope_index_gate_payload.get("scope_index_gate")
    if not scope_index_gate:
        scope_index_deterministic_gate = _validate_trusted_scope_index(scope_index)
        if api_key and model and base_url:
            scope_index_gate, scope_index_model_gate = _run_trusted_combined_gate(
                review_stage="scope_index_gate",
                deterministic_gate=scope_index_deterministic_gate,
                scope_index=scope_index,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
        else:
            scope_index_gate = _combine_trusted_gate(scope_index_deterministic_gate)
            scope_index_model_gate = None
        _persist_trusted_artifact(
            db,
            job.id,
            output_dir,
            "scope_index_gate",
            "scope_index_gate.json",
            {
                "scope_index_gate": scope_index_gate,
                "deterministic_gate": scope_index_deterministic_gate,
                "model_handoff_gate": scope_index_model_gate,
            },
        )
    requirement_gate = requirement_handoff_payload.get("requirement_gate")
    if not requirement_gate:
        requirement_deterministic_gate = _validate_trusted_requirement_handoff(scope_index, requirement_handoff)
        if api_key and model and base_url:
            requirement_gate, requirement_model_gate = _run_trusted_combined_gate(
                review_stage="requirement_gate",
                deterministic_gate=requirement_deterministic_gate,
                scope_index=scope_index,
                requirement_handoff=requirement_handoff,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
        else:
            requirement_gate = _combine_trusted_gate(requirement_deterministic_gate)
            requirement_model_gate = None
        requirement_handoff_payload = {
            "requirement_handoff": requirement_handoff,
            "requirement_gate": requirement_gate,
            "deterministic_gate": requirement_deterministic_gate,
            "model_handoff_gate": requirement_model_gate,
        }
        _persist_trusted_artifact(db, job.id, output_dir, "requirement_handoff", "requirement_handoff.json", requirement_handoff_payload)
    testcase_deterministic_gate = _validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
    if api_key and model and base_url:
        testcase_gate, testcase_model_gate = _run_trusted_combined_gate(
            review_stage="testcase_gate",
            deterministic_gate=testcase_deterministic_gate,
            scope_index=scope_index,
            requirement_handoff=requirement_handoff,
            testcase_handoff=testcase_handoff,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    else:
        testcase_gate = _combine_trusted_gate(testcase_deterministic_gate)
        testcase_model_gate = None
    _persist_trusted_artifact(
        db,
        job.id,
        output_dir,
        "testcase_handoff",
        "testcase_handoff.json",
        {
            "testcase_handoff": testcase_handoff,
            "testcase_gate": testcase_gate,
            "deterministic_gate": testcase_deterministic_gate,
            "model_handoff_gate": testcase_model_gate,
        },
    )
    standard_function_points = _trusted_standard_function_points(scope_index, requirement_handoff)
    standard_testcase_package = _trusted_standard_testcase_package(requirement_handoff, testcase_handoff)
    quality_summary = _build_case_generation_quality_summary(standard_function_points, standard_testcase_package)
    standard_review_report = {}
    if api_key and model and base_url:
        evidence_trace = _trusted_evidence_trace(
            image_links=image_links,
            downloaded_images=downloaded_images,
            image_analysis=image_analysis,
            pending_confirmations=requirement_handoff.get("pending_confirmations") or [],
        )
        standard_review_report = _build_trusted_semantic_review(
            evidence_trace,
            standard_function_points,
            standard_testcase_package,
            requirement_handoff.get("pending_confirmations") or [],
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    review_report = _build_trusted_review_report(
        scope_index,
        requirement_handoff,
        testcase_handoff,
        scope_index_gate,
        requirement_gate,
        testcase_gate,
        standard_review_report=standard_review_report,
        quality_summary=quality_summary,
    )
    _persist_trusted_artifact(db, job.id, output_dir, "trusted_review_report", "trusted_review_report.json", review_report)
    if not testcase_gate.get("passed"):
        review_report.setdefault("summary", {})["final_delivery_gate_passed"] = False
        review_report.setdefault("delivery_status", "blocked_by_testcase_gate")
        _persist_trusted_artifact(db, job.id, output_dir, "trusted_review_report", "trusted_review_report.json", review_report)
        return testcase_gate, review_report
    delivery_markdown = _build_trusted_delivery_markdown(job, review_report, testcase_handoff)
    _persist_trusted_artifact(db, job.id, output_dir, "markdown", "trusted_delivery_summary.md", delivery_markdown)
    _export_trusted_xmind(db, job, output_dir, standard_function_points, standard_testcase_package, review_report)
    final_delivery_gate = _run_final_delivery_gate(db, job, output_dir, standard_testcase_package, review_report)
    review_report.setdefault("summary", {})["final_delivery_gate_passed"] = bool(final_delivery_gate.get("passed"))
    _persist_trusted_artifact(db, job.id, output_dir, "trusted_review_report", "trusted_review_report.json", review_report)
    return testcase_gate, review_report


def _source_by_id(scope_index: dict, source_id: str) -> dict:
    source = _trusted_source_by_id(scope_index).get(source_id)
    if source:
        return source
    raise ValueError(f"未找到 source_id：{source_id}")


def _localize_trusted_shard_case_ids(raw_shard: dict) -> dict:
    localized = dict(raw_shard)
    source_id = str(localized.get("source_id") or "").strip()
    source_number = source_id.removeprefix("SRC-").zfill(3) if source_id else ""
    cases = [dict(item) for item in localized.get("testcases") or [] if isinstance(item, dict)]
    old_to_local: dict[str, str] = {}
    for index, case in enumerate(cases, start=1):
        old_case_id = str(case.get("case_id") or "").strip()
        local_case_id = f"TC-{index:03d}"
        if old_case_id:
            old_to_local[old_case_id] = local_case_id
        case["case_id"] = local_case_id
    localized["testcases"] = cases

    def _rewrite_refs(items: list[dict]) -> list[dict]:
        rewritten_items: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rewritten = dict(item)
            refs = rewritten.get("case_refs") if isinstance(rewritten.get("case_refs"), list) else rewritten.get("case_ids")
            new_refs = []
            for ref in refs or []:
                ref_text = str(ref or "").strip()
                if not ref_text:
                    continue
                mapped = old_to_local.get(ref_text, ref_text)
                if mapped == ref_text and source_number:
                    global_prefix = f"TC-{source_number}-"
                    if ref_text.startswith(global_prefix):
                        local_suffix = ref_text[len(global_prefix) :]
                        if local_suffix.isdigit():
                            mapped = f"TC-{int(local_suffix):03d}"
                if mapped not in new_refs:
                    new_refs.append(mapped)
            rewritten["case_refs"] = new_refs
            rewritten["case_ids"] = new_refs
            rewritten_items.append(rewritten)
        return rewritten_items

    localized["feature_point_consumption"] = _rewrite_refs(localized.get("feature_point_consumption") or [])
    localized["method_consumption"] = _rewrite_refs(localized.get("method_consumption") or [])
    return localized


def _resume_trusted_v2_from_testcase_gate(job_id: int) -> None:
    db = SessionLocal()
    attempt_id = current_attempt_id()
    try:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is None or job.status == "CANCELLED":
            return
        assert_active_attempt(job, attempt_id, db=db)
        payload = dict(job.input_payload_json or {})
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
            raise ValueError("缺少模型配置，无法从用例门禁继续")

        output_dir = _job_output_dir(job.id)
        scope_index = _trusted_artifact_content(db, job.id, "scope_index", allow_previous=True)
        requirement_payload = _trusted_artifact_content(db, job.id, "requirement_handoff", allow_previous=True)
        requirement_handoff = json.loads(json.dumps(
            requirement_payload.get("requirement_handoff") or requirement_payload,
            ensure_ascii=False,
        ))
        lite_testcase_package = _trusted_artifact_content(db, job.id, "testcase_base_package", allow_previous=True)
        existing_testcase_handoff = _optional_trusted_artifact_content(
            db,
            job.id,
            "testcase_package",
            allow_previous=True,
        )

        job.status = "RUNNING"
        job.summary = "正在复用已有基线用例，从用例门禁继续"
        job.error_message = None
        job.started_at = job.started_at or utc_now_naive()
        job.finished_at = None
        db.commit()

        requirement_handoff = _repair_converted_requirement_consumption(requirement_handoff)
        requirement_deterministic_gate = _validate_trusted_requirement_handoff(scope_index, requirement_handoff)
        requirement_gate, requirement_model_gate = _run_trusted_combined_gate(
            review_stage="requirement_gate",
            deterministic_gate=requirement_deterministic_gate,
            scope_index=scope_index,
            requirement_handoff=requirement_handoff,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        _persist_trusted_artifact(
            db,
            job.id,
            output_dir,
            "requirement_handoff",
            "requirement_handoff.json",
            {
                "requirement_handoff": requirement_handoff,
                "requirement_gate": requirement_gate,
                "deterministic_gate": requirement_deterministic_gate,
                "model_handoff_gate": requirement_model_gate,
            },
        )
        if not requirement_gate.get("passed"):
            raise ValueError(f"requirement_gate 未通过：{len(requirement_gate.get('blocking_issues') or [])} 个阻断问题")
        _update_stage(job, db, "requirement_gate", "需求门禁", "success", "需求回执已修复并重新通过门禁")

        _update_stage(job, db, "testcase_by_source_shard", "用例基线", "running", "正在复用已有基线用例并重建可信追溯")
        existing_shards = [
            item
            for item in (existing_testcase_handoff or {}).get("testcase_shards") or []
            if isinstance(item, dict)
        ]
        can_reuse_trusted_package = bool(
            existing_shards
            and all(item.get("status") == "success" and item.get("testcases") for item in existing_shards)
        )
        if can_reuse_trusted_package:
            source_by_id = _trusted_source_by_id(scope_index)
            normalized_shards = []
            for shard in existing_shards:
                source_id = str(shard.get("source_id") or "").strip()
                localized = _localize_trusted_shard_case_ids(shard)
                normalized_shards.append(
                    _normalize_trusted_testcase_handoff(
                        localized,
                        source_id,
                        source=source_by_id.get(source_id),
                    )
                )
            testcase_handoff = _finalize_trusted_testcase_shards(normalized_shards)
            baseline_summary = f"已复用 {len(testcase_handoff.get('testcases') or [])} 条可信 source 用例"
        else:
            testcase_handoff = _build_trusted_testcase_handoff_from_lite_package(
                scope_index,
                requirement_handoff,
                lite_testcase_package,
            )
            baseline_summary = f"已复用 {len(testcase_handoff.get('testcases') or [])} 条轻量基线用例"
        _persist_trusted_artifact(db, job.id, output_dir, "testcase_package", "trusted_testcase_package.json", testcase_handoff)
        _update_stage(job, db, "testcase_by_source_shard", "用例基线", "success", baseline_summary)

        _update_stage(job, db, "testcase_gate", "用例门禁", "running", "正在重新执行用例门禁并继续复核交付")
        testcase_gate, review_report = _rebuild_trusted_delivery_artifacts(
            db,
            job,
            output_dir,
            scope_index,
            requirement_handoff,
            testcase_handoff,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        if not testcase_gate.get("passed"):
            raise ValueError(f"testcase_gate 未通过：{len(testcase_gate.get('blocking_issues') or [])} 个阻断问题")
        _update_stage(job, db, "testcase_gate", "用例门禁", "success", _trusted_gate_success_summary("用例门禁", testcase_gate))
        _update_stage(job, db, "quality_review", "质量复核", "success", "可信指标和语义质量审查已更新")
        _update_stage(job, db, "export", "导出交付物", "success", "Markdown、JSON 和 XMind 产物已更新")
        _update_stage(job, db, "final_delivery_gate", "交付门禁", "success", "交付门禁通过")

        summary = review_report.get("summary") or {}
        payload.pop("trusted_resume_from_stage", None)
        payload["pipeline_mode"] = payload.get("pipeline_mode") or "trusted"
        job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
        job.summary = f"可信模式已复用基线生成 {summary.get('testcase_count', 0)} 条用例并导出 XMind，覆盖 {summary.get('source_count', 0)} 个直接测试对象，交付门禁通过"
        semantic_readiness = str(summary.get("semantic_release_readiness") or summary.get("release_readiness") or "conditional_pass")
        final_status = "SUCCESS" if semantic_readiness == "pass" else "CONDITIONAL"
        finish_attempt(db, job, status=final_status, summary=job.summary, error_message=None)
    except Exception as exc:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is not None:
            if isinstance(exc, SupersededAttemptError) or job.active_attempt_id != attempt_id:
                db.rollback()
                return
            if job.status == "CANCELLED":
                finish_attempt(db, job, status="CANCELLED", summary="生成已取消", error_message="任务已手动停止")
                return
            _mark_last_stage_failed(job, summary=str(exc))
            finish_attempt(db, job, status="FAILED", summary="可信模式恢复执行失败", error_message=str(exc))
        raise
    finally:
        db.close()


def _trusted_reusable_source_shards(testcase_handoff: dict | None) -> dict[str, dict]:
    if not isinstance(testcase_handoff, dict):
        return {}
    reusable: dict[str, dict] = {}
    for shard in testcase_handoff.get("testcase_shards") or []:
        if not isinstance(shard, dict):
            continue
        source_id = str(shard.get("source_id") or "").strip()
        if not source_id or shard.get("status") != "success":
            continue
        if not shard.get("testcases"):
            continue
        reusable[source_id] = dict(shard)
    return reusable


def _replace_trusted_testcase_shard(
    testcase_handoff: dict,
    shard: dict,
    *,
    source_by_id: dict[str, dict] | None = None,
) -> dict:

    source_id = str(shard.get("source_id") or "").strip()
    existing = []
    for item in testcase_handoff.get("testcase_shards") or []:
        if not isinstance(item, dict):
            continue
        localized = _localize_trusted_shard_case_ids(item)
        localized_source_id = str(localized.get("source_id") or "").strip()
        if source_by_id is not None:
            localized = _normalize_trusted_testcase_handoff(
                localized,
                localized_source_id,
                source=source_by_id.get(localized_source_id),
            )
        existing.append(localized)
    shard = _localize_trusted_shard_case_ids(shard)
    if source_by_id is not None:
        shard = _normalize_trusted_testcase_handoff(shard, source_id, source=source_by_id.get(source_id))
    replaced = False
    updated: list[dict] = []
    for item in existing:
        if str(item.get("source_id") or "").strip() == source_id:
            updated.append(shard)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(shard)
    return _finalize_trusted_testcase_shards(updated)


def _run_trusted_v2_pipeline(job_id: int) -> None:
    db = SessionLocal()
    attempt_id = current_attempt_id()
    try:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is None or job.status == "CANCELLED":
            return
        assert_active_attempt(job, attempt_id, db=db)
        payload = dict(job.input_payload_json or {})
        markdown_text = _resolve_markdown_text(payload)
        if not markdown_text:
            message = "请提供需求文本、上传文件内容或有效的需求文档链接"
            finish_attempt(db, job, status="FAILED", summary="输入内容为空", error_message=message)
            raise ValueError(message)
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
            message = "当前工作空间未配置可用模型或 API Key"
            finish_attempt(db, job, status="FAILED", summary="缺少模型配置", error_message=message)
            raise ValueError(message)

        job.status = "RUNNING"
        job.summary = "正在执行可信改进模式"
        job.error_message = None
        job.started_at = utc_now_naive()
        job.finished_at = None
        job.progress_json = {"stages": []}
        previous_testcase_handoff = _optional_trusted_artifact_content(
            db,
            job.id,
            "testcase_package",
            allow_previous=True,
        )
        previous_source_manifest = _optional_trusted_artifact_content(db, job.id, "source_manifest", allow_previous=True)
        previous_scope_index = _optional_trusted_artifact_content(db, job.id, "scope_index", allow_previous=True)
        previous_scope_gate_payload = _optional_trusted_artifact_content(db, job.id, "scope_index_gate", allow_previous=True)
        previous_requirement_payload = _optional_trusted_artifact_content(db, job.id, "requirement_handoff", allow_previous=True)
        sync_attempt_from_job(db, job)
        db.commit()
        _raise_if_job_cancelled(db, job.id)

        output_dir = _job_output_dir(job.id)
        image_links = _extract_image_links(markdown_text, payload.get("source_url"))
        _update_stage(job, db, "orchestrate", "任务编排", "running", "正在启动可信改进流程")
        source_manifest = _build_trusted_source_manifest(
            markdown_text,
            image_links,
            source_url=payload.get("source_url"),
            model=model,
        )
        _persist_trusted_artifact(db, job.id, output_dir, "source_manifest", "SourceManifest.json", source_manifest)
        _update_stage(job, db, "orchestrate", "任务编排", "success", "执行模式：trusted")

        _update_stage(job, db, "evidence_trace", "证据追踪", "running", "正在收集需求正文、下载图片并执行识图")
        downloaded_images = _download_image_links(image_links, output_dir)
        _raise_if_job_cancelled(db, job.id)
        image_result = _analyze_images(api_key, model, base_url, downloaded_images)
        image_analysis = image_result.get("images") or []
        _raise_if_job_cancelled(db, job.id)
        evidence_trace = _build_trusted_evidence_artifact(
            markdown_text,
            image_links,
            downloaded_images,
            image_analysis,
            base_url=payload.get("source_url"),
        )
        _persist_trusted_artifact(db, job.id, output_dir, "evidence_trace", "EvidenceTrace.json", evidence_trace)
        evidence_trace_gate = _validate_trusted_evidence_trace(evidence_trace)
        _persist_trusted_artifact(
            db,
            job.id,
            output_dir,
            "evidence_trace_gate",
            "EvidenceTraceGate.json",
            evidence_trace_gate,
        )
        if not evidence_trace_gate.get("passed"):
            raise ValueError(f"evidence_trace_gate 未通过：{len(evidence_trace_gate.get('issues') or [])} 个阻断问题")
        _update_stage(
            job,
            db,
            "evidence_trace",
            "证据追踪",
            "success",
            f"已收集 {evidence_trace.get('section_count', 0)} 个章节，发现 {len(image_links)} 张图片，识别 {len(image_analysis)} 张",
        )

        _update_stage(job, db, "scope_index", "范围索引", "running", "正在由模型建立直接测试对象索引")
        previous_scope_gate = (
            (previous_scope_gate_payload or {}).get("scope_index_gate")
            or previous_scope_gate_payload
            or {}
        )
        reuse_scope_index = _can_reuse_trusted_scope_index(
            previous_scope_index,
            previous_source_manifest,
            source_manifest,
            previous_scope_gate,
        )
        if reuse_scope_index:
            scope_index = json.loads(json.dumps(previous_scope_index, ensure_ascii=False))
            _update_stage(job, db, "scope_index", "范围索引", "running", "输入和规则未变化，正在复用已通过门禁的稳定范围索引")
        else:
            scope_index = _build_trusted_scope_index(
                markdown_text,
                image_analysis,
                api_key=api_key,
                model=model,
                base_url=base_url,
                progress_callback=lambda summary: _update_stage(job, db, "scope_index", "范围索引", "running", summary),
            )
        scope_index = _attach_scope_evidence(
            scope_index,
            markdown_text,
            image_links,
            image_analysis,
            base_url=payload.get("source_url"),
        )
        scope_index = _merge_evidence_risks_into_scope_index(scope_index, evidence_trace)
        _persist_trusted_artifact(db, job.id, output_dir, "scope_index", "scope_index.json", scope_index)
        _raise_if_job_cancelled(db, job.id)
        scope_summary = f"已建立 {len(_trusted_scope_source_items(scope_index))} 个直接测试对象"
        if reuse_scope_index:
            scope_summary += "，复用稳定索引"
        _update_stage(job, db, "scope_index", "范围索引", "success", scope_summary)

        _update_stage(job, db, "scope_index_gate", "范围门禁", "running", "正在执行后端确定性范围校验")
        scope_index_deterministic_gate = _validate_trusted_scope_index(scope_index)
        scope_index_gate, scope_index_model_gate = _run_trusted_combined_gate(
            review_stage="scope_index_gate",
            deterministic_gate=scope_index_deterministic_gate,
            scope_index=scope_index,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        _persist_trusted_artifact(
            db,
            job.id,
            output_dir,
            "scope_index_gate",
            "scope_index_gate.json",
            {
                "scope_index_gate": scope_index_gate,
                "deterministic_gate": scope_index_deterministic_gate,
                "model_handoff_gate": scope_index_model_gate,
            },
        )
        if not scope_index_gate.get("passed"):
            raise ValueError(f"scope_index_gate 未通过：{len(scope_index_gate.get('issues') or [])} 个阻断问题")
        _update_stage(job, db, "scope_index_gate", "范围门禁", "success", _trusted_gate_success_summary("范围门禁", scope_index_gate))

        _update_stage(job, db, "requirement", "需求分析", "running", "正在基于范围索引生成功能点")
        previous_requirement_handoff = (
            (previous_requirement_payload or {}).get("requirement_handoff")
            or previous_requirement_payload
            or {}
        )
        previous_requirement_gate = (previous_requirement_payload or {}).get("requirement_gate") or {}
        reuse_requirement = _can_reuse_trusted_requirement(
            previous_requirement_handoff,
            scope_index,
            previous_requirement_gate,
        )
        if reuse_requirement:
            requirement_handoff = _normalize_trusted_requirement_handoff(
                scope_index,
                json.loads(json.dumps(previous_requirement_handoff, ensure_ascii=False)),
            )
            _update_stage(job, db, "requirement", "需求分析", "running", "范围与规则未变化，正在复用已通过门禁的稳定功能点")
        else:
            requirement_handoff = _build_trusted_requirement_handoff(
                scope_index,
                markdown_text,
                image_analysis,
                api_key=api_key,
                model=model,
                base_url=base_url,
                progress_callback=lambda summary: _update_stage(job, db, "requirement", "需求分析", "running", summary),
            )
        _persist_trusted_artifact(db, job.id, output_dir, "function_points", "trusted_function_points.json", requirement_handoff)
        _raise_if_job_cancelled(db, job.id)
        requirement_summary = f"已生成 {len(requirement_handoff.get('function_points') or [])} 个功能点"
        if reuse_requirement:
            requirement_summary += "，复用稳定功能点"
        _update_stage(job, db, "requirement", "需求分析", "success", requirement_summary)

        _update_stage(job, db, "requirement_gate", "需求门禁", "running", "正在执行 source 消费确定性校验")
        requirement_deterministic_gate = _validate_trusted_requirement_handoff(scope_index, requirement_handoff)
        requirement_gate, requirement_model_gate = _run_trusted_combined_gate(
            review_stage="requirement_gate",
            deterministic_gate=requirement_deterministic_gate,
            scope_index=scope_index,
            requirement_handoff=requirement_handoff,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        requirement_handoff_payload = {
            "requirement_handoff": requirement_handoff,
            "requirement_gate": requirement_gate,
            "deterministic_gate": requirement_deterministic_gate,
            "model_handoff_gate": requirement_model_gate,
        }
        _persist_trusted_artifact(db, job.id, output_dir, "requirement_handoff", "requirement_handoff.json", requirement_handoff_payload)
        if not requirement_gate.get("passed"):
            raise ValueError(f"requirement_gate 未通过：{len(requirement_gate.get('issues') or [])} 个阻断问题")
        _update_stage(job, db, "requirement_gate", "需求门禁", "success", _trusted_gate_success_summary("需求门禁", requirement_gate))

        trusted_generation_strategy = str(payload.get("trusted_generation_strategy") or "source_shard").strip() or "source_shard"
        _update_stage(job, db, "testcase_by_source_shard", "用例基线", "running", "正在生成可信基线用例")
        def update_trusted_testcase_progress(summary: str) -> None:
            _update_stage(job, db, "testcase_by_source_shard", "用例基线", "running", summary)
            _raise_if_job_cancelled(db, job.id)

        if trusted_generation_strategy == "source_shard":
            _update_stage(job, db, "testcase_by_source_shard", "用例基线", "running", "正在按 source/shard 的适用方法和 must_cover 生成可解释用例")
            testcase_handoff = _build_trusted_testcase_handoff(
                scope_index,
                requirement_handoff,
                api_key=api_key,
                model=model,
                base_url=base_url,
                progress_callback=update_trusted_testcase_progress,
                existing_testcase_handoff=previous_testcase_handoff,
            )
        else:
            _update_stage(job, db, "testcase_by_source_shard", "用例基线", "running", "正在复用轻量用例设计生成基线用例，并映射为可信回执")
            standard_function_points_for_lite = _trusted_standard_function_points(scope_index, requirement_handoff)
            lite_testcase_package = _build_testcase_package(
                standard_function_points_for_lite,
                requirement_handoff.get("pending_confirmations") or [],
                api_key,
                model,
                base_url,
                audit_log=None,
                progress_callback=update_trusted_testcase_progress,
            )
            _persist_trusted_artifact(db, job.id, output_dir, "testcase_base_package", "lite_testcase_package.json", lite_testcase_package)
            testcase_handoff = _build_trusted_testcase_handoff_from_lite_package(
                scope_index,
                requirement_handoff,
                lite_testcase_package,
            )
        _persist_trusted_artifact(db, job.id, output_dir, "testcase_package", "trusted_testcase_package.json", testcase_handoff)
        _raise_if_job_cancelled(db, job.id)
        shard_failure_message = _trusted_shard_failure_message(testcase_handoff)
        if shard_failure_message:
            _rebuild_trusted_delivery_artifacts(
                db,
                job,
                output_dir,
                scope_index,
                requirement_handoff,
                testcase_handoff,
                api_key=api_key,
                model=model,
                base_url=base_url,
                image_links=image_links,
                downloaded_images=downloaded_images,
                image_analysis=image_analysis,
            )
            _update_stage(job, db, "testcase_by_source_shard", "用例基线", "failed", shard_failure_message)
            raise ValueError(shard_failure_message)
        _update_stage(job, db, "testcase_by_source_shard", "用例基线", "success", f"已生成 {len(testcase_handoff.get('testcases') or [])} 条测试用例")

        _update_stage(job, db, "testcase_gate", "用例门禁", "running", "正在执行 FP 消费、方法消费和溯源确定性校验")
        testcase_deterministic_gate = _validate_trusted_testcase_handoff(scope_index, requirement_handoff, testcase_handoff)
        testcase_gate, testcase_model_gate = _run_trusted_combined_gate(
            review_stage="testcase_gate",
            deterministic_gate=testcase_deterministic_gate,
            scope_index=scope_index,
            requirement_handoff=requirement_handoff,
            testcase_handoff=testcase_handoff,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        testcase_handoff_payload = {
            "testcase_handoff": testcase_handoff,
            "testcase_gate": testcase_gate,
            "deterministic_gate": testcase_deterministic_gate,
            "model_handoff_gate": testcase_model_gate,
        }
        _persist_trusted_artifact(db, job.id, output_dir, "testcase_handoff", "testcase_handoff.json", testcase_handoff_payload)
        if not testcase_gate.get("passed"):
            raise ValueError(f"testcase_gate 未通过：{len(testcase_gate.get('issues') or [])} 个阻断问题")
        _update_stage(job, db, "testcase_gate", "用例门禁", "success", _trusted_gate_success_summary("用例门禁", testcase_gate))

        _update_stage(job, db, "quality_review", "质量复核", "running", "正在汇总可信指标并执行语义质量审查")
        standard_function_points = _trusted_standard_function_points(scope_index, requirement_handoff)
        standard_testcase_package = _trusted_standard_testcase_package(requirement_handoff, testcase_handoff)
        quality_summary = _build_case_generation_quality_summary(standard_function_points, standard_testcase_package)
        standard_review_report = _build_trusted_semantic_review(
            _trusted_evidence_trace(
                image_links=image_links,
                downloaded_images=downloaded_images,
                image_analysis=image_analysis,
                pending_confirmations=requirement_handoff.get("pending_confirmations") or [],
            ),
            standard_function_points,
            standard_testcase_package,
            requirement_handoff.get("pending_confirmations") or [],
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        review_report = _build_trusted_review_report(
            scope_index,
            requirement_handoff,
            testcase_handoff,
            scope_index_gate,
            requirement_gate,
            testcase_gate,
            standard_review_report=standard_review_report,
            quality_summary=quality_summary,
        )
        _persist_trusted_artifact(db, job.id, output_dir, "trusted_review_report", "trusted_review_report.json", review_report)
        _update_stage(job, db, "quality_review", "质量复核", "success", "可信指标和语义质量审查已汇总")

        _update_stage(job, db, "export", "导出交付物", "running", "正在导出 Markdown、JSON、XMindMark，并尝试转换 XMind")
        delivery_markdown = _build_trusted_delivery_markdown(job, review_report, testcase_handoff)
        _persist_trusted_artifact(db, job.id, output_dir, "markdown", "trusted_delivery_summary.md", delivery_markdown)
        _export_trusted_xmind(db, job, output_dir, standard_function_points, standard_testcase_package, review_report)
        _update_stage(job, db, "export", "导出交付物", "success", "已写入 Markdown、JSON、XMindMark；XMind 转换结果由交付门禁确认")

        _update_stage(job, db, "final_delivery_gate", "交付门禁", "running", "正在校验 XMindMark、XMind 和统计一致性")
        final_delivery_gate = _run_final_delivery_gate(db, job, output_dir, standard_testcase_package, review_report)
        review_report.setdefault("summary", {})["final_delivery_gate_passed"] = bool(final_delivery_gate.get("passed"))
        _persist_trusted_artifact(db, job.id, output_dir, "trusted_review_report", "trusted_review_report.json", review_report)
        _update_stage(job, db, "final_delivery_gate", "交付门禁", "success", "交付门禁通过")

        summary = review_report.get("summary") or {}
        payload["pipeline_mode"] = payload.get("pipeline_mode") or "trusted"
        job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
        semantic_readiness = str(summary.get("semantic_release_readiness") or summary.get("release_readiness") or "conditional_pass")
        final_status = "SUCCESS" if semantic_readiness == "pass" else "CONDITIONAL"
        job.summary = (
            f"可信模式已生成 {summary.get('testcase_count', 0)} 条用例并导出 XMind，"
            f"覆盖 {summary.get('source_count', 0)} 个直接测试对象，"
            f"语义结论：{'通过' if final_status == 'SUCCESS' else '有条件通过'}"
        )
        finish_attempt(db, job, status=final_status, summary=job.summary, error_message=None)
    except Exception as exc:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is not None:
            if isinstance(exc, SupersededAttemptError) or job.active_attempt_id != attempt_id:
                db.rollback()
                return
            if job.status == "CANCELLED":
                finish_attempt(db, job, status="CANCELLED", summary="生成已取消", error_message="任务已手动停止")
                return
            payload = dict(job.input_payload_json or {})
            payload["pipeline_mode"] = payload.get("pipeline_mode") or "trusted"
            job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
            _mark_last_stage_failed(job, summary=str(exc))
            finish_attempt(db, job, status="FAILED", summary="可信模式生成失败", error_message=str(exc))
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.case_generation_v2.run_case_generation_v2_job",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_case_generation_v2_job(self, job_id: int, attempt_id: int | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is None:
            return
        attempt = ensure_attempt(db, job, pipeline_version="v2", attempt_id=attempt_id)
        if self.request.id and not attempt.task_id:
            attempt.task_id = self.request.id
            if job.active_attempt_id == attempt.id:
                job.task_id = self.request.id
            db.commit()
        payload = dict(job.input_payload_json or {})
        pipeline_mode = _normalize_pipeline_mode(payload.get("pipeline_mode"))
    finally:
        db.close()
    with bind_attempt(attempt.id, "v2", attempt.run_id), AttemptHeartbeat(attempt.id, "v2"):
        db = SessionLocal()
        try:
            active_job = db.get(CaseGenerationV2Job, job_id)
            active_attempt = ensure_attempt(db, active_job, pipeline_version="v2", attempt_id=attempt.id)
            mark_attempt_running(db, active_job, active_attempt)
        finally:
            db.close()
        if pipeline_mode == "trusted":
            if str(payload.get("trusted_resume_from_stage") or "").strip() == "testcase_gate":
                _resume_trusted_v2_from_testcase_gate(job_id)
                return
            _run_trusted_v2_pipeline(job_id)
            return
        _run_clone_pipeline(job_id)


@celery_app.task(
    name="app.tasks.case_generation_v2.rerun_case_generation_v2_source_shard",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def rerun_case_generation_v2_source_shard(
    self,
    job_id: int,
    source_id: str,
    attempt_id: int | None = None,
) -> None:
    db = SessionLocal()
    try:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is None or job.status == "CANCELLED":
            return
        attempt = ensure_attempt(db, job, pipeline_version="v2", attempt_id=attempt_id)
        assert_active_attempt(job, attempt.id, db=db)
        if self.request.id and not attempt.task_id:
            attempt.task_id = self.request.id
            job.task_id = self.request.id
        mark_attempt_running(db, job, attempt)
    finally:
        db.close()
    with bind_attempt(attempt.id, "v2", attempt.run_id), AttemptHeartbeat(attempt.id, "v2"):
        _rerun_case_generation_v2_source_shard_attempt(job_id, source_id, attempt.id)


def _rerun_case_generation_v2_source_shard_attempt(job_id: int, source_id: str, attempt_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is None or job.status == "CANCELLED":
            return
        assert_active_attempt(job, attempt_id, db=db)
        payload = dict(job.input_payload_json or {})
        payload["pipeline_mode"] = payload.get("pipeline_mode") or "trusted"
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
            raise ValueError("缺少模型配置，无法重跑 source shard")

        output_dir = _job_output_dir(job.id)
        scope_index = _trusted_artifact_content(db, job.id, "scope_index", allow_previous=True)
        evidence_trace = _trusted_artifact_content(db, job.id, "evidence_trace", allow_previous=True)
        requirement_payload = _trusted_artifact_content(db, job.id, "requirement_handoff", allow_previous=True)
        requirement_handoff = requirement_payload.get("requirement_handoff") or requirement_payload
        testcase_handoff = _trusted_artifact_content(db, job.id, "testcase_package", allow_previous=True)
        markdown_text = str(payload.get("markdown_text") or "")
        if markdown_text:
            scope_index = _attach_scope_evidence(
                scope_index,
                markdown_text,
                _extract_image_links(markdown_text, payload.get("source_url")),
                evidence_trace.get("image_analysis") or [],
                base_url=payload.get("source_url"),
            )
        source = _source_by_id(scope_index, source_id)
        function_points = [
            item for item in requirement_handoff.get("function_points") or []
            if isinstance(item, dict) and str(item.get("source_id") or "").strip() == source_id
        ]
        if not function_points:
            raise ValueError(f"{source_id} 没有可重跑的功能点")

        source_needs_state_repair = _source_requirement_needs_state_repair(source, function_points)
        if source_needs_state_repair:
            _update_stage(job, db, "requirement", "需求分析", "running", f"正在修复 {source_id} 的 current/target 证据语义")
            scope_index, requirement_handoff, source, function_points = _repair_trusted_state_transition_source_bundle(
                scope_index,
                requirement_handoff,
                source_id,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
            _persist_trusted_artifact(db, job.id, output_dir, "scope_index", "scope_index.json", scope_index)
            scope_gate = _combine_trusted_gate(_validate_trusted_scope_index(scope_index))
            _persist_trusted_artifact(
                db,
                job.id,
                output_dir,
                "scope_index_gate",
                "scope_index_gate.json",
                {"scope_index_gate": scope_gate, "deterministic_gate": _validate_trusted_scope_index(scope_index), "model_handoff_gate": None},
            )
            requirement_deterministic_gate = _validate_trusted_requirement_handoff(scope_index, requirement_handoff)
            requirement_gate, requirement_model_gate = _run_trusted_combined_gate(
                review_stage="requirement_gate",
                deterministic_gate=requirement_deterministic_gate,
                scope_index=scope_index,
                requirement_handoff=requirement_handoff,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
            _persist_trusted_artifact(
                db,
                job.id,
                output_dir,
                "requirement_handoff",
                "requirement_handoff.json",
                {
                    "requirement_handoff": requirement_handoff,
                    "requirement_gate": requirement_gate,
                    "deterministic_gate": requirement_deterministic_gate,
                    "model_handoff_gate": requirement_model_gate,
                },
            )
            if not requirement_gate.get("passed"):
                raise ValueError(f"{source_id} current/target 修复后 requirement_gate 未通过")
            _update_stage(job, db, "requirement", "需求分析", "success", f"{source_id} current/target 语义已修复")
        elif markdown_text:
            requirement_handoff = _normalize_trusted_requirement_handoff(scope_index, requirement_handoff)
            source = _source_by_id(scope_index, source_id)
            function_points = [
                item for item in requirement_handoff.get("function_points") or []
                if isinstance(item, dict) and str(item.get("source_id") or "").strip() == source_id
            ]
            scope_deterministic_gate = _validate_trusted_scope_index(scope_index)
            scope_gate = _combine_trusted_gate(scope_deterministic_gate)
            _persist_trusted_artifact(db, job.id, output_dir, "scope_index", "scope_index.json", scope_index)
            _persist_trusted_artifact(
                db,
                job.id,
                output_dir,
                "scope_index_gate",
                "scope_index_gate.json",
                {"scope_index_gate": scope_gate, "deterministic_gate": scope_deterministic_gate, "model_handoff_gate": None},
            )
            if not scope_gate.get("passed"):
                raise ValueError("证据角色刷新后 scope_index_gate 未通过")
            requirement_deterministic_gate = _validate_trusted_requirement_handoff(scope_index, requirement_handoff)
            requirement_gate = _combine_trusted_gate(requirement_deterministic_gate)
            _persist_trusted_artifact(
                db,
                job.id,
                output_dir,
                "requirement_handoff",
                "requirement_handoff.json",
                {
                    "requirement_handoff": requirement_handoff,
                    "requirement_gate": requirement_gate,
                    "deterministic_gate": requirement_deterministic_gate,
                    "model_handoff_gate": None,
                },
            )
            if not requirement_gate.get("passed"):
                raise ValueError("证据角色刷新后 requirement_gate 未通过")

        _update_stage(job, db, "testcase_by_source_shard", "用例基线", "running", f"正在重跑 {source_id} source shard")
        shard = _build_trusted_testcase_source_shard(
            source,
            function_points,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        _validate_trusted_source_shard_contract(source, function_points, shard)
        shard["source_id"] = source_id
        shard["status"] = "success"
        shard["test_design_profile"] = _normalize_test_design_profile(source.get("test_design_profile"), source)
        shard["function_point_count"] = len(function_points)
        shard["testcase_count"] = len(shard.get("testcases") or [])
        updated_handoff = _replace_trusted_testcase_shard(
            testcase_handoff,
            shard,
            source_by_id=_trusted_source_by_id(scope_index),
        )
        _persist_trusted_artifact(db, job.id, output_dir, "testcase_package", "trusted_testcase_package.json", updated_handoff)
        shard_failure_message = _trusted_shard_failure_message(updated_handoff)
        if shard_failure_message:
            raise ValueError(shard_failure_message)
        _update_stage(job, db, "testcase_by_source_shard", "用例基线", "success", f"{source_id} 重跑完成，当前共 {len(updated_handoff.get('testcases') or [])} 条用例")

        _update_stage(job, db, "testcase_gate", "用例门禁", "running", "正在重新校验 FP 消费、方法消费和溯源")
        testcase_gate, review_report = _rebuild_trusted_delivery_artifacts(
            db,
            job,
            output_dir,
            scope_index,
            requirement_handoff,
            updated_handoff,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        if not testcase_gate.get("passed"):
            raise ValueError(f"testcase_gate 未通过：{len(testcase_gate.get('issues') or [])} 个阻断问题")
        _update_stage(job, db, "testcase_gate", "用例门禁", "success", "用例门禁通过")
        _update_stage(job, db, "quality_review", "质量复核", "success", "可信指标已更新")
        _update_stage(job, db, "export", "导出交付物", "success", "Markdown、JSON 和 XMind 产物已更新")
        _update_stage(job, db, "final_delivery_gate", "交付门禁", "success", "交付门禁通过")

        summary = review_report.get("summary") or {}
        job.summary = f"{source_id} shard 重跑成功，可信模式当前 {summary.get('testcase_count', 0)} 条用例并导出 XMind，交付门禁通过"
        job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
        semantic_readiness = str(summary.get("semantic_release_readiness") or summary.get("release_readiness") or "conditional_pass")
        final_status = "SUCCESS" if semantic_readiness == "pass" else "CONDITIONAL"
        finish_attempt(db, job, status=final_status, summary=job.summary, error_message=None)
    except Exception as exc:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is not None:
            if isinstance(exc, SupersededAttemptError) or job.active_attempt_id != attempt_id:
                db.rollback()
                return
            if job.status == "CANCELLED":
                finish_attempt(db, job, status="CANCELLED", summary="生成已取消", error_message="任务已手动停止")
                return
            _mark_last_stage_failed(job, summary=str(exc))
            finish_attempt(db, job, status="FAILED", summary=f"{source_id} shard 重跑失败", error_message=str(exc))
        raise
    finally:
        db.close()


def _run_clone_pipeline(job_id: int) -> None:
    db = SessionLocal()
    attempt_id = current_attempt_id()
    run_started_at = time.perf_counter()
    audit_log: list[dict] = []
    try:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is None:
            return
        assert_active_attempt(job, attempt_id, db=db)
        if job.status == "CANCELLED":
            return

        payload = dict(job.input_payload_json or {})
        markdown_text = _resolve_markdown_text(payload)
        if not markdown_text:
            message = "请提供需求文本、上传文件内容或有效的需求文档链接"
            finish_attempt(db, job, status="FAILED", summary="输入内容为空", error_message=message)
            raise ValueError(message)

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
            message = "当前工作空间未配置可用模型或 API Key"
            finish_attempt(db, job, status="FAILED", summary="缺少模型配置", error_message=message)
            raise ValueError(message)

        job.status = "RUNNING"
        job.summary = "正在按 claw_5skill_unified/lite 生成 XMind 用例"
        job.started_at = utc_now_naive()
        job.progress_json = {"stages": []}
        sync_attempt_from_job(db, job)
        db.commit()
        _raise_if_job_cancelled(db, job.id)

        output_dir = _job_output_dir(job.id)
        output_stem = _sanitize_file_stem(job.source_document_name or job.name)
        image_links = _extract_image_links(markdown_text, payload.get("source_url"))
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
        image_result = _analyze_images(api_key, model, base_url, downloaded_images)
        image_analysis = image_result.get("images") or []
        image_skip_notes = image_result.get("skipped") or []
        _raise_if_job_cancelled(db, job.id)
        download_failed_count = sum(1 for item in downloaded_images if item.get("download_status") == "failed")
        image_summary_text = f"已识别 {len(image_analysis)} 张图片，下载失败 {download_failed_count} 张"
        if image_skip_notes:
            image_summary_text += f"，识图降级跳过 {len(image_skip_notes)} 张（已记入待确认）"
        _update_stage(
            job,
            db,
            "image_analysis",
            "图片识别",
            "success",
            image_summary_text,
        )

        _update_stage(job, db, "requirement", "需求分析", "running", "正在生成证据链和功能点")
        analysis = _build_requirement_analysis(
            job=job,
            db=db,
            markdown_text=markdown_text,
            downloaded_images=downloaded_images,
            image_analysis=image_analysis,
            image_skip_notes=image_skip_notes,
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
            block_on_fail=True,
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

        _write_text_file(output_dir, "delivery_summary.md", _build_delivery_summary(job, function_points, testcase_package, review_report))

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
        _upsert_artifact(
            db,
            job_id=job.id,
            artifact_type="xmindmark",
            file_name=xmindmark_file_name,
            file_path=xmindmark_file_path,
            content_json={"text": xmindmark_text},
        )
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
        final_status = "CONDITIONAL" if final_readiness == "conditional_pass" else "SUCCESS"
        if final_readiness == "fail":
            job.summary = f"已导出 XMind（质量审查未通过，{len(review_findings)} 项问题待人工复核），共 {review_report['case_count']} 条用例"
        elif final_readiness == "conditional_pass":
            job.summary = f"已生成 {review_report['case_count']} 条用例并导出 XMind（有条件通过，{len(review_findings)} 项改进建议）"
        else:
            job.summary = f"已生成 {review_report['case_count']} 条用例，并导出 XMind"
        finish_attempt(db, job, status=final_status, summary=job.summary, error_message=None)
    except Exception as exc:
        job = db.get(CaseGenerationV2Job, job_id)
        if job is not None:
            if isinstance(exc, SupersededAttemptError) or job.active_attempt_id != attempt_id:
                db.rollback()
                return
            if job.status == "CANCELLED":
                finish_attempt(db, job, status="CANCELLED", summary="生成已取消", error_message="任务已手动停止")
                return
            payload = dict(job.input_payload_json or {})
            job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
            _mark_last_stage_failed(job, summary=str(exc))
            finish_attempt(db, job, status="FAILED", summary="生成失败", error_message=str(exc))
        raise
    finally:
        db.close()
