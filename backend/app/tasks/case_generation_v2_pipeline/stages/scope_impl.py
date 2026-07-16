"""Implementation functions owned by this V2 pipeline stage."""

from __future__ import annotations

from app.tasks.case_generation_v2_pipeline import engine as _engine

ModelJSONParseError = getattr(_engine, 'ModelJSONParseError')
_CURRENT_STATE_MARKERS = getattr(_engine, '_CURRENT_STATE_MARKERS')
_CURRENT_STATE_NEGATION_PATTERN = getattr(_engine, '_CURRENT_STATE_NEGATION_PATTERN')
_HTML_COMMENT_PATTERN = getattr(_engine, '_HTML_COMMENT_PATTERN')
_HTML_IMAGE_PATTERN = getattr(_engine, '_HTML_IMAGE_PATTERN')
_HTML_TAG_PATTERN = getattr(_engine, '_HTML_TAG_PATTERN')
_LONG_CHAT_TIMEOUT_SECONDS = getattr(_engine, '_LONG_CHAT_TIMEOUT_SECONDS')
_MARKDOWN_IMAGE_PATTERN = getattr(_engine, '_MARKDOWN_IMAGE_PATTERN')
_REQUIREMENT_QUOTE_CHAR_MAP = getattr(_engine, '_REQUIREMENT_QUOTE_CHAR_MAP')
_SCOPE_INDEX_BATCH_MAX_SECTIONS = getattr(_engine, '_SCOPE_INDEX_BATCH_MAX_SECTIONS')
_SCOPE_INDEX_BATCH_TEXT_LIMIT = getattr(_engine, '_SCOPE_INDEX_BATCH_TEXT_LIMIT')
_SCOPE_INDEX_BATCH_TRIGGER_TEXT = getattr(_engine, '_SCOPE_INDEX_BATCH_TRIGGER_TEXT')
_SCOPE_INDEX_CONCURRENCY = getattr(_engine, '_SCOPE_INDEX_CONCURRENCY')
_SCOPE_INDEX_TWO_PHASE_TRIGGER_SECTIONS = getattr(_engine, '_SCOPE_INDEX_TWO_PHASE_TRIGGER_SECTIONS')
_SCOPE_INDEX_TWO_PHASE_TRIGGER_TEXT = getattr(_engine, '_SCOPE_INDEX_TWO_PHASE_TRIGGER_TEXT')
_STATE_ATTRIBUTE_PATTERNS = getattr(_engine, '_STATE_ATTRIBUTE_PATTERNS')
_TARGET_STATE_MARKERS = getattr(_engine, '_TARGET_STATE_MARKERS')
_TRUSTED_GENERATION_CONTRACT_VERSION = getattr(_engine, '_TRUSTED_GENERATION_CONTRACT_VERSION')
_call_trusted_skill_json = getattr(_engine, '_call_trusted_skill_json')
_clean_heading_text = getattr(_engine, '_clean_heading_text')
_compact_image_analysis_for_ai = getattr(_engine, '_compact_image_analysis_for_ai')
_compact_sections_for_ai = getattr(_engine, '_compact_sections_for_ai')
_coverage_budget_forbidden_keys = getattr(_engine, '_coverage_budget_forbidden_keys')
_default_test_design_profile = getattr(_engine, '_default_test_design_profile')
_extract_image_links = getattr(_engine, '_extract_image_links')
_extract_sections = getattr(_engine, '_extract_sections')
_filter_out_background_sections = getattr(_engine, '_filter_out_background_sections')
_format_duration_zh = getattr(_engine, '_format_duration_zh')
_is_json_truncation_error = getattr(_engine, '_is_json_truncation_error')
_normalize_test_design_profile = getattr(_engine, '_normalize_test_design_profile')
_normalize_title_key = getattr(_engine, '_normalize_title_key')
_requirement_text_excerpt = getattr(_engine, '_requirement_text_excerpt')
_resolve_unified_rules_dir = getattr(_engine, '_resolve_unified_rules_dir')
_trusted_scope_shards = getattr(_engine, '_trusted_scope_shards')
_trusted_scope_source_items = getattr(_engine, '_trusted_scope_source_items')
concurrent = getattr(_engine, 'concurrent')
contextvars = getattr(_engine, 'contextvars')
current_attempt_id = getattr(_engine, 'current_attempt_id')
current_run_id = getattr(_engine, 'current_run_id')
defaultdict = getattr(_engine, 'defaultdict')
hashlib = getattr(_engine, 'hashlib')
json = getattr(_engine, 'json')
re = getattr(_engine, 're')
support_can_reuse_trusted_requirement = getattr(_engine, 'support_can_reuse_trusted_requirement')
support_can_reuse_trusted_scope_index = getattr(_engine, 'support_can_reuse_trusted_scope_index')
time = getattr(_engine, 'time')
urljoin = getattr(_engine, 'urljoin')
utc_now_naive = getattr(_engine, 'utc_now_naive')

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
    scenario_text: str = "",
) -> bool:
    """Allow a current-state fact only when the target changes another explicit branch."""
    semantics = source.get("source_state_semantics") if isinstance(source.get("source_state_semantics"), dict) else {}
    if not semantics.get("has_state_transition"):
        return False
    expected = _normalize_requirement_quote(expected_result)
    scenario = _normalize_requirement_quote(scenario_text)
    quote = _normalize_requirement_quote(source_quote)
    current = _normalize_requirement_quote(_source_state_evidence_text(source, "current"))
    target = _normalize_requirement_quote(_source_state_evidence_text(source, "target"))
    expected_is_partial = any(marker in expected or marker in scenario for marker in ("非全选", "未全选", "部分选择"))
    current_covers_both = any(marker in quote or marker in current for marker in ("无论是否全选", "不论是否全选"))
    target_changes_full_only = "全选时" in target and not any(marker in target for marker in ("非全选", "未全选", "部分选择"))
    return expected_is_partial and current_covers_both and target_changes_full_only


def _current_state_expectation_is_allowed(
    source: dict,
    expected_result: str,
    source_quote: str = "",
    scenario_text: str = "",
) -> bool:
    return _current_state_basis_is_allowed(expected_result) or _current_state_positive_expectation_is_retained(
        source,
        expected_result,
        source_quote,
        scenario_text,
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
    return support_can_reuse_trusted_scope_index(
        previous_scope_index,
        previous_source_manifest,
        current_source_manifest,
        previous_scope_gate,
        generation_contract_version=_TRUSTED_GENERATION_CONTRACT_VERSION,
    )


def _can_reuse_trusted_requirement(
    previous_requirement_handoff: dict | None,
    scope_index: dict,
    previous_requirement_gate: dict | None,
) -> bool:
    return support_can_reuse_trusted_requirement(
        previous_requirement_handoff,
        _trusted_scope_fingerprint(scope_index),
        previous_requirement_gate,
        generation_contract_version=_TRUSTED_GENERATION_CONTRACT_VERSION,
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
