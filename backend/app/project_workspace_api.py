"""Project collaboration workspace API.

Adds requirements / iterations / tasks / defects / members / traceability on top
of the existing Project (which remains the test-asset container). Reuses the
dependency + access helpers defined in ``app.api`` to stay consistent with the
platform conventions (``get_current_user``, ``_require_project_access`` etc.).
"""

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

import uuid
from pathlib import Path

from app import schemas
from app.api import (
    _load_case_entity,
    _normalize_case_type,
    _require_project_access,
    get_current_user,
)
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Activity,
    Comment,
    Defect,
    DefectCaseLink,
    DefectRunLink,
    Iteration,
    Project,
    ProjectMember,
    ProjectTask,
    Requirement,
    RequirementCaseLink,
    TestRun,
    User,
)
from app.timeutil import utc_now_naive


workspace_router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Project role resolution (platform role x project member role)
# ---------------------------------------------------------------------------

_ROLE_RANK = {"viewer": 0, "member": 1, "manager": 2, "owner": 3}


def _resolve_project_role(db: Session, user: User, project: Project) -> str:
    if user.role == "admin":
        return "owner"
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    if member is not None:
        return member.role
    # Workspace members that are not explicit project members can still view.
    return "viewer"


def _require_project_role(db: Session, user: User, project_id: int, min_role: str) -> Project:
    project = _require_project_access(db, user, db.get(Project, project_id))
    role = _resolve_project_role(db, user, project)
    if _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(min_role, 0):
        raise HTTPException(status_code=403, detail="项目内权限不足")
    return project


# ---------------------------------------------------------------------------
# Rich-text image upload (shared by requirement / task / defect editors)
# ---------------------------------------------------------------------------

_ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


@workspace_router.post("/uploads/image", response_model=schemas.UploadResult)
async def upload_rich_text_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> schemas.UploadResult:
    """Accept a pasted / dropped image and return a browser-reachable URL.

    The file is stored under ``settings.upload_dir`` and served back through the
    ``{api_v1_prefix}/uploads`` static mount (already proxied by nginx ``/api/``).
    """
    ext = _ALLOWED_IMAGE_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(status_code=422, detail="仅支持 PNG/JPG/GIF/WEBP/BMP 图片")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="上传的图片内容为空")
    if len(data) > settings.max_image_upload_bytes:
        limit_mb = settings.max_image_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"图片大小不能超过 {limit_mb}MB")
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (upload_dir / filename).write_bytes(data)
    url = f"{settings.api_v1_prefix}/uploads/{filename}"
    return schemas.UploadResult(url=url, filename=filename, size=len(data))


def _user_name_map(db: Session, user_ids: set[int]) -> dict[int, str]:
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(ids))).all()
    return {uid: (display or username or f"用户{uid}") for uid, display, username in rows}


def _log_activity(
    db: Session,
    *,
    project_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    actor_id: int | None,
    payload: dict | None = None,
) -> None:
    db.add(
        Activity(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            payload_json=payload,
        )
    )


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------

REQUIREMENT_TRANSITIONS = {
    "PENDING": {"PLANNING", "REJECTED", "CLOSED"},
    "PLANNING": {"IN_PROGRESS", "PENDING", "REJECTED"},
    "IN_PROGRESS": {"TESTING", "PLANNING"},
    "TESTING": {"DONE", "IN_PROGRESS"},
    "DONE": {"CLOSED", "TESTING"},
    "CLOSED": {"PENDING"},
    "REJECTED": {"PENDING"},
}

TASK_TRANSITIONS = {
    "TODO": {"DOING"},
    "DOING": {"REVIEW", "TODO"},
    "REVIEW": {"DONE", "DOING"},
    "DONE": {"REVIEW"},
}

DEFECT_TRANSITIONS = {
    "NEW": {"CONFIRMED", "WONTFIX"},
    "CONFIRMED": {"IN_PROGRESS", "WONTFIX"},
    "IN_PROGRESS": {"RESOLVED"},
    "RESOLVED": {"VERIFYING", "REOPENED"},
    "VERIFYING": {"CLOSED", "REOPENED"},
    "CLOSED": {"REOPENED"},
    "REOPENED": {"CONFIRMED", "IN_PROGRESS"},
    "WONTFIX": {"REOPENED"},
}


def _validate_transition(kind: str, current: str, target: str, table: dict) -> None:
    if current == target:
        return
    allowed = table.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{kind}状态不允许从 {current} 迁移到 {target}",
        )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@workspace_router.get("/projects/{project_id}/members", response_model=list[schemas.ProjectMemberRead])
def list_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.ProjectMemberRead]:
    _require_project_role(db, current_user, project_id, "viewer")
    members = list(
        db.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.id.asc())
        ).all()
    )
    name_map = _user_name_map(db, {m.user_id for m in members})
    user_rows = db.execute(select(User.id, User.username).where(User.id.in_({m.user_id for m in members}))).all() if members else []
    username_map = {uid: username for uid, username in user_rows}
    return [
        schemas.ProjectMemberRead(
            id=m.id,
            project_id=m.project_id,
            user_id=m.user_id,
            username=username_map.get(m.user_id),
            display_name=name_map.get(m.user_id),
            role=m.role,
            created_at=m.created_at,
        )
        for m in members
    ]


@workspace_router.post(
    "/projects/{project_id}/members",
    response_model=schemas.ProjectMemberRead,
    status_code=201,
)
def add_project_member(
    project_id: int,
    payload: schemas.ProjectMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ProjectMemberRead:
    _require_project_role(db, current_user, project_id, "manager")
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    existing = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == payload.user_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="该用户已是项目成员")
    member = ProjectMember(project_id=project_id, user_id=payload.user_id, role=payload.role)
    db.add(member)
    db.commit()
    db.refresh(member)
    return schemas.ProjectMemberRead(
        id=member.id,
        project_id=member.project_id,
        user_id=member.user_id,
        username=user.username,
        display_name=user.display_name,
        role=member.role,
        created_at=member.created_at,
    )


@workspace_router.put(
    "/projects/{project_id}/members/{member_id}",
    response_model=schemas.ProjectMemberRead,
)
def update_project_member(
    project_id: int,
    member_id: int,
    payload: schemas.ProjectMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ProjectMemberRead:
    _require_project_role(db, current_user, project_id, "manager")
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    member.role = payload.role
    db.commit()
    db.refresh(member)
    user = db.get(User, member.user_id)
    return schemas.ProjectMemberRead(
        id=member.id,
        project_id=member.project_id,
        user_id=member.user_id,
        username=user.username if user else None,
        display_name=user.display_name if user else None,
        role=member.role,
        created_at=member.created_at,
    )


@workspace_router.delete(
    "/projects/{project_id}/members/{member_id}",
    status_code=204,
)
def delete_project_member(
    project_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _require_project_role(db, current_user, project_id, "manager")
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    db.delete(member)
    db.commit()


# ---------------------------------------------------------------------------
# Iterations
# ---------------------------------------------------------------------------


@workspace_router.get("/projects/{project_id}/iterations", response_model=list[schemas.IterationRead])
def list_iterations(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Iteration]:
    _require_project_role(db, current_user, project_id, "viewer")
    return list(
        db.scalars(
            select(Iteration)
            .where(Iteration.project_id == project_id)
            .order_by(Iteration.sort_order.asc(), Iteration.id.asc())
        ).all()
    )


@workspace_router.post(
    "/projects/{project_id}/iterations",
    response_model=schemas.IterationRead,
    status_code=201,
)
def create_iteration(
    project_id: int,
    payload: schemas.IterationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Iteration:
    _require_project_role(db, current_user, project_id, "manager")
    max_order = db.scalar(select(func.max(Iteration.sort_order)).where(Iteration.project_id == project_id)) or 0.0
    iteration = Iteration(
        project_id=project_id,
        sort_order=max_order + 1000.0,
        created_by=current_user.id,
        updated_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(iteration)
    db.commit()
    db.refresh(iteration)
    _log_activity(
        db,
        project_id=project_id,
        entity_type="iteration",
        entity_id=iteration.id,
        action="create",
        actor_id=current_user.id,
        payload={"name": iteration.name},
    )
    db.commit()
    return iteration


@workspace_router.put("/iterations/{iteration_id}", response_model=schemas.IterationRead)
def update_iteration(
    iteration_id: int,
    payload: schemas.IterationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Iteration:
    iteration = db.get(Iteration, iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="迭代不存在")
    _require_project_role(db, current_user, iteration.project_id, "manager")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(iteration, key, value)
    iteration.updated_by = current_user.id
    db.commit()
    db.refresh(iteration)
    return iteration


@workspace_router.delete("/iterations/{iteration_id}", status_code=204)
def delete_iteration(
    iteration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    iteration = db.get(Iteration, iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="迭代不存在")
    _require_project_role(db, current_user, iteration.project_id, "manager")
    # Detach dependent entities back to the requirement pool.
    db.execute(
        Requirement.__table__.update()
        .where(Requirement.iteration_id == iteration_id)
        .values(iteration_id=None)
    )
    db.execute(
        ProjectTask.__table__.update()
        .where(ProjectTask.iteration_id == iteration_id)
        .values(iteration_id=None)
    )
    db.execute(
        Defect.__table__.update().where(Defect.iteration_id == iteration_id).values(iteration_id=None)
    )
    db.delete(iteration)
    db.commit()


@workspace_router.get("/iterations/{iteration_id}/burndown")
def iteration_burndown(
    iteration_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    iteration = db.get(Iteration, iteration_id)
    if iteration is None:
        raise HTTPException(status_code=404, detail="迭代不存在")
    _require_project_role(db, current_user, iteration.project_id, "viewer")
    reqs = list(db.scalars(select(Requirement).where(Requirement.iteration_id == iteration_id)).all())
    total_points = sum((r.story_points or 0) for r in reqs)
    done_points = sum((r.story_points or 0) for r in reqs if r.status in {"DONE", "CLOSED"})
    return {
        "iteration_id": iteration_id,
        "capacity_points": iteration.capacity_points,
        "total_points": total_points,
        "done_points": done_points,
        "remaining_points": max(total_points - done_points, 0),
        "requirement_total": len(reqs),
        "requirement_done": sum(1 for r in reqs if r.status in {"DONE", "CLOSED"}),
    }


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


@workspace_router.get("/projects/{project_id}/requirements", response_model=schemas.RequirementPage)
def list_requirements(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    priority: str | None = None,
    iteration_id: int | None = None,
    owner_id: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.RequirementPage:
    _require_project_role(db, current_user, project_id, "viewer")
    stmt = select(Requirement).where(Requirement.project_id == project_id)
    if status:
        stmt = stmt.where(Requirement.status == status)
    if priority:
        stmt = stmt.where(Requirement.priority == priority)
    if iteration_id:
        stmt = stmt.where(Requirement.iteration_id == iteration_id)
    if owner_id:
        stmt = stmt.where(Requirement.owner_id == owner_id)
    if keyword:
        stmt = stmt.where(Requirement.title.ilike(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Requirement.order_index.asc(), Requirement.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return schemas.RequirementPage(items=rows, total=total, page=page, page_size=page_size)


@workspace_router.post(
    "/projects/{project_id}/requirements",
    response_model=schemas.RequirementRead,
    status_code=201,
)
def create_requirement(
    project_id: int,
    payload: schemas.RequirementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Requirement:
    _require_project_role(db, current_user, project_id, "member")
    max_order = db.scalar(select(func.max(Requirement.order_index)).where(Requirement.project_id == project_id)) or 0.0
    requirement = Requirement(
        project_id=project_id,
        reporter_id=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
        order_index=max_order + 1000.0,
        **payload.model_dump(),
    )
    db.add(requirement)
    db.commit()
    db.refresh(requirement)
    _log_activity(
        db,
        project_id=project_id,
        entity_type="requirement",
        entity_id=requirement.id,
        action="create",
        actor_id=current_user.id,
        payload={"title": requirement.title},
    )
    db.commit()
    return requirement


@workspace_router.get("/requirements/{requirement_id}", response_model=schemas.RequirementRead)
def get_requirement(
    requirement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "viewer")
    return requirement


@workspace_router.put("/requirements/{requirement_id}", response_model=schemas.RequirementRead)
def update_requirement(
    requirement_id: int,
    payload: schemas.RequirementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "member")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(requirement, key, value)
    requirement.updated_by = current_user.id
    db.commit()
    db.refresh(requirement)
    return requirement


@workspace_router.put("/requirements/{requirement_id}/status", response_model=schemas.RequirementRead)
def change_requirement_status(
    requirement_id: int,
    payload: schemas.StatusChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "member")
    _validate_transition("需求", requirement.status, payload.status, REQUIREMENT_TRANSITIONS)
    previous = requirement.status
    requirement.status = payload.status
    requirement.updated_by = current_user.id
    _log_activity(
        db,
        project_id=requirement.project_id,
        entity_type="requirement",
        entity_id=requirement.id,
        action="status_change",
        actor_id=current_user.id,
        payload={"from": previous, "to": payload.status},
    )
    db.commit()
    db.refresh(requirement)
    return requirement


@workspace_router.put("/requirements/{requirement_id}/rank", response_model=schemas.RequirementRead)
def rank_requirement(
    requirement_id: int,
    payload: schemas.RankUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "member")
    if payload.status and payload.status != requirement.status:
        _validate_transition("需求", requirement.status, payload.status, REQUIREMENT_TRANSITIONS)
        requirement.status = payload.status
    requirement.order_index = payload.order_index
    requirement.updated_by = current_user.id
    db.commit()
    db.refresh(requirement)
    return requirement


@workspace_router.delete("/requirements/{requirement_id}", status_code=204)
def delete_requirement(
    requirement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "manager")
    db.execute(delete(RequirementCaseLink).where(RequirementCaseLink.requirement_id == requirement_id))
    db.delete(requirement)
    db.commit()


@workspace_router.get("/requirements/{requirement_id}/cases", response_model=list[schemas.CaseLinkRead])
def list_requirement_cases(
    requirement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseLinkRead]:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "viewer")
    links = list(
        db.scalars(
            select(RequirementCaseLink).where(RequirementCaseLink.requirement_id == requirement_id)
        ).all()
    )
    result = []
    for link in links:
        case = _load_case_entity(db, link.case_type, link.case_id)
        result.append(
            schemas.CaseLinkRead(
                id=link.id,
                case_type=link.case_type,
                case_id=link.case_id,
                case_name=getattr(case, "name", None),
                created_at=link.created_at,
            )
        )
    return result


@workspace_router.post(
    "/requirements/{requirement_id}/cases",
    response_model=schemas.CaseLinkRead,
    status_code=201,
)
def link_requirement_case(
    requirement_id: int,
    payload: schemas.CaseLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseLinkRead:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "member")
    case_type = _normalize_case_type(payload.case_type)
    case = _load_case_entity(db, case_type, payload.case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    existing = db.scalar(
        select(RequirementCaseLink).where(
            RequirementCaseLink.requirement_id == requirement_id,
            RequirementCaseLink.case_type == case_type,
            RequirementCaseLink.case_id == payload.case_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="该用例已关联")
    link = RequirementCaseLink(
        requirement_id=requirement_id,
        case_type=case_type,
        case_id=payload.case_id,
        created_by=current_user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return schemas.CaseLinkRead(
        id=link.id,
        case_type=link.case_type,
        case_id=link.case_id,
        case_name=getattr(case, "name", None),
        created_at=link.created_at,
    )


@workspace_router.delete("/requirements/{requirement_id}/cases/{link_id}", status_code=204)
def unlink_requirement_case(
    requirement_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    _require_project_role(db, current_user, requirement.project_id, "member")
    link = db.get(RequirementCaseLink, link_id)
    if link is None or link.requirement_id != requirement_id:
        raise HTTPException(status_code=404, detail="关联不存在")
    db.delete(link)
    db.commit()


@workspace_router.get(
    "/cases/{case_type}/{case_id}/requirements",
    response_model=list[schemas.RequirementRead],
)
def list_case_requirements(
    case_type: str,
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Requirement]:
    normalized = _normalize_case_type(case_type)
    links = list(
        db.scalars(
            select(RequirementCaseLink).where(
                RequirementCaseLink.case_type == normalized,
                RequirementCaseLink.case_id == case_id,
            )
        ).all()
    )
    requirement_ids = [link.requirement_id for link in links]
    if not requirement_ids:
        return []
    requirements = list(db.scalars(select(Requirement).where(Requirement.id.in_(requirement_ids))).all())
    accessible: list[Requirement] = []
    for requirement in requirements:
        project = db.get(Project, requirement.project_id)
        if project is None:
            continue
        try:
            _require_project_access(db, current_user, project)
        except HTTPException:
            continue
        accessible.append(requirement)
    return accessible


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@workspace_router.get("/projects/{project_id}/tasks", response_model=schemas.TaskPage)
def list_tasks(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=300),
    status: str | None = None,
    priority: str | None = None,
    iteration_id: int | None = None,
    assignee_id: int | None = None,
    requirement_id: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.TaskPage:
    _require_project_role(db, current_user, project_id, "viewer")
    stmt = select(ProjectTask).where(ProjectTask.project_id == project_id)
    if status:
        stmt = stmt.where(ProjectTask.status == status)
    if priority:
        stmt = stmt.where(ProjectTask.priority == priority)
    if iteration_id:
        stmt = stmt.where(ProjectTask.iteration_id == iteration_id)
    if assignee_id:
        stmt = stmt.where(ProjectTask.assignee_id == assignee_id)
    if requirement_id:
        stmt = stmt.where(ProjectTask.requirement_id == requirement_id)
    if keyword:
        stmt = stmt.where(ProjectTask.title.ilike(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(ProjectTask.order_index.asc(), ProjectTask.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return schemas.TaskPage(items=rows, total=total, page=page, page_size=page_size)


@workspace_router.post("/projects/{project_id}/tasks", response_model=schemas.TaskRead, status_code=201)
def create_task(
    project_id: int,
    payload: schemas.TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTask:
    _require_project_role(db, current_user, project_id, "member")
    max_order = db.scalar(select(func.max(ProjectTask.order_index)).where(ProjectTask.project_id == project_id)) or 0.0
    task = ProjectTask(
        project_id=project_id,
        reporter_id=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
        order_index=max_order + 1000.0,
        **payload.model_dump(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    _log_activity(
        db,
        project_id=project_id,
        entity_type="task",
        entity_id=task.id,
        action="create",
        actor_id=current_user.id,
        payload={"title": task.title},
    )
    db.commit()
    return task


@workspace_router.get("/tasks/{task_id}", response_model=schemas.TaskRead)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTask:
    task = db.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_project_role(db, current_user, task.project_id, "viewer")
    return task


@workspace_router.put("/tasks/{task_id}", response_model=schemas.TaskRead)
def update_task(
    task_id: int,
    payload: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTask:
    task = db.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_project_role(db, current_user, task.project_id, "member")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, key, value)
    task.updated_by = current_user.id
    db.commit()
    db.refresh(task)
    return task


@workspace_router.put("/tasks/{task_id}/status", response_model=schemas.TaskRead)
def change_task_status(
    task_id: int,
    payload: schemas.StatusChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTask:
    task = db.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_project_role(db, current_user, task.project_id, "member")
    _validate_transition("任务", task.status, payload.status, TASK_TRANSITIONS)
    task.status = payload.status
    task.updated_by = current_user.id
    db.commit()
    db.refresh(task)
    return task


@workspace_router.put("/tasks/{task_id}/rank", response_model=schemas.TaskRead)
def rank_task(
    task_id: int,
    payload: schemas.RankUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectTask:
    task = db.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_project_role(db, current_user, task.project_id, "member")
    if payload.status and payload.status != task.status:
        _validate_transition("任务", task.status, payload.status, TASK_TRANSITIONS)
        task.status = payload.status
    task.order_index = payload.order_index
    task.updated_by = current_user.id
    db.commit()
    db.refresh(task)
    return task


@workspace_router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    task = db.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_project_role(db, current_user, task.project_id, "member")
    db.delete(task)
    db.commit()


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------


@workspace_router.get("/projects/{project_id}/defects", response_model=schemas.DefectPage)
def list_defects(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=300),
    status: str | None = None,
    severity: str | None = None,
    priority: str | None = None,
    iteration_id: int | None = None,
    assignee_id: int | None = None,
    requirement_id: int | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.DefectPage:
    _require_project_role(db, current_user, project_id, "viewer")
    stmt = select(Defect).where(Defect.project_id == project_id)
    if status:
        stmt = stmt.where(Defect.status == status)
    if severity:
        stmt = stmt.where(Defect.severity == severity)
    if priority:
        stmt = stmt.where(Defect.priority == priority)
    if iteration_id:
        stmt = stmt.where(Defect.iteration_id == iteration_id)
    if assignee_id:
        stmt = stmt.where(Defect.assignee_id == assignee_id)
    if requirement_id:
        stmt = stmt.where(Defect.requirement_id == requirement_id)
    if keyword:
        stmt = stmt.where(Defect.title.ilike(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Defect.order_index.asc(), Defect.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return schemas.DefectPage(items=rows, total=total, page=page, page_size=page_size)


@workspace_router.post("/projects/{project_id}/defects", response_model=schemas.DefectRead, status_code=201)
def create_defect(
    project_id: int,
    payload: schemas.DefectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Defect:
    _require_project_role(db, current_user, project_id, "member")
    max_order = db.scalar(select(func.max(Defect.order_index)).where(Defect.project_id == project_id)) or 0.0
    defect = Defect(
        project_id=project_id,
        reporter_id=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
        order_index=max_order + 1000.0,
        **payload.model_dump(),
    )
    db.add(defect)
    db.commit()
    db.refresh(defect)
    _log_activity(
        db,
        project_id=project_id,
        entity_type="defect",
        entity_id=defect.id,
        action="create",
        actor_id=current_user.id,
        payload={"title": defect.title},
    )
    db.commit()
    return defect


@workspace_router.post("/project-defects/from-run/{run_id}", response_model=schemas.DefectRead, status_code=201)
def create_defect_from_run(
    run_id: int,
    payload: schemas.DefectFromRunCreate | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Defect:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_role(db, current_user, run.project_id, "member")
    payload = payload or schemas.DefectFromRunCreate()
    title = payload.title or f"[{run.case_name}] 执行失败缺陷"
    description = payload.description or run.summary or "由执行失败自动创建"
    max_order = db.scalar(select(func.max(Defect.order_index)).where(Defect.project_id == run.project_id)) or 0.0
    defect = Defect(
        project_id=run.project_id,
        requirement_id=payload.requirement_id,
        assignee_id=payload.assignee_id,
        title=title[:200],
        description=description,
        reproduce_steps=run.stderr_text or run.summary,
        severity=payload.severity,
        priority=payload.priority,
        status="NEW",
        reporter_id=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
        order_index=max_order + 1000.0,
    )
    db.add(defect)
    db.flush()
    db.add(DefectRunLink(defect_id=defect.id, test_run_id=run.id))
    if run.case_type and run.case_id:
        db.add(
            DefectCaseLink(
                defect_id=defect.id,
                case_type=_normalize_case_type(run.case_type),
                case_id=run.case_id,
            )
        )
    _log_activity(
        db,
        project_id=run.project_id,
        entity_type="defect",
        entity_id=defect.id,
        action="create_from_run",
        actor_id=current_user.id,
        payload={"run_id": run.id, "case_name": run.case_name},
    )
    db.commit()
    db.refresh(defect)
    return defect


@workspace_router.get("/project-defects/{defect_id}", response_model=schemas.DefectRead)
def get_defect(
    defect_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Defect:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    _require_project_role(db, current_user, defect.project_id, "viewer")
    return defect


@workspace_router.put("/project-defects/{defect_id}", response_model=schemas.DefectRead)
def update_defect(
    defect_id: int,
    payload: schemas.DefectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Defect:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    _require_project_role(db, current_user, defect.project_id, "member")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(defect, key, value)
    defect.updated_by = current_user.id
    db.commit()
    db.refresh(defect)
    return defect


@workspace_router.put("/project-defects/{defect_id}/status", response_model=schemas.DefectRead)
def change_defect_status(
    defect_id: int,
    payload: schemas.StatusChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Defect:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    _require_project_role(db, current_user, defect.project_id, "member")
    _validate_transition("缺陷", defect.status, payload.status, DEFECT_TRANSITIONS)
    defect.status = payload.status
    if payload.status == "RESOLVED":
        defect.resolved_at = utc_now_naive()
    if payload.status == "CLOSED":
        defect.closed_at = utc_now_naive()
    if payload.status == "REOPENED":
        defect.resolved_at = None
        defect.closed_at = None
    defect.updated_by = current_user.id
    _log_activity(
        db,
        project_id=defect.project_id,
        entity_type="defect",
        entity_id=defect.id,
        action="status_change",
        actor_id=current_user.id,
        payload={"to": payload.status},
    )
    db.commit()
    db.refresh(defect)
    return defect


@workspace_router.put("/project-defects/{defect_id}/rank", response_model=schemas.DefectRead)
def rank_defect(
    defect_id: int,
    payload: schemas.RankUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Defect:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    _require_project_role(db, current_user, defect.project_id, "member")
    if payload.status and payload.status != defect.status:
        _validate_transition("缺陷", defect.status, payload.status, DEFECT_TRANSITIONS)
        defect.status = payload.status
    defect.order_index = payload.order_index
    defect.updated_by = current_user.id
    db.commit()
    db.refresh(defect)
    return defect


@workspace_router.delete("/project-defects/{defect_id}", status_code=204)
def delete_defect(
    defect_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    _require_project_role(db, current_user, defect.project_id, "manager")
    db.execute(delete(DefectRunLink).where(DefectRunLink.defect_id == defect_id))
    db.execute(delete(DefectCaseLink).where(DefectCaseLink.defect_id == defect_id))
    db.delete(defect)
    db.commit()


@workspace_router.get("/project-defects/{defect_id}/links")
def list_defect_links(
    defect_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    defect = db.get(Defect, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷不存在")
    _require_project_role(db, current_user, defect.project_id, "viewer")
    run_links = list(db.scalars(select(DefectRunLink).where(DefectRunLink.defect_id == defect_id)).all())
    case_links = list(db.scalars(select(DefectCaseLink).where(DefectCaseLink.defect_id == defect_id)).all())
    runs = []
    for link in run_links:
        run = db.get(TestRun, link.test_run_id)
        if run is not None:
            runs.append(
                {
                    "link_id": link.id,
                    "test_run_id": run.id,
                    "case_name": run.case_name,
                    "status": run.status,
                    "created_at": run.created_at,
                }
            )
    cases = []
    for link in case_links:
        case = _load_case_entity(db, link.case_type, link.case_id)
        cases.append(
            {
                "link_id": link.id,
                "case_type": link.case_type,
                "case_id": link.case_id,
                "case_name": getattr(case, "name", None),
            }
        )
    return {"defect_id": defect_id, "runs": runs, "cases": cases}


# ---------------------------------------------------------------------------
# Comments & activities
# ---------------------------------------------------------------------------

_COMMENT_ENTITIES = {"requirement", "task", "defect", "iteration"}


def _resolve_entity_project(db: Session, entity_type: str, entity_id: int) -> int | None:
    model = {
        "requirement": Requirement,
        "task": ProjectTask,
        "defect": Defect,
        "iteration": Iteration,
    }.get(entity_type)
    if model is None:
        return None
    entity = db.get(model, entity_id)
    return entity.project_id if entity is not None else None


@workspace_router.get("/{entity_type}/{entity_id}/comments", response_model=list[schemas.CommentRead])
def list_comments(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CommentRead]:
    if entity_type not in _COMMENT_ENTITIES:
        raise HTTPException(status_code=404, detail="不支持的实体类型")
    project_id = _resolve_entity_project(db, entity_type, entity_id)
    if project_id is None:
        raise HTTPException(status_code=404, detail="实体不存在")
    _require_project_role(db, current_user, project_id, "viewer")
    rows = list(
        db.scalars(
            select(Comment)
            .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
            .order_by(Comment.id.asc())
        ).all()
    )
    name_map = _user_name_map(db, {c.author_id for c in rows})
    return [
        schemas.CommentRead(
            id=c.id,
            project_id=c.project_id,
            entity_type=c.entity_type,
            entity_id=c.entity_id,
            author_id=c.author_id,
            author_name=name_map.get(c.author_id),
            content=c.content,
            created_at=c.created_at,
        )
        for c in rows
    ]


@workspace_router.post(
    "/{entity_type}/{entity_id}/comments",
    response_model=schemas.CommentRead,
    status_code=201,
)
def create_comment(
    entity_type: str,
    entity_id: int,
    payload: schemas.CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CommentRead:
    if entity_type not in _COMMENT_ENTITIES:
        raise HTTPException(status_code=404, detail="不支持的实体类型")
    project_id = _resolve_entity_project(db, entity_type, entity_id)
    if project_id is None:
        raise HTTPException(status_code=404, detail="实体不存在")
    _require_project_role(db, current_user, project_id, "member")
    comment = Comment(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        author_id=current_user.id,
        content=payload.content,
    )
    db.add(comment)
    _log_activity(
        db,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action="comment",
        actor_id=current_user.id,
    )
    db.commit()
    db.refresh(comment)
    return schemas.CommentRead(
        id=comment.id,
        project_id=comment.project_id,
        entity_type=comment.entity_type,
        entity_id=comment.entity_id,
        author_id=comment.author_id,
        author_name=current_user.display_name or current_user.username,
        content=comment.content,
        created_at=comment.created_at,
    )


@workspace_router.get("/projects/{project_id}/activities", response_model=list[schemas.ActivityRead])
def list_activities(
    project_id: int,
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.ActivityRead]:
    _require_project_role(db, current_user, project_id, "viewer")
    rows = list(
        db.scalars(
            select(Activity)
            .where(Activity.project_id == project_id)
            .order_by(Activity.id.desc())
            .limit(limit)
        ).all()
    )
    name_map = _user_name_map(db, {a.actor_id for a in rows})
    return [
        schemas.ActivityRead(
            id=a.id,
            project_id=a.project_id,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            action=a.action,
            payload_json=a.payload_json,
            actor_id=a.actor_id,
            actor_name=name_map.get(a.actor_id),
            created_at=a.created_at,
        )
        for a in rows
    ]


# ---------------------------------------------------------------------------
# Overview & traceability
# ---------------------------------------------------------------------------


def _count_by_status(db: Session, model, project_id: int) -> dict[str, int]:
    rows = db.execute(
        select(model.status, func.count(model.id))
        .where(model.project_id == project_id)
        .group_by(model.status)
    ).all()
    return {status: count for status, count in rows}


@workspace_router.get("/projects/{project_id}/overview", response_model=schemas.ProjectOverview)
def project_overview(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ProjectOverview:
    project = _require_project_role(db, current_user, project_id, "viewer")
    my_role = _resolve_project_role(db, current_user, project)
    req_counts = _count_by_status(db, Requirement, project_id)
    task_counts = _count_by_status(db, ProjectTask, project_id)
    defect_counts = _count_by_status(db, Defect, project_id)
    open_defect_total = sum(
        count for status, count in defect_counts.items() if status not in {"CLOSED", "WONTFIX"}
    )
    active_iteration = db.scalar(
        select(Iteration)
        .where(Iteration.project_id == project_id, Iteration.status == "ACTIVE")
        .order_by(Iteration.id.desc())
    )
    iteration_total = db.scalar(
        select(func.count(Iteration.id)).where(Iteration.project_id == project_id)
    ) or 0
    member_total = db.scalar(
        select(func.count(ProjectMember.id)).where(ProjectMember.project_id == project_id)
    ) or 0
    requirement_total = sum(req_counts.values())
    covered = db.scalar(
        select(func.count(func.distinct(RequirementCaseLink.requirement_id)))
        .select_from(RequirementCaseLink)
        .join(Requirement, Requirement.id == RequirementCaseLink.requirement_id)
        .where(Requirement.project_id == project_id)
    ) or 0
    coverage_rate = round((covered / requirement_total) * 100, 1) if requirement_total else 0.0
    my_open_requirements = db.scalar(
        select(func.count(Requirement.id)).where(
            Requirement.project_id == project_id,
            Requirement.owner_id == current_user.id,
            Requirement.status.notin_(["DONE", "CLOSED", "REJECTED"]),
        )
    ) or 0
    my_open_tasks = db.scalar(
        select(func.count(ProjectTask.id)).where(
            ProjectTask.project_id == project_id,
            ProjectTask.assignee_id == current_user.id,
            ProjectTask.status != "DONE",
        )
    ) or 0
    my_open_defects = db.scalar(
        select(func.count(Defect.id)).where(
            Defect.project_id == project_id,
            Defect.assignee_id == current_user.id,
            Defect.status.notin_(["CLOSED", "WONTFIX"]),
        )
    ) or 0
    activities = list_activities(project_id, limit=10, db=db, current_user=current_user)
    return schemas.ProjectOverview(
        project_id=project_id,
        my_role=my_role,
        requirement_counts=req_counts,
        task_counts=task_counts,
        defect_counts=defect_counts,
        requirement_total=requirement_total,
        task_total=sum(task_counts.values()),
        defect_total=sum(defect_counts.values()),
        open_defect_total=open_defect_total,
        iteration_total=iteration_total,
        active_iteration=active_iteration,
        member_total=member_total,
        case_coverage_rate=coverage_rate,
        my_open_requirements=my_open_requirements,
        my_open_tasks=my_open_tasks,
        my_open_defects=my_open_defects,
        recent_activities=activities,
    )


@workspace_router.get("/projects/{project_id}/trace", response_model=schemas.TraceMatrix)
def project_trace(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.TraceMatrix:
    _require_project_role(db, current_user, project_id, "viewer")
    requirements = list(
        db.scalars(
            select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.id.asc())
        ).all()
    )
    rows: list[schemas.TraceRow] = []
    for requirement in requirements:
        links = list(
            db.scalars(
                select(RequirementCaseLink).where(RequirementCaseLink.requirement_id == requirement.id)
            ).all()
        )
        api_count = sum(1 for link in links if link.case_type == "API")
        ui_count = sum(1 for link in links if link.case_type == "UI")
        perf_count = sum(1 for link in links if link.case_type == "PERF")
        total_cases = len(links)
        last_status = None
        if links:
            for link in links:
                run = db.scalar(
                    select(TestRun)
                    .where(TestRun.case_type == link.case_type, TestRun.case_id == link.case_id)
                    .order_by(TestRun.id.desc())
                )
                if run is not None:
                    if last_status is None:
                        last_status = run.status
                    if run.status != "SUCCESS":
                        last_status = run.status
                        break
        open_defects = db.scalar(
            select(func.count(Defect.id)).where(
                Defect.requirement_id == requirement.id,
                Defect.status.notin_(["CLOSED", "WONTFIX"]),
            )
        ) or 0
        closed_defects = db.scalar(
            select(func.count(Defect.id)).where(
                Defect.requirement_id == requirement.id,
                Defect.status.in_(["CLOSED", "WONTFIX"]),
            )
        ) or 0
        if total_cases == 0:
            coverage = "NONE"
        elif last_status == "SUCCESS":
            coverage = "COVERED"
        elif last_status is None:
            coverage = "UNTESTED"
        else:
            coverage = "FAILED"
        rows.append(
            schemas.TraceRow(
                requirement_id=requirement.id,
                requirement_title=requirement.title,
                requirement_status=requirement.status,
                priority=requirement.priority,
                api_case_count=api_count,
                ui_case_count=ui_count,
                perf_case_count=perf_count,
                total_case_count=total_cases,
                last_run_status=last_status,
                open_defect_count=open_defects,
                closed_defect_count=closed_defects,
                coverage=coverage,
            )
        )
    return schemas.TraceMatrix(project_id=project_id, rows=rows)
