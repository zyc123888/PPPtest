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

    return schema_changes
