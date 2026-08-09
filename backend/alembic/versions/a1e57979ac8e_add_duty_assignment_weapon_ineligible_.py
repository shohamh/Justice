"""add_duty_assignment_weapon_ineligible_cache

Revision ID: a1e57979ac8e
Revises: ffe105dad988
Create Date: 2026-08-08 18:17:09.326995

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1e57979ac8e'
down_revision: Union[str, Sequence[str], None] = 'ffe105dad988'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("weapon_ineligible", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("weapon_ineligible_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("weapon_ineligible_detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_duty_assignments_weapon_ineligible",
        "duty_assignments",
        ["id"],
        unique=False,
        postgresql_where=sa.text("weapon_ineligible = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_duty_assignments_weapon_ineligible", table_name="duty_assignments")
    op.drop_column("duty_assignments", "weapon_ineligible_detected_at")
    op.drop_column("duty_assignments", "weapon_ineligible_reason")
    op.drop_column("duty_assignments", "weapon_ineligible")
