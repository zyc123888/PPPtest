import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import String, cast, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas, services
from app import notifications
from app.core.config import settings
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.models import (
    APICase,
    AIModelConfig,
    Activity,
    ApiToken,
    CaseGenerationArtifact,
    CaseGenerationAttempt,
    CaseGenerationJob,
    CaseGenerationV2Artifact,
    CaseGenerationV2Attempt,
    CaseGenerationV2Job,
    CaseChangeHistory,
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
from app.execution_runtime import (
    MissingTemplateVariableError,
    prepare_http_request,
)
from app.model_registry import case_generation_model_options
from app.tasks.case_generation import (
    _normalize_model_base_url,
    normalize_model_api_key,
    run_case_generation_job,
    sanitize_case_generation_payload,
    validate_model_connection_config,
)
from app.tasks.case_generation_v2 import (
    _normalize_pipeline_mode,
    rerun_case_generation_v2_source_shard,
    run_case_generation_v2_job,
)
from app.tasks.case_generation_runtime import attempt_output_dir, create_attempt, set_attempt_task_id
from app.tasks.case_generation_v2_support.metrics import build_generation_metrics, compare_generation_metrics
from app.tasks.executions import (
    run_api_case,
    run_performance_case,
    run_test_plan,
    run_ui_batch,
    run_ui_case,
)
from app.timeutil import utc_now_naive
from app.ui_case_ai import generate_ui_case_draft


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
    issues.extend(
        _collect_missing_template_issues(case.assertions_json, variables, scope=case_scope, field="assertions_json")
    )
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


def _serialize_case_generation_job(job: CaseGenerationJob) -> schemas.CaseGenerationJobRead:
    payload = {
        field: getattr(job, field)
        for field in schemas.CaseGenerationJobRead.model_fields.keys()
    }
    payload["input_payload_json"] = sanitize_case_generation_payload(payload.get("input_payload_json"))
    return schemas.CaseGenerationJobRead(**payload)


def _sanitize_case_generation_v2_payload(payload: dict | None) -> dict | None:
    if payload is None:
        return None
    cleaned = dict(payload)
    cleaned.pop("openai_api_key", None)
    return cleaned


def _serialize_case_generation_v2_job(job: CaseGenerationV2Job) -> schemas.CaseGenerationV2JobRead:
    payload = {
        field: getattr(job, field)
        for field in schemas.CaseGenerationV2JobRead.model_fields.keys()
    }
    payload["input_payload_json"] = _sanitize_case_generation_v2_payload(payload.get("input_payload_json"))
    return schemas.CaseGenerationV2JobRead(**payload)


def _serialize_case_generation_artifact(
    artifact: CaseGenerationArtifact,
    *,
    include_content: bool,
) -> schemas.CaseGenerationArtifactRead:
    payload = {
        field: getattr(artifact, field)
        for field in schemas.CaseGenerationArtifactRead.model_fields.keys()
    }
    if not include_content:
        payload["content_json"] = None
    return schemas.CaseGenerationArtifactRead(**payload)


def _serialize_case_generation_v2_artifact(
    artifact: CaseGenerationV2Artifact,
    *,
    include_content: bool,
) -> schemas.CaseGenerationV2ArtifactRead:
    payload = {
        field: getattr(artifact, field)
        for field in schemas.CaseGenerationV2ArtifactRead.model_fields.keys()
    }
    if not include_content:
        payload["content_json"] = None
    return schemas.CaseGenerationV2ArtifactRead(**payload)


_JSON_CASE_GENERATION_ARTIFACT_TYPES = {
    "orchestration_plan",
    "source_manifest",
    "evidence_trace",
    "evidence_trace_gate",
    "scope_index",
    "scope_index_gate",
    "function_points",
    "requirement_handoff",
    "testcase_base_package",
    "testcase_package",
    "testcase_handoff",
    "review_report",
    "trusted_review_report",
    "execution_proof",
    "model_call_trace",
    "generation_metrics",
    "final_delivery_gate",
    "xmind_export_log",
}


def _case_generation_artifact_media_type(artifact_type: str) -> str:
    normalized = artifact_type.lower()
    if normalized in _JSON_CASE_GENERATION_ARTIFACT_TYPES:
        return "application/json"
    if normalized in {"markdown", "xmindmark"}:
        return "text/markdown; charset=utf-8"
    if normalized == "xmind":
        return "application/vnd.xmind.workbook"
    return "application/octet-stream"


def _inherit_case_generation_v2_artifacts(
    db: Session,
    *,
    job_id: int,
    attempt_id: int,
) -> None:
    """Copy prior artifact metadata into a new local-rerun attempt without mutating history."""
    inherited_dir = Path(attempt_output_dir(job_id, "v2", attempt_id)) / "inherited"
    prior_artifacts = list(
        db.scalars(
            select(CaseGenerationV2Artifact)
            .where(
                CaseGenerationV2Artifact.job_id == job_id,
                or_(
                    CaseGenerationV2Artifact.attempt_id.is_(None),
                    CaseGenerationV2Artifact.attempt_id != attempt_id,
                ),
                CaseGenerationV2Artifact.expired_at.is_(None),
            )
            .order_by(CaseGenerationV2Artifact.id.desc())
        ).all()
    )
    seen_types: set[str] = set()
    for artifact in prior_artifacts:
        if artifact.artifact_type in seen_types:
            continue
        seen_types.add(artifact.artifact_type)
        inherited_path = artifact.file_path
        if inherited_path and os.path.isfile(inherited_path) and not os.path.islink(inherited_path):
            inherited_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(artifact.file_name or inherited_path).name
            target_path = inherited_dir / f"{artifact.id}_{safe_name}"
            # Bind mounts on Docker Desktop can map file ownership to the host
            # user. Copying metadata with copy2 then fails at copystat even
            # though the container can create and write the target file.
            shutil.copyfile(inherited_path, target_path)
            inherited_path = str(target_path)
        db.add(
            CaseGenerationV2Artifact(
                job_id=job_id,
                attempt_id=attempt_id,
                artifact_type=artifact.artifact_type,
                file_name=artifact.file_name,
                file_path=inherited_path,
                content_json=artifact.content_json,
            )
        )
    db.commit()


def _find_active_case_generation_job_for_user(db: Session, user_id: int) -> CaseGenerationJob | None:
    jobs = list(
        db.scalars(
            select(CaseGenerationJob)
            .where(CaseGenerationJob.created_by == user_id, CaseGenerationJob.status.in_(["PENDING", "RUNNING"]))
            .order_by(CaseGenerationJob.id.desc())
        ).all()
    )
    return jobs[0] if jobs else None


def _find_active_case_generation_v2_job_for_user(db: Session, user_id: int) -> CaseGenerationV2Job | None:
    jobs = list(
        db.scalars(
            select(CaseGenerationV2Job)
            .where(CaseGenerationV2Job.created_by == user_id, CaseGenerationV2Job.status.in_(["PENDING", "RUNNING"]))
            .order_by(CaseGenerationV2Job.id.desc())
        ).all()
    )
    return jobs[0] if jobs else None


def _serialize_ai_model_config(config: AIModelConfig) -> schemas.AIModelConfigRead:
    payload = schemas.AIModelConfigRead.model_validate(config).model_dump()
    payload["api_key"] = "***已配置***" if config.api_key else None
    return schemas.AIModelConfigRead(**payload)


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
        "steps_json": getattr(case, "steps_json", None),
        "expect_text": getattr(case, "expect_text", None),
        "headers_json": getattr(case, "headers_json", None),
        "body_json": getattr(case, "body_json", None),
        "assertions_json": getattr(case, "assertions_json", None),
        "generation_mode": getattr(case, "generation_mode", None),
        "execution_mode": getattr(case, "execution_mode", None),
        "self_heal_enabled": bool(getattr(case, "self_heal_enabled", False)),
        "max_agent_steps": getattr(case, "max_agent_steps", None),
        "allowed_origins_json": getattr(case, "allowed_origins_json", None),
        "prohibited_actions_json": getattr(case, "prohibited_actions_json", None),
        "ai_goal": getattr(case, "ai_goal", None),
        "skill_name": getattr(case, "skill_name", None),
        "skill_version": getattr(case, "skill_version", None),
        "generation_meta_json": getattr(case, "generation_meta_json", None),
        "concurrency": getattr(case, "concurrency", None),
        "total_requests": getattr(case, "total_requests", None),
        "max_avg_response_ms": getattr(case, "max_avg_response_ms", None),
        "max_p95_response_ms": getattr(case, "max_p95_response_ms", None),
        "max_error_rate": getattr(case, "max_error_rate", None),
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
    for field in (
        "review_status",
        "version_no",
        "review_note",
        "generation_mode",
        "execution_mode",
        "self_heal_enabled",
        "max_agent_steps",
        "allowed_origins_json",
        "prohibited_actions_json",
        "ai_goal",
        "skill_name",
        "skill_version",
    ):
        if hasattr(case, field):
            payload[field] = getattr(case, field)
    return payload


def _ensure_case_defaults(case) -> None:
    if hasattr(case, "review_status") and not getattr(case, "review_status", None):
        case.review_status = "DRAFT"
    if hasattr(case, "version_no") and not getattr(case, "version_no", None):
        case.version_no = "1.0.0"
    if hasattr(case, "generation_mode") and not getattr(case, "generation_mode", None):
        case.generation_mode = "manual"
    if hasattr(case, "execution_mode") and not getattr(case, "execution_mode", None):
        case.execution_mode = "stable"
    if hasattr(case, "max_agent_steps") and not getattr(case, "max_agent_steps", None):
        case.max_agent_steps = 10


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


def _dispatch_task_or_run_inline(
    task_func, record_id: int, *task_args, background_inline: bool = False
) -> tuple[str | None, bool]:
    if (
        os.getenv("PYTEST_CURRENT_TEST")
        or settings.backend_internal_url.startswith("http://testserver")
    ):
        task_func(record_id, *task_args)
        return None, True
    try:
        task = task_func.delay(record_id, *task_args)
        return task.id, False
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"任务队列暂不可用，请稍后重试：{exc}") from exc


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
    try:
        user = services.authenticate_user(db, payload.username, payload.password)
    except services.AccountDisabledError:
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
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


@protected_router.post("/auth/change-password", status_code=204)
def change_password(
    payload: schemas.PasswordChangeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not services.verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    current_user.password_hash = services.hash_password(payload.new_password)
    db.commit()
    keep = credentials.credentials if credentials else None
    services.revoke_all_user_tokens(db, current_user.id, keep_token=keep)


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


@protected_router.get("/api-cases", response_model=schemas.APICasePage | list[schemas.APICaseRead])
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


@protected_router.get("/cases", response_model=list[schemas.UnifiedCaseRead])
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
    single_tag_value = (tag or "").strip().lower()
    tag_values = [item.strip().lower() for item in (tags or "").split(",") if item.strip()]
    if single_tag_value and single_tag_value not in tag_values:
        tag_values.append(single_tag_value)
    normalized_tag_mode = (tag_mode or "ANY").strip().upper()
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
            if tag_values:
                case_tags = {str(item).lower() for item in (case.tags_json or [])}
                if normalized_tag_mode == "ALL":
                    if not all(value in case_tags for value in tag_values):
                        continue
                elif not any(value in case_tags for value in tag_values):
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
            if tag_values:
                case_tags = {str(item).lower() for item in (case.tags_json or [])}
                if normalized_tag_mode == "ALL":
                    if not all(value in case_tags for value in tag_values):
                        continue
                elif not any(value in case_tags for value in tag_values):
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
            if tag_values:
                case_tags = {str(item).lower() for item in (case.tags_json or [])}
                if normalized_tag_mode == "ALL":
                    if not all(value in case_tags for value in tag_values):
                        continue
                elif not any(value in case_tags for value in tag_values):
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


@protected_router.get("/cases/export")
def export_cases(
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
        db=db,
        current_user=current_user,
    )
    return {
        "count": len(items),
        "items": [item.model_dump() for item in items],
    }


@protected_router.get("/cases/duplicates", response_model=list[schemas.CaseDuplicateGroup])
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

    if normalized_type in {"", "API"}:
        stmt = select(APICase)
        if project_ids is not None:
            stmt = stmt.where(APICase.project_id.in_(project_ids))
        for case in db.scalars(stmt).all():
            add_item("API", case, f"{case.method.upper()} {case.path}")
    if normalized_type in {"", "UI"}:
        stmt = select(UICase)
        if project_ids is not None:
            stmt = stmt.where(UICase.project_id.in_(project_ids))
        for case in db.scalars(stmt).all():
            add_item("UI", case, case.target_url)
    if normalized_type in {"", "PERF"}:
        stmt = select(PerformanceCase)
        if project_ids is not None:
            stmt = stmt.where(PerformanceCase.project_id.in_(project_ids))
        for case in db.scalars(stmt).all():
            add_item("PERF", case, f"{case.method.upper()} {case.path}")

    groups = [
        schemas.CaseDuplicateGroup(case_type=item_type, duplicate_key=duplicate_key, count=len(items), items=items)
        for (item_type, duplicate_key), items in buckets.items()
        if len(items) > 1
    ]
    return sorted(groups, key=lambda item: (item.case_type, item.duplicate_key))


@protected_router.post(
    "/cases/import",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
)
def import_cases(
    payload: schemas.CaseImportPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.BatchActionResult:
    affected_count = 0
    for item in payload.items:
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
                review_status=item.review_status,
                version_no=item.version_no,
                review_note=item.review_note,
                tags_json=item.tags_json,
                headers_json=item.headers_json,
                body_json=item.body_json,
                assertions_json=item.assertions_json,
                expected_status=item.expected_status or 200,
                created_by=current_user.id,
                updated_by=current_user.id,
            )
            db.add(case)
            db.flush()
            _record_case_history(db, case_type="API", case=case, action="IMPORT", changed_by=current_user.id, summary="批量导入接口用例")
        elif case_type == "UI":
            validated = schemas.UICaseCreate(
                project_id=project.id,
                name=item.name,
                folder_path=item.folder_path,
                target_url=item.target_url or "http://localhost",
                priority=item.priority,
                status=item.status,
                review_status=item.review_status,
                version_no=item.version_no,
                review_note=item.review_note,
                tags_json=item.tags_json,
                steps_json=item.steps_json or [],
                assertions_json=item.assertions_json,
                expect_text=item.expect_text or "ok",
                generation_mode=item.generation_mode,
                execution_mode=item.execution_mode,
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
            _record_case_history(db, case_type="UI", case=case, action="IMPORT", changed_by=current_user.id, summary="批量导入 UI 用例")
        else:
            case = PerformanceCase(
                project_id=project.id,
                name=item.name,
                folder_path=item.folder_path,
                method=(item.method or "GET").upper(),
                path=item.path or "/",
                priority=item.priority,
                status=item.status,
                review_status=item.review_status,
                version_no=item.version_no,
                review_note=item.review_note,
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
            _record_case_history(db, case_type="PERF", case=case, action="IMPORT", changed_by=current_user.id, summary="批量导入性能用例")
        affected_count += 1

    db.commit()
    return schemas.BatchActionResult(success=True, affected_count=affected_count, message=f"已导入 {affected_count} 条用例")


@protected_router.get("/cases/folders", response_model=list[schemas.CaseFolderNode])
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


@protected_router.get("/case-generation/jobs", response_model=list[schemas.CaseGenerationJobRead])
def list_case_generation_jobs(
    project_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseGenerationJobRead]:
    stmt = select(CaseGenerationJob).order_by(CaseGenerationJob.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(CaseGenerationJob.status == status.strip().upper())
    if mode:
        stmt = stmt.where(CaseGenerationJob.mode == mode.strip().upper())
    if created_after:
        stmt = stmt.where(CaseGenerationJob.created_at >= created_after)
    if created_before:
        stmt = stmt.where(CaseGenerationJob.created_at < created_before)
    if before_id:
        stmt = stmt.where(CaseGenerationJob.id < before_id)
    if project_id is not None:
        project = db.get(Project, project_id)
        _require_project_access(db, current_user, project)
        stmt = stmt.where(CaseGenerationJob.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(CaseGenerationJob.project_id.in_(project_ids))
    return [_serialize_case_generation_job(item) for item in db.scalars(stmt).all()]


@protected_router.get("/case-generation/model-config", response_model=schemas.AIModelConfigRead | None)
def get_case_generation_model_config(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_workspace_access(db, current_user, workspace_id)
    config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if config is None:
        return None
    return _serialize_ai_model_config(config)


@protected_router.get(
    "/case-generation/model-options",
    response_model=list[schemas.AIModelOptionRead],
)
def list_case_generation_model_options(
    current_user: User = Depends(get_current_user),
) -> list[schemas.AIModelOptionRead]:
    del current_user
    return [schemas.AIModelOptionRead(**item) for item in case_generation_model_options()]


@protected_router.post(
    "/case-generation/model-config",
    response_model=schemas.AIModelConfigRead,
    dependencies=[Depends(require_tester)],
)
def upsert_case_generation_model_config(
    payload: schemas.AIModelConfigUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.AIModelConfigRead:
    _require_workspace_access(db, current_user, payload.workspace_id)
    try:
        normalized_base_url, normalized_model = validate_model_connection_config(payload.model, payload.base_url, payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_api_key = normalize_model_api_key(payload.api_key)
    config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == payload.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if config is None:
        config = AIModelConfig(
            workspace_id=payload.workspace_id,
            provider=payload.provider,
            name=payload.name,
            base_url=normalized_base_url,
            model=normalized_model,
            api_key=normalized_api_key,
            is_active=1,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(config)
    else:
        config.provider = payload.provider
        config.name = payload.name
        config.base_url = normalized_base_url
        config.model = normalized_model
        config.api_key = normalized_api_key
        config.updated_by = current_user.id
    db.commit()
    db.refresh(config)
    return _serialize_ai_model_config(config)


@protected_router.post(
    "/case-generation/jobs",
    response_model=schemas.CaseGenerationJobRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_case_generation_job(
    payload: schemas.CaseGenerationJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobRead:
    project = _require_project_access(db, current_user, db.get(Project, payload.project_id))
    active_job = _find_active_case_generation_job_for_user(db, current_user.id)
    if active_job is not None:
        raise HTTPException(status_code=400, detail=f"你已有进行中的生成任务 #{active_job.id}，请先等待结束或手动停止")
    source_url = (payload.source_url or "").strip() or None
    markdown_text = (payload.markdown_text or "").strip() or None
    if not markdown_text and not source_url:
        raise HTTPException(status_code=400, detail="请提供需求文本、上传文件或需求文档链接")
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == project.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    direct_api_key = normalize_model_api_key(payload.openai_api_key)
    if (model_config is None or not model_config.api_key) and direct_api_key:
        normalized_base_url, normalized_model = validate_model_connection_config("gpt-5.5", None, direct_api_key)
        model_config = AIModelConfig(
            workspace_id=project.workspace_id,
            provider="OPENAI",
            name="任务提交临时模型配置",
            base_url=normalized_base_url,
            model=normalized_model,
            api_key=direct_api_key,
            is_active=1,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(model_config)
        db.commit()
        db.refresh(model_config)
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="请先配置该工作空间的模型连接信息")
    input_payload = sanitize_case_generation_payload(payload.model_dump()) | {
        "source_url": source_url,
        "markdown_text": markdown_text,
        "workspace_id": project.workspace_id,
        "model_config_id": model_config.id,
        "openai_model": model_config.model,
        "openai_base_url": _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key),
    }
    job = CaseGenerationJob(
        workspace_id=project.workspace_id,
        project_id=project.id,
        name=payload.name,
        mode=payload.mode,
        status="PENDING",
        source_document_name=payload.source_document_name,
        progress_json={"stages": []},
        input_payload_json=input_payload,
        summary="任务已提交，等待生成",
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v1")

    try:
        task_id, ran_inline = _dispatch_task_or_run_inline(
            run_case_generation_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"任务已提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_job(job)


@protected_router.get("/case-generation/jobs/{job_id}", response_model=schemas.CaseGenerationJobDetail)
def get_case_generation_job(
    job_id: int,
    include_content: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobDetail:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact_stmt = select(CaseGenerationArtifact).where(CaseGenerationArtifact.job_id == job.id)
    if job.active_attempt_id is not None:
        artifact_stmt = artifact_stmt.where(CaseGenerationArtifact.attempt_id == job.active_attempt_id)
    artifacts = list(db.scalars(artifact_stmt.order_by(CaseGenerationArtifact.id.asc())).all())
    attempts = list(
        db.scalars(
            select(CaseGenerationAttempt)
            .where(CaseGenerationAttempt.job_id == job.id)
            .order_by(CaseGenerationAttempt.id.desc())
            .limit(20)
        ).all()
    )
    return schemas.CaseGenerationJobDetail(
        job=_serialize_case_generation_job(job),
        artifacts=[_serialize_case_generation_artifact(item, include_content=include_content) for item in artifacts],
        attempts=[schemas.CaseGenerationAttemptRead.model_validate(item) for item in attempts],
    )


@protected_router.post(
    "/case-generation/jobs/{job_id}/rerun",
    response_model=schemas.CaseGenerationJobRead,
    dependencies=[Depends(require_tester)],
)
def rerun_case_generation_job_api(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobRead:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    active_job = _find_active_case_generation_job_for_user(db, current_user.id)
    if active_job is not None and active_job.id != job.id:
        raise HTTPException(status_code=400, detail=f"你已有进行中的生成任务 #{active_job.id}，请先等待结束或手动停止")
    
    if job.status in {"PENDING", "RUNNING"}:
        return _serialize_case_generation_job(job)
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="当前工作空间未配置可用模型，无法重跑")
    payload = dict(job.input_payload_json or {})
    payload["model_config_id"] = model_config.id
    payload["openai_model"] = model_config.model
    payload["openai_base_url"] = _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key)
    job.input_payload_json = payload
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v1")
    job.summary = "任务重新提交，等待生成"
    attempt.summary = job.summary
    db.commit()

    try:
        task_id, ran_inline = _dispatch_task_or_run_inline(
            run_case_generation_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"任务重新提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_job(job)


@protected_router.post(
    "/case-generation/jobs/{job_id}/cancel",
    response_model=schemas.CaseGenerationJobRead,
    dependencies=[Depends(require_tester)],
)
def cancel_case_generation_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationJobRead:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    if job.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="只能停止自己创建的生成任务")
    if job.status not in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="当前状态不允许停止")
    if job.task_id:
        celery_app.control.revoke(job.task_id, terminate=True, signal="SIGTERM")
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    if stages:
        stages[-1]["status"] = "failed"
        stages[-1]["summary"] = "任务已手动停止"
        progress["stages"] = stages
        job.progress_json = progress
    job.status = "CANCELLED"
    job.task_id = None
    job.summary = "生成已取消"
    job.error_message = "任务已手动停止"
    job.finished_at = utc_now_naive()
    if job.active_attempt_id:
        attempt = db.get(CaseGenerationAttempt, job.active_attempt_id)
        if attempt is not None:
            attempt.status = "CANCELLED"
            attempt.task_id = None
            attempt.summary = job.summary
            attempt.error_message = job.error_message
            attempt.progress_json = progress
            attempt.finished_at = job.finished_at
    db.commit()
    db.refresh(job)
    return _serialize_case_generation_job(job)


@protected_router.get("/case-generation/jobs/{job_id}/artifacts/{artifact_id}/download")
def download_case_generation_artifact(
    job_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationArtifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="生成产物不存在")
    if not artifact.file_path or not os.path.exists(artifact.file_path):
        raise HTTPException(status_code=404, detail="生成产物文件不存在")

    return FileResponse(
        path=artifact.file_path,
        media_type=_case_generation_artifact_media_type(artifact.artifact_type),
        filename=artifact.file_name or os.path.basename(artifact.file_path),
    )


@protected_router.get(
    "/case-generation/jobs/{job_id}/artifacts/{artifact_id}",
    response_model=schemas.CaseGenerationArtifactRead,
)
def get_case_generation_artifact_content(
    job_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationArtifactRead:
    job = db.get(CaseGenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationArtifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="生成产物不存在")
    return _serialize_case_generation_artifact(artifact, include_content=True)


@protected_router.get("/case-generation-v2/jobs", response_model=list[schemas.CaseGenerationV2JobRead])
def list_case_generation_v2_jobs(
    project_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    pipeline_mode: str | None = Query(default=None, pattern="^(clone|trusted_v2|lite|trusted)$"),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.CaseGenerationV2JobRead]:
    stmt = select(CaseGenerationV2Job).order_by(CaseGenerationV2Job.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(CaseGenerationV2Job.status == status.strip().upper())
    if mode:
        stmt = stmt.where(CaseGenerationV2Job.mode == mode.strip().upper())
    if pipeline_mode:
        normalized_pipeline_mode = _normalize_pipeline_mode(pipeline_mode)
        accepted_modes = ["lite", "clone"] if normalized_pipeline_mode == "lite" else ["trusted", "trusted_v2"]
        stmt = stmt.where(
            CaseGenerationV2Job.input_payload_json["pipeline_mode"].as_string().in_(accepted_modes)
        )
    if created_after:
        stmt = stmt.where(CaseGenerationV2Job.created_at >= created_after)
    if created_before:
        stmt = stmt.where(CaseGenerationV2Job.created_at < created_before)
    if before_id:
        stmt = stmt.where(CaseGenerationV2Job.id < before_id)
    if project_id is not None:
        project = db.get(Project, project_id)
        _require_project_access(db, current_user, project)
        stmt = stmt.where(CaseGenerationV2Job.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(CaseGenerationV2Job.project_id.in_(project_ids))
    return [_serialize_case_generation_v2_job(item) for item in db.scalars(stmt).all()]


@protected_router.post(
    "/case-generation-v2/jobs",
    response_model=schemas.CaseGenerationV2JobRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def create_case_generation_v2_job(
    payload: schemas.CaseGenerationV2JobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    project = _require_project_access(db, current_user, db.get(Project, payload.project_id))
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    if active_job is not None:
        raise HTTPException(status_code=400, detail=f"你已有进行中的 V2 生成任务 #{active_job.id}，请先等待结束或手动停止")
    source_url = (payload.source_url or "").strip() or None
    markdown_text = (payload.markdown_text or "").strip() or None
    if not markdown_text and not source_url:
        raise HTTPException(status_code=400, detail="请提供需求文本、上传文件或需求文档链接")
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == project.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    direct_api_key = normalize_model_api_key(payload.openai_api_key)
    if (model_config is None or not model_config.api_key) and direct_api_key:
        normalized_base_url, normalized_model = validate_model_connection_config("gpt-5.5", None, direct_api_key)
        model_config = AIModelConfig(
            workspace_id=project.workspace_id,
            provider="OPENAI",
            name="V2 任务提交临时模型配置",
            base_url=normalized_base_url,
            model=normalized_model,
            api_key=direct_api_key,
            is_active=1,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        db.add(model_config)
        db.commit()
        db.refresh(model_config)
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="请先配置该工作空间的模型连接信息")
    input_payload = sanitize_case_generation_payload(payload.model_dump()) | {
        "source_url": source_url,
        "markdown_text": markdown_text,
        "workspace_id": project.workspace_id,
        "pipeline": "case-generation-v2",
        "pipeline_mode": payload.pipeline_mode or "lite",
        "model_config_id": model_config.id,
        "openai_model": model_config.model,
        "openai_base_url": _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key),
    }
    job = CaseGenerationV2Job(
        workspace_id=project.workspace_id,
        project_id=project.id,
        name=payload.name,
        mode=payload.mode,
        status="PENDING",
        source_document_name=payload.source_document_name,
        progress_json={"stages": []},
        input_payload_json=input_payload,
        summary="V2 任务已提交，等待生成",
        created_by=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v2")

    try:
        task_id, ran_inline = _dispatch_task_or_run_inline(
            run_case_generation_v2_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "V2 任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "V2 任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"V2 任务已提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@protected_router.get("/case-generation-v2/jobs/{job_id}", response_model=schemas.CaseGenerationV2JobDetail)
def get_case_generation_v2_job(
    job_id: int,
    include_content: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobDetail:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact_stmt = select(CaseGenerationV2Artifact).where(CaseGenerationV2Artifact.job_id == job.id)
    if job.active_attempt_id is not None:
        artifact_stmt = artifact_stmt.where(CaseGenerationV2Artifact.attempt_id == job.active_attempt_id)
    artifacts = list(db.scalars(artifact_stmt.order_by(CaseGenerationV2Artifact.id.asc())).all())
    attempts = list(
        db.scalars(
            select(CaseGenerationV2Attempt)
            .where(CaseGenerationV2Attempt.job_id == job.id)
            .order_by(CaseGenerationV2Attempt.id.desc())
            .limit(20)
        ).all()
    )
    return schemas.CaseGenerationV2JobDetail(
        job=_serialize_case_generation_v2_job(job),
        artifacts=[_serialize_case_generation_v2_artifact(item, include_content=include_content) for item in artifacts],
        attempts=[schemas.CaseGenerationV2AttemptRead.model_validate(item) for item in attempts],
    )


def _generation_metrics_for_job(db: Session, job, *, pipeline_version: str) -> dict | None:
    attempt_cls = CaseGenerationV2Attempt if pipeline_version == "v2" else CaseGenerationAttempt
    artifact_cls = CaseGenerationV2Artifact if pipeline_version == "v2" else CaseGenerationArtifact
    attempt = db.get(attempt_cls, job.active_attempt_id) if job.active_attempt_id else None
    if attempt is None:
        attempt = db.scalar(
            select(attempt_cls)
            .where(attempt_cls.job_id == job.id)
            .order_by(attempt_cls.id.desc())
        )
    artifact_stmt = select(artifact_cls).where(artifact_cls.job_id == job.id)
    if attempt is not None:
        artifact_stmt = artifact_stmt.where(artifact_cls.attempt_id == attempt.id)
    artifacts = list(db.scalars(artifact_stmt.order_by(artifact_cls.id.asc())).all())
    if not artifacts and attempt is not None:
        artifacts = list(
            db.scalars(
                select(artifact_cls)
                .where(artifact_cls.job_id == job.id)
                .order_by(artifact_cls.id.asc())
            ).all()
        )
    metrics_artifact = next(
        (
            item
            for item in reversed(artifacts)
            if item.artifact_type == "generation_metrics" and isinstance(item.content_json, dict)
        ),
        None,
    )
    if metrics_artifact is not None:
        return dict(metrics_artifact.content_json)
    if attempt is None:
        return None
    trace = next(
        (
            item.content_json
            for item in reversed(artifacts)
            if item.artifact_type == "model_call_trace" and isinstance(item.content_json, dict)
        ),
        {},
    )
    return build_generation_metrics(
        job=job,
        attempt=attempt,
        artifacts=artifacts,
        model_calls=list((trace or {}).get("calls") or []),
        pipeline_version=pipeline_version,
        status=attempt.status or job.status,
    )


@protected_router.get(
    "/case-generation-v2/jobs/{job_id}/metrics-comparison",
    response_model=schemas.CaseGenerationMetricsComparison,
)
def compare_case_generation_v2_metrics(
    job_id: int,
    baseline_job_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationMetricsComparison:
    candidate_job = db.get(CaseGenerationV2Job, job_id)
    if candidate_job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, candidate_job.project_id))
    if baseline_job_id is not None:
        baseline_job = db.get(CaseGenerationJob, baseline_job_id)
        if baseline_job is None:
            raise HTTPException(status_code=404, detail="V1 基线任务不存在")
        _require_project_access(db, current_user, db.get(Project, baseline_job.project_id))
    else:
        baseline_stmt = (
            select(CaseGenerationJob)
            .where(
                CaseGenerationJob.project_id == candidate_job.project_id,
                CaseGenerationJob.status.in_(["SUCCESS", "CONDITIONAL"]),
            )
            .order_by(CaseGenerationJob.id.desc())
        )
        if candidate_job.source_document_name:
            same_document = db.scalar(
                baseline_stmt.where(CaseGenerationJob.source_document_name == candidate_job.source_document_name)
            )
            baseline_job = same_document or db.scalar(baseline_stmt)
        else:
            baseline_job = db.scalar(baseline_stmt)
    comparison = compare_generation_metrics(
        _generation_metrics_for_job(db, baseline_job, pipeline_version="v1") if baseline_job else None,
        _generation_metrics_for_job(db, candidate_job, pipeline_version="v2"),
    )
    return schemas.CaseGenerationMetricsComparison(
        baseline_job_id=baseline_job.id if baseline_job else None,
        candidate_job_id=candidate_job.id,
        **comparison,
    )


@protected_router.post(
    "/case-generation-v2/jobs/{job_id}/rerun",
    response_model=schemas.CaseGenerationV2JobRead,
    dependencies=[Depends(require_tester)],
)
def rerun_case_generation_v2_job_api(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    if active_job is not None and active_job.id != job.id:
        raise HTTPException(status_code=400, detail=f"你已有进行中的 V2 生成任务 #{active_job.id}，请先等待结束或手动停止")
    if job.status in {"PENDING", "RUNNING"}:
        return _serialize_case_generation_v2_job(job)
    previous_progress = dict(job.progress_json or {})
    failed_stage = next(
        (
            str(stage.get("key") or "").strip()
            for stage in reversed(previous_progress.get("stages") or [])
            if isinstance(stage, dict) and stage.get("status") == "failed"
        ),
        "",
    )
    payload = dict(job.input_payload_json or {})
    try:
        normalized_pipeline_mode = _normalize_pipeline_mode(payload.get("pipeline_mode"))
    except ValueError:
        normalized_pipeline_mode = "lite"
    available_artifact_types = set(
        db.scalars(
            select(CaseGenerationV2Artifact.artifact_type).where(
                CaseGenerationV2Artifact.job_id == job.id
            )
        ).all()
    )
    latest_testcase_artifact = db.scalar(
        select(CaseGenerationV2Artifact)
        .where(
            CaseGenerationV2Artifact.job_id == job.id,
            CaseGenerationV2Artifact.artifact_type == "testcase_package",
        )
        .order_by(CaseGenerationV2Artifact.id.desc())
    )
    testcase_shards = (
        (latest_testcase_artifact.content_json or {}).get("testcase_shards") or []
        if latest_testcase_artifact is not None and isinstance(latest_testcase_artifact.content_json, dict)
        else []
    )
    has_reusable_trusted_package = bool(
        testcase_shards
        and all(
            isinstance(item, dict)
            and item.get("status") == "success"
            and item.get("testcases")
            for item in testcase_shards
        )
    )
    resume_from_testcase_gate = (
        normalized_pipeline_mode == "trusted"
        and (
            (
                failed_stage == "testcase_gate"
                and {"scope_index", "requirement_handoff", "testcase_base_package"}.issubset(available_artifact_types)
            )
            or (
                failed_stage == "testcase_by_source_shard"
                and has_reusable_trusted_package
                and {"scope_index", "requirement_handoff", "testcase_package"}.issubset(available_artifact_types)
            )
        )
    )
    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="当前工作空间未配置可用模型，无法重跑")
    payload["pipeline_mode"] = payload.get("pipeline_mode") or "lite"
    if resume_from_testcase_gate:
        payload["trusted_resume_from_stage"] = "testcase_gate"
    else:
        payload.pop("trusted_resume_from_stage", None)
    payload["model_config_id"] = model_config.id
    payload["openai_model"] = model_config.model
    payload["openai_base_url"] = _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key)
    job.input_payload_json = payload
    db.commit()
    db.refresh(job)
    attempt = create_attempt(db, job, pipeline_version="v2")
    if resume_from_testcase_gate:
        _inherit_case_generation_v2_artifacts(db, job_id=job.id, attempt_id=attempt.id)
    job.summary = "V2 任务将复用已有基线，从用例门禁继续" if resume_from_testcase_gate else "V2 任务重新提交，等待生成"
    attempt.summary = job.summary
    if resume_from_testcase_gate:
        attempt.progress_json = previous_progress
        job.progress_json = previous_progress
    db.commit()

    try:
        task_id, ran_inline = _dispatch_task_or_run_inline(
            run_case_generation_v2_job, job.id, attempt.id, background_inline=True
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = "V2 任务派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = "V2 任务派发失败"
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"V2 任务重新提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@protected_router.post(
    "/case-generation-v2/jobs/{job_id}/cancel",
    response_model=schemas.CaseGenerationV2JobRead,
    dependencies=[Depends(require_tester)],
)
def cancel_case_generation_v2_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    if job.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="只能停止自己创建的 V2 生成任务")
    if job.status not in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="当前状态不允许停止")
    if job.task_id:
        celery_app.control.revoke(job.task_id, terminate=True, signal="SIGTERM")
    progress = dict(job.progress_json or {})
    stages = list(progress.get("stages") or [])
    if stages:
        stages[-1]["status"] = "failed"
        stages[-1]["summary"] = "V2 任务已手动停止"
        progress["stages"] = stages
        job.progress_json = progress
    job.status = "CANCELLED"
    job.task_id = None
    job.summary = "V2 生成已取消"
    job.error_message = "任务已手动停止"
    job.finished_at = utc_now_naive()
    if job.active_attempt_id:
        attempt = db.get(CaseGenerationV2Attempt, job.active_attempt_id)
        if attempt is not None:
            attempt.status = "CANCELLED"
            attempt.task_id = None
            attempt.summary = job.summary
            attempt.error_message = job.error_message
            attempt.progress_json = progress
            attempt.finished_at = job.finished_at
    db.commit()
    db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@protected_router.post(
    "/case-generation-v2/jobs/{job_id}/shards/{source_id}/rerun",
    response_model=schemas.CaseGenerationV2JobRead,
    dependencies=[Depends(require_tester)],
)
def rerun_case_generation_v2_source_shard_api(
    job_id: int,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2JobRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    payload = dict(job.input_payload_json or {})
    try:
        normalized_pipeline_mode = _normalize_pipeline_mode(payload.get("pipeline_mode"))
    except ValueError:
        normalized_pipeline_mode = "lite"
    if normalized_pipeline_mode != "trusted":
        raise HTTPException(status_code=400, detail="只有可信模式任务支持 source shard 重跑")
    if job.status in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="任务正在执行中，不能重跑单个 source shard")
    artifact = db.scalar(
        select(CaseGenerationV2Artifact).where(
            CaseGenerationV2Artifact.job_id == job.id,
            CaseGenerationV2Artifact.artifact_type == "testcase_package",
        )
    )
    if artifact is None or not isinstance(artifact.content_json, dict):
        raise HTTPException(status_code=400, detail="缺少 testcase_package，无法重跑 source shard")
    shard_ids = {
        str(item.get("source_id") or "").strip()
        for item in artifact.content_json.get("testcase_shards") or []
        if isinstance(item, dict)
    }
    if source_id not in shard_ids:
        raise HTTPException(status_code=404, detail=f"未找到 source shard：{source_id}")
    active_job = _find_active_case_generation_v2_job_for_user(db, current_user.id)
    if active_job is not None and active_job.id != job.id:
        raise HTTPException(status_code=400, detail=f"你已有进行中的 V2 生成任务 #{active_job.id}，请先等待结束或手动停止")

    model_config = db.scalar(
        select(AIModelConfig)
        .where(AIModelConfig.workspace_id == job.workspace_id, AIModelConfig.is_active == 1)
        .order_by(AIModelConfig.id.desc())
    )
    if model_config is None or not model_config.api_key:
        raise HTTPException(status_code=400, detail="当前工作空间未配置可用模型，无法重跑 source shard")
    payload["pipeline_mode"] = payload.get("pipeline_mode") or "trusted"
    payload["model_config_id"] = model_config.id
    payload["openai_model"] = model_config.model
    payload["openai_base_url"] = _normalize_model_base_url(model_config.model, model_config.base_url, model_config.api_key)
    job.input_payload_json = payload
    db.commit()
    db.refresh(job)
    attempt = create_attempt(
        db,
        job,
        pipeline_version="v2",
        kind="source_shard",
        source_id=source_id,
    )
    _inherit_case_generation_v2_artifacts(db, job_id=job.id, attempt_id=attempt.id)
    job.summary = f"{source_id} source shard 重跑已提交"
    attempt.summary = job.summary
    db.commit()

    try:
        task_id, ran_inline = _dispatch_task_or_run_inline(
            rerun_case_generation_v2_source_shard,
            job.id,
            source_id,
            attempt.id,
            background_inline=True,
        )
    except HTTPException as exc:
        attempt.status = "FAILED"
        attempt.summary = f"{source_id} source shard 派发失败"
        attempt.error_message = str(exc.detail)
        attempt.finished_at = utc_now_naive()
        job.status = "FAILED"
        job.summary = attempt.summary
        job.error_message = str(exc.detail)
        job.finished_at = utc_now_naive()
        db.commit()
        raise
    if not ran_inline:
        job.summary = f"{source_id} source shard 重跑已提交（task_id={task_id}）"
        attempt.summary = job.summary
        set_attempt_task_id(db, job, attempt, task_id)
        db.refresh(job)
    return _serialize_case_generation_v2_job(job)


@protected_router.get("/case-generation-v2/jobs/{job_id}/artifacts/{artifact_id}/download")
def download_case_generation_v2_artifact(
    job_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationV2Artifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="V2 生成产物不存在")
    if not artifact.file_path or not os.path.exists(artifact.file_path):
        raise HTTPException(status_code=404, detail="V2 生成产物文件不存在")

    return FileResponse(
        path=artifact.file_path,
        media_type=_case_generation_artifact_media_type(artifact.artifact_type),
        filename=artifact.file_name or os.path.basename(artifact.file_path),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@protected_router.get(
    "/case-generation-v2/jobs/{job_id}/artifacts/{artifact_id}",
    response_model=schemas.CaseGenerationV2ArtifactRead,
)
def get_case_generation_v2_artifact_content(
    job_id: int,
    artifact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.CaseGenerationV2ArtifactRead:
    job = db.get(CaseGenerationV2Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="V2 生成任务不存在")
    _require_project_access(db, current_user, db.get(Project, job.project_id))
    artifact = db.get(CaseGenerationV2Artifact, artifact_id)
    if artifact is None or artifact.job_id != job.id:
        raise HTTPException(status_code=404, detail="V2 生成产物不存在")
    return _serialize_case_generation_v2_artifact(artifact, include_content=True)


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
    "/cases/batch-move-folder",
    response_model=schemas.BatchActionResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
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


@protected_router.post(
    "/api-cases/debug",
    response_model=schemas.APICaseDebugResponse,
    dependencies=[Depends(require_tester)],
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
    variables = environment.variables_json if environment and environment.variables_json else None
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
    except MissingTemplateVariableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    started_at = time.perf_counter()

    try:
        parsed_url = urlparse(prepared.url)
        if parsed_url.hostname == "testserver":
            from app.main import app

            from fastapi.testclient import TestClient

            with TestClient(app, base_url="http://testserver") as client:
                response = client.request(prepared.method, parsed_url.path, headers=prepared.headers, **prepared.kwargs())
            response_headers = dict(response.headers)
            response_text = response.text
        else:
            with httpx.Client(timeout=payload.timeout_seconds) as client:
                response = client.request(prepared.method, prepared.url, headers=prepared.headers, **prepared.kwargs())
            response_headers = dict(response.headers)
            response_text = response.text
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"调试请求失败：{exc}") from exc

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    try:
        response_body = response.json()
        body_type = "json"
    except Exception:
        response_body = response_text[:5000]
        body_type = "text"

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


@protected_router.get("/api-cases/folders", response_model=schemas.APICaseFolderTree)
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


@protected_router.post(
    "/api-cases/folders/rename",
    response_model=schemas.APICaseBatchResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
            db,
            case_type="API",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"目录重命名 {old_path} → {new_path}",
        )
    db.commit()
    return schemas.APICaseBatchResult(affected=len(cases))


@protected_router.get("/api-cases/stats", response_model=schemas.APICaseStats)
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


@protected_router.put(
    "/api-cases/batch",
    response_model=schemas.APICaseBatchResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
            db,
            case_type="API",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"批量更新属性：{', '.join(sorted(patch.keys()))}",
        )
    db.commit()
    return schemas.APICaseBatchResult(affected=len(cases))


@protected_router.delete(
    "/api-cases/batch",
    response_model=schemas.APICaseBatchResult,
    dependencies=[Depends(require_admin)],
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
        _record_case_history(
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


@protected_router.get("/api-cases/{case_id}", response_model=schemas.APICaseRead)
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
    )
    data = payload.model_dump(exclude={"review_status", "review_note"})
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
    )
    if new_signature != original_signature:
        api_case.version_no = _bump_version(api_case.version_no)
        if original_review_status in {"APPROVED", "IN_REVIEW"}:
            api_case.review_status = "DRAFT"
            api_case.reviewed_by = None
            api_case.reviewed_at = None
            api_case.submitted_review_at = None
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


@protected_router.post(
    "/api-cases/{case_id}/review/submit",
    response_model=schemas.APICaseRead,
    dependencies=[Depends(require_tester)],
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
    _record_case_history(db, case_type="API", case=api_case, action="REVIEW", changed_by=current_user.id, summary="提交评审")
    db.commit()
    db.refresh(api_case)
    return api_case


@protected_router.post(
    "/api-cases/{case_id}/review/decide",
    response_model=schemas.APICaseRead,
    dependencies=[Depends(require_tester)],
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
    _require_project_access(db, current_user, db.get(Project, api_case.project_id))
    if api_case.created_by is not None and api_case.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
    _ensure_case_defaults(api_case)
    current_status = (api_case.review_status or "DRAFT").upper()
    if current_status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不在评审中")
    api_case.review_status = payload.result
    api_case.review_note = payload.note
    api_case.reviewed_by = current_user.id
    api_case.reviewed_at = utc_now_naive()
    api_case.updated_by = current_user.id
    _record_case_history(
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



@protected_router.get("/ui-cases", response_model=schemas.UICasePage | list[schemas.UICaseRead])
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
    stmt = select(UICase).order_by(UICase.id.asc())
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


@protected_router.post(
    "/ui-cases/ai/generate",
    response_model=schemas.UICaseAIGenerateResponse,
    dependencies=[Depends(require_tester)],
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
        return await generate_ui_case_draft(
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


@protected_router.get("/ui-cases/folders", response_model=schemas.UICaseFolderTree)
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


@protected_router.post(
    "/ui-cases/folders/rename",
    response_model=schemas.UICaseBatchResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
            db,
            case_type="UI",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"目录重命名 {old_path} → {new_path}",
        )
    db.commit()
    return schemas.UICaseBatchResult(affected=len(cases))


@protected_router.get("/ui-cases/stats", response_model=schemas.UICaseStats)
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


@protected_router.put(
    "/ui-cases/batch",
    response_model=schemas.UICaseBatchResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
            db,
            case_type="UI",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"批量更新属性：{', '.join(sorted(patch.keys()))}",
        )
    db.commit()
    return schemas.UICaseBatchResult(affected=len(cases))


@protected_router.delete(
    "/ui-cases/batch",
    response_model=schemas.UICaseBatchResult,
    dependencies=[Depends(require_admin)],
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
        _record_case_history(
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


@protected_router.get("/ui-cases/{case_id}", response_model=schemas.UICaseRead)
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
        ui_case.self_heal_enabled,
        ui_case.max_agent_steps,
        ui_case.allowed_origins_json,
        ui_case.prohibited_actions_json,
        ui_case.ai_goal,
        ui_case.skill_name,
        ui_case.skill_version,
        ui_case.generation_meta_json,
    )
    for key, value in payload.model_dump(exclude={"review_status", "review_note"}).items():
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
    _record_case_history(db, case_type="UI", case=ui_case, action="UPDATE", changed_by=current_user.id, summary="更新 UI 用例")
    db.commit()
    db.refresh(ui_case)
    return ui_case


@protected_router.post(
    "/ui-cases/{case_id}/review/submit",
    response_model=schemas.UICaseRead,
    dependencies=[Depends(require_tester)],
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
    _record_case_history(db, case_type="UI", case=ui_case, action="REVIEW", changed_by=current_user.id, summary="提交评审")
    db.commit()
    db.refresh(ui_case)
    return ui_case


@protected_router.post(
    "/ui-cases/{case_id}/review/decide",
    response_model=schemas.UICaseRead,
    dependencies=[Depends(require_tester)],
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
    _require_project_access(db, current_user, db.get(Project, ui_case.project_id))
    if ui_case.created_by is not None and ui_case.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
    _ensure_case_defaults(ui_case)
    current_status = (ui_case.review_status or "DRAFT").upper()
    if current_status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不在评审中")
    ui_case.review_status = payload.result
    ui_case.review_note = payload.note
    ui_case.reviewed_by = current_user.id
    ui_case.reviewed_at = utc_now_naive()
    ui_case.updated_by = current_user.id
    _record_case_history(
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


@protected_router.get(
    "/performance-cases", response_model=schemas.PerformanceCasePage | list[schemas.PerformanceCaseRead]
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


@protected_router.get("/performance-cases/folders", response_model=schemas.PerformanceCaseFolderTree)
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


@protected_router.post(
    "/performance-cases/folders/rename",
    response_model=schemas.PerformanceCaseBatchResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
            db,
            case_type="PERF",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"目录重命名 {old_path} → {new_path}",
        )
    db.commit()
    return schemas.PerformanceCaseBatchResult(affected=len(cases))


@protected_router.get("/performance-cases/stats", response_model=schemas.PerformanceCaseStats)
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


@protected_router.put(
    "/performance-cases/batch",
    response_model=schemas.PerformanceCaseBatchResult,
    dependencies=[Depends(require_tester)],
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
        _record_case_history(
            db,
            case_type="PERF",
            case=case,
            action="UPDATE",
            changed_by=current_user.id,
            summary=f"批量更新属性：{', '.join(sorted(patch.keys()))}",
        )
    db.commit()
    return schemas.PerformanceCaseBatchResult(affected=len(cases))


@protected_router.delete(
    "/performance-cases/batch",
    response_model=schemas.PerformanceCaseBatchResult,
    dependencies=[Depends(require_admin)],
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
        _record_case_history(
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


@protected_router.get("/performance-cases/{case_id}", response_model=schemas.PerformanceCaseRead)
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
    data = payload.model_dump(exclude={"review_status", "review_note"})
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
    _record_case_history(db, case_type="PERF", case=perf_case, action="UPDATE", changed_by=current_user.id, summary="更新性能用例")
    db.commit()
    db.refresh(perf_case)
    return perf_case


@protected_router.delete("/performance-cases/{case_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_performance_case(case_id: int, db: Session = Depends(get_db)) -> None:
    perf_case = db.get(PerformanceCase, case_id)
    if perf_case is None:
        raise HTTPException(status_code=404, detail="性能用例不存在")
    db.execute(
        delete(TestPlanCase).where(TestPlanCase.case_type == "PERF", TestPlanCase.case_id == case_id)
    )
    db.delete(perf_case)
    db.commit()


@protected_router.post(
    "/performance-cases/{case_id}/review/submit",
    response_model=schemas.PerformanceCaseRead,
    dependencies=[Depends(require_tester)],
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
    _record_case_history(db, case_type="PERF", case=perf_case, action="REVIEW", changed_by=current_user.id, summary="提交评审")
    db.commit()
    db.refresh(perf_case)
    return perf_case


@protected_router.post(
    "/performance-cases/{case_id}/review/decide",
    response_model=schemas.PerformanceCaseRead,
    dependencies=[Depends(require_tester)],
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
    _require_project_access(db, current_user, db.get(Project, perf_case.project_id))
    if perf_case.created_by is not None and perf_case.created_by == current_user.id:
        raise HTTPException(status_code=403, detail="不能评审自己创建的用例")
    _ensure_case_defaults(perf_case)
    current_status = (perf_case.review_status or "DRAFT").upper()
    if current_status != "IN_REVIEW":
        raise HTTPException(status_code=400, detail=f"当前评审状态为 {current_status}，不在评审中")
    perf_case.review_status = payload.result
    perf_case.review_note = payload.note
    perf_case.reviewed_by = current_user.id
    perf_case.reviewed_at = utc_now_naive()
    perf_case.updated_by = current_user.id
    _record_case_history(
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

    plan_run = services.create_plan_run_with_cases(
        db,
        plan,
        environment_id=environment_id,
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


@protected_router.put(
    "/test-plans/{plan_id}/schedule",
    response_model=schemas.TestPlanRead,
    dependencies=[Depends(require_tester)],
)
def update_test_plan_schedule(
    plan_id: int,
    payload: schemas.TestPlanScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TestPlan:
    plan = db.get(TestPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="测试计划不存在")
    _require_project_access(db, current_user, db.get(Project, plan.project_id))

    if payload.schedule_enabled:
        if payload.schedule_environment_id is not None:
            env = db.get(Environment, payload.schedule_environment_id)
            if env is None or env.project_id != plan.project_id:
                raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
        plan.schedule_enabled = True
        plan.schedule_cron = payload.schedule_cron
        plan.schedule_environment_id = payload.schedule_environment_id
        plan.schedule_timeout_seconds = payload.schedule_timeout_seconds
        plan.schedule_max_retries = payload.schedule_max_retries
        plan.next_run_at = services.compute_next_run_at(payload.schedule_cron)
    else:
        plan.schedule_enabled = False
        plan.schedule_cron = None
        plan.schedule_environment_id = None
        plan.schedule_timeout_seconds = None
        plan.schedule_max_retries = 0
        plan.next_run_at = None
    plan.updated_by = current_user.id
    db.commit()
    db.refresh(plan)
    return plan


@protected_router.get(
    "/projects/{project_id}/notification-setting",
    response_model=schemas.NotificationSettingRead,
)
def get_project_notification_setting(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.NotificationSettingRead:
    _require_project_access(db, current_user, db.get(Project, project_id))
    setting = db.scalar(
        select(ProjectNotificationSetting).where(ProjectNotificationSetting.project_id == project_id)
    )
    if setting is None:
        return schemas.NotificationSettingRead(project_id=project_id)
    return schemas.NotificationSettingRead.model_validate(setting)


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
    setting.secret = payload.secret
    setting.notify_on = payload.notify_on
    db.commit()
    db.refresh(setting)
    return setting


@protected_router.put(
    "/projects/{project_id}/notification-setting",
    response_model=schemas.NotificationSettingRead,
    dependencies=[Depends(require_tester)],
)
def update_project_notification_setting(
    project_id: int,
    payload: schemas.NotificationSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectNotificationSetting:
    _require_project_access(db, current_user, db.get(Project, project_id))
    return _upsert_notification_setting(db, project_id, payload)


@protected_router.post(
    "/projects/{project_id}/notification-setting/test",
    dependencies=[Depends(require_tester)],
)
def test_project_notification_setting(
    project_id: int,
    payload: schemas.NotificationSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    project = _require_project_access(db, current_user, db.get(Project, project_id))
    if not payload.webhook_url:
        raise HTTPException(status_code=400, detail="请先填写 Webhook 地址")
    probe = ProjectNotificationSetting(
        project_id=project_id,
        enabled=True,
        channel_type=payload.channel_type,
        webhook_url=payload.webhook_url,
        secret=payload.secret,
        notify_on=payload.notify_on,
    )
    text = f"【测试平台】这是一条测试消息\n项目：{project.name}\n若收到本消息，说明通知配置正确。"
    success = notifications.send_webhook_message(probe, text)
    return {"success": success, "message": "发送成功" if success else "发送失败，请检查 Webhook 地址与密钥"}


@protected_router.get("/api-tokens", response_model=list[schemas.ApiTokenRead])
def list_api_tokens(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.ApiTokenRead]:
    records = db.scalars(
        select(ApiToken).where(ApiToken.user_id == current_user.id).order_by(ApiToken.id.desc())
    ).all()
    return [
        schemas.ApiTokenRead(
            id=record.id,
            name=record.name,
            token_prefix=record.token[:8] + "****",
            expires_at=record.expires_at,
            last_used_at=record.last_used_at,
            created_at=record.created_at,
        )
        for record in records
    ]


@protected_router.post("/api-tokens", response_model=schemas.ApiTokenCreated, status_code=201)
def create_api_token(
    payload: schemas.ApiTokenCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ApiTokenCreated:
    record = services.create_api_token(
        db, current_user, name=payload.name.strip(), expires_days=payload.expires_days
    )
    return schemas.ApiTokenCreated(
        id=record.id,
        name=record.name,
        token_prefix=record.token[:8] + "****",
        token=record.token,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
    )


@protected_router.delete("/api-tokens/{token_id}", status_code=204)
def delete_api_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    record = db.get(ApiToken, token_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Token 不存在")
    db.delete(record)
    db.commit()


def _trigger_batch_run(
    case_type: str,
    payload: schemas.UIBatchRunCreate,
    db: Session,
    current_user: User,
) -> UIBatchRun:
    if case_type == "API":
        case_model = APICase
        precheck_fn = precheck_api_case_execution
    elif case_type == "PERF":
        case_model = PerformanceCase
        precheck_fn = precheck_performance_case_execution
    else:
        case_model = UICase
        precheck_fn = precheck_ui_case_execution
    case_ids = list(dict.fromkeys(payload.case_ids))
    cases = list(db.scalars(select(case_model).where(case_model.id.in_(case_ids))).all())
    case_map = {case.id: case for case in cases}
    missing = [case_id for case_id in case_ids if case_id not in case_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"用例不存在: {', '.join(str(item) for item in missing)}")
    project_ids = {case.project_id for case in cases}
    if len(project_ids) > 1:
        raise HTTPException(status_code=400, detail="批量执行的用例必须属于同一项目")
    project = _require_project_access(db, current_user, db.get(Project, project_ids.pop()))
    inactive = [case.name for case in cases if (case.status or "ACTIVE").upper() != "ACTIVE"]
    if inactive:
        raise HTTPException(status_code=400, detail=f"以下用例未启用：{', '.join(inactive)}")
    if payload.environment_id is not None:
        env = db.get(Environment, payload.environment_id)
        if env is None or env.project_id != project.id:
            raise HTTPException(status_code=400, detail="环境不存在或不属于该项目")
    for case_id in case_ids:
        _raise_precheck_failure(
            precheck_fn(
                case_id,
                environment_id=payload.environment_id,
                db=db,
                current_user=current_user,
            )
        )

    batch_run = UIBatchRun(
        project_id=project.id,
        environment_id=payload.environment_id,
        case_type=case_type,
        status="PENDING",
        summary="任务已提交，等待执行",
        total_count=len(case_ids),
        created_by=current_user.id,
    )
    db.add(batch_run)
    db.commit()
    db.refresh(batch_run)

    for case_id in case_ids:
        case = case_map[case_id]
        services.create_test_run(
            db,
            project_id=project.id,
            environment_id=payload.environment_id,
            batch_run_id=batch_run.id,
            case_type=case_type,
            case_id=case.id,
            case_name=case.name,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )

    task_id, ran_inline = _dispatch_task_or_run_inline(run_ui_batch, batch_run.id)
    if ran_inline:
        db.refresh(batch_run)
    else:
        batch_run.summary = f"任务已提交，执行中（task_id={task_id}）"
        db.commit()
        db.refresh(batch_run)
    return batch_run


@protected_router.post(
    "/executions/ui/batch-run",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def trigger_ui_batch_run(
    payload: schemas.UIBatchRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _trigger_batch_run("UI", payload, db, current_user)


@protected_router.post(
    "/executions/api/batch-run",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def trigger_api_batch_run(
    payload: schemas.UIBatchRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _trigger_batch_run("API", payload, db, current_user)


def _list_batch_runs(
    case_type: str,
    project_id: int | None,
    limit: int,
    db: Session,
    current_user: User,
) -> list[UIBatchRun]:
    stmt = select(UIBatchRun)
    if case_type == "UI":
        stmt = stmt.where(or_(UIBatchRun.case_type == "UI", UIBatchRun.case_type.is_(None)))
    else:
        stmt = stmt.where(UIBatchRun.case_type == case_type)
    if project_id is not None:
        _require_project_access(db, current_user, db.get(Project, project_id))
        stmt = stmt.where(UIBatchRun.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        stmt = stmt.where(UIBatchRun.project_id.in_(project_ids))
    stmt = stmt.order_by(UIBatchRun.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


@protected_router.get("/executions/ui/batch-runs", response_model=list[schemas.UIBatchRunRead])
def list_ui_batch_runs(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UIBatchRun]:
    return _list_batch_runs("UI", project_id, limit, db, current_user)


@protected_router.get("/executions/api/batch-runs", response_model=list[schemas.UIBatchRunRead])
def list_api_batch_runs(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UIBatchRun]:
    return _list_batch_runs("API", project_id, limit, db, current_user)


def _get_batch_run_detail(
    batch_id: int,
    db: Session,
    current_user: User,
) -> schemas.UIBatchRunDetail:
    batch_run = db.get(UIBatchRun, batch_id)
    if batch_run is None:
        raise HTTPException(status_code=404, detail="批量执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, batch_run.project_id))
    runs = list(
        db.scalars(
            select(TestRun).where(TestRun.batch_run_id == batch_run.id).order_by(TestRun.id.asc())
        ).all()
    )
    detail = schemas.UIBatchRunDetail.model_validate(batch_run)
    detail.runs = [schemas.TestRunRead.model_validate(run) for run in runs]
    return detail


@protected_router.get("/executions/ui/batch-runs/{batch_id}", response_model=schemas.UIBatchRunDetail)
def get_ui_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UIBatchRunDetail:
    return _get_batch_run_detail(batch_id, db, current_user)


@protected_router.get("/executions/api/batch-runs/{batch_id}", response_model=schemas.UIBatchRunDetail)
def get_api_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UIBatchRunDetail:
    return _get_batch_run_detail(batch_id, db, current_user)


def _rerun_failed_batch_run(
    batch_id: int,
    db: Session,
    current_user: User,
) -> UIBatchRun:
    batch_run = db.get(UIBatchRun, batch_id)
    if batch_run is None:
        raise HTTPException(status_code=404, detail="批量执行记录不存在")
    _require_project_access(db, current_user, db.get(Project, batch_run.project_id))
    if batch_run.status in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=400, detail="批量执行尚未结束")
    failed_runs = list(
        db.scalars(
            select(TestRun)
            .where(TestRun.batch_run_id == batch_run.id, TestRun.status != "SUCCESS")
            .order_by(TestRun.id.asc())
        ).all()
    )
    failed_case_ids = list(dict.fromkeys(run.case_id for run in failed_runs))
    if not failed_case_ids:
        raise HTTPException(status_code=400, detail="没有失败的用例可重跑")
    return _trigger_batch_run(
        (batch_run.case_type or "UI").upper(),
        schemas.UIBatchRunCreate(
            case_ids=failed_case_ids,
            environment_id=batch_run.environment_id,
            timeout_seconds=failed_runs[0].timeout_seconds,
            max_retries=failed_runs[0].max_retries or 0,
        ),
        db=db,
        current_user=current_user,
    )


@protected_router.post(
    "/executions/ui/batch-runs/{batch_id}/rerun-failed",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def rerun_failed_ui_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _rerun_failed_batch_run(batch_id, db, current_user)


@protected_router.post(
    "/executions/api/batch-runs/{batch_id}/rerun-failed",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def rerun_failed_api_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _rerun_failed_batch_run(batch_id, db, current_user)


@protected_router.post(
    "/executions/perf/batch-run",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def trigger_perf_batch_run(
    payload: schemas.UIBatchRunCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _trigger_batch_run("PERF", payload, db, current_user)


@protected_router.get("/executions/perf/batch-runs", response_model=list[schemas.UIBatchRunRead])
def list_perf_batch_runs(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UIBatchRun]:
    return _list_batch_runs("PERF", project_id, limit, db, current_user)


@protected_router.get("/executions/perf/batch-runs/{batch_id}", response_model=schemas.UIBatchRunDetail)
def get_perf_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.UIBatchRunDetail:
    return _get_batch_run_detail(batch_id, db, current_user)


@protected_router.post(
    "/executions/perf/batch-runs/{batch_id}/rerun-failed",
    response_model=schemas.UIBatchRunRead,
    status_code=201,
    dependencies=[Depends(require_tester)],
)
def rerun_failed_perf_batch_run(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UIBatchRun:
    return _rerun_failed_batch_run(batch_id, db, current_user)


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


@protected_router.get("/executions/runs", response_model=schemas.TestRunPage | list[schemas.TestRunRead])
def list_runs(
    project_id: int | None = None,
    case_type: str | None = None,
    case_id: int | None = None,
    status: str | None = None,
    error_type: str | None = None,
    keyword: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.TestRunPage | list[TestRun]:
    normalized_case_type = (case_type or "").strip().upper()
    if normalized_case_type and normalized_case_type not in {"API", "UI", "PERF"}:
        raise HTTPException(status_code=400, detail="不支持的用例类型")
    normalized_status = (status or "").strip().upper()
    if normalized_status and normalized_status not in {
        "PENDING",
        "RUNNING",
        "SUCCESS",
        "FAILED",
        "ERROR",
        "TIMEOUT",
        "CANCELLED",
    }:
        raise HTTPException(status_code=400, detail="不支持的执行状态")

    base_conditions = []
    if project_id is not None:
        _require_project_access(db, current_user, db.get(Project, project_id))
        base_conditions.append(TestRun.project_id == project_id)
    elif current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return schemas.TestRunPage(items=[], total=0) if page is not None else []
        base_conditions.append(TestRun.project_id.in_(project_ids))
    if normalized_case_type:
        base_conditions.append(TestRun.case_type == normalized_case_type)
    if case_id is not None:
        base_conditions.append(TestRun.case_id == case_id)

    filter_conditions = list(base_conditions)
    if normalized_status:
        filter_conditions.append(TestRun.status == normalized_status)
    if error_type and error_type.strip():
        filter_conditions.append(TestRun.error_type == error_type.strip().upper())
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        filter_conditions.append(or_(TestRun.case_name.like(pattern), TestRun.summary.like(pattern)))

    stmt = select(TestRun).where(*filter_conditions).order_by(TestRun.id.desc())
    if page is None:
        return list(db.scalars(stmt.limit(limit)).all())

    total = db.scalar(select(func.count()).select_from(TestRun).where(*filter_conditions)) or 0
    items = list(db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all())
    status_counts = dict(
        db.execute(
            select(TestRun.status, func.count()).where(*base_conditions).group_by(TestRun.status)
        ).all()
    )
    failed = sum(status_counts.get(key, 0) for key in ("FAILED", "ERROR", "TIMEOUT"))
    return schemas.TestRunPage(
        items=[schemas.TestRunRead.model_validate(item) for item in items],
        total=total,
        running=status_counts.get("RUNNING", 0) + status_counts.get("PENDING", 0),
        failed=failed,
        retryable=failed + status_counts.get("CANCELLED", 0),
    )


@protected_router.get("/executions/runs/latest", response_model=list[schemas.TestRunRead])
def list_latest_runs(
    case_type: str = Query(...),
    case_ids: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TestRun]:
    normalized_case_type = case_type.strip().upper()
    if normalized_case_type not in {"API", "UI", "PERF"}:
        raise HTTPException(status_code=400, detail="不支持的用例类型")
    try:
        ids = [int(item) for item in case_ids.split(",") if item.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="case_ids 格式不正确") from exc
    ids = list(dict.fromkeys(ids))[:200]
    if not ids:
        return []
    conditions = [TestRun.case_type == normalized_case_type, TestRun.case_id.in_(ids)]
    if current_user.role != "admin":
        project_ids = _accessible_project_ids(db, current_user)
        if not project_ids:
            return []
        conditions.append(TestRun.project_id.in_(project_ids))
    latest_ids = select(func.max(TestRun.id)).where(*conditions).group_by(TestRun.case_id)
    return list(db.scalars(select(TestRun).where(TestRun.id.in_(latest_ids))).all())


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


_VALID_USER_ROLES = {"admin", "tester", "viewer"}
_VALID_USER_STATUSES = {"ACTIVE", "DISABLED"}


def _validate_user_fields(role: str | None = None, status: str | None = None) -> None:
    if role is not None and role not in _VALID_USER_ROLES:
        raise HTTPException(status_code=422, detail="非法角色，仅支持 admin / tester / viewer")
    if status is not None and status not in _VALID_USER_STATUSES:
        raise HTTPException(status_code=422, detail="非法状态，仅支持 ACTIVE / DISABLED")


def _other_active_admin_exists(db: Session, exclude_user_id: int) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.status == "ACTIVE", User.id != exclude_user_id)
    )
    return bool(count)


@protected_router.get("/users", response_model=list[schemas.UserRead], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    users = list(db.scalars(select(User).order_by(User.id.asc())).all())
    return [_serialize_user(db, user) for user in users]


@protected_router.post("/users", response_model=schemas.UserRead, status_code=201, dependencies=[Depends(require_admin)])
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)) -> User:
    data = payload.model_dump()
    _validate_user_fields(role=data.get("role"), status=data.get("status"))
    if db.scalar(select(User).where(User.username == data["username"])) is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")
    password = data.pop("password")
    user = User(**data, password_hash=services.hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = services.ensure_default_workspace(db)
    services.ensure_workspace_member(db, workspace.id, user.id, "member")
    return _serialize_user(db, user)


@protected_router.put("/users/{user_id}", response_model=schemas.UserRead)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    _validate_user_fields(role=data.get("role"), status=data.get("status"))
    demoting = "role" in data and user.role == "admin" and data["role"] != "admin"
    disabling = "status" in data and user.status == "ACTIVE" and data["status"] == "DISABLED"
    if (demoting or disabling) and user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能停用或降级自己的账号")
    if (demoting or disabling) and user.role == "admin" and not _other_active_admin_exists(db, user.id):
        raise HTTPException(status_code=400, detail="至少保留一名启用的管理员")
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
    if disabling:
        services.revoke_all_user_tokens(db, user.id)
    return _serialize_user(db, user)


@protected_router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if user.role == "admin" and not _other_active_admin_exists(db, user.id):
        raise HTTPException(status_code=400, detail="至少保留一名启用的管理员")
    # 先将全库指向该用户的可空外键（created_by/updated_by 等审计字段）置空，
    # 避免数据库 RESTRICT 外键约束阻止删除；tokens/工作空间成员由级联删除处理
    for table in User.metadata.sorted_tables:
        for column in table.columns:
            if column.nullable and any(fk.column.table.name == "users" for fk in column.foreign_keys):
                db.execute(table.update().where(column == user.id).values({column.name: None}))
    db.execute(delete(ProjectMember).where(ProjectMember.user_id == user.id))
    db.delete(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该用户存在无法解除的关联数据，请先停用账号")
