from __future__ import annotations

from collections.abc import Callable


def combine_trusted_gate(
    deterministic_gate: dict,
    model_gate: dict | None,
    *,
    normalize_issues: Callable[[str, list[dict]], list[dict]],
    recovery_plan: Callable[[str, list[dict]], dict],
) -> dict:
    combined = dict(deterministic_gate or {})
    deterministic_issues = [item for item in (deterministic_gate or {}).get("issues") or [] if isinstance(item, dict)]
    model_issues: list[dict] = []
    if model_gate:
        for item in model_gate.get("blocking_issues") or []:
            if not isinstance(item, dict):
                continue
            model_issues.append(
                {
                    "severity": "blocker",
                    "model_severity": item.get("severity") or "blocker",
                    "code": "MODEL_HANDOFF_REVIEW_BLOCKER",
                    "message": str(item.get("message") or item.get("note") or item).strip(),
                    "source_id": item.get("source_id"),
                    "fp_id": item.get("fp_id"),
                }
            )
    deterministic_passed = bool((deterministic_gate or {}).get("passed"))
    model_passed = True if model_gate is None else bool(model_gate.get("passed"))
    gate_name = str(combined.get("gate") or "")
    combined["issues"] = normalize_issues(gate_name, deterministic_issues + model_issues)
    combined["blocking_issues"] = [item for item in combined["issues"] if item.get("severity") == "blocker"]
    combined["warning_issues"] = [item for item in combined["issues"] if item.get("severity") == "warning"]
    combined["passed"] = deterministic_passed and model_passed and not combined["blocking_issues"]
    combined["status"] = "pass" if combined["passed"] and not combined["warning_issues"] else ("warning" if combined["passed"] else "fail")
    combined["issue_counts"] = {
        "blocker": len(combined["blocking_issues"]),
        "warning": len(combined["warning_issues"]),
        "total": len(combined["issues"]),
    }
    combined["recovery_plan"] = recovery_plan(gate_name, combined["issues"])
    combined["deterministic_passed"] = deterministic_passed
    combined["model_passed"] = model_passed
    combined["model_gate_applied"] = model_gate is not None
    if model_gate:
        combined["model_decision"] = model_gate.get("decision")
        combined["model_return_to"] = model_gate.get("return_to")
        combined["model_return_reason"] = model_gate.get("return_reason")
        combined["model_checked_item_count"] = len(model_gate.get("checked_items") or [])
    return combined
