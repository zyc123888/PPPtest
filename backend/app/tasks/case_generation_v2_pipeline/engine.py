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

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import AIModelConfig, CaseGenerationV2Job
from app.tasks import case_generation as original_case_generation
from app.tasks.case_generation_common import (
    inspect_xmind_archive,
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
from app.tasks.case_generation_v2_support.async_runtime import run_async
from app.tasks.case_generation_v2_support.cache import (
    build_shard_cache_metadata,
    can_reuse_trusted_requirement as support_can_reuse_trusted_requirement,
    can_reuse_trusted_scope_index as support_can_reuse_trusted_scope_index,
    shard_cache_mismatch,
)
from app.tasks.case_generation_v2_support.density import (
    apply_generation_density,
    current_generation_density,
    generation_density_profile,
    reset_generation_density,
    set_generation_density,
)
from app.tasks.case_generation_v2_support.gates import combine_trusted_gate
from app.tasks.secure_fetch import fetch_resource, fetch_resource_async
from app.tasks.model_client import call_json_chat_completion
from app.timeutil import utc_now_naive
from app.tasks.case_generation_v2_pipeline.artifacts import (
    artifact_content as _trusted_artifact_content,
    artifact_json_payload as _artifact_json_payload,
    artifact_record as _trusted_artifact_record,
    artifact_text as _trusted_artifact_text,
    atomic_replace_file as _atomic_replace_file,
    ensure_output_dir_writable as _ensure_output_dir_writable,
    ensure_writable_dir as _ensure_writable_dir,
    optional_artifact_content as _optional_trusted_artifact_content,
    persist_artifact as _persist_trusted_artifact,
    read_text_if_exists as _read_text_if_exists,
    write_json_file as _write_json_file,
    write_text_file as _write_text_file,
    write_yaml_file as _write_yaml_file,
    upsert_artifact as _upsert_artifact,
)
from app.tasks.case_generation_v2_pipeline.normalizers import (
    coerce_atomicity_check as _coerce_atomicity_check,
    coerce_review_flags as _coerce_review_flags,
    coerce_source_refs as _coerce_source_refs,
    coerce_test_data as _coerce_test_data,
    is_trusted_pipeline_mode as _is_trusted_pipeline_mode,
    normalize_pipeline_mode as _normalize_pipeline_mode,
    sources_from_refs as _sources_from_refs,
)
from app.tasks.case_generation_v2_pipeline.validators import (
    count_xmindmark_function_point_nodes as _count_xmindmark_function_point_nodes,
    count_xmindmark_source_nodes as _count_xmindmark_source_nodes,
    count_xmindmark_testcase_nodes as _count_xmindmark_testcase_nodes,
    require as _gate,
    validate_xmindmark as _validate_xmindmark,
)
from app.tasks.case_generation_v2_pipeline.xmind_export import (
    append_node as _append_node,
    convert_xmindmark as _convert_xmindmark,
    sanitize_file_stem as _sanitize_file_stem,
    write_xmind_file as _write_xmind_archive,
)
from app.tasks.case_generation_v2_pipeline.stages import (
    DeliveryStageInput,
    RequirementStageInput,
    ScopeStageInput,
    TestcaseStageInput,
    run_delivery_stage,
    run_requirement_stage,
    run_scope_stage,
    run_testcase_stage,
)
from app.tasks.case_generation_v2_pipeline.orchestration import PipelineDispatchInput, dispatch_pipeline


logger = logging.getLogger(__name__)


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_HTML_BLOCK_PATTERN = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_MARKDOWN_LINK_ONLY_PATTERN = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")

_DEFAULT_MODEL = settings.case_gen_default_model
_OPENAI_BASE_URL = settings.case_gen_openai_base_url
_BAILIAN_BASE_URL = settings.case_gen_bailian_base_url
_QWEN_COMPATIBLE_BASE_URL = settings.case_gen_qwen_compatible_base_url
_QWEN_CODING_INTL_BASE_URL = settings.case_gen_qwen_coding_intl_base_url
_SECRET_SENTINEL = "***已提供***"
# engine.py lives under backend/app/tasks/case_generation_v2_pipeline. Relative
# rules directories in config are rooted at backend, matching Docker's /app.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
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
    return apply_generation_density(profile)


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
    unified_value = (settings.case_generation_unified_rules_dir or "").strip()
    if unified_value:
        configured = _resolve_rules_dir(unified_value)
        if configured.exists():
            return configured

    legacy_value = (settings.case_generation_rules_dir or "").strip()
    if legacy_value:
        legacy = _resolve_rules_dir(legacy_value)
        if legacy.exists():
            return legacy

    bundled_unified = _BACKEND_ROOT / "claw_5skill_unified"
    if bundled_unified.exists():
        return bundled_unified
    return _BACKEND_ROOT / "claw_5skill_final"


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
    return run_async(_download_image_links_async(image_links, output_dir))


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
    if "{" not in stripped:
        raise ValueError("模型输出缺少 JSON 对象起始符 `{`")

    depth = 0
    in_string = False
    escape = False
    start: int | None = None
    complete_objects: list[str] = []
    for index, char in enumerate(stripped):
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
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                complete_objects.append(stripped[start : index + 1])
                start = None

    if complete_objects:
        # Models sometimes emit a small draft object inside <thinking> before
        # the requested result. The final complete object is the deliverable.
        return complete_objects[-1]

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
    return run_async(_call_openai_json_async(**kwargs))


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
            "请严格对照 Schema 修正后直接重新输出完整 JSON。"
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
            "必须严格遵守以上 schema。只输出一个合法 JSON 对象，不输出 <thinking>、Markdown 或解释文字。\n\n"
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
                result = run_async(_repair_model_json_async(
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
    return run_async(_analyze_images_async(api_key, model, base_url, downloaded_images))


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
    batch_results = run_async(
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
    batch_results = run_async(
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
        repair_batch_results = run_async(
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

    ai_review = run_async(_call_skill_with_gate_async(
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
    for index, pc in enumerate(pending_confirmations, start=1):
        if isinstance(pc, dict):
            pc_id = str(pc.get("pending_id") or pc.get("id") or "").strip()
            topic = str(pc.get("topic") or "").strip()
            message = str(
                pc.get("message")
                or pc.get("description")
                or pc.get("question")
                or pc.get("reason")
                or pc.get("impact")
                or ""
            ).strip()
            if topic and message and topic not in message:
                message = f"{topic}：{message}"
            elif topic and not message:
                message = topic
        else:
            pc_id = ""
            message = str(pc or "").strip()
        pc_msg = _short_text(message, 100) or f"待确认项 {index}（详情缺失）"
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






































































































_TEST_DATA_REQUIRED_METHODS = {"boundary", "boundary_value", "decision_table", "state_transition"}
_NAVIGATION_SELECTION_PATTERN = re.compile(
    r"选择[^，。,；;]*(?:tab|页签|页面|模块|菜单|按钮)(?=[，。,；;]|后|并|展开|收起|查看|检查|$)",
    re.IGNORECASE,
)
































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
        delivery_stage = _run_trusted_delivery_stage(
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
        testcase_gate = delivery_stage.testcase_gate
        review_report = delivery_stage.review_report
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
            scope_stage = run_scope_stage(
                ScopeStageInput(
                    markdown_text=markdown_text,
                    image_analysis=image_analysis,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    progress_callback=lambda summary: _update_stage(job, db, "scope_index", "范围索引", "running", summary),
                ),
                build_scope_index=_build_trusted_scope_index,
            )
            scope_index = scope_stage.scope_index
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
            requirement_stage = run_requirement_stage(
                RequirementStageInput(
                    scope_index=scope_index,
                    markdown_text=markdown_text,
                    image_analysis=image_analysis,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    progress_callback=lambda summary: _update_stage(job, db, "requirement", "需求分析", "running", summary),
                ),
                build_requirement_handoff=_build_trusted_requirement_handoff,
            )
            requirement_handoff = requirement_stage.requirement_handoff
        requirement_handoff, converged_requirement_sources = _converge_requirement_handoff_state_conflicts(
            scope_index,
            requirement_handoff,
        )
        if converged_requirement_sources:
            _update_stage(
                job,
                db,
                "requirement",
                "需求分析",
                "running",
                f"已按 target 证据收敛 {len(converged_requirement_sources)} 个 current/target 冲突对象",
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
            testcase_stage = run_testcase_stage(
                TestcaseStageInput(
                    scope_index=scope_index,
                    requirement_handoff=requirement_handoff,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    previous_handoff=previous_testcase_handoff,
                    progress_callback=update_trusted_testcase_progress,
                ),
                build_testcase_handoff=_build_trusted_testcase_handoff,
            )
            testcase_handoff = testcase_stage.testcase_handoff
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
            _run_trusted_delivery_stage(
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
        if job is None or job.status == "CANCELLED":
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
            if active_job is None or active_job.status == "CANCELLED":
                return
            active_attempt = ensure_attempt(db, active_job, pipeline_version="v2", attempt_id=attempt.id)
            mark_attempt_running(db, active_job, active_attempt)
        finally:
            db.close()
        density_token = set_generation_density(payload.get("generation_density"))
        try:
            dispatch_pipeline(
                PipelineDispatchInput(
                    job_id=job_id,
                    pipeline_mode=pipeline_mode,
                    resume_from_stage=payload.get("trusted_resume_from_stage"),
                ),
                run_lite=_run_clone_pipeline,
                run_trusted=_run_trusted_v2_pipeline,
                resume_trusted_from_testcase_gate=_resume_trusted_v2_from_testcase_gate,
            )
        finally:
            reset_generation_density(density_token)


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
    density_token = None
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
        density_token = set_generation_density((job.input_payload_json or {}).get("generation_density"))
    finally:
        db.close()
    with bind_attempt(attempt.id, "v2", attempt.run_id), AttemptHeartbeat(attempt.id, "v2"):
        try:
            _rerun_case_generation_v2_source_shard_attempt(job_id, source_id, attempt.id)
        finally:
            if density_token is not None:
                reset_generation_density(density_token)


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
        shard["cache_metadata"] = build_shard_cache_metadata(
            source,
            function_points,
            rules_sha256=_unified_rules_sha256(),
            model=model,
            generation_contract_version=_TRUSTED_GENERATION_CONTRACT_VERSION,
            generation_density=current_generation_density(),
        )
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
        delivery_stage = _run_trusted_delivery_stage(
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
        testcase_gate = delivery_stage.testcase_gate
        review_report = delivery_stage.review_report
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

# Stage implementations are imported after core helpers and task orchestration are defined.
from app.tasks.case_generation_v2_pipeline.stages.scope_impl import (
    _normalize_requirement_quote,
    _requirement_state_marker_role,
    _image_urls_in_text_order,
    _requirement_state_semantics,
    _is_state_label_only,
    _source_evidence_role,
    _current_state_basis_is_allowed,
    _current_state_positive_expectation_is_retained,
    _current_state_expectation_is_allowed,
    _state_attribute_values,
    _source_state_evidence_text,
    _state_target_conflicts,
    _resolve_requirement_source_quote,
    _section_evidence_catalog,
    _scope_evidence_match,
    _attach_scope_evidence,
    _trusted_scope_fingerprint,
    _unified_rules_sha256,
    _can_reuse_trusted_scope_index,
    _can_reuse_trusted_requirement,
    _build_trusted_source_manifest,
    _build_trusted_evidence_artifact,
    _validate_trusted_evidence_trace,
    _merge_evidence_risks_into_scope_index,
    _scope_index_should_use_section_batches,
    _scope_index_document_stats,
    _build_scope_index_section_batches,
    _choose_scope_index_strategy,
    _replace_trusted_scope_refs,
    _flatten_scope_object_items,
    _default_scope_shard_for_block,
    _merge_trusted_scope_index_batches,
    _normalize_trusted_scope_index,
    _build_trusted_scope_index,
    _build_trusted_scope_index_by_section_batches,
    _validate_trusted_scope_index,
)
from app.tasks.case_generation_v2_pipeline.stages.requirement_impl import (
    _build_trusted_requirement_handoff,
    _source_batch_scope_index,
    _source_batch_sections,
    _renumber_trusted_requirement_handoff,
    _repair_pending_confirmation_fp_refs,
    _target_state_obligations,
    _converge_state_repair_output,
    _converge_requirement_handoff_state_conflicts,
    _repair_converted_requirement_consumption,
    _build_trusted_requirement_handoff_by_source_batches,
    _normalize_trusted_requirement_handoff,
    _validate_trusted_requirement_handoff,
    _source_requirement_needs_state_repair,
    _replace_trusted_scope_source,
    _replace_trusted_requirement_source,
    _repair_trusted_state_transition_source_bundle,
)
from app.tasks.case_generation_v2_pipeline.stages.testcase_impl import (
    _normalize_trusted_testcase_handoff,
    _case_requires_executable_test_data,
    _build_trusted_testcase_source_shard,
    _validate_trusted_source_shard_contract,
    _build_trusted_testcase_source_shard_async,
    _is_transient_model_error,
    _renumber_trusted_shard_cases,
    _finalize_trusted_testcase_shards,
    _trusted_shard_failure_message,
    _build_trusted_testcase_handoff_from_lite_package,
    _trusted_xmind_grouping_contract,
    _trusted_case_fingerprint,
    _merge_trusted_duplicate_cases,
    _build_trusted_testcase_handoff,
    _build_trusted_testcase_handoff_async,
    _validate_trusted_testcase_handoff,
    _source_by_id,
    _localize_trusted_shard_case_ids,
    _trusted_reusable_source_shards,
    _replace_trusted_testcase_shard,
)
from app.tasks.case_generation_v2_pipeline.stages.delivery_impl import (
    _normalize_trusted_gate_issues,
    _trusted_source_ids_list,
    _trusted_completed_requirement_sources,
    _trusted_completed_testcase_sources,
    _validate_trusted_model_handoff_gate,
    _trusted_gate_recovery_plan,
    _build_trusted_model_handoff_gate,
    _combine_trusted_gate,
    _run_trusted_combined_gate,
    _trusted_gate_success_summary,
    _build_trusted_review_report,
    _build_trusted_delivery_markdown,
    _trusted_method_for_case,
    _trusted_standard_function_points,
    _trusted_standard_testcase_package,
    _trusted_evidence_trace,
    _build_trusted_semantic_review,
    _export_trusted_xmind,
    _build_final_delivery_gate,
    _canonical_gate_report_for_validator,
    _write_trusted_canonical_files,
    _run_unified_trusted_validator,
    _run_final_delivery_gate,
    _rebuild_trusted_delivery_artifacts,
    _run_trusted_delivery_stage,
)
