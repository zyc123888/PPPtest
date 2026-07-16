from __future__ import annotations

from collections import Counter
from typing import Any


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _artifact_map(artifacts: list[Any]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for artifact in sorted(artifacts, key=lambda item: int(getattr(item, "id", 0) or 0)):
        artifact_type = str(getattr(artifact, "artifact_type", "") or "")
        content = getattr(artifact, "content_json", None)
        if artifact_type and isinstance(content, dict):
            result[artifact_type] = content
    return result


def _unwrap(payload: dict, *keys: str) -> dict:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def _first_int(*values: Any) -> int:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _gate_counts(artifact_payloads: dict[str, dict]) -> dict:
    counts = Counter()
    gate_statuses: dict[str, str] = {}
    for artifact_type, raw in artifact_payloads.items():
        if "gate" not in artifact_type:
            continue
        gate = _unwrap(raw, artifact_type, artifact_type.removesuffix("_report"), "gate_report")
        issue_counts = _as_dict(gate.get("issue_counts"))
        issues = _as_list(gate.get("issues"))
        blockers = _first_int(issue_counts.get("blocker"), len(_as_list(gate.get("blocking_issues"))))
        warnings = _first_int(issue_counts.get("warning"), len(_as_list(gate.get("warning_issues"))))
        if not blockers and not warnings and issues:
            blockers = len([item for item in issues if isinstance(item, dict) and item.get("severity") == "blocker"])
            warnings = len([item for item in issues if isinstance(item, dict) and item.get("severity") == "warning"])
        counts["blocker"] += blockers
        counts["warning"] += warnings
        counts["total"] += _first_int(issue_counts.get("total"), len(issues), blockers + warnings)
        gate_statuses[artifact_type] = str(
            gate.get("status")
            or ("pass" if gate.get("passed") is True else "fail" if gate.get("passed") is False else "unknown")
        )
    return {"counts": dict(counts), "statuses": gate_statuses}


def build_generation_metrics(
    *,
    job: Any,
    attempt: Any,
    artifacts: list[Any],
    model_calls: list[dict],
    pipeline_version: str,
    status: str,
) -> dict:
    artifact_payloads = _artifact_map(artifacts)
    input_payload = _as_dict(getattr(job, "input_payload_json", None))
    function_points_raw = artifact_payloads.get("function_points") or artifact_payloads.get("requirement_handoff") or {}
    function_points = _unwrap(function_points_raw, "requirement_handoff", "function_points")
    fp_items = (
        _as_list(function_points.get("function_points"))
        if isinstance(function_points, dict)
        else []
    )
    testcase_raw = (
        artifact_payloads.get("testcase_package")
        or artifact_payloads.get("testcase_handoff")
        or artifact_payloads.get("testcase_base_package")
        or {}
    )
    testcase_package = _unwrap(testcase_raw, "testcase_handoff", "testcase_package")
    cases = _as_list(testcase_package.get("testcases"))
    review_raw = artifact_payloads.get("trusted_review_report") or artifact_payloads.get("review_report") or {}
    review = _unwrap(review_raw, "trusted_review_report", "review_report")
    review_summary = _as_dict(review.get("summary"))
    quality = _as_dict(review.get("execution_proof")) or _as_dict(artifact_payloads.get("execution_proof"))
    quality_summary = _as_dict(quality.get("summary")) or quality
    scope_raw = artifact_payloads.get("scope_index") or {}
    scope = _unwrap(scope_raw, "scope_index")
    source_items = (
        _as_list(scope.get("direct_testcase_sources"))
        or _as_list(scope.get("source_blocks"))
        or _as_list(scope.get("shards"))
    )
    source_summary = _as_list(testcase_package.get("source_case_summary"))
    pending = _as_list(review.get("pending_confirmations"))
    if not pending:
        pending = _as_list(function_points.get("pending_confirmations"))
    shard_progress = _as_dict(testcase_package.get("shard_progress_summary"))

    testcase_count = _first_int(len(cases), review_summary.get("testcase_count"), review.get("case_count"))
    function_point_count = _first_int(
        len(fp_items),
        review_summary.get("function_point_count"),
        review.get("function_point_count"),
    )
    source_count = _first_int(len(source_items), review_summary.get("source_count"), len(source_summary))
    covered_source_count = _first_int(
        review_summary.get("covered_source_count"),
        len([item for item in source_summary if isinstance(item, dict) and item.get("coverage_status") == "covered"]),
    )
    duplicate_count = _first_int(review_summary.get("duplicate_count"), review.get("duplicate_count"))
    weak_expected_count = _first_int(
        review_summary.get("weak_expected_count"),
        quality_summary.get("weak_expected_count"),
    )
    weak_step_count = _first_int(
        review_summary.get("weak_step_count"),
        quality_summary.get("weak_step_count"),
        review_summary.get("ambiguous_step_count"),
    )
    covered_fp_count = _first_int(
        review_summary.get("covered_function_point_count"),
        quality_summary.get("covered_function_point_count"),
        function_point_count - _first_int(review_summary.get("uncovered_fp_count")),
    )
    started_at = getattr(attempt, "started_at", None) or getattr(job, "started_at", None)
    finished_at = getattr(attempt, "finished_at", None) or getattr(job, "finished_at", None)
    duration_ms = None
    if started_at is not None and finished_at is not None:
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    usage = Counter()
    for call in model_calls:
        call_usage = _as_dict(call.get("usage"))
        usage["prompt_tokens"] += _first_int(call_usage.get("prompt_tokens"))
        usage["completion_tokens"] += _first_int(call_usage.get("completion_tokens"))
        usage["total_tokens"] += _first_int(call_usage.get("total_tokens"))
        usage["duration_ms"] += _first_int(call.get("duration_ms"))
        usage["errors"] += 0 if call.get("status") == "success" else 1

    gate = _gate_counts(artifact_payloads)
    return {
        "schema_version": "generation-metrics-v1",
        "pipeline_version": pipeline_version,
        "pipeline_mode": input_payload.get("pipeline_mode") or ("v1" if pipeline_version == "v1" else "lite"),
        "generation_density": input_payload.get("generation_density") or "balanced",
        "job_id": getattr(job, "id", None),
        "attempt_id": getattr(attempt, "id", None),
        "status": status,
        "duration_ms": duration_ms,
        "source_count": source_count,
        "covered_source_count": covered_source_count,
        "source_coverage_rate": _ratio(covered_source_count, source_count),
        "function_point_count": function_point_count,
        "covered_function_point_count": covered_fp_count,
        "function_point_coverage_rate": _ratio(covered_fp_count, function_point_count),
        "testcase_count": testcase_count,
        "duplicate_count": duplicate_count,
        "duplicate_rate": _ratio(duplicate_count, testcase_count),
        "weak_expected_count": weak_expected_count,
        "weak_expected_rate": _ratio(weak_expected_count, testcase_count),
        "weak_step_count": weak_step_count,
        "pending_confirmation_count": len(pending),
        "model_call_count": len(model_calls),
        "model_error_count": usage["errors"],
        "model_duration_ms": usage["duration_ms"],
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "shard_reused_count": _first_int(shard_progress.get("reused_count")),
        "shard_cache_invalidated_count": _first_int(shard_progress.get("cache_invalidated_count")),
        "gate_issue_counts": gate["counts"],
        "gate_statuses": gate["statuses"],
        "stage_durations_ms": {
            str(item.get("key") or item.get("label") or index): _first_int(item.get("duration_ms"))
            for index, item in enumerate(_as_list(getattr(attempt, "progress_json", None) and attempt.progress_json.get("stages")), start=1)
            if isinstance(item, dict)
        },
    }


def compare_generation_metrics(baseline: dict | None, candidate: dict | None) -> dict:
    numeric_keys = (
        "duration_ms",
        "testcase_count",
        "duplicate_count",
        "duplicate_rate",
        "weak_expected_count",
        "weak_expected_rate",
        "pending_confirmation_count",
        "model_call_count",
        "model_error_count",
        "total_tokens",
    )
    delta = None
    if baseline and candidate:
        delta = {}
        for key in numeric_keys:
            baseline_value = baseline.get(key)
            candidate_value = candidate.get(key)
            if isinstance(baseline_value, (int, float)) and isinstance(candidate_value, (int, float)):
                delta[key] = round(candidate_value - baseline_value, 4)
    return {"baseline": baseline, "candidate": candidate, "delta": delta}
