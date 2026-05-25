import json
import os
import re
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.config import settings
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models import (
    APICase,
    CaseChangeHistory,
    DefectRecord,
    Environment,
    ExecutionArtifact,
    ExecutionLog,
    ExecutionStep,
    PerformanceCase,
    Project,
    TestPlan,
    TestPlanCase,
    TestPlanRun,
    TestRun,
    UICase,
    User,
    Workspace,
    WorkspaceMember,
)
from app.tasks.executions import run_api_case, run_performance_case, run_test_plan, run_ui_case
from app.timeutil import utc_now_naive


auth_scheme = HTTPBearer(auto_error=False)
_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    user = services.get_user_by_token(db, credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
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


def _require_project_access(db: Session, user: User, project: Project | None) -> Project:
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    _require_workspace_access(db, user, project.workspace_id)
    return project


def _accessible_project_ids(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(db.scalars(select(Project.id)).all())
    workspace_ids = _workspace_ids_for_user(db, user)
    if not workspace_ids:
        return []
    return list(db.scalars(select(Project.id).where(Project.workspace_id.in_(workspace_ids))).all())


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
        select(WorkspaceMember.workspace_id, Workspace.name, WorkspaceMember.role)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.name.asc())
    ).all()
    return [
        schemas.UserWorkspaceMembership(
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            role=role,
        )
        for workspace_id, workspace_name, role in rows
    ]


def _serialize_user(db: Session, user: User) -> schemas.UserRead:
    payload = schemas.UserRead.model_validate(user).model_dump()
    payload["workspaces"] = _workspace_names_for_user(db, user.id)
    payload["workspace_memberships"] = _workspace_memberships_for_user(db, user.id)
    return schemas.UserRead(**payload)


def _serialize_environment_variables(env: Environment) -> schemas.EnvironmentVariablesUpdate:
    return schemas.EnvironmentVariablesUpdate(
        variables_json=env.variables_json,
        headers_json=env.headers_json,
        auth_config_json=env.auth_config_json,
    )


def _collect_missing_template_issues(value, variables: dict | None, *, scope: str, field: str) -> list[schemas.EnvironmentValidationIssue]:
    issues: list[schemas.EnvironmentValidationIssue] = []
    known_variables = variables or {}

    if isinstance(value, str):
        missing = sorted({key for key in _TEMPLATE_VAR_PATTERN.findall(value) if key not in known_variables})
        if missing:
            issues.append(
                schemas.EnvironmentValidationIssue(
                    scope=scope,
                    field=field,
                    missing_variables=missing,
                    sample=value[:200],
                )
            )
        return issues
    if isinstance(value, dict):
        for key, item in value.items():
            issues.extend(
                _collect_missing_template_issues(
                    item,
                    variables,
                    scope=scope,
                    field=f"{field}.{key}",
                )
            )
        return issues
    if isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(
                _collect_missing_template_issues(
                    item,
                    variables,
                    scope=scope,
                    field=f"{field}[{index}]",
                )
            )
        return issues
    return issues


def _validate_environment_usage(db: Session, env: Environment) -> schemas.EnvironmentValidationResult:
    variables = env.variables_json or {}
    issues: list[schemas.EnvironmentValidationIssue] = []

    issues.extend(
        _collect_missing_template_issues(
            env.base_url,
            variables,
            scope=f"environment:{env.name}",
            field="base_url",
        )
    )
    issues.extend(
        _collect_missing_template_issues(
            env.headers_json,
            variables,
            scope=f"environment:{env.name}",
            field="headers_json",
        )
    )
    issues.extend(
        _collect_missing_template_issues(
            env.auth_config_json,
            variables,
            scope=f"environment:{env.name}",
            field="auth_config_json",
        )
    )

    api_cases = list(db.scalars(select(APICase).where(APICase.project_id == env.project_id).order_by(APICase.id.asc())).all())
    for case in api_cases:
        case_scope = f"api_case:{case.name}"
        issues.extend(_collect_missing_template_issues(case.path, variables, scope=case_scope, field="path"))
        issues.extend(_collect_missing_template_issues(case.headers_json, variables, scope=case_scope, field="headers_json"))
        issues.extend(_collect_missing_template_issues(case.body_json, variables, scope=case_scope, field="body_json"))

    ui_cases = list(db.scalars(select(UICase).where(UICase.project_id == env.project_id).order_by(UICase.id.asc())).all())
    for case in ui_cases:
        case_scope = f"ui_case:{case.name}"
        issues.extend(_collect_missing_template_issues(case.target_url, variables, scope=case_scope, field="target_url"))
        issues.extend(_collect_missing_template_issues(case.expect_text, variables, scope=case_scope, field="expect_text"))
        issues.extend(_collect_missing_template_issues(case.steps_json, variables, scope=case_scope, field="steps_json"))

    summary, scope_counts, missing_variables = _summarize_precheck_issues(issues)
    return schemas.EnvironmentValidationResult(
        environment_id=env.id,
        project_id=env.project_id,
        is_valid=len(issues) == 0,
        issue_count=len(issues),
        summary=summary,
        scope_counts=scope_counts,
        missing_variables=missing_variables,
        issues=issues,
    )


def _build_validation_result_for_environment(db: Session, env: Environment) -> schemas.EnvironmentValidationResult:
    return _validate_environment_usage(db, env)


def _scope_bucket(scope: str) -> str:
    return scope.split(":", 1)[0] if ":" in scope else scope


def _summarize_precheck_issues(issues: list[schemas.EnvironmentValidationIssue]) -> tuple[str, dict[str, int], list[str]]:
    scope_counts: dict[str, int] = {}
    missing_variables = sorted({name for issue in issues for name in issue.missing_variables})
    for issue in issues:
        bucket = _scope_bucket(issue.scope)
        scope_counts[bucket] = scope_counts.get(bucket, 0) + 1

    if not issues:
        return "未发现缺失变量", scope_counts, missing_variables

    ordered_buckets = ["environment", "project", "api_case", "ui_case"]
    labels = {
        "environment": "环境字段",
        "project": "项目字段",
        "api_case": "API 用例",
        "ui_case": "UI 用例",
    }
    parts = []
    for bucket in ordered_buckets:
        count = scope_counts.get(bucket)
        if count:
            parts.append(f"{count} 个{labels.get(bucket, bucket)}")
    for bucket, count in scope_counts.items():
        if bucket not in ordered_buckets:
            parts.append(f"{count} 个{bucket}")
    return "存在缺失变量：" + "，".join(parts), scope_counts, missing_variables


def _error_type_text(error_type: str) -> str:
    mapping = {
        "CONFIG": "预检失败",
        "ASSERTION": "断言失败",
        "SYSTEM": "系统异常",
        "TIMEOUT": "超时",
        "CANCELLED": "已取消",
    }
    return mapping.get(error_type, error_type)


def _summarize_failure_reasons(counts: dict[str, int]) -> list[str]:
    return [
        f"{_error_type_text(error_type)} {count}"
        for error_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _pass_rate(pass_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((pass_count / total_count) * 100, 1)


def _collect_failure_reason_map(db: Session, plan_run_ids: list[int]) -> dict[int, dict[str, int]]:
    if not plan_run_ids:
        return {}
    rows = db.execute(
        select(TestRun.plan_run_id, TestRun.error_type, func.count(TestRun.id))
        .where(
            TestRun.plan_run_id.in_(plan_run_ids),
            TestRun.status != "SUCCESS",
            TestRun.error_type.is_not(None),
        )
        .group_by(TestRun.plan_run_id, TestRun.error_type)
    ).all()
    result: dict[int, dict[str, int]] = {}
    for plan_run_id, error_type, count in rows:
        bucket = result.setdefault(plan_run_id, {})
        bucket[error_type] = count
    return result


def _build_report_insights(
    runs: list[TestPlanRun],
    plans_by_id: dict[int, TestPlan | None],
    failure_reason_map: dict[int, dict[str, int]],
) -> schemas.ReportInsights:
    report_count = len(runs)
    success_count = sum(1 for run in runs if run.status == "SUCCESS")
    failed_count = report_count - success_count
    failed_case_count = sum(run.fail_count or 0 for run in runs)
    config_fail_count = sum(failure_reason_map.get(run.id, {}).get("CONFIG", 0) for run in runs)
    success_rate = round((success_count / report_count) * 100, 1) if report_count else 0.0
    average_pass_rate = round(
        sum(_pass_rate(run.pass_count or 0, run.total_count or 0) for run in runs) / report_count, 1
    ) if report_count else 0.0
    duration_values = [run.duration_ms for run in runs if run.duration_ms is not None]
    average_duration_ms = int(sum(duration_values) / len(duration_values)) if duration_values else None

    overall_reason_counts: dict[str, int] = {}
    for counts in failure_reason_map.values():
        for error_type, count in counts.items():
            overall_reason_counts[error_type] = overall_reason_counts.get(error_type, 0) + count

    recent_trend = [
        schemas.ReportTrendPoint(
            plan_run_id=run.id,
            plan_id=run.plan_id,
            plan_name=plans_by_id.get(run.plan_id).name if plans_by_id.get(run.plan_id) else "-",
            status=run.status,
            error_type=run.error_type,
            pass_rate=_pass_rate(run.pass_count or 0, run.total_count or 0),
            fail_count=run.fail_count or 0,
            created_at=run.created_at,
            duration_ms=run.duration_ms,
        )
        for run in runs[:10]
    ]
    recent_window = runs[:10]
    older_window = runs[10:20]
    recent_success_rate = round(
        (sum(1 for run in recent_window if run.status == "SUCCESS") / len(recent_window)) * 100, 1
    ) if recent_window else success_rate
    older_success_rate = round(
        (sum(1 for run in older_window if run.status == "SUCCESS") / len(older_window)) * 100, 1
    ) if older_window else recent_success_rate
    success_rate_delta = round(recent_success_rate - older_success_rate, 1)

    runs_by_plan: dict[int, list[TestPlanRun]] = {}
    for run in runs:
        runs_by_plan.setdefault(run.plan_id, []).append(run)

    plan_histories: list[schemas.ReportPlanHistory] = []
    flaky_plan_count = 0
    for plan_id, plan_runs in runs_by_plan.items():
        ordered_runs = sorted(plan_runs, key=lambda item: item.id, reverse=True)
        latest = ordered_runs[0]
        latest_rate = _pass_rate(latest.pass_count or 0, latest.total_count or 0)
        previous_rate = _pass_rate(ordered_runs[1].pass_count or 0, ordered_runs[1].total_count or 0) if len(ordered_runs) > 1 else latest_rate
        avg_rate = round(
            sum(_pass_rate(item.pass_count or 0, item.total_count or 0) for item in ordered_runs) / len(ordered_runs), 1
        )
        history_duration_values = [item.duration_ms for item in ordered_runs if item.duration_ms is not None]
        reason_counts: dict[str, int] = {}
        for item in ordered_runs:
            for error_type, count in failure_reason_map.get(item.id, {}).items():
                reason_counts[error_type] = reason_counts.get(error_type, 0) + count
        status_set = {item.status for item in ordered_runs[:5]}
        if "SUCCESS" in status_set and any(status in {"FAILED", "ERROR", "TIMEOUT"} for status in status_set):
            flaky_plan_count += 1
        plan = plans_by_id.get(plan_id)
        plan_histories.append(
            schemas.ReportPlanHistory(
                plan_id=plan_id,
                plan_name=plan.name if plan else "-",
                latest_plan_run_id=latest.id,
                latest_status=latest.status,
                latest_error_type=latest.error_type,
                latest_created_at=latest.created_at,
                latest_pass_rate=latest_rate,
                average_pass_rate=avg_rate,
                pass_rate_delta=round(latest_rate - previous_rate, 1),
                latest_fail_count=latest.fail_count or 0,
                average_duration_ms=int(sum(history_duration_values) / len(history_duration_values))
                if history_duration_values
                else None,
                run_count=len(ordered_runs),
                failure_reason_counts=reason_counts,
                failure_reason_summary=_summarize_failure_reasons(reason_counts),
            )
        )
    plan_histories.sort(key=lambda item: (item.latest_created_at is None, item.latest_created_at), reverse=True)
    unstable_run_count = sum(
        1 for run in runs if (run.fail_count or 0) > 0 or run.error_type in {"CONFIG", "SYSTEM", "TIMEOUT"}
    )
    quality_score = round(
        max(
            0.0,
            min(
                100.0,
                success_rate * 0.45
                + average_pass_rate * 0.35
                + max(0.0, 100 - min((average_duration_ms or 0) / 50, 100)) * 0.1
                + max(0.0, 100 - min(config_fail_count * 5, 100)) * 0.1,
            ),
        ),
        1,
    )

    return schemas.ReportInsights(
        report_count=report_count,
        success_count=success_count,
        failed_count=failed_count,
        failed_case_count=failed_case_count,
        config_fail_count=config_fail_count,
        success_rate=success_rate,
        average_pass_rate=average_pass_rate,
        average_duration_ms=average_duration_ms,
        success_rate_delta=success_rate_delta,
        quality_score=quality_score,
        flaky_plan_count=flaky_plan_count,
        unstable_run_count=unstable_run_count,
        failure_reason_counts=overall_reason_counts,
        failure_reason_summary=_summarize_failure_reasons(overall_reason_counts),
        recent_trend=recent_trend,
        plan_histories=plan_histories[:8],
    )


def _validation_issues_for_api_case(case: APICase, variables: dict | None) -> list[schemas.EnvironmentValidationIssue]:
    case_scope = f"api_case:{case.name}"
    issues: list[schemas.EnvironmentValidationIssue] = []
    issues.extend(_collect_missing_template_issues(case.path, variables, scope=case_scope, field="path"))
    issues.extend(_collect_missing_template_issues(case.headers_json, variables, scope=case_scope, field="headers_json"))
    issues.extend(_collect_missing_template_issues(case.body_json, variables, scope=case_scope, field="body_json"))
    return issues


def _validation_issues_for_ui_case(case: UICase, variables: dict | None) -> list[schemas.EnvironmentValidationIssue]:
    case_scope = f"ui_case:{case.name}"
    issues: list[schemas.EnvironmentValidationIssue] = []
    issues.extend(_collect_missing_template_issues(case.target_url, variables, scope=case_scope, field="target_url"))
    issues.extend(_collect_missing_template_issues(case.expect_text, variables, scope=case_scope, field="expect_text"))
    issues.extend(_collect_missing_template_issues(case.steps_json, variables, scope=case_scope, field="steps_json"))
    return issues


def _validation_issues_for_performance_case(
    case: PerformanceCase, variables: dict | None
) -> list[schemas.EnvironmentValidationIssue]:
    case_scope = f"performance_case:{case.name}"
    issues: list[schemas.EnvironmentValidationIssue] = []
    issues.extend(_collect_missing_template_issues(case.path, variables, scope=case_scope, field="path"))
    issues.extend(_collect_missing_template_issues(case.headers_json, variables, scope=case_scope, field="headers_json"))
    issues.extend(_collect_missing_template_issues(case.body_json, variables, scope=case_scope, field="body_json"))
    return issues


def _validation_issues_for_environment_runtime(env: Environment | None, project: Project) -> list[schemas.EnvironmentValidationIssue]:
    if env is None:
        return _collect_missing_template_issues(project.base_url, {}, scope=f"project:{project.name}", field="base_url")
    variables = env.variables_json or {}
    issues: list[schemas.EnvironmentValidationIssue] = []
    issues.extend(_collect_missing_template_issues(env.base_url, variables, scope=f"environment:{env.name}", field="base_url"))
    issues.extend(
        _collect_missing_template_issues(env.headers_json, variables, scope=f"environment:{env.name}", field="headers_json")
    )
    issues.extend(
        _collect_missing_template_issues(
            env.auth_config_json, variables, scope=f"environment:{env.name}", field="auth_config_json"
        )
    )
    return issues


def _build_execution_precheck_result(
    *,
    target_type: str,
    target_id: int,
    project: Project,
    environment: Environment | None,
    issues: list[schemas.EnvironmentValidationIssue],
) -> schemas.ExecutionPrecheckResult:
    summary, scope_counts, missing_variables = _summarize_precheck_issues(issues)
    return schemas.ExecutionPrecheckResult(
        target_type=target_type,
        target_id=target_id,
        project_id=project.id,
        environment_id=environment.id if environment else None,
        is_valid=len(issues) == 0,
        issue_count=len(issues),
        summary=summary,
        scope_counts=scope_counts,
        missing_variables=missing_variables,
        issues=issues,
    )


def _raise_precheck_failure(result: schemas.ExecutionPrecheckResult) -> None:
    if result.is_valid:
        return
    raise HTTPException(status_code=400, detail=f"执行预检失败：{result.summary}")


def _serialize_plan_run(plan_run: TestPlanRun) -> schemas.TestPlanRunRead:
    payload = {
        field: getattr(plan_run, field)
        for field in schemas.TestPlanRunRead.model_fields.keys()
    }
    payload["retry_count"] = payload.get("retry_count") or 0
    return schemas.TestPlanRunRead(**payload)


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
        "concurrency": getattr(case, "concurrency", None),
        "total_requests": getattr(case, "total_requests", None),
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
    payload = {
        "id": case.id,
        "name": case.name,
        "project_id": case.project_id,
        "type": "API" if isinstance(case, APICase) else "UI",
    }
    for field in ("method", "path", "target_url", "expect_text", "priority", "status", "expected_status"):
        if hasattr(case, field):
            payload[field] = getattr(case, field)
    for field in ("review_status", "version_no", "review_note"):
        if hasattr(case, field):
            payload[field] = getattr(case, field)
    return payload


def _ensure_case_defaults(case) -> None:
    if hasattr(case, "review_status") and not getattr(case, "review_status", None):
        case.review_status = "DRAFT"
    if hasattr(case, "version_no") and not getattr(case, "version_no", None):
        case.version_no = "1.0.0"


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
    owner_count = db.scalar(
        select(func.count(WorkspaceMember.id)).where(
            WorkspaceMember.workspace_id == member.workspace_id,
            WorkspaceMember.role == "owner",
        )
    )
    if owner_count == 1:
        raise HTTPException(status_code=400, detail="工作空间至少需要保留一个 Owner")


public_router = APIRouter()
protected_router = APIRouter(dependencies=[Depends(get_current_user)])


def _dispatch_task_or_run_inline(task_func, record_id: int) -> tuple[str | None, bool]:
    if (
        os.getenv("PYTEST_CURRENT_TEST")
        or settings.backend_internal_url.startswith("http://testserver")
        or settings.app_env == "local"
    ):
        task_func(record_id)
        return None, True
    try:
        task = task_func.delay(record_id)
        return task.id, False
    except Exception:
        task_func(record_id)
        return None, True


@public_router.get("/system/health", response_model=schemas.SystemHealth)
def system_health() -> schemas.SystemHealth:
    return schemas.SystemHealth(**services.collect_system_health())


@protected_router.get("/system/info", response_model=schemas.SystemInfo)
def system_info() -> schemas.SystemInfo:
    return schemas.SystemInfo(**services.collect_system_info())


@protected_router.post(
    "/system/bootstrap",
    response_model=schemas.SystemBootstrapResult,
    dependencies=[Depends(require_admin)],
)
def system_bootstrap(
    payload: schemas.SystemBootstrapRequest | None = Body(None),
) -> schemas.SystemBootstrapResult:
    should_seed = payload.seed_demo_data if payload is not None else settings.seed_demo_data_on_bootstrap
    return schemas.SystemBootstrapResult(**services.bootstrap_runtime(seed_demo_data_enabled=should_seed))


@public_router.post("/auth/login", response_model=schemas.AuthLoginResponse)
def login(payload: schemas.AuthLoginRequest, db: Session = Depends(get_db)) -> schemas.AuthLoginResponse:
    user = services.authenticate_user(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = services.issue_user_token(db, user)
    return schemas.AuthLoginResponse(token=token, user=_serialize_user(db, user))


@protected_router.post("/auth/logout", status_code=204)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> None:
    if credentials and credentials.credentials:
        services.revoke_user_token(db, credentials.credentials)


@protected_router.get("/auth/me", response_model=schemas.UserRead)
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> schemas.UserRead:
    return _serialize_user(db, current_user)


@protected_router.get("/dashboard/summary", response_model=schemas.DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.DashboardSummary:
    project_ids = None if current_user.role == "admin" else _accessible_project_ids(db, current_user)
    return schemas.DashboardSummary(**services.build_dashboard_summary(db, project_ids=project_ids))


@protected_router.get("/workspaces", response_model=list[schemas.WorkspaceRead])
def list_workspaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Workspace]:
    stmt = select(Workspace).order_by(Workspace.id.asc())
    if current_user.role != "admin":
        stmt = stmt.join(WorkspaceMember).where(WorkspaceMember.user_id == current_user.id)
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/workspaces",
    response_model=schemas.WorkspaceRead,
    status_code=201,
    dependencies=[Depends(require_admin)],
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


@protected_router.get(
    "/workspaces/{workspace_id}/members",
    response_model=list[schemas.WorkspaceMemberRead],
    dependencies=[Depends(require_admin)],
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
    result = []
    for member in members:
        user = db.get(User, member.user_id)
        result.append(
            schemas.WorkspaceMemberRead(
                id=member.id,
                workspace_id=member.workspace_id,
                user_id=member.user_id,
                username=user.username if user else None,
                display_name=user.display_name if user else None,
                role=member.role,
                created_at=member.created_at,
            )
        )
    return result


@protected_router.post(
    "/workspaces/{workspace_id}/members",
    response_model=schemas.WorkspaceMemberRead,
    status_code=201,
    dependencies=[Depends(require_admin)],
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


@protected_router.delete(
    "/workspaces/{workspace_id}/members/{member_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_workspace_member(workspace_id: int, member_id: int, db: Session = Depends(get_db)) -> None:
    member = db.get(WorkspaceMember, member_id)
    if member is None or member.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="成员不存在")
    _ensure_workspace_owner_guard(db, member, deleting=True)
    db.delete(member)
    db.commit()


@protected_router.put(
    "/workspaces/{workspace_id}/members/{member_id}",
    response_model=schemas.WorkspaceMemberRead,
    dependencies=[Depends(require_admin)],
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


@protected_router.get("/projects", response_model=list[schemas.ProjectRead])
def list_projects(
    workspace_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Project]:
    stmt = select(Project).order_by(Project.id.asc())
    if workspace_id:
        _require_workspace_access(db, current_user, workspace_id)
        stmt = stmt.where(Project.workspace_id == workspace_id)
    elif current_user.role != "admin":
        workspace_ids = _workspace_ids_for_user(db, current_user)
        if not workspace_ids:
            return []
        stmt = stmt.where(Project.workspace_id.in_(workspace_ids))
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/projects",
    response_model=schemas.ProjectRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
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


@protected_router.delete("/projects/{project_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    plan_ids = list(db.scalars(select(TestPlan.id).where(TestPlan.project_id == project_id)).all())
    if plan_ids:
        db.execute(delete(TestPlanCase).where(TestPlanCase.plan_id.in_(plan_ids)))

    db.execute(delete(TestRun).where(TestRun.project_id == project_id))
    db.execute(delete(TestPlanRun).where(TestPlanRun.project_id == project_id))
    db.execute(delete(TestPlan).where(TestPlan.project_id == project_id))
    db.execute(delete(APICase).where(APICase.project_id == project_id))
    db.execute(delete(UICase).where(UICase.project_id == project_id))
    db.execute(delete(Environment).where(Environment.project_id == project_id))
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()


@protected_router.get("/api-cases", response_model=list[schemas.APICaseRead])
def list_api_cases(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[APICase]:
    stmt = select(APICase).order_by(APICase.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(APICase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(APICase.project_id.in_(project_ids))
    items = list(db.scalars(stmt).all())
    for item in items:
        _ensure_case_defaults(item)
    return items


@protected_router.get("/cases", response_model=list[schemas.UnifiedCaseRead])
def list_cases(
    project_id: int | None = None,
    case_type: str | None = None,
    folder_path: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    tag: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.UnifiedCaseRead]:
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        project_ids = [project_id]
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
    else:
        project_ids = None

    keyword_value = (keyword or "").strip().lower()
    folder_value = (folder_path or "").strip().lower()
    normalized_type = (case_type or "").strip().upper()
    normalized_priority = (priority or "").strip().upper()
    normalized_status = (status or "").strip().upper()
    normalized_review_status = (review_status or "").strip().upper()
    tag_value = (tag or "").strip().lower()
    items: list[schemas.UnifiedCaseRead] = []

    if normalized_type in {"", "API"}:
        stmt = select(APICase).order_by(APICase.id.desc())
        if project_ids is not None:
            stmt = stmt.where(APICase.project_id.in_(project_ids))
        api_cases = db.scalars(stmt).all()
        for case in api_cases:
            if folder_value and folder_value not in str(case.folder_path or "").lower():
                continue
            if normalized_priority and (case.priority or "").upper() != normalized_priority:
                continue
            if normalized_status and (case.status or "").upper() != normalized_status:
                continue
            if normalized_review_status and (case.review_status or "").upper() != normalized_review_status:
                continue
            if tag_value and tag_value not in {str(item).lower() for item in (case.tags_json or [])}:
                continue
            if keyword_value and keyword_value not in f"{case.name} {case.path}".lower():
                continue
            items.append(_serialize_unified_case("API", case))

    if normalized_type in {"", "UI"}:
        stmt = select(UICase).order_by(UICase.id.desc())
        if project_ids is not None:
            stmt = stmt.where(UICase.project_id.in_(project_ids))
        ui_cases = db.scalars(stmt).all()
        for case in ui_cases:
            if folder_value and folder_value not in str(case.folder_path or "").lower():
                continue
            if normalized_priority and (case.priority or "").upper() != normalized_priority:
                continue
            if normalized_status and (case.status or "").upper() != normalized_status:
                continue
            if normalized_review_status and (case.review_status or "").upper() != normalized_review_status:
                continue
            if tag_value and tag_value not in {str(item).lower() for item in (case.tags_json or [])}:
                continue
            if keyword_value and keyword_value not in f"{case.name} {case.target_url} {case.expect_text}".lower():
                continue
            items.append(_serialize_unified_case("UI", case))

    if normalized_type in {"", "PERF"}:
        stmt = select(PerformanceCase).order_by(PerformanceCase.id.desc())
        if project_ids is not None:
            stmt = stmt.where(PerformanceCase.project_id.in_(project_ids))
        perf_cases = db.scalars(stmt).all()
        for case in perf_cases:
            if folder_value and folder_value not in str(case.folder_path or "").lower():
                continue
            if normalized_priority and (case.priority or "").upper() != normalized_priority:
                continue
            if normalized_status and (case.status or "").upper() != normalized_status:
                continue
            if normalized_review_status and (case.review_status or "").upper() != normalized_review_status:
                continue
            if tag_value and tag_value not in {str(item).lower() for item in (case.tags_json or [])}:
                continue
            if keyword_value and keyword_value not in f"{case.name} {case.path}".lower():
                continue
            items.append(_serialize_unified_case("PERF", case))

    items.sort(
        key=lambda item: (
            item.updated_at is not None or item.created_at is not None,
            item.updated_at or item.created_at,
            item.case_id,
        ),
        reverse=True,
    )
    return items


@protected_router.get("/cases/{case_type}/{case_id}/history", response_model=list[schemas.CaseHistoryRead])
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


@protected_router.post(
    "/cases/batch-update",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
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


@protected_router.post(
    "/cases/batch-review",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
)
def batch_review_cases(
    payload: schemas.CaseBatchReviewPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    affected_count = 0
    normalized_review_status = payload.review_status.strip().upper()
    for item in payload.items:
        case = _load_case_entity(db, item.case_type, item.case_id)
        if case is None:
            continue
        _require_project_access(db, current_user, db.get(Project, case.project_id))
        case.review_status = normalized_review_status
        case.review_note = payload.review_note
        if hasattr(case, "updated_by"):
            case.updated_by = current_user.id
        _record_case_history(
            db,
            case_type=item.case_type,
            case=case,
            action="BATCH_REVIEW",
            changed_by=current_user.id,
            summary=f"批量评审为 {normalized_review_status}",
        )
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已评审 {affected_count} 条用例",
    )


@protected_router.post(
    "/api-cases",
    response_model=schemas.APICaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_api_case(
    payload: schemas.APICaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APICase:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    data = payload.model_dump()
    data["method"] = data["method"].upper()
    api_case = APICase(**data, created_by=current_user.id, updated_by=current_user.id)
    db.add(api_case)
    db.commit()
    db.refresh(api_case)
    _record_case_history(db, case_type="API", case=api_case, action="CREATE", changed_by=current_user.id, summary="创建接口用例")
    db.commit()
    return api_case


@protected_router.put(
    "/api-cases/{case_id}",
    response_model=schemas.APICaseRead,
    dependencies=[Depends(require_tester)],
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
    original_signature = (
        api_case.name,
        api_case.folder_path,
        api_case.method,
        api_case.path,
        api_case.priority,
        api_case.status,
        api_case.review_status,
        tuple(api_case.tags_json or []),
        api_case.review_note,
        api_case.expected_status,
        api_case.headers_json,
        api_case.body_json,
        api_case.assertions_json,
    )
    data = payload.model_dump()
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
        api_case.review_status,
        tuple(api_case.tags_json or []),
        api_case.review_note,
        api_case.expected_status,
        api_case.headers_json,
        api_case.body_json,
        api_case.assertions_json,
    )
    if new_signature != original_signature:
        api_case.version_no = _bump_version(api_case.version_no)
    api_case.updated_by = current_user.id
    _record_case_history(db, case_type="API", case=api_case, action="UPDATE", changed_by=current_user.id, summary="更新接口用例")
    db.commit()
    db.refresh(api_case)
    return api_case


@protected_router.delete("/api-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_api_case(case_id: int, db: Session = Depends(get_db)) -> None:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")

    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "API", TestPlanCase.case_id == case_id)
    )
    db.delete(api_case)
    db.commit()



@protected_router.get("/ui-cases", response_model=list[schemas.UICaseRead])
def list_ui_cases(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UICase]:
    stmt = select(UICase).order_by(UICase.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(UICase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(UICase.project_id.in_(project_ids))
    items = list(db.scalars(stmt).all())
    for item in items:
        _ensure_case_defaults(item)
    return items


@protected_router.put(
    "/ui-cases/{case_id}",
    response_model=schemas.UICaseRead,
    dependencies=[Depends(require_tester)],
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
    original_signature = (
        ui_case.name,
        ui_case.folder_path,
        ui_case.target_url,
        ui_case.priority,
        ui_case.status,
        ui_case.review_status,
        tuple(ui_case.tags_json or []),
        ui_case.review_note,
        ui_case.expect_text,
        ui_case.steps_json,
        ui_case.assertions_json,
    )
    for key, value in payload.model_dump().items():
        setattr(ui_case, key, value)
    new_signature = (
        ui_case.name,
        ui_case.folder_path,
        ui_case.target_url,
        ui_case.priority,
        ui_case.status,
        ui_case.review_status,
        tuple(ui_case.tags_json or []),
        ui_case.review_note,
        ui_case.expect_text,
        ui_case.steps_json,
        ui_case.assertions_json,
    )
    if new_signature != original_signature:
        ui_case.version_no = _bump_version(ui_case.version_no)
    ui_case.updated_by = current_user.id
    _record_case_history(db, case_type="UI", case=ui_case, action="UPDATE", changed_by=current_user.id, summary="更新 UI 用例")
    db.commit()
    db.refresh(ui_case)
    return ui_case


@protected_router.get("/performance-cases", response_model=list[schemas.PerformanceCaseRead])
def list_performance_cases(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PerformanceCase]:
    stmt = select(PerformanceCase).order_by(PerformanceCase.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(PerformanceCase.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(PerformanceCase.project_id.in_(project_ids))
    items = list(db.scalars(stmt).all())
    for item in items:
        _ensure_case_defaults(item)
    return items


@protected_router.delete("/ui-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_ui_case(case_id: int, db: Session = Depends(get_db)) -> None:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")

    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "UI", TestPlanCase.case_id == case_id)
    )
    db.delete(ui_case)
    db.commit()


@protected_router.post(
    "/performance-cases",
    response_model=schemas.PerformanceCaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_performance_case(
    payload: schemas.PerformanceCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceCase:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    perf_case = PerformanceCase(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(perf_case)
    db.commit()
    db.refresh(perf_case)
    _record_case_history(db, case_type="PERF", case=perf_case, action="CREATE", changed_by=current_user.id, summary="创建性能用例")
    db.commit()
    return perf_case


@protected_router.put(
    "/performance-cases/{case_id}",
    response_model=schemas.PerformanceCaseRead,
    dependencies=[Depends(require_tester)],
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
    original_signature = (
        perf_case.name,
        perf_case.folder_path,
        perf_case.method,
        perf_case.path,
        perf_case.priority,
        perf_case.status,
        perf_case.review_status,
        tuple(perf_case.tags_json or []),
        perf_case.review_note,
        perf_case.expected_status,
        perf_case.headers_json,
        perf_case.body_json,
        perf_case.concurrency,
        perf_case.total_requests,
        perf_case.max_avg_response_ms,
        perf_case.max_p95_response_ms,
        perf_case.max_error_rate,
    )
    data = payload.model_dump()
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
        perf_case.review_status,
        tuple(perf_case.tags_json or []),
        perf_case.review_note,
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
    perf_case.updated_by = current_user.id
    _record_case_history(db, case_type="PERF", case=perf_case, action="UPDATE", changed_by=current_user.id, summary="更新性能用例")
    db.commit()
    db.refresh(perf_case)
    return perf_case


@protected_router.delete("/performance-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_performance_case(case_id: int, db: Session = Depends(get_db)) -> None:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    db.delete(perf_case)
    db.commit()


@protected_router.get("/environments", response_model=list[schemas.EnvironmentRead])
def list_environments(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Environment]:
    stmt = select(Environment).order_by(Environment.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(Environment.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(Environment.project_id.in_(project_ids))
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/environments",
    response_model=schemas.EnvironmentRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_environment(
    payload: schemas.EnvironmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Environment:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    env = Environment(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(env)
    db.commit()
    db.refresh(env)
    return env


@protected_router.put(
    "/environments/{environment_id}",
    response_model=schemas.EnvironmentRead,
    dependencies=[Depends(require_tester)],
)
def update_environment(
    environment_id: int,
    payload: schemas.EnvironmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Environment:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_access(db, current_user, db.get(Project, env.project_id))

    env.name = payload.name
    env.base_url = payload.base_url
    env.headers_json = payload.headers_json
    env.variables_json = payload.variables_json
    env.auth_config_json = payload.auth_config_json
    env.updated_by = current_user.id
    db.commit()
    db.refresh(env)
    return env


@protected_router.delete("/environments/{environment_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_environment(environment_id: int, db: Session = Depends(get_db)) -> None:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")

    db.execute(update(TestRun).where(TestRun.environment_id == environment_id).values(environment_id=None))
    db.execute(
        update(TestPlanRun).where(TestPlanRun.environment_id == environment_id).values(environment_id=None)
    )
    db.delete(env)
    db.commit()


@protected_router.get("/environments/{environment_id}/variables", response_model=schemas.EnvironmentVariablesUpdate)
def get_environment_variables(
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentVariablesUpdate:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_access(db, current_user, db.get(Project, env.project_id))
    return _serialize_environment_variables(env)


@protected_router.get("/environments/{environment_id}/validate", response_model=schemas.EnvironmentValidationResult)
def validate_environment(
    environment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentValidationResult:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_access(db, current_user, db.get(Project, env.project_id))
    return _build_validation_result_for_environment(db, env)


@protected_router.get("/executions/api/{case_id}/precheck", response_model=schemas.ExecutionPrecheckResult)
def precheck_api_case_execution(
    case_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    project = _require_project_access(db, current_user, db.get(Project, api_case.project_id))
    environment = None
    if environment_id is not None:
        environment = db.get(Environment, environment_id)
        if environment is None or environment.project_id != api_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    variables = environment.variables_json if environment and environment.variables_json else {}
    issues = _validation_issues_for_environment_runtime(environment, project)
    issues.extend(_validation_issues_for_api_case(api_case, variables))
    return _build_execution_precheck_result(
        target_type="API",
        target_id=api_case.id,
        project=project,
        environment=environment,
        issues=issues,
    )


@protected_router.get("/executions/ui/{case_id}/precheck", response_model=schemas.ExecutionPrecheckResult)
def precheck_ui_case_execution(
    case_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    project = _require_project_access(db, current_user, db.get(Project, ui_case.project_id))
    environment = None
    if environment_id is not None:
        environment = db.get(Environment, environment_id)
        if environment is None or environment.project_id != ui_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    variables = environment.variables_json if environment and environment.variables_json else {}
    issues = _validation_issues_for_environment_runtime(environment, project)
    issues.extend(_validation_issues_for_ui_case(ui_case, variables))
    return _build_execution_precheck_result(
        target_type="UI",
        target_id=ui_case.id,
        project=project,
        environment=environment,
        issues=issues,
    )


@protected_router.get("/executions/perf/{case_id}/precheck", response_model=schemas.ExecutionPrecheckResult)
def precheck_performance_case_execution(
    case_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    project = _require_project_access(db, current_user, db.get(Project, perf_case.project_id))
    environment = None
    if environment_id is not None:
        environment = db.get(Environment, environment_id)
        if environment is None or environment.project_id != perf_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    variables = environment.variables_json if environment and environment.variables_json else {}
    issues = _validation_issues_for_environment_runtime(environment, project)
    issues.extend(_validation_issues_for_performance_case(perf_case, variables))
    return _build_execution_precheck_result(
        target_type="PERF",
        target_id=perf_case.id,
        project=project,
        environment=environment,
        issues=issues,
    )


@protected_router.get("/test-plans/{plan_id}/precheck", response_model=schemas.ExecutionPrecheckResult)
def precheck_plan_execution(
    plan_id: int,
    environment_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionPrecheckResult:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    project = _require_project_access(db, current_user, db.get(Project, plan.project_id))
    environment = None
    if environment_id is not None:
        environment = db.get(Environment, environment_id)
        if environment is None or environment.project_id != plan.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    variables = environment.variables_json if environment and environment.variables_json else {}
    issues = _validation_issues_for_environment_runtime(environment, project)
    cases = list(
        db.scalars(
            select(TestPlanCase).where(TestPlanCase.plan_id == plan.id).order_by(TestPlanCase.order_index.asc(), TestPlanCase.id.asc())
        ).all()
    )
    for plan_case in cases:
        if plan_case.case_type == "API":
            case = db.get(APICase, plan_case.case_id)
            if case:
                issues.extend(_validation_issues_for_api_case(case, variables))
        elif plan_case.case_type == "UI":
            case = db.get(UICase, plan_case.case_id)
            if case:
                issues.extend(_validation_issues_for_ui_case(case, variables))
    return _build_execution_precheck_result(
        target_type="PLAN",
        target_id=plan.id,
        project=project,
        environment=environment,
        issues=issues,
    )


@protected_router.post(
    "/environments/validate-draft",
    response_model=schemas.EnvironmentValidationResult,
    dependencies=[Depends(require_tester)],
)
def validate_environment_draft(
    payload: schemas.EnvironmentValidationDraft,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentValidationResult:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
    draft_env = Environment(
        id=0,
        project_id=payload.project_id,
        name=payload.name,
        base_url=payload.base_url,
        headers_json=payload.headers_json,
        variables_json=payload.variables_json,
        auth_config_json=payload.auth_config_json,
    )
    return _build_validation_result_for_environment(db, draft_env)


@protected_router.put(
    "/environments/{environment_id}/variables",
    response_model=schemas.EnvironmentVariablesUpdate,
    dependencies=[Depends(require_tester)],
)
def update_environment_variables(
    environment_id: int,
    payload: schemas.EnvironmentVariablesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.EnvironmentVariablesUpdate:
    env = db.get(Environment, environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="环境不存在")
    _require_project_access(db, current_user, db.get(Project, env.project_id))
    env.variables_json = payload.variables_json
    env.headers_json = payload.headers_json
    env.auth_config_json = payload.auth_config_json
    env.updated_by = current_user.id
    db.commit()
    db.refresh(env)
    return _serialize_environment_variables(env)


@protected_router.get("/test-plans", response_model=list[schemas.TestPlanRead])
def list_test_plans(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestPlan]:
    stmt = select(TestPlan).order_by(TestPlan.id.asc())
    if project_id:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(TestPlan.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(TestPlan.project_id.in_(project_ids))
    return list(db.scalars(stmt).all())


@protected_router.post(
    "/test-plans",
    response_model=schemas.TestPlanRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_test_plan(
    payload: schemas.TestPlanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    plan = TestPlan(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@protected_router.delete("/test-plans/{plan_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_test_plan(plan_id: int, db: Session = Depends(get_db)) -> None:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    plan_run_ids = list(db.scalars(select(TestPlanRun.id).where(TestPlanRun.plan_id == plan_id)).all())
    if plan_run_ids:
        db.execute(delete(TestRun).where(TestRun.plan_run_id.in_(plan_run_ids)))
        db.execute(delete(TestPlanRun).where(TestPlanRun.id.in_(plan_run_ids)))

    db.execute(delete(TestPlanCase).where(TestPlanCase.plan_id == plan_id))
    db.delete(plan)
    db.commit()


@protected_router.get("/test-plans/{plan_id}", response_model=schemas.TestPlanRead)
def get_test_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    return plan


@protected_router.get("/test-plans/{plan_id}/cases", response_model=list[schemas.TestPlanCaseRead])
def list_test_plan_cases(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestPlanCase]:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    return list(
        db.scalars(
            select(TestPlanCase).where(TestPlanCase.plan_id == plan_id).order_by(TestPlanCase.order_index.asc())
        ).all()
    )


@protected_router.post(
    "/test-plans/{plan_id}/cases",
    response_model=schemas.TestPlanCaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def add_test_plan_case(
    plan_id: int,
    payload: schemas.TestPlanCaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlanCase:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))

    if payload.case_type == "API":
        case = db.get(APICase, payload.case_id)
    else:
        case = db.get(UICase, payload.case_id)

    if case is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    if case.project_id != plan.project_id:
        raise HTTPException(status_code=400, detail="用例不属于该测试计划项目")
    _require_project_access(db, current_user, db.get(Project, case.project_id))
    _validate_plan_case_review_gate(case, current_user, payload.allow_unapproved)

    plan_case = TestPlanCase(
        plan_id=plan.id,
        case_type=payload.case_type,
        case_id=payload.case_id,
        case_name=case.name,
        case_snapshot_json=_case_snapshot(case),
        order_index=payload.order_index,
        created_by=current_user.id,
    )
    db.add(plan_case)
    db.commit()
    db.refresh(plan_case)
    return plan_case


@protected_router.post(
    "/test-plans/{plan_id}/cases/batch",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
)
def add_plan_cases_batch(
    plan_id: int,
    payload: schemas.CaseBatchPlanPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))

    existing_cases = list(
        db.scalars(select(TestPlanCase).where(TestPlanCase.plan_id == plan_id).order_by(TestPlanCase.order_index.asc(), TestPlanCase.id.asc())).all()
    )
    next_order = max([item.order_index for item in existing_cases], default=0)
    affected_count = 0

    for offset, item in enumerate(payload.items):
        case = _load_case_entity(db, item.case_type, item.case_id)
        if case is None or case.project_id != plan.project_id:
            continue
        _validate_plan_case_review_gate(case, current_user, payload.allow_unapproved)
        existing = db.scalar(
            select(TestPlanCase).where(
                TestPlanCase.plan_id == plan_id,
                TestPlanCase.case_type == item.case_type.upper(),
                TestPlanCase.case_id == item.case_id,
            )
        )
        if existing is not None:
            continue
        order_index = max(payload.order_start + offset, next_order + 1)
        next_order = order_index
        db.add(
            TestPlanCase(
                plan_id=plan_id,
                case_type=item.case_type.upper(),
                case_id=item.case_id,
                case_name=case.name,
                case_snapshot_json=_case_snapshot(case),
                order_index=order_index,
                created_by=current_user.id,
            )
        )
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已加入 {affected_count} 条计划用例",
    )


@protected_router.delete(
    "/test-plans/{plan_id}/cases/{plan_case_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
def delete_test_plan_case(plan_id: int, plan_case_id: int, db: Session = Depends(get_db)) -> None:
    plan_case = db.get(TestPlanCase, plan_case_id)
    if plan_case is None or plan_case.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="计划用例不存在")
    db.delete(plan_case)
    db.commit()


@protected_router.post(
    "/test-plans/{plan_id}/cases/reorder",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
)
def reorder_test_plan_cases(
    plan_id: int,
    payload: schemas.TestPlanCaseReorderPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))
    if not payload.items:
        raise HTTPException(status_code=400, detail="排序项不能为空")

    requested_ids = [item.id for item in payload.items]
    unique_ids = set(requested_ids)
    if len(unique_ids) != len(requested_ids):
        raise HTTPException(status_code=400, detail="排序项存在重复")

    plan_cases = list(
        db.scalars(select(TestPlanCase).where(TestPlanCase.plan_id == plan_id)).all()
    )
    plan_case_map = {item.id: item for item in plan_cases}

    if not unique_ids.issubset(plan_case_map.keys()):
        raise HTTPException(status_code=400, detail="排序项包含无效计划用例")

    affected_count = 0
    for item in payload.items:
        plan_case = plan_case_map[item.id]
        if plan_case.order_index != item.order_index:
            plan_case.order_index = item.order_index
            affected_count += 1

    db.commit()
    return schemas.BatchActionResult(
        success=True,
        affected_count=affected_count,
        message=f"已更新 {affected_count} 条计划用例顺序",
    )


@protected_router.post(
    "/test-plans/{plan_id}/run",
    response_model=schemas.TestPlanRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_test_plan(
    plan_id: int,
    payload: schemas.TestPlanRunCreate | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlanRun:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))

    cases = list(
        db.scalars(
            select(TestPlanCase)
            .where(TestPlanCase.plan_id == plan_id)
            .order_by(TestPlanCase.order_index.asc(), TestPlanCase.id.asc())
        ).all()
    )
    if not cases:
        raise HTTPException(status_code=400, detail="测试计划未配置用例")

    environment_id = payload.environment_id if payload else None
    timeout_seconds = payload.timeout_seconds if payload else None
    max_retries = payload.max_retries if payload else 0
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != plan.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_plan_execution(
            plan.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    plan_run = TestPlanRun(
        plan_id=plan.id,
        project_id=plan.project_id,
        environment_id=environment_id,
        status="PENDING",
        summary="任务已提交，等待执行",
        retry_count=0,
        total_count=len(cases),
    )
    db.add(plan_run)
    db.commit()
    db.refresh(plan_run)

    for plan_case in cases:
        services.create_test_run(
            db,
            project_id=plan.project_id,
            environment_id=environment_id,
            plan_run_id=plan_run.id,
            case_type=plan_case.case_type,
            case_id=plan_case.case_id,
            case_name=plan_case.case_name,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    task_id, ran_inline = _dispatch_task_or_run_inline(run_test_plan, plan_run.id)
    if ran_inline:
        db.refresh(plan_run)
    else:
        plan_run.summary = f"任务已提交，执行中（task_id={task_id}）"
        db.commit()
        db.refresh(plan_run)
    return plan_run


@protected_router.post(
    "/ui-cases",
    response_model=schemas.UICaseRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_ui_case(
    payload: schemas.UICaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UICase:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))

    ui_case = UICase(**payload.model_dump(), created_by=current_user.id, updated_by=current_user.id)
    db.add(ui_case)
    db.commit()
    db.refresh(ui_case)
    _record_case_history(db, case_type="UI", case=ui_case, action="CREATE", changed_by=current_user.id, summary="创建 UI 用例")
    db.commit()
    return ui_case


@protected_router.get("/executions/runs", response_model=list[schemas.TestRunRead])
def list_runs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestRun]:
    stmt = select(TestRun).order_by(TestRun.id.desc()).limit(30)
    if current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(TestRun.project_id.in_(project_ids))
    return list(db.scalars(stmt).all())


@protected_router.get("/executions/runs/{run_id}", response_model=schemas.TestRunRead)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    return run


@protected_router.get("/executions/runs/{run_id}/logs", response_model=schemas.ExecutionLogRead)
def get_run_logs(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionLogRead:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    logs = list(db.scalars(select(ExecutionLog).where(ExecutionLog.run_id == run.id)).all())
    steps = list(
        db.scalars(
            select(ExecutionStep)
            .where(ExecutionStep.run_id == run.id)
            .order_by(ExecutionStep.step_index)
        ).all()
    )
    stdout_text = next((item.content for item in logs if item.stream == "stdout"), run.stdout_text)
    stderr_text = next((item.content for item in logs if item.stream == "stderr"), run.stderr_text)
    step_results = [step.raw_json for step in steps if step.raw_json] or run.step_results_json
    return schemas.ExecutionLogRead(
        run_id=run.id,
        status=run.status,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        exit_code=run.exit_code,
        error_type=run.error_type,
        timeout_seconds=run.timeout_seconds,
        step_results_json=step_results,
    )


@protected_router.get("/executions/runs/{run_id}/steps", response_model=list[schemas.ExecutionStepRead])
def get_run_steps(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExecutionStep]:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    return list(
        db.scalars(
            select(ExecutionStep)
            .where(ExecutionStep.run_id == run.id)
            .order_by(ExecutionStep.step_index.asc(), ExecutionStep.id.asc())
        ).all()
    )


@protected_router.get("/executions/runs/{run_id}/artifacts", response_model=schemas.ExecutionArtifactsRead)
def get_run_artifacts(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ExecutionArtifactsRead:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    artifacts = list(
        db.scalars(
            select(ExecutionArtifact)
            .where(ExecutionArtifact.run_id == run.id)
            .order_by(ExecutionArtifact.id)
        ).all()
    )
    payload = [
        artifact.meta_json
        or {
            "name": artifact.name,
            "path": artifact.path,
            "type": artifact.artifact_type,
        }
        for artifact in artifacts
    ] or (run.artifacts_json or [])
    return schemas.ExecutionArtifactsRead(run_id=run.id, artifacts=payload)


@protected_router.get("/executions/runs/{run_id}/artifacts/{artifact_index}/download")
def download_run_artifact(
    run_id: int,
    artifact_index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))

    artifact_rows = list(
        db.scalars(
            select(ExecutionArtifact)
            .where(ExecutionArtifact.run_id == run.id)
            .order_by(ExecutionArtifact.id)
        ).all()
    )
    artifacts = [
        artifact.meta_json
        or {
            "name": artifact.name,
            "path": artifact.path,
            "type": artifact.artifact_type,
        }
        for artifact in artifact_rows
    ] or (run.artifacts_json or [])
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="执行产物不存在")

    artifact = artifacts[artifact_index]
    file_path = artifact.get("path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="执行产物文件不存在")

    media_type = "application/octet-stream"
    artifact_type = (artifact.get("type") or "").lower()
    if artifact_type == "json":
        media_type = "application/json"
    elif artifact_type in {"txt", "log"}:
        media_type = "text/plain; charset=utf-8"
    elif artifact_type == "png":
        media_type = "image/png"
    elif artifact_type in {"jpg", "jpeg"}:
        media_type = "image/jpeg"
    elif artifact_type == "html":
        media_type = "text/html; charset=utf-8"

    return FileResponse(path=file_path, media_type=media_type, filename=artifact.get("name") or os.path.basename(file_path))


@protected_router.post(
    "/executions/runs/{run_id}/rerun",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def rerun_execution(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    project = _require_project_access(db, current_user, db.get(Project, run.project_id))
    environment = db.get(Environment, run.environment_id) if run.environment_id else None
    if environment is not None and environment.project_id != run.project_id:
        raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    variables = environment.variables_json if environment and environment.variables_json else {}
    if run.case_type == "API":
        case = db.get(APICase, run.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="接口用例不存在")
        _raise_precheck_failure(
            _build_execution_precheck_result(
                target_type="API",
                target_id=case.id,
                project=project,
                environment=environment,
                issues=_validation_issues_for_environment_runtime(environment, project)
                + _validation_issues_for_api_case(case, variables),
            )
        )
    elif run.case_type == "UI":
        case = db.get(UICase, run.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="UI 用例不存在")
        _raise_precheck_failure(
            _build_execution_precheck_result(
                target_type="UI",
                target_id=case.id,
                project=project,
                environment=environment,
                issues=_validation_issues_for_environment_runtime(environment, project)
                + _validation_issues_for_ui_case(case, variables),
            )
        )
    elif run.case_type == "PERF":
        case = db.get(PerformanceCase, run.case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="性能用例不存在")
        _raise_precheck_failure(
            _build_execution_precheck_result(
                target_type="PERF",
                target_id=case.id,
                project=project,
                environment=environment,
                issues=_validation_issues_for_environment_runtime(environment, project)
                + _validation_issues_for_performance_case(case, variables),
            )
        )

    rerun = services.create_test_run(
        db,
        project_id=run.project_id,
        environment_id=run.environment_id,
        plan_run_id=run.plan_run_id,
        case_type=run.case_type,
        case_id=run.case_id,
        case_name=run.case_name,
    )
    rerun.retry_count = (run.retry_count or 0) + 1
    rerun.max_retries = max(run.max_retries or 0, rerun.retry_count)
    db.commit()
    db.refresh(rerun)

    if rerun.case_type == "API":
        task_id, ran_inline = _dispatch_task_or_run_inline(run_api_case, rerun.id)
    elif rerun.case_type == "PERF":
        task_id, ran_inline = _dispatch_task_or_run_inline(run_performance_case, rerun.id)
    else:
        task_id, ran_inline = _dispatch_task_or_run_inline(run_ui_case, rerun.id)
    if ran_inline:
        db.refresh(rerun)
    else:
        rerun.task_id = task_id
        rerun.summary = f"重跑任务已提交（来源执行 {run.id}）"
        db.commit()
        db.refresh(rerun)
    return rerun


@protected_router.post(
    "/executions/runs/{run_id}/cancel",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def cancel_execution(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, run.project_id))
    if run.status in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="当前状态不允许取消")

    if run.task_id:
        celery_app.control.revoke(run.task_id, terminate=True)

    run.status = "CANCELLED"
    run.summary = "执行已取消"
    run.error_type = "CANCELLED"
    run.finished_at = utc_now_naive()
    db.commit()
    db.refresh(run)
    return run


@protected_router.post(
    "/executions/api/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_api_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    api_case = db.get(APICase, case_id)
    if api_case is None:
        raise HTTPException(status_code=404, detail="接口用例不存在")
    _require_project_access(db, current_user, db.get(Project, api_case.project_id))

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != api_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_api_case_execution(
            api_case.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    run = services.create_test_run(
        db,
        project_id=api_case.project_id,
        environment_id=environment_id,
        case_type="API",
        case_id=api_case.id,
        case_name=api_case.name,
        timeout_seconds=payload.timeout_seconds if payload else None,
        max_retries=payload.max_retries if payload else 0,
    )
    db.commit()
    db.refresh(run)
    task_id, ran_inline = _dispatch_task_or_run_inline(run_api_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@protected_router.post(
    "/executions/ui/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_ui_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    ui_case = db.get(UICase, case_id)
    if ui_case is None:
        raise HTTPException(status_code=404, detail="UI 用例不存在")
    _require_project_access(db, current_user, db.get(Project, ui_case.project_id))

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != ui_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_ui_case_execution(
            ui_case.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    run = services.create_test_run(
        db,
        project_id=ui_case.project_id,
        environment_id=environment_id,
        case_type="UI",
        case_id=ui_case.id,
        case_name=ui_case.name,
        timeout_seconds=payload.timeout_seconds if payload else None,
        max_retries=payload.max_retries if payload else 0,
    )
    db.commit()
    db.refresh(run)
    task_id, ran_inline = _dispatch_task_or_run_inline(run_ui_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@protected_router.post(
    "/executions/perf/{case_id}/run",
    response_model=schemas.TestRunRead,
    dependencies=[Depends(require_tester)],
)
def trigger_performance_case(
    case_id: int,
    payload: schemas.ExecutionTrigger | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestRun:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    _require_project_access(db, current_user, db.get(Project, perf_case.project_id))

    environment_id = payload.environment_id if payload else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is None or env.project_id != perf_case.project_id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    _raise_precheck_failure(
        precheck_performance_case_execution(
            perf_case.id,
            environment_id=environment_id,
            db=db,
            current_user=current_user,
        )
    )

    run = services.create_test_run(
        db,
        project_id=perf_case.project_id,
        environment_id=environment_id,
        case_type="PERF",
        case_id=perf_case.id,
        case_name=perf_case.name,
        timeout_seconds=payload.timeout_seconds if payload else None,
        max_retries=payload.max_retries if payload else 0,
    )
    db.commit()
    db.refresh(run)
    task_id, ran_inline = _dispatch_task_or_run_inline(run_performance_case, run.id)
    if ran_inline:
        db.refresh(run)
    else:
        run.task_id = task_id
        db.commit()
        db.refresh(run)
    return run


@protected_router.post("/tools/json/format", response_model=schemas.ToolResult)
def json_formatter(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.format_json_payload(payload.payload))


@protected_router.post("/tools/base64/encode", response_model=schemas.ToolResult)
def base64_encode(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.encode_base64(payload.payload))


@protected_router.post("/tools/base64/decode", response_model=schemas.ToolResult)
def base64_decode(payload: schemas.TextPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.decode_base64(payload.payload))


@protected_router.post("/tools/timestamp/convert", response_model=schemas.ToolResult)
def timestamp_convert(payload: schemas.TimestampPayload) -> schemas.ToolResult:
    return schemas.ToolResult(result=services.convert_timestamp(payload.payload))


@protected_router.get("/reports", response_model=list[schemas.TestPlanRunView])
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


@protected_router.get("/defects", response_model=list[schemas.DefectRecordRead])
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


@protected_router.post("/defects", response_model=schemas.DefectRecordRead, status_code=201, dependencies=[Depends(require_tester)])
def create_defect(
    payload: schemas.DefectRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DefectRecord:
    _require_project_access(db, current_user, db.get(Project, payload.project_id))
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
    db.commit()
    db.refresh(defect)
    return defect


@protected_router.put("/defects/{defect_id}", response_model=schemas.DefectRecordRead, dependencies=[Depends(require_tester)])
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
    for key, value in payload.model_dump().items():
        setattr(defect, key, value)
    defect.updated_by = current_user.id
    db.commit()
    db.refresh(defect)
    return defect


@protected_router.delete("/defects/{defect_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_defect(defect_id: int, db: Session = Depends(get_db)) -> None:
    defect = db.get(DefectRecord, defect_id)
    if defect is None:
        raise HTTPException(status_code=404, detail="缺陷记录不存在")
    db.delete(defect)
    db.commit()


@protected_router.get("/reports/insights", response_model=schemas.ReportInsights)
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


@protected_router.get("/reports/{plan_run_id}", response_model=schemas.ReportDetail)
def get_report(
    plan_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ReportDetail:
    plan_run = db.get(TestPlanRun, plan_run_id)
    if plan_run is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    _require_project_access(db, current_user, db.get(Project, plan_run.project_id))

    test_runs = list(
        db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id).order_by(TestRun.id.asc())).all()
    )
    recent_history_runs = list(
        db.scalars(
            select(TestPlanRun)
            .where(TestPlanRun.plan_id == plan_run.plan_id)
            .order_by(TestPlanRun.id.desc())
            .limit(5)
        ).all()
    )
    recent_history = [
        schemas.ReportHistoryItem(
            plan_run_id=item.id,
            status=item.status,
            error_type=item.error_type,
            created_at=item.created_at,
            duration_ms=item.duration_ms,
            pass_rate=_pass_rate(item.pass_count or 0, item.total_count or 0),
            fail_count=item.fail_count or 0,
        )
        for item in recent_history_runs
    ]
    defects = list(
        db.scalars(
            select(DefectRecord)
            .where(
                DefectRecord.project_id == plan_run.project_id,
                (DefectRecord.plan_run_id == plan_run.id) | (DefectRecord.run_id.in_([run.id for run in test_runs]) if test_runs else False),
            )
            .order_by(DefectRecord.id.desc())
        ).all()
    )
    return schemas.ReportDetail(
        plan_run=_serialize_plan_run(plan_run),
        test_runs=test_runs,
        recent_history=recent_history,
        defects=defects,
    )


@protected_router.get("/reports/{plan_run_id}/download")
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
            "plan_run": _serialize_plan_run(plan_run).model_dump(),
            "test_runs": [schemas.TestRunRead.model_validate(run).model_dump() for run in runs],
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


@protected_router.get("/users", response_model=list[schemas.UserRead], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    users = list(db.scalars(select(User).order_by(User.id.asc())).all())
    return [_serialize_user(db, user) for user in users]


@protected_router.post("/users", response_model=schemas.UserRead, status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)) -> User:
    data = payload.model_dump()
    password = data.pop("password", None) or services.DEFAULT_USER_PASSWORD
    user = User(**data, password_hash=services.hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = services.ensure_default_workspace(db)
    services.ensure_workspace_member(db, workspace.id, user.id, "member")
    return _serialize_user(db, user)


@protected_router.put("/users/{user_id}", response_model=schemas.UserRead, dependencies=[Depends(require_admin)])
def update_user(user_id: int, payload: schemas.UserUpdate, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if password:
        user.password_hash = services.hash_password(password)
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "role" in data:
        user.role = data["role"]
    if "status" in data:
        user.status = data["status"]
    db.commit()
    db.refresh(user)
    return _serialize_user(db, user)
