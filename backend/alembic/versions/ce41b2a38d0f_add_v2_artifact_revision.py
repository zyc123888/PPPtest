"""add content revision to V2 artifacts

Revision ID: ce41b2a38d0f
Revises: 407d35f11aee
Create Date: 2026-11-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ce41b2a38d0f"
down_revision: Union[str, None] = "407d35f11aee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("case_generation_v2_artifacts") as batch_op:
        batch_op.add_column(sa.Column("revision", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("case_generation_v2_artifacts") as batch_op:
        batch_op.drop_column("revision")
