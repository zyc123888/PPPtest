"""encrypt notification webhook secret

Revision ID: a3b9e2c14f08
Revises: 7f42c1d93a6b
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from app.core.secrets import encrypt_secret, is_encryption_available


revision: str = "a3b9e2c14f08"
down_revision: Union[str, None] = "7f42c1d93a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("project_notification_settings")}
    if "secret_encrypted" not in columns:
        with op.batch_alter_table("project_notification_settings") as batch_op:
            batch_op.add_column(sa.Column("secret_encrypted", sa.Text(), nullable=True))

    pending = list(
        bind.execute(
            text(
                "SELECT id, secret FROM project_notification_settings "
                "WHERE secret IS NOT NULL AND secret != '' "
                "AND (secret_encrypted IS NULL OR secret_encrypted = '')"
            )
        ).mappings()
    )
    if pending and not is_encryption_available():
        raise RuntimeError("project_notification_settings 存在未加密 Webhook 密钥，但 APP_ENCRYPTION_KEY 不可用")
    for row in pending:
        encrypted = encrypt_secret(row["secret"])
        if encrypted:
            bind.execute(
                text(
                    "UPDATE project_notification_settings "
                    "SET secret_encrypted = :encrypted, secret = NULL WHERE id = :row_id"
                ),
                {"encrypted": encrypted, "row_id": row["id"]},
            )


def downgrade() -> None:
    pass
