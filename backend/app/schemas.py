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
    folder_path: str | None = Field(default=None, max_length=255)
    method: str = Field(default="GET", min_length=3, max_length=10)
    path: str = Field(..., min_length=1, max_length=255)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    review_status: str = Field(default="DRAFT", min_length=2, max_length=20)
    version_no: str = Field(default="1.0.0", min_length=1, max_length=30)
    review_note: str | None = None
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int = 200


class APICaseUpdate(APICaseCreate):
    pass


class APICaseRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    folder_path: str | None = None
    method: str
    path: str
    priority: str
    status: str
    review_status: str
    version_no: str
    review_note: str | None = None
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
    folder_path: str | None = Field(default=None, max_length=255)
    target_url: str = Field(..., min_length=5, max_length=255)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    review_status: str = Field(default="DRAFT", min_length=2, max_length=20)
    version_no: str = Field(default="1.0.0", min_length=1, max_length=30)
    review_note: str | None = None
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    steps_json: list[dict]
    expect_text: str = Field(..., min_length=1, max_length=255)


class UICaseUpdate(UICaseCreate):
    pass


class UICaseRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    folder_path: str | None = None
    target_url: str
    priority: str
    status: str
    review_status: str
    version_no: str
    review_note: str | None = None
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    steps_json: list[dict]
    expect_text: str
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PerformanceCaseCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    folder_path: str | None = Field(default=None, max_length=255)
    method: str = Field(default="GET", min_length=3, max_length=10)
    path: str = Field(..., min_length=1, max_length=255)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    review_status: str = Field(default="DRAFT", min_length=2, max_length=20)
    version_no: str = Field(default="1.0.0", min_length=1, max_length=30)
    review_note: str | None = None
    tags_json: list[str] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int = 200
    concurrency: int = Field(default=5, ge=1, le=50)
    total_requests: int = Field(default=20, ge=1, le=1000)
    max_avg_response_ms: int | None = Field(default=None, ge=1, le=60000)
    max_p95_response_ms: int | None = Field(default=None, ge=1, le=60000)
    max_error_rate: float | None = Field(default=None, ge=0, le=1)


class PerformanceCaseUpdate(PerformanceCaseCreate):
    pass


class PerformanceCaseRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    folder_path: str | None = None
    method: str
    path: str
    priority: str | None = None
    status: str
    review_status: str | None = None
    version_no: str | None = None
    review_note: str | None = None
    tags_json: list[str] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int
    concurrency: int
    total_requests: int
    max_avg_response_ms: int | None = None
    max_p95_response_ms: int | None = None
    max_error_rate: float | None = None
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


class UnifiedCaseRead(BaseModel):
    case_type: str
    case_id: int
    project_id: int
    name: str
    folder_path: str | None = None
    priority: str
    status: str
    review_status: str | None = None
    version_no: str | None = None
    review_note: str | None = None
    tags_json: list[str] | None = None
    method: str | None = None
    path: str | None = None
    target_url: str | None = None
    expected_status: int | None = None
    step_count: int | None = None
    concurrency: int | None = None
    total_requests: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseFolderNode(BaseModel):
    name: str
    path: str
    count: int
    children: list["CaseFolderNode"] = Field(default_factory=list)


class CaseDuplicateItem(BaseModel):
    case_type: str
    case_id: int
    project_id: int
    name: str
    folder_path: str | None = None
    entry: str
    review_status: str | None = None
    updated_at: datetime | None = None


class CaseDuplicateGroup(BaseModel):
    case_type: str
    duplicate_key: str
    count: int
    items: list[CaseDuplicateItem]


class CaseHistoryRead(ORMBaseModel):
    id: int
    project_id: int
    case_type: str
    case_id: int
    case_name: str
    action: str
    version_no: str | None = None
    review_status: str | None = None
    review_note: str | None = None
    summary: str | None = None
    snapshot_json: dict | None = None
    changed_by: int | None = None
    created_at: datetime | None = None


class UnifiedCaseRef(BaseModel):
    case_type: str = Field(..., min_length=2, max_length=20)
    case_id: int


class CaseBatchUpdatePayload(BaseModel):
    items: list[UnifiedCaseRef]
    status: str | None = Field(default=None, min_length=2, max_length=20)
    add_tags: list[str] | None = None


class CaseBatchMoveFolderPayload(BaseModel):
    items: list[UnifiedCaseRef]
    folder_path: str | None = Field(default=None, max_length=255)


class CaseBatchReviewPayload(BaseModel):
    items: list[UnifiedCaseRef]
    review_status: str = Field(..., min_length=2, max_length=20)
    review_note: str | None = None


class CaseImportItem(BaseModel):
    case_type: str = Field(..., pattern="^(API|UI|PERF)$")
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    folder_path: str | None = None
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    review_status: str = Field(default="DRAFT", min_length=2, max_length=20)
    version_no: str = Field(default="1.0.0", min_length=1, max_length=30)
    review_note: str | None = None
    tags_json: list[str] | None = None
    method: str | None = None
    path: str | None = None
    target_url: str | None = None
    expected_status: int | None = None
    steps_json: list[dict] | None = None
    expect_text: str | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    assertions_json: list[dict] | None = None
    concurrency: int | None = None
    total_requests: int | None = None
    max_avg_response_ms: int | None = None
    max_p95_response_ms: int | None = None
    max_error_rate: float | None = None


class CaseImportPayload(BaseModel):
    items: list[CaseImportItem] = Field(default_factory=list)


class CaseBatchPlanPayload(BaseModel):
    items: list[UnifiedCaseRef]
    order_start: int = Field(default=1, ge=1)
    allow_unapproved: bool = False


class BatchActionResult(BaseModel):
    success: bool
    affected_count: int
    message: str


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


class EnvironmentValidationIssue(BaseModel):
    scope: str
    field: str
    missing_variables: list[str]
    sample: str | None = None


class EnvironmentValidationResult(BaseModel):
    environment_id: int
    project_id: int
    is_valid: bool
    issue_count: int
    summary: str
    scope_counts: dict[str, int]
    missing_variables: list[str]
    issues: list[EnvironmentValidationIssue]


class EnvironmentValidationDraft(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    base_url: str = Field(..., min_length=5, max_length=255)
    headers_json: dict | None = None
    variables_json: dict | None = None
    auth_config_json: dict | None = None


class ExecutionPrecheckResult(BaseModel):
    target_type: str
    target_id: int
    project_id: int
    environment_id: int | None = None
    is_valid: bool
    issue_count: int
    summary: str
    scope_counts: dict[str, int]
    missing_variables: list[str]
    issues: list[EnvironmentValidationIssue]


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
    allow_unapproved: bool = False


class TestPlanCaseRead(ORMBaseModel):
    id: int
    plan_id: int
    case_type: str
    case_id: int
    case_name: str
    case_snapshot_json: dict | None = None
    order_index: int
    created_by: int | None = None
    created_at: datetime | None = None


class TestPlanCaseReorderItem(BaseModel):
    id: int
    order_index: int = Field(..., ge=1)


class TestPlanCaseReorderPayload(BaseModel):
    items: list[TestPlanCaseReorderItem] = Field(default_factory=list)


class TestPlanRunCreate(BaseModel):
    environment_id: int | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_retries: int = Field(default=0, ge=0, le=3)


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
    failure_reason_counts: dict[str, int] = {}
    failure_reason_summary: list[str] = []


class ReportTrendPoint(BaseModel):
    plan_run_id: int
    plan_id: int
    plan_name: str
    status: str
    error_type: str | None = None
    pass_rate: float
    fail_count: int
    created_at: datetime | None = None
    duration_ms: int | None = None


class ReportPlanHistory(BaseModel):
    plan_id: int
    plan_name: str
    latest_plan_run_id: int
    latest_status: str
    latest_error_type: str | None = None
    latest_created_at: datetime | None = None
    latest_pass_rate: float
    average_pass_rate: float
    pass_rate_delta: float
    latest_fail_count: int
    average_duration_ms: int | None = None
    run_count: int
    failure_reason_counts: dict[str, int] = {}
    failure_reason_summary: list[str] = []


class ReportInsights(BaseModel):
    report_count: int
    success_count: int
    failed_count: int
    failed_case_count: int
    config_fail_count: int
    success_rate: float
    average_pass_rate: float
    average_duration_ms: int | None = None
    success_rate_delta: float = 0
    quality_score: float = 0
    flaky_plan_count: int = 0
    unstable_run_count: int = 0
    failure_reason_counts: dict[str, int] = {}
    failure_reason_summary: list[str] = []
    recent_trend: list[ReportTrendPoint] = []
    plan_histories: list[ReportPlanHistory] = []


class ReportHistoryItem(BaseModel):
    plan_run_id: int
    status: str
    error_type: str | None = None
    created_at: datetime | None = None
    duration_ms: int | None = None
    pass_rate: float
    fail_count: int


class ReportDetail(BaseModel):
    plan_run: TestPlanRunRead
    test_runs: list[TestRunRead]
    recent_history: list[ReportHistoryItem] = []
    defects: list["DefectRecordRead"] = []


class DefectRecordCreate(BaseModel):
    project_id: int
    run_id: int | None = None
    plan_run_id: int | None = None
    title: str = Field(..., min_length=2, max_length=180)
    platform: str = Field(default="GENERIC", min_length=2, max_length=30)
    external_key: str | None = Field(default=None, max_length=80)
    external_url: str | None = Field(default=None, max_length=512)
    status: str = Field(default="OPEN", min_length=2, max_length=30)
    severity: str = Field(default="P2", min_length=2, max_length=20)
    summary: str | None = None


class DefectRecordUpdate(BaseModel):
    title: str = Field(..., min_length=2, max_length=180)
    platform: str = Field(default="GENERIC", min_length=2, max_length=30)
    external_key: str | None = Field(default=None, max_length=80)
    external_url: str | None = Field(default=None, max_length=512)
    status: str = Field(default="OPEN", min_length=2, max_length=30)
    severity: str = Field(default="P2", min_length=2, max_length=20)
    summary: str | None = None


class DefectRecordRead(ORMBaseModel):
    id: int
    project_id: int
    run_id: int | None = None
    plan_run_id: int | None = None
    title: str
    platform: str
    external_key: str | None = None
    external_url: str | None = None
    status: str
    severity: str
    summary: str | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExecutionLogRead(BaseModel):
    run_id: int
    status: str
    stdout_text: str | None = None
    stderr_text: str | None = None
    exit_code: int | None = None
    error_type: str | None = None
    timeout_seconds: int | None = None
    step_results_json: list | None = None


class ExecutionStepRead(ORMBaseModel):
    id: int
    run_id: int
    step_index: int
    name: str
    status: str
    detail: str | None = None
    duration_ms: int | None = None
    raw_json: dict | None = None
    created_at: datetime | None = None


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
    max_retries: int = Field(default=0, ge=0, le=3)
