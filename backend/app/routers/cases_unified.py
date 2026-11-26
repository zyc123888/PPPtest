"""统一用例中心路由（跨类型检索、导入导出、查重、批量治理）。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import schemas, spec_import
from app.core.database import get_db
from app.models import (
    APICase,
    CaseChangeHistory,
    PerformanceCase,
    Project,
    UICase,
    User,
)
from app.timeutil import utc_now_naive
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_project_member,
    get_current_user,
    require_tester,
)
from app.domain.cases import _load_case_entity, _normalize_case_type, _serialize_unified_case
from app.domain import cases as cases_domain

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=schemas.UnifiedCasePage | list[schemas.UnifiedCaseRead], summary="统一查询三类用例（支持分页与过滤）")
def list_cases(
    project_id: int | None = None,
    case_type: str | None = None,
    folder_path: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    tag: str | None = None,
    tags: str | None = None,
    tag_mode: str | None = Query(default="ANY", pattern="^(ANY|ALL)$"),
    keyword: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UnifiedCasePage | list[schemas.UnifiedCaseRead]:
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        project_ids = [project_id]
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.UnifiedCasePage(items=[], total=0, page=page, page_size=page_size) if page is not None else []
    else:
        project_ids = None

    keyword_value = (keyword or "").strip().lower()
    folder_value = (folder_path or "").strip().lower()
    normalized_type = (case_type or "").strip().upper()
    normalized_priority = (priority or "").strip().upper()
    normalized_status = (status or "").strip().upper()
    normalized_review_status = (review_status or "").strip().upper()
    single_tag_value = (tag or "").strip().lower()
    tag_values = [item.strip().lower() for item in (tags or "").split(",") if item.strip()]
    if single_tag_value and single_tag_value not in tag_values:
        tag_values.append(single_tag_value)
    normalized_tag_mode = (tag_mode or "ANY").strip().upper()
    items: list[schemas.UnifiedCaseRead] = []

    def _apply_sql_filters(stmt, model, keyword_cols):
        if project_ids is not None:
            stmt = stmt.where(model.project_id.in_(project_ids))
        if folder_value:
            stmt = stmt.where(func.lower(func.coalesce(model.folder_path, "")).like(f"%{folder_value}%"))
        if normalized_priority:
            stmt = stmt.where(func.upper(func.coalesce(model.priority, "")) == normalized_priority)
        if normalized_status:
            stmt = stmt.where(func.upper(func.coalesce(model.status, "")) == normalized_status)
        if normalized_review_status:
            stmt = stmt.where(func.upper(func.coalesce(model.review_status, "")) == normalized_review_status)
        if keyword_value:
            pattern = f"%{keyword_value}%"
            stmt = stmt.where(or_(*(func.lower(func.coalesce(col, "")).like(pattern) for col in keyword_cols)))
        return stmt

    def _matches_tags(case) -> bool:
        if not tag_values:
            return True
        case_tags = {str(item).lower() for item in (case.tags_json or [])}
        if normalized_tag_mode == "ALL":
            return all(value in case_tags for value in tag_values)
        return any(value in case_tags for value in tag_values)

    if normalized_type in {"", "API"}:
        stmt = _apply_sql_filters(select(APICase).order_by(APICase.id.desc()), APICase, [APICase.name, APICase.path])
        for case in db.scalars(stmt).all():
            if _matches_tags(case):
                items.append(_serialize_unified_case("API", case))

    if normalized_type in {"", "UI"}:
        stmt = _apply_sql_filters(
            select(UICase).order_by(UICase.id.desc()),
            UICase,
            [UICase.name, UICase.target_url, UICase.expect_text],
        )
        for case in db.scalars(stmt).all():
            if _matches_tags(case):
                items.append(_serialize_unified_case("UI", case))

    if normalized_type in {"", "PERF"}:
        stmt = _apply_sql_filters(
            select(PerformanceCase).order_by(PerformanceCase.id.desc()),
            PerformanceCase,
            [PerformanceCase.name, PerformanceCase.path],
        )
        for case in db.scalars(stmt).all():
            if _matches_tags(case):
                items.append(_serialize_unified_case("PERF", case))

    items.sort(
        key=lambda item: (
            item.updated_at is not None or item.created_at is not None,
            item.updated_at or item.created_at,
            item.case_id,
        ),
        reverse=True,
    )
    if page is not None:
        total = len(items)
        start = (page - 1) * page_size
        return schemas.UnifiedCasePage(
            items=items[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )
    return items


@router.get("/cases/export", summary="导出用例列表")
def export_cases(
    project_id: int | None = None,
    case_type: str | None = None,
    folder_path: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    tag: str | None = None,
    tags: str | None = None,
    tag_mode: str | None = "ANY",
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    items = list_cases(
        project_id=project_id,
        case_type=case_type,
        folder_path=folder_path,
        priority=priority,
        status=status,
        review_status=review_status,
        tag=tag,
        tags=tags,
        tag_mode=tag_mode,
        keyword=keyword,
        page=None,
        db=db,
        current_user=current_user,
    )
    return {
        "count": len(items),
        "items": [item.model_dump() for item in items],
    }


@router.get("/cases/duplicates", response_model=list[schemas.CaseDuplicateGroup], summary="检测重复用例")
def detect_duplicate_cases(
    project_id: int | None = None,
    case_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseDuplicateGroup]:
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        project_ids = [project_id]
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
    else:
        project_ids = None

    normalized_type = (case_type or "").strip().upper()
    buckets: dict[tuple[str, str], list[schemas.CaseDuplicateItem]] = {}

    def add_item(item_type: str, case, entry: str) -> None:
        key = entry.strip().lower()
        if not key:
            return
        buckets.setdefault((item_type, key), []).append(
            schemas.CaseDuplicateItem(
                case_type=item_type,
                case_id=case.id,
                project_id=case.project_id,
                name=case.name,
                folder_path=case.folder_path,
                entry=entry,
                review_status=getattr(case, "review_status", None),
                updated_at=getattr(case, "updated_at", None),
            )
        )

    # 分组与计数下推到数据库：先聚合出「出现 >1 次」的重复键，再只加载重复组成员，
    # 避免把全表用例（含大 JSON 列）读进内存。键表达式与原 Python 逻辑一致：
    # API/PERF = lower(trim(upper(method) + ' ' + path))；UI = lower(trim(target_url))。
    key_specs = [
        (
            "API",
            APICase,
            func.lower(func.trim(func.upper(APICase.method) + " " + APICase.path)),
        ),
        ("UI", UICase, func.lower(func.trim(UICase.target_url))),
        (
            "PERF",
            PerformanceCase,
            func.lower(func.trim(func.upper(PerformanceCase.method) + " " + PerformanceCase.path)),
        ),
    ]
    for item_type, model, key_expr in key_specs:
        if normalized_type not in {"", item_type}:
            continue
        base_filters = []
        if project_ids is not None:
            base_filters.append(model.project_id.in_(project_ids))
        dup_key_stmt = (
            select(key_expr)
            .where(*base_filters, key_expr.isnot(None), key_expr != "")
            .group_by(key_expr)
            .having(func.count() > 1)
        )
        duplicate_keys = [row[0] for row in db.execute(dup_key_stmt).all()]
        if not duplicate_keys:
            continue
        for case in db.scalars(
            select(model).where(*base_filters, key_expr.in_(duplicate_keys))
        ).all():
            if item_type == "UI":
                entry = case.target_url or ""
            else:
                entry = f"{(case.method or '').upper()} {case.path}"
            add_item(item_type, case, entry)

    groups = [
        schemas.CaseDuplicateGroup(case_type=item_type, duplicate_key=duplicate_key, count=len(items), items=items)
        for (item_type, duplicate_key), items in buckets.items()
        if len(items) > 1
    ]
    return sorted(groups, key=lambda item: (item.case_type, item.duplicate_key))


@router.post(
    "/cases/import",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量导入用例（全量事务回滚）",
)
def import_cases(
    payload: schemas.CaseImportPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    affected_count = 0
    for index, item in enumerate(payload.items, start=1):
        # 整批事务内逐条定位失败原因：任何一条失败都回滚整批，
        # 并在错误信息中标明条目序号与名称，避免“整批失败但不知道坏在哪一条”。
        try:
            project = _require_project_access(db, current_user, db.get(Project, item.project_id))
            case_type = item.case_type.upper()
            if case_type == "API":
                case = APICase(
                    project_id=project.id,
                    name=item.name,
                    folder_path=item.folder_path,
                    method=(item.method or "GET").upper(),
                    path=item.path or "/",
                    priority=item.priority,
                    status=item.status,
                    review_status="DRAFT",
                    version_no=item.version_no,
                    review_note=None,
                    tags_json=item.tags_json,
                    headers_json=item.headers_json,
                    body_json=item.body_json,
                    assertions_json=item.assertions_json,
                    extractors_json=item.extractors_json,
                    steps_json=item.steps_json,
                    expected_status=item.expected_status or 200,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
                db.add(case)
                db.flush()
                cases_domain._record_case_history(db, case_type="API", case=case, action="IMPORT", changed_by=current_user.id, summary="批量导入接口用例")
            elif case_type == "UI":
                validated = schemas.UICaseCreate(
                    project_id=project.id,
                    name=item.name,
                    folder_path=item.folder_path,
                    target_url=item.target_url or "http://localhost",
                    priority=item.priority,
                    status=item.status,
                    review_status="DRAFT",
                    version_no=item.version_no,
                    review_note=None,
                    tags_json=item.tags_json,
                    steps_json=item.steps_json or [],
                    assertions_json=item.assertions_json,
                    expect_text=item.expect_text or "ok",
                    generation_mode=item.generation_mode,
                    execution_mode=item.execution_mode,
                    engine=item.engine,
                    self_heal_enabled=item.self_heal_enabled,
                    max_agent_steps=item.max_agent_steps,
                    allowed_origins_json=item.allowed_origins_json,
                    prohibited_actions_json=item.prohibited_actions_json,
                    ai_goal=item.ai_goal,
                    skill_name=item.skill_name,
                    skill_version=item.skill_version,
                    generation_meta_json=item.generation_meta_json,
                ).model_dump()
                case = UICase(
                    **validated,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
                db.add(case)
                db.flush()
                cases_domain._record_case_history(db, case_type="UI", case=case, action="IMPORT", changed_by=current_user.id, summary="批量导入 UI 用例")
            else:
                case = PerformanceCase(
                    project_id=project.id,
                    name=item.name,
                    folder_path=item.folder_path,
                    method=(item.method or "GET").upper(),
                    path=item.path or "/",
                    priority=item.priority,
                    status=item.status,
                    review_status="DRAFT",
                    version_no=item.version_no,
                    review_note=None,
                    tags_json=item.tags_json,
                    headers_json=item.headers_json,
                    body_json=item.body_json,
                    expected_status=item.expected_status or 200,
                    concurrency=item.concurrency or 5,
                    total_requests=item.total_requests or 20,
                    max_avg_response_ms=item.max_avg_response_ms,
                    max_p95_response_ms=item.max_p95_response_ms,
                    max_error_rate=item.max_error_rate,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
                db.add(case)
                db.flush()
                cases_domain._record_case_history(db, case_type="PERF", case=case, action="IMPORT", changed_by=current_user.id, summary="批量导入性能用例")
            affected_count += 1
        except HTTPException:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"导入失败：第 {index} 条（{item.case_type} · {item.name}）：{exc}",
            ) from exc

    db.commit()
    return schemas.BatchActionResult(success=True, affected_count=affected_count, message=f"已导入 {affected_count} 条用例")


@router.post(
    "/api-cases/import-spec",
    response_model=schemas.ApiSpecImportResult,
    dependencies=[Depends(require_tester)],
    summary="从 OpenAPI/Swagger 或 Postman 导入接口用例",
)
def import_api_spec(
    payload: schemas.ApiSpecImportPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ApiSpecImportResult:
    """从 OpenAPI/Swagger 或 Postman Collection 导入接口用例。

    dry_run=True 时仅解析预览、不落库；否则逐条创建 APICase 并记录导入历史。
    """
    project = _require_project_access(db, current_user, db.get(Project, payload.project_id))
    try:
        drafts, warnings = spec_import.parse_spec(payload.source_type, payload.content)
    except spec_import.SpecParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    base_folder = (payload.folder_path or "").strip().strip("/") or None
    preview_items: list[schemas.ApiSpecImportPreviewItem] = []
    created_count = 0
    for draft in drafts:
        folder = draft.get("folder_path")
        if base_folder:
            folder = f"{base_folder}/{folder}" if folder else base_folder
        folder = folder[:255] if folder else None
        preview_items.append(
            schemas.ApiSpecImportPreviewItem(
                name=draft["name"],
                method=draft["method"],
                path=draft["path"],
                folder_path=folder,
            )
        )
        if payload.dry_run:
            continue
        case = APICase(
            project_id=project.id,
            name=draft["name"],
            folder_path=folder,
            method=draft["method"],
            path=draft["path"] or "/",
            headers_json=draft.get("headers_json"),
            body_json=draft.get("body_json"),
            expected_status=200,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(case)
        db.flush()
        cases_domain._record_case_history(
            db,
            case_type="API",
            case=case,
            action="IMPORT",
            changed_by=current_user.id,
            summary=f"从 {payload.source_type} 导入接口用例",
        )
        created_count += 1

    if not payload.dry_run and created_count:
        db.commit()
    return schemas.ApiSpecImportResult(
        source_type=payload.source_type,
        detected_count=len(drafts),
        created_count=created_count,
        dry_run=payload.dry_run,
        items=preview_items,
        warnings=warnings,
    )


@router.get("/cases/folders", response_model=list[schemas.CaseFolderNode], summary="获取统一用例目录树")
def list_case_folders(
    project_id: int | None = None,
    case_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseFolderNode]:
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        project_ids = [project_id]
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
    else:
        project_ids = None

    normalized_type = (case_type or "").strip().upper()
    folder_paths: list[str] = []
    if normalized_type in {"", "API"}:
        stmt = select(APICase.folder_path).where(APICase.folder_path.is_not(None))
        if project_ids is not None:
            stmt = stmt.where(APICase.project_id.in_(project_ids))
        folder_paths.extend([str(item).strip() for item in db.scalars(stmt).all() if str(item).strip()])
    if normalized_type in {"", "UI"}:
        stmt = select(UICase.folder_path).where(UICase.folder_path.is_not(None))
        if project_ids is not None:
            stmt = stmt.where(UICase.project_id.in_(project_ids))
        folder_paths.extend([str(item).strip() for item in db.scalars(stmt).all() if str(item).strip()])
    if normalized_type in {"", "PERF"}:
        stmt = select(PerformanceCase.folder_path).where(PerformanceCase.folder_path.is_not(None))
        if project_ids is not None:
            stmt = stmt.where(PerformanceCase.project_id.in_(project_ids))
        folder_paths.extend([str(item).strip() for item in db.scalars(stmt).all() if str(item).strip()])

    path_counts: dict[str, int] = {}
    for raw_path in folder_paths:
        segments = [part.strip() for part in raw_path.split("/") if part.strip()]
        current = []
        for segment in segments:
            current.append(segment)
            joined = "/".join(current)
            path_counts[joined] = path_counts.get(joined, 0) + 1

    node_map: dict[str, schemas.CaseFolderNode] = {}
    for path in sorted(path_counts.keys(), key=lambda value: (value.count("/"), value)):
        name = path.split("/")[-1]
        node_map[path] = schemas.CaseFolderNode(name=name, path=path, count=path_counts[path], children=[])

    roots: list[schemas.CaseFolderNode] = []
    for path in sorted(node_map.keys(), key=lambda value: value):
        node = node_map[path]
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent_path and parent_path in node_map:
            node_map[parent_path].children.append(node)
        else:
            roots.append(node)
    return roots


@router.get("/cases/{case_type}/{case_id}/history", response_model=list[schemas.CaseHistoryRead], summary="获取用例变更历史")
def list_case_history(
    case_type: str,
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CaseChangeHistory]:
    case = _load_case_entity(db, case_type, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    _require_project_access(db, current_user, db.get(Project, case.project_id))
    normalized_case_type = _normalize_case_type(case_type)
    return list(
        db.scalars(
            select(CaseChangeHistory)
            .where(
                CaseChangeHistory.case_type == normalized_case_type,
                CaseChangeHistory.case_id == case_id,
            )
            .order_by(CaseChangeHistory.id.desc())
        ).all()
    )


@router.post(
    "/cases/batch-update",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量更新用例状态或标签",
)
def batch_update_cases(
    payload: schemas.CaseBatchUpdatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    affected_count = 0
    normalized_status = (payload.status or "").strip().upper() or None
    normalized_tags = []
    if payload.add_tags:
        seen = set()
        for item in payload.add_tags:
            tag = str(item).strip()
            if not tag:
                continue
            lower = tag.lower()
            if lower in seen:
                continue
            seen.add(lower)
            normalized_tags.append(tag)

    for item in payload.items:
        case = _load_case_entity(db, item.case_type, item.case_id)
        if case is None:
            continue
        _require_project_access(db, current_user, db.get(Project, case.project_id))
        if normalized_status:
            case.status = normalized_status
        if normalized_tags:
            current_tags = list(case.tags_json or [])
            current_tag_lowers = {str(tag).lower() for tag in current_tags}
            for tag in normalized_tags:
                if tag.lower() not in current_tag_lowers:
                    current_tags.append(tag)
                    current_tag_lowers.add(tag.lower())
            case.tags_json = current_tags
        if hasattr(case, "updated_by"):
            case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type=item.case_type,
            case=case,
            action="BATCH_UPDATE",
            changed_by=current_user.id,
            summary="批量更新状态或标签",
        )
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已更新 {affected_count} 条用例",
    )


@router.post(
    "/cases/batch-review",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量提交或决策用例评审",
)
def batch_review_cases(
    payload: schemas.CaseBatchReviewPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    affected_count = 0
    normalized_review_status = payload.review_status.strip().upper()
    if normalized_review_status not in {"IN_REVIEW", "APPROVED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="批量评审仅支持提交评审(IN_REVIEW)、通过(APPROVED)或拒绝(REJECTED)")
    cases = []
    seen = set()
    for item in payload.items:
        key = (item.case_type.upper(), item.case_id)
        if key in seen:
            raise HTTPException(status_code=400, detail="评审用例存在重复")
        seen.add(key)
        case = _load_case_entity(db, item.case_type, item.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="部分评审用例不存在")
        if normalized_review_status == "IN_REVIEW":
            _require_project_access(db, current_user, db.get(Project, case.project_id))
            if (case.review_status or "DRAFT").upper() not in {"DRAFT", "REJECTED"}:
                raise HTTPException(status_code=400, detail="仅草稿或已拒绝状态的用例可批量提交评审")
        else:
            _require_project_member(db, current_user, db.get(Project, case.project_id))
            if case.created_by is not None and case.created_by == current_user.id:
                raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
            if (case.review_status or "DRAFT").upper() != "IN_REVIEW":
                raise HTTPException(status_code=400, detail="部分用例不在评审中")
        cases.append((item.case_type, case))
    for case_type, case in cases:
        case.review_status = normalized_review_status
        if normalized_review_status == "IN_REVIEW":
            case.submitted_review_at = utc_now_naive()
            case.reviewed_by = None
            case.reviewed_at = None
        else:
            case.review_note = payload.review_note
            case.reviewed_by = current_user.id
            case.reviewed_at = utc_now_naive()
        if hasattr(case, "updated_by"):
            case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type=case_type,
            case=case,
            action="BATCH_REVIEW",
            changed_by=current_user.id,
            summary="批量提交评审" if normalized_review_status == "IN_REVIEW" else f"批量评审为 {normalized_review_status}",
        )
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已提交 {affected_count} 条用例评审" if normalized_review_status == "IN_REVIEW" else f"已评审 {affected_count} 条用例",
    )


@router.post(
    "/cases/batch-move-folder",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
    summary="批量移动用例目录",
)
def batch_move_case_folder(
    payload: schemas.CaseBatchMoveFolderPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    target_folder = (payload.folder_path or "").strip() or None
    affected_count = 0
    for item in payload.items:
        case = _load_case_entity(db, item.case_type, item.case_id)
        if case is None:
            continue
        _require_project_access(db, current_user, db.get(Project, case.project_id))
        if (case.folder_path or None) == target_folder:
            continue
        case.folder_path = target_folder
        if hasattr(case, "updated_by"):
            case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type=item.case_type,
            case=case,
            action="MOVE_FOLDER",
            changed_by=current_user.id,
            summary=f"移动目录到 {target_folder or '根目录'}",
        )
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已移动 {affected_count} 条用例",
    )
