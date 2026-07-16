"""Implementation functions owned by this V2 pipeline stage."""

from __future__ import annotations

from app.tasks.case_generation_v2_pipeline import engine as _engine

ModelContractError = getattr(_engine, 'ModelContractError')
_DEFAULT_CHAT_TIMEOUT_SECONDS = getattr(_engine, '_DEFAULT_CHAT_TIMEOUT_SECONDS')
_LONG_CHAT_TIMEOUT_SECONDS = getattr(_engine, '_LONG_CHAT_TIMEOUT_SECONDS')
_REQUIREMENT_BATCH_CONCURRENCY = getattr(_engine, '_REQUIREMENT_BATCH_CONCURRENCY')
_TRUSTED_GENERATION_CONTRACT_VERSION = getattr(_engine, '_TRUSTED_GENERATION_CONTRACT_VERSION')
_TRUSTED_REQUIREMENT_RESULTS = getattr(_engine, '_TRUSTED_REQUIREMENT_RESULTS')
_call_trusted_skill_json = getattr(_engine, '_call_trusted_skill_json')
_compact_image_analysis_for_ai = getattr(_engine, '_compact_image_analysis_for_ai')
_compact_sections_for_ai = getattr(_engine, '_compact_sections_for_ai')
_extract_sections = getattr(_engine, '_extract_sections')
_filter_out_background_sections = getattr(_engine, '_filter_out_background_sections')
_format_duration_zh = getattr(_engine, '_format_duration_zh')
_is_state_label_only = getattr(_engine, '_is_state_label_only')
_normalize_requirement_quote = getattr(_engine, '_normalize_requirement_quote')
_normalize_test_design_profile = getattr(_engine, '_normalize_test_design_profile')
_resolve_requirement_source_quote = getattr(_engine, '_resolve_requirement_source_quote')
_source_evidence_role = getattr(_engine, '_source_evidence_role')
_state_target_conflicts = getattr(_engine, '_state_target_conflicts')
_trusted_scope_fingerprint = getattr(_engine, '_trusted_scope_fingerprint')
_trusted_scope_source_items = getattr(_engine, '_trusted_scope_source_items')
_trusted_source_by_id = getattr(_engine, '_trusted_source_by_id')
_trusted_v2_source_ids = getattr(_engine, '_trusted_v2_source_ids')
_validate_trusted_scope_index = getattr(_engine, '_validate_trusted_scope_index')
concurrent = getattr(_engine, 'concurrent')
contextvars = getattr(_engine, 'contextvars')
defaultdict = getattr(_engine, 'defaultdict')
json = getattr(_engine, 'json')
re = getattr(_engine, 're')
time = getattr(_engine, 'time')


def _source_by_id(*args, **kwargs):
    return getattr(_engine, "_source_by_id")(*args, **kwargs)

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


def _target_state_obligations(source: dict) -> list[str]:
    """Return explicit target-state statements suitable for generated rules."""
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    target_values = _engine._state_attribute_values(_engine._source_state_evidence_text(source, "target"))
    if not target_values:
        return []

    candidates: list[str] = []
    target_text = str(semantics.get("target_text") or "").strip()
    if target_text:
        candidates.extend(line.strip(" +-\t") for line in target_text.splitlines())
    for evidence in source.get("image_evidence") or []:
        if not isinstance(evidence, dict) or str(evidence.get("evidence_role") or "") != "target":
            continue
        candidates.append(str(evidence.get("summary") or "").strip())
        candidates.extend(str(value or "").strip() for value in evidence.get("requirement_hints") or [])

    obligations: list[str] = []
    for candidate in candidates:
        if not candidate or candidate in obligations:
            continue
        attributes = _engine._state_attribute_values(candidate)
        if any((attributes.get(name) or set()).intersection(values) for name, values in target_values.items()):
            obligations.append(candidate)
    return obligations


def _converge_state_repair_output(source: dict, raw: dict) -> dict:
    """Remove residual current-state claims after model repair, without weakening gates."""
    if not isinstance(raw, dict):
        return raw
    obligations = _target_state_obligations(source)
    if not obligations:
        return raw

    updated = json.loads(json.dumps(raw, ensure_ascii=False))
    profile = updated.get("test_design_profile") if isinstance(updated.get("test_design_profile"), dict) else {}
    must_cover = [
        str(value or "").strip()
        for value in profile.get("must_cover") or []
        if str(value or "").strip() and not _state_target_conflicts(source, str(value or ""))
    ]
    if not must_cover:
        must_cover.append(obligations[0])
    profile["must_cover"] = must_cover
    updated["test_design_profile"] = profile

    smoke_note = str(updated.get("smoke_test_scope_note") or "").strip()
    if _state_target_conflicts(source, smoke_note):
        updated["smoke_test_scope_note"] = obligations[0]

    for fp in updated.get("function_points") or []:
        if not isinstance(fp, dict):
            continue
        candidate_text = "\n".join([
            str(fp.get("title") or ""),
            str(fp.get("description") or ""),
            *[str(value or "") for value in fp.get("rules") or []],
            *[str(value or "") for value in fp.get("test_hints") or []],
        ])
        if not _state_target_conflicts(source, candidate_text):
            continue
        title = str(fp.get("title") or "").strip()
        if _state_target_conflicts(source, title):
            fp["title"] = str(source.get("title") or source.get("source_title") or "目标状态验证").strip()
        description = str(fp.get("description") or "").strip()
        if _state_target_conflicts(source, description):
            fp["description"] = f"按 target 证据实现并验证：{obligations[0]}"
        rules = [
            str(value or "").strip()
            for value in fp.get("rules") or []
            if str(value or "").strip() and not _state_target_conflicts(source, str(value or ""))
        ]
        hints = [
            str(value or "").strip()
            for value in fp.get("test_hints") or []
            if str(value or "").strip() and not _state_target_conflicts(source, str(value or ""))
        ]
        target_rule = f"目标行为：{obligations[0]}"
        if target_rule not in rules:
            rules.append(target_rule)
        fp["rules"] = rules
        fp["test_hints"] = hints
    return updated


def _converge_requirement_handoff_state_conflicts(
    scope_index: dict,
    requirement_handoff: dict,
) -> tuple[dict, list[str]]:
    """Apply target-evidence convergence before the full requirement gate."""
    updated = json.loads(json.dumps(requirement_handoff, ensure_ascii=False))
    repaired_source_ids: list[str] = []
    for source in _trusted_scope_source_items(scope_index):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("source_id") or "").strip()
        if not source_id:
            continue
        source_fps = [
            item
            for item in updated.get("function_points") or []
            if isinstance(item, dict) and str(item.get("source_id") or "").strip() == source_id
        ]
        if not source_fps:
            continue
        raw = {
            "function_points": source_fps,
            "test_design_profile": source.get("test_design_profile") or {},
            "smoke_test_scope_note": source.get("smoking_scope_note") or source.get("smoke_test_scope_note") or "",
        }
        converged = _converge_state_repair_output(source, raw)
        converged_fps = [item for item in converged.get("function_points") or [] if isinstance(item, dict)]
        if converged_fps == source_fps:
            continue
        source_pending = [
            item
            for item in updated.get("pending_confirmations") or []
            if isinstance(item, dict)
            and str(item.get("source_id") or item.get("ref_id") or "").strip() == source_id
        ]
        updated = _replace_trusted_requirement_source(
            scope_index,
            updated,
            source_id,
            converged_fps,
            source_pending,
        )
        repaired_source_ids.append(source_id)
    return updated, repaired_source_ids


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
    if isinstance(raw, dict):
        raw = _converge_state_repair_output(source, raw)
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
