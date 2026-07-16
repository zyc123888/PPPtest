from __future__ import annotations

import json


PIPELINE_MODE_ALIASES = {
    "clone": "lite",
    "trusted_v2": "trusted",
    "lite": "lite",
    "trusted": "trusted",
}
SUPPORTED_PIPELINE_MODES = frozenset({"lite", "trusted"})


def normalize_pipeline_mode(mode: str | None) -> str:
    raw_mode = str(mode or "lite").strip() or "lite"
    normalized = PIPELINE_MODE_ALIASES.get(raw_mode, raw_mode)
    if normalized not in SUPPORTED_PIPELINE_MODES:
        raise ValueError(f"不支持的 V2 生成模式：{raw_mode}")
    return normalized


def is_trusted_pipeline_mode(mode: str | None) -> bool:
    return normalize_pipeline_mode(mode) == "trusted"


def coerce_test_data(value) -> list[dict]:
    if not value:
        return []
    items: list[dict] = []
    for entry in value if isinstance(value, list) else [value]:
        if isinstance(entry, dict):
            name = str(entry.get("name") or entry.get("field") or "数据").strip()
            raw_value = entry.get("value")
            normalized_value = "" if raw_value is None else (
                raw_value if isinstance(raw_value, str) else json.dumps(raw_value, ensure_ascii=False)
            )
            items.append({"name": name or "数据", "value": normalized_value})
            continue
        text = str(entry)
        separator = "：" if "：" in text else (":" if ":" in text else "")
        if separator:
            name, _, normalized_value = text.partition(separator)
            items.append({"name": name.strip() or "数据", "value": normalized_value.strip()})
        else:
            items.append({"name": "数据", "value": text})
    return items


def coerce_source_refs(value) -> list[dict]:
    if not value:
        return []
    items: list[dict] = []
    for entry in value if isinstance(value, list) else [value]:
        if isinstance(entry, dict):
            serialized = json.dumps(entry, ensure_ascii=False)
            items.append(
                {
                    "source_type": str(entry.get("source_type") or ("image" if "IMG-" in serialized else "text")),
                    "doc": str(entry.get("doc") or ""),
                    "section": str(entry.get("section") or ""),
                    "quote": str(entry.get("quote") or entry.get("text") or ""),
                }
            )
            continue
        text = str(entry)
        is_image = "IMG-" in text
        items.append(
            {
                "source_type": "image" if is_image else "text",
                "doc": text if is_image else "",
                "section": "",
                "quote": "" if is_image else text,
            }
        )
    return items


def coerce_atomicity_check(value) -> dict:
    if isinstance(value, dict):
        passed = value.get("passed")
        issues = value.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        return {"passed": True if passed is None else bool(passed), "issues": [str(item) for item in issues]}
    return {"passed": True, "issues": []}


def coerce_review_flags(value) -> dict:
    allowed = {"low", "medium", "high"}
    result = {"executable_risk": "low", "ambiguity_risk": "low"}
    if isinstance(value, dict):
        for key in result:
            candidate = str(value.get(key) or "").strip().lower()
            if candidate in allowed:
                result[key] = candidate
    return result


def sources_from_refs(source_refs) -> list[str]:
    result: list[str] = []
    for ref in source_refs or []:
        if isinstance(ref, dict):
            source_type = ref.get("source_type")
        elif ref:
            source_type = "image" if "IMG-" in str(ref) else "text"
        else:
            source_type = None
        if source_type and source_type not in result:
            result.append(source_type)
    return result or ["text"]
