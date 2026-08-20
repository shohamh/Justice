"""create role_deputies table

Revision ID: bccac29dd1b5
Revises: b7c8d9e0f1a2
Create Date: 2026-08-20 17:21:17.422185

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'bccac29dd1b5'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_deputies",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), primary_key=True,
        ),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deputy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role", sa.Enum("commander", "duty_manager", name="deputy_role"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_role_deputy_principal"),
        sa.ForeignKeyConstraint(["deputy_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_role_deputy_deputy"),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_role_deputy_created_by"),
        sa.UniqueConstraint("principal_id", "deputy_id", "role", name="uq_role_deputy"),
        sa.CheckConstraint("end_date >= start_date", name="ck_role_deputy_date_range"),
    )


def downgrade() -> None:
    op.drop_table("role_deputies")
    op.execute("DROP TYPE IF EXISTS deputy_role")
