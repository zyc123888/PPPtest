from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


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


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    workspace = relationship("Workspace", back_populates="projects")
    api_cases = relationship("APICase", back_populates="project", cascade="all, delete-orphan")
    ui_cases = relationship("UICase", back_populates="project", cascade="all, delete-orphan")
    environments = relationship("Environment", back_populates="project", cascade="all, delete-orphan")
    test_plans = relationship("TestPlan", back_populates="project", cascade="all, delete-orphan")
    test_runs = relationship("TestRun", back_populates="project", cascade="all, delete-orphan")


class APICase(Base):
    __tablename__ = "api_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="GET")
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    body_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_status: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    project = relationship("Project", back_populates="api_cases")


class UICase(Base):
    __tablename__ = "ui_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_url: Mapped[str] = mapped_column(String(255), nullable=False)
    steps_json: Mapped[list] = mapped_column(JSON, nullable=False)
    expect_text: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    project = relationship("Project", back_populates="ui_cases")


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    headers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    variables_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    project = relationship("Project", back_populates="environments")
    test_runs = relationship("TestRun", back_populates="environment")
    plan_runs = relationship("TestPlanRun", back_populates="environment")


class TestPlan(Base):
    __tablename__ = "test_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
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
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    report_junit_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    report_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    plan = relationship("TestPlan", back_populates="runs")
    project = relationship("Project")
    environment = relationship("Environment", back_populates="plan_runs")
    test_runs = relationship("TestRun", back_populates="plan_run")


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
    case_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    case_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    user = relationship("User", back_populates="tokens")
