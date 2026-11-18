"""encrypt legacy project and environment variable pools

Revision ID: 9a6639e3e4d1
Revises: ce41b2a38d0f
Create Date: 2026-11-10
"""
import json
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "9a6639e3e4d1"
down_revision: Union[str, None] = "ce41b2a38d0f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _encrypt_legacy_values(table_name: str) -> None:
    from app.core.secrets import encrypt_secret, is_encryption_available

    connection = op.get_bind()
    pending = list(
        connection.execute(
            text(
                f"SELECT id, variables_json FROM {table_name} "
                "WHERE variables_encrypted IS NULL AND variables_json IS NOT NULL"
            )
        ).mappings()
    )
    if pending and not is_encryption_available():
        raise RuntimeError(f"{table_name} 存在未加密变量，但 APP_ENCRYPTION_KEY 不可用；迁移已停止")

    for row in pending:
        raw_value = row["variables_json"]
        if raw_value in (None, "", {}, []):
            continue
        serialized = raw_value if isinstance(raw_value, str) else json.dumps(raw_value, ensure_ascii=False)
        encrypted = encrypt_secret(serialized)
        if not encrypted:
            raise RuntimeError(f"{table_name}.variables_json 加密失败；迁移已停止")
        connection.execute(
            text(
                f"UPDATE {table_name} SET variables_encrypted = :encrypted, variables_json = NULL "
                "WHERE id = :row_id"
            ),
            {"encrypted": encrypted, "row_id": row["id"]},
        )


def upgrade() -> None:
    _encrypt_legacy_values("projects")
    _encrypt_legacy_values("environments")


def downgrade() -> None:
    # The encrypted storage format remains valid when moving the schema revision backward.
    pass
