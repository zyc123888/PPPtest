"""性能测试用例管理路由。"""

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
from app.core.database import get_db
from app.models import (
    PerformanceCase,
    Project,
    TestPlanCase,
    TestRun,
    User,
)
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
from app.domain import cases as cases_domain

router = APIRouter(tags=["performance-cases"])


def _perf_case_scope_conditions(db: Session, current_user: User, project_id: int | None) -> list | None:
    conditions: list = []
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        conditions.append(PerformanceCase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return None
        conditions.append(PerformanceCase.project_id.in_(project_ids))
    return conditions


@router.get(
    "/performance-cases", response_model=schemas.PerformanceCasePage | list[schemas.PerformanceCaseRead],
    summary="获取性能用例列表",
)
def list_performance_cases(
    project_id: int | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = None,
    priority: str | None = None,
    review_status: str | None = None,
    method: str | None = None,
    folder: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.PerformanceCasePage | list[PerformanceCase]:
    stmt = select(PerformanceCase).order_by(PerformanceCase.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(PerformanceCase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.PerformanceCasePage(items=[], total=0) if page is not None else []
        stmt = stmt.where(PerformanceCase.project_id.in_(project_ids))
    if status:
        stmt = stmt.where(PerformanceCase.status == status.strip().upper())
    if priority:
        stmt = stmt.where(PerformanceCase.priority == priority.strip().upper())
    if review_status:
        stmt = stmt.where(PerformanceCase.review_status == review_status.strip().upper())
    if method:
        stmt = stmt.where(PerformanceCase.method == method.strip().upper())
    if folder:
        normalized_folder = folder.strip().strip("/")
        if normalized_folder == "__ungrouped__":
            stmt = stmt.where(or_(PerformanceCase.folder_path.is_(None), PerformanceCase.folder_path == ""))
        elif normalized_folder:
            stmt = stmt.where(
                or_(
                    PerformanceCase.folder_path == normalized_folder,
                    PerformanceCase.folder_path.like(f"{normalized_folder}/%"),
                )
            )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                PerformanceCase.name.like(pattern),
                PerformanceCase.folder_path.like(pattern),
                PerformanceCase.path.like(pattern),
                cast(PerformanceCase.tags_json, String).like(pattern),
            )
        )
    if page is not None:
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        items = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
        for item in items:
            _ensure_case_defaults(item)
        return schemas.PerformanceCasePage(
            items=[schemas.PerformanceCaseRead.model_validate(item) for item in items],
            total=total,
        )
    items = list(db.scalars(stmt).all())
    for item in items:
        _ensure_case_defaults(item)
    return items


@router.post(
    "/performance-cases",
    response_model=schemas.PerformanceCaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建性能用例",
)
def create_performance_case(
    payload: schemas.PerformanceCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceCase:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    perf_case = PerformanceCase(**_initial_case_data(payload), created_by=current_user.id, updated_by=current_user.id)
    db.add(perf_case)
    db.commit()
    db.refresh(perf_case)
    cases_domain._record_case_history(db, case_type="PERF", case=perf_case, action="CREATE", changed_by=current_user.id, summary="创建性能用例")
    db.commit()
    return perf_case


@router.get("/performance-cases/folders", response_model=schemas.PerformanceCaseFolderTree, summary="获取性能用例目录树")
def get_performance_case_folder_tree(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.PerformanceCaseFolderTree:
    conditions = _perf_case_scope_conditions(db, current_user, project_id)
    if conditions is None:
        return schemas.PerformanceCaseFolderTree()
    stmt = select(PerformanceCase.folder_path, func.count(PerformanceCase.id)).group_by(PerformanceCase.folder_path)
    for condition in conditions:
        stmt = stmt.where(condition)
    rows = db.execute(stmt).all()

    total = 0
    ungrouped = 0
    nodes: dict[str, schemas.PerformanceCaseFolderNode] = {}
    roots: list[schemas.PerformanceCaseFolderNode] = []

    def ensure_node(path: str) -> schemas.PerformanceCaseFolderNode:
        node = nodes.get(path)
        if node is not None:
            return node
        node = schemas.PerformanceCaseFolderNode(path=path, name=path.rsplit("/", 1)[-1])
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

    def sort_nodes(items: list[schemas.PerformanceCaseFolderNode]) -> None:
        items.sort(key=lambda node: node.name)
        for child in items:
            sort_nodes(child.children)

    sort_nodes(roots)
    return schemas.PerformanceCaseFolderTree(total=total, ungrouped=ungrouped, folders=roots)


@router.post(
    "/performance-cases/folders/rename",
    response_model=schemas.PerformanceCaseBatchResult,
    dependencies=[Depends(require_tester)],
    summary="重命名性能用例目录",
)
def rename_performance_case_folder(
    payload: schemas.PerformanceCaseFolderRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.PerformanceCaseBatchResult:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    old_path = payload.old_path.strip().strip("/")
    new_path = payload.new_path.strip().strip("/")
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="目录路径不能为空")
    if old_path == new_path:
        return schemas.PerformanceCaseBatchResult(affected=0)
    cases = list(
        db.scalars(
            select(PerformanceCase).where(
                PerformanceCase.project_id == payload.project_id,
                or_(
                    PerformanceCase.folder_path == old_path,
                    PerformanceCase.folder_path.like(f"{old_path}/%"),
                ),
            )
        ).all()
    )
    for case in cases:
        current = case.folder_path or ""
        case.folder_path = new_path + current[len(old_path):]
        case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type="PERF",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"目录重命名 {old_path} → {new_path}",
        )
    db.commit()
    return schemas.PerformanceCaseBatchResult(affected=len(cases))


@router.get("/performance-cases/stats", response_model=schemas.PerformanceCaseStats, summary="获取性能用例统计信息")
def get_performance_case_stats(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.PerformanceCaseStats:
    conditions = _perf_case_scope_conditions(db, current_user, project_id)
    if conditions is None:
        return schemas.PerformanceCaseStats()
    base = select(func.count(PerformanceCase.id))
    for condition in conditions:
        base = base.where(condition)
    total = db.scalar(base) or 0
    active = db.scalar(base.where(PerformanceCase.status == "ACTIVE")) or 0
    approved = db.scalar(base.where(PerformanceCase.review_status == "APPROVED")) or 0

    runs_stmt = select(TestRun.status).where(TestRun.case_type == "PERF")
    if project_id:
        runs_stmt = runs_stmt.where(TestRun.project_id == project_id)
    elif current_user.role != "admin":
        runs_stmt = runs_stmt.where(TestRun.project_id.in_(_accessible_project_ids(db, current_user)))
    statuses = list(db.scalars(runs_stmt.order_by(TestRun.id.desc()).limit(50)).all())
    finished = [item for item in statuses if item in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}]
    rate = None
    if finished:
        rate = round(sum(1 for item in finished if item == "SUCCESS") / len(finished), 4)
    return schemas.PerformanceCaseStats(total=total, active=active, approved=approved, recent_success_rate=rate)


@router.put(
    "/performance-cases/batch",
    response_model=schemas.PerformanceCaseBatchResult,
    dependencies=[Depends(require_tester)],
    summary="批量更新性能用例",
)
def batch_update_performance_cases(
    payload: schemas.PerformanceCaseBatchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.PerformanceCaseBatchResult:
    patch = payload.patch.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(PerformanceCase).where(PerformanceCase.id.in_(case_ids))).all())
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
            case_type="PERF",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"批量更新属性：{', '.join(sorted(patch.keys()))}",
        )
    db.commit()
    return schemas.PerformanceCaseBatchResult(affected=len(cases))


@router.delete(
    "/performance-cases/batch",
    response_model=schemas.PerformanceCaseBatchResult,
    dependencies=[Depends(require_admin)],
    summary="批量删除性能用例",
)
def batch_delete_performance_cases(
    payload: schemas.PerformanceCaseBatchDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.PerformanceCaseBatchResult:
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(PerformanceCase).where(PerformanceCase.id.in_(case_ids))).all())
    if len(cases) != len(case_ids):
        raise HTTPException(status_code=404, detail="部分用例不存在")
    for case in cases:
        cases_domain._record_case_history(
            db,
            case_type="PERF",
            case=case,
            action="DELETE",
            changed_by=current_user.id,
            summary="批量删除性能用例",
        )
        db.execute(
            delete(TestPlanCase).where(TestPlanCase.case_type == "PERF", TestPlanCase.case_id == case.id)
        )
        db.delete(case)
    db.commit()
    return schemas.PerformanceCaseBatchResult(affected=len(cases))


@router.get("/performance-cases/{case_id}", response_model=schemas.PerformanceCaseRead, summary="获取性能用例详情")
def get_performance_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceCase:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    _require_project_access(db, current_user, db.get(Project, perf_case.project_id))
    _ensure_case_defaults(perf_case)
    return perf_case


@router.put(
    "/performance-cases/{case_id}",
    response_model=schemas.PerformanceCaseRead,
    dependencies=[Depends(require_tester)],
    summary="更新性能用例",
)
def update_performance_case(
    case_id: int,
    payload: schemas.PerformanceCaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceCase:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    _require_project_access(db, current_user, db.get(Project, perf_case.project_id))
    _reject_case_project_reassignment(perf_case.project_id, payload.project_id)
    original_review_status = (perf_case.review_status or "DRAFT").upper()
    original_signature = (
        perf_case.name,
        perf_case.folder_path,
        perf_case.method,
        perf_case.path,
        perf_case.priority,
        perf_case.status,
        tuple(perf_case.tags_json or []),
        perf_case.expected_status,
        perf_case.headers_json,
        perf_case.body_json,
        perf_case.concurrency,
        perf_case.total_requests,
        perf_case.max_avg_response_ms,
        perf_case.max_p95_response_ms,
        perf_case.max_error_rate,
    )
    data = payload.model_dump(exclude={"project_id", "review_status", "review_note"})
    data["method"] = data["method"].upper()
    for key, value in data.items():
        setattr(perf_case, key, value)
    new_signature = (
        perf_case.name,
        perf_case.folder_path,
        perf_case.method,
        perf_case.path,
        perf_case.priority,
        perf_case.status,
        tuple(perf_case.tags_json or []),
        perf_case.expected_status,
        perf_case.headers_json,
        perf_case.body_json,
        perf_case.concurrency,
        perf_case.total_requests,
        perf_case.max_avg_response_ms,
        perf_case.max_p95_response_ms,
        perf_case.max_error_rate,
    )
    if new_signature != original_signature:
        perf_case.version_no = _bump_version(perf_case.version_no)
        if original_review_status in {"APPROVED", "IN_REVIEW"}:
            perf_case.review_status = "DRAFT"
            perf_case.reviewed_by = None
            perf_case.reviewed_at = None
            perf_case.submitted_review_at = None
    perf_case.updated_by = current_user.id
    cases_domain._record_case_history(db, case_type="PERF", case=perf_case, action="UPDATE", changed_by=current_user.id, summary="更新性能用例")
    db.commit()
    db.refresh(perf_case)
    return perf_case


@router.delete("/performance-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除性能用例")
def delete_performance_case(case_id: int, db: Session = Depends(get_db)) -> None:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "PERF", TestPlanCase.case_id == case_id)
    )
    db.delete(perf_case)
    db.commit()


@router.post(
    "/performance-cases/{case_id}/review/submit",
    response_model=schemas.PerformanceCaseRead,
    dependencies=[Depends(require_tester)],
    summary="提交性能用例评审",
)
def submit_performance_case_review(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceCase:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    _require_project_access(db, current_user, db.get(Project, perf_case.project_id))
    _ensure_case_defaults(perf_case)
    current_status = (perf_case.review_status or "DRAFT").upper()
    if current_status not in {"DRAFT", "REJECTED"}:
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不能提交评审")
    perf_case.review_status = "IN_REVIEW"
    perf_case.submitted_review_at = utc_now_naive()
    perf_case.reviewed_by = None
    perf_case.reviewed_at = None
    perf_case.updated_by = current_user.id
    cases_domain._record_case_history(db, case_type="PERF", case=perf_case, action="REVIEW", changed_by=current_user.id, summary="提交评审")
    db.commit()
    db.refresh(perf_case)
    return perf_case


@router.post(
    "/performance-cases/{case_id}/review/decide",
    response_model=schemas.PerformanceCaseRead,
    dependencies=[Depends(require_tester)],
    summary="审批性能用例评审",
)
def decide_performance_case_review(
    case_id: int,
    payload: schemas.PerformanceCaseReviewDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceCase:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    if perf_case.created_by is not None and perf_case.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
    _require_project_member(db, current_user, db.get(Project, perf_case.project_id))
    _ensure_case_defaults(perf_case)
    current_status = (perf_case.review_status or "DRAFT").upper()
    if current_status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不在评审中")
    perf_case.review_status = payload.result
    perf_case.review_note = payload.note
    perf_case.reviewed_by = current_user.id
    perf_case.reviewed_at = utc_now_naive()
    perf_case.updated_by = current_user.id
    cases_domain._record_case_history(
        db,
        case_type="PERF",
        case=perf_case,
        action="REVIEW",
        changed_by=current_user.id,
        summary="评审通过" if payload.result == "APPROVED" else "评审拒绝",
    )
    db.commit()
    db.refresh(perf_case)
    return perf_case
