from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORMBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    workspace_id: int | None = None
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = None
    base_url: str = Field(..., min_length=5, max_length=255)
    code: str | None = Field(default=None, max_length=40)
    status: str = Field(default="ACTIVE", max_length=20)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    base_url: str | None = Field(default=None, min_length=5, max_length=255)
    code: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=20)


class ProjectRead(ORMBaseModel):
    id: int
    workspace_id: int
    name: str
    description: str | None = None
    base_url: str
    status: str | None = "ACTIVE"
    code: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectVariablesUpdate(BaseModel):
    variables_json: dict | None = None


class APICaseCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    folder_path: str | None = Field(default=None, max_length=255)
    method: str = Field(default="GET", min_length=3, max_length=10)
    path: str = Field(..., min_length=1)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    review_status: str = Field(default="DRAFT", min_length=2, max_length=20)
    version_no: str = Field(default="1.0.0", min_length=1, max_length=30)
    review_note: str | None = None
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    extractors_json: list[dict] | None = None
    steps_json: list[dict] | None = None
    datasets_json: list[dict] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int = 200
    mock_enabled: bool = False
    mock_config_json: dict | None = None


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
    extractors_json: list[dict] | None = None
    steps_json: list[dict] | None = None
    datasets_json: list[dict] | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    expected_status: int
    mock_enabled: bool = False
    mock_config_json: dict | None = None
    submitted_review_at: datetime | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class APICaseFolderNode(BaseModel):
    path: str
    name: str
    case_count: int = 0
    children: list["APICaseFolderNode"] = Field(default_factory=list)


class APICaseFolderTree(BaseModel):
    total: int = 0
    ungrouped: int = 0
    folders: list[APICaseFolderNode] = Field(default_factory=list)


class APICaseFolderRename(BaseModel):
    project_id: int
    old_path: str = Field(..., min_length=1, max_length=255)
    new_path: str = Field(..., min_length=1, max_length=255)


class APICaseBatchPatch(BaseModel):
    folder_path: str | None = Field(default=None, max_length=255)
    priority: str | None = Field(default=None, min_length=2, max_length=20)
    status: str | None = Field(default=None, min_length=2, max_length=20)
    tags_json: list[str] | None = None


class APICaseBatchUpdate(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=200)
    patch: APICaseBatchPatch


class APICaseBatchDelete(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=200)


class APICaseBatchResult(BaseModel):
    affected: int = 0


class APICaseReviewDecision(BaseModel):
    result: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    note: str | None = Field(default=None, max_length=2000)


class APICasePage(BaseModel):
    items: list[APICaseRead]
    total: int


class APICaseStats(BaseModel):
    total: int = 0
    active: int = 0
    approved: int = 0
    recent_success_rate: float | None = None


class APICaseDebugRequest(APICaseCreate):
    environment_id: int | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class APICaseDebugResponse(BaseModel):
    request: dict
    response: dict
    duration_ms: int
    assertion_passed: bool | None = None
    assertion_results: list[dict] = Field(default_factory=list)
    extracted_variables: dict = Field(default_factory=dict)
    extractor_results: list[dict] = Field(default_factory=list)


UI_STEP_ACTIONS = {
    "goto",
    "click",
    "fill",
    "press",
    "select_option",
    "check",
    "uncheck",
    "hover",
    "wait",
    "wait_for_selector",
    "wait_for_text",
    "assert_text",
    "assert_visible",
    "assert_hidden",
    "assert_url_contains",
    "assert_title_contains",
    "set_viewport",
}

UI_ASSERTION_TYPES = {
    "text_present",
    "text_visible",
    "text_hidden",
    "selector_visible",
    "selector_hidden",
    "url_contains",
    "title_contains",
    "visual",
}


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_ui_target(value: dict) -> bool:
    locator = value.get("locator")
    locator = locator if isinstance(locator, dict) else {}
    return any(
        _has_text(candidate)
        for candidate in (
            value.get("selector"),
            value.get("target"),
            value.get("test_id"),
            value.get("role"),
            value.get("accessible_name"),
            value.get("label"),
            value.get("placeholder"),
            value.get("text"),
            locator.get("selector"),
            locator.get("test_id"),
            locator.get("role"),
            locator.get("name"),
            locator.get("label"),
            locator.get("placeholder"),
            locator.get("text"),
        )
    )


def _validate_ui_steps(steps: list[dict]) -> None:
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"第 {index} 个 UI 步骤必须是对象")
        action = str(step.get("action") or "").strip()
        if action not in UI_STEP_ACTIONS:
            raise ValueError(f"第 {index} 个 UI 步骤类型不支持：{action or '空'}")

        if action in {"goto", "wait_for_text", "assert_text", "assert_url_contains", "assert_title_contains"}:
            if not _has_text(step.get("value")):
                raise ValueError(f"第 {index} 个 UI 步骤 {action} 必须填写值")
        if action in {
            "click",
            "fill",
            "press",
            "select_option",
            "check",
            "uncheck",
            "hover",
            "wait_for_selector",
            "assert_visible",
            "assert_hidden",
        } and not _has_ui_target(step):
            raise ValueError(f"第 {index} 个 UI 步骤 {action} 必须填写语义目标或选择器")
        if action in {"press", "select_option"} and not (
            _has_text(step.get("value")) or (isinstance(step.get("value"), list) and step.get("value"))
        ):
            raise ValueError(f"第 {index} 个 UI 步骤 {action} 必须填写值")
        if action == "wait":
            duration_ms = step.get("duration_ms")
            if not isinstance(duration_ms, int) or not 1 <= duration_ms <= 60_000:
                raise ValueError(f"第 {index} 个 UI 步骤 wait 的等待时间必须是 1 到 60000 毫秒")
        if action == "set_viewport":
            width = step.get("width")
            height = step.get("height")
            if not isinstance(width, int) or not isinstance(height, int) or not 320 <= width <= 3840 or not 320 <= height <= 2160:
                raise ValueError(f"第 {index} 个 UI 步骤 set_viewport 的宽高超出支持范围")


def _validate_ui_assertions(assertions: list[dict] | None) -> None:
    for index, assertion in enumerate(assertions or [], start=1):
        if not isinstance(assertion, dict):
            raise ValueError(f"第 {index} 个 UI 断言必须是对象")
        assertion_type = str(assertion.get("type") or "").strip()
        if assertion_type not in UI_ASSERTION_TYPES:
            raise ValueError(f"第 {index} 个 UI 断言类型不支持：{assertion_type or '空'}")
        if assertion_type in {"selector_visible", "selector_hidden"} and not _has_ui_target(assertion):
            raise ValueError(f"第 {index} 个 UI 断言 {assertion_type} 必须填写语义目标或选择器")
        if assertion_type in {"text_present", "text_visible", "text_hidden", "url_contains", "title_contains"}:
            value = assertion.get("value", assertion.get("expected"))
            if not _has_text(value):
                raise ValueError(f"第 {index} 个 UI 断言 {assertion_type} 必须填写期望值")
        if assertion_type == "visual" and not _has_text(assertion.get("value")):
            raise ValueError(f"第 {index} 个 UI 断言 visual 必须填写视觉期望")


class UICaseCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    folder_path: str | None = Field(default=None, max_length=255)
    target_url: str = Field(..., min_length=5)
    priority: str = Field(default="P2", min_length=2, max_length=20)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)
    review_status: str = Field(default="DRAFT", min_length=2, max_length=20)
    version_no: str = Field(default="1.0.0", min_length=1, max_length=30)
    review_note: str | None = None
    tags_json: list[str] | None = None
    assertions_json: list[dict] | None = None
    steps_json: list[dict] = Field(default_factory=list)
    expect_text: str = Field(..., min_length=1, max_length=255)
    generation_mode: str = Field(default="manual", pattern="^(manual|ai_skill)$")
    execution_mode: str = Field(default="stable", pattern="^(stable|adaptive|explore|visual)$")
    engine: str = Field(default="native", pattern="^(native|midscene)$")
    self_heal_enabled: bool = False
    max_agent_steps: int = Field(default=10, ge=1, le=30)
    allowed_origins_json: list[str] | None = None
    prohibited_actions_json: list[str] | None = None
    ai_goal: str | None = Field(default=None, max_length=4000)
    skill_name: str | None = Field(default=None, max_length=120)
    skill_version: str | None = Field(default=None, max_length=30)
    generation_meta_json: dict | None = None

    @model_validator(mode="after")
    def validate_ui_workflow(self):
        _validate_ui_steps(self.steps_json)
        _validate_ui_assertions(self.assertions_json)
        return self


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
    generation_mode: str = "manual"
    execution_mode: str = "stable"
    engine: str = "native"
    self_heal_enabled: bool = False
    max_agent_steps: int = 10
    allowed_origins_json: list[str] | None = None
    prohibited_actions_json: list[str] | None = None
    ai_goal: str | None = None
    skill_name: str | None = None
    skill_version: str | None = None
    generation_meta_json: dict | None = None
    submitted_review_at: datetime | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UICaseAIGenerateRequest(BaseModel):
    project_id: int
    target_url: str = Field(..., min_length=5, max_length=2000)
    goal: str = Field(..., min_length=5, max_length=4000)
    context: str | None = Field(default=None, max_length=8000)
    max_steps: int = Field(default=12, ge=1, le=30)
    execution_mode: str = Field(default="adaptive", pattern="^(stable|adaptive|explore|visual)$")


class UICaseAIGenerateResponse(BaseModel):
    draft: UICaseCreate
    skill_name: str
    skill_version: str
    model: str
    warnings: list[str] = Field(default_factory=list)
    design_notes: list[str] = Field(default_factory=list)


class UICaseFolderNode(BaseModel):
    path: str
    name: str
    case_count: int = 0
    children: list["UICaseFolderNode"] = Field(default_factory=list)


class UICaseFolderTree(BaseModel):
    total: int = 0
    ungrouped: int = 0
    folders: list[UICaseFolderNode] = Field(default_factory=list)


class UICaseFolderRename(BaseModel):
    project_id: int
    old_path: str = Field(..., min_length=1, max_length=255)
    new_path: str = Field(..., min_length=1, max_length=255)


class UICaseBatchPatch(BaseModel):
    folder_path: str | None = Field(default=None, max_length=255)
    priority: str | None = Field(default=None, min_length=2, max_length=20)
    status: str | None = Field(default=None, min_length=2, max_length=20)
    tags_json: list[str] | None = None


class UICaseBatchUpdate(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=200)
    patch: UICaseBatchPatch


class UICaseBatchDelete(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=200)


class UICaseBatchResult(BaseModel):
    affected: int = 0


class UICaseReviewDecision(BaseModel):
    result: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    note: str | None = Field(default=None, max_length=2000)


class UICasePage(BaseModel):
    items: list[UICaseRead]
    total: int


class UICaseStats(BaseModel):
    total: int = 0
    active: int = 0
    approved: int = 0
    recent_success_rate: float | None = None


class UIBatchRunCreate(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=100)
    environment_id: int | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    max_retries: int = Field(default=0, ge=0, le=3)


class UIBatchRunRead(ORMBaseModel):
    id: int
    project_id: int
    environment_id: int | None = None
    case_type: str = "UI"
    status: str
    summary: str | None = None
    error_type: str | None = None
    total_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PerformanceCaseCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    folder_path: str | None = Field(default=None, max_length=255)
    method: str = Field(default="GET", min_length=3, max_length=10)
    path: str = Field(..., min_length=1)
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
    submitted_review_at: datetime | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PerformanceCaseFolderNode(BaseModel):
    path: str
    name: str
    case_count: int = 0
    children: list["PerformanceCaseFolderNode"] = Field(default_factory=list)


class PerformanceCaseFolderTree(BaseModel):
    total: int = 0
    ungrouped: int = 0
    folders: list[PerformanceCaseFolderNode] = Field(default_factory=list)


class PerformanceCaseFolderRename(BaseModel):
    project_id: int
    old_path: str = Field(..., min_length=1, max_length=255)
    new_path: str = Field(..., min_length=1, max_length=255)


class PerformanceCaseBatchPatch(BaseModel):
    folder_path: str | None = Field(default=None, max_length=255)
    priority: str | None = Field(default=None, min_length=2, max_length=20)
    status: str | None = Field(default=None, min_length=2, max_length=20)
    tags_json: list[str] | None = None


class PerformanceCaseBatchUpdate(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=200)
    patch: PerformanceCaseBatchPatch


class PerformanceCaseBatchDelete(BaseModel):
    case_ids: list[int] = Field(..., min_length=1, max_length=200)


class PerformanceCaseBatchResult(BaseModel):
    affected: int = 0


class PerformanceCaseReviewDecision(BaseModel):
    result: str = Field(..., pattern="^(APPROVED|REJECTED)$")
    note: str | None = Field(default=None, max_length=2000)


class PerformanceCasePage(BaseModel):
    items: list[PerformanceCaseRead]
    total: int


class PerformanceCaseStats(BaseModel):
    total: int = 0
    active: int = 0
    approved: int = 0
    recent_success_rate: float | None = None


class TestRunRead(ORMBaseModel):
    id: int
    project_id: int
    environment_id: int | None = None
    plan_run_id: int | None = None
    batch_run_id: int | None = None
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


class TestRunPage(BaseModel):
    items: list[TestRunRead]
    total: int
    running: int = 0
    failed: int = 0
    retryable: int = 0


class UIBatchRunDetail(UIBatchRunRead):
    runs: list[TestRunRead] = Field(default_factory=list)


class CaseGenerationJobCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    mode: str = Field(default="MARKDOWN", min_length=2, max_length=30)
    source_type: str = Field(default="PASTE", min_length=2, max_length=20)
    source_document_name: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    markdown_text: str | None = Field(default=None, min_length=10, max_length=5_000_000)
    extra_notes: str | None = Field(default=None, max_length=100_000)
    export_xmind: bool = True
    openai_api_key: str | None = None


class CaseGenerationProgressStage(BaseModel):
    key: str
    title: str
    status: str
    summary: str | None = None


class AIModelConfigUpsert(BaseModel):
    workspace_id: int
    provider: str = Field(default="OPENAI", min_length=2, max_length=30)
    name: str = Field(default="默认模型配置", min_length=2, max_length=120)
    base_url: str | None = Field(default=None, max_length=1000)
    model: str = Field(default="gpt-5.5", min_length=2, max_length=80)
    api_key: str = Field(..., min_length=10, max_length=255)


class AIModelConfigRead(ORMBaseModel):
    id: int
    workspace_id: int
    provider: str
    name: str
    base_url: str | None = None
    model: str
    api_key: str | None = None
    is_active: int
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AIModelOptionRead(BaseModel):
    provider: str
    label: str
    value: str
    base_url: str


class CaseGenerationJobRead(ORMBaseModel):
    id: int
    workspace_id: int
    project_id: int
    name: str
    mode: str
    status: str
    source_document_name: str | None = None
    progress_json: dict | None = None
    input_payload_json: dict | None = None
    task_id: str | None = None
    active_attempt_id: int | None = None
    summary: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseGenerationArtifactRead(ORMBaseModel):
    id: int
    job_id: int
    attempt_id: int | None = None
    artifact_type: str
    file_name: str | None = None
    content_json: dict | list | None = None
    expired_at: datetime | None = None
    created_at: datetime | None = None


class CaseGenerationAttemptRead(ORMBaseModel):
    id: int
    job_id: int
    run_id: str
    kind: str
    source_id: str | None = None
    status: str
    task_id: str | None = None
    progress_json: dict | None = None
    summary: str | None = None
    error_message: str | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseGenerationJobDetail(BaseModel):
    job: CaseGenerationJobRead
    artifacts: list[CaseGenerationArtifactRead] = Field(default_factory=list)
    attempts: list[CaseGenerationAttemptRead] = Field(default_factory=list)


class CaseGenerationV2JobCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=2, max_length=120)
    mode: str = Field(default="MARKDOWN", min_length=2, max_length=30)
    pipeline_mode: str = Field(default="lite", pattern="^(clone|trusted_v2|lite|trusted)$")
    trusted_generation_strategy: str = Field(default="source_shard", pattern="^(source_shard|lite_review)$")
    generation_density: str = Field(default="balanced", pattern="^(concise|balanced|exhaustive)$")
    source_type: str = Field(default="PASTE", min_length=2, max_length=20)
    source_document_name: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=1000)
    markdown_text: str | None = Field(default=None, min_length=10, max_length=5_000_000)
    extra_notes: str | None = Field(default=None, max_length=100_000)
    export_xmind: bool = True
    openai_api_key: str | None = None


class CaseGenerationV2JobRead(ORMBaseModel):
    id: int
    workspace_id: int
    project_id: int
    name: str
    mode: str
    status: str
    source_document_name: str | None = None
    progress_json: dict | None = None
    input_payload_json: dict | None = None
    task_id: str | None = None
    active_attempt_id: int | None = None
    summary: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseGenerationV2ArtifactRead(ORMBaseModel):
    id: int
    job_id: int
    attempt_id: int | None = None
    artifact_type: str
    file_name: str | None = None
    content_json: dict | list | None = None
    expired_at: datetime | None = None
    created_at: datetime | None = None


class CaseGenerationV2AttemptRead(ORMBaseModel):
    id: int
    job_id: int
    run_id: str
    kind: str
    source_id: str | None = None
    status: str
    task_id: str | None = None
    progress_json: dict | None = None
    summary: str | None = None
    error_message: str | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseGenerationV2JobDetail(BaseModel):
    job: CaseGenerationV2JobRead
    artifacts: list[CaseGenerationV2ArtifactRead] = Field(default_factory=list)
    attempts: list[CaseGenerationV2AttemptRead] = Field(default_factory=list)


class CaseGenerationMetricsComparison(BaseModel):
    baseline_job_id: int | None = None
    candidate_job_id: int
    baseline: dict | None = None
    candidate: dict | None = None
    delta: dict | None = None


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
    steps_json: list[dict] | None = None
    expect_text: str | None = None
    headers_json: dict | None = None
    body_json: dict | None = None
    assertions_json: list[dict] | None = None
    generation_mode: str | None = None
    execution_mode: str | None = None
    engine: str | None = None
    self_heal_enabled: bool | None = None
    max_agent_steps: int | None = None
    allowed_origins_json: list[str] | None = None
    prohibited_actions_json: list[str] | None = None
    ai_goal: str | None = None
    skill_name: str | None = None
    skill_version: str | None = None
    generation_meta_json: dict | None = None
    concurrency: int | None = None
    total_requests: int | None = None
    max_avg_response_ms: int | None = None
    max_p95_response_ms: int | None = None
    max_error_rate: float | None = None
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
    extractors_json: list[dict] | None = None
    generation_mode: str = Field(default="manual", pattern="^(manual|ai_skill)$")
    execution_mode: str = Field(default="stable", pattern="^(stable|adaptive|explore|visual)$")
    engine: str = Field(default="native", pattern="^(native|midscene)$")
    self_heal_enabled: bool = False
    max_agent_steps: int = Field(default=10, ge=1, le=30)
    allowed_origins_json: list[str] | None = None
    prohibited_actions_json: list[str] | None = None
    ai_goal: str | None = Field(default=None, max_length=4000)
    skill_name: str | None = Field(default=None, max_length=120)
    skill_version: str | None = Field(default=None, max_length=30)
    generation_meta_json: dict | None = None
    concurrency: int | None = None
    total_requests: int | None = None
    max_avg_response_ms: int | None = None
    max_p95_response_ms: int | None = None
    max_error_rate: float | None = None


class CaseImportPayload(BaseModel):
    items: list[CaseImportItem] = Field(default_factory=list)


class ApiSpecImportPayload(BaseModel):
    project_id: int
    source_type: str = Field(..., pattern="^(openapi|postman)$")
    content: str = Field(..., min_length=2)
    folder_path: str | None = Field(default=None, max_length=255)
    dry_run: bool = False


class ApiSpecImportPreviewItem(BaseModel):
    name: str
    method: str
    path: str
    folder_path: str | None = None


class ApiSpecImportResult(BaseModel):
    source_type: str
    detected_count: int = 0
    created_count: int = 0
    dry_run: bool = False
    items: list[ApiSpecImportPreviewItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
    member_id: int
    workspace_id: int
    workspace_name: str
    role: str


class ApiTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    expires_days: int | None = Field(None, ge=1, le=3650)


class ApiTokenRead(ORMBaseModel):
    id: int
    name: str
    token_prefix: str
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None


class ApiTokenCreated(ApiTokenRead):
    token: str


class NotificationSettingRead(ORMBaseModel):
    project_id: int
    enabled: bool = False
    channel_type: str = "FEISHU"
    webhook_url: str | None = None
    secret: str | None = None
    notify_on: str = "ALL"
    updated_at: datetime | None = None


class NotificationSettingUpdate(BaseModel):
    enabled: bool = False
    channel_type: str = Field("FEISHU", pattern="^(FEISHU|DINGTALK|WECOM|CUSTOM)$")
    webhook_url: str | None = Field(None, max_length=512)
    secret: str | None = Field(None, max_length=128)
    notify_on: str = Field("ALL", pattern="^(ALL|FAIL_ONLY)$")

    @model_validator(mode="after")
    def _validate_webhook(self) -> "NotificationSettingUpdate":
        if self.enabled:
            url = (self.webhook_url or "").strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError("启用通知时必须填写合法的 Webhook 地址")
            self.webhook_url = url
        return self


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
    schedule_enabled: bool = False
    schedule_cron: str | None = None
    schedule_environment_id: int | None = None
    schedule_timeout_seconds: int | None = None
    schedule_max_retries: int = 0
    next_run_at: datetime | None = None
    last_triggered_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestPlanScheduleUpdate(BaseModel):
    schedule_enabled: bool = False
    schedule_cron: str | None = Field(None, max_length=120)
    schedule_environment_id: int | None = None
    schedule_timeout_seconds: int | None = Field(None, ge=1, le=7200)
    schedule_max_retries: int = Field(0, ge=0, le=3)

    @model_validator(mode="after")
    def _validate_cron(self) -> "TestPlanScheduleUpdate":
        from croniter import croniter

        if self.schedule_enabled:
            if not self.schedule_cron or not self.schedule_cron.strip():
                raise ValueError("启用定时执行时必须填写 cron 表达式")
            if not croniter.is_valid(self.schedule_cron.strip()):
                raise ValueError("cron 表达式不合法，请使用 5 段标准格式，例如 0 2 * * *")
            self.schedule_cron = self.schedule_cron.strip()
        return self


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
    share_token: str | None = None
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


class PublicTestPlanRunRead(BaseModel):
    id: int
    status: str
    summary: str | None = None
    error_type: str | None = None
    total_count: int
    pass_count: int
    fail_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class PublicTestRunRead(BaseModel):
    case_type: str
    case_name: str
    status: str
    summary: str | None = None
    error_type: str | None = None
    duration_ms: int | None = None


class PublicReportDetail(BaseModel):
    plan_run: PublicTestPlanRunRead
    test_runs: list[PublicTestRunRead]
    recent_history: list[ReportHistoryItem] = []


class ReportShareResult(BaseModel):
    plan_run_id: int
    share_token: str | None = None
    share_url: str
    enabled: bool


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
    password: str = Field(..., min_length=6, max_length=64)
    display_name: str | None = None
    role: str = Field(default="tester", min_length=2, max_length=50)
    status: str = Field(default="ACTIVE", min_length=2, max_length=20)


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


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(..., min_length=6, max_length=64)
    new_password: str = Field(..., min_length=6, max_length=64)


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


# ---------------------------------------------------------------------------
# Project collaboration module (requirements / iterations / tasks / defects)
# ---------------------------------------------------------------------------


class ProjectMemberCreate(BaseModel):
    user_id: int
    role: str = Field(default="member", max_length=30)


class ProjectMemberUpdate(BaseModel):
    role: str = Field(..., max_length=30)


class ProjectMemberRead(ORMBaseModel):
    id: int
    project_id: int
    user_id: int
    username: str | None = None
    display_name: str | None = None
    role: str
    created_at: datetime | None = None


class IterationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    goal: str | None = None
    status: str = Field(default="PLANNING", max_length=20)
    start_date: datetime | None = None
    end_date: datetime | None = None
    capacity_points: float | None = None


class IterationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal: str | None = None
    status: str | None = Field(default=None, max_length=20)
    start_date: datetime | None = None
    end_date: datetime | None = None
    capacity_points: float | None = None


class IterationRead(ORMBaseModel):
    id: int
    project_id: int
    name: str
    goal: str | None = None
    status: str
    start_date: datetime | None = None
    end_date: datetime | None = None
    capacity_points: float | None = None
    sort_order: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RequirementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    status: str = Field(default="PENDING", max_length=20)
    priority: str = Field(default="P2", max_length=10)
    type: str = Field(default="FEATURE", max_length=20)
    iteration_id: int | None = None
    parent_id: int | None = None
    owner_id: int | None = None
    story_points: float | None = None
    folder_path: str | None = Field(default=None, max_length=255)
    tags_json: list | None = None
    assignees_json: list | None = None
    due_date: datetime | None = None


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: str | None = Field(default=None, max_length=10)
    type: str | None = Field(default=None, max_length=20)
    iteration_id: int | None = None
    parent_id: int | None = None
    owner_id: int | None = None
    story_points: float | None = None
    folder_path: str | None = Field(default=None, max_length=255)
    tags_json: list | None = None
    assignees_json: list | None = None
    due_date: datetime | None = None


class RequirementRead(ORMBaseModel):
    id: int
    project_id: int
    iteration_id: int | None = None
    parent_id: int | None = None
    title: str
    description: str | None = None
    status: str
    priority: str
    type: str
    owner_id: int | None = None
    reporter_id: int | None = None
    story_points: float | None = None
    folder_path: str | None = None
    tags_json: list | None = None
    assignees_json: list | None = None
    order_index: float | None = None
    due_date: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RequirementPage(BaseModel):
    items: list[RequirementRead]
    total: int
    page: int
    page_size: int


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    status: str = Field(default="TODO", max_length=20)
    priority: str = Field(default="P2", max_length=10)
    iteration_id: int | None = None
    requirement_id: int | None = None
    assignee_id: int | None = None
    assignees_json: list | None = None
    estimate_hours: float | None = None
    due_date: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: str | None = Field(default=None, max_length=10)
    iteration_id: int | None = None
    requirement_id: int | None = None
    assignee_id: int | None = None
    assignees_json: list | None = None
    estimate_hours: float | None = None
    spent_hours: float | None = None
    due_date: datetime | None = None


class TaskRead(ORMBaseModel):
    id: int
    project_id: int
    iteration_id: int | None = None
    requirement_id: int | None = None
    title: str
    description: str | None = None
    status: str
    priority: str
    assignee_id: int | None = None
    assignees_json: list | None = None
    reporter_id: int | None = None
    estimate_hours: float | None = None
    spent_hours: float | None = None
    order_index: float | None = None
    due_date: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskPage(BaseModel):
    items: list[TaskRead]
    total: int
    page: int
    page_size: int


class DefectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    reproduce_steps: str | None = None
    severity: str = Field(default="MAJOR", max_length=20)
    priority: str = Field(default="P2", max_length=10)
    status: str = Field(default="NEW", max_length=20)
    defect_type: str = Field(default="FUNCTION", max_length=20)
    reproducibility: str = Field(default="ALWAYS", max_length=20)
    found_version: str | None = Field(default=None, max_length=80)
    fixed_version: str | None = Field(default=None, max_length=80)
    module: str | None = Field(default=None, max_length=120)
    resolution: str | None = None
    iteration_id: int | None = None
    requirement_id: int | None = None
    assignee_id: int | None = None
    assignees_json: list | None = None
    cc_json: list | None = None
    tags_json: list | None = None
    due_date: datetime | None = None


class DefectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    reproduce_steps: str | None = None
    severity: str | None = Field(default=None, max_length=20)
    priority: str | None = Field(default=None, max_length=10)
    defect_type: str | None = Field(default=None, max_length=20)
    reproducibility: str | None = Field(default=None, max_length=20)
    found_version: str | None = Field(default=None, max_length=80)
    fixed_version: str | None = Field(default=None, max_length=80)
    module: str | None = Field(default=None, max_length=120)
    resolution: str | None = None
    iteration_id: int | None = None
    requirement_id: int | None = None
    assignee_id: int | None = None
    assignees_json: list | None = None
    cc_json: list | None = None
    tags_json: list | None = None
    due_date: datetime | None = None


class DefectRead(ORMBaseModel):
    id: int
    project_id: int
    iteration_id: int | None = None
    requirement_id: int | None = None
    title: str
    description: str | None = None
    reproduce_steps: str | None = None
    severity: str
    priority: str
    status: str
    defect_type: str | None = None
    reproducibility: str | None = None
    found_version: str | None = None
    fixed_version: str | None = None
    module: str | None = None
    resolution: str | None = None
    assignee_id: int | None = None
    assignees_json: list | None = None
    cc_json: list | None = None
    tags_json: list | None = None
    reporter_id: int | None = None
    order_index: float | None = None
    due_date: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DefectPage(BaseModel):
    items: list[DefectRead]
    total: int
    page: int
    page_size: int


class DefectFromRunCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    severity: str = Field(default="MAJOR", max_length=20)
    priority: str = Field(default="P2", max_length=10)
    requirement_id: int | None = None
    assignee_id: int | None = None
    description: str | None = None


class UploadResult(BaseModel):
    url: str
    filename: str
    size: int


class StatusChange(BaseModel):
    status: str = Field(..., max_length=20)


class RankUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    order_index: float


class CaseLinkCreate(BaseModel):
    case_type: str = Field(..., max_length=20)
    case_id: int


class CaseLinkRead(ORMBaseModel):
    id: int
    case_type: str
    case_id: int
    case_name: str | None = None
    created_at: datetime | None = None


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1)


class CommentRead(ORMBaseModel):
    id: int
    project_id: int
    entity_type: str
    entity_id: int
    author_id: int | None = None
    author_name: str | None = None
    content: str
    created_at: datetime | None = None


class ActivityRead(ORMBaseModel):
    id: int
    project_id: int
    entity_type: str
    entity_id: int
    action: str
    payload_json: dict | None = None
    actor_id: int | None = None
    actor_name: str | None = None
    created_at: datetime | None = None


class ProjectOverview(BaseModel):
    project_id: int
    my_role: str | None = None
    requirement_counts: dict[str, int]
    task_counts: dict[str, int]
    defect_counts: dict[str, int]
    requirement_total: int
    task_total: int
    defect_total: int
    open_defect_total: int
    iteration_total: int
    active_iteration: IterationRead | None = None
    member_total: int
    case_coverage_rate: float
    my_open_requirements: int
    my_open_tasks: int
    my_open_defects: int
    recent_activities: list[ActivityRead]


class TraceRow(BaseModel):
    requirement_id: int
    requirement_title: str
    requirement_status: str
    priority: str
    api_case_count: int
    ui_case_count: int
    perf_case_count: int
    total_case_count: int
    last_run_status: str | None = None
    open_defect_count: int
    closed_defect_count: int
    coverage: str


class TraceMatrix(BaseModel):
    project_id: int
    rows: list[TraceRow]
