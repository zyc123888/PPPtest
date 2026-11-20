from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.db_migrate import BASELINE_REVISION, current_revision, migration_config, upgrade_database

# Keep the migration contract aligned with the actual Alembic graph.  The
# webhook-secret migration is the current head after the V2 artifact changes.
HEAD_REVISION = "a3b9e2c14f08"


def test_fresh_database_migrates_and_revision_column_downgrades_without_data_loss(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    config = migration_config(database_url)
    assert upgrade_database(database_url) == HEAD_REVISION

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users (username, role, status) VALUES ('migration-user', 'admin', 'ACTIVE')")
            )
        assert current_revision(engine) == HEAD_REVISION
        migrated_columns = {column["name"] for column in inspect(engine).get_columns("case_generation_v2_artifacts")}
        assert {"revision", "parent_attempt_id"}.issubset(migrated_columns)

        command.downgrade(config, BASELINE_REVISION)
        assert current_revision(engine) == BASELINE_REVISION
        downgraded_columns = {column["name"] for column in inspect(engine).get_columns("case_generation_v2_artifacts")}
        assert not {"revision", "parent_attempt_id"}.intersection(downgraded_columns)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT username FROM users WHERE username = 'migration-user'")) == "migration-user"

        command.upgrade(config, "head")
        assert current_revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_existing_unversioned_baseline_is_stamped_and_preserved(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    config = migration_config(database_url)
    assert upgrade_database(database_url) == HEAD_REVISION

    engine = create_engine(database_url)
    try:
        command.downgrade(config, BASELINE_REVISION)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
            connection.execute(
                text("INSERT INTO users (username, role, status) VALUES ('legacy-user', 'admin', 'ACTIVE')")
            )

        assert upgrade_database(database_url) == HEAD_REVISION
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT username FROM users WHERE username = 'legacy-user'")) == "legacy-user"
        assert current_revision(engine) == HEAD_REVISION
    finally:
        engine.dispose()


def test_unversioned_incompatible_database_is_rejected_without_stamping(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'incompatible.db'}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(80))"))
        with pytest.raises(RuntimeError, match="未版本化的非空数据库"):
            upgrade_database(database_url)
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_unversioned_database_with_post_baseline_column_is_rejected(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'partially-migrated.db'}"
    config = migration_config(database_url)
    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        command.downgrade(config, BASELINE_REVISION)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
            connection.execute(text("ALTER TABLE case_generation_v2_artifacts ADD COLUMN revision VARCHAR(64)"))

        with pytest.raises(RuntimeError, match="已包含后续迁移字段"):
            upgrade_database(database_url)
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_unversioned_database_missing_baseline_index_is_rejected(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing-index.db'}"
    config = migration_config(database_url)
    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        command.downgrade(config, BASELINE_REVISION)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
            connection.execute(text("DROP INDEX ix_users_id"))

        with pytest.raises(RuntimeError, match="missing index ix_users_id"):
            upgrade_database(database_url)
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_legacy_plaintext_variables_are_encrypted_before_migration_finishes(tmp_path: Path) -> None:
    from app.core.secrets import decrypt_secret

    database_url = f"sqlite:///{tmp_path / 'legacy-secrets.db'}"
    config = migration_config(database_url)
    command.upgrade(config, "ce41b2a38d0f")
    engine = create_engine(database_url)
    raw_variables = {"api_key": "legacy-secret-value"}
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO workspaces (name) VALUES ('legacy-secret-workspace')"))
            workspace_id = connection.scalar(text("SELECT id FROM workspaces WHERE name = 'legacy-secret-workspace'"))
            connection.execute(
                text(
                    "INSERT INTO projects (workspace_id, name, base_url, status, variables_json) "
                    "VALUES (:workspace_id, 'legacy-secret-project', 'http://example.test', 'ACTIVE', :variables)"
                ),
                {"workspace_id": workspace_id, "variables": json.dumps(raw_variables)},
            )

        assert upgrade_database(database_url) == HEAD_REVISION
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT variables_json, variables_encrypted FROM projects "
                    "WHERE name = 'legacy-secret-project'"
                )
            ).mappings().one()
        assert row["variables_json"] is None
        assert json.loads(decrypt_secret(row["variables_encrypted"])) == raw_variables
    finally:
        engine.dispose()


def test_empty_alembic_version_table_with_application_schema_is_rejected(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-version.db'}"
    upgrade_database(database_url)

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM alembic_version"))

        with pytest.raises(RuntimeError, match="没有有效 revision"):
            upgrade_database(database_url)
        assert current_revision(engine) is None
    finally:
        engine.dispose()
