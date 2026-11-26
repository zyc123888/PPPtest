"""add execution heartbeat_at columns

Revision ID: b7c4d8e21a09
Revises: a3b9e2c14f08
Create Date: 2026-11-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c4d8e21a09"
down_revision: Union[str, None] = "a3b9e2c14f08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HEARTBEAT_TABLES = (
    ("test_plan_runs", "ix_test_plan_runs_heartbeat_at"),
    ("ui_batch_runs", "ix_ui_batch_runs_heartbeat_at"),
    ("test_runs", "ix_test_runs_heartbeat_at"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, index_name in _HEARTBEAT_TABLES:
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        with op.batch_alter_table(table_name) as batch_op:
            if "heartbeat_at" not in columns:
                batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=False), nullable=True))
            if index_name not in indexes:
                batch_op.create_index(index_name, ["heartbeat_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, index_name in _HEARTBEAT_TABLES:
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        with op.batch_alter_table(table_name) as batch_op:
            if index_name in indexes:
                batch_op.drop_index(index_name)
            if "heartbeat_at" in columns:
                batch_op.drop_column("heartbeat_at")
