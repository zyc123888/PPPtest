"""工作空间与工作台聚合路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.database import get_db
from app.models import (
    AIModelConfig,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.deps.auth import (
    _accessible_project_ids,
    _ensure_workspace_owner_guard,
    get_current_user,
    require_admin,
)

router = APIRouter(tags=["workspaces"])


@router.get("/dashboard/summary", response_model=schemas.DashboardSummary, summary="获取工作台汇总指标")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.DashboardSummary:
    project_ids = None if current_user.role == "admin" else _accessible_project_ids(db, current_user)
    return schemas.DashboardSummary(**services.build_dashboard_summary(db, project_ids=project_ids))


@router.get("/workspaces", response_model=list[schemas.WorkspaceRead], summary="获取可访问的工作空间列表")
def list_workspaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Workspace]:
    stmt = select(Workspace).order_by(Workspace.id.asc())
    if current_user.role != "admin":
        stmt = stmt.join(WorkspaceMember).where(WorkspaceMember.user_id == current_user.id)
    return list(db.scalars(stmt).all())


@router.post(
    "/workspaces",
    response_model=schemas.WorkspaceRead,
    status_code=201,
    dependencies=[Depends(require_admin)],
    summary="创建工作空间",
)
def create_workspace(
    payload: schemas.WorkspaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Workspace:
    workspace = Workspace(**payload.model_dump())
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    services.ensure_workspace_member(db, workspace.id, current_user.id, "owner")
    return workspace


@router.put(
    "/workspaces/{workspace_id}",
    response_model=schemas.WorkspaceRead,
    dependencies=[Depends(require_admin)],
    summary="更新工作空间",
)
def update_workspace(
    workspace_id: int,
    payload: schemas.WorkspaceUpdate,
    db: Session = Depends(get_db),
) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    duplicate = db.scalar(
        select(Workspace.id).where(Workspace.name == payload.name, Workspace.id != workspace_id)
    )
    if duplicate is not None:
        raise HTTPException(status_code=400, detail="工作空间名称已存在")
    workspace.name = payload.name
    workspace.description = payload.description
    db.commit()
    db.refresh(workspace)
    return workspace


@router.delete(
    "/workspaces/{workspace_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
    summary="删除工作空间",
)
def delete_workspace(workspace_id: int, db: Session = Depends(get_db)) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    has_projects = db.scalar(select(Project.id).where(Project.workspace_id == workspace_id).limit(1))
    if has_projects is not None:
        raise HTTPException(status_code=400, detail="该工作空间下仍存在关联项目，请先迁移或删除项目")
    db.execute(delete(AIModelConfig).where(AIModelConfig.workspace_id == workspace_id))
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id))
    db.delete(workspace)
    db.commit()


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=list[schemas.WorkspaceMemberRead],
    dependencies=[Depends(require_admin)],
    summary="获取工作空间成员列表",
)
def list_workspace_members(workspace_id: int, db: Session = Depends(get_db)) -> list[schemas.WorkspaceMemberRead]:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    members = list(
        db.scalars(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id).order_by(WorkspaceMember.id.asc())
        ).all()
    )
    user_ids = {member.user_id for member in members if member.user_id is not None}
    users_by_id = (
        {user.id: user for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
        if user_ids
        else {}
    )
    return [
        schemas.WorkspaceMemberRead(
            id=member.id,
            workspace_id=member.workspace_id,
            user_id=member.user_id,
            username=users_by_id[member.user_id].username if member.user_id in users_by_id else None,
            display_name=users_by_id[member.user_id].display_name if member.user_id in users_by_id else None,
            role=member.role,
            created_at=member.created_at,
        )
        for member in members
    ]


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=schemas.WorkspaceMemberRead,
    status_code=201,
    dependencies=[Depends(require_admin)],
    summary="添加或更新工作空间成员",
)
def add_workspace_member(
    workspace_id: int,
    payload: schemas.WorkspaceMemberCreate,
    db: Session = Depends(get_db),
) -> schemas.WorkspaceMemberRead:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="工作空间不存在")
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    existing = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id
    ))
    if existing is not None:
        _ensure_workspace_owner_guard(db, existing, next_role=payload.role)
    member = services.ensure_workspace_member(db, workspace_id, payload.user_id, payload.role)
    return schemas.WorkspaceMemberRead(
        id=member.id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        username=user.username,
        display_name=user.display_name,
        role=member.role,
        created_at=member.created_at,
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{member_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
    summary="移除工作空间成员",
)
def delete_workspace_member(workspace_id: int, member_id: int, db: Session = Depends(get_db)) -> None:
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    _ensure_workspace_owner_guard(db, member, deleting=True)
    db.delete(member)
    db.commit()


@router.put(
    "/workspaces/{workspace_id}/members/{member_id}",
    response_model=schemas.WorkspaceMemberRead,
    dependencies=[Depends(require_admin)],
    summary="修改工作空间成员角色",
)
def update_workspace_member(
    workspace_id: int,
    member_id: int,
    payload: schemas.WorkspaceMemberUpdate,
    db: Session = Depends(get_db),
) -> schemas.WorkspaceMemberRead:
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    _ensure_workspace_owner_guard(db, member, next_role=payload.role)
    member.role = payload.role
    db.commit()
    db.refresh(member)
    user = db.get(User, member.user_id)
    return schemas.WorkspaceMemberRead(
        id=member.id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        username=user.username if user else None,
        display_name=user.display_name if user else None,
        role=member.role,
        created_at=member.created_at,
    )
