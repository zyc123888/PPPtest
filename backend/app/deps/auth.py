"""共享鉴权依赖、权限守卫、用户序列化与异步任务派发。"""

import os

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.config import settings
from app.core.database import get_db
from app.core.observability import bind_context, reset_context, user_id_var
from app.models import (
    Project,
    ProjectMember,
    User,
    Workspace,
    WorkspaceMember,
)
from app.permissions import PROJECT_ROLE_RANK, project_role_allows


auth_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    browser_session: str | None = Cookie(default=None, alias="tp_browser_session"),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials and credentials.credentials else None
    # Native resources such as <img> cannot attach the SPA's Bearer header.
    # Only read-only requests may fall back to the HttpOnly browser session;
    # mutations continue to require an explicit Authorization header.
    if token is None and request.method in {"GET", "HEAD"}:
        token = browser_session
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    user = services.get_user_by_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    request.state.user_id = user.id
    user_id_var.set(user.id)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user


def require_tester(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {"admin", "tester"}:
        raise HTTPException(status_code=403, detail="需要测试执行权限")
    return current_user


def _workspace_ids_for_user(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(db.scalars(select(Workspace.id)).all())
    return list(
        db.scalars(
            select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
        ).all()
    )


def _can_access_workspace(db: Session, user: User, workspace_id: int) -> bool:
    if user.role == "admin":
        return True
    return db.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    ) is not None


def _require_workspace_access(db: Session, user: User, workspace_id: int) -> None:
    if not _can_access_workspace(db, user, workspace_id):
        raise HTTPException(status_code=403, detail="无权访问该工作空间")


def _ensure_workspace_owner_guard(
    db: Session,
    member: WorkspaceMember,
    next_role: str | None = None,
    deleting: bool = False,
) -> None:
    current_is_owner = member.role == "owner"
    remains_owner = (next_role or member.role) == "owner" and not deleting
    if not current_is_owner or remains_owner:
        return
    owner_ids = list(db.scalars(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == member.workspace_id,
            WorkspaceMember.role == "owner",
        ).order_by(WorkspaceMember.id).with_for_update()
    ))
    if member.id in owner_ids and len(owner_ids) <= 1:
        raise HTTPException(status_code=400, detail="工作空间至少需要保留一个 Owner")


def _project_has_members(db: Session, project_id: int) -> bool:
    """项目是否配置了显式成员（一旦配置即进入项目级隔离模式）。"""
    return db.scalar(
        select(ProjectMember.id).where(ProjectMember.project_id == project_id).limit(1)
    ) is not None


def _is_project_member(db: Session, user: User, project_id: int) -> bool:
    return db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    ) is not None


def _can_access_project(db: Session, user: User, project: Project) -> bool:
    """项目级数据隔离判定。

    - admin 或项目创建人拥有全部权限；
    - 显式项目成员始终可访问；
    - 项目一旦配置显式成员则仅成员可访问（隔离模式）；
    - 未配置成员时回退到工作空间级可见性（向后兼容旧行为）。
    """
    if user.role == "admin":
        return True
    if project.created_by is not None and project.created_by == user.id:
        return True
    if _is_project_member(db, user, project.id):
        return True
    if _project_has_members(db, project.id):
        return False
    return _can_access_workspace(db, user, project.workspace_id)


def _require_project_access(db: Session, user: User, project: Project | None) -> Project:
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not _can_access_project(db, user, project):
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return project


def _resolve_project_role(db: Session, user: User, project: Project) -> str:
    if user.role == "admin" or (project.created_by is not None and project.created_by == user.id):
        return "owner"
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
    return member.role if member else "viewer"


def _require_project_member(db: Session, user: User, project: Project | None, minimum_role: str = "member") -> Project:
    project = _require_project_access(db, user, project)
    if not project_role_allows(_resolve_project_role(db, user, project), minimum_role):
        raise HTTPException(status_code=403, detail="项目内权限不足")
    return project


def _guard_project_member_change(db: Session, user: User, project: Project, member: ProjectMember | None, next_role: str | None) -> None:
    if next_role is not None and next_role not in PROJECT_ROLE_RANK:
        raise HTTPException(status_code=400, detail="无效的项目角色")
    if user.role != "admin" and ((member and member.role == "owner") or next_role == "owner"):
        _require_project_member(db, user, project, "owner")
    if member and member.role == "owner" and next_role != "owner":
        owner_ids = list(db.scalars(
            select(ProjectMember.id)
            .where(ProjectMember.project_id == project.id, ProjectMember.role == "owner")
            .order_by(ProjectMember.id)
            .with_for_update()
        ))
        if member.id in owner_ids and len(owner_ids) <= 1:
            raise HTTPException(status_code=400, detail="项目至少需要保留一个 Owner")


def _accessible_project_ids(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(db.scalars(select(Project.id)).all())
    # 用户显式加入的项目（隔离授权）与自己创建的项目
    member_project_ids = set(
        db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)).all()
    )
    created_project_ids = set(
        db.scalars(select(Project.id).where(Project.created_by == user.id)).all()
    )
    # 所有配置了显式成员的项目（处于隔离模式，非成员不可见）
    restricted_project_ids = set(db.scalars(select(ProjectMember.project_id).distinct()).all())
    # 用户所在工作空间下的项目
    workspace_ids = _workspace_ids_for_user(db, user)
    workspace_project_ids: set[int] = set()
    if workspace_ids:
        workspace_project_ids = set(
            db.scalars(select(Project.id).where(Project.workspace_id.in_(workspace_ids))).all()
        )
    accessible = member_project_ids | created_project_ids | (workspace_project_ids - restricted_project_ids)
    return list(accessible)


def _workspace_names_for_user(db: Session, user_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Workspace.name)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.name.asc())
        ).all()
    )


def _workspace_memberships_for_user(db: Session, user_id: int) -> list[schemas.UserWorkspaceMembership]:
    rows = db.execute(
        select(WorkspaceMember.id, WorkspaceMember.workspace_id, Workspace.name, WorkspaceMember.role)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.name.asc())
    ).all()
    return [
        schemas.UserWorkspaceMembership(
            member_id=member_id,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            role=role,
        )
        for member_id, workspace_id, workspace_name, role in rows
    ]


def _serialize_user(db: Session, user: User) -> schemas.UserRead:
    payload = schemas.UserRead.model_validate(user).model_dump()
    payload["workspaces"] = _workspace_names_for_user(db, user.id)
    payload["workspace_memberships"] = _workspace_memberships_for_user(db, user.id)
    return schemas.UserRead(**payload)


def _dispatch_task_or_run_inline(
    task_func,
    record_id: int,
    *task_args,
    background_inline: bool = False,
    queue: str | None = None,
    context_user_id: int | None = None,
) -> tuple[str | None, bool]:
    context_tokens = bind_context(user_id=context_user_id) if context_user_id is not None else {}
    if (
        os.getenv("PYTEST_CURRENT_TEST")
        or settings.backend_internal_url.startswith("http://testserver")
    ):
        try:
            task_func(record_id, *task_args)
            return None, True
        finally:
            reset_context(context_tokens)
    try:
        if queue:
            task = task_func.apply_async(args=(record_id, *task_args), queue=queue)
        else:
            task = task_func.delay(record_id, *task_args)
        return task.id, False
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"任务队列暂不可用，请稍后重试：{exc}") from exc
    finally:
        reset_context(context_tokens)
