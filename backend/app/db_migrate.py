from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import UniqueConstraint, create_engine, inspect, text
from sqlalchemy.engine import Engine

from app import models  # noqa: F401
from app.core.config import settings
from app.core.database import Base, engine as application_engine

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]


BASELINE_REVISION = "407d35f11aee"
MIGRATION_ADDED_COLUMNS = {
    "case_generation_v2_artifacts": {"revision", "parent_attempt_id"},
    "project_notification_settings": {"secret_encrypted"},
    "test_plan_runs": {"heartbeat_at"},
    "ui_batch_runs": {"heartbeat_at"},
    "test_runs": {"heartbeat_at"},
}
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def migration_config(database_url: str | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    config.set_main_option("sqlalchemy.url", (database_url or settings.database_url).replace("%", "%%"))
    return config


@contextmanager
def _migration_lock(db_engine: Engine):
    """Serialize concurrent migrations across multi-replica startup or local processes."""
    dialect = db_engine.dialect.name
    if dialect in {"mysql", "mariadb"}:
        with db_engine.connect() as connection:
            acquired = connection.scalar(text("SELECT GET_LOCK('omnitest_alembic_migrate', 60)"))
            if acquired != 1:
                raise RuntimeError("获取数据库迁移锁超时，可能有另一实例正在执行迁移")
            try:
                yield
            finally:
                try:
                    connection.execute(text("SELECT RELEASE_LOCK('omnitest_alembic_migrate')"))
                except Exception:
                    pass
        return

    db_path = db_engine.url.database
    if dialect == "sqlite" and db_path and db_path != ":memory:" and fcntl is not None:
        lock_name = hashlib.sha256(str(db_path).encode("utf-8")).hexdigest()[:12]
        lock_path = Path(tempfile.gettempdir()) / f"omnitest-alembic-{lock_name}.lock"
        with open(lock_path, "w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return

    yield


def _schema_gaps(db_engine: Engine) -> list[str]:
    inspector = inspect(db_engine)
    existing_tables = set(inspector.get_table_names())
    gaps: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            gaps.append(f"missing table {table_name}")
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        ignored = MIGRATION_ADDED_COLUMNS.get(table_name, set())
        for column in table.columns:
            if column.name not in existing_columns and column.name not in ignored:
                gaps.append(f"missing column {table_name}.{column.name}")

        existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        for index in table.indexes:
            if all(column.name in ignored for column in index.columns):
                continue
            if index.name not in existing_indexes:
                gaps.append(f"missing index {index.name}")

        expected_primary_key = tuple(column.name for column in table.primary_key.columns)
        actual_primary_key = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
        if expected_primary_key != actual_primary_key:
            gaps.append(f"primary key mismatch {table_name}")

        expected_unique_constraints = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        actual_unique_constraints = {
            tuple(constraint.get("column_names") or ())
            for constraint in inspector.get_unique_constraints(table_name)
        }
        if not expected_unique_constraints.issubset(actual_unique_constraints):
            gaps.append(f"unique constraint mismatch {table_name}")

        expected_foreign_keys = {
            (
                tuple(element.parent.name for element in constraint.elements),
                constraint.elements[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in table.foreign_key_constraints
            if not any(element.parent.name in ignored for element in constraint.elements)
        }
        actual_foreign_keys = {
            (
                tuple(foreign_key.get("constrained_columns") or ()),
                foreign_key.get("referred_table"),
                tuple(foreign_key.get("referred_columns") or ()),
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        if not expected_foreign_keys.issubset(actual_foreign_keys):
            gaps.append(f"foreign key mismatch {table_name}")
    return gaps


def _stamp_unversioned_database(config: Config, db_engine: Engine) -> None:
    inspector = inspect(db_engine)
    existing_tables = set(inspector.get_table_names())
    application_tables = existing_tables.intersection(Base.metadata.tables)
    revision = current_revision(db_engine)
    if revision is not None or not application_tables:
        return
    if "alembic_version" in existing_tables:
        raise RuntimeError(
            "数据库存在 alembic_version 表但没有有效 revision，无法安全判断当前结构版本；"
            "为避免重复执行迁移，启动已停止，请先核对数据库版本记录。"
        )

    partially_applied = [
        f"{table_name}.{column_name}"
        for table_name, column_names in MIGRATION_ADDED_COLUMNS.items()
        if table_name in existing_tables
        for column_name in column_names
        if column_name in {column["name"] for column in inspector.get_columns(table_name)}
    ]
    if partially_applied:
        raise RuntimeError(
            "未版本化的数据库已包含后续迁移字段，无法安全推断当前 revision："
            f"{', '.join(partially_applied)}；迁移已停止，请先核对数据库版本。"
        )

    gaps = _schema_gaps(db_engine)
    if gaps:
        sample = "; ".join(gaps[:12])
        suffix = f"（另有 {len(gaps) - 12} 项）" if len(gaps) > 12 else ""
        raise RuntimeError(
            "检测到未版本化的非空数据库，结构与 Alembic baseline 不匹配；"
            f"为避免自动改写业务库，迁移已停止：{sample}{suffix}"
        )
    command.stamp(config, BASELINE_REVISION)


def upgrade_database(database_url: str | None = None) -> str:
    url = database_url or settings.database_url
    config = migration_config(url)
    db_engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        with _migration_lock(db_engine):
            _stamp_unversioned_database(config, db_engine)
            command.upgrade(config, "head")
        return ScriptDirectory.from_config(config).get_current_head()
    finally:
        db_engine.dispose()


def current_revision(db_engine: Engine = application_engine) -> str | None:
    with db_engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def assert_database_current(db_engine: Engine = application_engine) -> str:
    config = migration_config()
    expected = ScriptDirectory.from_config(config).get_current_head()
    current = current_revision(db_engine)
    if current != expected:
        raise RuntimeError(
            "数据库迁移版本不匹配："
            f"current={current or '未初始化'}，expected={expected}。"
            "请先运行 `python -m app.db_migrate upgrade`。"
        )
    return current


def verify_schema_parity(database_url: str | None = None) -> None:
    """Assert Alembic head matches SQLAlchemy models with no pending autogenerate diff."""
    url = database_url or settings.database_url
    db_engine = create_engine(url, pool_pre_ping=True, future=True)
    try:
        assert_database_current(db_engine)
    finally:
        db_engine.dispose()
    command.check(migration_config(url))


def main() -> None:
    parser = argparse.ArgumentParser(description="OmniTest database schema migrations")
    parser.add_argument("action", choices=("upgrade", "check", "schema-check", "revision"))
    parser.add_argument("-m", "--message", help="Alembic revision message")
    args = parser.parse_args()
    if args.action == "upgrade":
        print(f"数据库迁移完成：{upgrade_database()}")
    elif args.action == "check":
        print(f"数据库迁移版本有效：{assert_database_current()}")
    elif args.action == "schema-check":
        verify_schema_parity()
        print("数据库迁移与 ORM 模型结构完全一致")
    else:
        if not args.message:
            parser.error("revision 操作必须提供 --message")
        assert_database_current()
        command.revision(migration_config(), message=args.message, autogenerate=True)


if __name__ == "__main__":
    main()
