from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

from app import schemas
from app.core.config import settings
from app.tasks.model_client import call_json_chat_completion
from app.timeutil import utc_now_naive


SKILL_NAME = "ui-case-designer"
SKILL_VERSION = "1.0.0"
_REQUIRED_OUTPUT_KEYS = {
    "name",
    "folder_path",
    "target_url",
    "priority",
    "expect_text",
    "tags_json",
    "steps_json",
    "assertions_json",
    "design_notes",
    "warnings",
}


def _skill_directory() -> Path:
    configured = Path(settings.ui_case_skill_dir)
    candidates = [configured] if configured.is_absolute() else [
        Path(__file__).resolve().parents[1] / configured,
        Path.cwd() / configured,
    ]
    for root in candidates:
        skill_dir = root / SKILL_NAME
        if (skill_dir / "SKILL.md").is_file():
            return skill_dir
    raise RuntimeError(f"UI 用例 Skill 不存在：{SKILL_NAME}")


def _load_skill_contract() -> tuple[str, str]:
    skill_dir = _skill_directory()
    skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    schema_text = (skill_dir / "references" / "output-schema.json").read_text(encoding="utf-8")
    json.loads(schema_text)
    return skill_text, schema_text


def _parse_json_object(raw_text: str) -> dict:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("模型未返回 UI 用例 JSON 对象")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型返回的 UI 用例 JSON 无法解析：{exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("模型返回的 UI 用例必须是 JSON 对象")
    missing = sorted(_REQUIRED_OUTPUT_KEYS - set(payload))
    if missing:
        raise ValueError(f"模型返回的 UI 用例缺少字段：{', '.join(missing)}")
    unexpected = sorted(set(payload) - _REQUIRED_OUTPUT_KEYS)
    if unexpected:
        raise ValueError(f"模型返回的 UI 用例包含未支持字段：{', '.join(unexpected)}")
    return payload


def _origin(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("目标地址必须是有效的 HTTP 或 HTTPS URL")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"


def _text_list(value, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"模型返回的 {field_name} 必须是数组")
    return [str(item).strip() for item in value if str(item).strip()]


def _gate_generated_payload(
    payload: dict,
    request: schemas.UICaseAIGenerateRequest,
    *,
    project_base_url: str,
) -> tuple[dict, list[str], list[str]]:
    requested_target = request.target_url.strip()
    if str(payload.get("target_url") or "").strip() != requested_target:
        raise ValueError("模型修改了目标地址，AI 草稿已被门禁拒绝")

    allowed_origins = {_origin(requested_target)}
    if project_base_url:
        allowed_origins.add(_origin(project_base_url))

    steps = payload.get("steps_json")
    assertions = payload.get("assertions_json")
    if not isinstance(steps, list) or not steps:
        raise ValueError("AI 草稿至少需要一个操作步骤")
    if len(steps) > request.max_steps:
        raise ValueError(f"AI 草稿包含 {len(steps)} 个步骤，超过上限 {request.max_steps}")
    if not isinstance(assertions, list):
        raise ValueError("模型返回的 assertions_json 必须是数组")

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"第 {index} 个 AI 步骤必须是对象")
        if step.get("action") != "goto":
            continue
        destination = urljoin(requested_target, str(step.get("value") or "").strip())
        if _origin(destination) not in allowed_origins:
            raise ValueError(f"第 {index} 个 AI 步骤尝试跳转到未授权域名")

    warnings = _text_list(payload.get("warnings"), "warnings")[:10]
    design_notes = _text_list(payload.get("design_notes"), "design_notes")[:10]
    tags = _text_list(payload.get("tags_json"), "tags_json")
    for tag in ("AI生成", SKILL_NAME):
        if tag not in tags:
            tags.append(tag)

    gated = {
        "project_id": request.project_id,
        "name": str(payload.get("name") or "").strip(),
        "folder_path": str(payload.get("folder_path") or "").strip() or "AI生成",
        "target_url": requested_target,
        "priority": str(payload.get("priority") or "P2").strip().upper(),
        "status": "ACTIVE",
        "review_status": "DRAFT",
        "version_no": "1.0.0",
        "review_note": None,
        "tags_json": tags[:12],
        "steps_json": steps,
        "assertions_json": assertions or None,
        "expect_text": str(payload.get("expect_text") or "").strip(),
        "generation_mode": "ai_skill",
        "ai_goal": request.goal.strip(),
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
    }
    return gated, warnings, design_notes


async def generate_ui_case_draft(
    request: schemas.UICaseAIGenerateRequest,
    *,
    project_name: str,
    project_base_url: str,
    model: str,
    base_url: str,
    api_key: str,
) -> schemas.UICaseAIGenerateResponse:
    skill_text, schema_text = _load_skill_contract()
    allowed_origins = sorted({_origin(request.target_url), _origin(project_base_url)})
    system_prompt = (
        f"You are running the {SKILL_NAME} skill, version {SKILL_VERSION}.\n\n"
        f"{skill_text}\n\nOutput contract:\n{schema_text}"
    )
    user_content = json.dumps(
        {
            "project": {"name": project_name, "base_url": project_base_url},
            "target_url": request.target_url.strip(),
            "goal": request.goal.strip(),
            "context": (request.context or "").strip() or None,
            "max_steps": request.max_steps,
            "allowed_origins": allowed_origins,
        },
        ensure_ascii=False,
    )
    raw_text = await call_json_chat_completion(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=settings.ui_case_ai_max_tokens,
        timeout_seconds=settings.ui_case_ai_timeout_seconds,
    )
    payload = _parse_json_object(raw_text)
    gated, warnings, design_notes = _gate_generated_payload(
        payload,
        request,
        project_base_url=project_base_url,
    )
    generated_at = utc_now_naive().isoformat(timespec="seconds") + "Z"
    gated["generation_meta_json"] = {
        "generated_at": generated_at,
        "model": model,
        "skill_name": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "skill_sha256": hashlib.sha256(skill_text.encode("utf-8")).hexdigest(),
        "context_provided": bool((request.context or "").strip()),
        "max_steps": request.max_steps,
        "design_notes": design_notes,
        "warnings": warnings,
    }
    draft = schemas.UICaseCreate(**gated)
    return schemas.UICaseAIGenerateResponse(
        draft=draft,
        skill_name=SKILL_NAME,
        skill_version=SKILL_VERSION,
        model=model,
        warnings=warnings,
        design_notes=design_notes,
    )
