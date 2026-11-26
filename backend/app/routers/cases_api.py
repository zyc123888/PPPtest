"""API 接口用例管理与即时调试路由。"""

import time
from urllib.parse import urlparse

import httpx
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
    APICase,
    Environment,
    Project,
    TestPlanCase,
    TestRun,
    User,
)
from app.execution_runtime import (
    MissingTemplateVariableError,
    UnsafeTargetURLError,
    build_variable_context,
    prepare_http_request,
)
from app.assertion_engine import ResponseFacts, evaluate_assertions, run_extractors
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

router = APIRouter(tags=["api-cases"])


@router.get("/api-cases", response_model=schemas.APICasePage | list[schemas.APICaseRead], summary="获取接口用例列表")
def list_api_cases(
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
) -> schemas.APICasePage | list[APICase]:
    stmt = select(APICase).order_by(APICase.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(APICase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.APICasePage(items=[], total=0) if page is not None else []
        stmt = stmt.where(APICase.project_id.in_(project_ids))
    if status:
        stmt = stmt.where(APICase.status == status.strip().upper())
    if priority:
        stmt = stmt.where(APICase.priority == priority.strip().upper())
    if review_status:
        stmt = stmt.where(APICase.review_status == review_status.strip().upper())
    if method:
        stmt = stmt.where(APICase.method == method.strip().upper())
    if folder:
        normalized_folder = folder.strip().strip("/")
        if normalized_folder == "__ungrouped__":
            stmt = stmt.where(or_(APICase.folder_path.is_(None), APICase.folder_path == ""))
        elif normalized_folder:
            stmt = stmt.where(
                or_(APICase.folder_path == normalized_folder, APICase.folder_path.like(f"{normalized_folder}/%"))
            )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                APICase.name.like(pattern),
                APICase.folder_path.like(pattern),
                APICase.path.like(pattern),
                cast(APICase.tags_json, String).like(pattern),
            )
        )
    if page is not None:
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        items = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
        for item in items:
            _ensure_case_defaults(item)
        return schemas.APICasePage(
            items=[schemas.APICaseRead.model_validate(item) for item in items],
            total=total,
        )
    items = list(db.scalars(stmt).all())
    for item in items:
        _ensure_case_defaults(item)
    return items


@router.post(
    "/api-cases",
    response_model=schemas.APICaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
    summary="创建接口用例",
)
def create_api_case(
    payload: schemas.APICaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APICase:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    data = _initial_case_data(payload)
    data["method"] = data["method"].upper()
    api_case = APICase(**data, created_by=current_user.id, updated_by=current_user.id)
    db.add(api_case)
    db.commit()
    db.refresh(api_case)
    cases_domain._record_case_history(db, case_type="API", case=api_case, action="CREATE", changed_by=current_user.id, summary="创建接口用例")
    db.commit()
    return api_case


@router.post(
    "/api-cases/debug",
    response_model=schemas.APICaseDebugResponse,
    dependencies=[Depends(require_tester)],
    summary="即时调试接口用例",
)
def debug_api_case(
    payload: schemas.APICaseDebugRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.APICaseDebugResponse:
    project = db.get(Project, payload.project_id)
    _require_project_access(db, current_user, project)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    environment = None
    if payload.environment_id:
        environment = db.get(Environment, payload.environment_id)
        if environment is None or environment.project_id != project.id:
            raise HTTPException(status_code=404, detail="执行环境不存在")

    dataset_applied: dict = {}
    if isinstance(payload.datasets_json, list) and payload.datasets_json:
        first_row = payload.datasets_json[0]
        if isinstance(first_row, dict):
            if "data" in first_row and isinstance(first_row.get("data"), dict):
                dataset_applied = {k: v for k, v in first_row["data"].items()}
            else:
                dataset_applied = {k: v for k, v in first_row.items() if k != "__name__"}

    variables = build_variable_context(project, environment, dataset_applied or None)

    def _send_debug_http(prepared_req):
        parsed_url = urlparse(prepared_req.url)
        req_started = time.perf_counter()
        if parsed_url.hostname == "testserver":
            from app.main import app
            from fastapi.testclient import TestClient

            with TestClient(app, base_url="http://testserver") as client:
                resp = client.request(
                    prepared_req.method, parsed_url.path, headers=prepared_req.headers, **prepared_req.kwargs()
                )
        else:
            with httpx.Client(timeout=payload.timeout_seconds, follow_redirects=False) as client:
                resp = client.request(
                    prepared_req.method, prepared_req.url, headers=prepared_req.headers, **prepared_req.kwargs()
                )
        dur = int((time.perf_counter() - req_started) * 1000)
        return resp, dur

    steps = [s for s in (payload.steps_json or []) if isinstance(s, dict)]
    if steps:
        step_results: list[dict] = []
        extracted_all: dict = {}
        all_assertions: list[dict] = []
        all_extractors: list[dict] = []
        total_duration = 0
        last_req_dict = {}
        last_resp_dict = {}
        all_passed = True

        for idx, step in enumerate(steps):
            step_name = str(step.get("name") or f"步骤 {idx + 1}")
            try:
                prepared = prepare_http_request(
                    method=str(step.get("method") or "GET"),
                    project=project,
                    environment=environment,
                    case_path=str(step.get("path") or "/"),
                    case_headers=step.get("headers_json"),
                    case_body=step.get("body_json"),
                    variables=variables,
                )
            except (MissingTemplateVariableError, UnsafeTargetURLError) as exc:
                raise HTTPException(status_code=400, detail=f"{step_name}：{exc}") from exc

            try:
                response, dur_ms = _send_debug_http(prepared)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"{step_name} 调试请求失败：{exc}") from exc

            total_duration += dur_ms
            response_headers = dict(response.headers)
            response_text = response.text
            try:
                response_body = response.json()
                body_type = "json"
            except Exception:
                response_body = response_text[:5000]
                body_type = "text"

            facts = ResponseFacts(
                status_code=response.status_code,
                headers=response_headers,
                body_text=response_text or "",
                body_json=response_body if body_type == "json" else None,
                duration_ms=dur_ms,
            )
            exp_status = int(step.get("expected_status") or 200)
            outcome = evaluate_assertions(step.get("assertions"), facts, expected_status=exp_status)
            extracted, extractor_results = run_extractors(step.get("extractors"), facts)
            variables.update(extracted)
            extracted_all.update({k: str(v) for k, v in extracted.items()})
            all_assertions.extend(outcome.results)
            all_extractors.extend(extractor_results)
            extract_failed = any(not item.get("ok") for item in extractor_results)
            step_ok = outcome.passed and not extract_failed
            if not step_ok:
                all_passed = False

            last_req_dict = {
                "method": prepared.method,
                "url": prepared.url,
                "headers": prepared.headers,
                "body": prepared.body,
            }
            last_resp_dict = {
                "status_code": response.status_code,
                "headers": response_headers,
                "body": response_body,
                "body_type": body_type,
                "size": len(response.content),
            }
            step_results.append(
                {
                    "index": idx + 1,
                    "name": step_name,
                    "status": "SUCCESS" if step_ok else "FAILED",
                    "duration_ms": dur_ms,
                    "request": last_req_dict,
                    "response": last_resp_dict,
                    "assertion_passed": step_ok,
                    "assertion_results": outcome.results,
                    "extracted_variables": {k: str(v) for k, v in extracted.items()},
                    "extractor_results": extractor_results,
                }
            )
            if not step_ok:
                break

        return schemas.APICaseDebugResponse(
            request=last_req_dict,
            response=last_resp_dict,
            duration_ms=total_duration,
            assertion_passed=all_passed,
            assertion_results=all_assertions,
            extracted_variables=extracted_all,
            extractor_results=all_extractors,
            step_results=step_results,
            dataset_applied={k: str(v) for k, v in dataset_applied.items()},
        )

    try:
        prepared = prepare_http_request(
            method=payload.method,
            project=project,
            environment=environment,
            case_path=payload.path,
            case_headers=payload.headers_json,
            case_body=payload.body_json,
            variables=variables,
        )
    except (MissingTemplateVariableError, UnsafeTargetURLError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        response, duration_ms = _send_debug_http(prepared)
        response_headers = dict(response.headers)
        response_text = response.text
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"调试请求失败：{exc}") from exc

    try:
        response_body = response.json()
        body_type = "json"
    except Exception:
        response_body = response_text[:5000]
        body_type = "text"

    facts = ResponseFacts(
        status_code=response.status_code,
        headers=response_headers,
        body_text=response_text or "",
        body_json=response_body if body_type == "json" else None,
        duration_ms=duration_ms,
    )
    outcome = evaluate_assertions(payload.assertions_json, facts, expected_status=payload.expected_status)
    extracted, extractor_results = run_extractors(payload.extractors_json, facts)

    return schemas.APICaseDebugResponse(
        request={
            "method": prepared.method,
            "url": prepared.url,
            "headers": prepared.headers,
            "body": prepared.body,
        },
        response={
            "status_code": response.status_code,
            "headers": response_headers,
            "body": response_body,
            "body_type": body_type,
            "size": len(response.content),
        },
        duration_ms=duration_ms,
        assertion_passed=outcome.passed,
        assertion_results=outcome.results,
        extracted_variables={key: str(value) for key, value in extracted.items()},
        extractor_results=extractor_results,
        step_results=[],
        dataset_applied={k: str(v) for k, v in dataset_applied.items()},
    )


def _api_case_scope_conditions(db: Session, current_user: User, project_id: int | None) -> list | None:
    conditions: list = []
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        conditions.append(APICase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return None
        conditions.append(APICase.project_id.in_(project_ids))
    return conditions


@router.get("/api-cases/folders", response_model=schemas.APICaseFolderTree, summary="获取接口用例目录树")
def get_api_case_folder_tree(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.APICaseFolderTree:
    conditions = _api_case_scope_conditions(db, current_user, project_id)
    if conditions is None:
        return schemas.APICaseFolderTree()
    stmt = select(APICase.folder_path, func.count(APICase.id)).group_by(APICase.folder_path)
    for condition in conditions:
        stmt = stmt.where(condition)
    rows = db.execute(stmt).all()

    total = 0
    ungrouped = 0
    nodes: dict[str, schemas.APICaseFolderNode] = {}
    roots: list[schemas.APICaseFolderNode] = []

    def ensure_node(path: str) -> schemas.APICaseFolderNode:
        node = nodes.get(path)
        if node is not None:
            return node
        node = schemas.APICaseFolderNode(path=path, name=path.rsplit("/", 1)[-1])
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

    def sort_nodes(items: list[schemas.APICaseFolderNode]) -> None:
        items.sort(key=lambda node: node.name)
        for child in items:
            sort_nodes(child.children)

    sort_nodes(roots)
    return schemas.APICaseFolderTree(total=total, ungrouped=ungrouped, folders=roots)


@router.post(
    "/api-cases/folders/rename",
    response_model=schemas.APICaseBatchResult,
    dependencies=[Depends(require_tester)],
    summary="重命名接口用例目录",
)
def rename_api_case_folder(
    payload: schemas.APICaseFolderRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.APICaseBatchResult:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    old_path = payload.old_path.strip().strip("/")
    new_path = payload.new_path.strip().strip("/")
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="目录路径不能为空")
    if old_path == new_path:
        return schemas.APICaseBatchResult(affected=0)
    cases = list(
        db.scalars(
            select(APICase).where(
                APICase.project_id == payload.project_id,
                or_(APICase.folder_path == old_path, APICase.folder_path.like(f"{old_path}/%")),
            )
        ).all()
    )
    for case in cases:
        current = case.folder_path or ""
        case.folder_path = new_path + current[len(old_path):]
        case.updated_by = current_user.id
        cases_domain._record_case_history(
            db,
            case_type="API",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"目录重命名 {old_path} → {new_path}",
        )
    db.commit()
    return schemas.APICaseBatchResult(affected=len(cases))


@router.get("/api-cases/stats", response_model=schemas.APICaseStats, summary="获取接口用例统计信息")
def get_api_case_stats(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.APICaseStats:
    conditions = _api_case_scope_conditions(db, current_user, project_id)
    if conditions is None:
        return schemas.APICaseStats()
    base = select(func.count(APICase.id))
    for condition in conditions:
        base = base.where(condition)
    total = db.scalar(base) or 0
    active = db.scalar(base.where(APICase.status == "ACTIVE")) or 0
    approved = db.scalar(base.where(APICase.review_status == "APPROVED")) or 0

    runs_stmt = select(TestRun.status).where(TestRun.case_type == "API")
    if project_id:
        runs_stmt = runs_stmt.where(TestRun.project_id == project_id)
    elif current_user.role != "admin":
        runs_stmt = runs_stmt.where(TestRun.project_id.in_(_accessible_project_ids(db, current_user)))
    statuses = list(db.scalars(runs_stmt.order_by(TestRun.id.desc()).limit(50)).all())
    finished = [item for item in statuses if item in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}]
    rate = None
    if finished:
        rate = round(sum(1 for item in finished if item == "SUCCESS") / len(finished), 4)
    return schemas.APICaseStats(total=total, active=active, approved=approved, recent_success_rate=rate)


@router.put(
    "/api-cases/batch",
    response_model=schemas.APICaseBatchResult,
    dependencies=[Depends(require_tester)],
    summary="批量更新接口用例",
)
def batch_update_api_cases(
    payload: schemas.APICaseBatchUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.APICaseBatchResult:
    patch = payload.patch.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(APICase).where(APICase.id.in_(case_ids))).all())
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
            case_type="API",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"批量更新属性：{', '.join(sorted(patch.keys()))}",
        )
    db.commit()
    return schemas.APICaseBatchResult(affected=len(cases))


@router.delete(
    "/api-cases/batch",
    response_model=schemas.APICaseBatchResult,
    dependencies=[Depends(require_admin)],
    summary="批量删除接口用例",
)
def batch_delete_api_cases(
    payload: schemas.APICaseBatchDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.APICaseBatchResult:
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(APICase).where(APICase.id.in_(case_ids))).all())
    if len(cases) != len(case_ids):
        raise HTTPException(status_code=404, detail="部分用例不存在")
    for case in cases:
        cases_domain._record_case_history(
            db,
            case_type="API",
            case=case,
            action="DELETE",
            changed_by=current_user.id,
            summary="批量删除接口用例",
        )
        db.execute(
            delete(TestPlanCase).where(TestPlanCase.case_type == "API", TestPlanCase.case_id == case.id)
        )
        db.delete(case)
    db.commit()
    return schemas.APICaseBatchResult(affected=len(cases))


@router.get("/api-cases/{case_id}", response_model=schemas.APICaseRead, summary="获取接口用例详情")
def get_api_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APICase:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    _require_project_access(db, current_user, db.get(Project, api_case.project_id))
    _ensure_case_defaults(api_case)
    return api_case


@router.put(
    "/api-cases/{case_id}",
    response_model=schemas.APICaseRead,
    dependencies=[Depends(require_tester)],
    summary="更新接口用例",
)
def update_api_case(
    case_id: int,
    payload: schemas.APICaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APICase:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    _require_project_access(db, current_user, db.get(Project, api_case.project_id))
    _reject_case_project_reassignment(api_case.project_id, payload.project_id)
    original_review_status = (api_case.review_status or "DRAFT").upper()
    original_signature = (
        api_case.name,
        api_case.folder_path,
        api_case.method,
        api_case.path,
        api_case.priority,
        api_case.status,
        tuple(api_case.tags_json or []),
        api_case.expected_status,
        api_case.headers_json,
        api_case.body_json,
        api_case.assertions_json,
        api_case.extractors_json,
        api_case.steps_json,
        api_case.datasets_json,
        api_case.mock_enabled,
        api_case.mock_config_json,
    )
    data = payload.model_dump(exclude={"project_id", "review_status", "review_note"})
    data["method"] = data["method"].upper()
    for key, value in data.items():
        setattr(api_case, key, value)
    new_signature = (
        api_case.name,
        api_case.folder_path,
        api_case.method,
        api_case.path,
        api_case.priority,
        api_case.status,
        tuple(api_case.tags_json or []),
        api_case.expected_status,
        api_case.headers_json,
        api_case.body_json,
        api_case.assertions_json,
        api_case.extractors_json,
        api_case.steps_json,
        api_case.datasets_json,
        api_case.mock_enabled,
        api_case.mock_config_json,
    )
    if new_signature != original_signature:
        api_case.version_no = _bump_version(api_case.version_no)
        if original_review_status in {"APPROVED", "IN_REVIEW"}:
            api_case.review_status = "DRAFT"
            api_case.reviewed_by = None
            api_case.reviewed_at = None
            api_case.submitted_review_at = None
    api_case.updated_by = current_user.id
    cases_domain._record_case_history(db, case_type="API", case=api_case, action="UPDATE", changed_by=current_user.id, summary="更新接口用例")
    db.commit()
    db.refresh(api_case)
    return api_case


@router.delete("/api-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除接口用例")
def delete_api_case(case_id: int, db: Session = Depends(get_db)) -> None:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")

    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "API", TestPlanCase.case_id == case_id)
    )
    db.delete(api_case)
    db.commit()


@router.post(
    "/api-cases/{case_id}/review/submit",
    response_model=schemas.APICaseRead,
    dependencies=[Depends(require_tester)],
    summary="提交接口用例评审",
)
def submit_api_case_review(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APICase:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    _require_project_access(db, current_user, db.get(Project, api_case.project_id))
    _ensure_case_defaults(api_case)
    current_status = (api_case.review_status or "DRAFT").upper()
    if current_status not in {"DRAFT", "REJECTED"}:
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不能提交评审")
    api_case.review_status = "IN_REVIEW"
    api_case.submitted_review_at = utc_now_naive()
    api_case.reviewed_by = None
    api_case.reviewed_at = None
    api_case.updated_by = current_user.id
    cases_domain._record_case_history(db, case_type="API", case=api_case, action="REVIEW", changed_by=current_user.id, summary="提交评审")
    db.commit()
    db.refresh(api_case)
    return api_case


@router.post(
    "/api-cases/{case_id}/review/decide",
    response_model=schemas.APICaseRead,
    dependencies=[Depends(require_tester)],
    summary="审批接口用例评审",
)
def decide_api_case_review(
    case_id: int,
    payload: schemas.APICaseReviewDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APICase:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    if api_case.created_by is not None and api_case.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
    _require_project_member(db, current_user, db.get(Project, api_case.project_id))
    _ensure_case_defaults(api_case)
    current_status = (api_case.review_status or "DRAFT").upper()
    if current_status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不在评审中")
    api_case.review_status = payload.result
    api_case.review_note = payload.note
    api_case.reviewed_by = current_user.id
    api_case.reviewed_at = utc_now_naive()
    api_case.updated_by = current_user.id
    cases_domain._record_case_history(
        db,
        case_type="API",
        case=api_case,
        action="REVIEW",
        changed_by=current_user.id,
        summary="评审通过" if payload.result == "APPROVED" else "评审拒绝",
    )
    db.commit()
    db.refresh(api_case)
    return api_case
