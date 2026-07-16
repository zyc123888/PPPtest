from __future__ import annotations

import contextvars
from copy import deepcopy


GENERATION_DENSITIES = ("concise", "balanced", "exhaustive")

_DENSITY = contextvars.ContextVar("case_generation_v2_density", default="balanced")

_PROFILES = {
    "concise": {
        "label": "精简",
        "guidance": "优先核心主流程和高风险 must_cover；低风险同构字段允许参数化合并，但不得遗漏 source、功能点或适用方法的消费回执。",
        "merge_policy": "aggressive_with_traceability",
        "coverage_depth": "core_and_high_risk",
    },
    "balanced": {
        "label": "均衡",
        "guidance": "覆盖 must_cover、核心边界、关键异常和适用测试方法；仅合并低风险且语义同构的场景，不以固定条数为目标。",
        "merge_policy": "risk_based",
        "coverage_depth": "core_boundary_negative",
    },
    "exhaustive": {
        "label": "全面",
        "guidance": "展开 must_cover、适用测试方法、边界、异常、权限、状态迁移和关键组合；除语义、步骤、预期与风险完全一致外不得合并。",
        "merge_policy": "exact_duplicates_only",
        "coverage_depth": "full_risk_and_method_matrix",
    },
}


def normalize_generation_density(value: str | None) -> str:
    normalized = str(value or "balanced").strip().lower()
    if normalized not in GENERATION_DENSITIES:
        raise ValueError(f"不支持的生成密度：{value}")
    return normalized


def set_generation_density(value: str | None):
    return _DENSITY.set(normalize_generation_density(value))


def reset_generation_density(token) -> None:
    _DENSITY.reset(token)


def current_generation_density() -> str:
    return _DENSITY.get()


def generation_density_profile(value: str | None = None) -> dict:
    density = normalize_generation_density(value or current_generation_density())
    return {"key": density, **deepcopy(_PROFILES[density])}


def apply_generation_density(profile: dict) -> dict:
    result = deepcopy(profile or {})
    density = generation_density_profile()
    budget = result.get("coverage_budget") if isinstance(result.get("coverage_budget"), dict) else {}
    budget["guidance"] = density["guidance"]
    budget["density"] = density["key"]
    budget["coverage_depth"] = density["coverage_depth"]
    budget["merge_policy"] = density["merge_policy"]
    result["coverage_budget"] = budget
    result["generation_density"] = density["key"]
    if density["key"] == "exhaustive":
        result["merge_allowed"] = ["仅允许语义、步骤、预期与风险完全一致的重复用例"]
    elif density["key"] == "concise" and not result.get("merge_allowed"):
        result["merge_allowed"] = ["低风险同构字段可参数化合并，但必须保留消费回执"]
    return result
