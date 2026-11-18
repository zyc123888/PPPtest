"""track parent attempt for inherited V2 artifacts

Revision ID: 7f42c1d93a6b
Revises: 9a6639e3e4d1
Create Date: 2026-11-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7f42c1d93a6b"
down_revision: Union[str, None] = "9a6639e3e4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("case_generation_v2_artifacts") as batch_op:
        batch_op.add_column(sa.Column("parent_attempt_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_case_generation_v2_artifacts_parent_attempt_id", ["parent_attempt_id"])
        batch_op.create_foreign_key(
            "fk_case_generation_v2_artifacts_parent_attempt_id",
            "case_generation_v2_attempts",
            ["parent_attempt_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("case_generation_v2_artifacts") as batch_op:
        batch_op.drop_constraint("fk_case_generation_v2_artifacts_parent_attempt_id", type_="foreignkey")
        batch_op.drop_index("ix_case_generation_v2_artifacts_parent_attempt_id")
        batch_op.drop_column("parent_attempt_id")
