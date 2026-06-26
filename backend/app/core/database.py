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


def init_db() -> dict:
    from app import models  # noqa: F401

    inspector_before = inspect(engine)
    tables_before = set(inspector_before.get_table_names())

    Base.metadata.create_all(bind=engine)

    inspector_after = inspect(engine)
    tables_after = set(inspector_after.get_table_names())

    return {
        "database_backend": engine.url.get_backend_name(),
        "database_name": engine.url.database,
        "created_tables": sorted(tables_after - tables_before),
        "schema_changes": ensure_schema(engine),
    }


def ensure_schema(db_engine) -> list[str]:
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    schema_changes: list[str] = []

    def add_column_if_missing(connection, table_name: str, column_name: str, ddl: str) -> None:
        if table_name not in tables:
            return
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name not in columns:
            connection.execute(text(ddl))
            schema_changes.append(f"{table_name}.{column_name}")

    def create_index_if_missing(connection, index_name: str, ddl: str) -> None:
        try:
            connection.execute(text(ddl))
            schema_changes.append(f"index:{index_name}")
        except Exception:
            return

    def widen_mysql_varchar_if_needed(
        connection,
        table_name: str,
        column_name: str,
        min_length: int,
        ddl: str,
    ) -> None:
        if table_name not in tables or not db_engine.url.get_backend_name().startswith("mysql"):
            return
        columns = {col["name"]: col for col in inspector.get_columns(table_name)}
        column = columns.get(column_name)
        if column is None:
            return
        current_length = getattr(column["type"], "length", None)
        if current_length is not None and current_length < min_length:
            connection.execute(text(ddl))
            schema_changes.append(f"{table_name}.{column_name}:varchar({min_length})")

    with db_engine.begin() as connection:
        if settings.normalize_mysql_charset_on_bootstrap and db_engine.url.get_backend_name().startswith("mysql"):
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

        add_column_if_missing(
            connection,
            "projects",
            "workspace_id",
            "ALTER TABLE projects ADD COLUMN workspace_id INTEGER NULL",
        )
        add_column_if_missing(
            connection,
            "test_runs",
            "environment_id",
            "ALTER TABLE test_runs ADD COLUMN environment_id INTEGER NULL",
        )
        add_column_if_missing(
            connection,
            "test_runs",
            "plan_run_id",
            "ALTER TABLE test_runs ADD COLUMN plan_run_id INTEGER NULL",
        )
        add_column_if_missing(
            connection,
            "test_runs",
            "started_at",
            "ALTER TABLE test_runs ADD COLUMN started_at DATETIME NULL",
        )
        add_column_if_missing(
            connection,
            "test_runs",
            "finished_at",
            "ALTER TABLE test_runs ADD COLUMN finished_at DATETIME NULL",
        )
        add_column_if_missing(
            connection,
            "test_plan_runs",
            "report_json_path",
            "ALTER TABLE test_plan_runs ADD COLUMN report_json_path VARCHAR(512) NULL",
        )
        add_column_if_missing(
            connection,
            "test_plan_runs",
            "report_junit_path",
            "ALTER TABLE test_plan_runs ADD COLUMN report_junit_path VARCHAR(512) NULL",
        )
        add_column_if_missing(
            connection,
            "test_plan_runs",
            "report_generated_at",
            "ALTER TABLE test_plan_runs ADD COLUMN report_generated_at DATETIME NULL",
        )
        add_column_if_missing(
            connection,
            "users",
            "password_hash",
            "ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL",
        )
        widen_mysql_varchar_if_needed(
            connection,
            "users",
            "password_hash",
            255,
            "ALTER TABLE users MODIFY COLUMN password_hash VARCHAR(255) NULL",
        )
        add_column_if_missing(
            connection,
            "users",
            "last_login_at",
            "ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL",
        )
        extra_columns = [
            ("projects", "created_by", "ALTER TABLE projects ADD COLUMN created_by INTEGER NULL"),
            ("projects", "updated_by", "ALTER TABLE projects ADD COLUMN updated_by INTEGER NULL"),
            ("api_cases", "priority", "ALTER TABLE api_cases ADD COLUMN priority VARCHAR(20) NULL"),
            ("api_cases", "status", "ALTER TABLE api_cases ADD COLUMN status VARCHAR(20) NULL"),
            ("api_cases", "review_status", "ALTER TABLE api_cases ADD COLUMN review_status VARCHAR(20) NULL"),
            ("api_cases", "version_no", "ALTER TABLE api_cases ADD COLUMN version_no VARCHAR(30) NULL"),
            ("api_cases", "review_note", "ALTER TABLE api_cases ADD COLUMN review_note TEXT NULL"),
            ("api_cases", "folder_path", "ALTER TABLE api_cases ADD COLUMN folder_path VARCHAR(255) NULL"),
            ("api_cases", "tags_json", "ALTER TABLE api_cases ADD COLUMN tags_json JSON NULL"),
            ("api_cases", "assertions_json", "ALTER TABLE api_cases ADD COLUMN assertions_json JSON NULL"),
            ("api_cases", "created_by", "ALTER TABLE api_cases ADD COLUMN created_by INTEGER NULL"),
            ("api_cases", "updated_by", "ALTER TABLE api_cases ADD COLUMN updated_by INTEGER NULL"),
            ("api_cases", "updated_at", "ALTER TABLE api_cases ADD COLUMN updated_at DATETIME NULL"),
            ("ui_cases", "priority", "ALTER TABLE ui_cases ADD COLUMN priority VARCHAR(20) NULL"),
            ("ui_cases", "status", "ALTER TABLE ui_cases ADD COLUMN status VARCHAR(20) NULL"),
            ("ui_cases", "review_status", "ALTER TABLE ui_cases ADD COLUMN review_status VARCHAR(20) NULL"),
            ("ui_cases", "version_no", "ALTER TABLE ui_cases ADD COLUMN version_no VARCHAR(30) NULL"),
            ("ui_cases", "review_note", "ALTER TABLE ui_cases ADD COLUMN review_note TEXT NULL"),
            ("ui_cases", "folder_path", "ALTER TABLE ui_cases ADD COLUMN folder_path VARCHAR(255) NULL"),
            ("ui_cases", "tags_json", "ALTER TABLE ui_cases ADD COLUMN tags_json JSON NULL"),
            ("ui_cases", "assertions_json", "ALTER TABLE ui_cases ADD COLUMN assertions_json JSON NULL"),
            ("ui_cases", "created_by", "ALTER TABLE ui_cases ADD COLUMN created_by INTEGER NULL"),
            ("ui_cases", "updated_by", "ALTER TABLE ui_cases ADD COLUMN updated_by INTEGER NULL"),
            ("ui_cases", "updated_at", "ALTER TABLE ui_cases ADD COLUMN updated_at DATETIME NULL"),
            ("performance_cases", "folder_path", "ALTER TABLE performance_cases ADD COLUMN folder_path VARCHAR(255) NULL"),
            ("performance_cases", "priority", "ALTER TABLE performance_cases ADD COLUMN priority VARCHAR(20) NULL"),
            ("performance_cases", "status", "ALTER TABLE performance_cases ADD COLUMN status VARCHAR(20) NULL"),
            ("performance_cases", "review_status", "ALTER TABLE performance_cases ADD COLUMN review_status VARCHAR(20) NULL"),
            ("performance_cases", "version_no", "ALTER TABLE performance_cases ADD COLUMN version_no VARCHAR(30) NULL"),
            ("performance_cases", "review_note", "ALTER TABLE performance_cases ADD COLUMN review_note TEXT NULL"),
            ("performance_cases", "tags_json", "ALTER TABLE performance_cases ADD COLUMN tags_json JSON NULL"),
            ("performance_cases", "headers_json", "ALTER TABLE performance_cases ADD COLUMN headers_json JSON NULL"),
            ("performance_cases", "body_json", "ALTER TABLE performance_cases ADD COLUMN body_json JSON NULL"),
            ("performance_cases", "expected_status", "ALTER TABLE performance_cases ADD COLUMN expected_status INTEGER NULL"),
            ("performance_cases", "concurrency", "ALTER TABLE performance_cases ADD COLUMN concurrency INTEGER NULL"),
            ("performance_cases", "total_requests", "ALTER TABLE performance_cases ADD COLUMN total_requests INTEGER NULL"),
            ("performance_cases", "max_avg_response_ms", "ALTER TABLE performance_cases ADD COLUMN max_avg_response_ms INTEGER NULL"),
            ("performance_cases", "max_p95_response_ms", "ALTER TABLE performance_cases ADD COLUMN max_p95_response_ms INTEGER NULL"),
            ("performance_cases", "max_error_rate", "ALTER TABLE performance_cases ADD COLUMN max_error_rate FLOAT NULL"),
            ("performance_cases", "created_by", "ALTER TABLE performance_cases ADD COLUMN created_by INTEGER NULL"),
            ("performance_cases", "updated_by", "ALTER TABLE performance_cases ADD COLUMN updated_by INTEGER NULL"),
            ("performance_cases", "updated_at", "ALTER TABLE performance_cases ADD COLUMN updated_at DATETIME NULL"),
            ("defect_records", "project_id", "ALTER TABLE defect_records ADD COLUMN project_id INTEGER NULL"),
            ("defect_records", "run_id", "ALTER TABLE defect_records ADD COLUMN run_id INTEGER NULL"),
            ("defect_records", "plan_run_id", "ALTER TABLE defect_records ADD COLUMN plan_run_id INTEGER NULL"),
            ("defect_records", "platform", "ALTER TABLE defect_records ADD COLUMN platform VARCHAR(30) NULL"),
            ("defect_records", "external_key", "ALTER TABLE defect_records ADD COLUMN external_key VARCHAR(80) NULL"),
            ("defect_records", "external_url", "ALTER TABLE defect_records ADD COLUMN external_url VARCHAR(512) NULL"),
            ("defect_records", "status", "ALTER TABLE defect_records ADD COLUMN status VARCHAR(30) NULL"),
            ("defect_records", "severity", "ALTER TABLE defect_records ADD COLUMN severity VARCHAR(20) NULL"),
            ("defect_records", "summary", "ALTER TABLE defect_records ADD COLUMN summary TEXT NULL"),
            ("defect_records", "created_by", "ALTER TABLE defect_records ADD COLUMN created_by INTEGER NULL"),
            ("defect_records", "updated_by", "ALTER TABLE defect_records ADD COLUMN updated_by INTEGER NULL"),
            ("defect_records", "updated_at", "ALTER TABLE defect_records ADD COLUMN updated_at DATETIME NULL"),
            ("case_generation_jobs", "progress_json", "ALTER TABLE case_generation_jobs ADD COLUMN progress_json JSON NULL"),
            ("environments", "auth_config_json", "ALTER TABLE environments ADD COLUMN auth_config_json JSON NULL"),
            ("environments", "created_by", "ALTER TABLE environments ADD COLUMN created_by INTEGER NULL"),
            ("environments", "updated_by", "ALTER TABLE environments ADD COLUMN updated_by INTEGER NULL"),
            ("environments", "updated_at", "ALTER TABLE environments ADD COLUMN updated_at DATETIME NULL"),
            ("test_plans", "created_by", "ALTER TABLE test_plans ADD COLUMN created_by INTEGER NULL"),
            ("test_plans", "updated_by", "ALTER TABLE test_plans ADD COLUMN updated_by INTEGER NULL"),
            ("test_plan_cases", "case_snapshot_json", "ALTER TABLE test_plan_cases ADD COLUMN case_snapshot_json JSON NULL"),
            ("test_plan_cases", "created_by", "ALTER TABLE test_plan_cases ADD COLUMN created_by INTEGER NULL"),
            ("test_plan_runs", "error_type", "ALTER TABLE test_plan_runs ADD COLUMN error_type VARCHAR(30) NULL"),
            ("test_plan_runs", "retry_count", "ALTER TABLE test_plan_runs ADD COLUMN retry_count INTEGER NULL"),
            ("test_runs", "error_type", "ALTER TABLE test_runs ADD COLUMN error_type VARCHAR(30) NULL"),
            ("test_runs", "exit_code", "ALTER TABLE test_runs ADD COLUMN exit_code INTEGER NULL"),
            ("test_runs", "timeout_seconds", "ALTER TABLE test_runs ADD COLUMN timeout_seconds INTEGER NULL"),
            ("test_runs", "retry_count", "ALTER TABLE test_runs ADD COLUMN retry_count INTEGER NULL"),
            ("test_runs", "max_retries", "ALTER TABLE test_runs ADD COLUMN max_retries INTEGER NULL"),
            ("test_runs", "stdout_text", "ALTER TABLE test_runs ADD COLUMN stdout_text TEXT NULL"),
            ("test_runs", "stderr_text", "ALTER TABLE test_runs ADD COLUMN stderr_text TEXT NULL"),
            ("test_runs", "artifacts_json", "ALTER TABLE test_runs ADD COLUMN artifacts_json JSON NULL"),
            ("test_runs", "step_results_json", "ALTER TABLE test_runs ADD COLUMN step_results_json JSON NULL"),
            ("case_generation_jobs", "task_id", "ALTER TABLE case_generation_jobs ADD COLUMN task_id VARCHAR(120) NULL"),
        ]
        for table_name, column_name, ddl in extra_columns:
            add_column_if_missing(connection, table_name, column_name, ddl)

        create_index_if_missing(
            connection,
            "idx_test_runs_project_status",
            "CREATE INDEX IF NOT EXISTS idx_test_runs_project_status ON test_runs(project_id, status)",
        )
        create_index_if_missing(
            connection,
            "idx_test_runs_plan_run_id",
            "CREATE INDEX IF NOT EXISTS idx_test_runs_plan_run_id ON test_runs(plan_run_id)",
        )
        create_index_if_missing(
            connection,
            "idx_test_plan_runs_project_status",
            "CREATE INDEX IF NOT EXISTS idx_test_plan_runs_project_status ON test_plan_runs(project_id, status)",
        )
        create_index_if_missing(
            connection,
            "idx_execution_logs_run_id",
            "CREATE INDEX IF NOT EXISTS idx_execution_logs_run_id ON execution_logs(run_id)",
        )
        create_index_if_missing(
            connection,
            "idx_execution_artifacts_run_id",
            "CREATE INDEX IF NOT EXISTS idx_execution_artifacts_run_id ON execution_artifacts(run_id)",
        )
        create_index_if_missing(
            connection,
            "idx_execution_steps_run_status",
            "CREATE INDEX IF NOT EXISTS idx_execution_steps_run_status ON execution_steps(run_id, status)",
        )
        create_index_if_missing(
            connection,
            "idx_defect_records_project_status",
            "CREATE INDEX IF NOT EXISTS idx_defect_records_project_status ON defect_records(project_id, status)",
        )

    return schema_changes
