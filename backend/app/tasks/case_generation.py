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
_GENERIC_EXPECTATION_REPLACEMENTS = {
    "系统正常": "页面状态、接口返回和数据记录均可被复核",
    "结果正确": "关键字段、状态值和数据记录与规则一致",
    "功能正常": "相关入口、状态流转和数据记录均可被复核",
    "符合预期": "页面状态、接口返回字段或数据记录可被复核",
    "操作成功": "操作后状态、提示文案和数据记录完成更新",
    "结果符合需求": "结果中的字段、状态和业务记录与需求规则一致",
    "符合需求": "字段、状态和业务记录与需求规则一致",
    "满足需求": "字段、状态和业务记录与需求规则一致",
    "按预期": "页面状态、接口返回字段或数据记录可被复核",
    "正确显示": "展示指定字段、排序位置、选中状态或提示文案",
    "正常显示": "展示指定字段、排序位置、选中状态或提示文案",
    "校验通过": "校验结果展示为可复核的状态、提示或记录",
    "验证通过": "验证结果展示为可复核的状态、提示或记录",
    "观察页面、接口和数据结果": "核对页面状态、接口返回和数据记录",
    "观察结果": "核对页面状态、接口返回和数据记录",
}


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


def _sanitize_expected_phrase(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern, replacement in _GENERIC_EXPECTATION_REPLACEMENTS.items():
        text = text.replace(pattern, replacement)
    return text.strip(" ；;，,")


def _expected_results_are_generic(expected_results) -> bool:
    if isinstance(expected_results, str):
        expected_text = expected_results
    elif isinstance(expected_results, list):
        expected_text = " ".join(str(item) for item in expected_results)
    else:
        expected_text = ""
    return _text_contains_any(expected_text, _GENERIC_EXPECTATION_PATTERNS)


def _expected_has_observable_anchor(expected_results) -> bool:
    if isinstance(expected_results, str):
        expected_text = expected_results
    elif isinstance(expected_results, list):
        expected_text = " ".join(str(item) for item in expected_results)
    else:
        expected_text = ""
    return _text_contains_any(expected_text, _EXPECTED_OBSERVABLE_ANCHORS)


def _normalize_expected_results_list(expected_results) -> list[str]:
    if isinstance(expected_results, str):
        items = [expected_results]
    elif isinstance(expected_results, list):
        items = expected_results
    else:
        items = []
    normalized: list[str] = []
    for item in items:
        text = _sanitize_expected_phrase(str(item))
        if text:
            normalized.append(text)
    return normalized


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


def _build_specific_expected_results(case: dict, fp: dict) -> list[str]:
    title = str(case.get("title") or fp.get("title") or case.get("fp_id") or "").strip()
    module = str(case.get("module") or fp.get("module") or "需求模块").strip()
    scene = str(case.get("scene") or fp.get("scene") or "需求场景").strip()
    description = _compact_case_text(fp.get("description"))
    rules = _compact_case_text(fp.get("rules"))
    hints = fp.get("test_hints") or {}
    positive = _compact_case_text(hints.get("positive"))
    boundary = _compact_case_text(hints.get("boundary"))
    negative = _compact_case_text(hints.get("negative"))
    action_preview = ""
    steps = case.get("steps") or []
    if isinstance(steps, list) and steps:
        first_step = steps[0]
        if isinstance(first_step, dict):
            action_preview = str(first_step.get("action") or first_step.get("expected") or "").strip()
        else:
            action_preview = str(first_step).strip()

    summary_parts = [part for part in [title, module, scene, description[:80], rules[:80]] if part]
    base = "；".join(summary_parts[:3]) if summary_parts else (title or module or scene)
    if action_preview:
        base = f"{base}；执行{action_preview[:40]}后"
    if positive:
        primary = f"{base}，页面展示、接口返回或数据记录应体现：{positive[:120]}"
    else:
        primary = f"{base}，应产生可观察的页面状态、接口字段或后台记录变化，并可通过日志/列表/详情页复核"

    secondary_bits = [item for item in [boundary, negative] if item]
    if secondary_bits:
        secondary = f"边界/异常场景下，提示文案、状态流转、拦截结果或数据记录应体现：{'；'.join(secondary_bits)[:180]}"
    else:
        secondary = f"{scene} 相关关键字段、状态值、筛选结果或操作记录应可在页面/接口/数据库侧复核"

    return [_sanitize_expected_phrase(primary), _sanitize_expected_phrase(secondary)]


def _ensure_specific_expected_results(case: dict, fp: dict) -> list[str]:
    expected_results = _normalize_expected_results_list(case.get("expected_results"))
    expected_text = " ".join(expected_results)
    needs_rebuild = (
        not expected_results
        or len(expected_text) < 40
        or _expected_results_are_generic(expected_results)
        or not _expected_has_observable_anchor(expected_results)
    )
    if needs_rebuild:
        expected_results = _normalize_expected_results_list(_build_specific_expected_results(case, fp))

    if len(expected_results) < 2:
        fallback = _build_specific_expected_results(case, fp)
        for item in fallback:
            text = _sanitize_expected_phrase(item)
            if text and text not in expected_results:
                expected_results.append(text)
            if len(expected_results) >= 2:
                break

    expected_text = " ".join(expected_results)
    if _expected_results_are_generic(expected_results):
        expected_results = [_sanitize_expected_phrase(item) for item in expected_results]
    if not _expected_has_observable_anchor(expected_results):
        expected_results.append(
            "核对页面状态、接口返回字段、后台数据记录或任务日志，确保实际结果可复核并能追溯到对应需求规则"
        )
    if len(" ".join(expected_results)) < 40:
        expected_results.append(
            "关键业务对象的字段值、状态流转、提示文案和持久化记录应与功能点规则一致"
        )
    return [item for item in expected_results if item]


def _build_specific_steps(case: dict, fp: dict) -> list[dict]:
    title = str(case.get("title") or fp.get("title") or case.get("fp_id") or "当前功能点").strip()
    module = str(case.get("module") or fp.get("module") or "需求模块").strip()
    scene = str(case.get("scene") or fp.get("scene") or "需求场景").strip()
    description = _compact_case_text(fp.get("description")) or title
    rules = _compact_case_text(fp.get("rules"))
    hints = fp.get("test_hints") or {}
    positive = _compact_case_text(hints.get("positive")) or description
    boundary = _compact_case_text(hints.get("boundary"))
    test_data = case.get("test_data") or []
    if isinstance(test_data, list):
        data_text = "；".join(str(item) for item in test_data[:3] if str(item).strip())
    else:
        data_text = str(test_data or "").strip()
    if not data_text:
        data_text = rules[:120] or positive[:120] or description[:120]

    return [
        {
            "step_no": 1,
            "action": f"打开 {module} 中的 {scene} 功能入口，定位到与「{title}」相关的配置、列表或操作区域",
            "expected": f"页面或接口入口可用，能看到与「{module}/{scene}」相关的业务对象或操作控件",
        },
        {
            "step_no": 2,
            "action": f"准备并录入测试条件：{data_text}",
            "expected": "测试数据可被页面、接口或后台任务识别，未出现前置校验异常",
        },
        {
            "step_no": 3,
            "action": f"按需求执行「{description[:140]}」对应的核心操作或触发流程",
            "expected": f"系统按「{positive[:160]}」处理，并产生可观察的页面状态、接口返回或数据变更",
        },
        {
            "step_no": 4,
            "action": f"核验结果并补充检查边界/异常条件：{(boundary or rules or description)[:140]}",
            "expected": f"结果与功能点 {fp.get('fp_id') or case.get('fp_id') or ''} 的规则一致，关键状态、记录、提示信息可复核",
        },
    ]


def _build_variant_steps(case: dict, fp: dict, variant: dict) -> list[dict]:
    title = str(fp.get("title") or case.get("title") or "当前功能点").strip()
    module = str(case.get("module") or fp.get("module") or "需求模块").strip()
    scene = str(case.get("scene") or fp.get("scene") or "需求场景").strip()
    focus = str(variant.get("focus") or _compact_case_text(fp.get("description")) or title).strip()
    key = str(variant.get("key") or "").strip()
    step_map = {
        "default_state": [
            f"进入 {module} 的 {scene} 页面，刷新后不做任何筛选或编辑操作",
            "检查默认可见字段、按钮、标签、占位文案和初始选中状态",
            "对照需求或截图核对默认态下隐藏/展示的字段边界",
        ],
        "expand_collapse": [
            f"进入 {module} 的 {scene} 页面，定位到展开/收起或二级菜单入口",
            "点击展开入口，检查新增区域的位置、动画、字段顺序和按钮状态",
            "再次点击收起入口，检查隐藏字段、箭头方向和已输入条件是否按规则保留",
        ],
        "field_order": [
            f"进入 {module} 的 {scene} 页面，打开涉及字段展示的区域",
            "逐项核对字段名称、字段顺序、改名结果和数据来源",
            "执行一次查询、保存或选择操作，检查字段值是否参与后续逻辑",
        ],
        "invalid_filter": [
            f"进入 {module} 的 {scene} 页面，准备空值、特殊字符、超长文本和不存在的数据",
            "分别提交异常输入，观察提示、按钮状态和结果列表",
            "清空异常条件后重新提交有效条件，确认页面恢复正常",
        ],
        "responsive_layout": [
            f"进入 {module} 的 {scene} 页面，分别切换宽屏、窄屏和浏览器缩放比例",
            "执行展开、收起、输入、清空等连续操作",
            "检查字段换行、按钮位置、弹层边界和内容遮挡情况",
        ],
        "pagination": [
            f"进入 {module} 的 {scene} 列表，准备多页数据",
            "切换页码、每页条数和上一页/下一页按钮",
            "核对总数、当前页范围、接口参数和列表记录是否同步变化",
        ],
        "empty_data": [
            f"进入 {module} 的 {scene} 页面，构造无数据或末页无记录条件",
            "执行查询、翻页或筛选操作",
            "检查空态文案、分页按钮禁用状态和历史数据是否被清空",
        ],
        "table_overflow": [
            f"进入 {module} 的 {scene} 表格，准备长文本、长 ID 或多列数据",
            "观察列宽、截断、省略号、tooltip 和横向滚动表现",
            "点击或悬停长文本字段，核对完整内容是否可查看",
        ],
        "large_data": [
            f"进入 {module} 的 {scene} 页面，准备大批量列表或候选项数据",
            "执行加载、翻页、搜索或展开操作",
            "记录响应时间、加载状态、按钮可用性和失败提示",
        ],
        "keyword_search": [
            f"进入 {module} 的 {scene} 搜索入口，准备完整 ID、部分 ID、名称和混合关键词",
            "分别输入关键词并触发搜索",
            "核对匹配规则、返回记录、展示格式和选中回填结果",
        ],
        "no_match": [
            f"进入 {module} 的 {scene} 搜索入口，输入不存在的关键词或非法格式",
            "触发搜索后观察无结果提示和下拉列表状态",
            "清空关键词再次搜索，确认历史无结果状态不会残留",
        ],
        "multi_select": [
            f"进入 {module} 的 {scene} 多选控件，打开候选项列表",
            "连续选择多个候选项，再删除其中一个标签",
            "切换全选、反选或清空操作，检查标签展示和提交值",
        ],
        "option_source": [
            f"进入 {module} 的 {scene} 候选项控件，打开选项列表",
            "核对候选项名称、ID、顺序、搜索结果和业务来源",
            "选择候选项并提交，检查请求参数或保存结果是否使用正确来源值",
        ],
        "status_display": [
            f"进入 {module} 的 {scene} 状态展示区域，准备不同状态的数据",
            "分别查看图标、按钮、颜色、文案和 Preview/操作可用性",
            "切换或刷新状态，检查视觉状态与后台数据是否一致",
        ],
        "state_transition": [
            f"进入 {module} 的 {scene} 页面，准备可触发状态变化的数据",
            "触发上传、保存、启停、刷新或其他状态变化动作",
            "核对状态流转顺序、最终状态、日志记录和接口返回",
        ],
        "conflict_rule": [
            f"进入 {module} 的 {scene} 页面，准备需求存在冲突或待确认的数据",
            "触发冲突场景对应的操作",
            "检查系统是否给出明确提示、禁用风险操作或保留待确认记录",
        ],
        "permission_guard": [
            f"使用无权限或受限角色进入 {module} 的 {scene} 页面",
            "尝试执行查看、编辑、保存或搜索操作",
            "检查权限提示、按钮禁用状态、接口状态码和数据未变更",
        ],
        "data_integrity": [
            f"进入 {module} 的 {scene} 页面，准备包含已存在字段值的数据",
            "只修改目标字段并提交保存",
            "对比保存前后页面、接口返回和数据记录，确认未修改字段未被覆盖",
        ],
    }
    actions = step_map.get(key) or [
        f"进入 {module} 的 {scene} 页面，定位「{title}」相关入口",
        f"按测试关注点执行：{focus[:120]}",
        "核对页面状态、接口返回、数据记录和提示文案",
    ]
    return [{"step_no": index, "action": action} for index, action in enumerate(actions, start=1)]


def _build_variant_expected_results(case: dict, fp: dict, variant: dict) -> list[str]:
    title = str(fp.get("title") or case.get("title") or "当前功能点").strip()
    focus = str(variant.get("focus") or _compact_case_text(fp.get("description")) or title).strip()
    key = str(variant.get("key") or "").strip()
    expected_map = {
        "default_state": [
            f"默认态展示内容与「{title}」规则一致，核心字段、按钮和占位文案可直接核对。",
            "隐藏字段不会占用可见布局，默认选中值和空态提示不会影响后续操作。",
        ],
        "expand_collapse": [
            "展开后新增字段位于预期区域，箭头方向、动画和按钮状态同步变化。",
            "收起后高级字段隐藏，已输入条件按需求保留或清空，Search/Clear 等操作入口仍可用。",
        ],
        "field_order": [
            f"字段名称、展示顺序、改名结果和数据来源均与「{title}」规则一致。",
            "执行查询或保存后，相关字段值会进入接口参数、列表展示或数据记录，且无错位。",
        ],
        "invalid_filter": [
            "空值、非法字符、超长文本和无匹配数据均有明确提示或稳定空态。",
            "异常输入不会触发前端报错、接口 500 或旧结果残留，恢复有效输入后结果正常刷新。",
        ],
        "responsive_layout": [
            "不同宽度下字段、按钮、弹层和标签不会重叠、截断关键内容或超出容器。",
            "连续操作后最终状态稳定，展开/收起方向、选中状态和已输入内容保持一致。",
        ],
        "pagination": [
            "页码、每页条数、总数、当前页范围和接口参数同步变化。",
            "切换分页后列表记录正确刷新，不出现重复、遗漏、空白或旧数据残留。",
        ],
        "empty_data": [
            "无数据场景展示明确空态文案，列表记录被清空，分页按钮进入正确禁用状态。",
            "从空态恢复到有数据条件后，列表、总数和分页状态能重新同步。",
        ],
        "table_overflow": [
            "长文本按规则截断或换行，tooltip/详情入口可查看完整内容。",
            "多列或长字段不会破坏表格对齐、操作列可见性和横向滚动体验。",
        ],
        "large_data": [
            "大数据量下加载状态明确，列表、搜索或分页在可接受时间内完成反馈。",
            "加载失败或超时会给出可见提示，不会造成按钮卡死或数据错乱。",
        ],
        "keyword_search": [
            "完整 ID、部分 ID、名称和混合关键词返回符合匹配规则的结果。",
            "展示格式、排序、高亮和选中回填内容与接口返回字段一致。",
        ],
        "no_match": [
            "无匹配关键词展示明确无结果状态，下拉列表或结果区不会残留历史数据。",
            "清空关键词后可恢复默认列表或重新搜索，接口参数同步清空。",
        ],
        "multi_select": [
            "多选标签新增、删除、全选和清空后，页面标签与提交值保持一致。",
            "标签过多时展示不重叠、不遮挡关键按钮，候选项选中状态准确回显。",
        ],
        "option_source": [
            "候选项名称、ID、排序和搜索结果来自正确业务来源。",
            "提交后接口参数或保存记录使用选中项真实值，不出现展示值与提交值不一致。",
        ],
        "status_display": [
            "不同状态的图标、颜色、按钮、文案和 Preview 可用性清晰区分。",
            "刷新或状态变化后，页面状态与接口返回、后台记录保持一致。",
        ],
        "state_transition": [
            "状态按需求顺序流转，最终状态、提示文案和操作按钮同步更新。",
            "异常或失败状态会保留可追踪日志/记录，不会误展示为成功。",
        ],
        "conflict_rule": [
            "冲突或待确认场景有明确提示，风险操作被拦截或进入待确认状态。",
            "系统不会静默按错误规则继续处理，证据冲突点可在记录中追溯。",
        ],
        "permission_guard": [
            "无权限用户看到禁用按钮、权限提示或接口拒绝状态，不能完成受限操作。",
            "权限拦截后业务数据保持不变，页面、接口和日志均可复核。",
        ],
        "data_integrity": [
            "只修改目标字段时，未修改字段在页面、接口返回和数据记录中保持原值。",
            "保存成功后存在可追踪记录，失败时不会产生部分覆盖或脏数据。",
        ],
    }
    expected = expected_map.get(key) or [
        f"{focus[:100]} 的页面状态、接口返回或数据记录可被直接核对。",
        "异常或边界条件下有明确提示，关键业务数据保持一致。",
    ]
    return [_sanitize_expected_phrase(item) for item in expected]


def _step_to_text(step) -> str:
    if isinstance(step, dict):
        action = str(step.get("action") or "").strip()
        expected = str(step.get("expected") or "").strip()
        if action and expected:
            return f"{action}；期望：{expected}"
        return action or expected or json.dumps(step, ensure_ascii=False)
    return str(step or "").strip()


def _build_specific_case_title(case: dict, fp: dict) -> str:
    fp_title = str(fp.get("title") or "").strip()
    module = str(case.get("module") or fp.get("module") or "").strip()
    scene = str(case.get("scene") or fp.get("scene") or "").strip()
    category = _normalize_category(case.get("category"))
    description = _compact_case_text(fp.get("description"))

    subject_parts = []
    for item in (module, scene, fp_title, description[:32]):
        if item and item not in subject_parts:
            subject_parts.append(item)
    subject = " / ".join(subject_parts[:3]) or str(case.get("fp_id") or "功能点")

    category_prefix = {
        "negative": "异常场景",
        "boundary": "边界场景",
        "security": "安全场景",
        "compatibility": "兼容场景",
        "performance": "性能场景",
    }.get(category, "主流程")
    return f"{subject} - {category_prefix}校验"


def _naturalize_case_title(case: dict, fp: dict) -> str:
    title = re.sub(r"\s+", " ", str(case.get("title") or "")).strip()
    if not title:
        return _build_specific_case_title(case, fp)
    module = str(case.get("module") or fp.get("module") or "").strip()
    scene = str(case.get("scene") or fp.get("scene") or "").strip()
    fp_title = str(fp.get("title") or "").strip()
    for prefix in (
        f"{module} / {scene} / {fp_title} - ",
        f"{module}/{scene}/{fp_title} - ",
        f"{module} / {scene} / ",
        f"{module}/{scene}/",
    ):
        if prefix.strip() and title.startswith(prefix):
            title = title[len(prefix):].strip()
            break
    if fp_title and title in {"主流程校验", "边界条件校验", "异常处理校验", "功能校验"}:
        title = f"{fp_title} - {title}"
    if len(title) > 90:
        title = _short_text(title, 90)
    return title or _build_specific_case_title(case, fp)


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
                "item": _truncate_text(str(item.get("item") or item.get("focus") or item.get("reason") or ""), _PENDING_CONFIRMATION_TEXT_LIMIT),
                "reason": _truncate_text(str(item.get("reason") or ""), _PENDING_CONFIRMATION_TEXT_LIMIT),
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
                has_img_ref = any("IMG-" in str(r) for r in refs)
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
                fp.setdefault("source_refs", [])
                fp.setdefault("rules", [])
                fp.setdefault("priority_hint", "P1")
                fp["priority_hint"] = _normalize_priority(fp.get("priority_hint"), fp=fp)
                fp.setdefault("requirement_group_id", "")
                fp.setdefault("requirement_group_title", "")
                fp.setdefault("atomicity_check", "已按当前批次需求拆分为可验证功能点")
                fp.setdefault("source_distribution", {})
                fp.setdefault("source_order", index)
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
                        '{"evidence_trace": {"image_summary": "string", "images": [{"image_id": "string", "summary": "string", "source_url": "string"}], "pending_confirmations": [{"item": "string", "reason": "string", "status": "pending"}]}, '
                        '"function_points": {"function_points": [{"fp_id": "string", "module": "string", "scene": "string", "requirement_group_id": "string", "requirement_group_title": "string", "title": "string", "type": "string", "description": "string", "source_refs": ["string"], "rules": ["string"], "test_hints": {"positive": ["string"], "boundary": ["string"], "negative": ["string"]}, "priority_hint": "string", "atomicity_check": "string", "source_distribution": "string", "source_order": 1}]}}'
                    ),
                    validator=batch_validator,
                    max_tokens=4000,
                    timeout_seconds=_LONG_CHAT_TIMEOUT_SECONDS,
                    max_attempts=1,
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
    evidence_trace = {
        "image_summary": "\n".join(image_summary_parts) or "无图片证据",
        "images": evidence_images,
        "pending_confirmations": evidence_pending,
    }
    function_points_payload = {"function_points": sorted(function_points, key=lambda item: item.get("source_order", 0))}
    _assign_requirement_groups(function_points_payload)
    return {
        "evidence_trace": evidence_trace,
        "function_points": function_points_payload,
        "pending_confirmations": pending_confirmations or evidence_pending,
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
        case.setdefault("title", f"{fp.get('title') or fp_id}验证")
        case.setdefault("category", "functional")
        case["category"] = _normalize_category(case.get("category"))
        case["title"] = _naturalize_case_title(case, fp)
        if _text_contains_any(str(case.get("title") or ""), _GENERIC_CASE_TITLE_PATTERNS) or len(str(case.get("title") or "").strip()) < 8:
            case["title"] = _build_specific_case_title(case, fp)
        
        fp_priority = _normalize_priority(fp.get("priority_hint"), fp=fp, case=case, category=case["category"])
        raw_case_priority = str(case.get("priority") or "").strip()
        priority_source = fp_priority if raw_case_priority in {"", "P1", "p1", "1"} and fp_priority != "P1" else raw_case_priority
        case["priority"] = _normalize_priority(priority_source or fp_priority, fp=fp, case=case, category=case["category"])
        
        case.setdefault("tags", ["AI-GEN"])
        case.setdefault("preconditions", [])
        case.setdefault("test_data", [])
        case.setdefault("steps", [])
        case.setdefault("expected_results", [])
        case.setdefault("traceability", {"function_points": [fp_id], "sources": fp.get("source_refs") or ["text"]})
        if isinstance(case.get("traceability"), dict):
            case["traceability"].setdefault("function_points", [fp_id])
            case["traceability"].setdefault("sources", fp.get("source_refs") or ["text"])
        case.setdefault("generation_basis", {"method": "functional", "rationale": "基于功能点生成"})
        case.setdefault("scenario_dimensions", [case["category"]])
        case.setdefault("baseline_candidate", case.get("category") == "functional")
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
        steps_text_before = " ".join(_step_to_text(item) for item in case.get("steps") or [])
        if (
            len(case.get("steps") or []) < 3
            or len(steps_text_before) < 60
            or _text_contains_any(steps_text_before, _GENERIC_STEP_PATTERNS)
        ):
            case["steps"] = _build_specific_steps(case, fp)
        case["expected_results"] = _ensure_specific_expected_results(case, fp)
        if fp_id not in allowed_fp_ids:
            case["fp_id"] = fp_id
        return case

    def target_case_count_for_fp(fp: dict) -> int:
        text = _compact_case_text(fp).lower()
        high_variation_terms = (
            "筛选",
            "filter",
            "搜索",
            "search",
            "分页",
            "page",
            "上传",
            "upload",
            "tooltip",
            "悬停",
            "hover",
            "状态",
            "status",
            "兼容",
            "responsive",
            "响应式",
            "主题",
            "排序",
            "多选",
            "标签",
            "dropdown",
            "下拉",
        )
        return 5 if any(term in text for term in high_variation_terms) else _MIN_CASES_PER_FUNCTION_POINT

    def supplemental_variants_for_fp(fp: dict) -> list[dict]:
        text = _compact_case_text(fp).lower()
        variants: list[dict] = []

        def add(key: str, label: str, category: str, focus: str, priority: str | None = None) -> None:
            if key in {item["key"] for item in variants}:
                return
            variants.append(
                {
                    "key": key,
                    "label": label,
                    "category": _normalize_category(category),
                    "focus": focus,
                    "priority": priority,
                }
            )

        if any(term in text for term in ("筛选", "filter", "more filters", "字段", "field")):
            add("default_state", "默认展示", "ui", "验证默认态字段展示、字段顺序、核心筛选项和按钮状态")
            add("expand_collapse", "展开折叠", "ui", "验证展开/折叠、箭头方向、二级菜单位置和布局稳定性")
            add("field_order", "字段顺序", "functional", "验证新增、改名或排序后的字段位置、可见性和数据来源")
            add("invalid_filter", "异常输入", "negative", "验证空值、非法值、无匹配数据时的提示和结果列表")
            add("responsive_layout", "响应式布局", "compatibility", "验证窄屏、缩放、快速点击下筛选栏布局不重叠")
        if any(term in text for term in ("分页", "page", "每页", "列表", "表格", "table")):
            add("pagination", "分页切换", "functional", "验证页码、每页条数、总数和列表数据范围")
            add("empty_data", "空数据", "boundary", "验证无数据、末页、超出页码时的空态和分页控件状态")
            add("table_overflow", "列宽截断", "ui", "验证长文本截断、tooltip、列宽和表格横向布局")
            add("large_data", "大数据量", "performance", "验证大数据量下列表加载、分页切换和交互响应")
        if any(term in text for term in ("搜索", "search", "模糊", "匹配")):
            add("keyword_search", "关键词搜索", "functional", "验证关键词、前缀/包含匹配、大小写和结果格式")
            add("no_match", "无匹配结果", "negative", "验证无匹配数据、特殊字符和清空搜索后的结果恢复")
        if any(term in text for term in ("多选", "标签", "下拉", "dropdown", "select", "country", "location")):
            add("multi_select", "多选标签", "functional", "验证多选、标签展示、删除标签和搜索候选项")
            add("option_source", "选项来源", "functional", "验证候选项来源、Included/Excluded 规则和数据一致性")
        if any(term in text for term in ("上传", "upload", "素材", "preview", "icon", "状态")):
            add("status_display", "状态展示", "ui", "验证上传状态、图标样式、Preview 可用性和操作按钮状态")
            add("state_transition", "状态流转", "functional", "验证未上传、上传中、上传成功、失败状态的流转和数据记录")
            add("conflict_rule", "冲突规则", "negative", "验证证据冲突或未明确状态下的拦截、提示和待确认项")
        if any(term in text for term in ("保存", "更新", "覆盖", "删除", "权限", "预算", "状态变更", "任务")):
            add("permission_guard", "权限拦截", "security", "验证无权限、缺少参数、非法状态下的提示和数据不变")
            add("data_integrity", "数据完整性", "negative", "验证保存或更新时未修改字段不被覆盖，变更记录可追溯")

        fallback_hints = fp.get("test_hints") or {}
        add("main_flow", "主路径", "functional", _compact_case_text(fallback_hints.get("positive")) or _compact_case_text(fp.get("description")) or "验证核心业务流程")
        add("boundary_rule", "边界条件", "boundary", _compact_case_text(fallback_hints.get("boundary")) or "验证边界值、空态和组合条件")
        add("exception_rule", "异常处理", "negative", _compact_case_text(fallback_hints.get("negative")) or "验证缺失、非法或冲突条件下的处理")
        add("compatibility", "兼容回归", "compatibility", "验证刷新、历史状态、不同数据量或关联模块下表现一致")
        return variants

    def build_supplemental_case(fp: dict, variant: dict, index: int) -> dict:
        fp_id = fp.get("fp_id")
        title = fp.get("title") or fp.get("description") or fp.get("scene") or fp_id
        module = fp.get("module") or "需求模块"
        scene = fp.get("scene") or module
        rules_text = _compact_case_text(fp.get("rules")) or _compact_case_text(fp.get("description")) or str(title)
        label = variant.get("label") or "补充场景"
        category = _normalize_category(variant.get("category"))
        focus = variant.get("focus") or rules_text
        priority = _normalize_priority(variant.get("priority") or fp.get("priority_hint"), fp=fp, category=category)
        short_title = f"{title} - {label}校验"
        case = {
            "case_id": f"TC-TEMP-{index:03d}",
            "fp_id": fp_id,
            "module": module,
            "scene": scene,
            "source_order": fp.get("source_order") or index,
            "title": short_title,
            "category": category,
            "priority": priority,
            "tags": ["AI-GEN", "SUPPLEMENTAL", label],
            "preconditions": [
                f"已登录测试环境并进入 {module} - {scene} 相关页面或接口入口",
                f"已准备可触发「{title}」规则的数据或配置",
            ],
            "test_data": [focus[:180], rules_text[:180]],
            "steps": [],
            "expected_results": [],
            "traceability": {"function_points": [fp_id], "sources": fp.get("source_refs") or []},
            "generation_basis": {"method": variant.get("key") or "supplemental", "rationale": f"后端按功能点内容补齐{label}用例"},
            "scenario_dimensions": [variant.get("key") or category, category],
            "baseline_candidate": category == "functional",
        }
        case["steps"] = _build_variant_steps(case, fp, variant)
        case["expected_results"] = _build_variant_expected_results(case, fp, variant)
        return case

    def supplement_case_density(cases: list[dict]) -> list[dict]:
        supplemented = list(cases)
        existing_titles_by_fp: dict[str, set[str]] = {}
        counts_by_fp = Counter()
        for case in supplemented:
            fp_id = case.get("fp_id")
            if not fp_id:
                continue
            counts_by_fp[fp_id] += 1
            existing_titles_by_fp.setdefault(fp_id, set()).add(re.sub(r"\s+", "", str(case.get("title") or "")))
        supplemental_index = len(supplemented) + 1
        for fp in fps:
            fp_id = fp.get("fp_id")
            if not fp_id:
                continue
            target_count = target_case_count_for_fp(fp)
            for variant in supplemental_variants_for_fp(fp):
                if counts_by_fp[fp_id] >= target_count:
                    break
                candidate = build_supplemental_case(fp, variant, supplemental_index)
                title_key = re.sub(r"\s+", "", str(candidate.get("title") or ""))
                if title_key in existing_titles_by_fp.setdefault(fp_id, set()):
                    continue
                normalize_case(candidate, supplemental_index, {fp_id})
                supplemented.append(candidate)
                existing_titles_by_fp[fp_id].add(title_key)
                counts_by_fp[fp_id] += 1
                supplemental_index += 1
        return supplemented

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
            case["expected_results"] = _ensure_specific_expected_results(case, fp)
            
            fp_priority = _normalize_priority(fp.get("priority_hint"), fp=fp, case=case, category=case.get("category"))
            raw_case_priority = str(case.get("priority") or "").strip()
            priority_source = fp_priority if raw_case_priority in {"", "P1", "p1", "1"} and fp_priority != "P1" else raw_case_priority
            priority = _normalize_priority(priority_source or fp_priority, fp=fp, case=case, category=case.get("category"))
            case["priority"] = priority
            _gate(priority in {"P0", "P1", "P2", "P3"}, f"用例 {case.get('case_id')} 优先级非法")
            
            _gate(isinstance(case.get("steps"), list) and len(case["steps"]) >= 2, f"用例 {case.get('case_id')} 步骤不足")
            _gate(isinstance(case.get("expected_results"), list) and case["expected_results"], f"用例 {case.get('case_id')} 缺少可验证预期")
            title = str(case.get("title") or "")
            steps_text = " ".join(_step_to_text(item) for item in case.get("steps") or [])
            expected_text = " ".join(str(item) for item in case.get("expected_results") or [])
            _gate(not _text_contains_any(title, _GENERIC_CASE_TITLE_PATTERNS), f"用例 {case.get('case_id')} 标题过于模板化")
            _gate(not _text_contains_any(steps_text, _GENERIC_STEP_PATTERNS), f"用例 {case.get('case_id')} 步骤过于模板化")
            _gate(len(title) >= 8, f"用例 {case.get('case_id')} 标题过短，疑似未结合需求")
            _gate(len(steps_text) >= 60, f"用例 {case.get('case_id')} 步骤过短，疑似未结合需求")
            _gate(len(expected_text) >= 40, f"用例 {case.get('case_id')} 预期过短，疑似未结合需求")
            _gate(_expected_has_observable_anchor(case.get("expected_results")), f"用例 {case.get('case_id')} 预期缺少可观察核验点")

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
                "每个 fp_id 至少生成 1 条主流程用例，并根据 test_hints 补充边界、异常、状态流转用例。",
                "category 只能使用 functional/ui/boundary/negative/regression/compatibility/performance/security。",
                "priority 只能使用 P0/P1/P2/P3，并参考 function_points.priority_hint。",
                "标题必须包含具体业务对象、场景或规则，不得使用正常流程验证/主流程验证/边界验证/异常验证等模板标题。",
                "用例必须包含可执行的步骤和预期结果，预期结果必须写成可观察、可判定、可复核的业务结论，不能只写系统正常/结果正确/符合预期等空话。",
                "steps 至少 4 步，必须包含：入口/前置数据、具体操作对象、触发动作、页面或接口或数据层核验；禁止写“进入对应页面/执行正常流程验证/观察结果”。",
                "expected_results 至少 2 条，必须说明可观察结果，例如状态变化、记录落库、接口字段、提示文案、预算或任务状态等。",
                "traceability 必须准确引用 fp_id 和 source_refs。",
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
                '{"testcases": [{"case_id": "string", "fp_id": "string", "title": "string", "category": "functional|ui|boundary|negative|regression|compatibility|performance|security", "priority": "P0|P1|P2|P3", "preconditions": ["string"], "test_data": ["string"], "steps": [{"step_no": 1, "action": "string"}], "expected_results": ["string"], "traceability": {}, "generation_basis": {}, "scenario_dimensions": ["string"], "baseline_candidate": true}]}'
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

    all_cases = supplement_case_density(dedupe_cases(all_cases))
    all_cases = renumber_cases(dedupe_cases(all_cases))
    for index, case in enumerate(all_cases, start=1):
        if isinstance(case, dict):
            normalize_case(case, index, fp_ids)
    missing_ids = sorted(fp_id for fp_id in fp_ids if fp_id not in covered_fp_ids(all_cases))
    _gate(not missing_ids, f"补齐后仍有功能点未被用例覆盖：{', '.join(missing_ids)}")
    insufficient = {
        fp_id: count
        for fp_id, count in Counter(case.get("fp_id") for case in all_cases).items()
        if fp_id in fp_by_id and count < target_case_count_for_fp(fp_by_id[fp_id])
    }
    _gate(not insufficient, f"以下功能点用例密度不足：{insufficient}")
    validate({"testcases": all_cases}, fp_ids, require_all_allowed=True)
    if audit_log is not None:
        audit_log.append(
            {
                "skill": "testcase-designer",
                "attempt": "coverage-merge",
                "status": "passed",
                "testcase_count": len(all_cases),
                "covered_fp_count": len(covered_fp_ids(all_cases)),
                "min_cases_per_fp": _MIN_CASES_PER_FUNCTION_POINT,
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
        "output_contract": "ReviewReport.yaml 等价 JSON，必须包含 summary.release_readiness、coverage、method_coverage、dimension_matrix、evidence_trace、execution_proof、findings",
    }

    def validate(result: dict) -> None:
        summary = result.get("summary") or {}
        _gate(summary.get("release_readiness") in {"pass", "conditional_pass", "fail"}, "ReviewReport 缺少合法 summary.release_readiness")
        for key in ("coverage", "method_coverage", "dimension_matrix", "evidence_trace", "execution_proof", "findings"):
            _gate(key in result, f"ReviewReport 缺少 {key}")
        if result.get("coverage", {}).get("uncovered_fp_ids"):
            _gate(summary.get("release_readiness") != "pass", "存在未覆盖功能点时审查结论不能为 pass")

    ai_review = asyncio.run(_call_skill_with_gate_async(
        api_key=api_key,
        model=model,
        base_url=base_url,
        skill_name="quality-reviewer",
        task_payload=prompt,
        output_contract=(
            '{"summary": {"release_readiness": "pass|conditional_pass|fail"}, "coverage": {}, "method_coverage": {}, "dimension_matrix": {}, "evidence_trace": {}, "execution_proof": {}, "findings": [], "repair_tasks": []}'
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


def _extract_repair_tasks(review_report: dict, function_points: dict) -> list[dict]:
    fp_by_id = {item.get("fp_id"): item for item in function_points.get("function_points", []) if isinstance(item, dict)}
    tasks: list[dict] = []
    for item in review_report.get("repair_tasks") or []:
        if not isinstance(item, dict):
            continue
        fp_ids = [fp_id for fp_id in item.get("fp_ids", []) if fp_id in fp_by_id]
        if fp_ids:
            tasks.append(
                {
                    "reason": item.get("reason") or item.get("finding") or "quality-reviewer 要求补齐",
                    "fp_ids": fp_ids,
                    "focus": item.get("focus") or item.get("suggestion") or "补充缺失或薄弱场景",
                }
            )
    coverage_missing = (review_report.get("coverage") or {}).get("uncovered_fp_ids") or []
    missing = [fp_id for fp_id in coverage_missing if fp_id in fp_by_id]
    if missing and not any(set(missing).issubset(set(task["fp_ids"])) for task in tasks):
        tasks.append({"reason": "coverage.uncovered_fp_ids", "fp_ids": missing, "focus": "每个未覆盖功能点至少补充一条主流程用例"})
    return tasks


def _repair_testcase_package_with_review(
    *,
    testcase_package: dict,
    review_report: dict,
    function_points: dict,
    pending_confirmations: list,
    api_key: str,
    model: str,
    base_url: str | None = None,
    audit_log: list[dict] | None = None,
    progress_callback=None,
) -> dict:
    repair_tasks = _extract_repair_tasks(review_report, function_points)
    if not repair_tasks:
        return testcase_package

    fp_by_id = {item.get("fp_id"): item for item in function_points.get("function_points", []) if isinstance(item, dict)}
    repaired_cases = list(testcase_package.get("testcases") or [])

    for task_index, repair_task in enumerate(repair_tasks, start=1):
        if progress_callback:
            progress_callback(f"正在按质量审查建议补齐用例（第 {task_index}/{len(repair_tasks)} 项）")
        repair_fps = [fp_by_id[fp_id] for fp_id in repair_task["fp_ids"] if fp_id in fp_by_id]
        if not repair_fps:
            continue
        repair_package = _build_testcase_package(
            {"function_points": repair_fps},
            pending_confirmations + [{"source": "quality-reviewer", **repair_task}],
            api_key,
            model,
            base_url,
            audit_log,
            progress_callback=progress_callback,
        )
        repaired_cases.extend(repair_package.get("testcases") or [])

    seen: set[tuple[str, str]] = set()
    unique_cases: list[dict] = []
    for case in repaired_cases:
        key = (case.get("fp_id") or "", re.sub(r"\s+", "", str(case.get("title") or "")))
        if key in seen:
            continue
        seen.add(key)
        unique_cases.append(case)
    return {"testcases": unique_cases}


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


def _build_xmindmark(
    job: CaseGenerationJob,
    function_points: dict,
    testcase_package: dict,
    review_report: dict,
) -> str:
    root = f"{_sanitize_file_stem(job.source_document_name or job.name)}测试用例"
    lines = [root]
    cases = [case for case in testcase_package.get("testcases", []) if isinstance(case, dict)]
    _assign_requirement_groups(function_points)
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
    quality_summary = review_report.get("quality_summary") or {}
    if quality_summary:
        _append_node(lines, 1, f"证据覆盖率：{quality_summary.get('evidence_coverage_rate', 0):.0%}")
        _append_node(lines, 1, f"弱预期数量：{quality_summary.get('weak_expected_count', 0)}")

    fp_by_id = {item.get("fp_id"): item for item in function_points.get("function_points", [])}
    cases_by_fp: dict[str, list[dict]] = {}
    for case in cases:
        cases_by_fp.setdefault(case.get("fp_id") or "UNMAPPED", []).append(case)

    groups: dict[tuple[str, str], list[dict]] = {}
    for fp in sorted(function_points.get("function_points", []), key=lambda item: item.get("source_order", 0)):
        group_key = (
            str(fp.get("requirement_group_id") or "REQ-00"),
            str(fp.get("requirement_group_title") or fp.get("module") or "需求分组"),
        )
        groups.setdefault(group_key, []).append(fp)

    for (_group_id, group_title), fps in groups.items():
        _append_node(lines, 0, group_title)
        modules: dict[str, list[dict]] = {}
        for fp in fps:
            modules.setdefault(fp.get("module") or "默认模块", []).append(fp)
        for module, module_fps in modules.items():
            _append_node(lines, 1, f"模块：{module}")
            for fp in module_fps:
                fp_id = fp.get("fp_id") or "FP-000"
                scene = fp.get("scene") or module
                fp_title = fp.get("title") or fp.get("name") or fp.get("description") or "功能点"
                _append_node(lines, 2, f"{fp_id}：{scene} / {fp_title}")
                if fp.get("description"):
                    _append_node(lines, 3, f"说明：{_short_text(fp.get('description'), 120)}")
                rules = fp.get("rules") or []
                if rules:
                    _append_node(lines, 3, f"规则摘要：{_short_text('；'.join(str(item) for item in rules[:3]), 160)}")
                for case in cases_by_fp.get(fp_id, []):
                    case_id = case.get("case_id") or "TC-000"
                    category = _normalize_category(case.get("category"))
                    title = _short_text(case.get("title") or "测试用例", 90)
                    _append_node(lines, 3, f"{case_id}｜{case.get('priority') or 'P1'}｜{_category_label(category)}｜{title}")
                    steps = case.get("steps") or []
                    if not isinstance(steps, list):
                        steps = [str(steps)]
                    if steps:
                        _append_node(lines, 4, "操作步骤")
                        for step_index, step in enumerate(steps[:3], start=1):
                            _append_node(lines, 5, f"{step_index}. {_short_text(_step_to_text(step), 120)}")
                    expected = case.get("expected_results") or []
                    expected_items = expected if isinstance(expected, list) else [expected]
                    if expected_items:
                        _append_node(lines, 4, f"预期：{_short_text('；'.join(str(item) for item in expected_items[:2]), 160)}")
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
            _append_node(lines, 4, f"优先级：{case.get('priority') or 'P1'}｜类型：{case.get('category') or '功能'}")

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
        for repair_round in range(1, _TESTCASE_REPAIR_MAX_ROUNDS + 1):
            repair_tasks = _extract_repair_tasks(review_report, function_points)
            readiness = (review_report.get("summary") or {}).get("release_readiness")
            if readiness != "fail" and not repair_tasks:
                break
            if not repair_tasks:
                _gate(readiness != "fail", "quality-reviewer 审查结论为 fail，且未返回可执行修复任务")
                break
            _update_stage(
                job,
                db,
                "repair",
                "用例补齐",
                "running",
                f"第 {repair_round}/{_TESTCASE_REPAIR_MAX_ROUNDS} 轮质量修复，待处理 {len(repair_tasks)} 项",
            )

            def update_repair_progress(summary: str, current_round: int = repair_round) -> None:
                _update_stage(job, db, "repair", "用例补齐", "running", f"第 {current_round} 轮质量修复：{summary}")
                _raise_if_job_cancelled(db, job.id)

            testcase_package = _repair_testcase_package_with_review(
                testcase_package=testcase_package,
                review_report=review_report,
                function_points=function_points,
                pending_confirmations=pending_confirmations,
                api_key=api_key,
                model=model,
                base_url=base_url,
                audit_log=audit_log,
                progress_callback=update_repair_progress,
            )
            _raise_if_job_cancelled(db, job.id)
            _persist_stage_artifact(output_dir, "testcase_package.json", testcase_package)
            _update_stage(job, db, "repair", "用例补齐", "success", f"第 {repair_round} 轮修复后共 {len(testcase_package.get('testcases', []))} 条用例")
            _update_stage(job, db, "review", "质量复审", "running", f"正在进行第 {repair_round} 轮质量复审")
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
        final_readiness = (review_report.get("summary") or {}).get("release_readiness")
        _gate(final_readiness != "fail", "quality-reviewer 复审结论为 fail，禁止导出 XMind")
        if _extract_repair_tasks(review_report, function_points):
            _update_stage(job, db, "review", "质量复审", "success", "复审通过，仍保留后续优化建议")
        else:
            _update_stage(job, db, "review", "质量复审", "success", "复审通过")
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
        job.input_payload_json = sanitize_case_generation_payload(payload, cleanup_secret=True)
        job.status = "SUCCESS"
        job.task_id = None
        job.summary = f"已生成 {review_report['case_count']} 条用例，并导出 XMind"
        job.error_message = None
        job.finished_at = utc_now_naive()
        db.commit()
        db.refresh(job)
        _cleanup_previous_success_xmind_for_project(db, job)
        _cleanup_expired_success_xmind(db, retention_days=3)
        db.commit()
        keep_paths = _collect_final_artifact_paths(db, job.id)
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
