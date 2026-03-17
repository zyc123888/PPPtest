from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)


def ensure_schema(db_engine) -> None:
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())

    with db_engine.begin() as connection:
        if db_engine.url.get_backend_name().startswith("mysql"):
            db_name = db_engine.url.database or "test_platform"
            connection.execute(
                text(
                    f"ALTER DATABASE {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            for table_name in tables:
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )

        if "projects" in tables:
            columns = {col["name"] for col in inspector.get_columns("projects")}
            if "workspace_id" not in columns:
                connection.execute(text("ALTER TABLE projects ADD COLUMN workspace_id INTEGER NULL"))

        if "test_runs" in tables:
            columns = {col["name"] for col in inspector.get_columns("test_runs")}
            if "environment_id" not in columns:
                connection.execute(text("ALTER TABLE test_runs ADD COLUMN environment_id INTEGER NULL"))
            if "plan_run_id" not in columns:
                connection.execute(text("ALTER TABLE test_runs ADD COLUMN plan_run_id INTEGER NULL"))
            if "started_at" not in columns:
                connection.execute(text("ALTER TABLE test_runs ADD COLUMN started_at DATETIME NULL"))
            if "finished_at" not in columns:
                connection.execute(text("ALTER TABLE test_runs ADD COLUMN finished_at DATETIME NULL"))

        if "test_plan_runs" in tables:
            columns = {col["name"] for col in inspector.get_columns("test_plan_runs")}
            if "report_json_path" not in columns:
                connection.execute(text("ALTER TABLE test_plan_runs ADD COLUMN report_json_path VARCHAR(512) NULL"))
            if "report_junit_path" not in columns:
                connection.execute(text("ALTER TABLE test_plan_runs ADD COLUMN report_junit_path VARCHAR(512) NULL"))
            if "report_generated_at" not in columns:
                connection.execute(text("ALTER TABLE test_plan_runs ADD COLUMN report_generated_at DATETIME NULL"))

        if "users" in tables:
            columns = {col["name"] for col in inspector.get_columns("users")}
            if "password_hash" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(128) NULL"))
            if "last_login_at" not in columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL"))
