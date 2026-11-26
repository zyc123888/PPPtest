"""测试报告、报告公开分享与执行缺陷记录路由。"""

import json
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from xml.etree import ElementTree as ET
from app import schemas
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Defect,
    DefectCaseLink,
    DefectRecord,
    DefectRunLink,
    Environment,
    Project,
    TestPlan,
    TestPlanRun,
    TestRun,
    User,
)
from app.rich_text_security import plain_text_to_safe_html
from app.timeutil import utc_now_naive
from app.deps.auth import (
    _accessible_project_ids,
    _require_project_access,
    _require_project_member,
    get_current_user,
    require_admin,
    require_tester,
)
from app.domain.cases import _normalize_case_type
from app.domain.reports import (
    _assemble_report_detail,
    _build_report_insights,
    _collect_failure_reason_map,
    _report_share_url,
    _serialize_plan_run,
    _summarize_failure_reasons,
)

router = APIRouter(tags=["reports"])
public_router = APIRouter(tags=["reports"])
defects_router = APIRouter(tags=["defects"])


@router.get("/reports", response_model=list[schemas.TestPlanRunView], summary="获取测试计划报告列表")
def list_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.TestPlanRunView]:
    stmt = select(TestPlanRun).order_by(TestPlanRun.id.desc()).limit(50)
    if current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(TestPlanRun.project_id.in_(project_ids))
    runs = list(db.scalars(stmt).all())
    failure_reason_map = _collect_failure_reason_map(db, [run.id for run in runs])
    result = []
    for run in runs:
        plan = db.get(TestPlan, run.plan_id)
        project = db.get(Project, run.project_id)
        environment = db.get(Environment, run.environment_id) if run.environment_id else None
        base_payload = _serialize_plan_run(run).model_dump()
        failure_reason_counts = failure_reason_map.get(run.id, {})
        result.append(
            schemas.TestPlanRunView(
                **base_payload,
                plan_name=plan.name if plan else "-",
                project_name=project.name if project else "-",
                environment_name=environment.name if environment else None,
                failure_reason_counts=failure_reason_counts,
                failure_reason_summary=_summarize_failure_reasons(failure_reason_counts),
            )
        )
    return result


@router.get("/reports/insights", response_model=schemas.ReportInsights, summary="获取测试报告质量趋势洞察")
def get_report_insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ReportInsights:
    stmt = select(TestPlanRun).order_by(TestPlanRun.id.desc()).limit(50)
    if current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.ReportInsights(
                report_count=0,
                success_count=0,
                failed_count=0,
                failed_case_count=0,
                config_fail_count=0,
                success_rate=0.0,
                average_pass_rate=0.0,
                average_duration_ms=None,
                failure_reason_counts={},
                failure_reason_summary=[],
                recent_trend=[],
                plan_histories=[],
            )
        stmt = stmt.where(TestPlanRun.project_id.in_(project_ids))
    runs = list(db.scalars(stmt).all())
    plan_ids = sorted({run.plan_id for run in runs})
    plans_by_id = {plan.id: plan for plan in db.scalars(select(TestPlan).where(TestPlan.id.in_(plan_ids))).all()} if plan_ids else {}
    failure_reason_map = _collect_failure_reason_map(db, [run.id for run in runs])
    return _build_report_insights(runs, plans_by_id, failure_reason_map)


@router.get("/reports/{plan_run_id}", response_model=schemas.ReportDetail, summary="获取测试报告详情")
def get_report(
    plan_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ReportDetail:
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    _require_project_access(db, current_user, db.get(Project, plan_run.project_id))
    return _assemble_report_detail(db, plan_run)


@router.get("/reports/{plan_run_id}/download", summary="下载测试报告文件（JSON/JUnit）")
def download_report_file(
    plan_run_id: int,
    format: str = Query(default="json", pattern="^(json|junit)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    _require_project_access(db, current_user, db.get(Project, plan_run.project_id))
    file_path = plan_run.report_json_path if format == "json" else plan_run.report_junit_path

    if not file_path or not os.path.exists(file_path):
        runs = list(
            db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id).order_by(TestRun.id.asc())).all()
        )
        root_dir = settings.report_output_dir
        if not os.path.isabs(root_dir):
            root_dir = os.path.abspath(root_dir)
        plan_dir = os.path.join(root_dir, f"plan_run_{plan_run.id}")
        os.makedirs(plan_dir, exist_ok=True)

        summary_path = os.path.join(plan_dir, "summary.json")
        junit_path = os.path.join(plan_dir, "junit.xml")

        summary_payload = {
            "plan_run": _serialize_plan_run(plan_run).model_dump(mode="json"),
            "test_runs": [schemas.TestRunRead.model_validate(run).model_dump(mode="json") for run in runs],
        }
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump(summary_payload, handle, ensure_ascii=False, indent=2)

        testcases = []
        total_seconds = 0.0
        failures = 0
        for run in runs:
            case_time = float((run.duration_ms or 0) / 1000)
            total_seconds += case_time
            testcases.append((run, case_time))
            if run.status != "SUCCESS":
                failures += 1

        suite_name = f"test-plan-{plan_run.id}"
        root = ET.Element(
            "testsuite",
            {
                "name": suite_name,
                "tests": str(len(runs)),
                "failures": str(failures),
                "errors": "0",
                "skipped": "0",
                "time": f"{total_seconds:.3f}",
            },
        )

        for run, case_time in testcases:
            case_name = run.case_name or f"{run.case_type}-{run.case_id}"
            class_name = run.case_type or "CASE"
            tc = ET.SubElement(
                root,
                "testcase",
                {
                    "classname": class_name,
                    "name": case_name,
                    "time": f"{case_time:.3f}",
                },
            )
            if run.status != "SUCCESS":
                message = run.summary or "执行失败"
                failure = ET.SubElement(tc, "failure", {"message": message})
                failure.text = message

        ET.ElementTree(root).write(junit_path, encoding="utf-8", xml_declaration=True)

        plan_run.report_json_path = summary_path
        plan_run.report_junit_path = junit_path
        plan_run.report_generated_at = utc_now_naive()
        db.commit()
        db.refresh(plan_run)

        file_path = plan_run.report_json_path if format == "json" else plan_run.report_junit_path

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="报告文件不存在")
    media_type = "application/json" if format == "json" else "application/xml"
    filename = f"plan_run_{plan_run.id}.{format if format == 'json' else 'xml'}"
    return FileResponse(path=file_path, media_type=media_type, filename=filename)


@router.post(
    "/reports/{plan_run_id}/share",
    response_model=schemas.ReportShareResult,
    dependencies=[Depends(require_tester)],
    summary="开启测试报告公开分享链接",
)
def enable_report_share(
    plan_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ReportShareResult:
    """为报告生成（或复用）公开分享链接 token，无需登录即可访问。"""
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    _require_project_member(db, current_user, db.get(Project, plan_run.project_id), "manager")
    if not plan_run.share_token:
        plan_run.share_token = secrets.token_urlsafe(24)
        db.commit()
        db.refresh(plan_run)
    return schemas.ReportShareResult(
        plan_run_id=plan_run.id,
        share_token=plan_run.share_token,
        share_url=_report_share_url(plan_run.share_token),
        enabled=True,
    )


@router.delete(
    "/reports/{plan_run_id}/share",
    response_model=schemas.ReportShareResult,
    dependencies=[Depends(require_tester)],
    summary="关闭测试报告公开分享链接",
)
def disable_report_share(
    plan_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ReportShareResult:
    """关闭报告分享，使已发出的链接失效。"""
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    _require_project_member(db, current_user, db.get(Project, plan_run.project_id), "manager")
    plan_run.share_token = None
    db.commit()
    db.refresh(plan_run)
    return schemas.ReportShareResult(
        plan_run_id=plan_run.id,
        share_token=None,
        share_url="",
        enabled=False,
    )


@public_router.get("/public/reports/{share_token}", response_model=schemas.PublicReportDetail, summary="匿名访问公开分享的测试报告")
def get_shared_report(
    share_token: str,
    db: Session = Depends(get_db),
) -> schemas.PublicReportDetail:
    """通过分享 token 匿名访问报告详情（无需登录）。"""
    plan_run = db.scalar(select(TestPlanRun).where(TestPlanRun.share_token == share_token))
    if plan_run is None:
        raise HTTPException(status_code=404, detail="分享链接无效或已失效")
    detail = _assemble_report_detail(db, plan_run)
    return schemas.PublicReportDetail(
        plan_run=schemas.PublicTestPlanRunRead.model_validate(
            detail.plan_run.model_dump()
        ),
        test_runs=[
            schemas.PublicTestRunRead.model_validate(run.model_dump())
            for run in detail.test_runs
        ],
        recent_history=detail.recent_history,
    )


@defects_router.get("/defects", response_model=list[schemas.DefectRecordRead], summary="获取执行缺陷记录列表")
def list_defects(
    project_id: int | None = None,
    run_id: int | None = None,
    plan_run_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DefectRecord]:
    stmt = select(DefectRecord).order_by(DefectRecord.id.desc())
    target_project_id = project_id
    if run_id is not None:
        run = db.get(TestRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="执行记录不存在")
        target_project_id = run.project_id
        stmt = stmt.where(DefectRecord.run_id == run_id)
    if plan_run_id is not None:
        plan_run = db.get(TestPlanRun, plan_run_id)
        if plan_run is None:
            raise HTTPException(status_code=404, detail="报告不存在")
        target_project_id = plan_run.project_id
        stmt = stmt.where(DefectRecord.plan_run_id == plan_run_id)
    if target_project_id is not None:
        _require_project_access(db, current_user, db.get(Project, target_project_id))
        stmt = stmt.where(DefectRecord.project_id == target_project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(DefectRecord.project_id.in_(project_ids))
    return list(db.scalars(stmt).all())


@defects_router.post("/defects", response_model=schemas.DefectRecordRead, status_code=201, dependencies=[Depends(require_tester)], summary="创建执行缺陷记录")
def create_defect(
    payload: schemas.DefectRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DefectRecord:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    run = None
    if payload.run_id is not None:
        run = db.get(TestRun, payload.run_id)
        if run is None or run.project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="关联执行不存在或不属于该项目")
    if payload.plan_run_id is not None:
        plan_run = db.get(TestPlanRun, payload.plan_run_id)
        if plan_run is None or plan_run.project_id != payload.project_id:
            raise HTTPException(status_code=400, detail="关联报告不存在或不属于该项目")
    defect = DefectRecord(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(defect)
    db.flush()

    status_map = {"OPEN": "NEW", "FIXING": "IN_PROGRESS", "RESOLVED": "RESOLVED", "CLOSED": "CLOSED"}
    max_order = db.scalar(select(func.max(Defect.order_index)).where(Defect.project_id == payload.project_id)) or 0.0
    ws_defect = Defect(
        project_id=payload.project_id,
        title=payload.title[:200],
        description=plain_text_to_safe_html(payload.summary),
        severity=payload.severity if payload.severity in {"BLOCKER", "CRITICAL", "MAJOR", "MINOR", "TRIVIAL"} else "MAJOR",
        priority="P1",
        status=status_map.get(payload.status, "NEW"),
        reporter_id=current_user.id,
        created_by=current_user.id,
        updated_by=current_user.id,
        order_index=max_order + 1000.0,
    )
    db.add(ws_defect)
    db.flush()
    if run is not None:
        db.add(DefectRunLink(defect_id=ws_defect.id, test_run_id=run.id))
        if run.case_type and run.case_id:
            db.add(
                DefectCaseLink(
                    defect_id=ws_defect.id,
                    case_type=_normalize_case_type(run.case_type),
                    case_id=run.case_id,
                )
            )

    db.commit()
    db.refresh(defect)
    return defect


@defects_router.put("/defects/{defect_id}", response_model=schemas.DefectRecordRead, dependencies=[Depends(require_tester)], summary="更新执行缺陷记录")
def update_defect(
    defect_id: int,
    payload: schemas.DefectRecordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DefectRecord:
    defect = db.get(DefectRecord, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷记录不存在")
    _require_project_access(db, current_user, db.get(Project, defect.project_id))
    old_title = defect.title
    for key, value in payload.model_dump().items():
        setattr(defect, key, value)
    defect.updated_by = current_user.id

    status_map = {"OPEN": "NEW", "FIXING": "IN_PROGRESS", "RESOLVED": "RESOLVED", "CLOSED": "CLOSED"}
    ws_defect = db.scalar(
        select(Defect)
        .where(Defect.project_id == defect.project_id, Defect.title == old_title)
        .order_by(Defect.id.desc())
    )
    if ws_defect is not None:
        ws_defect.title = defect.title[:200]
        ws_defect.description = plain_text_to_safe_html(defect.summary)
        if defect.severity in {"BLOCKER", "CRITICAL", "MAJOR", "MINOR", "TRIVIAL"}:
            ws_defect.severity = defect.severity
        ws_defect.status = status_map.get(defect.status, ws_defect.status)
        ws_defect.updated_by = current_user.id

    db.commit()
    db.refresh(defect)
    return defect


@defects_router.delete("/defects/{defect_id}", status_code=204, dependencies=[Depends(require_admin)], summary="删除执行缺陷记录")
def delete_defect(defect_id: int, db: Session = Depends(get_db)) -> None:
    defect = db.get(DefectRecord, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷记录不存在")
    db.delete(defect)
    db.commit()
