"""Implementation functions owned by this V2 pipeline stage."""

from __future__ import annotations

from app.tasks.case_generation_v2_pipeline import engine as _engine

CaseGenerationV2Job = getattr(_engine, 'CaseGenerationV2Job')
Counter = getattr(_engine, 'Counter')
DeliveryStageInput = getattr(_engine, 'DeliveryStageInput')
_LONG_CHAT_TIMEOUT_SECONDS = getattr(_engine, '_LONG_CHAT_TIMEOUT_SECONDS')
_TRUSTED_ADVISORY_ISSUE_CODES = getattr(_engine, '_TRUSTED_ADVISORY_ISSUE_CODES')
_TRUSTED_HANDOFF_GATE_CONTRACT = getattr(_engine, '_TRUSTED_HANDOFF_GATE_CONTRACT')
_TRUSTED_MODEL_GATE_ENABLED = getattr(_engine, '_TRUSTED_MODEL_GATE_ENABLED')
_artifact_json_payload = getattr(_engine, '_artifact_json_payload')
_build_case_generation_quality_summary = getattr(_engine, '_build_case_generation_quality_summary')
_build_xmindmark = getattr(_engine, '_build_xmindmark')
_call_skill_with_gate = getattr(_engine, '_call_skill_with_gate')
_call_skill_with_gate_async = getattr(_engine, '_call_skill_with_gate_async')
_compact_case_text = getattr(_engine, '_compact_case_text')
_convert_xmindmark = getattr(_engine, '_convert_xmindmark')
_count_xmindmark_function_point_nodes = getattr(_engine, '_count_xmindmark_function_point_nodes')
_count_xmindmark_source_nodes = getattr(_engine, '_count_xmindmark_source_nodes')
_count_xmindmark_testcase_nodes = getattr(_engine, '_count_xmindmark_testcase_nodes')
_current_state_expectation_is_allowed = getattr(_engine, '_current_state_expectation_is_allowed')
_gate = getattr(_engine, '_gate')
_normalize_category = getattr(_engine, '_normalize_category')
_persist_trusted_artifact = getattr(_engine, '_persist_trusted_artifact')
_resolve_unified_rules_dir = getattr(_engine, '_resolve_unified_rules_dir')
_sanitize_file_stem = getattr(_engine, '_sanitize_file_stem')
_source_evidence_role = getattr(_engine, '_source_evidence_role')
_text_contains_any = getattr(_engine, '_text_contains_any')
_trusted_artifact_content = getattr(_engine, '_trusted_artifact_content')
_trusted_artifact_record = getattr(_engine, '_trusted_artifact_record')
_trusted_artifact_text = getattr(_engine, '_trusted_artifact_text')
_trusted_scope_source_items = getattr(_engine, '_trusted_scope_source_items')
_trusted_source_by_id = getattr(_engine, '_trusted_source_by_id')
_trusted_source_order_key = getattr(_engine, '_trusted_source_order_key')
_trusted_v2_source_ids = getattr(_engine, '_trusted_v2_source_ids')
_trusted_xmind_grouping_contract = getattr(_engine, '_trusted_xmind_grouping_contract')
_upsert_artifact = getattr(_engine, '_upsert_artifact')
_validate_trusted_requirement_handoff = getattr(_engine, '_validate_trusted_requirement_handoff')
_validate_trusted_scope_index = getattr(_engine, '_validate_trusted_scope_index')
_validate_trusted_testcase_handoff = getattr(_engine, '_validate_trusted_testcase_handoff')
_write_text_file = getattr(_engine, '_write_text_file')
_write_yaml_file = getattr(_engine, '_write_yaml_file')
combine_trusted_gate = getattr(_engine, 'combine_trusted_gate')
inspect = getattr(_engine, 'inspect')
inspect_xmind_archive = getattr(_engine, 'inspect_xmind_archive')
json = getattr(_engine, 'json')
os = getattr(_engine, 'os')
re = getattr(_engine, 're')
run_async = getattr(_engine, 'run_async')
run_delivery_stage = getattr(_engine, 'run_delivery_stage')
settings = getattr(_engine, 'settings')
subprocess = getattr(_engine, 'subprocess')
utc_now_naive = getattr(_engine, 'utc_now_naive')

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
    return combine_trusted_gate(
        deterministic_gate,
        model_gate,
        normalize_issues=_normalize_trusted_gate_issues,
        recovery_plan=_trusted_gate_recovery_plan,
    )


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


def _case_scenario_text(case: dict | None) -> str:
    """Build the scenario text used to judge current-state allowances.

    Mirrors the generation-stage contract (see testcase_impl) so the delivery
    detector recognises the same partial-selection signals (e.g. 非全选状态)
    carried in title/preconditions/steps/scenario_dimensions instead of only
    the expected_result text.
    """
    case = case or {}
    return _compact_case_text([
        case.get("title"),
        case.get("preconditions"),
        case.get("steps"),
        case.get("scenario_dimensions"),
    ])


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
            "若精确文案、字段顺序、数值或矩阵已完整出现在 test_data、expected_results 和 assertion_basis 中，不得仅因 steps 通过数据名称引用、未再次逐项复制而判定 exact_value_loss。",
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

    review = run_async(
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
        scenario_text = _case_scenario_text(case)
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
                scenario_text,
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
        scenario_text = _case_scenario_text(case)
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
                scenario_text,
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


def _run_trusted_delivery_stage(
    db,
    job: CaseGenerationV2Job,
    output_dir: str,
    scope_index: dict,
    requirement_handoff: dict,
    testcase_handoff: dict,
    *,
    api_key: str,
    model: str,
    base_url: str,
    image_links: list[str] | None = None,
    downloaded_images: list[dict] | None = None,
    image_analysis: list[dict] | None = None,
):
    stage_input = DeliveryStageInput(
        scope_index=scope_index,
        requirement_handoff=requirement_handoff,
        testcase_handoff=testcase_handoff,
        api_key=api_key,
        model=model,
        base_url=base_url,
        image_links=image_links,
        downloaded_images=downloaded_images,
        image_analysis=image_analysis,
    )

    def rebuild_delivery(stage_scope, stage_requirement, stage_testcases, **kwargs):
        return _rebuild_trusted_delivery_artifacts(
            db,
            job,
            output_dir,
            stage_scope,
            stage_requirement,
            stage_testcases,
            **kwargs,
        )

    return run_delivery_stage(stage_input, rebuild_delivery=rebuild_delivery)
