"""Implementation functions owned by this V2 pipeline stage."""

from __future__ import annotations

from app.tasks.case_generation_v2_pipeline import engine as _engine

Counter = getattr(_engine, 'Counter')
ModelContractError = getattr(_engine, 'ModelContractError')
_LONG_CHAT_TIMEOUT_SECONDS = getattr(_engine, '_LONG_CHAT_TIMEOUT_SECONDS')
_NAVIGATION_SELECTION_PATTERN = getattr(_engine, '_NAVIGATION_SELECTION_PATTERN')
_TEST_DATA_REQUIRED_METHODS = getattr(_engine, '_TEST_DATA_REQUIRED_METHODS')
_TRUSTED_GENERATION_CONTRACT_VERSION = getattr(_engine, '_TRUSTED_GENERATION_CONTRACT_VERSION')
_TRUSTED_SHARD_CONCURRENCY = getattr(_engine, '_TRUSTED_SHARD_CONCURRENCY')
_TRUSTED_SHARD_MAX_ATTEMPTS = getattr(_engine, '_TRUSTED_SHARD_MAX_ATTEMPTS')
_TRUSTED_TESTCASE_RESULTS = getattr(_engine, '_TRUSTED_TESTCASE_RESULTS')
_call_trusted_skill_json_async = getattr(_engine, '_call_trusted_skill_json_async')
_coerce_test_data = getattr(_engine, '_coerce_test_data')
_compact_case_text = getattr(_engine, '_compact_case_text')
_current_state_basis_is_allowed = getattr(_engine, '_current_state_basis_is_allowed')
_current_state_expectation_is_allowed = getattr(_engine, '_current_state_expectation_is_allowed')
_default_test_design_profile = getattr(_engine, '_default_test_design_profile')
_format_duration_zh = getattr(_engine, '_format_duration_zh')
_gather_limited = getattr(_engine, '_gather_limited')
_is_state_label_only = getattr(_engine, '_is_state_label_only')
_normalize_requirement_quote = getattr(_engine, '_normalize_requirement_quote')
_normalize_test_design_profile = getattr(_engine, '_normalize_test_design_profile')
_source_evidence_role = getattr(_engine, '_source_evidence_role')
_state_target_conflicts = getattr(_engine, '_state_target_conflicts')
_step_to_text = getattr(_engine, '_step_to_text')
_text_contains_any = getattr(_engine, '_text_contains_any')
_trusted_scope_source_items = getattr(_engine, '_trusted_scope_source_items')
_trusted_source_by_id = getattr(_engine, '_trusted_source_by_id')
_unified_rules_sha256 = getattr(_engine, '_unified_rules_sha256')
asyncio = getattr(_engine, 'asyncio')
build_shard_cache_metadata = getattr(_engine, 'build_shard_cache_metadata')
current_generation_density = getattr(_engine, 'current_generation_density')
defaultdict = getattr(_engine, 'defaultdict')
generation_density_profile = getattr(_engine, 'generation_density_profile')
logger = getattr(_engine, 'logger')
re = getattr(_engine, 're')
run_async = getattr(_engine, 'run_async')
shard_cache_mismatch = getattr(_engine, 'shard_cache_mismatch')
time = getattr(_engine, 'time')


def _trusted_gate_recovery_plan(*args, **kwargs):
    return getattr(_engine, "_trusted_gate_recovery_plan")(*args, **kwargs)


def _trusted_method_for_case(*args, **kwargs):
    return getattr(_engine, "_trusted_method_for_case")(*args, **kwargs)


def _compact_evidence_match_text(value: object) -> str:
    normalized = _normalize_requirement_quote(str(value or "")).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)


def _evidence_bigram_coverage(claim: object, evidence: object) -> float:
    claim_text = _compact_evidence_match_text(claim)
    evidence_text = _compact_evidence_match_text(evidence)
    if not claim_text or not evidence_text:
        return 0.0
    if claim_text in evidence_text:
        return 1.0
    if len(evidence_text) >= 6 and evidence_text in claim_text:
        return 1.0
    if len(claim_text) < 4:
        return 0.0
    claim_pairs = {claim_text[index:index + 2] for index in range(len(claim_text) - 1)}
    evidence_pairs = {evidence_text[index:index + 2] for index in range(len(evidence_text) - 1)}
    return len(claim_pairs & evidence_pairs) / max(len(claim_pairs), 1)


def _target_image_ref_for_text_basis(source: dict, basis: dict) -> str:
    """Recover an image-derived claim that the model mislabeled as text.

    The conversion remains deterministic: only target images bound to this
    source are eligible, and the claimed fact must be explicitly traceable to
    the image summary or one of its requirement hints.
    """
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    target_refs = [
        str(value).strip()
        for value in semantics.get("target_image_refs") or []
        if str(value).strip()
    ]
    if not target_refs:
        return ""

    basis_ref = str(basis.get("basis_ref") or "").strip()
    if basis_ref in target_refs:
        return basis_ref

    claims = [
        str(basis.get("source_quote") or "").strip(),
        str(basis.get("expected_result") or "").strip(),
    ]
    explicit_refs = {
        match.upper()
        for claim in claims
        for match in re.findall(r"IMG-\d+", claim, flags=re.IGNORECASE)
    }
    for target_ref in target_refs:
        if target_ref.upper() in explicit_refs:
            return target_ref

    evidence_by_ref = {
        str(item.get("image_id") or "").strip(): item
        for item in source.get("image_evidence") or []
        if isinstance(item, dict) and str(item.get("image_id") or "").strip()
    }
    for target_ref in target_refs:
        evidence = evidence_by_ref.get(target_ref) or {}
        evidence_texts = [
            str(evidence.get("summary") or "").strip(),
            *[str(value or "").strip() for value in evidence.get("requirement_hints") or []],
        ]
        if any(
            _evidence_bigram_coverage(claim, evidence_text) >= 0.65
            for claim in claims
            if claim
            for evidence_text in evidence_texts
            if evidence_text
        ):
            return target_ref
    return ""


def _repair_image_derived_assertion_basis(source: dict, basis: dict) -> None:
    if str(basis.get("basis_type") or "").strip() != "text":
        return
    source_quote = _normalize_requirement_quote(basis.get("source_quote") or "")
    source_excerpt = _normalize_requirement_quote(source.get("source_excerpt") or "")
    if source_quote and source_quote in source_excerpt:
        return
    target_image_ref = _target_image_ref_for_text_basis(source, basis)
    if not target_image_ref:
        return
    basis["basis_type"] = "image"
    basis["basis_ref"] = target_image_ref
    basis["basis_correction"] = "text_to_target_image"


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
                    _repair_image_derived_assertion_basis(source, basis)
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
    return run_async(_build_trusted_testcase_source_shard_async(source, function_points, api_key=api_key, model=model, base_url=base_url))


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
        scenario_text = _compact_case_text([
            case.get("title"),
            case.get("preconditions"),
            case.get("steps"),
            case.get("scenario_dimensions"),
        ])
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
                    target_refs = ", ".join(
                        str(value).strip()
                        for value in (source.get("source_state_semantics") or {}).get("target_image_refs") or []
                        if str(value).strip()
                    )
                    detail = f"：{str(basis.get('source_quote') or '').strip()[:80]}"
                    if target_refs:
                        detail += f"；若依据来自目标图，应使用 image/{target_refs}"
                    raise ModelContractError(f"{source_id} 分片用例 {case_id or '未命名'} 的文本依据不在需求原文中{detail}")
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
                scenario_text,
            ):
                raise ModelContractError(
                    f"{source_id} 分片用例 {case_id or '未命名'} 把 current 旧状态写成正向预期：{expected_result}"
                )
            state_conflicts = _state_target_conflicts(source, expected_result)
            if state_conflicts and not _current_state_expectation_is_allowed(
                source,
                expected_result,
                str(basis.get("source_quote") or "").strip(),
                scenario_text,
            ):
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
    density = generation_density_profile()
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
                        {"expected_result": "与 expected_results 中一项逐字一致", "basis_type": "text|image", "basis_ref": "DOC-001|IMG-001", "source_quote": "text 时逐字复制 source_excerpt；image 时描述图片中可核验的视觉事实", "evidence_role": "由后端写入 current|target|unspecified"}
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
            f"当前生成密度为 {density['label']}（{density['key']}）：{density['guidance']}",
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
            "若预期事实来自 image_evidence.summary 或 requirement_hints，即使该事实以文字描述，也必须使用 basis_type=image 和对应 image_id；不得标记为 text",
            "禁止根据‘优化、提升、合理、正常’等目标性措辞自行发明位置、边框、颜色、文案或交互；依据不明确时不要写成确定预期",
            "source_state_semantics.has_state_transition=true 时，expected_results 必须描述 target；current_text/current_image_refs 只能用于前置条件或‘不再出现/改为’等负向回归断言，禁止把 current 旧状态写成正向预期",
            "目标效果仅在图片中时，assertion_basis.basis_type=image 且 basis_ref 必须引用 target_image_refs；不得用 current 文本为目标位置或样式背书",
            "需求中出现精确文案、字段顺序、尺寸、状态组合、错误提示时，expected_results 和 test_data 必须保留这些精确值，不得改写为‘内容正确’或‘符合表格’",
            "只为需求明确规定的等价类和边界值写确定性预期；不得把未定义的相邻值自行推导为通过、失败或无警告，存在歧义时不要生成该推导用例",
            "涉及业务输入、业务值选择、搜索、筛选、上传、保存、导出或等价类/边界值/决策表/状态转换时，test_data 必须给出可直接执行的具体值；仅进入 Tab/页面后检查字段展示、改名或隐藏时允许为空",
            "当前 source 至少选择一条核心用例标记 baseline_candidate=true",
            "case_id 可先使用当前 shard 内唯一编号，后端会统一重排",
        ],
        "source": source,
        "generation_density": density,
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
        _validate_trusted_source_shard_contract(source, function_points, normalized)
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
    return run_async(_build_trusted_testcase_handoff_async(
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
    progress_state = {
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "reused": 0,
        "cache_invalidated": 0,
    }
    progress_lock = asyncio.Lock()
    reusable_shards = _trusted_reusable_source_shards(existing_testcase_handoff)
    rules_sha256 = _unified_rules_sha256()
    density = current_generation_density()

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
        expected_cache_metadata = build_shard_cache_metadata(
            source,
            source_fps,
            rules_sha256=rules_sha256,
            model=model,
            generation_contract_version=_TRUSTED_GENERATION_CONTRACT_VERSION,
            generation_density=density,
        )
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
            mismatch_keys = shard_cache_mismatch(cached_shard, expected_cache_metadata)
            if mismatch_keys:
                async with progress_lock:
                    progress_state["cache_invalidated"] += 1
                logger.info(
                    "cached source shard %s fingerprint mismatch (%s); regenerating",
                    source_id,
                    ", ".join(mismatch_keys),
                )
                cached_shard = None
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
                cached_shard["cache_metadata"] = expected_cache_metadata
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
            shard["cache_metadata"] = expected_cache_metadata
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
        "cache_invalidated_count": progress_state["cache_invalidated"],
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
            scenario_text = _compact_case_text([
                case.get("title"),
                case.get("preconditions"),
                case.get("steps"),
                case.get("scenario_dimensions"),
            ])
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
                    scenario_text,
                ):
                    issues.append({
                        "severity": "blocker",
                        "code": "CASE_CURRENT_STATE_AS_EXPECTED",
                        "source_id": source_id,
                        "case_id": case_id,
                        "message": f"{case_id} 把 current 旧状态写成正向预期：{expected_result}",
                    })
                state_conflicts = _state_target_conflicts(source, expected_result)
                if state_conflicts and not _current_state_expectation_is_allowed(
                    source,
                    expected_result,
                    str(basis.get("source_quote") or "").strip(),
                    scenario_text,
                ):
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
        if source_id in failed_source_ids:
            continue
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
