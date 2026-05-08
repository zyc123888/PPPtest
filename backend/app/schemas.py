from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORMBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    workspace_id: int | None = None
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = None
    base_url: str = Field(..., min_length=5, max_length=255)


class ProjectRead(ORMBaseModel):
    id: int
    workspace_id: int
    name: str
    description: str | None = None
    base_url: str
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class APICaseCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    method: str = Field(default="GET", min_length=3, max_length=10)
    path: str = Field(..., min_length=1, max_length=255)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int = 200


class APICaseRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    method: str
    path: str
    priority: str
    status: str
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UICaseCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    target_url: str = Field(..., min_length=5, max_length=255)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    steps_json: list[dict]
    expect_text: str = Field(..., min_length=1, max_length=255)


class UICaseRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    target_url: str
    priority: str
    status: str
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    steps_json: list[dict]
    expect_text: str
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestRunRead(ORMBaseModel):
    id: int
    project_id: int
    environment_id: int | None = None
    plan_run_id: int | None = None
    case_type: str
    case_id: int
    case_name: str
    status: str
    task_id: str | None = None
    summary: str | None = None
    error_type: str | None = None
    duration_ms: int | None = None
    exit_code: int | None = None
    timeout_seconds: int | None = None
    retry_count: int = 0
    max_retries: int = 0
    stdout_text: str | None = None
    stderr_text: str | None = None
    artifacts_json: list | None = None
    step_results_json: list | None = None
    request_payload: dict | None = None
    response_payload: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DashboardSummary(BaseModel):
    workspace_count: int
    project_count: int
    api_case_count: int
    ui_case_count: int
    environment_count: int
    plan_count: int
    run_count: int
    plan_run_count: int
    recent_runs: list[TestRunRead]


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = None


class WorkspaceRead(ORMBaseModel):
    id: int
    name: str
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkspaceMemberCreate(BaseModel):
    user_id: int
    role: str = Field(default="member", pattern="^(owner|member)$")


class WorkspaceMemberUpdate(BaseModel):
    role: str = Field(..., pattern="^(owner|member)$")


class WorkspaceMemberRead(ORMBaseModel):
    id: int
    workspace_id: int
    user_id: int
    username: str | None = None
    display_name: str | None = None
    role: str
    created_at: datetime | None = None


class UserWorkspaceMembership(BaseModel):
    workspace_id: int
    workspace_name: str
    role: str


class EnvironmentCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    base_url: str = Field(..., min_length=5, max_length=255)
    headers_json: dict | None = None
    variables_json: dict | None = None
    auth_config_json: dict | None = None


class EnvironmentUpdate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    base_url: str = Field(..., min_length=5, max_length=255)
    headers_json: dict | None = None
    variables_json: dict | None = None
    auth_config_json: dict | None = None


class EnvironmentRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    base_url: str
    headers_json: dict | None = None
    variables_json: dict | None = None
    auth_config_json: dict | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EnvironmentVariablesUpdate(BaseModel):
    variables_json: dict | None = None
    headers_json: dict | None = None
    auth_config_json: dict | None = None


class TestPlanCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    description: str | None = None


class TestPlanRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    description: str | None = None
    status: str
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestPlanCaseCreate(BaseModel):
    case_type: str = Field(..., pattern="^(API|UI)$")
    case_id: int
    order_index: int = 1


class TestPlanCaseRead(ORMBaseModel):
    id: int
    plan_id: int
    case_type: str
    case_id: int
    case_name: str
    case_snapshot_json: dict | None = None
    order_index: int
    created_at: datetime | None = None


class TestPlanRunCreate(BaseModel):
    environment_id: int | None = None


class TestPlanRunRead(ORMBaseModel):
    id: int
    plan_id: int
    project_id: int
    environment_id: int | None = None
    status: str
    summary: str | None = None
    error_type: str | None = None
    retry_count: int = 0
    total_count: int
    pass_count: int
    fail_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    report_json_path: str | None = None
    report_junit_path: str | None = None
    report_generated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestPlanRunView(TestPlanRunRead):
    plan_name: str
    project_name: str
    environment_name: str | None = None


class ReportDetail(BaseModel):
    plan_run: TestPlanRunRead
    test_runs: list[TestRunRead]


class ExecutionLogRead(BaseModel):
    run_id: int
    status: str
    stdout_text: str | None = None
    stderr_text: str | None = None
    exit_code: int | None = None
    error_type: str | None = None
    timeout_seconds: int | None = None
    step_results_json: list | None = None


class ExecutionArtifactsRead(BaseModel):
    run_id: int
    artifacts: list[dict] = []


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=80)
    password: str | None = Field(default=None, min_length=6, max_length=64)
    display_name: str | None = None
    role: str = Field(default="tester", min_length=2, max_length=50)


class UserRead(ORMBaseModel):
    id: int
    username: str
    display_name: str | None = None
    role: str
    status: str
    workspaces: list[str] = []
    workspace_memberships: list[UserWorkspaceMembership] = []
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = Field(default=None, min_length=2, max_length=50)
    status: str | None = Field(default=None, min_length=2, max_length=20)
    password: str | None = Field(default=None, min_length=6, max_length=64)


class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=80)
    password: str = Field(..., min_length=6, max_length=64)


class AuthLoginResponse(ORMBaseModel):
    token: str
    user: UserRead


class SystemHealth(BaseModel):
    app_status: str
    database: str
    redis: str
    checked_at: datetime


class SystemInfo(BaseModel):
    app_name: str
    app_version: str
    app_env: str
    api_v1_prefix: str
    database_backend: str
    database_name: str | None = None
    database_url: str
    redis_url: str
    backend_public_url: str
    frontend_public_url: str
    execution_engine: str
    report_output_dir: str
    auto_bootstrap_on_startup: bool
    seed_demo_data_on_bootstrap: bool


class SystemBootstrapRequest(BaseModel):
    seed_demo_data: bool = True


class SystemBootstrapResult(BaseModel):
    success: bool
    database_backend: str
    database_name: str | None = None
    created_tables: list[str]
    schema_changes: list[str]
    seeded_resources: list[str]
    bootstrapped_at: datetime


class TextPayload(BaseModel):
    payload: str


class TimestampPayload(BaseModel):
    payload: str


class ToolResult(BaseModel):
    result: str


class ExecutionTrigger(BaseModel):
    environment_id: int | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
