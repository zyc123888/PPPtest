import json

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.secrets import decrypt_secret, encrypt_secret, is_encryption_available


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_members")


class AIModelConfig(Base):
    __tablename__ = "ai_model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="OPENAI")
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="默认模型配置")
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="gpt-5.5")
    _legacy_api_key: Mapped[str | None] = mapped_column("api_key", String(255), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    @property
    def api_key(self) -> str | None:
        if self.api_key_encrypted:
            return decrypt_secret(self.api_key_encrypted)
        return self._legacy_api_key

    @api_key.setter
    def api_key(self, value: str | None) -> None:
        self.api_key_encrypted = encrypt_secret(value)
        self._legacy_api_key = None


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    _legacy_variables_json: Mapped[dict | None] = mapped_column("variables_json", JSON, nullable=True)
    variables_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    workspace = relationship("Workspace", back_populates="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    iterations = relationship("Iteration", back_populates="project", cascade="all, delete-orphan")
    requirements = relationship("Requirement", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("ProjectTask", back_populates="project", cascade="all, delete-orphan")
    defects = relationship("Defect", back_populates="project", cascade="all, delete-orphan")
    api_cases = relationship("APICase", back_populates="project", cascade="all, delete-orphan")
    ui_cases = relationship("UICase", back_populates="project", cascade="all, delete-orphan")
    environments = relationship("Environment", back_populates="project", cascade="all, delete-orphan")
    test_plans = relationship("TestPlan", back_populates="project", cascade="all, delete-orphan")
    test_runs = relationship("TestRun", back_populates="project", cascade="all, delete-orphan")
    case_generation_jobs = relationship("CaseGenerationJob", back_populates="project", cascade="all, delete-orphan")
    case_generation_v2_jobs = relationship("CaseGenerationV2Job", back_populates="project", cascade="all, delete-orphan")

    @property
    def variables_json(self) -> dict | None:
        if self.variables_encrypted:
            decrypted = decrypt_secret(self.variables_encrypted)
            if decrypted:
                try:
                    parsed = json.loads(decrypted)
                    return parsed if isinstance(parsed, dict) else None
                except (TypeError, ValueError):
                    return None
        return self._legacy_variables_json

    @variables_json.setter
    def variables_json(self, value: dict | None) -> None:
        if value and isinstance(value, dict):
            if is_encryption_available():
                self.variables_encrypted = encrypt_secret(json.dumps(value, ensure_ascii=False))
                self._legacy_variables_json = None
            else:
                self.variables_encrypted = None
                self._legacy_variables_json = value
        else:
            self.variables_encrypted = None
            self._legacy_variables_json = None


class APICase(Base):
    __tablename__ = "api_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    folder_path: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    path: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="P2")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    version_no: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0.0")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assertions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extractors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    steps_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    datasets_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    body_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    mock_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mock_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="api_cases")


class UICase(Base):
    __tablename__ = "ui_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    folder_path: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="P2")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    version_no: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0.0")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assertions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    steps_json: Mapped[list] = mapped_column(JSON, nullable=False)
    expect_text: Mapped[str] = mapped_column(String(255), nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    execution_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="stable")
    engine: Mapped[str] = mapped_column(String(20), nullable=False, default="native")
    self_heal_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_agent_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    allowed_origins_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prohibited_actions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ai_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    skill_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    generation_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="ui_cases")


class PerformanceCase(Base):
    __tablename__ = "performance_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    folder_path: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    path: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="P2")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    version_no: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0.0")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    body_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    max_avg_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_p95_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project")


class CaseChangeHistory(Base):
    __tablename__ = "case_change_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    case_name: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    version_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), index=True)

    project = relationship("Project")


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    _legacy_variables_json: Mapped[dict | None] = mapped_column("variables_json", JSON, nullable=True)
    variables_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    _legacy_auth_config_json: Mapped[dict | None] = mapped_column("auth_config_json", JSON, nullable=True)
    auth_config_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="environments")
    test_runs = relationship("TestRun", back_populates="environment")
    plan_runs = relationship("TestPlanRun", back_populates="environment")

    @property
    def variables_json(self) -> dict | None:
        if self.variables_encrypted:
            decrypted = decrypt_secret(self.variables_encrypted)
            if decrypted:
                try:
                    parsed = json.loads(decrypted)
                    return parsed if isinstance(parsed, dict) else None
                except (TypeError, ValueError):
                    return None
        return self._legacy_variables_json

    @variables_json.setter
    def variables_json(self, value: dict | None) -> None:
        if value and isinstance(value, dict):
            if is_encryption_available():
                self.variables_encrypted = encrypt_secret(json.dumps(value, ensure_ascii=False))
                self._legacy_variables_json = None
            else:
                self.variables_encrypted = None
                self._legacy_variables_json = value
        else:
            self.variables_encrypted = None
            self._legacy_variables_json = None

    @property
    def auth_config_json(self) -> dict | None:
        """认证配置透明加解密：密文列优先，兼容历史明文 JSON 列"""
        if self.auth_config_encrypted:
            decrypted = decrypt_secret(self.auth_config_encrypted)
            if decrypted:
                try:
                    parsed = json.loads(decrypted)
                    return parsed if isinstance(parsed, dict) else None
                except (TypeError, ValueError):
                    return None
        return self._legacy_auth_config_json

    @auth_config_json.setter
    def auth_config_json(self, value: dict | None) -> None:
        if value and isinstance(value, dict):
            if is_encryption_available():
                # 已配置密钥：加密存储，清除历史明文
                self.auth_config_encrypted = encrypt_secret(json.dumps(value, ensure_ascii=False))
                self._legacy_auth_config_json = None
            else:
                # 未配置密钥：降级为明文存储，保持向后兼容
                self.auth_config_encrypted = None
                self._legacy_auth_config_json = value
        else:
            self.auth_config_encrypted = None
            self._legacy_auth_config_json = None


class TestPlan(Base):
    __tablename__ = "test_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schedule_environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id"), nullable=True
    )
    schedule_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, index=True
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="test_plans")
    cases = relationship("TestPlanCase", back_populates="plan", cascade="all, delete-orphan")
    runs = relationship("TestPlanRun", back_populates="plan", cascade="all, delete-orphan")


class TestPlanCase(Base):
    __tablename__ = "test_plan_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plans.id"), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    case_name: Mapped[str] = mapped_column(String(120), nullable=False)
    case_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    plan = relationship("TestPlan", back_populates="cases")


class TestPlanRun(Base):
    __tablename__ = "test_plan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("test_plans.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    report_junit_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    report_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    plan = relationship("TestPlan", back_populates="runs")
    project = relationship("Project")
    environment = relationship("Environment", back_populates="plan_runs")
    test_runs = relationship("TestRun", back_populates="plan_run")


class UIBatchRun(Base):
    __tablename__ = "ui_batch_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id"), nullable=True, index=True
    )
    case_type: Mapped[str] = mapped_column(String(20), nullable=False, default="UI", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project")


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id"), nullable=True, index=True
    )
    plan_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("test_plan_runs.id"), nullable=True, index=True
    )
    batch_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ui_batch_runs.id"), nullable=True, index=True
    )
    case_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    case_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stdout_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    step_results_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="test_runs")
    environment = relationship("Environment", back_populates="test_runs")
    plan_run = relationship("TestPlanRun", back_populates="test_runs")
    logs = relationship("ExecutionLog", back_populates="run", cascade="all, delete-orphan")
    artifacts = relationship("ExecutionArtifact", back_populates="run", cascade="all, delete-orphan")
    steps = relationship("ExecutionStep", back_populates="run", cascade="all, delete-orphan")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), nullable=False, index=True)
    stream: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    run = relationship("TestRun", back_populates="logs")


class ExecutionArtifact(Base):
    __tablename__ = "execution_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    run = relationship("TestRun", back_populates="artifacts")


class ExecutionStep(Base):
    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), nullable=False, index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    run = relationship("TestRun", back_populates="steps")


class CaseGenerationJob(Base):
    __tablename__ = "case_generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="MARKDOWN")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    source_document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    active_attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="case_generation_jobs")
    artifacts = relationship("CaseGenerationArtifact", back_populates="job", cascade="all, delete-orphan")
    attempts = relationship(
        "CaseGenerationAttempt",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CaseGenerationAttempt.id",
    )


class CaseGenerationAttempt(Base):
    __tablename__ = "case_generation_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("case_generation_jobs.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    execution_token: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="full")
    source_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    input_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    job = relationship("CaseGenerationJob", back_populates="attempts")
    artifacts = relationship("CaseGenerationArtifact", back_populates="attempt")


class CaseGenerationArtifact(Base):
    __tablename__ = "case_generation_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("case_generation_jobs.id"), nullable=False, index=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("case_generation_attempts.id"), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    job = relationship("CaseGenerationJob", back_populates="artifacts")
    attempt = relationship("CaseGenerationAttempt", back_populates="artifacts")


class CaseGenerationV2Job(Base):
    __tablename__ = "case_generation_v2_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="MARKDOWN")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    source_document_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    progress_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    active_attempt_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="case_generation_v2_jobs")
    artifacts = relationship("CaseGenerationV2Artifact", back_populates="job", cascade="all, delete-orphan")
    attempts = relationship(
        "CaseGenerationV2Attempt",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CaseGenerationV2Attempt.id",
    )


class CaseGenerationV2Attempt(Base):
    __tablename__ = "case_generation_v2_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("case_generation_v2_jobs.id"), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    execution_token: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="full")
    source_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    input_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    job = relationship("CaseGenerationV2Job", back_populates="attempts")
    artifacts = relationship("CaseGenerationV2Artifact", back_populates="attempt")


class CaseGenerationV2Artifact(Base):
    __tablename__ = "case_generation_v2_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("case_generation_v2_jobs.id"), nullable=False, index=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("case_generation_v2_attempts.id"), nullable=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    job = relationship("CaseGenerationV2Job", back_populates="artifacts")
    attempt = relationship("CaseGenerationV2Attempt", back_populates="artifacts")


class DefectRecord(Base):
    __tablename__ = "defect_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("test_runs.id"), nullable=True, index=True)
    plan_run_id: Mapped[int | None] = mapped_column(ForeignKey("test_plan_runs.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False, default="GENERIC")
    external_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="P2")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="tester")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    tokens = relationship("UserToken", back_populates="user", cascade="all, delete-orphan")
    api_tokens = relationship("ApiToken", back_populates="user", cascade="all, delete-orphan")
    workspace_members = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")


class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    user = relationship("User", back_populates="tokens")


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    user = relationship("User", back_populates="api_tokens")


class ProjectNotificationSetting(Base):
    __tablename__ = "project_notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), nullable=False, unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False, default="FEISHU")
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notify_on: Mapped[str] = mapped_column(String(20), nullable=False, default="ALL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    project = relationship("Project", back_populates="members")
    user = relationship("User")


class Iteration(Base):
    __tablename__ = "iterations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PLANNING", index=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    capacity_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="iterations")


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    iteration_id: Mapped[int | None] = mapped_column(ForeignKey("iterations.id"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="P2", index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="FEATURE")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    story_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    folder_path: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    assignees_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    order_index: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="requirements")


class ProjectTask(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    iteration_id: Mapped[int | None] = mapped_column(ForeignKey("iterations.id"), nullable=True, index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="TODO", index=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="P2", index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    estimate_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    spent_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    assignees_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    order_index: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="tasks")


class Defect(Base):
    __tablename__ = "defects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    iteration_id: Mapped[int | None] = mapped_column(ForeignKey("iterations.id"), nullable=True, index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reproduce_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="MAJOR", index=True)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="P2", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="NEW", index=True)
    defect_type: Mapped[str] = mapped_column(String(20), nullable=False, default="FUNCTION", index=True)
    reproducibility: Mapped[str] = mapped_column(String(20), nullable=False, default="ALWAYS")
    found_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fixed_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    module: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assignees_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cc_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    order_index: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", back_populates="defects")


class RequirementCaseLink(Base):
    __tablename__ = "requirement_case_links"
    __table_args__ = (
        UniqueConstraint("requirement_id", "case_type", "case_id", name="uq_requirement_case_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class DefectRunLink(Base):
    __tablename__ = "defect_run_links"
    __table_args__ = (UniqueConstraint("defect_id", "test_run_id", name="uq_defect_run_link"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    defect_id: Mapped[int] = mapped_column(ForeignKey("defects.id"), nullable=False, index=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class DefectCaseLink(Base):
    __tablename__ = "defect_case_links"
    __table_args__ = (
        UniqueConstraint("defect_id", "case_type", "case_id", name="uq_defect_case_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    defect_id: Mapped[int] = mapped_column(ForeignKey("defects.id"), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
