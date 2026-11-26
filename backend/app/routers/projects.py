"""项目管理、成员权限、变量池与通知设置路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import schemas, services, notifications
from app.core.database import get_db
from app.models import (
    APICase,
    Activity,
    CaseChangeHistory,
    CaseGenerationArtifact,
    CaseGenerationAttempt,
    CaseGenerationJob,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
    CaseGenerationV2Job,
    Comment,
    Defect,
    DefectCaseLink,
    DefectRecord,
    DefectRunLink,
    Environment,
    ExecutionArtifact,
    ExecutionLog,
    ExecutionStep,
    Iteration,
    PerformanceCase,
    Project,
    ProjectMember,
    ProjectNotificationSetting,
    ProjectTask,
    Requirement,
    RequirementCaseLink,
    TestPlan,
    TestPlanCase,
    TestPlanRun,
    TestRun,
    UIBatchRun,
    UICase,
    User,
    Workspace,
    WorkspaceMember,
)
from app.permissions import project_role_allows
from app.deps.auth import (
    _accessible_project_ids,
    _guard_project_member_change,
    _project_has_members,
    _require_project_access,
    _require_project_member,
    _require_workspace_access,
    _resolve_project_role,
    _workspace_ids_for_user,
    get_current_user,
    require_admin,
    require_tester,
)

router = APIRouter(tags=["projects"])


def _project_member_to_read(db: Session, member: ProjectMember) -> schemas.ProjectMemberRead:
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


@router.get(
    "/projects/{project_id}/members",
    response_model=list[schemas.ProjectMemberRead],
    summary="获取项目成员列表",
)
def list_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.ProjectMemberRead]:
    project = _require_project_access(db, current_user, db.get(Project, project_id))
    members = list(
        db.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == project.id)
            .order_by(ProjectMember.id.asc())
        ).all()
    )
    return [_project_member_to_read(db, member) for member in members]


@router.get("/projects/{project_id}/member-candidates", response_model=list[schemas.ProjectMemberCandidate], summary="获取可添加为项目成员的候选人")
def list_project_member_candidates(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    stmt = select(User).order_by(User.username)
    if current_user.role != "admin":
        if project.workspace_id is None:
            return []
        stmt = stmt.join(WorkspaceMember, WorkspaceMember.user_id == User.id).where(
            WorkspaceMember.workspace_id == project.workspace_id
        )
    return list(db.scalars(stmt))


@router.post(
    "/projects/{project_id}/members",
    response_model=schemas.ProjectMemberRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="添加项目成员",
)
def add_project_member(
    project_id: int,
    payload: schemas.ProjectMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ProjectMemberRead:
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not _project_has_members(db, project.id):
        owner_uid = project.created_by or current_user.id
        # A project creator already has implicit owner access. Keep an
        # explicit membership row for ordinary creators so switching a
        # project into member-isolation mode cannot lock them out, but avoid
        # duplicating the global admin as an explicit owner.
        creator_is_global_admin = owner_uid == current_user.id and current_user.role == "admin"
        if owner_uid and owner_uid != payload.user_id and not creator_is_global_admin:
            services.ensure_project_member(db, project.id, owner_uid, "owner")
    existing = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == payload.user_id))
    _guard_project_member_change(db, current_user, project, existing, payload.role)
    member = services.ensure_project_member(db, project.id, payload.user_id, payload.role)
    return _project_member_to_read(db, member)


@router.put(
    "/projects/{project_id}/members/{member_id}",
    response_model=schemas.ProjectMemberRead,
    dependencies=[Depends(require_tester)],
    summary="修改项目成员角色",
)
def update_project_member(
    project_id: int,
    member_id: int,
    payload: schemas.ProjectMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ProjectMemberRead:
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    _guard_project_member_change(db, current_user, project, member, payload.role)
    member.role = payload.role
    db.commit()
    db.refresh(member)
    return _project_member_to_read(db, member)


@router.delete(
    "/projects/{project_id}/members/{member_id}",
    status_code=204,
    dependencies=[Depends(require_tester)],
    summary="移除项目成员",
)
def delete_project_member(
    project_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    member = db.get(ProjectMember, member_id)
    if member is None or member.project_id != project_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    _guard_project_member_change(db, current_user, project, member, None)
    db.delete(member)
    db.commit()


@router.get("/projects", response_model=list[schemas.ProjectRead], summary="获取可见项目列表")
def list_projects(
    workspace_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Project]:
    stmt = select(Project).order_by(Project.id.asc())
    if workspace_id:
        _require_workspace_access(db, current_user, workspace_id)
        stmt = stmt.where(Project.workspace_id == workspace_id)
    if current_user.role != "admin":
        accessible_ids = _accessible_project_ids(db, current_user)
        if not accessible_ids:
            return []
        stmt = stmt.where(Project.id.in_(accessible_ids))
    return list(db.scalars(stmt).all())


@router.post(
    "/projects",
    response_model=schemas.ProjectRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建项目",
)
def create_project(
    payload: schemas.ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    data = payload.model_dump()
    if data.get("workspace_id") is None:
        if current_user.role == "admin":
            workspace = services.ensure_default_workspace(db)
        else:
            workspace_ids = _workspace_ids_for_user(db, current_user)
            if not workspace_ids:
                raise HTTPException(status_code=403, detail="未加入任何工作空间")
            workspace = db.get(Workspace, workspace_ids[0])
        data["workspace_id"] = workspace.id
    else:
        workspace = db.get(Workspace, data["workspace_id"])
        if workspace is None:
            raise HTTPException(status_code=404, detail="工作空间不存在")
        _require_workspace_access(db, current_user, workspace.id)
    project = Project(**data, created_by=current_user.id, updated_by=current_user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.put(
    "/projects/{project_id}",
    response_model=schemas.ProjectRead,
    dependencies=[Depends(require_tester)],
    summary="更新项目信息",
)
def update_project(
    project_id: int,
    payload: schemas.ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    data = payload.model_dump(exclude_unset=True)
    if "workspace_id" in data and data["workspace_id"] is not None:
        workspace = db.get(Workspace, data["workspace_id"])
        if workspace is None:
            raise HTTPException(status_code=404, detail="工作空间不存在")
        _require_workspace_access(db, current_user, workspace.id)
    for key, value in data.items():
        if value is not None or key == "description":
            setattr(project, key, value)
    project.updated_by = current_user.id
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除项目及关联数据")
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    plan_ids = list(db.scalars(select(TestPlan.id).where(TestPlan.project_id == project_id)).all())
    if plan_ids:
        db.execute(delete(TestPlanCase).where(TestPlanCase.plan_id.in_(plan_ids)))

    run_ids = list(db.scalars(select(TestRun.id).where(TestRun.project_id == project_id)).all())
    if run_ids:
        db.execute(delete(ExecutionArtifact).where(ExecutionArtifact.run_id.in_(run_ids)))
        db.execute(delete(ExecutionLog).where(ExecutionLog.run_id.in_(run_ids)))
        db.execute(delete(ExecutionStep).where(ExecutionStep.run_id.in_(run_ids)))
        db.execute(delete(DefectRunLink).where(DefectRunLink.test_run_id.in_(run_ids)))

    defect_ids = list(db.scalars(select(Defect.id).where(Defect.project_id == project_id)).all())
    if defect_ids:
        db.execute(delete(DefectRunLink).where(DefectRunLink.defect_id.in_(defect_ids)))
        db.execute(delete(DefectCaseLink).where(DefectCaseLink.defect_id.in_(defect_ids)))

    req_ids = list(db.scalars(select(Requirement.id).where(Requirement.project_id == project_id)).all())
    if req_ids:
        db.execute(delete(RequirementCaseLink).where(RequirementCaseLink.requirement_id.in_(req_ids)))

    job_v1_ids = list(db.scalars(select(CaseGenerationJob.id).where(CaseGenerationJob.project_id == project_id)).all())
    if job_v1_ids:
        db.execute(delete(CaseGenerationArtifact).where(CaseGenerationArtifact.job_id.in_(job_v1_ids)))
        db.execute(delete(CaseGenerationAttempt).where(CaseGenerationAttempt.job_id.in_(job_v1_ids)))
        db.execute(delete(CaseGenerationJob).where(CaseGenerationJob.id.in_(job_v1_ids)))

    job_v2_ids = list(db.scalars(select(CaseGenerationV2Job.id).where(CaseGenerationV2Job.project_id == project_id)).all())
    if job_v2_ids:
        db.execute(delete(CaseGenerationV2Artifact).where(CaseGenerationV2Artifact.job_id.in_(job_v2_ids)))
        db.execute(delete(CaseGenerationV2Attempt).where(CaseGenerationV2Attempt.job_id.in_(job_v2_ids)))
        db.execute(delete(CaseGenerationV2Job).where(CaseGenerationV2Job.id.in_(job_v2_ids)))

    db.execute(delete(Comment).where(Comment.project_id == project_id))
    db.execute(delete(Activity).where(Activity.project_id == project_id))
    db.execute(delete(Defect).where(Defect.project_id == project_id))
    db.execute(delete(DefectRecord).where(DefectRecord.project_id == project_id))
    db.execute(delete(ProjectTask).where(ProjectTask.project_id == project_id))
    db.execute(delete(Requirement).where(Requirement.project_id == project_id))
    db.execute(delete(Iteration).where(Iteration.project_id == project_id))
    db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
    db.execute(delete(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == project_id))
    db.execute(delete(CaseChangeHistory).where(CaseChangeHistory.project_id == project_id))
    db.execute(delete(TestRun).where(TestRun.project_id == project_id))
    db.execute(delete(UIBatchRun).where(UIBatchRun.project_id == project_id))
    db.execute(delete(TestPlanRun).where(TestPlanRun.project_id == project_id))
    db.execute(delete(TestPlan).where(TestPlan.project_id == project_id))
    db.execute(delete(APICase).where(APICase.project_id == project_id))
    db.execute(delete(UICase).where(UICase.project_id == project_id))
    db.execute(delete(PerformanceCase).where(PerformanceCase.project_id == project_id))
    db.execute(delete(Environment).where(Environment.project_id == project_id))
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()


@router.get(
    "/projects/{project_id}/variables",
    dependencies=[Depends(require_tester)],
    summary="获取项目全局变量池",
)
def get_project_variables(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """获取项目级全局变量池。"""
    project = _require_project_access(db, current_user, db.get(Project, project_id))
    return {"project_id": project.id, "variables_json": project.variables_json or {}}


@router.put(
    "/projects/{project_id}/variables",
    dependencies=[Depends(require_tester)],
    summary="更新项目全局变量池",
)
def update_project_variables(
    project_id: int,
    payload: schemas.ProjectVariablesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """更新项目级全局变量池。"""
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    project.variables_json = payload.variables_json or {}
    project.updated_by = current_user.id
    db.commit()
    return {"project_id": project.id, "variables_json": project.variables_json or {}}


@router.get(
    "/projects/{project_id}/notification-setting",
    response_model=schemas.NotificationSettingRead,
    summary="获取项目 Webhook 通知设置",
)
def get_project_notification_setting(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.NotificationSettingRead:
    project = _require_project_access(db, current_user, db.get(Project, project_id))
    setting = db.scalar(
        select(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == project_id)
    )
    if setting is None:
        return schemas.NotificationSettingRead(project_id=project_id)
    return schemas.NotificationSettingRead(
        project_id=setting.project_id,
        enabled=setting.enabled,
        channel_type=setting.channel_type,
        webhook_url=setting.webhook_url if project_role_allows(_resolve_project_role(db, current_user, project), "manager") else None,
        secret_configured=bool(setting.secret),
        notify_on=setting.notify_on,
        updated_at=setting.updated_at,
    )


def _upsert_notification_setting(
    db: Session, project_id: int, payload: schemas.NotificationSettingUpdate
) -> ProjectNotificationSetting:
    setting = db.scalar(
        select(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == project_id)
    )
    if setting is None:
        setting = ProjectNotificationSetting(project_id=project_id)
        db.add(setting)
    setting.enabled = payload.enabled
    setting.channel_type = payload.channel_type
    setting.webhook_url = payload.webhook_url
    if payload.secret is not None and payload.secret != "":
        setting.secret = payload.secret
    setting.notify_on = payload.notify_on
    db.commit()
    db.refresh(setting)
    return setting


@router.put(
    "/projects/{project_id}/notification-setting",
    response_model=schemas.NotificationSettingRead,
    dependencies=[Depends(require_tester)],
    summary="更新项目 Webhook 通知设置",
)
def update_project_notification_setting(
    project_id: int,
    payload: schemas.NotificationSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectNotificationSetting:
    _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    setting = _upsert_notification_setting(db, project_id, payload)
    return schemas.NotificationSettingRead(
        project_id=setting.project_id,
        enabled=setting.enabled,
        channel_type=setting.channel_type,
        webhook_url=setting.webhook_url,
        secret_configured=bool(setting.secret),
        notify_on=setting.notify_on,
        updated_at=setting.updated_at,
    )


@router.post(
    "/projects/{project_id}/notification-setting/test",
    dependencies=[Depends(require_tester)],
    summary="发送测试通知消息",
)
def test_project_notification_setting(
    project_id: int,
    payload: schemas.NotificationSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = _require_project_member(db, current_user, db.get(Project, project_id), "manager")
    if not payload.webhook_url:
        raise HTTPException(status_code=400, detail="请先填写 Webhook 地址")
    saved = db.scalar(select(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == project_id))
    secret = payload.secret
    if secret is None and saved and saved.webhook_url == payload.webhook_url and saved.channel_type == payload.channel_type:
        secret = saved.secret
    probe = ProjectNotificationSetting(
        project_id=project_id,
        enabled=True,
        channel_type=payload.channel_type,
        webhook_url=payload.webhook_url,
        secret=secret,
        notify_on=payload.notify_on,
    )
    text = f"【测试平台】这是一条测试消息\n项目：{project.name}\n若收到本消息，说明通知配置正确。"
    success = notifications.send_webhook_message(probe, text)
    return {"success": success, "message": "发送成功" if success else "发送失败，请检查 Webhook 地址与密钥"}
