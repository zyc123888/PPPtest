"""环境与用例执行前模板变量预检领域逻辑。"""

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.models import (
    User,
    TestPlan,
    TestPlanCase,
    APICase,
    Environment,
    PerformanceCase,
    Project,
    UICase,
)
from app.deps.auth import _require_project_access
from app.execution_runtime import build_variable_context
from app.tasks.executions import normalize_datasets


_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


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
    project = db.get(Project, env.project_id)
    variables = build_variable_context(project, env) if project else (env.variables_json or {})
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
        issues.extend(_validation_issues_for_api_case(case, variables))

    ui_cases = list(db.scalars(select(UICase).where(UICase.project_id == env.project_id).order_by(UICase.id.asc())).all())
    for case in ui_cases:
        issues.extend(_validation_issues_for_ui_case(case, variables))

    perf_cases = list(db.scalars(select(PerformanceCase).where(PerformanceCase.project_id == env.project_id).order_by(PerformanceCase.id.asc())).all())
    for case in perf_cases:
        issues.extend(_validation_issues_for_performance_case(case, variables))

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


def _validation_issues_for_api_case(case: APICase, variables: dict | None) -> list[schemas.EnvironmentValidationIssue]:
    case_scope = f"api_case:{case.name}"
    issues: list[schemas.EnvironmentValidationIssue] = []
    if case.steps_json:
        # 场景模式：前序步骤提取的变量在执行时才产生，预检时视为已知变量
        known = dict(variables or {})
        for index, step in enumerate(case.steps_json):
            if not isinstance(step, dict):
                continue
            step_scope = f"{case_scope}#step{index + 1}"
            issues.extend(_collect_missing_template_issues(step.get("path"), known, scope=step_scope, field="path"))
            issues.extend(
                _collect_missing_template_issues(step.get("headers_json"), known, scope=step_scope, field="headers_json")
            )
            issues.extend(
                _collect_missing_template_issues(step.get("body_json"), known, scope=step_scope, field="body_json")
            )
            for extractor in step.get("extractors") or []:
                if isinstance(extractor, dict) and str(extractor.get("name") or "").strip():
                    known[str(extractor["name"]).strip()] = "__extracted__"
        return issues
    datasets = normalize_datasets(case.datasets_json)
    for index, row in enumerate(datasets or [{}], start=1):
        scope = f"{case_scope}#row{index}" if datasets else case_scope
        known = {**(variables or {}), **{key: value for key, value in row.items() if key != "__name__"}}
        for field in ("path", "headers_json", "body_json"):
            issues.extend(_collect_missing_template_issues(getattr(case, field), known, scope=scope, field=field))
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
    variables = build_variable_context(project, env)
    if env is None:
        return _collect_missing_template_issues(project.base_url, variables, scope=f"project:{project.name}", field="base_url")
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


def precheck_api_case(
    case_id: int,
    db: Session,
    current_user: User,
    environment_id: int | None = None,
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
    variables = build_variable_context(project, environment)
    issues = _validation_issues_for_environment_runtime(environment, project)
    issues.extend(_validation_issues_for_api_case(api_case, variables))
    return _build_execution_precheck_result(
        target_type="API",
        target_id=api_case.id,
        project=project,
        environment=environment,
        issues=issues,
    )


def precheck_ui_case(
    case_id: int,
    db: Session,
    current_user: User,
    environment_id: int | None = None,
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
    variables = build_variable_context(project, environment)
    issues = _validation_issues_for_environment_runtime(environment, project)
    issues.extend(_validation_issues_for_ui_case(ui_case, variables))
    return _build_execution_precheck_result(
        target_type="UI",
        target_id=ui_case.id,
        project=project,
        environment=environment,
        issues=issues,
    )


def precheck_performance_case(
    case_id: int,
    db: Session,
    current_user: User,
    environment_id: int | None = None,
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
    variables = build_variable_context(project, environment)
    issues = _validation_issues_for_environment_runtime(environment, project)
    issues.extend(_validation_issues_for_performance_case(perf_case, variables))
    return _build_execution_precheck_result(
        target_type="PERF",
        target_id=perf_case.id,
        project=project,
        environment=environment,
        issues=issues,
    )


def precheck_plan(
    plan_id: int,
    db: Session,
    current_user: User,
    environment_id: int | None = None,
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
    variables = build_variable_context(project, environment)
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
        elif plan_case.case_type == "PERF":
            case = db.get(PerformanceCase, plan_case.case_id)
            if case:
                issues.extend(_validation_issues_for_performance_case(case, variables))
    return _build_execution_precheck_result(
        target_type="PLAN",
        target_id=plan.id,
        project=project,
        environment=environment,
        issues=issues,
    )
