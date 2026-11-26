"""UI 自动化用例管理与 AI 草稿生成路由。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import (
    String,
    cast,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Session

from app import schemas
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    AIModelConfig,
    Project,
    TestPlanCase,
    TestRun,
    UICase,
    User,
)
from app.tasks.case_generation import _normalize_model_base_url
from app.timeutil import utc_now_naive
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_project_member,
    get_current_user,
    require_admin,
    require_tester,
)
from app.domain.cases import (
    _bump_version,
    _ensure_case_defaults,
    _initial_case_data,
    _reject_case_project_reassignment,
)
from app import ui_case_ai
from app.domain import cases as cases_domain

router = APIRouter(tags=["ui-cases"])


@router.get("/ui-cases", response_model=schemas.UICasePage | list[schemas.UICaseRead], summary="获取 UI 用例列表")
def list_ui_cases(
    project_id: int | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = None,
    priority: str | None = None,
    review_status: str | None = None,
    folder: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICasePage | list[UICase]:
    # UI 用例列表按最新创建顺序展示，避免新建用例落到后续分页而不可见。
    stmt = select(UICase).order_by(UICase.id.desc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(UICase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.UICasePage(items=[], total=0) if page is not None else []
        stmt = stmt.where(UICase.project_id.in_(project_ids))
    if status:
        stmt = stmt.where(UICase.status == status.strip().upper())
    if priority:
        stmt = stmt.where(UICase.priority == priority.strip().upper())
    if review_status:
        stmt = stmt.where(UICase.review_status == review_status.strip().upper())
    if folder:
        normalized_folder = folder.strip().strip("/")
        if normalized_folder == "__ungrouped__":
            stmt = stmt.where(or_(UICase.folder_path.is_(None), UICase.folder_path == ""))
        elif normalized_folder:
            stmt = stmt.where(
                or_(UICase.folder_path == normalized_folder, UICase.folder_path.like(f"{normalized_folder}/%"))
            )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                UICase.name.like(pattern),
                UICase.folder_path.like(pattern),
                UICase.target_url.like(pattern),
                cast(UICase.tags_json, String).like(pattern),
            )
        )
    if page is not None:
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        items = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
        for item in items:
            _ensure_case_defaults(item)
        return schemas.UICasePage(
            items=[schemas.UICaseRead.model_validate(item) for item in items],
            total=total,
        )
    items = list(db.scalars(stmt).all())
    for item in items:
        _ensure_case_defaults(item)
    return items


@router.post(
    "/ui-cases",
    response_model=schemas.UICaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建 UI 用例",
)
def create_ui_case(
    payload: schemas.UICaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UICase:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    ui_case = UICase(**_initial_case_data(payload), created_by=current_user.id, updated_by=current_user.id)
    db.add(ui_case)
    db.commit()
    db.refresh(ui_case)
    cases_domain._record_case_history(db, case_type="UI", case=ui_case, action="CREATE", changed_by=current_user.id, summary="创建 UI 用例")
    db.commit()
    return ui_case


@router.post(
    "/ui-cases/ai/generate",
    response_model=schemas.UICaseAIGenerateResponse,
    dependencies=[Depends(require_tester)],
    summary="AI 辅助生成 UI 用例草稿",
)
async def generate_ui_case_with_ai(
    payload: schemas.UICaseAIGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICaseAIGenerateResponse:
    project = _require_project_access(db, current_user, db.get(Project, payload.project_id))
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == project.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="请先配置该工作空间的模型连接信息")
    model = (model_config.model or settings.case_gen_default_model).strip()
    api_key = model_config.api_key
    base_url = _normalize_model_base_url(model, model_config.base_url, api_key)
    try:
        return await ui_case_ai.generate_ui_case_draft(
            payload,
            project_name=project.name,
            project_base_url=project.base_url,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _ui_case_scope_conditions(db: Session, current_user: User, project_id: int | None) -> list | None:
    conditions: list = []
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        conditions.append(UICase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return None
        conditions.append(UICase.project_id.in_(project_ids))
    return conditions


@router.get("/ui-cases/folders", response_model=schemas.UICaseFolderTree, summary="获取 UI 用例目录树")
def get_ui_case_folder_tree(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICaseFolderTree:
    conditions = _ui_case_scope_conditions(db, current_user, project_id)
    if conditions is None:
        return schemas.UICaseFolderTree()
    stmt = select(UICase.folder_path, func.count(UICase.id)).group_by(UICase.folder_path)
    for condition in conditions:
        stmt = stmt.where(condition)
    rows = db.execute(stmt).all()

    total = 0
    ungrouped = 0
    nodes: dict[str, schemas.UICaseFolderNode] = {}
    roots: list[schemas.UICaseFolderNode] = []

    def ensure_node(path: str) -> schemas.UICaseFolderNode:
        node = nodes.get(path)
        if node is not None:
            return node
        node = schemas.UICaseFolderNode(path=path, name=path.rsplit("/", 1)[-1])
        nodes[path] = node
        if "/" in path:
            ensure_node(path.rsplit("/", 1)[0]).children.append(node)
        else:
            roots.append(node)
        return node

    for folder_path, count in rows:
        total += count
        normalized = (folder_path or "").strip().strip("/")
        if not normalized:
            ungrouped += count
            continue
        ensure_node(normalized)
        parts = normalized.split("/")
        for index in range(1, len(parts) + 1):
            ensure_node("/".join(parts[:index])).case_count += count

    def sort_nodes(items: list[schemas.UICaseFolderNode]) -> None:
        items.sort(key=lambda node: node.name)
        for child in items:
            sort_nodes(child.children)

    sort_nodes(roots)
    return schemas.UICaseFolderTree(total=total, ungrouped=ungrouped, folders=roots)


@router.post(
    "/ui-cases/folders/rename",
    response_model=schemas.UICaseBatchResult,
    dependencies=[Depends(require_tester)],
    summary="重命名 UI 用例目录",
)
def rename_ui_case_folder(
    payload: schemas.UICaseFolderRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICaseBatchResult:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    old_path = payload.old_path.strip().strip("/")
    new_path = payload.new_path.strip().strip("/")
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="目录路径不能为空")
    if old_path == new_path:
        return schemas.UICaseBatchResult(affected=0)
    cases = list(
        db.scalars(
            select(UICase).where(
                UICase.project_id == payload.project_id,
                or_(UICase.folder_path == old_path, UICase.folder_path.like(f"{old_path}/%")),
            )
        ).all()
    )
    for case in cases:
        current = case.folder_path or ""
        case.folder_path = new_path + current[len(old_path):]
        case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type="UI",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"目录重命名 {old_path} → {new_path}",
        )
    db.commit()
    return schemas.UICaseBatchResult(affected=len(cases))


@router.get("/ui-cases/stats", response_model=schemas.UICaseStats, summary="获取 UI 用例统计信息")
def get_ui_case_stats(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICaseStats:
    conditions = _ui_case_scope_conditions(db, current_user, project_id)
    if conditions is None:
        return schemas.UICaseStats()
    base = select(func.count(UICase.id))
    for condition in conditions:
        base = base.where(condition)
    total = db.scalar(base) or 0
    active = db.scalar(base.where(UICase.status == "ACTIVE")) or 0
    approved = db.scalar(base.where(UICase.review_status == "APPROVED")) or 0

    runs_stmt = select(TestRun.status).where(TestRun.case_type == "UI")
    if project_id:
        runs_stmt = runs_stmt.where(TestRun.project_id == project_id)
    elif current_user.role != "admin":
        runs_stmt = runs_stmt.where(TestRun.project_id.in_(_accessible_project_ids(db, current_user)))
    statuses = list(db.scalars(runs_stmt.order_by(TestRun.id.desc()).limit(50)).all())
    finished = [item for item in statuses if item in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}]
    rate = None
    if finished:
        rate = round(sum(1 for item in finished if item == "SUCCESS") / len(finished), 4)
    return schemas.UICaseStats(total=total, active=active, approved=approved, recent_success_rate=rate)


@router.put(
    "/ui-cases/batch",
    response_model=schemas.UICaseBatchResult,
    dependencies=[Depends(require_tester)],
    summary="批量更新 UI 用例",
)
def batch_update_ui_cases(
    payload: schemas.UICaseBatchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICaseBatchResult:
    patch = payload.patch.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(UICase).where(UICase.id.in_(case_ids))).all())
    if len(cases) != len(case_ids):
        raise HTTPException(status_code=404, detail="部分用例不存在")
    checked_projects: set[int] = set()
    for case in cases:
        if case.project_id not in checked_projects:
            _require_project_access(db, current_user, db.get(Project, case.project_id))
            checked_projects.add(case.project_id)
    for case in cases:
        for key, value in patch.items():
            setattr(case, key, value)
        case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type="UI",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"批量更新属性：{', '.join(sorted(patch.keys()))}",
        )
    db.commit()
    return schemas.UICaseBatchResult(affected=len(cases))


@router.delete(
    "/ui-cases/batch",
    response_model=schemas.UICaseBatchResult,
    dependencies=[Depends(require_admin)],
    summary="批量删除 UI 用例",
)
def batch_delete_ui_cases(
    payload: schemas.UICaseBatchDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UICaseBatchResult:
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(UICase).where(UICase.id.in_(case_ids))).all())
    if len(cases) != len(case_ids):
        raise HTTPException(status_code=404, detail="部分用例不存在")
    for case in cases:
        cases_domain._record_case_history(
            db,
            case_type="UI",
            case=case,
            action="DELETE",
            changed_by=current_user.id,
            summary="批量删除 UI 用例",
        )
        db.execute(
            delete(TestPlanCase).where(TestPlanCase.case_type == "UI", TestPlanCase.case_id == case.id)
        )
        db.delete(case)
    db.commit()
    return schemas.UICaseBatchResult(affected=len(cases))


@router.get("/ui-cases/{case_id}", response_model=schemas.UICaseRead, summary="获取 UI 用例详情")
def get_ui_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UICase:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    _require_project_access(db, current_user, db.get(Project, ui_case.project_id))
    _ensure_case_defaults(ui_case)
    return ui_case


@router.put(
    "/ui-cases/{case_id}",
    response_model=schemas.UICaseRead,
    dependencies=[Depends(require_tester)],
    summary="更新 UI 用例",
)
def update_ui_case(
    case_id: int,
    payload: schemas.UICaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UICase:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    _require_project_access(db, current_user, db.get(Project, ui_case.project_id))
    _reject_case_project_reassignment(ui_case.project_id, payload.project_id)
    original_review_status = (ui_case.review_status or "DRAFT").upper()
    original_signature = (
        ui_case.name,
        ui_case.folder_path,
        ui_case.target_url,
        ui_case.priority,
        ui_case.status,
        tuple(ui_case.tags_json or []),
        ui_case.expect_text,
        ui_case.steps_json,
        ui_case.assertions_json,
        ui_case.generation_mode,
        ui_case.execution_mode,
        ui_case.engine,
        ui_case.self_heal_enabled,
        ui_case.max_agent_steps,
        ui_case.allowed_origins_json,
        ui_case.prohibited_actions_json,
        ui_case.ai_goal,
        ui_case.skill_name,
        ui_case.skill_version,
        ui_case.generation_meta_json,
    )
    for key, value in payload.model_dump(exclude={"project_id", "review_status", "review_note"}).items():
        setattr(ui_case, key, value)
    new_signature = (
        ui_case.name,
        ui_case.folder_path,
        ui_case.target_url,
        ui_case.priority,
        ui_case.status,
        tuple(ui_case.tags_json or []),
        ui_case.expect_text,
        ui_case.steps_json,
        ui_case.assertions_json,
        ui_case.generation_mode,
        ui_case.execution_mode,
        ui_case.engine,
        ui_case.self_heal_enabled,
        ui_case.max_agent_steps,
        ui_case.allowed_origins_json,
        ui_case.prohibited_actions_json,
        ui_case.ai_goal,
        ui_case.skill_name,
        ui_case.skill_version,
        ui_case.generation_meta_json,
    )
    if new_signature != original_signature:
        ui_case.version_no = _bump_version(ui_case.version_no)
        if original_review_status in {"APPROVED", "IN_REVIEW"}:
            ui_case.review_status = "DRAFT"
            ui_case.reviewed_by = None
            ui_case.reviewed_at = None
            ui_case.submitted_review_at = None
    ui_case.updated_by = current_user.id
    cases_domain._record_case_history(db, case_type="UI", case=ui_case, action="UPDATE", changed_by=current_user.id, summary="更新 UI 用例")
    db.commit()
    db.refresh(ui_case)
    return ui_case


@router.delete("/ui-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除 UI 用例")
def delete_ui_case(case_id: int, db: Session = Depends(get_db)) -> None:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")

    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "UI", TestPlanCase.case_id == case_id)
    )
    db.delete(ui_case)
    db.commit()


@router.post(
    "/ui-cases/{case_id}/review/submit",
    response_model=schemas.UICaseRead,
    dependencies=[Depends(require_tester)],
    summary="提交 UI 用例评审",
)
def submit_ui_case_review(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UICase:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    _require_project_access(db, current_user, db.get(Project, ui_case.project_id))
    _ensure_case_defaults(ui_case)
    current_status = (ui_case.review_status or "DRAFT").upper()
    if current_status not in {"DRAFT", "REJECTED"}:
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不能提交评审")
    ui_case.review_status = "IN_REVIEW"
    ui_case.submitted_review_at = utc_now_naive()
    ui_case.reviewed_by = None
    ui_case.reviewed_at = None
    ui_case.updated_by = current_user.id
    cases_domain._record_case_history(db, case_type="UI", case=ui_case, action="REVIEW", changed_by=current_user.id, summary="提交评审")
    db.commit()
    db.refresh(ui_case)
    return ui_case


@router.post(
    "/ui-cases/{case_id}/review/decide",
    response_model=schemas.UICaseRead,
    dependencies=[Depends(require_tester)],
    summary="审批 UI 用例评审",
)
def decide_ui_case_review(
    case_id: int,
    payload: schemas.UICaseReviewDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UICase:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    if ui_case.created_by is not None and ui_case.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
    _require_project_member(db, current_user, db.get(Project, ui_case.project_id))
    _ensure_case_defaults(ui_case)
    current_status = (ui_case.review_status or "DRAFT").upper()
    if current_status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不在评审中")
    ui_case.review_status = payload.result
    ui_case.review_note = payload.note
    ui_case.reviewed_by = current_user.id
    ui_case.reviewed_at = utc_now_naive()
    ui_case.updated_by = current_user.id
    cases_domain._record_case_history(
        db,
        case_type="UI",
        case=ui_case,
        action="REVIEW",
        changed_by=current_user.id,
        summary="评审通过" if payload.result == "APPROVED" else "评审拒绝",
    )
    db.commit()
    db.refresh(ui_case)
    return ui_case
