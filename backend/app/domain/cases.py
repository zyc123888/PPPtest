"""用例领域共享辅助逻辑（类型归一化、快照、变更历史与评审门禁）。"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.models import (
    APICase,
    CaseChangeHistory,
    PerformanceCase,
    UICase,
    User,
)


def _initial_case_data(payload) -> dict:
    """Create/import paths cannot grant a review decision."""
    data = payload.model_dump()
    data["review_status"] = "DRAFT"
    data["review_note"] = None
    return data


def _reject_case_project_reassignment(current_project_id: int, requested_project_id: int) -> None:
    if requested_project_id != current_project_id:
        raise HTTPException(
            status_code=400,
            detail="普通更新不允许变更用例所属项目，请使用专用移动操作",
        )


def _serialize_unified_case(case_type: str, case) -> schemas.UnifiedCaseRead:
    payload = {
        "case_type": case_type,
        "case_id": case.id,
        "project_id": case.project_id,
        "name": case.name,
        "folder_path": getattr(case, "folder_path", None),
        "priority": getattr(case, "priority", "P2") or "P2",
        "status": getattr(case, "status", "ACTIVE") or "ACTIVE",
        "review_status": getattr(case, "review_status", "DRAFT") or "DRAFT",
        "version_no": getattr(case, "version_no", "1.0.0") or "1.0.0",
        "review_note": getattr(case, "review_note", None),
        "tags_json": getattr(case, "tags_json", None),
        "method": getattr(case, "method", None),
        "path": getattr(case, "path", None),
        "target_url": getattr(case, "target_url", None),
        "expected_status": getattr(case, "expected_status", None),
        "step_count": len(getattr(case, "steps_json", []) or []) if hasattr(case, "steps_json") else None,
        "steps_json": getattr(case, "steps_json", None),
        "expect_text": getattr(case, "expect_text", None),
        "headers_json": getattr(case, "headers_json", None),
        "body_json": getattr(case, "body_json", None),
        "assertions_json": getattr(case, "assertions_json", None),
        "generation_mode": getattr(case, "generation_mode", None),
        "execution_mode": getattr(case, "execution_mode", None),
        "engine": getattr(case, "engine", "native") or "native",
        "self_heal_enabled": bool(getattr(case, "self_heal_enabled", False)),
        "max_agent_steps": getattr(case, "max_agent_steps", None),
        "allowed_origins_json": getattr(case, "allowed_origins_json", None),
        "prohibited_actions_json": getattr(case, "prohibited_actions_json", None),
        "ai_goal": getattr(case, "ai_goal", None),
        "skill_name": getattr(case, "skill_name", None),
        "skill_version": getattr(case, "skill_version", None),
        "generation_meta_json": getattr(case, "generation_meta_json", None),
        "concurrency": getattr(case, "concurrency", None),
        "total_requests": getattr(case, "total_requests", None),
        "max_avg_response_ms": getattr(case, "max_avg_response_ms", None),
        "max_p95_response_ms": getattr(case, "max_p95_response_ms", None),
        "max_error_rate": getattr(case, "max_error_rate", None),
        "created_at": getattr(case, "created_at", None),
        "updated_at": getattr(case, "updated_at", None),
    }
    return schemas.UnifiedCaseRead(**payload)


def _normalize_case_type(case_type: str) -> str:
    return (case_type or "").strip().upper()


def _load_case_entity(db: Session, case_type: str, case_id: int):
    normalized_type = _normalize_case_type(case_type)
    if normalized_type == "API":
        return db.get(APICase, case_id)
    if normalized_type == "UI":
        return db.get(UICase, case_id)
    if normalized_type == "PERF":
        return db.get(PerformanceCase, case_id)
    return None


def _bump_version(version_no: str | None) -> str:
    value = (version_no or "1.0.0").strip()
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return "1.0.1"
    major, minor, patch = [int(part) for part in parts]
    return f"{major}.{minor}.{patch + 1}"


def _case_snapshot(case) -> dict:
    if isinstance(case, APICase):
        case_type = "API"
    elif isinstance(case, PerformanceCase):
        case_type = "PERF"
    else:
        case_type = "UI"
    payload = {
        "id": case.id,
        "name": case.name,
        "project_id": case.project_id,
        "type": case_type,
    }
    for field in (
        "folder_path",
        "method",
        "path",
        "target_url",
        "expect_text",
        "priority",
        "status",
        "expected_status",
        "tags_json",
        "headers_json",
        "body_json",
        "assertions_json",
        "extractors_json",
        "steps_json",
        "datasets_json",
        "mock_enabled",
        "mock_config_json",
        "concurrency",
        "total_requests",
        "max_avg_response_ms",
        "max_p95_response_ms",
        "max_error_rate",
        "review_status",
        "version_no",
        "review_note",
        "generation_mode",
        "execution_mode",
        "engine",
        "self_heal_enabled",
        "max_agent_steps",
        "allowed_origins_json",
        "prohibited_actions_json",
        "ai_goal",
        "skill_name",
        "skill_version",
    ):
        if hasattr(case, field):
            payload[field] = getattr(case, field)
    return payload


def _ensure_case_defaults(case) -> None:
    if hasattr(case, "review_status") and not getattr(case, "review_status", None):
        case.review_status = "DRAFT"
    if hasattr(case, "version_no") and not getattr(case, "version_no", None):
        case.version_no = "1.0.0"
    if hasattr(case, "generation_mode") and not getattr(case, "generation_mode", None):
        case.generation_mode = "manual"
    if hasattr(case, "execution_mode") and not getattr(case, "execution_mode", None):
        case.execution_mode = "stable"
    if hasattr(case, "engine") and not getattr(case, "engine", None):
        case.engine = "native"
    if hasattr(case, "max_agent_steps") and not getattr(case, "max_agent_steps", None):
        case.max_agent_steps = 10


def _record_case_history(
    db: Session,
    *,
    case_type: str,
    case,
    action: str,
    changed_by: int | None,
    summary: str | None = None,
) -> None:
    db.add(
        CaseChangeHistory(
            project_id=case.project_id,
            case_type=_normalize_case_type(case_type),
            case_id=case.id,
            case_name=case.name,
            action=action,
            version_no=getattr(case, "version_no", None),
            review_status=getattr(case, "review_status", None),
            review_note=getattr(case, "review_note", None),
            summary=summary,
            snapshot_json=_case_snapshot(case),
            changed_by=changed_by,
        )
    )


def _validate_plan_case_review_gate(case, current_user: User, allow_unapproved: bool) -> None:
    review_status = (getattr(case, "review_status", "DRAFT") or "DRAFT").upper()
    if review_status == "APPROVED":
        return
    if allow_unapproved and current_user.role == "admin":
        return
    raise HTTPException(status_code=400, detail=f"用例未通过评审，当前状态为 {review_status}")
